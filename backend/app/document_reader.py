"""Bounded extraction worker. Invoked in a separate process for untrusted PDFs."""
from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

MAX_TEXT = 500_000


def extract(path: Path) -> dict:
    if path.suffix.lower() == '.pdf':
        from pypdf import PdfReader
        reader = PdfReader(path, strict=False)
        if reader.is_encrypted:
            raise ValueError('Password-protected PDFs must be unlocked before upload')
        parts = []
        length = 0
        pages = len(reader.pages)
        for index in range(min(pages, 100)):
            page = reader.pages[index]
            part = page.extract_text() or ''
            parts.append(f'\n[Page {index + 1}]\n' + part)
            length += len(part)
            if length >= MAX_TEXT:
                break
        text = ''.join(parts)[:MAX_TEXT]
        return {'text': text, 'pages': pages, 'truncated': pages > len(parts) or length > MAX_TEXT,
                'note': 'Text extraction only; scanned images need OCR.'}
    if path.suffix.lower() == '.docx':
        from defusedxml.ElementTree import fromstring
        with zipfile.ZipFile(path) as archive:
            info = archive.getinfo('word/document.xml')
            if info.file_size > 4 * 1024 * 1024:
                raise ValueError('Document text is too large to extract')
            root = fromstring(archive.read(info))
        ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
        text = '\n'.join(''.join(p.itertext()) for p in root.findall('.//w:p', ns))
        return {'text': text[:MAX_TEXT], 'truncated': len(text) > MAX_TEXT}
    raise ValueError('Unsupported document format')


if __name__ == '__main__':
    try:
        if sys.platform != 'win32':
            import resource
            resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))
            resource.setrlimit(resource.RLIMIT_CPU, (12, 12))
        print(json.dumps(extract(Path(sys.argv[1]))))
    except Exception:
        print(json.dumps({'error': 'Document could not be extracted. Use an unlocked PDF, DOCX, or plain text file.'}))

