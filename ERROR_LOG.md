# ERROR LOG

本文档用于回顾项目运行中出现的错误、原因、方案选择与最终处理结果。

## 1. 缺少模块：`No module named 'langchain.chains'`

- 问题：启动时报 `ModuleNotFoundError: No module named 'langchain.chains'`。
- 原因：LangChain 新版本中导入路径调整，旧入口不再稳定可用。
- 解决措施：
  - `GraphCypherQAChain` 改为优先从 `langchain_community.chains.graph_qa.cypher` 导入。
  - `PromptTemplate` 改为 `langchain_core.prompts`。
  - 同步更新 `requirements.txt` 版本约束。

## 2. 环境变量缺失：`Missing required environment variable: DEEPSEEK_API_KEY`

- 问题：运行时找不到 `DEEPSEEK_API_KEY`。
- 原因：进程未稳定加载环境文件。
- 解决措施：
  - 后续按你的要求统一改为仅加载 `.env.example`。
  - 现在修改 `.env.example` 后，重启进程即可生效。

## 3. 模型余额不足：`402 Insufficient Balance`

- 问题：模型接口返回 402。
- 原因：供应商账户余额/额度不足。
- 解决措施：
  - 在 `app.py` 增加 provider 错误识别：
    - DeepSeek 余额不足提示。
    - Qwen 余额不足提示。

## 4. Supervisor 结构化输出不兼容：`response_format type is unavailable now`

- 问题：`supervisor` 使用 `with_structured_output(...)` 报 400。
- 原因：当前 DeepSeek 端点不支持该 `response_format`。
- 解决措施：
  - 改为“纯文本 JSON 路由 + 本地解析”：
    - `supervisor` 使用普通 `invoke`。
    - 本地 `parse_router_choice()` 解析 `{"next":"..."}`。

## 5. `graph_kg` 动态构图触发相同不兼容

- 问题：`LLMGraphTransformer.convert_to_graph_documents(...)` 触发同样的 `response_format` 错误。
- 原因：动态图构建也依赖结构化输出能力。
- 方案选择：你选择了**方案A**（运行时只查询现有图数据）。
- 解决措施：
  - 从 `get_cypher_chain()` 移除运行时 `LLMGraphTransformer` 动态构图。
  - 新增离线建图脚本 `build_graph_offline.py`（规则抽取，不依赖 LLM 结构化输出）。
  - 先执行离线导入，再运行主程序。

## 6. `GraphCypherQAChain` 输入键报错：`Missing input keys: {'query'}`

- 问题：调用链期望 `query` 变量。
- 原因：自定义 QA 模板与链输入字段不一致（历史版本残留）。
- 解决措施：
  - QA Prompt 保持 `question + context` 输入，不使用 `{query}`。
  - 重新运行后该错误不再作为主阻塞出现。

## 7. Neo4j 告警：`Company label / name property not found`

- 问题：查询时警告图里缺少 `Company`/`name`。
- 原因：方案A下未先完成离线建图时，库中确实无对应节点。
- 解决措施：
  - 执行 `python multi-agent/build_graph_offline.py`。
  - 当前一次导入结果：`companies=35, relations=11`。

## 8. Milvus 连接失败（临时出现）

- 问题：`localhost:19530` 连接超时。
- 原因：当时触发了临时 fallback 到 `vec_kg`，而本地 Milvus 未可用。
- 解决措施：
  - 已按你要求撤销“自动切到 vec_kg”的策略方向（当前主路径按方案A走 graph_kg 查询）。
  - `app.py` 保留 Milvus/Neo4j 认证类错误识别提示。

## 9. 目前状态（最新）

- 主命令已可执行并返回结果：
  - `python main.py "都有哪些公司在我的数据库中？"`
- 仍存在非阻塞告警：
  - `LangChainPendingDeprecationWarning`
  - `Neo4jGraph` 未来弃用告警（建议后续迁移到 `langchain-neo4j`）。

## 10. 图表绘制告警（Matplotlib 线程与中文字体）

- 问题：
  - `Starting a Matplotlib GUI outside of the main thread will likely fail`
  - `Glyph ... missing from font(s) DejaVu Sans`
