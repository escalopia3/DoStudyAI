# Windows 环境准备与第一闭环验收

2026-10-13。本次只提供安装步骤，没有下载或启动任何环境。以下命令由你准备好后执行；npm、Maven、Docker首次运行相应命令会下载依赖/镜像。

## 1. 需要哪些环境

| 项目 | 选择与用途 |
|---|---|
| JDK | 推荐JDK21，与server/pom.xml和CI一致；需要完整JDK而非JRE。此前找到D:/java为JDK26，但未验证其对现有Lombok/测试工具的兼容性，不作为本次验收基线 |
| Node.js + npm | 使用Node24 LTS；当前机器已能运行Node24.18.0，可继续使用，不必重复安装Node。缺的是client/node_modules里的项目依赖 |
| Docker Desktop | Windows版，启用WSL2/Linux containers；使用仓库Compose运行中间件 |
| MySQL/Redis/MinIO/RocketMQ/Qdrant | 按现有docker-compose.yml固定配置启动，无需逐个下载安装程序；原应用启动与视频能力仍依赖这些服务 |
| FFmpeg/ffprobe | 仅上传归档不调用；测试原视频转写、音频导出、分析需要。把可执行文件目录加入PATH（仅配置FFMPEG_DIR不足以覆盖原代码全部调用） |
| yt-dlp | 测试在线视频链接导入需要；可用Windows独立exe，不必仅为它安装Python。配置YTDLP_PATH或加入PATH |
| Tesseract OCR | 测试原视频画面文字提取需要，安装中文简体chi_sim及英文eng语言数据；配置OCR_COMMAND或加入PATH |
| 模型API Key | 课程/章节/文档归档不调用模型；原视频转写、分析需配置供应商有效密钥和可用模型 |

官方下载/说明入口：

