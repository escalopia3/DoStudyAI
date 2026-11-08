# Agent 工程化实现与运行说明

日期：2026-11-06。已完成本机0012迁移、Gateway/Worker切换和真实链路冒烟。评分缺口已补齐，独立AI复核非人工金标；当前逐题质量门禁因Q25/Q37退化仍阻断。最新验收与准确统计见 [收尾核验报告](agent-engineering-closure.md)，下文较早的测试数字保留为历史记录。

## 已实现

| 能力 | 入口 |
|---|---|
| HTTP错误分类、有限退避、Retry-After、部分流失败 | backend/dovideo/agents/reliability.py、provider.py |
| 租约重领上限、持久deadline、共享配额 | agents/service.py、migrations/versions/0012_agent_reliability.py |
| checkpoint版本、配置/实现指纹、旧版本拒绝恢复 | agents/checkpoints.py、app/agent_worker.py |
| 编号存在、实际输入、来源定位校验 | agents/citations.py、agents/loop.py |
| 私有调用事件、关联ID、耗时、用量、健康告警 | agents/reliability.py、observability.py |
| 按run查询、聚合与价格表估算 | tools/inspect_agent_runs.py |
| 真实运行、独立judge配置、逐题比较和完整性门槛 | tools/run_agent_regression.py |
| 源文与已复核公式打包 | tools/build_agent_source_truth.py |
| 临时PostgreSQL迁移、恢复与隔离验收 | tools/verify_agent_postgres.py |
| 后端常驻无模型调用检查 | .github/workflows/agent-engineering.yml |

练习工具原有确定性ID及租约校验保留，增加真实数据库重复执行测试。基础观测不依赖开启详细检索轨迹；私有事件不进入公开SSE。前端显示部分流中断/引用失败提示，避免把失败正文显示成已验证答案。

## 发布前提

业务库已从0011升级到0012。迁移前完整备份已在临时库恢复验证，迁移后及测试清理后逐表行数与维护前一致。本轮已重启本机Gateway/Worker，没有发布或修改来源索引。

部署时先停止接收新run并排空旧Worker，再备份数据库、升级到0012、启动新版Gateway/Worker。0012只增加字段和索引；不要在旧Worker仍领取任务时升级新checkpoint协议。首次启动旧RUNNING任务若没有版本指纹，默认以CHECKPOINT_INCOMPATIBLE明确终结，不能静默重跑。

在项目原有Python环境中执行，工作目录为仓库根目录：

```powershell
$env:PYTHONPATH = 'backend'
python -m alembic -c backend/alembic.ini upgrade head
python -m app.agent_worker
```

迁移命令已在本机业务库执行，重复维护应先核对实际版本。此次服务切换使用 tools/deploy_agent_services.ps1，启动时启用原生流式输出和私有检索轨迹；不要在现有服务运行时再启动重复进程。

## 配置

| 配置 | 默认 | 含义 |
|---|---:|---|
| DOVIDEO_MODEL_ATTEMPTS | 3 | 初次请求在内，上限3次 |
| DOVIDEO_MODEL_DEADLINE_SECONDS | 120 | 一次逻辑模型调用预算，包含退避 |
| DOVIDEO_RUN_DEADLINE_SECONDS | 300 | 整个run预算，跨重领保留 |
| DOVIDEO_MAX_CLAIM_ATTEMPTS | 3 | 初次领取在内的最大次数 |
| DOVIDEO_RUN_TOKEN_LIMIT | 100000 | 已知token消耗达到后不再继续执行；当前请求仍可能超过阈值 |
| DOVIDEO_MAX_ACTIVE_RUNS | 32 | 共享数据库中的全局排队+运行数量上限 |
| DOVIDEO_MAX_USER_RUNS | 2 | 同一用户排队+运行数量上限 |
| DOVIDEO_MAX_USER_DAILY_RUNS | 200 | 滚动24小时提交数上限 |
| DOVIDEO_ALLOW_LEGACY_CHECKPOINT | 0 | 默认拒绝无法证明兼容性的无版本checkpoint |

HTTP为同步客户端。预算在请求、流读取和退避边界检查，正在阻塞的网络操作受socket超时约束，不承诺毫秒级抢占。取消在检查点/事件提交或心跳处生效。无法确认供应商是否处理的失败请求不算0消耗；自动重试不提供供应商调用恰好一次保证。

## 回归命令

先生成来源真值文件。这里只整理原有XML和已有13条带哈希的公式复核，不产生新的人工金标，也不证明全部公式已恢复。

```powershell
python tools/build_agent_source_truth.py --slides rag_source_slides.json --review-manifest outputs/rag-round2-20261106/formula-review-manifest.json --reviews-dir deploy/formula-reviews --output outputs/agent-engineering-20261106/source-truth.json
python tools/run_agent_regression.py --phase preflight --course-id <课程UUID> --output outputs/agent-check
```