- 原因：
  - 在工具执行线程里调用了 GUI 显示（`plt.show()`）。
  - 默认字体不包含中文字形。
- 解决措施：
  - 在 `python_repl` 执行前注入 `MPLBACKEND=Agg`，强制非 GUI 后端。
  - 设置中文字体回退链（`Microsoft YaHei / SimHei / Noto Sans CJK SC / Arial Unicode MS / DejaVu Sans`）。
  - 自动将 `plt.show()` 替换为 `plt.savefig("chart_output.png", ...)`，在终端环境稳定产出图片文件。

## 11. 多轮对话未进入 / 审批“否”未生效

- 问题：
  - 运行后未进入多轮对话循环。
  - 审批输入“否”时未正确拒绝写库操作。
- 原因：
  - CLI 默认走单轮问答，未显式启用 `--dialogue`。
  - 早期审批输入归一化不完整，中文“否”分支处理不稳定。
- 解决措施：
  - 增加 `--dialogue` 入口，显式进入多轮循环。
  - 在 `hitl.py` 增加审批输入标准化，覆盖“是/否/同意/拒绝”等表达。
  - 在 `streaming.py` 的多轮函数中增加“是/否”重试提示与拒绝分支反馈。

## 13. 图表任务未触发 coder，仅返回文字代码

- 问题：图表请求有时只返回代码说明，不落地图像文件。
- 原因：
  - 路由与提示词存在歧义，`sqler` 可能直接结束回答。
  - `coder` 未被稳定触发执行绘图代码。
- 解决措施：
  - 调整 `sqler` 提示词：只负责取数，不宣称完成绘图。
  - 增加 supervisor 图表任务硬规则：`sqler` 后必须转 `coder`。
  - `python_repl` 执行层强制非 GUI 后端并保存文件，避免仅文本输出。

## 14. 重复响应过多（worker-supervisor 循环）

- 问题：同一问题会出现多次重复 `graph_kg` 回复，终端刷屏。
- 原因：`worker -> supervisor -> worker` 循环缺少硬上限，未及时 `FINISH`。
- 解决措施：

  - 在 `supervisor` 增加轮次限制：同一线程累计 worker 响应达到 3 次后，强制进入 `persist_memory -> END`。
  - 图表任务仍保留 `sqler -> coder` 优先链路，但整体不会无限循环。

## 15. graph_kg 效果优化完整链路复盘

### 初始：数据提取到 `Neo4j `

- 结论：当前主路径使用 `LLMGraphTransformer(..., ignore_tool_usage=True)`。
- 含义：优先走“提示模式/非工具调用模式”，不是函数调用结构化输出模式。
- 现状：主路径可成功导入；若失败，脚本再回退到规则抽取兜底。

&emsp;准备好数据后，我们可以使用 `langchain_experimental.graph_transformers` 中的 `LLMGraphTransformer` 将其摄取到 `Neo4j` 中。该工具会自动将文档转换为图格式。`LLMGraphTransformer` 能够以两种完全独立的模式运行：

- 基于工具的模式模式（默认）：当使用的大模型支持结构化输出或函数调用时，该模式利用内置的 `with_structured_output`来使用工具。工具规范定义了输出格式，确保以结构化、预定义的方式提取实体和关系。
- 基于提示的模式（回退）：在使用的大模型不支持工具或函数调用的情况下， 该转换器回退到纯粹提示驱动的方法。该模式使用 `few-shot`提示来定义输出格式，指导大模型以基于文本的方式提取实体和关系。然后通过自定义函数解析结果，该函数将大模型的输出转换为 `JSON` 格式。该 `JSON` 用于填充节点和关系。

### 问题：文档转图时实体边界不准，普通短语也会被当成节点。

   原因： 

    -`LLMGraphTransformer` 会生成开放类型，如 `Characteristic`、`Market`、`Organization`，但这些类型没有经过业务筛选。
    - Neo4j 中旧图数据被污染后，`Company` 标签下混入了很多非公司实体，导致“都有哪些公司”这类问题答歪。
    - `GraphCypherQAChain` 对高频确定性问题也让 LLM 生成 Cypher，偶尔会生成坏 Cypher 或答非所问。

