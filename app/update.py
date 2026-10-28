"""Self-update from GitHub Releases.

Each release publishes latest.json:
    {"version": "0.3.1", "shell": "0.3.0", "notes": "...",
     "patch":   {"url": ..., "sha256": ..., "size": ...},   # code + web UI only, a few MB
     "mac":     {...}, "windows": {...}}                     # the whole app, ~300MB

Same SHELL_VERSION as the running app -> light update (unzip the patch into updates/current).
Otherwise -> full update (download the app, swap it in after this process exits).
Either way the app restarts through a small script that waits for this process to end.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

from .config import APP_VERSION, FROZEN, IS_MAC, IS_WIN, SHELL_VERSION, USER_DIR

REPO = "nmhieudut/longtieng"
LATEST_URL = os.getenv("LONGTIENG_UPDATE_URL") or f"https://github.com/{REPO}/releases/latest/download/latest.json"
CHECK_EVERY = 30 * 60

UPDATES = USER_DIR / "updates"
_lock = threading.Lock()
_state: dict = {"stage": "idle", "progress": None, "error": None, "latest": None, "kind": None, "checked_at": 0}

# set by app/desktop.py: closes the window so the process can exit and be replaced
request_quit = None


def enabled() -> bool:
    return FROZEN or os.getenv("LONGTIENG_UPDATE_TEST") == "1"


def _ver(v: str) -> tuple:
    try:
        return tuple(int(x) for x in v.strip().lstrip("v").split("."))
    except ValueError:
        return (0,)


def state() -> dict:
    with _lock:
        s = dict(_state)
    s.update(current=APP_VERSION, shell=SHELL_VERSION, enabled=enabled())
    return s


def _set(**kw) -> None:
    with _lock:
        _state.update(kw)


def check(force: bool = False) -> dict:
    """Ask GitHub for the newest release (at most every 30 min unless forced)."""
    if not enabled():
        return state()
    with _lock:
        busy = _state["stage"] in ("downloading", "installing", "restarting")
        fresh = time.time() - _state["checked_at"] < CHECK_EVERY
    if busy or (fresh and not force):
        return state()
    try:
        req = urllib.request.Request(LATEST_URL, headers={"User-Agent": "Longtieng/" + APP_VERSION})
        with urllib.request.urlopen(req, timeout=15) as r:
            latest = json.loads(r.read().decode())
    except Exception as e:
        _set(checked_at=time.time(), stage="idle" if not force else "error",
             error=None if not force else f"Không kiểm tra được bản mới ({type(e).__name__}). Kiểm tra mạng rồi thử lại.")
        return state()
    if _ver(latest.get("version", "0")) <= _ver(APP_VERSION):
        _set(checked_at=time.time(), stage="none", latest=latest, kind=None, error=None)
        return state()
    kind = "patch" if latest.get("shell") == SHELL_VERSION and latest.get("patch") else "full"
    _set(checked_at=time.time(), stage="available", latest=latest, kind=kind, error=None, progress=None)
    return state()


def apply() -> dict:
    check(force=True)  # the button may show a release that is no longer the newest
    with _lock:
        if _state["stage"] != "available":
            raise RuntimeError("Không có bản cập nhật nào để cài.")
        _state.update(stage="downloading", progress=0.0, error=None)
    threading.Thread(target=_apply, daemon=True).start()
    return state()


def _apply() -> None:
    latest, kind = _state["latest"], _state["kind"]
    try:
        asset = latest["patch"] if kind == "patch" else latest["mac" if IS_MAC else "windows"]
        UPDATES.mkdir(parents=True, exist_ok=True)
        zpath = UPDATES / ("patch.zip" if kind == "patch" else "full.zip")
        _download(asset, zpath)
        _set(stage="installing", progress=None)
        if kind == "patch":
            _install_patch(zpath, latest["version"])
            script = _restart_script(None)
        else:
            new_app = _unpack_full(zpath)
            script = _restart_script(new_app)
        _set(stage="restarting")
        _launch(script)
        time.sleep(0.5)
        if request_quit:
            request_quit()
        else:
            os._exit(0)
    except Exception as e:
        _set(stage="error", progress=None, error=f"Cập nhật lỗi: {e}")


def _download(asset: dict, dest: Path) -> None:
    req = urllib.request.Request(asset["url"], headers={"User-Agent": "Longtieng/" + APP_VERSION})
    total = int(asset.get("size") or 0)
    h = hashlib.sha256()
    got = 0
    tmp = dest.with_suffix(".part")
    with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as out:
        total = total or int(r.headers.get("content-length") or 0)
        while chunk := r.read(1 << 20):
            out.write(chunk)
            h.update(chunk)
            got += len(chunk)
            if total:
                _set(progress=min(0.99, got / total))
    if asset.get("sha256") and h.hexdigest() != asset["sha256"]:
        tmp.unlink(missing_ok=True)
        raise RuntimeError("file tải về bị hỏng (sai mã kiểm tra). Thử lại sau.")
    tmp.replace(dest)


def _install_patch(zpath: Path, version: str) -> None:
    new = UPDATES / "new"
    shutil.rmtree(new, ignore_errors=True)
    with zipfile.ZipFile(zpath) as z:
        z.extractall(new)
    meta = json.loads((new / "meta.json").read_text())
    if meta.get("shell") != SHELL_VERSION or not (new / "app" / "desktop.py").is_file():
        raise RuntimeError("gói cập nhật không khớp với bản app này.")
    cur, old = UPDATES / "current", UPDATES / "old"
    shutil.rmtree(old, ignore_errors=True)
    if cur.exists():
        cur.rename(old)
    new.rename(cur)
    (UPDATES / "booting").unlink(missing_ok=True)
    zpath.unlink(missing_ok=True)


def _unpack_full(zpath: Path) -> Path:
    out = UPDATES / "full"
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    if IS_MAC:  # ditto keeps the .app's symlinks, permissions and signature intact
        subprocess.run(["ditto", "-x", "-k", str(zpath), str(out)], check=True, capture_output=True)
        found = next(out.glob("*.app"), None)
    else:
        with zipfile.ZipFile(zpath) as z:
            z.extractall(out)
        found = next((p.parent for p in out.rglob("Longtieng.exe")), None)
    if not found:
        raise RuntimeError("gói cập nhật không có app.")
    zpath.unlink(missing_ok=True)
    return found


def _install_location() -> Path:
    exe = Path(sys.executable).resolve()
    return exe.parents[2] if IS_MAC else exe.parent  # …/X.app/Contents/MacOS/Longtieng  |  …\Longtieng\Longtieng.exe


def _restart_script(new_app: Path | None) -> Path:
    """Script that waits for this process to exit, swaps in the new app (full update) and relaunches."""
    pid = os.getpid()
    target = _install_location()
    if IS_WIN:
        lines = [f"Wait-Process -Id {pid} -ErrorAction SilentlyContinue", "Start-Sleep -Milliseconds 500"]
        if new_app:
            # /MIR only on our own folder (has _internal); never mirror over e.g. Downloads
            mode = "/MIR" if (target / "_internal").is_dir() and target.name.lower().startswith("longtieng") else "/E"
            log = UPDATES.parent / "logs" / "update.log"
            log.parent.mkdir(parents=True, exist_ok=True)
            lines.append(f'robocopy "{new_app}" "{target}" {mode} /R:5 /W:1 /NFL /NDL /NJH /NJS /NP | Out-File -LiteralPath "{log}" -Encoding utf8')
            lines.append(f'"robocopy exit code: $LASTEXITCODE (0-7 = ok, 8+ = failed); target: {target}" | Out-File -Append -LiteralPath "{log}" -Encoding utf8')
            lines.append(f'Remove-Item -Recurse -Force "{new_app.parent}" -ErrorAction SilentlyContinue')
        lines.append(f'Start-Process -FilePath "{target / "Longtieng.exe"}"')
        script = UPDATES / "restart.ps1"
        script.write_text("\r\n".join(lines), encoding="utf-8-sig")
    else:
        q = lambda p: "'" + str(p).replace("'", "'\\''") + "'"  # noqa: E731
        lines = ["#!/bin/sh", f"while kill -0 {pid} 2>/dev/null; do sleep 0.3; done", "sleep 0.5"]
        if new_app:
            old = UPDATES / "old.app"
            lines += [f"rm -rf {q(old)}", f"mv {q(target)} {q(old)} && mv {q(new_app)} {q(target)} || mv {q(old)} {q(target)}",
                      f"rm -rf {q(old)} {q(new_app.parent)}"]
        lines.append(f"open -n {q(target)}" if IS_MAC else q(sys.executable) + " &")
        script = UPDATES / "restart.sh"
        script.write_text("\n".join(lines) + "\n")
        script.chmod(0o755)
    return script


def _launch(script: Path) -> None:
    if IS_WIN:
        flags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
                          "-File", str(script)], creationflags=flags, close_fds=True)
    else:
        subprocess.Popen(["/bin/sh", str(script)], start_new_session=True, close_fds=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def check_in_background() -> None:
    if enabled():
        threading.Thread(target=check, daemon=True).start()
