"""Desktop app: runs the FastAPI server in this process and shows the UI in a native window.

Packaged with PyInstaller (see packaging/). Also runnable from source: `uv run python -m app.desktop`.
`--selftest` checks the bundle without opening a window (used by CI for the Windows build).
"""

import multiprocessing
import os
import socket
import sys
import threading
import time
from pathlib import Path

PREFERRED_PORT = 47821


def _redirect_output(log_dir: Path) -> None:
    """A windowed app has no console: sys.stdout/err can be None, and libraries that print would crash."""
    log_dir.mkdir(parents=True, exist_ok=True)
    log = open(log_dir / "app.log", "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = log
    print(f"\n===== start {time.strftime('%Y-%m-%d %H:%M:%S')} =====")


def _free_port() -> int:
    for port in (PREFERRED_PORT, 0):  # fixed port keeps the web view's storage stable
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return s.getsockname()[1]
            except OSError:
                continue
    raise RuntimeError("no free port")


class _SingleInstance:
    """Two copies would run two job queues on the same data folder."""

    def __init__(self, path: Path):
        self.f = open(path, "a+")
        try:
            if sys.platform == "win32":
                import msvcrt
                msvcrt.locking(self.f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.ok = True
        except OSError:
            self.ok = False


def _start_server(port: int):
    import uvicorn

    from app.main import app

    # explicit loop/http/ws: the "auto" choices import modules PyInstaller can't see
    cfg = uvicorn.Config(app, host="127.0.0.1", port=port, workers=1, log_config=None,
                         loop="asyncio", http="h11", ws="none", lifespan="on")
    server = uvicorn.Server(cfg)
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(300):
        if server.started:
            return server
        time.sleep(0.05)
    raise RuntimeError("Server không khởi động được.")


class Api:
    """Exposed to the page as window.pywebview.api (see web/lib/api.ts)."""

    def __init__(self, base: str):
        self._base = base
        self._window = None

    def save_file(self, url: str) -> dict:
        import urllib.parse
        import urllib.request

        import webview

        try:
            with urllib.request.urlopen(self._base + url, timeout=30) as r:
                cd = r.headers.get("content-disposition", "")
                name = "longtieng"
                if "filename*=" in cd:
                    name = urllib.parse.unquote(cd.split("filename*=")[1].split("''", 1)[-1].strip('"; '))
                elif "filename=" in cd:
                    name = cd.split("filename=")[1].strip('"; ')
                downloads = Path.home() / "Downloads"
                picked = self._window.create_file_dialog(
                    webview.FileDialog.SAVE, directory=str(downloads if downloads.is_dir() else Path.home()),
                    save_filename=name)
                if not picked:
                    return {"cancelled": True}
                dest = Path(picked[0] if isinstance(picked, (list, tuple)) else picked)
                tmp = dest.with_name(dest.name + ".part")
                with open(tmp, "wb") as out:
                    while chunk := r.read(1 << 20):
                        out.write(chunk)
                tmp.replace(dest)
                return {"saved": str(dest)}
        except Exception as e:
            return {"error": f"Không lưu được file: {e}"}

    def reveal(self, path: str) -> None:
        import subprocess

        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", path])
        else:
            subprocess.Popen(["xdg-open", str(Path(path).parent)])

    def copy(self, text: str) -> None:
        if sys.platform == "darwin":
            from AppKit import NSPasteboard, NSPasteboardTypeString

            pb = NSPasteboard.generalPasteboard()
            pb.clearContents()
            pb.setString_forType_(text, NSPasteboardTypeString)
        elif sys.platform == "win32":
            _win_copy(text)


def _win_copy(text: str) -> None:
    import ctypes
    from ctypes import wintypes

    u32, k32 = ctypes.windll.user32, ctypes.windll.kernel32
    k32.GlobalAlloc.restype = wintypes.HGLOBAL
    k32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    k32.GlobalLock.restype = wintypes.LPVOID
    k32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    k32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    u32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    data = text.encode("utf-16-le") + b"\0\0"
    for _ in range(10):  # another app may hold the clipboard for a moment
        if u32.OpenClipboard(None):
            break
        time.sleep(0.05)
    else:
        raise RuntimeError("Clipboard đang bận.")
    try:
        u32.EmptyClipboard()
        h = k32.GlobalAlloc(0x0002, len(data))  # GMEM_MOVEABLE
        ctypes.memmove(k32.GlobalLock(h), data, len(data))
        k32.GlobalUnlock(h)
        u32.SetClipboardData(13, h)  # CF_UNICODETEXT
    finally:
        u32.CloseClipboard()


def _shutdown(server) -> None:
    from app import cancel

    cancel.cancel_all()  # kills ffmpeg/yt-dlp still running for any job
    server.should_exit = True


def _reattach_stdio() -> None:
    """Windowed build started with redirected pipes (yt-dlp child, selftest): use them."""
    for name, fd in (("stdout", 1), ("stderr", 2)):
        stream = getattr(sys, name)
        if stream is None:
            try:
                setattr(sys, name, open(fd, "w", encoding="utf-8", buffering=1, closefd=False))
            except OSError:
                pass
        elif hasattr(stream, "reconfigure"):
            # Windows pipes default to cp1252, which can't print Vietnamese ("ẵ") and raises
            stream.reconfigure(encoding="utf-8", errors="replace")


def _run_ytdlp(args: list[str]) -> None:
    """Child process mode: behave exactly like the yt-dlp command line."""
    _reattach_stdio()
    import yt_dlp

    sys.exit(yt_dlp.main(args))


def main() -> None:
    multiprocessing.freeze_support()
    if sys.argv[1:2] == ["--yt-dlp"]:
        _run_ytdlp(sys.argv[2:])
    if "--selftest" in sys.argv:
        _reattach_stdio()
        from app.selftest import run
        sys.exit(run())

    from app.config import FROZEN, USER_DIR

    if FROZEN:
        _redirect_output(USER_DIR / "logs")

    import webview

    lock = _SingleInstance(USER_DIR / ".lock")
    if not lock.ok:
        webview.create_window("Lồng tiếng", html="<body style='font:15px system-ui;padding:24px'>"
                              "<b>App Lồng tiếng đang mở rồi.</b><br>Hãy dùng cửa sổ đang mở.</body>",
                              width=420, height=160)
        webview.start()
        return

    port = _free_port()
    server = _start_server(port)
    base = f"http://127.0.0.1:{port}"
    api = Api(base)
    window = webview.create_window("Lồng tiếng", base + "/", js_api=api, width=1400, height=900,
                                   min_size=(960, 640), text_select=True)
    api._window = window
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
    webview.settings["ALLOW_DOWNLOADS"] = True
    try:
        webview.start(private_mode=False, storage_path=str(USER_DIR / "webview"))
    finally:
        _shutdown(server)
        time.sleep(0.3)
        os._exit(0)  # don't wait for worker threads stuck in a model call


if __name__ == "__main__":
    main()