- 判断：这不是单纯换模型能解决的问题，而是需要把“文档抽取 -> 图谱写入 -> 查询问答”做成可控工程流程。
- 因此检索并参考了开源社区方向寻找skills与harness：

  - `neo4j-labs/llm-graph-builder`：参考 schema-first 图谱构建思路。
  - `GLiNER`：参考按标签抽实体的 NER 思路，作为可选实体候选增强。
  - `sift-kg`：参考 human-in-the-loop entity resolution 思路。
  - `GraphRAG` / `LightRAG`：参考完整图谱索引与评测闭环，但暂不整体迁移，避免项目过重。

### 方案取舍

- 没有直接替换成 **微软 **microsoft/graphrag** 或 HKU **LightRAG** 这些现成框架** 。而是在现有 LangGraph + Neo4j 多代理架构里，实现了一个轻量级、可控的 GraphRAG 子系统。

  - 优点是能力强，但会显著改变项目结构，当前多代理项目会变得不聚焦。
- 没有继续完全依赖 LLMGraphTransformer：

  - 优点是自动化强，但实体类型和关系类型太开放，演示时不稳定。
- 最终选择轻量 harness：

  - 保留当前 LangGraph + Neo4j 架构。
  - 在离线构图阶段增加 schema guard、entity resolution、eval。
  - LLMGraphTransformer 改为可选预览，不再默认写入主图。

### 落地改造

- 新增 `kg_schema.py`：

  - 定义允许的实体类型：`Company / University / ResearchInstitution / Product / Technology / Market / Organization / Project / Material`。
  - 定义允许的关系类型：`DEVELOPS / PRODUCES / COOPERATES_WITH / PARTNERS_WITH / EXPANDS_TO / SUPPORTS / USES_MATERIAL / SPONSORS`。
  - 过滤掉不在 schema 内的实体和关系。
- 新增 `entity_resolution.py`：

  - 合并简称、英文名和规范名。
  - 例如：`华为 -> 华为技术有限公司`，`Apple -> 苹果公司`，`Microsoft -> 微软`。
- 新增 `kg_eval.py`：

  - 固定一组期望关系作为回归评测。
  - 每次构图后输出命中率，避免后续修改规则时效果退化。
- 新增 `gliner_harness.py`：

  - 提供可选 `--use-gliner` 入口。
  - 默认不开启，避免引入额外模型下载和运行成本。
- 重构 `build_graph_offline.py`：

  - 默认流程变为：读取语料 -> 规则高置信抽取 -> schema guard -> entity resolution -> eval -> 写入 Neo4j。
  - 增加 `--dry-run`：只预览抽取结果，不写 Neo4j。
  - 增加 `--reset`：清理旧图后重建干净图。
  - 增加 `--preview-llm`：只查看 LLMGraphTransformer 输出，默认不写入主图。

### 清理旧脏图

- 发现：即使新抽取策略变好，Neo4j 里旧的 LLMGraphTransformer 噪声节点还在。
- 现象：

  - `MATCH (c:Company)` 查出大量非公司短语。
  - `graph_kg` 查询仍然被旧脏数据误导。
- 处理：

  - 执行 `python build_graph_offline.py --reset`。
  - 删除旧图数据，重新写入经过 schema guard 的干净图。
- 验证：

  - `Company` 标签下只剩：`Adobe、华为技术有限公司、小米科技有限责任公司、微软、英特尔、苹果公司、谷歌`。

### graph_kg 查询侧兜底

- 问题：即使图谱干净，`GraphCypherQAChain` 对高频确定性问题仍可能生成坏 Cypher。
- 处理：

  - 对“都有哪些公司”这类问题增加确定性分支，直接执行：

    `MATCH (c:Company) RETURN c.name AS name ORDER BY c.name`
  - 对“华为技术有限公司与哪些教育机构建立了合作？”增加确定性分支，直接查：

    `(Company)-[:COOPERATES_WITH]->(University / ResearchInstitution / Organization)`
  - 收紧 `is_company_list_question()`，避免把“与哪些教育机构合作”误判成公司列表问题。
  - 保留 LLM-to-Cypher 主能力：不命中确定性分支的问题继续走 `GraphCypherQAChain`。

