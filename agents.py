from __future__ import annotations

import json
import operator
import os
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal, Sequence

from pydantic import BaseModel
from typing_extensions import TypedDict

from langchain_core.documents import Document
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder, PromptTemplate
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.store.base import BaseStore
from neo4j import GraphDatabase

try:
    from langchain_community.chains.graph_qa.cypher import GraphCypherQAChain
except ImportError:
    from langchain.chains import GraphCypherQAChain

from config import (
    BASE_DIR,
    COMPANY_DOC_PATH,
    MEMBERS,
    MEMORY_NODE,
    PROJECT_ROOT,
    REVIEW_NODE,
    CompetitorAnalysis,
    CustomerInformation,
    ProductInformation,
    SalesData,
    SessionLocal,
    get_coder_llm,
    get_cypher_llm,
    get_embeddings,
    get_graph_llm,
    get_main_llm,
    get_router_llm,
    repl,
    require_env,
)
from hitl import normalize_review_decision
from memory import (
    build_knowledge_question,
    get_checkpointer,
    get_latest_user_message,
    get_long_term_memories,
    get_memory_namespace,
    get_memory_store,
    with_memory_context,
)


class AddSaleSchema(BaseModel):
    product_id: int
    employee_id: int
    customer_id: int
    sale_date: str
    quantity: int
    amount: float
    discount: float


class DeleteSaleSchema(BaseModel):
    sales_id: int


class UpdateSaleSchema(BaseModel):
    sales_id: int
    quantity: int
    amount: float


class QuerySalesSchema(BaseModel):
    sales_id: int


@tool(args_schema=AddSaleSchema)
def add_sale(
    product_id: int,
    employee_id: int,
    customer_id: int,
    sale_date: str,
    quantity: int,
    amount: float,
    discount: float,
):
    """添加销售记录"""
    session = SessionLocal()
    try:
        new_sale = SalesData(
            product_id=product_id,
            employee_id=employee_id,
            customer_id=customer_id,
            sale_date=sale_date,
            quantity=quantity,
            amount=amount,
            discount=discount,
        )
        session.add(new_sale)
        session.commit()
        return {"messages": ["Sale record added successfully."]}
    except Exception as exc:
        session.rollback()
        return {"messages": [f"Add failed: {exc}"]}
    finally:
        session.close()


@tool(args_schema=DeleteSaleSchema)
def delete_sale(sales_id: int):
    """删除销售记录"""
    session = SessionLocal()
    try:
        sale = session.query(SalesData).filter(SalesData.sales_id == sales_id).first()
        if not sale:
            return {"messages": [f"Sale record not found: {sales_id}"]}
        session.delete(sale)
        session.commit()
        return {"messages": ["Sale record deleted successfully."]}
    except Exception as exc:
        session.rollback()
        return {"messages": [f"Delete failed: {exc}"]}
    finally:
        session.close()


@tool(args_schema=UpdateSaleSchema)
def update_sale(sales_id: int, quantity: int, amount: float):
    """更新销售记录"""
    session = SessionLocal()
    try:
        sale = session.query(SalesData).filter(SalesData.sales_id == sales_id).first()
        if not sale:
            return {"messages": [f"Sale record not found: {sales_id}"]}
        sale.quantity = quantity
        sale.amount = amount
        session.commit()
        return {"messages": ["Sale record updated successfully."]}
    except Exception as exc:
        session.rollback()
        return {"messages": [f"Update failed: {exc}"]}
    finally:
        session.close()


@tool(args_schema=QuerySalesSchema)
def query_sales(sales_id: int):
    """查询销售记录"""
    session = SessionLocal()
    try:
        sale = session.query(SalesData).filter(SalesData.sales_id == sales_id).first()
        if not sale:
            return {"messages": [f"Sale record not found: {sales_id}"]}
        return {
            "sales_id": sale.sales_id,
            "product_id": sale.product_id,
            "employee_id": sale.employee_id,
            "customer_id": sale.customer_id,
            "sale_date": sale.sale_date,
            "quantity": sale.quantity,
            "amount": sale.amount,
            "discount": sale.discount,
        }
    except Exception as exc:
        return {"messages": [f"Query failed: {exc}"]}
    finally:
        session.close()


