# 统一文档模块

此模块包含统一文档解析，以及父子分块、本地 BGE-M3 embedding、Qdrant
dense + BM25 索引、版本发布和授权检索。运行时固定使用项目的 Python 3.12
环境和本地模型；不会隐式下载模型。

## 使用

从仓库根目录执行，输入已经生成的 Docling `export_to_dict()` JSON：

```powershell
python -m knowledge_service.main input.json --kind docling --source-type PDF --revision rev-001 --output artifacts/rev-001
```

现有 Java `VideoContext`（source、segments；每个片段含 startMs、endMs、transcript、ocrTexts、evidenceFrames）：

```powershell
python -m knowledge_service.main video-context.json --kind video --revision rev-002 --output artifacts/rev-002
```

输出 `document.json`（包含完整元素、定位与质量信息的权威结构）、`content.md`（可读内容）、`manifest.json`（UTF-8 文件哈希）。分块和检索 metadata 由 `document.json` 派生，不长期保存重复的元素或原始解析文件。
目录通过同文件系统重命名发布，避免读到半份 JSON/MD；相同结果重复保存幂等，不覆盖不同结果。
输出路径由调用者提供，不使用资料名称拼接。部署时调用者需限制为可信工作目录。

## 接口

- `normalize_docling(payload, revision, source_type)`：按 body 引用树遍历；不会按 texts/tables 数组分别拼接。
- `normalize_video(payload, revision)`：复用既有视频处理结果，不重新下载或转写视频。
- `convert_document(path, revision, converter)`：接受调用方显式传入的 Docling 兼容 converter；只有转换状态 success 才继续。
- `save_artifacts(document, destination)`：一致保存三份规范产物。

直接处理 PDF/DOCX/PPTX 需要调用方已安装并配置好的 Docling converter。
本模块不创建默认 converter，因为其模型初始化可能联网下载。converter 的本地模型配置、OCR 引擎和网络策略由调用方管理。
DOC/PPT 旧格式仍需外部转换。PDF/DOCX/PPTX/VIDEO 的解析产物会由
`agent_service.worker` 自动进入索引状态机，只有发布成功后才标记 `READY`。

## 数据约定

`document.json` 是后续分块依据；MD 从完全相同的 elements 生成，并带稳定元素锚点。
ID 由资料版本及来源元素引用确定；规则变化另建产物版本目录，不原地覆盖。
PDF/幻灯片定位从 Docling 的一基 page_no 转成零基 pageIndex；保留 bbox 及坐标原点。
Word 使用元素定位，不把排版页码视为稳定位置。视频时间为毫秒，精度不超出现有片段范围。
原始 charspan 保留为 parserCharSpan，不宣称是导出 MD 的字符偏移。

表格保留原始单元格结构，普通表格输出 Markdown；合并单元格输出内嵌 HTML 表格。
图片保存 image/annotations/meta 引用，不联网读取，不伪造图像描述。视频保存关键帧引用。
未知元素保留原始对象并标记；缺页码、空内容、替换字符等进入 qualityFlags。
Docling 无法从当前导出证明原生提取/OCR 的元素保持 extractionMethod=UNKNOWN。
VideoContext 不包含完整失败区间清单，因此标记 UPSTREAM_COMPLETENESS_UNKNOWN。
该模块不做语义校对或保证解析完整；调用方应结合转换阶段状态审核 qualityFlags。
Markdown/内嵌 HTML 用于阅读和模型输入；网页展示必须经前端安全渲染/清洗。

## 测试（不安装依赖）

```powershell
python -m unittest discover -s knowledge_service/tests -v
```

如果当前沙箱的系统临时目录不可写，可在本次 PowerShell 会话中将 TEMP/TMP
设置为工作区内的测试目录后运行（不改系统环境配置）：

```powershell
$env:TEMP = (Resolve-Path knowledge_service/tests).Path
$env:TMP = $env:TEMP
python -m unittest discover -s knowledge_service/tests -v
```

测试覆盖阅读顺序、稳定 ID、引用、表格及合并单元格、视频时间、损坏引用、幂等写入和 CLI。
使用合成 Docling 导出契约及模拟 converter；真实 Docling、OCR 和真实文件转换需在依赖与模型已经准备好的环境做集成验证。
