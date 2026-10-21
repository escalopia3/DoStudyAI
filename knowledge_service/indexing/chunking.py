from __future__ import annotations

from dataclasses import asdict, dataclass, field
from hashlib import sha256
import json
import re
from typing import Any, Callable


TokenCounter = Callable[[str], int]


def approximate_tokens(text: str) -> int:
    """Conservative tokenizer-independent estimate for Chinese and Latin text."""
    cjk = len(re.findall(r"[\u3400-\u9fff\uf900-\ufaff]", text))
    other = len(re.findall(r"[A-Za-z0-9_]+|[^\sA-Za-z0-9_\u3400-\u9fff\uf900-\ufaff]", text))
    return cjk + other


def _stable(prefix: str, *values: object) -> str:
    raw = "\0".join(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                separators=(",", ":")) for value in values)
    return prefix + "-" + sha256(raw.encode("utf-8")).hexdigest()[:32]


@dataclass(frozen=True)
class Chunk:
    chunkId: str
    parentId: str | None
    chunkType: str
    ordinal: int
    titlePath: list[str]
    content: str
    embeddingText: str
    contentHash: str
    tokenCount: int
    elementType: str
    sourceElementIds: list[str]
    locators: list[dict[str, Any]]
    previousChunkId: str | None = None
    nextChunkId: str | None = None
    childIds: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ChunkBundle:
    schemaVersion: str
    chunkerVersion: str
    resourceRevisionId: str
    documentName: str
    parents: list[Chunk]
    children: list[Chunk]

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "parents": [x.to_dict() for x in self.parents],
                "children": [x.to_dict() for x in self.children]}


