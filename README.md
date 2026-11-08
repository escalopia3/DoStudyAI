# DoStudy 多模态课程学习助手

DoStudy 提供个人课程、资料上传与解析、知识检索、带出处的问答和练习。Vue 工作台通过 `/api/v2` 访问 FastAPI Gateway。资料处理和 LangGraph Agent 分别由 Python Worker 执行，使用 PostgreSQL、MinIO 和 Qdrant。

| 路径 | 用途 |
| --- | --- |
| `client/` | Vue 课程学习工作台 |
| `backend/` | Gateway、资料处理 Worker、Agent Worker 和 Alembic 迁移 |
| `knowledge_service/` | 新版共享的文档归一化、分块和嵌入模块 |
| `deploy/compose.v2.yaml` | 本地 PostgreSQL、MinIO 和 Qdrant |
| `.env.example` | 本地存储、模型及前端代理配置模板 |

## 本地启动

从仓库根目录执行以下命令。首次配置时将 `.env.example` 复制为 `.env` 并填写连接参数和密钥。如果已有 `.env`，补齐模板中的新版变量即可。接入现有 v2 数据时，沿用其存储地址、凭据和卷。

```powershell
python -m pip install -e ./backend
./scripts/load-env.ps1
# 本地首次缺少 MinIO 镜像时执行这一行
docker build -t dovideo-minio-local:RELEASE.2025-09-07T16-13-09Z -f docker/minio/Dockerfile .
docker compose --env-file .env -f deploy/compose.v2.yaml up -d
python -m alembic -c backend/alembic.ini upgrade head
```

在三个独立终端中分别加载 `.env` 并从仓库根目录运行其中一条。使用本地模型处理资料时，按后端文档配置对应依赖和模型路径。

```powershell
./scripts/load-env.ps1
# 每个终端运行一个进程
python -m uvicorn app.gateway:create_app --factory --host 127.0.0.1 --port 8092
python -m app.worker --run
python -m app.agent_worker
```

在另一个终端启动网页，打开 `http://localhost:5173`。

```powershell
cd client
npm ci
npm run dev
```

- [后端依赖、模型配置和验收说明](backend/README.md)
- [前端开发与部署](client/README.md)
- [Agent 运行手册](docs/agent-engineering-runbook.md)
