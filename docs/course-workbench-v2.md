# 课程工作台一期：AI 工程实施规范

版本：2.0 · 2026-10-12 · 状态：待实施，本文不代表功能已完成。

## 1. 文档效力与产品意图

本文是用户最新确认需求的一期开发基线。与 `course-learning-development.md`、`course-learning-technical.md`、`learning-plan/` v1 发生冲突时，以本文为准。旧文档只作历史技术参考；不得直接执行旧 T00～T37 台账，或沿用“课程可选、原视频首页为默认”的产品结构。新执行记录使用 `docs/course-workbench-v2/`，不得把旧任务状态冒充本期进度。

目标：将原来进入工作台就处理视频的产品，升级成进入工作台先看“我的课程”，进入课程后管理章节、上传视频/PDF/Word/PPT，由 Agent 处理选定资料并生成、保存学习笔记。

必须实现的闭环：登录 → 我的课程 → 新建/进入课程 → 创建章节 → 上传/加入资料 → 处理资料 → Agent 总结 → 查看、保存、编辑及导出学习笔记 → 点击来源回看资料。

原视频上传、解析、分析方式保留，并整合到课程内部。不能只在旧视频首页增加一个“我的课程”按钮，不能只做上传列表或假数据演示，不能把生成内容只保存在浏览器内存。

课程专家的一对一答疑、课程检索库、考试范围解析、自测、错题与复习计划属于后续阶段。未来课程专家和期末复习是同一个逻辑课程 Agent 的不同任务模式，共享课程资料与学习记录；不是两个独立 Agent，也不要求所有任务塞进一个聊天会话。本期的笔记生成服务为它们提供可复用的数据与工具。

## 2. 已核实的原项目接入点

以下是读取源码得到的事实；类名和路径之外的拟新增内容均属于设计，不表示已实现。

| 现有文件/目录 | 当前职责与改造要求 |
|---|---|
| `client/src/main.js` | 直接挂载 App.vue；在这里接入新应用壳/开关 |
| `client/src/App.vue` | 视频上传、列表、账号及分析侧栏；分步抽取组件，保留行为 |
| `client/src/useAnalysisWorkspace.js` | 视频分析交互，含 GENERAL/LEARNING/REVIEW/CREATION 与前端 AUTO；复用 |
| `client/src/chunkUpload.js` | 视频分片上传；课程内上传仍沿用 |
| `client/src/taskEvents.js` | 旧任务流；保留其契约 |
| `client/src/api.js` | Bearer 认证、Result 解包、401 会话处理、流透传；新 API 复用 |
| `client/src/videoTimestamps.js` | 原视频时间戳处理；不得用新页面路由破坏 |
| `client/vite.config.js` | 现有代理含 /user、/media、/analysis 等；必须新增 /learn 代理 |
| `server/.../controller/MediaController.java` | /media/upload、分片接口、upload-url、list、playback、delete；契约保留 |
| `server/.../controller/AnalysisController.java` | /analysis/ai、analysis-status、analysis-events、追问及证据检索；契约保留 |
| `server/.../service/AnalysisDispatchService.java` | 视频任务提交、模式与配额；新视频学习入口调用已有链路 |
| `server/.../service/VideoContextService.java` 等 | 原视频上下文能力；实施前核对产物缓存和读取路径 |
| `server/.../entity/MediaFile.java` | media_files，含 aiSummary、transcriptText 等视频字段；不能将其改作文档通用表 |
| `server/.../config/WebConfig.java` | 鉴权当前匹配 /media、/analysis 等，未含 /learn；新 API 必须补入鉴权 |
| `server/src/main/resources/db/migration` | 当前 V1～V3；新增迁移前重新检查版本，禁止修改已执行迁移 |

表中 `server/...` 指 `server/src/main/java/com/example/server`。技术栈为 Vue 3/Vite、Java 21/Spring Boot、MyBatis Plus/MySQL，已有 Redis、MinIO、RocketMQ 及视频向量相关服务。新功能不要求更换框架或拆微服务。

