# 课程学习 Agent 运行说明

## 当前范围

本阶段实现课程授权范围内的短期会话链路：

`课程权限 → READY 资料 → active index 混合检索 → 受限上下文 → LLM 结构化回答 → 引用校验 → Java 持久化 → 课程页展示`

已实现四种模式：课程问答、引导讲解、学习笔记、重点与难点。当前不包含长期学习记忆、自动薄弱点画像、完整组卷系统或外部课程搜索。

## 模型配置

只在项目根目录被忽略的 `.env` 中填写，不要提交密钥：

```dotenv
LEARNING_LLM_BASE_URL=https://你的兼容接口地址/v1
LEARNING_LLM_API_KEY=你的密钥
LEARNING_LLM_MODEL=你的模型名称
LEARNING_LLM_TIMEOUT_SECONDS=45
LEARNING_LLM_MAX_INPUT_TOKENS=24000
LEARNING_LLM_MAX_OUTPUT_TOKENS=1600
LEARNING_LLM_TEMPERATURE=0.2
LEARNING_LLM_THINKING=disabled
```

接口须兼容 `POST /chat/completions`，并支持 `response_format: {"type":"json_object"}`。DeepSeek 当前默认开启思考模式，课程 Agent 应配置 `LEARNING_LLM_THINKING=disabled`，由外层有限 AgentLoop 负责检索与校验。其他供应商不支持 `thinking` 参数时将此项留空。

## 尚需用户批准安装的依赖

专用 Conda 环境仍是：

```text
D:\miniconda3\envs\dovideo-learning\python.exe
```

生产 Agent 图需要 `langgraph>=1,<2`。代码已写入 `pyproject.toml` 的 `agent` 可选依赖，但目前未安装，也未在本轮自动下载。得到用户同意后，在项目根目录、激活专用环境的前提下安装：

```powershell
python -m pip install -e ".[agent]"
```

`httpx`、Pydantic、SQLAlchemy、BGE-M3 相关依赖已经存在，不需要为了本 Agent 安装 OpenAI SDK 或 `tiktoken`。

## 数据库迁移

真实联调前执行两套增量迁移：

```powershell
python -m alembic upgrade head
Set-Location server
.\mvnw.cmd flyway:migrate
```

Python Alembic只管理 `ai_agent_runs` 与 `ai_agent_outbox` 等 `ai_*` 表；Java Flyway V7 管理会话、消息、业务运行和引用表。不要手工重复建表。

## 进程

除现有 MySQL、MinIO、Qdrant、Java、解析/索引 worker 外，新增一个独立 Agent worker：

```powershell
python -m agent_service.learning_agent.worker
```

Docker overlay 中对应服务名为 `learning-agent-worker`。API 仍复用 `learning-api` 的 `8091`，Agent worker不新增监听端口。

## 真实联调顺序

1. 确认专用 Python 环境和三个基础服务健康。
2. 执行 Python Alembic 与 Java Flyway 增量迁移。
3. 填写三个 LLM 必填项，先用一条无隐私的短提示验证 JSON 输出能力。
4. 启动 `learning-api`、原解析/索引 worker 和新增 Agent worker。
5. 在课程页选择已有 READY 资料并提问。
6. 验证回答引用的 `resourceId/indexRevision/chunkId` 均来自当前 active index，并检查页码或视频时间定位。
7. 再验证无答案问题、伪造引用、超时、取消、服务重启和重复回调。

## 已完成的离线验证

- Python 离线套件：50 项通过；其中包括引用伪造拦截、无证据降级、轮数/Token/时限、幂等任务、租约 fencing 与取消。
- Java：Maven compile 通过。
- Web：33 项测试通过，Vite production build 通过。

这些结果不代表真实模型已经验收。真实回答质量、供应商 JSON 兼容性、延迟和 token usage 必须等 API 配置后再测。