@tool
def python_repl(
    code: Annotated[str, "The Python code to execute to generate a chart or compute a result."],
):
    """执行Python代码"""
    try:
        chart_dir = BASE_DIR / "artifacts" / "charts"
        chart_dir.mkdir(parents=True, exist_ok=True)
        chart_path = chart_dir / f"chart_{uuid.uuid4().hex}.png"
        bootstrap = (
            "import os\n"
            "os.environ['MPLBACKEND'] = 'Agg'\n"
            "import matplotlib\n"
            "matplotlib.use('Agg', force=True)\n"
            "import matplotlib.pyplot as plt\n"
            "plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'Noto Sans CJK SC', 'Arial Unicode MS', 'DejaVu Sans']\n"
            "plt.rcParams['axes.unicode_minus'] = False\n"
        )
        safe_code = code.replace(
            "plt.show()",
            "print('plt.show() skipped in server mode')",
        )
        save_chart = (
            "\n"
            f"_chart_output_path = r'''{chart_path}'''\n"
            "if 'plt' in globals() and plt.get_fignums():\n"
            "    plt.savefig(_chart_output_path, dpi=200, bbox_inches='tight')\n"
            "    print(f'Saved chart: {_chart_output_path}')\n"
            "    plt.close('all')\n"
        )
        result = repl.run(f"{bootstrap}\n{safe_code}\n{save_chart}")
    except BaseException as exc:
        return f"Failed to execute. Error: {repr(exc)}"
    return (
        "Successfully executed:\n```python\n"
        f"{code}\n"
        "```\n"
        f"Stdout: {result}\n\n"
        f"Chart artifact: {chart_path.as_posix()}\n\n"
        "If you have completed all tasks, respond with FINAL ANSWER."
    )


def create_agent(llm, tools, system_message: str):
    """创建工具代理链"""
    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "You are a helpful AI assistant, collaborating with other assistants. "
                "Use the provided tools to progress towards answering the question. "
                "If you are unable to fully answer, that is OK, another assistant with different "
                "tools will help where you left off. Execute what you can to make progress. "
                "If you or any of the other assistants have the final answer or deliverable, "
                "prefix your response with FINAL ANSWER so the team knows to stop. "
                "You have access to the following tools: {tool_names}.\n{system_message}",
            ),
            MessagesPlaceholder(variable_name="messages"),
        ]
    )
    prompt = prompt.partial(system_message=system_message)
    prompt = prompt.partial(tool_names=", ".join(tool_def.name for tool_def in tools))
    return prompt | llm.bind_tools(tools)


class ToolAgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], operator.add]


def build_tool_agent_graph(agent, agent_name: str, tools):
    """构建子代理图"""
    tool_executor = ToolNode(tools)

    def agent_step(state: ToolAgentState):
        """执行代理一步"""
        result = agent.invoke({"messages": state["messages"]})
        if isinstance(result, AIMessage):
            message = AIMessage(**result.dict(exclude={"type", "name"}), name=agent_name)
        else:
            message = result
        return {"messages": [message]}

    def route(state: ToolAgentState):
        """判断是否调工具"""
        last_message = state["messages"][-1]
        if getattr(last_message, "tool_calls", None):
            return "call_tool"
        return END

    workflow = StateGraph(ToolAgentState)
    workflow.add_node("agent", agent_step)
    workflow.add_node("call_tool", tool_executor)
    workflow.add_conditional_edges("agent", route, {"call_tool": "call_tool", END: END})
    workflow.add_edge("call_tool", "agent")
    workflow.set_entry_point("agent")
    return workflow.compile()