当前工作目录未检测到 Git 仓库；开始实施时重新确认。若仍无 .git，交接记录使用文件清单及差异证据，不编造 commit/branch。

## 3. 页面及交互契约

```text
工作台：我的课程（登录后的默认页面）
├── 新建课程
├── 待归课资料（仅用于历史视频/旧扩展导入资料的整理）
└── 课程卡片 → 课程详情
    ├── 左侧：全部、未分章、第一章、第二章……
    ├── 资料页签：添加资料、加入已有视频、类型/状态筛选
    │   ├── 视频：原上传、播放和分析操作
    │   └── PDF/Word/PPT：上传、解析状态、原文内容、重新处理
    └── 笔记页签：生成笔记、笔记列表、编辑、来源、导出
```

- 空课程显示“添加资料/创建章节”；空工作台显示“新建课程”。未登录复用原登录注册能力，不发受保护列表请求。
- 新建课程必填名称（1～100 字），学期（≤50 字）和简介（≤1000 字）可选。章节名 1～100 字，支持排序。
- 课程内新增资料必须有 courseId，chapterId 可空，默认当前章节。无需用户重复选择当前课程。
- 视频支持原本地上传与链接导入；文档只支持文件上传。多个文件逐个展示进度和失败，失败不撤销其他成功项。
- 历史视频不自动推断课程、不批量重跑；“加入课程”只建立关联。新 UI 不提供独立文档库作为主入口。
- 删除章节把资料和章节归属笔记移至未分章；删除课程需提示影响并确认，资料解除归属、单资料笔记保留，整课/多资料笔记归档只读。文件删除必须单独操作。
- 资料卡显示类型、名称、处理状态、页数/时长、更新时间；上传、解析、笔记生成状态分开，不用一个“完成”混淆。
- 默认用户明确点击“生成学习笔记”后才调用模型。文档上传成功自动解析，不自动消耗模型生成笔记。
- 用户可选择一份、多份或当前章节全部资料，输入要求（≤2000 字）。默认要求：整理核心概念、重点难点、例子、易错点和简要总结；一期不实现交互自测。
- 未就绪资料必须列出原因。默认阻止提交，用户可明确选择“仅处理已就绪资料”；后端保存实际选择清单，不能悄悄忽略资料。
- 成功生成笔记自动持久化，刷新后存在；可编辑、保存新版本、导出 Markdown、回看历史版本。模型失败不产生“成功笔记”。
- PDF 展示页码，PPT 展示幻灯片编号，Word 展示标题/段落，视频引用跳到播放器时间点。Office 首版是解析内容预览，不承诺像素级原版式预览。
- 路由建议使用 pathname：`/`、`/courses/:courseId`、`/courses/:courseId/notes/:noteId`；禁止用 hash router 接管旧 #video-t=。若新增 Vue Router，锁定依赖及 lockfile，部署配置对应前端路径 fallback，不吞掉 API 请求。
- 新界面默认打开；回退开关可恢复旧工作台。`?demo` 保留可用并区分演示数据，不能把演示成功作为验收证据。

## 4. 一期范围及格式交付批次

| 批次 | 支持能力 | 完成定义 |
|---|---|---|
| A（必做） | 视频、文本 PDF、DOCX、PPTX | 上传、解析/原视频处理、带来源笔记、保存编辑导出 |
| B（A 稳定后交付） | 扫描 PDF OCR、DOC、PPT 基础文字 | 使用真实样本验证，失败明确说明并允许转现代格式 |

批次 A 发布时，界面精确标注 PDF/DOCX/PPTX 支持范围，不能显示“全部 Word/PPT 均支持”。批次 B 未做时不能把本期完整格式覆盖标为完成。图片课件、复杂公式、SmartArt、复杂表格的完整语义不在基础承诺内；有遗漏时记录 qualityWarnings，不可返回空内容成功。

PDF 解析候选 PDFBox，Word/PPT 候选 Apache POI；依赖版本需读取官方文档、使用样本验证、检查 Maven 依赖冲突后锁定。OCR 先核对原 OcrUtils 的输入和质量，不能假定它可直接处理文档页面。

