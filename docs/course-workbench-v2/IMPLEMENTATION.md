# 第一闭环：实现说明与交接

日期：2026-10-13。范围为用户最新指定的“登录 → 我的课程 → 新建/进入课程 → 创建章节 → 上传/加入资料”。这次没有下载或安装环境。代码收尾已写入，环境相关验收尚未执行，不应把它标为完整上线验收通过。

## 产品行为

- 复用原登录/注册/退出与令牌机制，正常登录后的默认工作台是课程列表。
- 创建课程（名称、学期、简介），进入课程，创建章节，按全部/未分章/章节筛选资料。
- 本地视频沿用原分片上传、续传和合并；链接导入沿用 /media/upload-url。成功后将原 mediaId 关联到当前课程和章节。
- 已有视频通过“加入已有视频”关联，不复制文件、不重新处理。归课失败可从待归课视频重试。
- PDF/DOCX/PPTX 上传到 MinIO 并归档，支持获取原文件。文档不超过50 MiB，每批最多10个文件；批量逐个处理，逐文件显示结果。
- 课程视频卡片接入原播放/分析、转写、音频下载与删除。分析侧栏和 SSE 继续复用；资料列表每10秒刷新，后台任务通过 activeTasks 展示。
- 文档只标“已上传 · 待接入解析”。本次不包含文档原文解析、Agent笔记、课程问答或复习。

## 前端

`client/src/App.vue` 保留账号与旧视频工作区状态，正常模式挂载 `features/courses/CourseWorkbench.vue`；原首页用于既有 demo 或显式关闭 VITE_COURSE_WORKBENCH_ENABLED 的回退。课程卡片通过事件调用原 openAgent/transcribe/downloadAudio/deleteItem，不另写视频处理逻辑。

课程组件负责列表/表单/章节/文件上传。`courseApi.js` 复用 api.js，保留 Bearer、Result 解包、401失效和非JSON响应透传；错误附 HTTP status，便于区分上传409与网络故障。

导航使用 `?course=<id>` 与 History API；保留其他查询参数和 #video-t=，支持前进后退，未引入 Router。与规划 pathname 方案不同，这是当前闭环为避免新增依赖采用的已记录实现选择。

刷新由 `refreshLoop.js` 在上次请求结束后再计时，页面隐藏/上传中不轮询。请求 generation + loadSequence + captureAuthSession 共同拦截跨课程、过期列表和旧账号响应；卸载会停止定时器并中止请求。用户可手动刷新，切回页面或恢复网络时也刷新。

`uploadReceipts.js` 按用户、课程、章节及文件元数据保存随机请求键，重新选择同一文件会复用键。后端实际校验内容哈希，客户端元数据不是可信文件身份。同键内容冲突返回409，并清除此键供下次明确重试；网络失败不清键。存储禁用时降级为页面内缓存，不承诺跨刷新幂等。

课程视频ID为字符串，调用旧侧栏时尽量使用原媒体列表项，避免旧数字ID和新字符串ID的严格比较冲突。删除成功同时刷新课程列表，旧删除失败不虚报成功。音频下载在账号切换后不触发过期结果下载。

## 后端与数据库

`learning/CourseController` 提供新 /learn 接口，`CourseService` 处理授权/事务/归属，`CourseRepository` 使用现有数据源的 JdbcTemplate 参数化SQL。视频 MediaService 和其 MyBatis 数据模型保持复用；没有把文档塞进 media_files。

迁移 V4 新增四张表：

| 表 | 用途 |
|---|---|
| courses | 用户私有课程 |
| course_chapters | 课程章节，创建时分配排序值 |
| learning_resources | 统一资料身份，视频引用旧mediaId，文档保存MinIO对象键 |
| course_resources | 资料与课程/章节关联，一份资料最多归一门课程 |

迁移 V5 增加 request_fingerprint，用于绑定文档上传请求内容和目标位置；未改已写入的V4迁移。当前数据库是否已执行迁移尚未核实，启动由Flyway正常执行。

课程归属校验基于 AuthService.REQUEST_USER_ID，不信任客户端userId；章节必须属于课程。新JSON DTO中的ID转为字符串，旧API序列化不变。/learn 已加入 WebConfig 鉴权范围和 Vite代理。

创建章节锁课程行并在事务内分配 sort_order。视频归课锁原media行，检查现有映射，同位置重复请求返回原映射，其他课程/章节冲突返回409。资料列表和获取视频原文件时重新检查旧视频存在性，旧视频删除后不会因为残留映射继续显示。

文档上传流程：

1. 检查用户课程及章节、50 MiB限制、扩展名和文件结构。
2. PDF只做文件头初筛；DOCX/PPTX检查ZIP核心条目，限制条目数/展开量并拒绝宏；这不是完整解析或内容质量验证。
3. SHA-256指纹涵盖文件字节、名称、大小、课程及章节。同用户同请求键相同指纹直接返回原资料；不同指纹409。
4. 文件先写入独立 `learning/<userId>/` 前缀，存储I/O不持有数据库事务。
5. 数据库事务锁用户行后再次检查请求键，提交资料和关联。并发重复请求只保留一个资料记录，清理本次多余对象。
6. 异常后检查对象是否已提交：数据库确认无关联才清理；数据库不可达/提交结果不确定时保留对象并记日志，避免误删已成功上传的文件。

尚未添加自动孤儿对象巡检；极端进程崩溃或清理失败可能留下独立前缀中的孤儿对象，通过日志追踪，不能声称存储与数据库是分布式原子事务。

## 当前接口

GET/POST /learn/courses；GET /learn/courses/{id}；POST /learn/courses/{id}/chapters；GET /learn/courses/{id}/resources；GET /learn/available-videos；POST /learn/courses/{id}/videos；POST /learn/courses/{id}/documents；GET /learn/resources/{id}/file。

文档接口同步完成上传与入库，返回 Result 成功及资料ID（不是解析任务202）；没有实现后续解析任务。当前章节只有创建、课程只有创建/查看，重命名/删除/调整排序/资料移动不属于本次最小闭环，后续另做。

## 已执行检查

- 前端离线：`node --test src/api.test.js src/chunkUpload.test.js src/taskEvents.test.js src/courseWorkbench.test.js`，22项通过，包括7项新增课程支持逻辑测试。
- 扩展：`node --test`，54项通过。
- App.vue/CourseWorkbench.vue 的 script setup 经Node语法检查通过；这不等价于Vue模板编译或浏览器渲染测试。
- 新增后端 `CourseServiceTest`、`DocumentUploadValidatorTest` 共12项测试，覆盖所有权、错章节、归课冲突/重复、上传指纹/重试、数据库失败清理、格式检查。尚未执行。
- 原视频工作区另补1项字符串/数字ID删除回归测试，需Vue依赖，尚未执行；两份Windows脚本已通过PowerShell语法检查，未实际启动服务。

## 环境就绪后必须补的验收

1. JDK21下后端全量测试与编译；安装前端锁定依赖后全量测试及生产构建。
2. 含历史数据的MySQL副本执行V4/V5，确认原media数据不变。
3. 两用户真实登录隔离；创建课程/章节、刷新页面仍存在。
4. 本地视频/链接视频/已有视频归课、播放分析、转写、音频、删除。
5. PDF/DOCX/PPTX真实文件上传/下载；同请求键同内容只一条记录，错误章节/其他用户不可访问。
6. 上传完成响应丢失再重试、切换账号、浏览器前进后退、批量部分失败。
7. 浏览器布局/键盘交互、网络错误提示和旧demo回归。

不改旧T系列台账。本目录 STATUS.json 记录本次窄范围，不能等同于完整W00～W09完成。