@lru_cache(maxsize=1)
def get_sqler_app():
    """获取SQL代理图"""
    tools = [add_sale, delete_sale, update_sale, query_sales]
    agent = create_agent(
        get_main_llm(),
        tools,
        system_message=(
            "You manage the structured sales database. "
            "Provide accurate structured data for the coder agent to use. "
            "Do not output plotting code. Do not claim chart is generated. "
            "If a chart is requested, return clean data summary only and hand off to coder."
        ),
    )
    return build_tool_agent_graph(agent, "sqler", tools)


@lru_cache(maxsize=1)
def get_coder_app():
    """获取代码代理图"""
    tools = [python_repl]
    agent = create_agent(
        get_coder_llm(),
        tools,
        system_message=(
            "Act as a data analyst. When the user asks for a chart, use python_repl to create "
            "a real matplotlib figure from the provided data. Do not return placeholder images "
            "or tell the user to run code manually. After the tool runs, summarize the chart and "
            "mention that the chart artifact has been generated."
        ),
    )
    return build_tool_agent_graph(agent, "coder", tools)


def sqler(
    state: MessagesState,
    config: RunnableConfig,
    *,
    store: BaseStore | None = None,
):
    """执行SQL代理"""
    result = get_sqler_app().invoke(
        {"messages": with_memory_context(state["messages"], config, store)}
    )
    final_message = result["messages"][-1]
    return {"messages": [HumanMessage(content=final_message.content, name="sqler")]}


def coder(
    state: MessagesState,
    config: RunnableConfig,
    *,
    store: BaseStore | None = None,
):
    """执行代码代理"""
    result = get_coder_app().invoke(
        {"messages": with_memory_context(state["messages"], config, store)}
    )
    final_message = result["messages"][-1]
    return {"messages": [HumanMessage(content=final_message.content, name="coder")]}


def chat(
    state: MessagesState,
    config: RunnableConfig,
    *,
    store: BaseStore | None = None,
):
    """执行聊天代理"""
    response = get_main_llm().invoke(with_memory_context(state["messages"], config, store))
    return {"messages": [HumanMessage(content=response.content, name="chat")]}


def resolve_company_doc_path() -> Path:
    """解析语料路径"""
    configured = COMPANY_DOC_PATH
    if configured:
        path = Path(configured)
        return path if path.is_absolute() else (PROJECT_ROOT / path).resolve()
    return (PROJECT_ROOT / "doc" / "company.txt").resolve()


def load_company_documents() -> list[Document]:
    """加载企业语料"""
    company_path = resolve_company_doc_path()
    if not company_path.exists():
        raise FileNotFoundError(
            "Company corpus not found. Set COMPANY_DOC_PATH or place the file at "
            f"{company_path}"
        )
    content = company_path.read_text(encoding="utf-8")
    return [Document(page_content=content)]


@lru_cache(maxsize=1)
def get_neo4j_graph():
    """创建Neo4j连接"""
    from langchain_community.graphs import Neo4jGraph

    return Neo4jGraph(
        url=require_env("NEO4J_URL"),
        username=require_env("NEO4J_USERNAME"),
        password=require_env("NEO4J_PASSWORD"),
        database=os.getenv("NEO4J_DATABASE", "neo4j"),
    )


@lru_cache(maxsize=1)
def get_cypher_chain():
    """构建Cypher问答链"""
    graph = get_neo4j_graph()

    cypher_prompt = PromptTemplate(
        template=(
            "You are an expert at generating Cypher queries for Neo4j.\n"
            "Use the following schema to generate a Cypher query that answers the given question.\n"
            "Make the query flexible by using case-insensitive matching and partial string matching where appropriate.\n"
            "Schema:\n{schema}\n\n"
            "Question: {question}\n\n"
            "Cypher Query:"
        ),
        input_variables=["schema", "question"],
    )
    qa_prompt = PromptTemplate(
        template=(
            "You are an assistant for question-answering tasks.\n"
            "Use the following Cypher query results to answer the question. "
            "If you do not know the answer, say that you do not know.\n"
            "Use three sentences maximum and keep the answer concise.\n\n"
            "Question: {question}\n"
            "Query Results: {context}\n\n"
            "Answer:"
        ),
        input_variables=["question", "context"],
    )

    return GraphCypherQAChain.from_llm(
        graph=graph,
        cypher_llm=get_cypher_llm(),
        qa_llm=get_graph_llm(),
        cypher_prompt=cypher_prompt,
        qa_prompt=qa_prompt,
        validate_cypher=True,
        allow_dangerous_requests=True,
    )