一期不引入知识库发布审批、embedding/index generation、RAG 平台、考试题库、长期对话记忆。这些不能成为课程 CRUD 或首篇笔记的前置工程。

## 5. 代码组织与处理架构

拟新增前端 `src/features/courses/`、`resources/`、`notes/`，分别放页面/组件/composable/API；通用认证与请求继续复用。App 壳负责导航、登录及全局通知，资料处理状态属于各自模块。切换课程/退出登录时中止旧请求和事件流，迟到响应不得写入新会话。

拟新增后端 `learning` 包，下分 controller/dto/entity/mapper/service/parser/worker。Controller 仅校验入参和身份并调用服务；服务负责事务和权限；解析器只返回结构化内容；模型调用经独立适配层，禁止在 Controller 内解析文件或拼接模型提示。

```text
视频 → 原上传接口 → mediaId → 课程资料映射
                         → 原 LEARNING 分析/已有学习结果 → 来源适配
PDF/Word/PPT → 新文档上传 → 原文件存储 → 持久化解析任务 → 来源片段
来源片段/原视频产物 → 学习笔记编排 → 引用校验 → 笔记版本入库
```

新增建议接口：`DocumentParser.parse(input, limits)` 返回 segments、metadata、warnings；`VideoLearningAdapter` 读取/启动原学习任务并获取可核验来源；`LearningNoteService` 编排与持久化；`SourceResolver` 在权限校验后定位原文。

视频要求：明确传 LEARNING；原 GENERAL 默认、REVIEW（原审查模式，不是期末复习）、CREATION、AUTO 路由保留。相同学习要求已有可用结果时读取复用；缺少结果时经原 dispatch 提交，不自己复制 ASR/OCR/AgentLoop。原视频系统本身的正常结果写入继续，新增笔记写入不得额外覆盖 aiSummary。必须绑定实际 mediaId、mode、goalDigest/结果版本，不能拿“最后一次任意模式摘要”当学习结果。

单视频笔记优先直接适配原 LEARNING 产物为笔记，避免再跑一轮相同总结；混合资料笔记用原学习产物和来源片段参与归纳。旧学习结果无法核实引用时可保存为“待核验”笔记，不伪造时间点。

## 6. 数据契约（拟新增表）

所有新表 ID 用 BIGINT；新 DTO 以十进制字符串输出 ID，避免 JavaScript 精度损失，不能修改旧 DTO 的全局序列化。时间用 UTC 存储/ISO-8601 输出；前端按本地时区展示。以下是必需字段语义，实施任务必须交付实际 Flyway SQL、索引和实体映射。

| 表 | 核心字段/约束 |
|---|---|
| courses | id,user_id,name,semester,description,status,version,created_at,updated_at,deleted_at；索引(user_id,deleted_at,updated_at) |
| course_chapters | id,course_id,name,sort_order,version；索引(course_id,sort_order) |
| learning_resources | id,user_id,type(VIDEO/PDF/DOCX/PPTX/DOC/PPT),media_id nullable,filename,object_key nullable,content_hash,active_source_version,parse_status,metadata_json,deleted_at；media_id 唯一映射；视频文件仍由旧系统拥有 |
| course_resources | resource_id 唯一,course_id,chapter_id nullable,created_at；一期一份资料最多归一门课；索引(course_id,chapter_id) |
| resource_versions | id,resource_id,version_no,parser_version,status,warnings_json,created_at；唯一(resource_id,version_no) |
| resource_segments | id,resource_version_id,ordinal,text,locator_json；唯一(resource_version_id,ordinal) |
| learning_notes | id,user_id,course_id nullable,chapter_id nullable,title,current_revision_id,status,version,created_at,updated_at；删除课程后的多资料笔记标 ARCHIVED |
| note_revisions | id,note_id,revision_no,markdown,structured_json,goal,coverage_json,model_config_version,created_at；唯一(note_id,revision_no)，版本不可变 |
| note_sources | revision_id,resource_id,resource_version_id,segment_id,citation_key；保存确切版本/片段引用，不保存模型虚构路径 |
| learning_tasks | id,user_id,course_id,type,resource_id nullable,state,payload_json,result_json,error_code,attempt,lease_owner,lease_until,fence,version,idempotency_key,created_at,updated_at；唯一(user_id,type,idempotency_key) |

