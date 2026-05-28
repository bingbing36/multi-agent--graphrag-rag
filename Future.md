# Future Roadmap

本文档记录 multi-agent 项目的后续优化方向，重点围绕前端工程化、生产级记忆、RAG 效果优化、意图识别、Agent 架构演进和评测体系建设。

## 1. FastAPI + React/Vite 前端工程化

### 目标

- 给当前多代理项目增加可交互前端界面。
- 从 CLI 演示升级为可视化产品形态。
- 支持聊天、多轮对话、事件流、人机审批、图表预览、图谱构建和状态查看。

### 学习与落地路线

1. FastAPI 基础
   - 学习 `GET / POST`、Pydantic 请求体、路由拆分、CORS、错误处理。
   - 项目接口示例：
     - `POST /chat`：提交用户问题。
     - `POST /approve`：提交人工审批。
     - `GET /state/{thread_id}`：查看线程状态。
     - `POST /build-graph`：触发离线构图。

2. React/Vite 基础
   - 学习组件、状态管理、表单输入、`fetch`、基础布局。
   - 页面模块示例：
     - 聊天输入区。
     - 消息列表。
     - Agent Trace 面板。
     - 人工审批按钮。
     - 图表结果预览。
     - 图谱构建控制台。

3. 流式输出
   - 第一阶段使用 SSE，适合服务端单向推送。
   - 第二阶段升级 WebSocket，适合双向对话、人机审批和实时 Agent Trace。

4. 工程化目录建议

```text
multi-agent/
  backend/
    main.py
    routers/
      chat.py
      graph.py
      memory.py
      review.py
    services/
      agent_service.py
  frontend/
    src/
      App.jsx
      api/
      components/
      pages/
```

## 2. 生产级记忆存储设计

### 当前问题

- 当前 `MemorySaver` 和 `InMemoryStore` 适合开发验证，不适合生产。
- 服务重启后记忆丢失。
- 多实例部署无法共享状态。
- 缺少审计、权限隔离和长期存储能力。

### 短期记忆：线程 Checkpoint

可选方案：

- SQLite checkpoint：适合本地演示和单机部署。
- PostgreSQL checkpoint：适合生产环境，多实例共享，事务能力强。
- Redis checkpoint：适合短生命周期、高频访问状态，但审计和持久化能力较弱。

推荐路线：

- 开发阶段：SQLite。
- 生产阶段：PostgreSQL。

### 长期记忆：用户画像与历史知识

可选方案：

- PostgreSQL：存结构化记忆、元数据、权限和审计。
- Milvus / Qdrant / Chroma：存向量化记忆，支持语义召回。
- PostgreSQL + 向量库：推荐方案，兼顾可管理性与语义检索能力。

推荐生产架构：

```text
短期记忆：PostgreSQL Checkpointer
长期记忆：PostgreSQL metadata + Milvus vector memory
审批记录：PostgreSQL audit log
```

### 迭代步骤

1. 将 `MemorySaver` 替换为 SQLite checkpoint。
2. 将长期记忆从 `InMemoryStore` 替换为 SQLite/PostgreSQL 表。
3. 给长期记忆增加 embedding，接入 Milvus。
4. 将人机审批日志落 PostgreSQL，支持审计追踪。

## 3. RAG 优化效果对比

### 目标

- 系统性优化 `vec_kg` 和多路知识库检索效果。
- 所有优化通过 A/B 测试迭代验证。
- 用检索召回率、精准率、答案满意度等指标量化评估。

### 优化方向

1. 文本切块优化
   - 对比固定长度切块、递归切块、语义切块、标题感知切块。
   - 评估 chunk size、chunk overlap 对召回率和答案质量的影响。

2. 混合检索策略
   - 对比向量检索、关键词检索、BM25 + 向量混合检索。
   - 对不同问题类型采用不同检索组合。

3. 召回重排序
   - 引入 reranker，对初步召回结果二次排序。
   - 对比无 rerank、cross-encoder rerank、LLM rerank 的效果与成本。

4. 查询 Query 优化
   - Query rewrite：将用户问题改写成更适合检索的查询。
   - Multi-query：生成多个查询版本并合并召回。
   - HyDE：先生成假设答案，再用假设答案做检索。

5. 多路知识库检索
   - 同时检索向量库、图数据库、SQL 数据库和长期记忆。
   - 根据意图动态选择检索路径。
   - 对检索结果做融合、去重和排序。

### A/B 测试指标

- Recall@K：正确证据是否被召回。
- Precision@K：召回结果中有效证据比例。
- MRR / NDCG：排序质量。
- Answer Faithfulness：答案是否忠于证据。
- Answer Relevance：答案是否回应用户问题。
- 用户满意度：人工打分或偏好对比。
- 延迟与成本：响应时间、token 成本、模型调用次数。

## 4. 意图识别优化

### 当前方向

- 当前 supervisor 负责在 `chat / sqler / coder / graph_kg / vec_kg` 之间路由。
- 后续需要让意图识别更稳定、更可评测。

### 优化方案