def graph_kg(
    state: MessagesState,
    config: RunnableConfig,
    *,
    store: BaseStore | None = None,
):
    """执行图谱问答"""
    question = build_knowledge_question(state["messages"][-1].content, config, store)
    if is_education_cooperation_question(question):
        return {"messages": [HumanMessage(content=query_education_partners(question), name="graph_kg")]}
    if is_company_list_question(question):
        return {"messages": [HumanMessage(content=query_company_names(), name="graph_kg")]}
    try:
        response = get_cypher_chain().invoke(question)
        result = response["result"] if isinstance(response, dict) else str(response)
        return {"messages": [HumanMessage(content=result, name="graph_kg")]}
    except Exception as exc:
        if False:
            fallback = vec_kg(state, config, store=store)
            fallback_message = fallback["messages"][-1].content
            return {
                "messages": [
                    HumanMessage(
                        content=(
                            "graph_kg 当前模型不支持结构化输出，已自动切换 vec_kg：\n"
                            f"{fallback_message}"
                        ),
                        name="graph_kg",
                    )
                ]
            }
        raise


@lru_cache(maxsize=1)
def get_vectorstore():
    """创建向量数据库"""
    try:
        from langchain_milvus import Milvus
    except ImportError as exc:
        raise ImportError(
            "langchain_milvus is required for vec_kg. Install it before running this agent."
        ) from exc

    documents = load_company_documents()
    splitter = RecursiveCharacterTextSplitter(chunk_size=250, chunk_overlap=30)
    splits = splitter.split_documents(documents)

    return Milvus.from_documents(
        documents=splits,
        collection_name=os.getenv("MILVUS_COLLECTION", "company_milvus"),
        embedding=get_embeddings(),
        connection_args={
            "uri": require_env("MILVUS_URI"),
            "user": require_env("MILVUS_USER"),
            "password": require_env("MILVUS_PASSWORD"),
        },
    )


def build_vec_rag_chain():
    """构建向量问答链"""
    prompt = PromptTemplate(
        template=(
            "You are an assistant for question-answering tasks.\n"
            "Here is relevant durable user memory from prior threads:\n"
            "{memory_context}\n\n"
            "Use the following pieces of retrieved context to answer the question. "
            "If you do not know the answer, say that you do not know.\n"
            "Use three sentences maximum and keep the answer concise.\n\n"
            "Question: {question}\n"
            "Context: {context}\n"
            "Answer:"
        ),
        input_variables=["question", "context", "memory_context"],
    )
    return prompt | get_graph_llm() | StrOutputParser()


def format_documents(documents: Sequence[Document]) -> str:
    """拼接检索文档"""
    return "\n\n".join(document.page_content for document in documents)


def vec_kg(
    state: MessagesState,
    config: RunnableConfig,
    *,
    store: BaseStore | None = None,
):
    """执行向量检索问答"""
    question = state["messages"][-1].content
    retriever = get_vectorstore().as_retriever(
        search_kwargs={"k": int(os.getenv("VECTOR_TOP_K", "3"))}
    )
    docs = retriever.invoke(question)
    memory_context = "\n".join(get_long_term_memories(config, store)) or "None"
    generation = build_vec_rag_chain().invoke(
        {
            "context": format_documents(docs),
            "question": question,
            "memory_context": memory_context,
        }
    )
    return {"messages": [HumanMessage(content=generation, name="vec_kg")]}


def is_company_list_question(question: str) -> bool:
    """识别公司列表问题"""
    text = question or ""
    return "公司" in text and any(keyword in text for keyword in ("哪些", "都有哪些", "有什么"))