新任务可直接采用 MySQL 持久化队列与独立定时 Worker，不强制一期增加 MQ/Outbox。通过事务条件更新领取、租约及 fence 防止双执行提交；若选用 MQ，必须添加事务 Outbox、重复投递幂等和恢复扫描，不能用裸 @Async 替代持久化任务。

关系校验：chapter 必须属于 course；所有 resource 必须属于当前用户且关联当前课程。用户 ID 从认证取，禁止接受客户端 userId 作为授权依据。新关联不能添加阻止旧 media 删除的外键。

来源 locator 示例：

```json
{"kind":"PDF_PAGE","page":8}
{"kind":"SLIDE","slide":12}
{"kind":"DOC_PARAGRAPH","headingPath":["第一章","基本概念"],"paragraph":23}
{"kind":"VIDEO_TIME","startMs":512000,"endMs":540000}
```

页、幻灯片、段落从 1 开始；时间用毫秒。Word 不虚构页码；PPT 备注需标明来自备注。重解析产生新版本，成功后原子切 active_source_version，失败保留旧可用版本；旧引用保留历史版本，展示“来源已更新”。

## 7. API 契约

新服务端路径统一 `/learn`，不是上一轮建议的 `/api/learn`。当前原项目实际使用 `/media` 和 `/analysis`，必须同时更新 Vite/部署代理与 WebConfig 鉴权匹配。沿用 `Result {code,message,data}`，成功 code=0；错误沿用现有异常处理及 ErrorCode 风格。下表全部受认证和资源权限约束。

为兼容当前 CORS 允许的方法，本期使用 GET/POST/DELETE；如改用 PATCH/PUT，必须同步修改预检与测试，不得只改单端。

