from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest

from knowledge_service.modules.document_parser import (
    NormalizationError, convert_document, normalize_docling, normalize_video, save_artifacts,
)


def docling():
    return {
        "schema_name": "DoclingDocument", "version": "1.0.0", "name": "课程",
        "body": {"children": [{"$ref": "#/texts/1"}, {"$ref": "#/texts/0"}]},
        "texts": [
            {"label": "text", "text": "左子树、根节点、右子树。", "prov": [{"page_no": 12}]},
            {"label": "section_header", "level": 2, "text": "中序遍历", "prov": [{"page_no": 12}]},
        ],
    }


def cell(row, col, text, **kwargs):
    return {"start_row_offset_idx": row, "end_row_offset_idx": row + 1,
            "start_col_offset_idx": col, "end_col_offset_idx": col + 1, "text": text, **kwargs}


class NormalizationTests(unittest.TestCase):
    def test_reading_order_location_and_stability(self):
        raw = docling()
        before = deepcopy(raw)
        result = normalize_docling(raw, "rev1", "PDF")
        self.assertEqual(result.elements[0].type, "HEADING")
        self.assertEqual(result.elements[1].titlePath, ["中序遍历"])
        self.assertEqual(result.elements[1].locators[0]["pageIndex"], 11)
        self.assertEqual(result.to_dict(), normalize_docling(raw, "rev1", "PDF").to_dict())
        self.assertNotEqual(result.elements[0].id, normalize_docling(raw, "rev2", "PDF").elements[0].id)
        self.assertEqual(raw, before)
        self.assertIn(result.elements[1].id, result.to_markdown())

    def test_cycle_and_missing_reference(self):
        raw = docling()
        raw["body"]["children"] = [{"$ref": "#/body"}]
        with self.assertRaises(NormalizationError):
            normalize_docling(raw, "rev", "PDF")
        raw["body"]["children"] = [{"$ref": "#/texts/99"}]
        with self.assertRaises(NormalizationError):
            normalize_docling(raw, "rev", "PDF")

    def test_caption_emitted_once_and_unknown_retained(self):
        raw = docling()
        raw["pictures"] = [{"label": "picture", "captions": [{"$ref": "#/texts/0"}]}]
        raw["body"]["children"] = [{"$ref": "#/pictures/0"}, {"$ref": "#/texts/0"}]
        result = normalize_docling(raw, "rev", "PPTX")
        self.assertEqual(len(result.elements), 2)
        self.assertIn("IMAGE_REQUIRES_REVIEW", result.elements[0].qualityFlags)
        raw["texts"][0]["label"] = "future_label"
        result = normalize_docling(raw, "rev", "PDF")
        self.assertEqual(result.elements[1].data["raw"]["text"], raw["texts"][0]["text"])

    def test_table_and_merged_cells(self):
        raw = docling()
        raw["body"]["children"] = [{"$ref": "#/tables/0"}]
        raw["tables"] = [{"label": "table", "data": {"num_rows": 2, "num_cols": 2,
            "table_cells": [cell(0, 0, "名称", column_header=True), cell(0, 1, "值", column_header=True),
                            cell(1, 0, "A|B"), cell(1, 1, "2")]}}]
        result = normalize_docling(raw, "rev", "PDF")
        self.assertIn("| 名称 | 值 |", result.to_markdown())
        self.assertIn("A\\|B", result.to_markdown())
        raw["tables"][0]["data"]["table_cells"] = [cell(0, 0, "合并", end_col_offset_idx=2), cell(1, 0, "甲"), cell(1, 1, "乙")]
        result = normalize_docling(raw, "rev", "PDF")
        self.assertIn('colspan="2"', result.to_markdown())
        self.assertEqual(len(result.elements[0].data["table"]["table_cells"]), 3)

    def test_invalid_table_rejected(self):
        raw = docling()
        raw["body"]["children"] = [{"$ref": "#/tables/0"}]
        raw["tables"] = [{"label": "table", "data": {"num_rows": 1, "num_cols": 1,
                            "table_cells": [cell(0, 0, "A"), cell(0, 0, "B")]}}]
        with self.assertRaises(NormalizationError):
            normalize_docling(raw, "rev", "PDF")

    def test_docx_uses_element_not_claimed_stable_page(self):
        result = normalize_docling(docling(), "rev", "DOCX")
        self.assertEqual(result.elements[0].locators[0]["type"], "DOCUMENT_ELEMENT")
        self.assertNotIn("pageIndex", result.elements[0].locators[0])

    def test_video_preserves_asr_ocr_and_timestamps(self):
        raw = {"source": "lecture.mp4", "segments": [{"startMs": 60000, "endMs": 120000,
               "transcript": "定义", "ocrTexts": ["公式"], "evidenceFrames": ["frame.jpg"]}]}
        result = normalize_video(raw, "rev")
        self.assertEqual(result.elements[0].locators[0]["startMs"], 60000)
        self.assertEqual(result.elements[0].data["evidenceFrames"], ["frame.jpg"])
        self.assertIn("定义", result.to_markdown())
        self.assertIn("公式", result.to_markdown())
        raw["segments"][0]["endMs"] = 10
        with self.assertRaises(NormalizationError):
            normalize_video(raw, "rev")

    def test_empty_and_missing_location_reported(self):
        raw = docling()
        raw["body"]["children"] = []
        self.assertIn("EMPTY_DOCUMENT", normalize_docling(raw, "rev", "PDF").qualityFlags)
        raw = docling()
        raw["texts"][0].pop("prov")
        self.assertIn("NO_PAGE_LOCATION", normalize_docling(raw, "rev", "PDF").elements[1].qualityFlags)

    def test_artifacts_idempotent_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "artifacts"
            raw = docling()
            document = normalize_docling(raw, "rev", "PDF")
            save_artifacts(document, path)
            save_artifacts(document, path)
            saved = json.loads((path / "document.json").read_text(encoding="utf-8"))
            self.assertEqual(saved, document.to_dict())
            self.assertEqual((path / "content.md").read_text(encoding="utf-8"), document.to_markdown())
            self.assertEqual({item.name for item in path.iterdir()},
                             {"document.json", "content.md", "manifest.json"})
            document.name = "changed"
            with self.assertRaises(FileExistsError):
                save_artifacts(document, path)

    def test_explicit_converter_contract(self):
        class Converter:
            def convert(self, source):
                return SimpleNamespace(status="success", document=SimpleNamespace(export_to_dict=docling))
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "sample.pdf"
            path.write_bytes(b"test")
            result, raw = convert_document(path, "rev", Converter())
            self.assertEqual(result.sourceType, "PDF")
            self.assertEqual(raw, docling())

    def test_cli_end_to_end(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            (path / "input.json").write_text(json.dumps(docling()), encoding="utf-8")
            result = subprocess.run([sys.executable, "-m", "knowledge_service.main", str(path / "input.json"),
                "--kind", "docling", "--source-type", "PDF", "--revision", "rev", "--output", str(path / "out")],
                cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((path / "out" / "manifest.json").is_file())


if __name__ == "__main__":
    unittest.main()
