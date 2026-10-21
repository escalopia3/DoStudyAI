# 分块前解析链路：运行与验收

日期：2026-10-16。范围：Java 上传后派发 → Python 解析/归一化 → MinIO 产物 → Java PARSED 状态。尚未实现分块、embedding、关键词/向量索引、学习问答。

## 1. 数据边界

同一 MySQL 实例、同一 media_db。Flyway 管理 Java 的 learning_parse_jobs / learning_parse_outbox 和 learning_resources.parsing_job_id；Alembic 管理 ai_parse_jobs / ai_knowledge_outbox / ai_alembic_version。运行账号分别按具体表授权；不要让 Python 对业务表拥有写权限。迁移账号可以执行 DDL，运行账号只需要各自表的 SELECT/INSERT/UPDATE/DELETE。

不自动创建数据库或账号，不修改 .env 中的现有凭证，不清空旧视频数据。新功能默认关闭，启用才注册派发器、消费者、解析路由和客户端。

## 2. 准备 Python

在仓库根目录创建独立环境（推荐 Python 3.13；当前标准库归一化测试使用 3.13）：

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install -e '.[test]'
```

依赖安装需要网络，Docling 依赖较大。安装完执行 `pip check` 并记录实际版本；当前 pyproject 是版本范围，不是已经验收的跨平台锁文件。不要直接把另一操作系统的完整环境 freeze 当作通用生产锁。

PDF 标准解析所需模型必须预先下载到明确目录，通过 DOCLING_ARTIFACTS_PATH 配置。模型准备按所安装 Docling 版本的 `docling-tools models download --help` 选择目录和模型；不得在用户请求中隐式下载。Office 转换不需要假造 PDF 页码。未准备模型的 PDF 任务应失败，不得标 PARSED。

## 3. 配置与迁移

加载项目 `.env`，补充 `.env.example` 中 LEARNING_* 配置：

- LEARNING_SERVICE_TOKEN：Java/Python 一致的随机令牌，至少 32 字符；禁止提交。
- LEARNING_DATABASE_URL：`mysql+pymysql://<user>:<URL编码密码>@127.0.0.1:3307/media_db?charset=utf8mb4`。
- LEARNING_MINIO_*：本机访问地址及有权读取 learning/、写入 learning-artifacts/ 的凭证。
- LEARNING_JAVA_URL、LEARNING_PYTHON_URL：对应服务真实可达地址。
- DOCLING_ARTIFACTS_PATH：预先准备的本地模型目录。

Java 启动时由现有 Flyway 执行 V6。Python 迁移单独执行，不在每个 worker 启动时自动建表：

```powershell
./scripts/load-env.ps1
.venv/Scripts/python -m alembic upgrade head
.venv/Scripts/python -m uvicorn agent_service.api:create_app --factory --host 127.0.0.1 --port 8091
```

另一个同配置终端启动 worker：

```powershell
.venv/Scripts/python -m agent_service.worker
```

设置 Java 的 LEARNING_PARSING_ENABLED=true 后重启后端。关闭功能时不要求 Python 凭证，既有功能仍可启动。

## 4. Docker 可选部署

提供 `agent_service/Dockerfile` 与 `docker-compose.learning.yml`。这是本地生产形态模板，不代表已在本机成功构建或部署。

```powershell
docker compose -f docker-compose.yml -f docker-compose.override.yml -f docker-compose.learning.yml --profile learning build learning-api
docker compose -f docker-compose.yml -f docker-compose.override.yml -f docker-compose.learning.yml --profile learning run --rm learning-api python -m alembic upgrade head
docker compose -f docker-compose.yml -f docker-compose.override.yml -f docker-compose.learning.yml --profile learning up -d learning-api learning-worker
```

容器内数据库地址使用 mysql:3306，不能沿用宿主机 127.0.0.1。Java 若运行在宿主机，LEARNING_JAVA_URL 使用可达的 host.docker.internal 地址；原后端默认只监听 127.0.0.1，需明确配置监听地址和防火墙，不能假设容器能访问该回环端口。优先使用双服务均在宿主机的方式完成首次联调。

API/worker 非 root，模型只读挂载，临时目录有容量上限，worker 限制内存/CPU/PID。API 健康检查验证迁移后数据库；worker 的模型就绪仍须用真实样本测试。

## 5. 使用与故障处理

- 新上传文档在功能开启后约 5 秒内被扫描到。已提交资源是可恢复的待处理记录，扫描器创建任务+outbox 的事务；因此上传后立即崩溃也不会丢任务。扫描器也会处理此前未解析的文档。
- 视频需已有 VideoContext；通过 POST /learn/resources/{id}/parse 请求，当前不自动重新下载或转写。
- POST /learn/resources/{id}/parse 对当前来源版本幂等；GET /learn/parse-jobs/{id} 查询。
- POST /learn/parse-jobs/{id}/cancel 立即阻止业务结果发布，并由对账通知 Python。已完成任务取消不倒退。
- POST /learn/parse-jobs/{id}/retry 为 FAILED/CANCELLED 创建新的执行任务；旧任务保留审计，新请求在资源锁下去重。旧任务不能覆盖新任务的状态或产物。
- 文档前端显示等待、解析中、解析完成、失败或取消，并提供已有任务的重试/取消按钮。
- Python 回调丢失由 Java 定期查询修复；MQ 重复投递由 Python jobId+内容哈希去重。
- Python outbox 达到 20 次回调失败后 delivered=-1，需先修复原因，再由运维按明确 event ID 重置 delivered/available_at；禁止全表无条件重放。
- Java outbox 到 20 次发送失败保留记录；对账仍能通过幂等 HTTP 提交恢复。MQ 是主投递通道，对账是明确的补偿通道。
- PARSER_FAILED：查看依赖/模型是否已准备，再用离线 converter 对相同文件复现。对外错误不输出文件内容、凭证或内部堆栈。
- 取消或租约失效后的未发布对象可能留在独立 attempt 前缀；它们不会被显示为有效产物。定期对象清理仍需按业务 job 引用核对，不能仅凭目录年龄删除有效产物。

## 6. 验收命令

```powershell
python -m unittest discover -s agent_service/tests -v
python -m unittest discover -s knowledge_service/tests -v
cd server
./mvnw.cmd -o test
```

Windows 沙箱的系统临时目录可能不可写，可将当前进程 TEMP/TMP 指向仓库的 .learning-work/test-temp；API TestClient 需要本地 socket，Mockito 需要本机 JVM 管道。受限环境失败不能记作业务测试通过。

真实集成验收：每类 PDF、DOCX、PPTX 各一份合法样本和一份损坏样本；已有 VideoContext 一份。检查源权限、Java 任务、Python 状态、三个 MinIO 产物（`document.json`、`content.md`、`manifest.json`）、前端 PARSED、重复提交和取消。真实 PDF/Office 与 MySQL/MQ/MinIO 联调结果未取得前，不标记生产可用。

## 7. 回滚

先关闭 LEARNING_PARSING_ENABLED，再停止 Python worker/API。保留新表和产物，以便恢复；不回滚或删除旧业务表。V6 为增量迁移，切回旧应用代码仍可保留这些字段。Python 表删除只能作为显式数据清理操作，不是正常回滚步骤。