| 方法与路径 | 请求/返回核心约定 |
|---|---|
| GET /learn/courses | page=1,size=20；返回 items,total,page,size，size≤100 |
| POST /learn/courses | name,semester?,description? → course |
| GET /learn/courses/{id} | → course + chapters + counts |
| POST /learn/courses/{id}/update | name/semester/description,status?,expectedVersion → course；冲突409 |
| DELETE /learn/courses/{id} | 逻辑删除及解除关联，事务内完成可见性撤销 |
| POST /learn/courses/{id}/chapters | name → chapter |
| POST /learn/chapters/{id}/update | name,expectedVersion |
| POST /learn/courses/{id}/chapters/reorder | chapterIds（该课程完整有序集合）、expectedVersion；事务更新 |
| DELETE /learn/chapters/{id} | 资料/笔记 chapterId 清空，再删除章节 |
| GET /learn/courses/{id}/resources | page,size,type?,chapterId?,unassigned?；chapterId 与 unassigned 互斥 |
| POST /learn/courses/{id}/videos | mediaId,chapterId?；幂等映射，校验旧视频 owner |
| POST /learn/courses/{id}/documents | multipart file,chapterId? + Idempotency-Key → 202 {resource,taskId} |
| POST /learn/resources/{id}/move | courseId,chapterId?；事务校验两端归属 |
| POST /learn/resources/{id}/detach | 解除课程关系，不删文件 |
| DELETE /learn/resources/{id} | 文档逻辑删除；视频明确委托旧删除服务，保持其行为 |
| GET /learn/resources/{id} | 元数据、状态、warnings、activeSourceVersion |
| GET /learn/resources/{id}/segments | sourceVersion,page,size → 原文片段分页 |
| POST /learn/resources/{id}/parse | Idempotency-Key → 202 {taskId}；视频不走文档解析 |
| POST /learn/courses/{id}/notes/generate | resourceIds,chapterId?,goal,sourceVersions + Idempotency-Key → 202 {taskId} |
| GET /learn/courses/{id}/notes | page,size,chapterId? → 笔记列表 |
| GET /learn/notes/{id} | 当前正文、版本、覆盖范围、引用状态 |
| POST /learn/notes/{id}/revisions | title,markdown,expectedRevisionId → 新版本；过期409 |
| GET /learn/notes/{id}/revisions | 历史版本列表 |
| GET /learn/notes/{id}/revisions/{revisionId} | 不可变历史正文 |
| GET /learn/notes/{id}/export | text/markdown 附件，前端不得走 JSON 解包 |
| GET /learn/notes/{id}/sources/{citationKey} | revisionId → 经校验的 locator/原文/短效文件访问方式 |
| GET /learn/tasks/{id} | state,stage,progress?,result,error,attempt；返回快照 |
| POST /learn/tasks/{id}/cancel | 幂等取消；终态返回当前状态 |
| POST /learn/tasks/{id}/retry | 仅失败可重试，复用绑定输入且增加 attempt |
```

任务初版采用前端轮询（进行中约2秒，失败退避上限10秒，终态停止，页面卸载取消）；SSE 是可选优化，不能成为第一闭环阻塞。旧视频 SSE 不改。

同一幂等键不同请求体返回409；同键同体返回已有资源/任务。重复上传不能只按全局 hash 暴露其他用户资料。文档限制建议配置为50 MiB、500页/幻灯片，批次≤10个；上传流、展开内容量、解析内存和耗时也需限制，不能只校验扩展名。只对新端点应用限制，不下调旧视频全局 multipart 上限。

## 8. 解析与笔记生成算法

文档处理：校验类型/文件头 → 存入独立 MinIO 前缀 → 记录资源和解析任务 → 受限解析器提取结构 → 校验非空、编号与覆盖范围 → 入库版本和片段 → 更新 READY/READY_WITH_WARNINGS。原文件写入成功而 DB 失败需清理孤儿；定期清理仅限新模块自有前缀，禁止扫描删除旧视频对象。

解析进程建议采用同仓 Java CLI 子进程，限制 heap、超时并在超时杀死；隔离不可信压缩包、禁用外部实体/宏执行/外部资源获取。损坏、加密、空内容、超限返回稳定错误码和可理解提示。缺失 OCR 配置时扫描页显示不支持/部分覆盖，不能以空片段进入笔记生成。

笔记生成流程：

1. 校验身份、课程关联、sourceVersions；资料版本已变化则409要求刷新。
2. 将选定资源版本、学习要求、模型配置版本写入任务快照，任务执行不能随课程后来变化扩大输入范围。
3. 读取所有选定资料的结构化片段；视频通过适配器读取对应学习结果和可核验来源。
4. 短资料一次生成；长资料按页/标题/时间段分批提取再合并。记录每个分块成功/失败，禁止只检索相似的少量块冒充整章总结。
5. 模型返回结构化 sections、citationKeys、warnings；引用键只能指向本次服务端提供的片段。资料内容视为数据，不执行资料内“忽略指令”等提示。
6. 校验 JSON、引用存在性和归属、内容非空、覆盖情况。格式失败允许一次修复；仍失败返回失败，不保存乱码为成功结果。
7. 合并结果保留引用；机械校验不等于事实完全正确，真实模型样本仍需人工复核。
8. 提交前重新校验来源权限/课程关联及取消状态，在同一事务写入笔记版本、来源关系、任务成功结果。唯一约束保证重投不生成重复版本。

笔记至少包含标题、摘要、核心知识点、重点难点、例子（资料没有则明确缺失）、易错点、来源与覆盖说明。用户要求优先；模型补充内容需标“补充解释”，不伪装来自课件。

coverage 必须保存 requestedResourceIds、usedResourceVersions、excludedResources[{id,reason}]、processedSegmentCount、totalSegmentCount、warnings。处理不全时必须标 PARTIAL，并让用户看到遗漏范围；不能用成功状态隐藏截断。

编辑 Markdown 时来源映射保留，只允许现有合法 citationKey；新增未知引用拒绝或标未核验，不允许客户端指定其他用户 segmentId。用户补充文字可以保存，标为用户编辑，不声称已核实。标题/正文使用安全 Markdown 渲染，禁用原始 HTML 或执行严格清洗。

## 9. 一致性、故障与权限

- 任务状态：QUEUED → RUNNING → SUCCEEDED/PARTIAL/FAILED/CANCELLED；等待原视频任务可用 WAITING_INPUT，释放执行线程并由恢复扫描续行。
- 心跳续租，过期任务可重领；fence 防止旧 Worker 晚提交。进程重启必须能从 DB 恢复，不以 Redis 临时键为唯一真源。
- 模型/网络暂时故障最多自动重试2次并退避；输入错误不自动重试。外部调用不可能保证 exactly-once，必须保证 DB 结果幂等并记录重复调用成本。
- 取消为协作式：停止后续分块和提交，尽力中断当前调用；不能承诺撤销已发生的模型费用。已完成解析可保留。
- 运行中移出/删除资料使待提交课程笔记任务终止为 SOURCE_CHANGED；既有笔记正文保留、引用显示失效，不提供已撤销来源正文。删除课程后任务不得成功写回课程。
- 每次读取、文件预览、引用解析、任务查询和提交都校验 owner；旧视频还需实时校验 media_files 存在性，不能只信映射表。
- 新任务并发、模型配额、解析进程与原视频分开控制。默认每用户1个笔记任务、全局2个新任务，部署可配置；长任务不能持有 DB 事务。
- 日志只记录 IDs、阶段、错误码、耗时和用量；不记录令牌、原文、完整提示或签名URL。记录 parser/model/prompt 版本便于复现。
- 文件默认私有，下载/预览经过授权或短效签名；API 不返回存储凭据。UI 显示来源失效不依赖后台物理清理是否完成。

## 10. 按顺序交付的任务包

一个 AI 每次执行一个包；每包完成后留下真实交接。不能为了展示进度把接口 stub、内存数组、TODO 解析器当生产实现。

| 编号 | 前置 | 内容和必交产物 | 验收 |
|---|---|---|---|
| W00 | 无 | 核对源码/环境、旧视频流程与测试基线，记录已有失败；创建 v2 STATUS.json | 基线命令输出、依赖/配置缺口可追踪 |
| W01 | W00 | 冻结本文 DTO/schema/错误码、样例文件与解析实验；输出 contracts.md、SQL 草案 | 三种现代格式样本真实可解析，视频结果读取契约明确 |
| W02 | W01 | 新迁移、实体 mapper、课程/章节 API 与权限；加入 /learn 鉴权/代理 | 双用户隔离、排序、删除及迁移验证 |
| W03 | W02 | 应用壳/课程首页/课程详情/空态；抽取原视频组件 | 登录后默认我的课程、浏览器前进后退、demo可用 |
| W04 | W03 | 视频映射、待归课、章节移动、课程内旧上传分析接入 | 旧视频无需重传；本地/链接上传及学习模式可用 |
| W05 | W04 | 文档上传、持久化任务、受限解析、内容预览、重试 | PDF/DOCX/PPTX 真文件端到端；重启恢复与坏文件失败 |
| W06 | W05 | 原视频结果适配、单资料笔记生成、来源校验及入库 | 视频/三种文档分别生成可定位的持久笔记 |
| W07 | W06 | 多资料分批归纳、覆盖记录、编辑版本、导出 | 同章混合资料总结、部分失败可见、并发编辑409 |
| W08 | W07 | 删除/移出竞态、隔离、回归、发布回退演练 | 本文验收用例通过，批次A可交付 |
| W09 | W08 | 扫描PDF OCR、DOC/PPT兼容及样本验收 | 批次B能力真实可用，限制公开 |

W02～W04 不得因未来向量库、课程聊天或考试复习未开发而阻塞。W01 若某现代格式解析不可行，记录具体阻塞并修正实现，不得静默缩减必做格式。

每包交接文件 `docs/course-workbench-v2/handoffs/Wxx.md` 必含：完成范围、变更文件、契约变化、实际测试命令/结果、未解决风险、下一包及必要上下文。台账最少含 taskId/status/dependsOn/changedFiles/checks/handoff；状态 TODO/IN_PROGRESS/BLOCKED/DONE；仅有实现且验收证据满足才 DONE。

## 11. 测试及完成标准

原项目测试入口（在各自目录执行，先检查运行时）：server `./mvnw.cmd test`；client `npm test`、`npm run build`；extension `node --test`。测试失败记录是既有还是新增；不得通过删除原测试掩盖回归。

新增测试应验证真实行为：迁移升级、数据库事务/唯一约束、接口权限、解析器样本、任务恢复及取消、版本冲突、引用定位、前端跨课程迟到响应。基础设施集成使用隔离测试库/桶，不能对用户生产数据执行测试清理。

必须人工或自动化运行并保留证据的验收场景：

1. 登录默认课程列表；创建两门课程及章节，刷新后保持。
2. 已有视频加入课程，播放/转写/学习分析/时间跳转仍可用；没有重复上传。
3. 课程内本地视频分片、断点续传、链接导入可用；归课失败后可重试关联已上传视频。
4. PDF/DOCX/PPTX 各至少两份真实样本成功；坏文件、加密文件、空文档、超限文件有明确失败。
5. 视频、PDF、Word、PPT 分别生成笔记且重开可读；引用跳至正确时间/页/段落/幻灯片。
6. 混合资料生成笔记覆盖所有选择内容；存在未就绪或失败资料时准确列出。
7. 修改笔记、读取旧版本、导出 Markdown；两个客户端并发保存不会静默覆盖。
8. 两个用户不能读取对方课程/资料/笔记/任务/引用；同用户不同课程不会混入来源。
9. 上传重复请求、Worker重启、重复领取、模型超时、取消、删除与生成并发不会产生重复成功结果或幽灵课程笔记。
10. 原四种模式、AUTO、追问、反馈修订、转写、音频导出、扩展、demo回归无新增失败。
11. 关闭新 UI 后原视频可用；重新开启不能访问关闭期间删除的视频副本。
12. 新文档负载下原视频仍能受理和处理；记录基线与对照时延/错误率，资源不足则调低新并发。

确定性 CI 使用模型 stub 验证编排；真实模型验收至少覆盖每种格式、混合总结、无依据、恶意指令文本和长资料覆盖，报告不能把 stub 成功写成真实模型质量合格。

## 12. 发布与工程交付要求

新配置放入示例环境文件并解释默认值，不提交密钥。开发、生产代理都覆盖 /learn；前端路由 fallback 仅匹配页面路径。先在有历史数据的副本演练新增迁移，采用新 UI 开关渐进启用，关闭开关不能删除新增内容。

回退优先关闭新入口和新任务执行，保留表与文件。旧二进制可能不认识新 Flyway 版本；若回退二进制，需要包含新 migration 的兼容回退构建并演练，不能临时删迁移记录或关校验。

最终交付至少包括：真实前后端代码、数据库迁移、锁定依赖、配置示例、接口契约样例、解析样本/测试、部署说明、任务交接与验收报告。模型/存储配置缺失时明确显示不可用，不以本地 mock 自动替代生产结果。

## 13. 可直接复制给下一位 AI 的启动指令

> 阅读 docs/course-workbench-v2.md，它是当前一期基线。目标是默认工作台展示我的课程，课程内上传视频/PDF/Word/PPT，由 Agent 生成带出处且持久化的学习笔记。原视频上传处理链路复用，课程专家与期末复习后续实现。先核实源码及 docs/course-workbench-v2/STATUS.json（不存在则从 W00 初始化），只执行当前最早未完成且依赖满足的 W 任务包。不要执行旧 learning-plan 的 T 台账，不要恢复“课程可选、视频首页默认”的旧方案。完成真实代码、必要测试和交接；未运行的测试明确标注。遇到具体契约缺口先记录并采用兼容的最小实现，不擅自扩展为完整 RAG/考试系统，不用占位和假数据替代交付。

## 14. 技术核实参考

- PDFBox：https://pdfbox.apache.org/ （PDF 文本提取与页面渲染）
- Apache POI：https://poi.apache.org/components/ （Word/PowerPoint 组件及支持限制）

这些是候选依赖依据，不表示本项目已集成。实施 W01 时重新核实版本与真实样本。
