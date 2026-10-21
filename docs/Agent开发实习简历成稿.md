# Agent 开发实习简历（成稿）

> 使用说明：将方括号内容替换为个人信息；项目部分可直接使用。默认控制在一页，投递 Agent / LLM 应用 / AI 后端开发实习。

## [姓名]

[手机] ｜ [邮箱] ｜ [所在城市] ｜ [GitHub/个人主页]

**求职意向：Agent 开发实习生 / LLM 应用开发实习生**

## 教育背景

**[学校名称]** ｜ [专业] ｜ [本科/硕士] ｜ [20XX.09–20XX.06]

- 主修课程：[数据结构、操作系统、计算机网络、数据库、机器学习等]
- [GPA / 排名 / 奖项；没有突出优势可删除本行]

## 专业技能

- **Agent / LLM：** 掌握 Planner–Executor–Critic、Function Calling、结构化输出、上下文管理、有限轮次反思与证据校验；具备 RAG、混合检索、Prompt 约束及幻觉治理实践。
- **后端：** 熟悉 Java 21、Spring Boot、Python、FastAPI，能够设计异步任务、幂等消费、分布式锁、限流、重试、Checkpoint 与失败补偿机制。
- **数据与中间件：** 熟悉 MySQL、Redis、MinIO、Qdrant、RocketMQ，理解关系数据、缓存、对象存储与向量数据库的职责边界。
- **工程与前端：** 熟悉 Vue 3、SSE、Docker Compose、Git；能够完成 Agent 应用从模型调用、后端编排到前端交互的端到端开发与测试。

## 项目经历

### DoVideoAI——有证据约束的长视频理解 Agent ｜ 个人项目 ｜ [20XX.XX–至今]

**技术栈：** Java 21、Spring Boot、LangChain4j、Python、FastAPI、Vue 3、RocketMQ、Redis/Redisson、MySQL、MinIO、Qdrant、FFmpeg、Tesseract、Docker Compose

- 面向课程、会议与操作录屏等长视频场景，设计并实现从上传、解析、检索到生成与追问的 **Video Agent**；将 ASR、OCR、关键帧及时间戳统一为 `VideoContext`，使生成结论可回溯至原视频证据。
- 构建 **Planner–Executor–Critic** 受控 Agent 工作流：Planner 将目标拆解为可检查任务，Executor 基于召回证据生成结构化结果，Critic 校验目标覆盖、输出结构与时间戳证据，并按缺失内容定向补证；通过最多 2 轮闭环约束延迟与 Token 成本。
- 针对长上下文设计分层检索：按 5 分钟聚合视频片段，结合关键词匹配与 Qdrant 向量召回筛选 Top-K 原始证据；当 Embedding 或向量服务异常时降级到本地检索，保证主链路可继续执行。
- 设计长耗时任务可靠性方案：前端按 5 MB 分片上传并支持断点续传，RocketMQ 异步削峰，Redisson 以“内容指纹 + 分析目标”实现并发去重；MySQL 持久化 Checkpoint、Redis 提供热缓存，支持任务重投与分阶段恢复。
- 将 FFmpeg 音频切片、ASR 与关键帧 OCR 组成双分支解析链路，使用独立有界线程池并行执行，并通过场景检测、30 秒保底采样和感知哈希去重兼顾信息覆盖与处理成本。
- 实现通用、学习、审查、创作 4 类分析模式及 Redis 多轮追问记忆；通过 Function Calling 按需查询时间段证据，设置工具调用次数、证据条数与上下文预算，降低无效调用和无依据生成。
- 完善 SSE 阶段进度、失败任务落库与重试、用户级/全局限流、指数退避及安全 Markdown 渲染；编写 Java/Python/前端测试，覆盖幂等、租约 fencing、取消、引用伪造、无证据降级和预算终止等关键边界。

**项目链接：** https://github.com/Xiaoc7r/DOVideo-AI

## 自我评价

- 对 Agent 的理解不止于 Prompt 调用，关注证据、状态、工具、预算和终止条件等可控边界，能够把模型能力落到可恢复、可观测的工程链路中。
- 具备独立拆解复杂需求和端到端交付能力，重视真实验收与能力边界，不以 Mock 结果替代模型、检索或中间件的实际可用性。
- [补充一项与你本人一致的特点，例如：持续关注 Agent/RAG 论文与开源框架，并能通过项目快速验证方案。]

---

## 一页简历空间不足时的精简项目版

### DoVideoAI——有证据约束的长视频理解 Agent ｜ 个人项目

**Java 21 / Spring Boot / LangChain4j / Python / Vue 3 / RocketMQ / Redis / Qdrant / MinIO**

- 设计并实现长视频理解 Agent，将 ASR、OCR、关键帧与时间戳融合为统一 `VideoContext`，支持课程笔记、内容审查、创作提炼及多轮追问，所有核心结论均可定位至原视频证据。
- 构建 Planner–Executor–Critic 有限闭环，通过任务拆解、结构化生成、证据校验与定向补证提升目标覆盖；限制最多 2 轮执行，并配置 Token、工具调用和上下文预算控制成本。
- 采用“5 分钟片段摘要 + 关键词/Qdrant 向量召回 + Top-K 原始证据”处理长上下文，向量服务异常时自动降级；结合 Function Calling 按需补充指定时间段证据。
- 以 RocketMQ、Redisson 和 MySQL/Redis Checkpoint 构建异步、幂等、可恢复任务链路，并实现 5 MB 分片续传、SSE 进度、失败重试、限流及指数退避。

## 面试时的 30 秒项目介绍

DoVideoAI 是一个面向课程、会议和操作录屏的长视频理解 Agent。它不会直接把整段视频交给模型，而是先用 ASR 和关键帧 OCR 生成带时间戳的统一证据，再通过关键词与向量混合检索找到相关片段，最后由 Planner、Executor 和 Critic 完成任务拆解、结构化生成和证据校验。工程上我用分片上传、RocketMQ、幂等锁和 Checkpoint 解决长耗时链路的重复执行与断点恢复问题，并通过轮次、Token 和工具预算控制 Agent 成本。

## 投递前必须补充的量化信息

以下数据应使用真实测试结果填写，不建议估算：

- 典型视频时长、端到端处理耗时及优化前后对比。
- 混合检索 Recall@K、回答证据支持率或人工评测结果。
- 并发数、重复消息场景下的幂等成功率、故障恢复耗时。
- 测试用例数量与真实通过情况；区分离线测试、真实模型测试和端到端联调。

当前仓库已能证明的参数包括：5 MB 上传分片、60 秒音频切片、30 秒关键帧保底采样、5 分钟检索分块、最多 2 轮 AgentLoop、4 类分析模式。课程学习 Agent 的真实模型与完整中间件联调仍有待验收，不应写成已生产上线。