- 构建意图标签集：
  - 普通聊天。
  - SQL 查询。
  - SQL 写操作。
  - 图表生成。
  - 图谱关系查询。
  - 向量知识库检索。
  - 多路检索。
  - 人机审批任务。

- 增加确定性规则：
  - 高频稳定问题优先规则路由。
  - 危险写库操作强制进入 HITL。

- 增加 LLM 分类器：
  - 对复杂模糊问题使用 LLM 做意图识别。
  - 输出结构化 JSON，进入本地解析和校验。

- 增加意图识别评测集：
  - 每类意图准备固定样例。
  - 对路由准确率进行回归测试。

## 5. Agent 架构演进：ReAct / Plan-and-Execute / Workflow

### 当前状态

- 当前项目中的工具型 Agent 更接近 ReAct 风格：
  - 观察用户问题。
  - 决定是否调用工具。
  - 根据工具结果继续推理。

### 后续目标

- 加入 Plan-and-Execute Agent。
- 加入固定 Workflow。
- 在项目中体现三种模式的区别和适用任务。

### 三类模式对比

- ReAct Agent
  - 适合开放式探索、工具调用不确定的任务。
  - 优点是灵活。
  - 缺点是路径不稳定，可能循环或多调用工具。

- Plan-and-Execute Agent
  - 适合复杂任务拆解，例如“先查数据，再分析，再画图，再总结”。
  - 优点是任务结构清晰。
  - 缺点是规划错误会影响后续执行。

- Workflow
  - 适合流程明确、可控性要求高的任务。
  - 例如：危险操作审批、图谱离线构建、RAG 评测流水线。
  - 优点是稳定可测。
  - 缺点是灵活性低。

### 落地场景

- 图表生成：Plan-and-Execute。
- 删除/修改数据库：Workflow + HITL。
- 普通知识问答：ReAct 或普通 LLM。
- RAG 评测：Workflow。
- 多路知识库检索：Plan-and-Execute + Workflow 混合。

## 6. 记忆提取层设计优化

### 目标

- 不把所有对话都直接写入长期记忆。
- 增加“记忆提取层”，只保存真正有长期价值的信息。

### 设计方向

- 记忆类型分类：
  - 用户身份信息。
  - 用户偏好。
  - 项目事实。
  - 历史决策。
  - 长期目标。
  - 禁止保存的信息。

- 记忆提取流程：
  - 从对话中识别候选记忆。
  - 判断是否值得长期保存。
  - 生成结构化记忆。
  - 写入长期记忆库。
  - 支持更新、合并和删除。

- 记忆安全：
  - 敏感信息过滤。
  - 用户可查看、修改、删除记忆。
  - 审计记忆来源。

## 7. Agent 记忆机制设计优化

### 目标

- 不同 Agent 使用不同记忆。
- 避免所有 Agent 共享同一堆上下文导致混乱。

### 设计方向

- chat agent：
  - 使用用户偏好、历史对话摘要。

- sqler agent：
  - 使用数据库 schema、历史 SQL 操作、审批记录。

- coder agent：
  - 使用图表偏好、代码执行历史、文件路径。

- graph_kg agent：
  - 使用图谱 schema、实体别名、历史图谱查询样例。

- vec_kg agent：
  - 使用 RAG 检索偏好、用户常问主题、长期知识片段。

### 记忆注入策略

- 按 Agent 注入最小必要记忆。
- 按任务意图召回相关记忆。
- 对长期记忆做摘要压缩。
- 给记忆设置过期时间和可信度。

## 8. 评测体系建设

### 目标

- 给多代理系统建立可重复的评测流程。
- 每次修改 prompt、路由、RAG、图谱构建、记忆机制后，都能量化比较效果。

### 评测对象

- Supervisor 路由准确率。
- SQL Agent 查询和写库正确性。
- Coder Agent 图表生成成功率。
- graph_kg 图谱问答准确率。
- vec_kg RAG 检索和答案质量。
- HITL 审批流程正确性。
- 记忆提取和召回质量。

### 评测方式

- 离线测试集：
  - 固定问题、期望路由、期望答案、期望证据。

- A/B 测试：
  - 对比不同切块策略、检索策略、prompt、reranker。

- 回归测试：
  - 每次修改后运行核心样例，避免旧功能退化。

- 人工评分：
  - 对答案满意度、可读性、可信度进行评分。

### 指标

- 路由准确率。
- 工具调用成功率。
- 检索 Recall@K / Precision@K。
- 答案正确率。
- 答案忠实度。
- 图表生成成功率。
- 人机审批拦截准确率。
- 端到端响应延迟。
- token 成本。

## 9. 建议推进顺序

1. 先做 FastAPI 最小后端：`POST /chat`。
2. 再做 React/Vite 最小聊天界面。
3. 将 `MemorySaver` 替换为 SQLite checkpoint。
4. 建立 RAG 评测集和图谱问答评测集。
5. 做文本切块 A/B 测试。
6. 加入混合检索和 reranker。
7. 优化 supervisor 意图识别。
8. 引入 Plan-and-Execute Agent。
9. 设计生产级长期记忆。
10. 最后统一做前端 Agent Trace、审批面板和评测面板。