独立设置 DOVIDEO_JUDGE_MODEL、DOVIDEO_JUDGE_BASE_URL、DOVIDEO_JUDGE_API_KEY。生成模型仍使用现有DOVIDEO_CHAT_*配置。不要将密钥写入评测报告或提交到Git。Full模式在生成前检查judge和来源文件是否配置；同模型模式会在manifest中标注。

```powershell
python tools/run_agent_regression.py --course-id <课程UUID> --source-truth outputs/agent-engineering-20261106/source-truth.json --baseline outputs/frozen-baseline --output outputs/current-regression
```

首次没有统一格式基线时不传 --baseline。若要复用历史回答而不重新生成：

```powershell
python tools/run_agent_regression.py --phase judge --run-dir outputs/rag-round2-20261106/after40 --source-truth outputs/agent-engineering-20261106/source-truth.json --output outputs/frozen-baseline
```

重评历史回答会调用judge，历史生成代码以原目录metadata哈希留档，不能将当前代码哈希冒充历史生成版本。比较两组必须使用相同题库、评分代码、judge配置和来源真值；历史旧评分协议不能直接混作新基线。

可分别选择 --phase run / judge / compare。Run只生成回答，未评分是ungraded，不会冒充judge失败或质量通过；judge-only可在不重新生成的情况下重新评分。生成缓存要求代码、配置和索引指纹完全匹配。

输出含 generation-manifest.json、逐题runs、judge输入输出、report.json、comparison.json和comparison.md。退出码：0通过；1质量回归/确定性引用错误；2执行或配置失败；3评分不完整。未知项保留在总分母中，不能排除后声称100%。目前保守门槛为逐题主分下降或已验证成功变失败即阻断；未知/评分覆盖不足也不能发布为通过。

原40题中4题为资料边界题，比例10%。现有独立版本化的46题集增加6题，总计10道负样本（21.74%）；schema、来源页及AI复核均已完成，尚非人工金标。原40题前后对照与补充6题分开报告，不能把没有历史回答的6题混入原基线。

## 观测与故障处理

```powershell
python tools/inspect_agent_runs.py --run-id <运行UUID>
python tools/inspect_agent_runs.py --minutes 10
```

这些是持有服务器凭据的私有运维命令，没有新增公共调试API。价格表可通过 --prices 指定JSON（version、currency、input_per_million、output_per_million）；只对已知usage估算，不声称是供应商账单。

Worker每60秒输出一次JSON健康摘要；队列最老任务超过120秒、最近10分钟存在恢复失败、或至少20个终态run中失败率超过10%时输出warning。外部告警通知/日志采集器需要部署环境接入，本轮没有向外部服务发送通知。

PARTIAL_STREAM保留已展示正文并结束，不自动重复生成。CITATION_VALIDATION_FAILED非流式返回明确失败说明；流式保留正文并标明未验证。来源定位缺失为unverifiable；正文中的复杂文件名/页码引用格式未被解析时也不能算已核验。语义支撑不通过文本包含判断。

## 测试与回滚

```powershell
python -m pytest backend/tests -q -p no:cacheprovider
python tools/verify_agent_postgres.py
```

第二条命令只创建自身生成名称的新数据库，完整迁移、执行恢复测试，最后只删除该测试库。需要当前数据库账号具备创建测试库权限；不修改业务schema，不连接对象存储写入或调用真实模型。可在CI自带PostgreSQL服务运行。

回滚先停止领取和排空run，恢复原代码/配置。新增数据库字段可保留；若旧Storage严格检查0011版本，需在确认没有新版Worker后按备份/迁移流程恢复版本，不能直接启动旧版。新checkpoint不允许由不识别协议的旧程序恢复。本轮未改索引，无需切换索引指针。

验收原始文件位于 outputs/agent-engineering-20261106。代码测试通过不等于业务库发布完成，也不等于新版本40题质量通过。

本次验证：后端98项通过、14项跳过、2个子测试通过；其中新增的6项PostgreSQL测试已在隔离库另行执行并全部通过。隔离库0012→0011→0012迁移往返通过，测试库已清理。前端36项测试通过，生产构建通过。详见该目录implementation-verification.json及JUnit XML。

部署后最近一次后端全套100项通过、14项跳过、2个子测试通过；随后评分器主分保留修复的专项24项通过。此前14个跳过项中，新建的6项PostgreSQL恢复测试已单独执行通过；其余需外部集成/解析条件的测试未冒充通过。

部署回归整合入口为 tools/run_agent_release_regression.py：指定 --course-id、--historical-run、--source-truth、--output；仅在明确接受同模型自评时加 --allow-self-judge。它并行执行当前真实生成与历史回答重评，再对当前组评分和比较。评分并发上限4，默认3；输出长度设置在独立judge子进程中，不改变生成进程配置。
