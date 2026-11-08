"""Offline document parsing and immutable artifact publication."""
import hashlib
import os
import tempfile
from pathlib import Path
from dovideo.validation import InvalidResource

SUFFIXES = {'application/pdf': '.pdf',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document': '.docx',
    'application/vnd.openxmlformats-officedocument.presentationml.presentation': '.pptx'}

def process(storage, snapshot):
    content_type = snapshot['content_type']
    suffix = SUFFIXES.get(content_type) or {'image/png':'.png','image/jpeg':'.jpg',
        'video/mp4':'.mp4','video/webm':'.webm','audio/mpeg':'.mp3','audio/wav':'.wav'}.get(content_type)
    if suffix is None:
        raise InvalidResource('PARSER_NOT_CONFIGURED_FOR_MEDIA')
    if content_type in SUFFIXES and snapshot['size'] > 50 * 1024 * 1024:
        raise InvalidResource('DOCUMENT_LIMIT_50_MIB')
    if content_type.startswith('image/') and snapshot['size'] > 50 * 1024 * 1024:
        raise InvalidResource('IMAGE_LIMIT_50_MIB')
    # Explicit offline settings must precede Docling/model imports.
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['TRANSFORMERS_OFFLINE'] = '1'
    from knowledge_service.parsing.convert import parse
    with tempfile.TemporaryDirectory(prefix='dovideo-parse-') as directory:
        root = Path(directory)
        source = root / ('source' + suffix)
        response = storage.minio.get_object(storage.bucket, snapshot['key'], version_id=snapshot['object_version_id'])
        try:
            size = 0
            digest = hashlib.sha256()
            with source.open('wb') as stream:
                for chunk in response.stream(1024 * 1024):
                    size += len(chunk)
                    if size > snapshot['size']:
                        raise InvalidResource('SOURCE_SIZE_MISMATCH')
                    stream.write(chunk)
                    digest.update(chunk)
            if size != snapshot['size']:
                raise InvalidResource('SOURCE_SIZE_MISMATCH')
            if snapshot.get('expected_sha256') and digest.hexdigest()!=snapshot['expected_sha256']:
                raise InvalidResource('SOURCE_HASH_MISMATCH')
        finally:
            response.close()
            response.release_conn()
        destination = root / 'artifacts'
        if snapshot.get('formula_review_sha256'):
            review=Path(os.environ.get('DOVIDEO_FORMULA_REVIEWS_DIR',''))/(digest.hexdigest()+'.json')
            if not review.is_file() or hashlib.sha256(review.read_bytes()).hexdigest()!=snapshot['formula_review_sha256']:
                raise InvalidResource('FORMULA_REVIEW_CHANGED')
        try:
            if content_type.startswith('image/'):
                from dovideo.media_parsing import parse_image
                parse_image(source, snapshot['version_id'], destination)
            elif content_type.startswith(('audio/', 'video/')):
                from dovideo.media_parsing import parse_media
                parse_media(source, snapshot['version_id'], destination)
            else:
                parse(source, snapshot['version_id'], destination,
                      artifacts_path=os.getenv('DOCLING_ARTIFACTS_PATH', ''), timeout=300, max_pages=500,
                      formula_reviews=os.getenv('DOVIDEO_FORMULA_REVIEWS_DIR',''))
        except (ValueError, ImportError) as exc:
            code = str(exc) if isinstance(exc, ValueError) else 'PARSER_DEPENDENCY_MISSING'
            raise InvalidResource(code[:160]) from exc
        except Exception as exc:
            from docling.exceptions import ConversionError
            if isinstance(exc, ConversionError):
                raise InvalidResource('DOCUMENT_CONVERSION_FAILED') from exc
            raise
        prefix = f"artifacts/{snapshot['version_id']}/{snapshot['lease_token']}"
        files = {}
        for name in ('document.json', 'content.md', 'manifest.json'):
            path = destination / name
            result = storage.minio.fput_object(storage.bucket, prefix + '/' + name, str(path),
                content_type='application/json' if name.endswith('.json') else 'text/markdown; charset=utf-8')
            files[name] = {'key': prefix + '/' + name, 'version_id':result.version_id,
                           'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
        return {'ok':True, 'artifacts':files}
