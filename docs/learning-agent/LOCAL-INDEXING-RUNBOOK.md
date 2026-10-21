# 本地知识索引运行说明

项目唯一受支持的本地 Python 环境是
`D:\miniconda3\envs\dovideo-learning\python.exe`（Python 3.12）。先执行
`. .\scripts\learning-live-env.ps1`，脚本会验证解释器并将该环境放到当前 PowerShell 的 PATH
首位。不得使用 Conda base 环境或恢复已废弃的 `.python-deps`。

可随时运行 `powershell -ExecutionPolicy Bypass -File scripts\verify-learning-env.ps1`
检查解释器、包、模型目录和旧环境残留。

本实现使用 BAAI/bge-m3（1024 维）、Qdrant dense + BM25、父子分块和 MySQL CAS 发布。
代码默认离线：设置 `HF_HUB_OFFLINE=1`、`TRANSFORMERS_OFFLINE=1` 并使用
`local_files_only=True`，运行任务不会下载模型。

## 构成

- `knowledge_service/indexing/chunking.py`：稳定父子块、标题路径、相邻关系和 locator。
- `embedding.py`：离线 BGE-M3 Provider 和向量完整性检查。
- `qdrant.py`：collection schema、幂等 point、dense/BM25 RRF 和成对版本过滤。
- `store.py`：不可变 manifest 与活动版本指针。
- `pipeline.py`：构建、写入、抽样校验和 CAS 发布。
- `retrieval.py`：只查询授权资源的活动版本。

## 需要用户批准后准备的依赖

1. Python optional dependency：`pip install -e ".[indexing,test]"`。
2. 完整的 `BAAI/bge-m3` 模型目录，放到 `.learning-models/bge-m3`；模型版本必须固定并填写
   `LEARNING_EMBEDDING_MODEL_REVISION`，不能使用浮动的 `main` 作为生产版本。
3. Qdrant 版本须支持 Query API、RRF、named dense/sparse vectors 和 `Qdrant/bm25` 文档推理。
4. 执行 Alembic `0002_knowledge_indexes` 迁移。

## 显式本地执行

准备好依赖、模型、MySQL 和 Qdrant 后：

```powershell
python -m knowledge_service.indexing.cli path\to\document.json `
  --owner-id 1001 --resource-id 2001 --source-revision src3 --index-revision idx7
```

更新已有索引时必须传实际旧版本：

```powershell
python -m knowledge_service.indexing.cli path\to\document.json `
  --owner-id 1001 --resource-id 2001 --source-revision src4 `
  --index-revision idx8 --expected-previous idx7
```

未通过 point 数量、抽样哈希和父子 manifest 校验时不会更新活动索引指针。

## 自动入库状态机

`agent_service.worker` 现在负责同一持久化任务的两个阶段：

```text
QUEUED -> RUNNING -> PARSED -> INDEXING -> READY
```

- `PARSED` 表示规范产物已经完整写入 MinIO，但尚未对用户检索可见。
- `INDEXING` 使用租约和心跳；进程退出后可重新领取过期任务。
- 索引版本由资源 ID、来源版本和固定 embedding 版本确定，重试不会生成重复版本。
- Qdrant 点数、向量维度、抽样内容哈希和 manifest 全部通过后，才会 CAS 发布 active index。
- 发布前再次调用 Java 校验任务未取消、资料未替换，并确认 Worker 租约仍有效。
- `READY` 表示 Java 业务投影与 Python active index 均已完成；问答链路只能检索 READY 资料的活动版本。
- 暂时性 MinIO/HTTP 故障会退回 `PARSED` 延迟重试；确定性数据、模型或 schema 错误进入 `FAILED`。

本地运行时分别启动 API 和 Worker：

```powershell
. .\scripts\learning-live-env.ps1
python -m uvicorn agent_service.api:create_app --factory --host 127.0.0.1 --port 8091
```

另开一个已加载相同环境的 PowerShell：

```powershell
. .\scripts\learning-live-env.ps1
python -m agent_service.worker
```

Java 正常项目端口使用 `9090`；只有隔离联调环境脚本覆盖为 `9092` 时，Java 才应启动在 `9092`。
