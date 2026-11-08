# DoVideo Python 后端

从仓库根目录启动新版环境，见[项目启动说明](../README.md)。

## 职责与实现

- Gateway：身份、个人课程归属、上传授权、资源与任务查询。
- Worker：上传校验、固化、HTTPS直链导入、延迟删除；子进程隔离、心跳、租约凭证、超时、取消、重试及过期回收。
- Agent Worker：运行 LangGraph 模型与工具循环，处理课程问答、练习和流式运行事件。
- PostgreSQL：事务、会话摘要、课程 owner_id、资源、上传会话、可靠任务。原 course_members 改名为 legacy_course_members 仅作归档，不参与授权。
- MinIO：启用版本控制，complete 绑定明确版本；Worker 读取该版本并写入独立正式对象。下载绑定正式对象版本。
- Qdrant：保存父子分块、BGE-M3 dense 向量和 BM25 sparse 向量，通过 RRF 混合检索。PostgreSQL 生效指针决定哪些版本可被查询。

## 启动

本机解析和模型路径可配置在 `backend/runtime.local.json`，Gateway 和 Worker 启动时自动加载。模型相对路径以仓库根目录解析，显式环境变量优先。该文件由 Git 忽略。

在仓库根目录根据 `.env.example` 配置 `.env`，加载变量后启动服务并迁移：

```powershell
./scripts/load-env.ps1
docker compose --env-file .env -f deploy/compose.v2.yaml up -d
python -m alembic -c backend/alembic.ini upgrade head
```

在三个终端分别加载 `.env` 后启动：

```powershell
python -m uvicorn app.gateway:create_app --factory --host 127.0.0.1 --port 8092
python -m app.worker --run
python -m app.agent_worker
# 单次消费 / 就绪检查 / 显式清理
python -m app.worker --once
python -m app.worker --check
python -m app.worker --maintenance
```

Worker 默认任务超时3600秒，`--timeout` 可调整；租约60秒，每10秒续租。常驻模式每5分钟执行一次维护。进程异常退出后，任务按租约重新领取；处理器没有注册的任务保持排队，不假报成功。

## 上传与状态

1. POST `/api/v2/courses/{id}/resources/uploads`，提供 Idempotency-Key、filename、contentType、sizeBytes，可选 sha256。
2. 小文件使用返回的 PUT URL。超过16MiB使用分片模式：POST `/uploads/{id}/parts/{number}` 签发分片URL，GET `/uploads/{id}/parts` 查询已上传分片并续传。分片编号从1开始，最后一片之外每片16MiB。
3. POST `/uploads/{id}/complete` 固定对象版本，原子登记资源版本和 VALIDATE_RESOURCE 任务，返回202。重复complete返回相同ID。
4. Worker 流式计算SHA-256、核验大小、文件头与Office内部结构，写入正式对象后将资源设为READY，再创建PROCESS_RESOURCE任务。
5. PROCESS_RESOURCE执行Docling、图片OCR或音视频ASR/采样OCR，成功发布PARSED。READY仅表示源文件已校验，PARSED仍不表示已建索引。实现与验收见 [工作块4记录](../docs/block4-handoff.md)。
6. 解析提交时自动创建 INDEX_RESOURCE；独立子进程完成分块、Embedding、Qdrant 写入与核验，父进程在有效租约下事务发布。解析状态保留 PARSED，索引状态单独查询。失败或取消重建不替换旧索引。

请求元数据指纹只用于请求幂等；内容校验以Worker计算的SHA-256为准。不做跨用户内容去重。格式检测是基础接收校验，不等于完整解析或恶意文件扫描。

上传可通过 POST `/uploads/{id}/cancel` 取消；任务支持 GET `/jobs/{id}`、POST `/jobs/{id}/cancel` 和 `/retry`。
DELETE `/resources/{id}` 立即禁止新增下载授权，31分钟后清理对象；已有签名链接在过期前仍可能访问。上传过期一小时后清理暂存对象；失败校验的源保留供重试；孤立正式对象在一天宽限后回收。