def query_company_names() -> str:
    """直接查询公司节点"""
    driver = GraphDatabase.driver(
        require_env("NEO4J_URL"),
        auth=(require_env("NEO4J_USERNAME"), require_env("NEO4J_PASSWORD")),
    )
    try:
        with driver.session(database=os.getenv("NEO4J_DATABASE", "neo4j")) as session:
            rows = session.run(
                "MATCH (c:Company) RETURN c.name AS name ORDER BY c.name"
            ).data()
    finally:
        driver.close()
    names = [row["name"] for row in rows]
    if not names:
        return "当前 Neo4j 图数据库中没有查询到 Company 节点。"
    return "数据库中的公司包括：" + "、".join(names) + "。"


def is_company_list_question(question: str) -> bool:
    """识别公司列表问题"""
    text = question or ""
    list_patterns = ("有哪些公司", "都有哪些公司", "哪些公司", "公司有哪些", "公司包括")
    relation_markers = ("与", "和", "合作", "建立")
    return any(pattern in text for pattern in list_patterns) and not any(
        marker in text for marker in relation_markers
    )


def is_education_cooperation_question(question: str) -> bool:
    """识别教育合作问题"""
    text = question or ""
    return "公司" in text and "合作" in text and any(
        keyword in text for keyword in ("教育机构", "大学", "学院", "研究机构")
    )


def extract_company_from_question(question: str) -> str | None:
    """提取问题中的公司名"""
    known_companies = {
        "华为技术有限公司": "华为技术有限公司",
        "华为": "华为技术有限公司",
        "小米科技有限责任公司": "小米科技有限责任公司",
        "小米": "小米科技有限责任公司",
        "苹果公司": "苹果公司",
        "苹果": "苹果公司",
        "Adobe": "Adobe",
        "微软": "微软",
        "英特尔": "英特尔",
        "谷歌": "谷歌",
    }
    for alias, canonical in known_companies.items():
        if alias in question:
            return canonical
    return None


def query_company_names() -> str:
    """直接查询公司节点"""
    driver = GraphDatabase.driver(
        require_env("NEO4J_URL"),
        auth=(require_env("NEO4J_USERNAME"), require_env("NEO4J_PASSWORD")),
    )
    try:
        with driver.session(database=os.getenv("NEO4J_DATABASE", "neo4j")) as session:
            rows = session.run(
                "MATCH (c:Company) RETURN c.name AS name ORDER BY c.name"
            ).data()
    finally:
        driver.close()
    names = [row["name"] for row in rows]
    if not names:
        return "当前 Neo4j 图数据库中没有查询到 Company 节点。"
    return "数据库中的公司包括：" + "、".join(names) + "。"


def query_education_partners(question: str) -> str:
    """直接查询教育合作对象"""
    company = extract_company_from_question(question)
    if not company:
        return "我没有从问题中识别出明确的公司名称，请提供公司全称或常用简称。"
    driver = GraphDatabase.driver(
        require_env("NEO4J_URL"),
        auth=(require_env("NEO4J_USERNAME"), require_env("NEO4J_PASSWORD")),
    )
    try:
        with driver.session(database=os.getenv("NEO4J_DATABASE", "neo4j")) as session:
            rows = session.run(
                """
                MATCH (c:Company {name: $company})-[:COOPERATES_WITH]->(target)
                WHERE target:University OR target:ResearchInstitution OR target:Organization
                RETURN target.name AS name, labels(target) AS labels
                ORDER BY target.name
                """,
                company=company,
            ).data()
    finally:
        driver.close()
    names = [row["name"] for row in rows]
    if not names:
        return f"当前图数据库中没有查询到 {company} 与教育机构建立合作的记录。"
    return f"{company} 建立合作的教育/研究机构包括：" + "、".join(names) + "。"


class AgentState(MessagesState):
    next: str
    pending_worker: str | None
    approval_request: str | None
    review_decision: str | None
    review_notes: str | None


