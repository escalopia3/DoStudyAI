"""Bounded format checks; full parsing remains block 4."""
import zipfile

class InvalidResource(ValueError):
    pass

def check_format(stream, content_type):
    stream.seek(0)
    head = stream.read(4096)
    stream.seek(0)
    if content_type.endswith('wordprocessingml.document') or content_type.endswith('presentationml.presentation'):
        try:
            with zipfile.ZipFile(stream) as archive:
                entries = archive.infolist()
                if len(entries) > 10000 or sum(x.file_size for x in entries) > 1024**3:
                    raise InvalidResource('ARCHIVE_LIMIT')
                if any(x.flag_bits & 1 or x.file_size > 200 * 1024**2 or
                       x.file_size > max(x.compress_size, 1) * 1000 for x in entries):
                    raise InvalidResource('ARCHIVE_LIMIT')
                names = set(archive.namelist())
                required = 'word/document.xml' if content_type.endswith('wordprocessingml.document') else 'ppt/presentation.xml'
                if not {'[Content_Types].xml', required}.issubset(names):
                    raise InvalidResource('INVALID_OFFICE_STRUCTURE')
        except zipfile.BadZipFile as exc:
            raise InvalidResource('INVALID_ZIP') from exc
    else:
        valid = {
            'application/pdf': head.startswith(b'%PDF-'),
            'image/png': head.startswith(b'\x89PNG\r\n\x1a\n'),
            'image/jpeg': head.startswith(b'\xff\xd8\xff'),
            'video/mp4': len(head) >= 12 and head[4:8] == b'ftyp',
            'video/webm': head.startswith(b'\x1aE\xdf\xa3'),
            'audio/wav': head.startswith(b'RIFF') and head[8:12] == b'WAVE',
            'audio/mpeg': head.startswith(b'ID3') or (len(head) > 1 and head[0] == 255 and head[1] & 224 == 224),
        }.get(content_type, False)
        if not valid:
            raise InvalidResource('FORMAT_MISMATCH')
    stream.seek(0)