URL导入：POST `/courses/{id}/resources/imports`，字段同上传并增加url。要求声明预期大小，支持配置 `DOVIDEO_IMPORT_HOSTS` 的精确HTTPS域名；默认禁用。导入固定公开IP连接、验证TLS、不跟随重定向，不支持B站页面或需要登录的网站下载。此路径已实现，外部实际源需由部署方配置后验收。

## 验证与依赖

依赖沿用现有环境，无新增下载。无需Redis、Celery或python-multipart。

索引依赖为已安装的 `sentence-transformers`、`qdrant-client` 和本地 `.learning-models/bge-m3`。本机 Embedding 路径已写入忽略 Git 的 `runtime.local.json`，模型 revision 默认读取 `.learning-models/bge-m3.revision.txt`。新环境的可选依赖声明为 `backend[indexing]`；无需在当前环境重复安装。

## 索引、检索与评测

开发者 Top-k 过程记录与 HTML/JSON 导出见[开发者检索调试](../docs/retrieval-debug.md)。仅在 Agent Worker 设置 `DOVIDEO_RETRIEVAL_TRACE=1` 时采集，记录存于后端 checkpoint，不新增学生页面或 HTTP 调试入口。

structure-v3升级已增加完整父块、父子双层召回和目录顺序分页。新统一接口为 `POST /api/v2/courses/{course_id}/knowledge/query`，字段query、intent(auto/detail/overview)、resource_ids、section_ids、cursor；旧搜索接口兼容保留。旧资料需要通过重建接口生成新产物。实现、用法和限制见 [结构化RAG升级](../docs/block5-structure-v3.md)。

- `GET /api/v2/courses/{course_id}/knowledge`：资料解析状态、索引任务状态与生效版本。
- `POST /api/v2/courses/{course_id}/knowledge/search`：`{"question":"TCP提供什么保证？","limit":8}`，返回带页码/时间定位的 `evidence`、对应父块概览 `parentEvidence`、快照与耗时。
- `POST /api/v2/resources/{resource_id}/indexes`：异步重建，返回 `jobId`；并发重建合并至当前未完成任务。旧索引保持可查直至新版本发布。
- 所有 HTTP 接口复用 Bearer 认证和个人课程授权；检索范围由服务端取得，模型不能传入其他用户身份。

从 backend 目录为块4已有 PARSED 资料补建任务：`python -m app.index_backfill`，再运行 Worker。FAILED/CANCELLED 任务通过既有 `/jobs/{id}/retry` 重试。

评测数据为 JSON 数组，每条含 `question` 和 `expectedResourceIds`，也可提供更精确的 `expectedChunkIds`。从 backend 目录执行：

```powershell
python -m dovideo.evaluate --user-id 用户UUID --course-id 课程UUID --dataset 绝对路径/questions.json --limit 8 --output 绝对路径/report.json
```

输出 Recall@K、MRR@K、平均耗时和每题证据。CLI 是受信任的本地运维入口，需要数据库凭据；HTTP 入口通过登录鉴权。没有人工标注的真实课程问题集时，不声称达到教学检索质量指标。冷启动耗时包含加载模型。

```powershell
# 仓库根目录；默认跳过需要真实服务的测试
python -m unittest discover -s backend/tests -v
# 配置隔离服务环境变量后开启集成测试
$env:DOVIDEO_INTEGRATION='1'
python -m unittest discover -s backend/tests -v
```

集成测试会创建带随机名称的测试账号与资源，保留数据库审计记录。覆盖跨用户隔离、并发上传幂等、版本覆盖防护、分片续传、取消重试、登录并发、租约凭证与重试耗尽。

旧0003测试数据的未固化上传不会自动假定可信；需要重新上传或显式重建校验任务。迁移保留旧课程和旧成员归档。浏览器前端接入和跨域部署配置属于块7；本次使用API和存储集成测试验收。