class Router(TypedDict):
    next: Literal["chat", "coder", "sqler", "graph_kg", "vec_kg", "FINISH"]


def parse_router_choice(raw_text: str) -> str:
    """解析路由模型输出"""
    allowed = {"chat", "coder", "sqler", "graph_kg", "vec_kg", "FINISH"}
    text = (raw_text or "").strip()

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            candidate = str(parsed.get("next", "")).strip()
            if candidate in allowed:
                return candidate
    except json.JSONDecodeError:
        pass

    for candidate in allowed:
        if candidate in text:
            return candidate
    return "chat"


DB_WRITE_KEYWORDS = (
    "delete",
    "remove",
    "drop",
    "update",
    "modify",
    "删除",
    "删掉",
    "清除",
    "更新",
    "修改",
    "改写",
)

CHART_KEYWORDS = (
    "chart",
    "plot",
    "bar chart",
    "line chart",
    "matplotlib",
    "visualize",
    "graph",
    "柱状图",
    "折线图",
    "可视化",
    "画图",
    "绘图",
)


def needs_chart_generation(user_request: str) -> bool:
    """判断是否为图表生成请求"""
    text = user_request.lower()
    return any(keyword in text for keyword in CHART_KEYWORDS)


def worker_response_count(state: AgentState) -> int:
    """统计当前线程内 worker 已响应次数"""
    count = 0
    for message in state["messages"]:
        name = getattr(message, "name", "")
        if name in MEMBERS:
            count += 1
    return count


def needs_db_write_approval(user_request: str) -> bool:
    """判断是否需写库审批"""
    text = user_request.lower()
    has_write_intent = any(keyword in text for keyword in DB_WRITE_KEYWORDS)
    has_db_context = any(
        keyword in text for keyword in ("database", "db", "sales", "数据库", "销售", "记录")
    )
    return has_write_intent and has_db_context


def supervisor(state: AgentState):
    """路由下个代理"""
    system_prompt = (
        "You are a supervisor tasked with managing a conversation between the following workers: "
        f"{MEMBERS}.\n\n"
        "Each worker has a specific role:\n"
        "- chat: answer general conversational questions directly.\n"
        "- sqler: query and modify structured sales data in the SQL database.\n"
        "- coder: write or run Python code, especially for charts and computations.\n"
        "- graph_kg: answer broad market and company questions from the Neo4j graph knowledge base.\n"
        "- vec_kg: answer detailed retrieval questions from the vector knowledge base.\n"
        "Routing rule for chart tasks: if the user asks for a chart/plot/visualization, "
        "sqler should fetch data first, then coder must execute plotting code.\n"
        "Choose the single best next worker.\n"
        "Return ONLY a strict JSON object like: {\"next\":\"chat\"}.\n"
        "Allowed next values: chat, coder, sqler, graph_kg, vec_kg, FINISH.\n"
        "When the user request is fully handled, return {\"next\":\"FINISH\"}."
    )

    messages = [{"role": "system", "content": system_prompt}] + state["messages"]
    response = get_router_llm().invoke(messages)
    next_worker = parse_router_choice(getattr(response, "content", str(response)))

    user_request = get_latest_user_message(state["messages"]) or state["messages"][-1].content
    round_count = worker_response_count(state)

    # Hard rule: prevent endless worker->supervisor loop.
    if round_count >= 3:
        return {
            "next": MEMORY_NODE,
            "approval_request": None,
            "pending_worker": None,
            "review_decision": None,
            "review_notes": None,
            }

    # Hard rule: chart request must go to coder after sqler returns data.
    # This must run before FINISH because router LLM may stop after seeing tabular data.
    if needs_chart_generation(user_request):
        last_message = state["messages"][-1]
        if getattr(last_message, "name", "") == "sqler":
            return {
                "next": "coder",
                "approval_request": None,
                "pending_worker": None,
                "review_decision": None,
                "review_notes": None,
            }

    if next_worker == "FINISH":
        return {
            "next": MEMORY_NODE,
            "approval_request": None,
            "pending_worker": None,
            "review_decision": None,
            "review_notes": None,
        }

    last_message = state["messages"][-1]
    if getattr(last_message, "name", "") in MEMBERS:
        return {
            "next": MEMORY_NODE,
            "approval_request": None,
            "pending_worker": None,
            "review_decision": None,
            "review_notes": None,
        }

    if next_worker == "sqler" and needs_db_write_approval(user_request):
        return {
            "next": REVIEW_NODE,
            "pending_worker": next_worker,
            "approval_request": (
                f"用户输入的指令是:{user_request}, 请人工确认是否执行！"
            ),
            "review_decision": None,
            "review_notes": None,
        }

    return {
        "next": next_worker,
        "approval_request": None,
        "pending_worker": None,
        "review_decision": None,
        "review_notes": None,
    }


