import argparse
import json
import os
from pathlib import Path
from zipfile import ZipFile, BadZipFile
from knowledge_service.modules.document_parser import convert_document, normalize_video, save_artifacts


def validate_file(path, max_bytes=50*1024*1024, max_expanded=200*1024*1024):
    if not path.is_file() or not 0 < path.stat().st_size <= max_bytes:
        raise ValueError("FILE_SIZE_LIMIT")
    if path.suffix.lower() not in (".pdf", ".docx", ".pptx", ".json"):
        raise ValueError("UNSUPPORTED_FORMAT")
    if path.suffix.lower() in (".docx", ".pptx"):
        try:
            with ZipFile(path) as archive:
                info = archive.infolist()
                if len(info) > 10000 or sum(x.file_size for x in info) > max_expanded:
                    raise ValueError("ARCHIVE_SIZE_LIMIT")
                if any(x.flag_bits & 1 for x in info): raise ValueError("ENCRYPTED_ARCHIVE")
        except BadZipFile as e:
            raise ValueError("INVALID_OFFICE_FILE") from e


def build_converter(artifacts_path, timeout):
    # Never download model artifacts from a worker request.
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions, RapidOcrOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption
    options = PdfPipelineOptions(enable_remote_services=False, document_timeout=timeout)
    options.ocr_options = RapidOcrOptions(backend="onnxruntime")
    if artifacts_path:
        if not Path(artifacts_path).is_dir(): raise ValueError("MODEL_DIRECTORY_MISSING")
        options.artifacts_path = Path(artifacts_path)
    return DocumentConverter(allowed_formats=[InputFormat.PDF, InputFormat.DOCX, InputFormat.PPTX],
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)})


def parse(path, revision, destination, artifacts_path="", timeout=300, max_pages=500):
    validate_file(path)
    if path.suffix == ".json":
        raw = json.loads(path.read_text(encoding="utf-8"))
        doc = normalize_video(raw, revision)
    else:
        if path.suffix.lower() == ".pdf" and (not artifacts_path or not Path(artifacts_path).is_dir()):
            raise ValueError("MODEL_DIRECTORY_MISSING")
        converter = build_converter(artifacts_path, timeout)
        # The existing adapter validates successful conversion before normalization.
        class LimitedConverter:
            def convert(self, source):
                return converter.convert(source, max_num_pages=max_pages, max_file_size=50*1024*1024)
        doc, raw = convert_document(path, revision, LimitedConverter())
    if not doc.elements: raise ValueError("EMPTY_DOCUMENT")
    return save_artifacts(doc, destination)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("revision")
    parser.add_argument("destination", type=Path)
    parser.add_argument("--artifacts", default="")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--max-pages", type=int, default=500)
    args = parser.parse_args()
    parse(args.source, args.revision, args.destination, args.artifacts, args.timeout, args.max_pages)
