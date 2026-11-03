from pathlib import Path
from types import SimpleNamespace
import pytest
from server.preview import render_preview, PreviewError


def test_repacked_docx_does_not_rerender(tmp_path, monkeypatch):
    from io import BytesIO
    from zipfile import ZipFile, ZipInfo
    calls = []
    def archive(year, text):
        out = BytesIO()
        with ZipFile(out, 'w') as z:
            z.writestr(ZipInfo('word/document.xml', (year, 1, 1, 0, 0, 0)), text)
        return out.getvalue()
    def run(args, **kwargs):
        calls.append(args)
        (Path(args[-1])/'preview.pdf').write_bytes(b'%PDF-test')
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr('server.preview.subprocess.run', run)
    a = render_preview(archive(2020, '<p>same</p>'), tmp_path)
    assert render_preview(archive(2026, '<p>same</p>'), tmp_path) == a
    assert len(calls) == 1
    assert render_preview(archive(2026, '<p>changed</p>'), tmp_path) != a
    assert len(calls) == 2


def test_preview_cache_uses_document_bytes(tmp_path, monkeypatch):
    calls=[]
    def run(args, **kwargs):
        calls.append(args)
        (Path(args[-1])/'preview.pdf').write_bytes(b'%PDF-test')
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr('server.preview.subprocess.run', run)
    a=render_preview(b'original',tmp_path)
    assert render_preview(b'original',tmp_path)==a
    assert render_preview(b'edited',tmp_path)!=a
    assert len(calls)==2
    assert (a.parent/'input.docx').read_bytes()==b'original'


def test_failed_preview_does_not_cache_partial_pdf(tmp_path, monkeypatch):
    def run(args, **kwargs):
        (Path(args[-1])/'preview.pdf').write_bytes(b'partial')
        return SimpleNamespace(returncode=1)
    monkeypatch.setattr('server.preview.subprocess.run', run)
    with pytest.raises(PreviewError): render_preview(b'original',tmp_path)
    assert not list(tmp_path.glob('*/preview.pdf'))


def test_preview_timeout_is_reported(tmp_path, monkeypatch):
    import subprocess
    def run(args, **kwargs):
        raise subprocess.TimeoutExpired(args, 90)
    monkeypatch.setattr('server.preview.subprocess.run', run)
    with pytest.raises(PreviewError, match='超时'): render_preview(b'original',tmp_path)