### Supervisor 与输出稳定性

- 问题：`worker -> supervisor -> worker` 循环会让 `graph_kg` 重复回答，甚至第二轮生成坏 Cypher。
- 处理：

  - worker 已经给出答案后默认进入 `persist_memory -> END`，图表链路除外。
  - `streaming.py` 跳过无 name 的用户消息，并对相同 `(speaker, content)` 去重。
- 效果：

  - `python main.py "都有哪些公司在我的数据库中？"` 只输出一条结果。
  - `python main.py "华为技术有限公司与哪些教育机构建立了合作？"` 返回对应教育/研究机构，不再答非所问。

### 当前效果

- 构图评测：

  - `python build_graph_offline.py --dry-run`
  - `KG eval: hits=13/13, actual_relations=36`
- 清理并重建：

  - `python build_graph_offline.py --reset`
  - `Clean graph imported. entities=35, relations=36, reset=True`
- 查询验证：

  - 公司列表：返回 `Adobe、华为技术有限公司、小米科技有限责任公司、微软、英特尔、苹果公司、谷歌`。
  - 华为教育合作：返回 `全球多家顶尖大学和研究机构、剑桥大学`。

### 最终认知

- `graph_kg` 效果提升的关键不是单点 prompt，而是整个链路变成了可控系统：

  - 抽取前有 schema。
  - 写入前有实体归一化。
  - 写入后有评测。
  - 查询时有确定性兜底。
  - 旧数据需要显式清理，否则新逻辑会被历史脏图拖累。

## 16. 前端图表已生成但会话框不显示图片

- 问题：用户多次请求“生成柱状图”后，`coder` 已经在本地生成 `artifacts/charts/*.png`，但前端会话框只显示“图表工作已生成，请到 artifacts 目录查看”，没有直接渲染图片。
- 原因：
  - 后端最初只用 `list_chart_artifacts(started_at)` 按时间戳猜测“本轮新生成的图片”。
  - 这个方式不是强绑定，容易被后端进程未重启、文件时间戳误差、工作目录差异、模型最终回答不包含文件名等情况打断。
  - 前端本身已经写了 `message.artifacts` 图片渲染逻辑，但后端返回的 `artifacts` 为空，所以会话框自然没有图片。
- 解决措施：
  - 在 `backend/services/agent_service.py` 新增 `extract_chart_artifacts()`，从 `sqler/coder/final` 文本中解析 `artifacts/charts/*.png` 或绝对路径。
  - 新增 `merge_artifacts()`，优先使用文本中解析出的强关联图片，再用时间戳扫描作为兜底。
  - `stream_chat_events()` 收集 trace 文本和 final answer，统一抽取图片并放入 final 事件的 `artifacts` 字段。
  - 前端图片加载后触发滚动到底部，避免图片出现后把最新内容顶出可视区域。
- 经验：
  - “文件已生成”不等于“前端可展示”，必须验证完整链路：工具产物 -> 后端结构化字段 -> 静态资源 URL -> 前端消息气泡渲染。
  - 对用户可见产物不能靠时间戳猜测，应该让工具输出明确 artifact path，并由后端解析为结构化 artifact。

## 17. 聊天消息更新后不会自动滚到底部

- 问题：流式输出或长回答出现后，用户需要手动拖动会话框滚动条才能看到最新内容。
- 原因：
  - 前端 `.messages` 区域已经是内部滚动，但 React 状态更新后没有主动滚动到底部。
  - 图片异步加载后会改变消息高度，即使文本更新时滚到底部，图片加载完成后也可能再次把底部推出可视区。
- 解决措施：
  - 在 `frontend/src/main.jsx` 增加 `messagesEndRef`。
  - 在 `messages` 或 `activeThreadId` 变化时调用 `scrollIntoView()`。
  - 在 artifact 图片 `onLoad` 时再次滚到底部。
- 经验：
  - 聊天产品的自动跟随要同时处理文本流式更新和图片加载后的二次布局变化。