class HierarchicalChunker:
    """Create bounded semantic parents and retrieval children from normalized elements."""

    def __init__(self, child_max_tokens: int = 600, parent_max_tokens: int = 1800,
                 token_counter: TokenCounter = approximate_tokens):
        if child_max_tokens < 64 or parent_max_tokens < child_max_tokens:
            raise ValueError("Invalid chunk token limits")
        self.child_max_tokens = child_max_tokens
        self.parent_max_tokens = parent_max_tokens
        self.tokens = token_counter

    def build(self, document: dict[str, Any]) -> ChunkBundle:
        revision = str(document.get("resourceRevisionId", "")).strip()
        if not revision or not isinstance(document.get("elements"), list):
            raise ValueError("Invalid normalized document")
        name = str(document.get("name") or "未命名资料")
        groups: list[list[dict[str, Any]]] = []
        current: list[dict[str, Any]] = []
        current_path: list[str] | None = None
        current_tokens = 0
        for element in document["elements"]:
            content = str(element.get("markdown") or "").strip()
            if not content:
                continue
            path = [str(x).strip() for x in element.get("titlePath", []) if str(x).strip()]
            size = self.tokens(content)
            structural_break = current and path != current_path and element.get("type") == "HEADING"
            capacity_break = current and current_tokens + size > self.parent_max_tokens
            if structural_break or capacity_break:
                groups.append(current); current = []; current_tokens = 0
            current.append(element); current_tokens += size; current_path = path
        if current:
            groups.append(current)
        if not groups:
            raise ValueError("EMPTY_DOCUMENT")

        parents: list[Chunk] = []
        children: list[Chunk] = []
        child_ordinal = 0
        for parent_ordinal, elements in enumerate(groups):
            path = self._path(elements)
            parent_id = _stable("parent", revision, path, [e.get("id") for e in elements])
            child_specs = self._children(elements)
            local_children: list[Chunk] = []
            for content, source in child_specs:
                child_id = _stable("chunk", revision, path,
                                   [e.get("id") for e in source], sha256(content.encode()).hexdigest())
                local_children.append(Chunk(
                    child_id, parent_id, "CHILD", child_ordinal, path, content,
                    self._child_embedding(name, path, content), sha256(content.encode()).hexdigest(),
                    self.tokens(content), self._element_type(source),
                    [str(e.get("id")) for e in source], self._locators(source)))
                child_ordinal += 1
            for index, child in enumerate(local_children):
                values = child.to_dict()
                values["previousChunkId"] = local_children[index-1].chunkId if index else None
                values["nextChunkId"] = local_children[index+1].chunkId if index+1 < len(local_children) else None
                local_children[index] = Chunk(**values)
            children.extend(local_children)
            summary = self._parent_summary(path, local_children)
            parents.append(Chunk(
                parent_id, None, "PARENT", parent_ordinal, path, summary,
                self._parent_embedding(name, path, local_children), sha256(summary.encode()).hexdigest(),
                self.tokens(summary), "SECTION", [str(e.get("id")) for e in elements],
                self._locators(elements), childIds=[x.chunkId for x in local_children],
                keywords=self._keywords(path, local_children)))
        return ChunkBundle("1", "hierarchical-v1", revision, name, parents, children)

    def _children(self, elements: list[dict[str, Any]]) -> list[tuple[str, list[dict[str, Any]]]]:
        result: list[tuple[str, list[dict[str, Any]]]] = []
        current: list[dict[str, Any]] = []
        size = 0
        atomic = {"TABLE", "CODE", "FORMULA", "VIDEO_SEGMENT", "IMAGE"}
        for element in elements:
            text = str(element.get("markdown") or "").strip()
            count = self.tokens(text)
            if element.get("type") in atomic or count > self.child_max_tokens:
                if current:
                    result.append(("\n\n".join(str(x["markdown"]).strip() for x in current), current)); current=[]; size=0
                if count <= self.child_max_tokens or element.get("type") in atomic:
                    result.append((text, [element]))
                else:
                    for part in self._split_text(text):
                        result.append((part, [element]))
            elif current and size + count > self.child_max_tokens:
                result.append(("\n\n".join(str(x["markdown"]).strip() for x in current), current))
                current = [element]; size = count
            else:
                current.append(element); size += count
        if current:
            result.append(("\n\n".join(str(x["markdown"]).strip() for x in current), current))
        return result

    def _split_text(self, text: str) -> list[str]:
        parts = [x.strip() for x in re.split(r"(?<=[。！？.!?])\s*|\n{2,}", text) if x.strip()]
        output: list[str] = []
        current = ""
        for part in parts or [text]:
            if current and self.tokens(current + " " + part) > self.child_max_tokens:
                output.append(current); current = part
            else:
                current = (current + " " + part).strip()
        if current: output.append(current)
        return output

    @staticmethod
    def _path(elements: list[dict[str, Any]]) -> list[str]:
        for element in reversed(elements):
            path = element.get("titlePath") or []
            if path: return [str(x) for x in path]
        return []

    @staticmethod
    def _locators(elements: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[str] = set(); output = []
        for element in elements:
            for locator in element.get("locators", []):
                key = json.dumps(locator, sort_keys=True, ensure_ascii=False)
                if key not in seen: seen.add(key); output.append(locator)
        return output

    @staticmethod
    def _element_type(elements: list[dict[str, Any]]) -> str:
        types = {str(x.get("type", "UNKNOWN")) for x in elements}
        return next(iter(types)) if len(types) == 1 else "MIXED"

    @staticmethod
    def _keywords(path: list[str], children: list[Chunk]) -> list[str]:
        terms = []
        for value in path:
            terms.extend(re.findall(r"[\u3400-\u9fff]{2,8}|[A-Za-z][A-Za-z0-9_+.-]{1,30}", value))
        return list(dict.fromkeys(terms))[:32]

    @staticmethod
    def _parent_summary(path: list[str], children: list[Chunk]) -> str:
        heading = " / ".join(path) or "未命名章节"
        previews = [re.sub(r"\s+", " ", child.content)[:180] for child in children[:8]]
        return f"章节：{heading}\n内容概览：" + "；".join(previews)

    @staticmethod
    def _child_embedding(name: str, path: list[str], content: str) -> str:
        return f"课程资料：{name}\n章节：{' / '.join(path) or '未分类'}\n内容：{content}"

    @staticmethod
    def _parent_embedding(name: str, path: list[str], children: list[Chunk]) -> str:
        titles = "；".join(re.sub(r"[#*`]", "", x.content).strip()[:80] for x in children[:12])
        return f"课程资料：{name}\n章节：{' / '.join(path) or '未分类'}\n子主题：{titles}"