def human_review(state: AgentState):
    """处理人工审核"""
    pending_worker = state.get("pending_worker")
    if not pending_worker:
        return {
            "next": "supervisor",
            "approval_request": None,
            "review_decision": None,
            "review_notes": None,
        }

    decision = normalize_review_decision(state.get("review_decision"))
    if decision == "approve":
        return {
            "next": pending_worker,
            "approval_request": None,
            "pending_worker": pending_worker,
            "review_decision": None,
            "review_notes": None,
        }

    if decision == "reject":
        notes = (state.get("review_notes") or "").strip() or "No extra review note was provided."
        review_message = HumanMessage(
            content=(
                f"Human review rejected agent {pending_worker}. "
                "Do not call tools that write data or execute code. "
                f"Explain the risk to the user or ask for clearer authorization first. Review note: {notes}"
            ),
            name="human_review",
        )
        return {
            "next": "chat",
            "messages": [review_message],
            "approval_request": None,
            "pending_worker": None,
            "review_decision": None,
            "review_notes": None,
        }

    raise ValueError(
        "Human review is pending. Set review_decision to approve or reject before resuming the thread."
    )


def persist_memory(
    state: AgentState,
    config: RunnableConfig,
    *,
    store: BaseStore | None = None,
):
    """落库对话记忆"""
    if store is not None and state["messages"]:
        latest_user = get_latest_user_message(state["messages"])
        latest_reply = state["messages"][-1].content
        if latest_user and latest_reply:
            store.put(
                get_memory_namespace(config),
                str(uuid.uuid4()),
                {"data": f"Q: {latest_user}\nA: {latest_reply}"},
            )

    return {
        "approval_request": None,
        "pending_worker": None,
        "review_decision": None,
        "review_notes": None,
    }


@lru_cache(maxsize=1)
def get_app():
    """编译主状态图"""
    builder = StateGraph(AgentState)
    builder.add_node("supervisor", supervisor)
    builder.add_node(REVIEW_NODE, human_review)
    builder.add_node(MEMORY_NODE, persist_memory)
    builder.add_node("chat", chat)
    builder.add_node("coder", coder)
    builder.add_node("sqler", sqler)
    builder.add_node("graph_kg", graph_kg)
    builder.add_node("vec_kg", vec_kg)

    for member in MEMBERS:
        builder.add_edge(member, "supervisor")

    builder.add_conditional_edges(
        "supervisor",
        lambda state: state["next"],
        {
            "chat": "chat",
            "coder": "coder",
            "sqler": "sqler",
            "graph_kg": "graph_kg",
            "vec_kg": "vec_kg",
            REVIEW_NODE: REVIEW_NODE,
            MEMORY_NODE: MEMORY_NODE,
        },
    )
    builder.add_conditional_edges(
        REVIEW_NODE,
        lambda state: state["next"],
        {
            "supervisor": "supervisor",
            "chat": "chat",
            "coder": "coder",
            "sqler": "sqler",
        },
    )
    builder.add_edge(MEMORY_NODE, END)
    builder.add_edge(START, "supervisor")
    return builder.compile(
        checkpointer=get_checkpointer(),
        store=get_memory_store(),
        interrupt_before=[REVIEW_NODE],
    )
