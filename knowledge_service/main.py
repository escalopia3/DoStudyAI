"""Offline CLI entry point for the normalization module."""

import argparse
import json
from pathlib import Path

from knowledge_service.modules.document_parser import normalize_docling, normalize_video, save_artifacts


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize existing parser JSON without downloading dependencies/models")
    parser.add_argument("input", type=Path)
    parser.add_argument("--kind", required=True, choices=["docling", "video"])
    parser.add_argument("--revision", required=True)
    parser.add_argument("--source-type", help="Original format, e.g. PDF, DOCX, PPTX; required for Docling")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.kind == "docling" and not args.source_type:
        parser.error("--source-type is required for Docling input")
    try:
        raw = json.loads(args.input.read_text(encoding="utf-8-sig"))
        if not isinstance(raw, dict):
            raise ValueError("Input JSON must be an object")
        document = (normalize_video(raw, args.revision) if args.kind == "video" else
                    normalize_docling(raw, args.revision, args.source_type))
        print(save_artifacts(document, args.output))
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.exit(1, f"Normalization failed: {exc}\n")


if __name__ == "__main__":
    main()
