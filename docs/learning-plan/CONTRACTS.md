# 共享契约登记

> 本登记属于历史 v1 方案。当前一期契约以 [课程工作台 v2](../course-workbench-v2.md) 为准，并由 W01 落实；不要直接据本文实现旧入口或独立资料产品流程。

本文件登记已有设计的固定约定和待 T01 细化的契约。**这里只是设计，不表示 DTO、表或接口已经实现。**

## 1. 已固定的约定

| 编号 | 约定 | 来源 |
|---|---|---|
| C01 | 原视频代码/数据保持兼容；新 API `/api/v1`；旧 API 不要求 courseId | 技术 §1.1 |
| C02 | learning_resources 独立；course_resources 只负责至多一个课程的当前归属 | 技术 §3.1 |
| C03 | RESOURCE 笔记归个人资料，CHAPTER/COURSE 笔记归课程 | 技术 §3.2 |
| C04 | 新 ID 对外为字符串，新时间为 UTC；不改全局旧序列化/时区 | 技术 §3 |
| C05 | 新任务用 learning-jobs-v1、独立消费组/失败主题、learning: 缓存前缀 | 技术 §5 |
| C06 | 显式 SourceLocator，视频时间 / PDF 页 / Word 段落 / PPT 页，不虚构定位 | 技术 §4 |
| C07 | 笔记可保存未验证草稿；只有 SUPPORTED 且来源有效段落进入可靠知识库 | 技术 §6 |
| C08 | 新 Qdrant collection，用户/课程/generation 必须过滤；结果再次校验 DB 当前权限 | 技术 §7 |
| C09 | 原视频删除不增加同步课程依赖；新查询检查旧媒体当前存在性 | 技术 §11 |
| C10 | 新课程 Agent 独立状态与提示词；工具从服务端注入 owner/course | 技术 §8 |
| C11 | 无自测数据掌握度未知；客观题评分幂等，计划应用是显式用户操作 | 技术 §9 |
| C12 | 新模块默认关闭，不改旧视频上传上限、限流键和线程池配置 | 技术 §1/2/4 |

## 2. T01 要产出的机器可读契约

下列路径是**待创建产物**，本次任务拆分不预填虚假的完整 schema：

| 产物 | 负责包 | 内容与检验 |
|---|---|---|
| `contracts/learning-api.yaml` | T01 | OpenAPI：技术 §10 所有新路径、类型、错误、分页、幂等头；无需改旧 OpenAPI |
| `contracts/resource-context.schema.json` | T01 | ResourceContext、locator、质量标记；覆盖多 locator、表格/shape 定位 |
| `contracts/job-event.schema.json` | T01 | job 状态、阶段、sequence、错误码、取消和重试行为 |
| `contracts/note.schema.json` | T01 | scope、版本、sectionId、引用、验证状态、发布资格 |
| `contracts/course-agent.schema.json` | T01 | 工具输入输出、run 状态、答案、引用、停止原因 |
| `contracts/review.schema.json` | T01 | topic、范围、题目、作答、掌握度、计划及执行记录 |
| `contracts/examples/` | T01 | 每个 schema 的有效及无效样例，含无课程资料、跨课程非法引用 |
| `contracts/schema-plan.md` | T01 | 字段空值/唯一键/外键/索引/所有者，按任务分配迁移；不预占版本号 |

初次仅冻结首版已确定字段，不借写 schema 扩需求。后续新增字段遵循 EXECUTION 的变更登记，不能各任务创造第二套同义 DTO。

## 3. 高风险契约细化清单

T01 必须解决下列实现细节，并在交接中列出正式决定：

- membership_version 每次重新加入必须变化，删除/重建不能复用旧值；生成方式可用 UUID 或全局单调 ID。
- 旧 VideoContext 适配保留出处；原文 chunk 多页时用 locator 列表，不能强行挤入一个 page。
- GET /resources 采用稳定跨类型游标；旧视频尚无 resourceId 时可由 kind/mediaId 执行 prepare-video。
- 无 courseId 的资料、job、RESOURCE 笔记为合法状态；CHAPTER/COURSE scope 必须有课程。
- 草稿、已验证、已发布、已索引为不同状态；发布前后指针和 generation 事务规则须可测试。
- 未具备索引功能的早期课程操作只保存归档与待构建状态，不生成假 READY；对外完整索引 API 到 T25 才启用。
- Outbox 事件种类与 job.type 明确区分；未注册处理器不得把消息确认成业务成功。
- 删除原来源后的历史笔记允许保留文本，引用不可再授权；移出课程不全局删除个人笔记。
- objective 评分返回答案仅在提交后；重复网络请求和同题复练计数分开。
- `expectedVersion`、Idempotency-Key 的冲突、重放、过期规则，以及新错误码不能改旧错误码语义。

## 4. 已有旧代码的只读参照

- `MediaController / MediaProcessingController`：视频上传、转写、音频下载。
- `AnalysisController / ModeRegistry / AgentLoopService`：原四模式、自动路由、反馈和检查点。
- `MediaService / AgentCheckpointRepository`：原媒体真源与可读取的上下文。
- `AuthInterceptor / WebConfig`：授权接入。
- `client/src/api.js / taskEvents.js / markdown.js / videoTimestamps.js`：旧客户端契约。
- `extension/sidepanel.js`：旧外部客户端兼容。

文件均以执行时 rg 搜索结果为准；私有函数名称和行号不得靠本文推断。
