"""Normalize exported Docling JSON or the Java VideoContext contract.

No imports of Docling, model initialization, downloads or network calls occur here.
Document conversion can be supplied explicitly through ``convert_document``.
"""

from copy import deepcopy
from hashlib import sha256
from html import escape
import json
import math
from pathlib import Path
import re
import tempfile
from typing import Any, Protocol

from knowledge_service.models import DocumentElement, NormalizedDocument


class NormalizationError(ValueError):
    """The parser output cannot safely be normalized."""


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"


def _text(value: Any, field: str = "text") -> str:
    if not isinstance(value, str):
        raise NormalizationError(f"{field} must be a string")
    return value.replace("\r\n", "\n").replace("\r", "\n")


def _integer(value: Any, field: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise NormalizationError(f"{field} must be an integer >= {minimum}")
    return value


def _identifier(revision: str, ref: str) -> str:
    return "el-" + sha256((revision + "\0" + ref).encode()).hexdigest()[:24]


def _revision(value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise NormalizationError("resourceRevisionId is required")


def _resolve(payload: dict, ref: str) -> dict:
    if not isinstance(ref, str) or not ref.startswith("#/"):
        raise NormalizationError(f"Invalid local JSON reference: {ref!r}")
    node: Any = payload
    try:
        for part in ref[2:].split("/"):
            part = part.replace("~1", "/").replace("~0", "~")
            if isinstance(node, list):
                if not part.isdigit():
                    raise ValueError("Invalid index")
                node = node[int(part)]
            else:
                node = node[part]
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise NormalizationError(f"Unresolved reference: {ref}") from exc
    if not isinstance(node, dict):
        raise NormalizationError(f"Reference is not an object: {ref}")
    return node


def _locators(item: dict, ref: str, source_type: str) -> list[dict]:
    result = []
    for prov in item.get("prov", []):
        page = _integer(prov.get("page_no"), "page_no", 1) - 1
        # DOCX layout is not a stable page coordinate system.
        if source_type in {"DOC", "DOCX"}:
            loc = {"type": "DOCUMENT_ELEMENT", "elementRef": ref, "parserPageIndex": page}
        else:
            kind = "SLIDE" if source_type in {"PPT", "PPTX"} else "PAGE"
            loc = {"type": kind, "pageIndex": page}
        if "bbox" in prov:
            bbox = prov["bbox"]
            for key in ("l", "t", "r", "b"):
                value = bbox.get(key)
                if type(value) not in (int, float) or not math.isfinite(value):
                    raise NormalizationError(f"Invalid bounding box at {ref}")
            loc["bbox"] = deepcopy(bbox)
        if "charspan" in prov:
            loc["parserCharSpan"] = deepcopy(prov["charspan"])
        result.append(loc)
    return result or [{"type": "DOCUMENT_ELEMENT", "elementRef": ref}]


def _table(data: dict) -> tuple[str, list[str]]:
    rows = _integer(data.get("num_rows"), "num_rows")
    cols = _integer(data.get("num_cols"), "num_cols")
    if rows * cols > 100_000:
        raise NormalizationError("Table exceeds 100000 cell budget")
    cells = data.get("table_cells", [])
    if not rows or not cols:
        if cells:
            raise NormalizationError("Nonempty table has zero dimensions")
        return "[空表格]", ["EMPTY_TABLE"]
    grid = [[""] * cols for _ in range(rows)]
    occupied: set[tuple[int, int]] = set()
    merged = False
    html_rows: dict[int, list[tuple[int, str]]] = {i: [] for i in range(rows)}
    for cell in cells:
        r = _integer(cell.get("start_row_offset_idx"), "start_row_offset_idx")
        c = _integer(cell.get("start_col_offset_idx"), "start_col_offset_idx")
        end_r = _integer(cell.get("end_row_offset_idx"), "end_row_offset_idx", 1)
        end_c = _integer(cell.get("end_col_offset_idx"), "end_col_offset_idx", 1)
        if not (r < end_r <= rows and c < end_c <= cols):
            raise NormalizationError("Invalid table cell range")
        positions = {(i, j) for i in range(r, end_r) for j in range(c, end_c)}
        if positions & occupied:
            raise NormalizationError("Overlapping table cells")
        occupied.update(positions)
        value = _text(cell.get("text", ""))
        grid[r][c] = value.replace("\\", "\\\\").replace("|", "\\|").replace("\n", "<br>")
        tag = "th" if cell.get("column_header") else "td"
        html_rows[r].append((c, f'<{tag} rowspan="{end_r-r}" colspan="{end_c-c}">{escape(value)}</{tag}>'))
        merged |= end_r - r > 1 or end_c - c > 1
    flags = [] if len(occupied) == rows * cols else ["INCOMPLETE_TABLE_GRID"]
    if merged:
        # Markdown tables cannot represent merged cells: retain HTML and raw cells.
        return "<table>\n" + "\n".join(
            "<tr>" + "".join(value for _, value in sorted(html_rows[r])) + "</tr>"
            for r in range(rows)
        ) + "\n</table>", flags
    # Only use the first row as a header if the source explicitly marks all cells.
    first_row = [c for c in cells if c["start_row_offset_idx"] == 0]
    has_header = bool(first_row) and all(c.get("column_header", False) for c in first_row)
    header, body = (grid[0], grid[1:]) if has_header else ([""] * cols, grid)
    lines = [header, ["---"] * cols, *body]
    return "\n".join("| " + " | ".join(row) + " |" for row in lines), flags


def normalize_docling(payload: dict, resource_revision_id: str, source_type: str) -> NormalizedDocument:
    """Walk Docling's body tree, never concatenate its separate item arrays."""
    _revision(resource_revision_id)
    source_type = source_type.upper()
    if payload.get("schema_name") != "DoclingDocument":
        raise NormalizationError("Expected a DoclingDocument export")
    if not isinstance(payload.get("body"), dict):
        raise NormalizationError("Docling body is required")
    elements: list[DocumentElement] = []
    headings: list[tuple[int, str]] = []
    visited: set[str] = set()
    active: set[str] = set()

    def walk(ref: str, depth: int = 0) -> None:
        if depth > 100:
            raise NormalizationError("Document nesting exceeds 100 levels")
        if ref in active:
            raise NormalizationError(f"Cyclic body reference: {ref}")
        if ref in visited:
            return
        active.add(ref)
        visited.add(ref)
        item = _resolve(payload, ref)
        label = item.get("label", "")
        if ref.startswith("#/groups/") or ref == "#/body":
            for child in item.get("children", []):
                walk(child["$ref"], depth + 1)
            active.remove(ref)
            return
        content = _text(item.get("text", ""))
        flags: list[str] = []
        data: dict[str, Any] = {"sourceLabel": label}
        kind = "PARAGRAPH"
        if label in {"title", "section_header"}:
            level = 1 if label == "title" else _integer(item.get("level", 1), "heading level", 1)
            while headings and headings[-1][0] >= level:
                headings.pop()
            headings.append((level, content))
            data["level"] = level
            content = "#" * min(level, 6) + " " + content
            kind = "HEADING"
        elif label == "table":
            data["table"] = deepcopy(item.get("data", {}))
            content, flags = _table(data["table"])
            kind = "TABLE"
        elif label == "picture":
            kind = "IMAGE"
            # Do not fetch URIs or fabricate picture descriptions.
            data["image"] = deepcopy(item.get("image"))
            data["annotations"] = deepcopy(item.get("annotations", []))
            data["meta"] = deepcopy(item.get("meta", {}))
            content = content or "[图片：参见原资料]"
            flags.append("IMAGE_REQUIRES_REVIEW")
        elif label == "list_item":
            kind = "LIST_ITEM"
            marker = str(item.get("marker") or "-")
            data["marker"] = marker
            content = marker + " " + content
        elif label == "code":
            kind = "CODE"
            longest = max((len(m.group()) for m in re.finditer(r"`+", content)), default=0)
            fence = "`" * max(3, longest + 1)
            content = f"{fence}\n{content}\n{fence}"
        elif label == "formula":
            kind = "FORMULA"
            content = "$$\n" + content + "\n$$"
        elif label not in {"text", "paragraph", "caption", "footnote", "page_header", "page_footer"}:
            kind = "UNKNOWN"
            flags.append("UNSUPPORTED_ELEMENT")
            data["raw"] = deepcopy(item)
        if not content.strip():
            flags.append("EMPTY_CONTENT")
        if "\ufffd" in content:
            flags.append("REPLACEMENT_CHARACTER")
        if not item.get("prov"):
            flags.append("NO_PAGE_LOCATION")
        data["contentLayer"] = item.get("content_layer", "body")
        data["captionRefs"] = deepcopy(item.get("captions", []))
        elements.append(DocumentElement(
            _identifier(resource_revision_id, ref), kind, content,
            [title for _, title in headings], [ref], _locators(item, ref, source_type),
            "UNKNOWN", flags, data,
        ))
        for child in item.get("children", []):
            walk(child["$ref"], depth + 1)
        for caption in item.get("captions", []):
            if caption["$ref"] not in visited:
                walk(caption["$ref"], depth + 1)
        active.remove(ref)

    walk("#/body")
    document = NormalizedDocument(resource_revision_id, _text(payload.get("name", "")),
                                  source_type, {"name": "docling", "schemaVersion": str(payload.get("version", "unknown"))}, elements)
    if not elements:
        document.qualityFlags.append("EMPTY_DOCUMENT")
    # Detect parser items omitted by the body tree instead of claiming full coverage.
    for collection in ("texts", "tables", "pictures"):
        for index, item in enumerate(payload.get(collection, [])):
            if f"#/{collection}/{index}" not in visited and item.get("content_layer") != "furniture":
                document.qualityFlags.append("UNREFERENCED_ITEMS")
                break
    if any(item.qualityFlags for item in elements):
        document.qualityFlags.append("ELEMENTS_REQUIRE_REVIEW")
    return document


def normalize_video(payload: dict, resource_revision_id: str) -> NormalizedDocument:
    """Accept the existing Java VideoContext JSON; retain segment-level timestamps."""
    _revision(resource_revision_id)
    segments = payload.get("segments")
    if not isinstance(segments, list):
        raise NormalizationError("VideoContext.segments must be a list")
    elements = []
    previous_start = -1
    for index, segment in enumerate(segments):
        start = _integer(segment.get("startMs"), "startMs")
        end = _integer(segment.get("endMs"), "endMs")
        if end <= start or start < previous_start:
            raise NormalizationError("Video segments must have valid, ordered time ranges")
        previous_start = start
        transcript = _text(segment.get("transcript", ""))
        ocr = segment.get("ocrTexts", [])
        frames = segment.get("evidenceFrames", [])
        if not isinstance(ocr, list) or not isinstance(frames, list):
            raise NormalizationError("ocrTexts and evidenceFrames must be lists")
        ocr = [_text(text, "ocrTexts entry") for text in ocr]
        frames = [_text(frame, "evidenceFrames entry") for frame in frames]
        ref = f"#/segments/{index}"
        content = []
        if transcript.strip():
            content.append("**语音转写**\n\n" + transcript)
        if any(text.strip() for text in ocr):
            content.append("**画面文字**\n\n" + "\n\n".join(text for text in ocr if text.strip()))
        elements.append(DocumentElement(
            _identifier(resource_revision_id, ref), "VIDEO_SEGMENT", "\n\n".join(content), [], [ref],
            [{"type": "VIDEO", "startMs": start, "endMs": end}], "ASR_OCR",
            [] if content else ["EMPTY_CONTENT"],
            {"transcript": transcript, "ocrTexts": ocr, "evidenceFrames": frames},
        ))
    flags = ["UPSTREAM_COMPLETENESS_UNKNOWN"]
    if not elements:
        flags.append("EMPTY_DOCUMENT")
    if any(item.qualityFlags for item in elements):
        flags.append("ELEMENTS_REQUIRE_REVIEW")
    return NormalizedDocument(resource_revision_id, _text(payload.get("source", "video")), "VIDEO",
                              {"name": "java-video-context", "schemaVersion": "1"}, elements, qualityFlags=flags)


def save_artifacts(document: NormalizedDocument, destination: Path) -> Path:
    """Publish an immutable artifact directory, with a hash manifest, by rename.

    Reusing an identical result is idempotent. Different results require a new path.
    """
    destination = Path(destination)
    files = {
        "document.json": _json(document.to_dict()),
        "content.md": document.to_markdown(),
    }
    manifest = {"schemaVersion": "1", "resourceRevisionId": document.resourceRevisionId,
                "files": {name: sha256(value.encode("utf-8")).hexdigest() for name, value in files.items()}}
    files["manifest.json"] = _json(manifest)
    if destination.exists():
        if destination.is_dir() and all((destination / name).is_file() and
                (destination / name).read_bytes() == content.encode("utf-8") for name, content in files.items()):
            return destination
        raise FileExistsError(f"Artifact destination already contains different data: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".normalizing-", dir=destination.parent) as staging:
        bundle = Path(staging) / "bundle"
        bundle.mkdir()
        for name, content in files.items():
            (bundle / name).write_bytes(content.encode("utf-8"))
        bundle.rename(destination)
    return destination


class Converter(Protocol):
    def convert(self, source: Path) -> Any: ...


def convert_document(source: Path, resource_revision_id: str, converter: Converter) -> tuple[NormalizedDocument, dict]:
    """Use an explicitly supplied, locally configured Docling-compatible converter.

    The caller owns its dependencies/models/network policy; this function never
    constructs a default converter, which could implicitly fetch model artifacts.
    """
    source = Path(source)
    if not source.is_file():
        raise FileNotFoundError(source)
    result = converter.convert(source)
    status = getattr(result.status, "value", result.status)
    if status != "success":
        raise NormalizationError(f"Document conversion did not fully succeed: {status}")
    raw = result.document.export_to_dict()
    return normalize_docling(raw, resource_revision_id, source.suffix.lstrip(".")), raw