- [Temurin JDK21](https://adoptium.net/temurin/releases/?version=21)：选择Windows x64、JDK、21。
- [Node.js](https://nodejs.org/en/download)：已有可用Node24时无需重复安装。
- [Docker Desktop Windows](https://docs.docker.com/desktop/setup/install/windows-install/)：按官方WSL与系统要求安装、启动Linux容器后端。
- [FFmpeg](https://ffmpeg.org/download.html)：使用其Windows构建入口。
- [yt-dlp安装说明](https://github.com/yt-dlp/yt-dlp#installation)：部分网站另需登录cookie/JS运行时，跟随站点与工具诊断，不承诺所有URL均能下载。
- [Tesseract安装说明](https://tesseract-ocr.github.io/tessdoc/Installation.html)：Windows发行包及语言数据按官方文档指向安装。

Maven不必单独安装，server/mvnw.cmd会使用仓库固定的Maven3.9.12。首次需要联网。IDE可选，不需要为本项目另装IDE。

## 2. 检查版本与路径

新开PowerShell，检查：

```powershell
java -version
javac -version
node --version
npm --version
docker version
docker compose version
```

JDK安装后设置JAVA_HOME到实际JDK21目录，把其bin目录加入PATH；重开终端。不要照抄并不存在的安装路径。视频工具装好后验证 `ffmpeg -version`、`ffprobe -version`、`yt-dlp --version`、`tesseract --list-langs`（包含eng与chi_sim）。

## 3. 创建并填写配置

```powershell
Set-Location D:\DOVideo-AI-main
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

使用编辑器修改根目录.env，不覆盖已有正确配置，不提交密钥。必须将以下示例密码替换为自己的值：DB_PASSWORD、MYSQL_ROOT_PASSWORD、REDIS_PASSWORD、MINIO_SECRET_KEY、QDRANT_API_KEY。DB_USERNAME和MYSQL_APP_USER保持一致（示例均为dovideo）。MINIO_ACCESS_KEY沿用示例或自行修改。

DB_URL保留本项目Compose的3307端口，MinIO为9000、Redis为6379。现有MySQL数据目录的账户密码不会随.env自动重置；有历史数据时使用原密码，不删除数据目录“修复”。

SILICONFLOW_API_KEY用于原视频AI能力。只验收课程创建和上传时，可暂填非空占位值 `local-upload-only` 以满足模型客户端配置；该值不能调用模型，不要点击转写/分析。运行时若供应商客户端拒绝占位值，需提供有效密钥；不能把启动或模型失败报成验收通过。完整视频兼容验收必须使用有效密钥。

新课程首页开关 `VITE_COURSE_WORKBENCH_ENABLED=true` 默认开启。设置false并重启Vite/重新构建可回到旧视频界面，不删除课程数据。生产中 /learn 与原 /media、/analysis 一样反向代理到后端，不能返回前端index.html。

新增 scripts/load-env.ps1 只加载字面量KEY=VALUE，支持外层单/双引号，不执行命令替换，不支持内联注释或变量插值。使用新PowerShell窗口时需要重新加载；Spring Boot本身不会自动读取根.env。

## 4. 启动中间件

先启动Docker Desktop，然后在项目根目录执行：

```powershell
.\scripts\dev-up.ps1
```

脚本检查配置、初始化RocketMQ命名卷权限、启动Compose、等待Broker注册并创建原分析主题。与已有Bash脚本目的相同，不创建新终端，不启动前后端。

脚本未在本机Docker环境执行过，仅做语法检查。若PowerShell执行策略阻止本地脚本，可在当前会话采用符合你设备管理规则的脚本执行设置后再运行，或使用已配置的PowerShell开发终端。

启动后检查：

```powershell
docker compose ps
docker compose logs --tail 80 mysql minio rmqbroker
```

MinIO后端初始化会自动创建media桶，保持私有即可，无需设置公开读取。

## 5. 安装项目依赖并运行测试

以下步骤会下载依赖，是你之后执行的步骤，不是本轮已执行结果。

PowerShell终端A：

```powershell
Set-Location D:\DOVideo-AI-main
.\scripts\load-env.ps1
Set-Location server
.\mvnw.cmd test
```

PowerShell终端B：

```powershell
Set-Location D:\DOVideo-AI-main\client
npm ci
npm test
npm run build
```

后端测试包含新增CourseServiceTest和DocumentUploadValidatorTest。若在JDK21仍出现失败，保存测试报告和错误后修复，不跳过测试直接宣布完成。前端新增测试已由现有src/*.test.js命令自动纳入。

## 6. 启动后端和前端

终端A（先确认加载.env）：

```powershell
Set-Location D:\DOVideo-AI-main
.\scripts\load-env.ps1
Set-Location server
.\mvnw.cmd spring-boot:run
```

默认后端端口9090。第一次启动Flyway执行尚未执行的迁移，包括V4课程基础表和V5上传指纹。先备份旧数据库或使用副本；不用手动重复运行SQL，更不能修改flyway_schema_history来跳过失败。

终端B：

```powershell
Set-Location D:\DOVideo-AI-main\client
npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

浏览器打开 http://127.0.0.1:5173 。使用固定5173避免端口自动递增后与CORS白名单不一致。

## 7. 验收第一闭环

1. 注册/登录，默认显示“我的课程”，创建课程并进入。
2. 创建第一章，分别上传本地视频、PDF、DOCX、PPTX，刷新页面确认都存在且归属正确。
3. 在全部/未分章/第一章切换，检查类型筛选。
4. 同一PDF重新选择上传，确认同一目标位置没有新增重复记录；原文件可获取。
5. 加入旧视频，确认无需重传；视频播放/分析、转写、音频导出和删除入口可用（处理能力需要相应工具/密钥）。
6. 用另一个账号确认看不到第一账号课程；直接访问其课程ID也被拒绝。
7. 上传中取消/断网再恢复，按提示重试；已经保存但归课失败的视频通过“加入已有视频”重试。

文档显示“已上传 · 待接入解析”是本次正确状态，不会自动生成笔记。完成这些真实验收后再更新STATUS.json中的releaseAccepted。
