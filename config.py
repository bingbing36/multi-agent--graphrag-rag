from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import Column, Float, ForeignKey, Integer, String, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from langchain_experimental.utilities import PythonREPL
from langchain_openai import ChatOpenAI, OpenAIEmbeddings


BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent

# 只从 .env.example 读取配置
load_dotenv(BASE_DIR / ".env.example", override=True)

DEFAULT_THREAD_ID = os.getenv("LANGGRAPH_THREAD_ID", "default-thread")
DEFAULT_USER_ID = os.getenv("LANGGRAPH_USER_ID", "default-user")
DEFAULT_MEMORY_LIMIT = int(os.getenv("LONG_TERM_MEMORY_LIMIT", "5"))
REVIEW_NODE = "human_review"
MEMORY_NODE = "persist_memory"
APPROVAL_REQUIRED_MEMBERS = {"coder", "sqler"}
MEMBERS = ["chat", "coder", "sqler", "graph_kg", "vec_kg"]

# 统一管理公司语料路径
COMPANY_DOC_PATH = os.getenv("COMPANY_DOC_PATH", "doc/company.txt")

# LangSmith tracing 配置
LANGSMITH_TRACING = os.getenv("LANGSMITH_TRACING", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
LANGSMITH_ENDPOINT = os.getenv("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com")
LANGSMITH_API_KEY = os.getenv("LANGSMITH_API_KEY", "")
LANGSMITH_PROJECT = os.getenv("LANGSMITH_PROJECT", "multi-agent")


def require_env(name: str) -> str:
    """读取必填环境变量"""
    value = os.getenv(name)
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def configure_langsmith() -> None:
    """统一注入 LangSmith 环境变量"""
    if not LANGSMITH_TRACING:
        return
    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGSMITH_ENDPOINT"] = LANGSMITH_ENDPOINT
    os.environ["LANGSMITH_PROJECT"] = LANGSMITH_PROJECT
    if LANGSMITH_API_KEY:
        os.environ["LANGSMITH_API_KEY"] = LANGSMITH_API_KEY


def get_deepseek_base_url() -> str:
    """获取 DeepSeek 地址"""
    return os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")


def get_qwen_base_url() -> str:
    """获取 Qwen 兼容地址"""
    return os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")


def get_deepseek_extra_body() -> dict:
    """DeepSeek 请求附加参数"""
    mode = os.getenv("DEEPSEEK_THINKING_MODE", "off").strip().lower()
    if mode in {"off", "disable", "disabled", "false", "0"}:
        return {"thinking": {"type": "disabled"}}
    return {}


@lru_cache(maxsize=1)
def get_main_llm() -> ChatOpenAI:
    """创建主对话模型"""
    return ChatOpenAI(
        model=os.getenv("DEEPSEEK_CHAT_MODEL", "deepseek-chat"),
        api_key=require_env("DEEPSEEK_API_KEY"),
        base_url=get_deepseek_base_url(),
        temperature=0,
        extra_body=get_deepseek_extra_body(),
    )


@lru_cache(maxsize=1)
def get_router_llm() -> ChatOpenAI:
    """创建路由模型"""
    return ChatOpenAI(
        model=os.getenv("DEEPSEEK_ROUTER_MODEL", "deepseek-chat"),
        api_key=require_env("DEEPSEEK_API_KEY"),
        base_url=get_deepseek_base_url(),
        temperature=0,
        extra_body=get_deepseek_extra_body(),
    )


@lru_cache(maxsize=1)
def get_graph_llm() -> ChatOpenAI:
    """创建图谱模型"""
    return ChatOpenAI(
        model=os.getenv("DEEPSEEK_GRAPH_MODEL", os.getenv("DEEPSEEK_CHAT_MODEL", "deepseek-chat")),
        api_key=require_env("DEEPSEEK_API_KEY"),
        base_url=get_deepseek_base_url(),
        temperature=0,
        extra_body=get_deepseek_extra_body(),
    )


@lru_cache(maxsize=1)
def get_cypher_llm() -> ChatOpenAI:
    """创建 Cypher 模型"""
    return ChatOpenAI(
        model=os.getenv(
            "DEEPSEEK_CYPHER_MODEL",
            os.getenv("DEEPSEEK_ROUTER_MODEL", "deepseek-chat"),
        ),
        api_key=require_env("DEEPSEEK_API_KEY"),
        base_url=get_deepseek_base_url(),
        temperature=0,
        extra_body=get_deepseek_extra_body(),
    )


@lru_cache(maxsize=1)
def get_coder_llm():
    """创建代码模型"""
    backend = os.getenv("CODER_BACKEND", "deepseek").lower()
    if backend == "openai":
        return ChatOpenAI(
            model=os.getenv("DEEPSEEK_CODER_MODEL", os.getenv("DEEPSEEK_CHAT_MODEL", "deepseek-chat")),
            api_key=require_env("DEEPSEEK_API_KEY"),
            base_url=get_deepseek_base_url(),
            temperature=0,
            extra_body=get_deepseek_extra_body(),
        )
    if backend == "deepseek":
        return ChatOpenAI(
            model=os.getenv("DEEPSEEK_CODER_MODEL", os.getenv("DEEPSEEK_CHAT_MODEL", "deepseek-chat")),
            api_key=require_env("DEEPSEEK_API_KEY"),
            base_url=get_deepseek_base_url(),
            temperature=0,
            extra_body=get_deepseek_extra_body(),
        )

    try:
        from langchain_ollama import ChatOllama
    except ImportError as exc:
        raise ImportError(
            "langchain_ollama is required when CODER_BACKEND=ollama. "
            "Install it or set CODER_BACKEND=openai."
        ) from exc

    return ChatOllama(
        base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        model=os.getenv("OLLAMA_MODEL", "qwen2.5-coder:32b"),
    )


@lru_cache(maxsize=1)
def get_embeddings() -> OpenAIEmbeddings:
    """创建向量模型"""
    return OpenAIEmbeddings(
        model=os.getenv("QWEN_EMBEDDING_MODEL", "text-embedding-v3"),
        api_key=require_env("QWEN_API_KEY"),
        base_url=get_qwen_base_url(),
    )


repl = PythonREPL()

Base = declarative_base()


class SalesData(Base):
    __tablename__ = "sales_data"

    sales_id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("product_information.product_id"))
    employee_id = Column(Integer)
    customer_id = Column(Integer, ForeignKey("customer_information.customer_id"))
    sale_date = Column(String(50))
    quantity = Column(Integer)
    amount = Column(Float)
    discount = Column(Float)


class CustomerInformation(Base):
    __tablename__ = "customer_information"

    customer_id = Column(Integer, primary_key=True)
    customer_name = Column(String(50))
    contact_info = Column(String(100))
    region = Column(String(50))
    customer_type = Column(String(50))


class ProductInformation(Base):
    __tablename__ = "product_information"

    product_id = Column(Integer, primary_key=True)
    product_name = Column(String(50))
    category = Column(String(50))
    unit_price = Column(Float)
    stock_level = Column(Integer)


class CompetitorAnalysis(Base):
    __tablename__ = "competitor_analysis"

    competitor_id = Column(Integer, primary_key=True)
    competitor_name = Column(String(50))
    region = Column(String(50))
    market_share = Column(Float)


DATABASE_URI = os.getenv(
    "DATABASE_URI",
    f"sqlite:///{(BASE_DIR / 'sales_demo.db').resolve()}",
)

engine = create_engine(DATABASE_URI)
SessionLocal = sessionmaker(bind=engine)
Base.metadata.create_all(engine)

configure_langsmith()
