"""Versioned contracts shared by normalization and future chunking."""

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class DocumentElement:
    id: str
    type: str
    markdown: str
    titlePath: list[str]
    sourceRefs: list[str]
    locators: list[dict[str, Any]] = field(default_factory=list)
    extractionMethod: str = "UNKNOWN"
    qualityFlags: list[str] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class NormalizedDocument:
    resourceRevisionId: str
    name: str
    sourceType: str
    parser: dict[str, str]
    elements: list[DocumentElement]
    schemaVersion: str = "1"
    normalizerVersion: str = "1"
    qualityFlags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_markdown(self) -> str:
        """Render the same ordered elements as JSON, with stable citation anchors."""
        return "\n\n".join(
            f"<a id=\"{item.id}\"></a>\n\n{item.markdown}"
            for item in self.elements
        ) + ("\n" if self.elements else "")
