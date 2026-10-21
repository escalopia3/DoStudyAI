# 解析阶段契约

Python JSON Schema 与 OpenAPI 由 `python scripts/export-learning-contracts.py` 导出；从仓库根运行并将根目录加入 PYTHONPATH。仅覆盖分块前阶段，不声明 Agent/RAG API 已实现。

内部调用使用 `Authorization: Bearer <LEARNING_SERVICE_TOKEN>`；外部 `/learn/**` 继续使用现有用户认证。Python 不接受任意 URL、文件路径、前端传来的文件身份；worker 用 jobId 向 Java 重新取得经授权的来源。

| Java 接口 | 响应 |
|---|---|
| POST /learn/resources/{id}/parse | 202，项目 Result 包装的 jobId/state；同来源版本幂等 |
| GET /learn/parse-jobs/{id} | 本人任务的状态、序号、产物前缀、错误码 |
| POST /learn/parse-jobs/{id}/cancel | 202，持久化取消意图；立即阻止迟到结果展示 |
| POST /learn/parse-jobs/{id}/retry | 202，对失败/取消任务新建执行 ID；资源锁下去重 |
| GET /learn/parse-jobs/{id}/artifacts/{filename} | 本人已完成任务的短期签名 URL；仅允许 `document.json`、`content.md`、`manifest.json` |
| GET /internal/learning/jobs/{id}/source | 原始 JSON，身份字段与解析请求一致；文档 objectKey 或视频 videoContext |
| POST /internal/learning/knowledge-events | 原始 JSON `{ "accepted": true }`，序号去重，拒绝来源不匹配 |

sourceRevision：文档为不可变对象 key 与大小的 SHA-256；视频为创建任务时的 VideoContext JSON SHA-256。视频快照固定在 Java 任务行中，worker 不重新转写。当前不提供原对象覆盖接口；未来替换文件必须生成新对象 key。

状态：QUEUED → RUNNING → PARSED/FAILED/CANCELLED；可重试的依赖故障 RUNNING → QUEUED。PARSED 仅表示统一文档产物已上传，不表示已分块或可检索。

Python 和 Java 分别持有执行真源与展示投影；终态不被旧回调覆盖。Java 对账可恢复回调丢失。MQ 接收成功不表示解析成功。

新表归属：Java `learning_parse_jobs`、`learning_parse_outbox`；Python `ai_parse_jobs`、`ai_knowledge_outbox`、`ai_alembic_version`。共用 media_db，但迁移工具只管理各自表。
