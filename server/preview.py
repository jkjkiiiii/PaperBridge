"""Local desktop Word preview; only task-owned copies enter the COM worker."""
from pathlib import Path
from hashlib import sha256
import subprocess
import sys
import threading
import json
from io import BytesIO
from zipfile import ZipFile, BadZipFile

_LOCK = threading.Lock()

class PreviewError(ValueError):
    pass


def preview_key(data: bytes) -> str:
    # ZIP entry timestamps/compression change on export even when every Word
    # part is identical. Hash named uncompressed parts, not the ZIP envelope.
    digest = sha256(b'word-pdf-parts-v2')
    try:
        with ZipFile(BytesIO(data)) as archive:
            for name in sorted(archive.namelist()):
                payload = archive.read(name)
                digest.update(name.encode('utf-8') + b'\0')
                digest.update(len(payload).to_bytes(8, 'big'))
                digest.update(payload)
    except BadZipFile:
        digest.update(data)
    return digest.hexdigest()


def render_preview(data: bytes, cache: Path) -> Path:
    key = preview_key(data)
    folder = cache / key
    pdf = folder / 'preview.pdf'
    with _LOCK:
        if pdf.exists() and pdf.stat().st_size > 0:
            return pdf
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'word-pid.json').unlink(missing_ok=True)
        (folder / 'input.docx').write_bytes(data)
        try:
            result = subprocess.run([sys.executable, str(Path(__file__).resolve()), str(folder)],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except subprocess.TimeoutExpired as exc:
            # Kill only the dedicated Word instance identified by this worker.
            marker = folder / 'word-pid.json'
            if marker.exists():
                try:
                    info = json.loads(marker.read_text())
                    import win32api, win32con, win32process
                    handle = win32api.OpenProcess(win32con.PROCESS_QUERY_INFORMATION | win32con.PROCESS_TERMINATE, False, info['pid'])
                    try:
                        created = str(win32process.GetProcessTimes(handle)['CreationTime'])
                        if created == info['created']:
                            win32api.TerminateProcess(handle, 1)
                    finally: handle.Close()
                except Exception: pass
            pdf.unlink(missing_ok=True)
            raise PreviewError('Word 页面生成超时，请稍后重试。') from exc
        if result.returncode or not pdf.exists():
            pdf.unlink(missing_ok=True)
            raise PreviewError('Word 页面预览失败，请确认本机已安装并可启动 Microsoft Word，以及 pywin32 依赖可用。')
        return pdf


def worker(folder: Path):
    import win32com.client
    import win32process
    import win32api
    import win32con
    app = win32com.client.DispatchEx('Word.Application')
    document = None
    options = {}
    try:
        app.Visible = False
        app.DisplayAlerts = 0
        app.AutomationSecurity = 3
        for name in ("UpdateLinksAtOpen", "UpdateFieldsAtPrint", "UpdateLinksAtPrint"):
            options[name] = getattr(app.Options, name)
            setattr(app.Options, name, False)
        document = app.Documents.Add()
        _, pid = win32process.GetWindowThreadProcessId(document.ActiveWindow.Hwnd)
        handle = win32api.OpenProcess(win32con.PROCESS_QUERY_INFORMATION, False, pid)
        try: created = str(win32process.GetProcessTimes(handle)['CreationTime'])
        finally: handle.Close()
        (folder / 'word-pid.json').write_text(json.dumps({'pid': pid, 'created': created}))
        document.Close(SaveChanges=0)
        document = None
        document = app.Documents.Open(str(folder / 'input.docx'), ReadOnly=True,
            AddToRecentFiles=False, ConfirmConversions=False, OpenAndRepair=False)
        document.ExportAsFixedFormat(str(folder / 'preview.pdf'), 17, OpenAfterExport=False,
            IncludeDocProps=False, DocStructureTags=True)
    finally:
        try:
            if document is not None: document.Close(SaveChanges=0)
        finally:
            for name, value in options.items():
                try: setattr(app.Options, name, value)
                except Exception: pass
            app.Quit(SaveChanges=0)

if __name__ == '__main__':
    worker(Path(sys.argv[1]).resolve())
