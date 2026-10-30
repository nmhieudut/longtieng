"""Self-update from GitHub Releases.

Each release publishes latest.json:
    {"version": "0.3.1", "shell": "0.3.0", "notes": "...",
     "patch":   {"url": ..., "sha256": ..., "size": ...},   # code + web UI only, a few MB
     "mac":     {...}, "windows": {...}}                     # the whole app, ~300MB

Same SHELL_VERSION as the running app -> light update (unzip the patch into updates/current).
Otherwise -> full update (download the app, swap it in after this process exits).
Mac restarts through a small shell script that waits for this process to end. Windows has no helper
script (a hidden PowerShell script gets blocked or killed too easily): a full update starts the *new*
exe with --finish-update, which waits for us to exit, copies itself over the install folder (logging each
step) and starts the app; a light update just starts our own exe again. See finish_update().
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
    _verify_last_attempt()
    with _lock:
        s = dict(_state)
    s.update(current=APP_VERSION, shell=SHELL_VERSION, enabled=enabled())
    return s


def _set(**kw) -> None:
    with _lock:
        _state.update(kw)


_BUSY = ("downloading", "installing", "restarting")


def _set_if_idle(**kw) -> None:
    """Like _set, but never touches the state while an update is being installed. A check that was already
    waiting on the network when Cập nhật was pressed would otherwise flip the stage back to "available" and a
    second install would start on top of the first (seen in a real update.log)."""
    with _lock:
        if _state["stage"] not in _BUSY:
            _state.update(kw)


def check(force: bool = False) -> dict:
    """Ask GitHub for the newest release (at most every 30 min unless forced)."""
    if not enabled():
        return state()
    with _lock:
        busy = _state["stage"] in _BUSY
        fresh = time.time() - _state["checked_at"] < CHECK_EVERY
    if busy or (fresh and not force):
        return state()
    try:
        req = urllib.request.Request(LATEST_URL, headers={"User-Agent": "Longtieng/" + APP_VERSION})
        with urllib.request.urlopen(req, timeout=15) as r:
            latest = json.loads(r.read().decode())
    except Exception as e:
        _set_if_idle(checked_at=time.time(), stage="idle" if not force else "error",
             error=None if not force else f"Không kiểm tra được bản mới ({type(e).__name__}). Kiểm tra mạng rồi thử lại.")
        return state()
    if _ver(latest.get("version", "0")) <= _ver(APP_VERSION):
        _set_if_idle(checked_at=time.time(), stage="none", latest=latest, kind=None, error=None)
        return state()
    kind = "patch" if latest.get("shell") == SHELL_VERSION and latest.get("patch") else "full"
    _set_if_idle(checked_at=time.time(), stage="available", latest=latest, kind=kind, error=None, progress=None)
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
        if kind == "full":
            _check_install_location()
        zpath = UPDATES / ("patch.zip" if kind == "patch" else "full.zip")
        _download(asset, zpath)
        _set(stage="installing", progress=None)
        _log(f"cập nhật {APP_VERSION} -> {latest['version']} ({kind}), app ở {_install_location()}")
        if kind == "patch":
            _install_patch(zpath, latest["version"])
            new_app = None
        else:
            new_app = _unpack_full(zpath)
        _set(stage="restarting")
        # remembered across the restart: if the app comes back on the old version, say so (see _verify_last_attempt)
        (UPDATES / "attempt.json").write_text(json.dumps({"to": latest["version"], "from": APP_VERSION, "at": time.time()}))
        if IS_WIN:
            if new_app:  # the new exe copies itself over the install folder after we exit
                _spawn(new_app / "Longtieng.exe", "--finish-update", str(_install_location()), "--wait-pid", str(os.getpid()))
            else:
                _spawn(sys.executable, "--wait-pid", str(os.getpid()))
            _log("đã chạy tiến trình tiếp theo, đóng app này")
        else:
            _launch(_restart_script(new_app))
        time.sleep(0.5)
        if request_quit:
            request_quit()
        threading.Timer(10, os._exit, [0]).start()  # a stuck window must not block the swap
        if not request_quit:
            os._exit(0)
    except Exception as e:
        _log(f"LỖI khi cập nhật: {type(e).__name__}: {e}")
        _set(stage="error", progress=None, error=f"Cập nhật lỗi: {e}")


def _log(msg: str) -> None:
    """One line in logs/update.log: what the updater did (the only trace when a restart goes wrong)."""
    try:
        f = USER_DIR / "logs" / "update.log"
        f.parent.mkdir(parents=True, exist_ok=True)
        with open(f, "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except OSError:
        pass


def _can_write(folder: Path) -> bool:
    """os.access ignores Windows permissions, so try for real."""
    try:
        t = folder / f".lt-{os.getpid()}.tmp"
        t.write_bytes(b"")
        t.unlink()
        return True
    except OSError:
        return False


def _check_install_location() -> None:
    """A full update has to replace the app where it is. Refuse early, with a reason, where that can't work;
    otherwise the old app starts again and the update "never goes away"."""
    target = _install_location()
    if IS_MAC and ("/AppTranslocation/" in str(target) or not os.access(target.parent, os.W_OK)):
        raise RuntimeError(
            "App đang chạy ở chỗ không thay thế được (trong ổ cài đặt .dmg hoặc thư mục tạm của macOS). "
            "Kéo “Lồng tiếng” vào thư mục Applications, mở từ đó rồi cập nhật lại. "
            "Nếu macOS chặn mở, chạy: xattr -cr \"/Applications/Lồng tiếng.app\"")
    if IS_WIN and ("\\Temp\\" in str(target) or ".zip" in str(target).lower() or not _can_write(target)):
        raise RuntimeError(
            f"App đang chạy ở {target}, nơi không cập nhật được (trong file zip, thư mục tạm hoặc không có quyền ghi). "
            "Giải nén file zip ra một thư mục riêng (ví dụ D:\\Longtieng), mở Longtieng.exe từ đó rồi cập nhật lại.")
    free = shutil.disk_usage(UPDATES.parent).free
    if free < 3 * 1024**3:
        raise RuntimeError(f"Ổ đĩa chỉ còn {free / 1024**3:.1f}GB trống, cần khoảng 3GB để cập nhật. Dọn bớt rồi thử lại.")


def _spawn(exe, *args: str) -> None:
    """Start a program that outlives this process (Windows)."""
    flags = (getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
             | getattr(subprocess, "CREATE_NO_WINDOW", 0))
    subprocess.Popen([str(exe), *args], creationflags=flags, close_fds=True, cwd=str(Path(exe).parent),
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def wait_pid(pid: int, timeout: float = 30) -> bool:
    """Wait until process `pid` is gone (the app that started us). False if it is still there."""
    import psutil

    end = time.time() + timeout
    while psutil.pid_exists(pid) and time.time() < end:
        time.sleep(0.25)
    return not psutil.pid_exists(pid)


def finish_update(install: Path, pid: int | None) -> int:
    """Windows full update, run by the NEW exe (from updates/full): copy this app over `install`, start it."""
    from concurrent.futures import ThreadPoolExecutor

    staged = Path(sys.executable).resolve().parent
    relaunch = not os.getenv("LONGTIENG_FINISH_NO_RELAUNCH")  # the CI test copies but does not start the app
    _log(f"finish-update: {staged} -> {install} (chờ pid {pid})")
    try:
        if pid and not wait_pid(pid):
            _log("app cũ vẫn chạy sau 30 giây, vẫn tiếp tục")
        from .desktop import _SingleInstance

        lock = None
        for _ in range(60):  # nobody may start the old exe while its files are being replaced
            lock = _SingleInstance(USER_DIR / ".lock")
            if lock.ok:
                break
            time.sleep(0.5)
        install.mkdir(parents=True, exist_ok=True)
        files = [f for f in staged.rglob("*") if f.is_file()]
        exe = [f for f in files if f.parent == staged and f.name.lower() == "longtieng.exe"]
        rest = [f for f in files if f not in exe]

        def copy_one(src: Path) -> None:
            dest = install / src.relative_to(staged)
            dest.parent.mkdir(parents=True, exist_ok=True)
            last = None
            for _ in range(8):  # antivirus may hold a fresh file for a moment
                try:
                    shutil.copy2(src, dest)
                    return
                except OSError as e:
                    last = e
                    time.sleep(1)
            raise RuntimeError(f"không chép được {dest}: {last}")

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(copy_one, rest))
        for f in exe:
            copy_one(f)
        # mirror: drop files of the old version that the new one no longer has (only in our own folder)
        if (install / "_internal").is_dir() and install.name.lower().startswith("longtieng"):
            keep = {f.relative_to(staged) for f in files}
            for f in [p for p in install.rglob("*") if p.is_file()]:
                if f.relative_to(install) not in keep and not f.name.startswith(".lt-"):
                    f.unlink(missing_ok=True)
        if not (install / "Longtieng.exe").is_file() or not list((install / "_internal").glob("python3*.dll")):
            raise RuntimeError("sau khi chép vẫn thiếu Longtieng.exe hoặc python3*.dll")
        _log(f"chép xong {len(files)} file, copy ok")
        if relaunch:
            if lock and lock.ok:
                lock.f.close()
            _spawn(install / "Longtieng.exe", "--wait-pid", str(os.getpid()))
        return 0
    except Exception as e:
        _log(f"LỖI khi chép: {type(e).__name__}: {e}")
        try:
            UPDATES.mkdir(parents=True, exist_ok=True)
            (UPDATES / "finish_error.json").write_text(json.dumps({"error": f"{type(e).__name__}: {e}", "install": str(install),
                                                                  "staged": str(staged)}))
        except OSError:
            pass
        if relaunch:  # still give the user a working app: run the new one from where it was unpacked
            _spawn(sys.executable, "--wait-pid", str(os.getpid()))
        return 1


def _cleanup_staged() -> None:
    """The unpacked update is no longer needed once the app runs from the install folder."""
    full = UPDATES / "full"
    try:
        if full.exists() and not Path(sys.executable).resolve().is_relative_to(full.resolve()):
            shutil.rmtree(full, ignore_errors=True)
            (UPDATES / "full.zip").unlink(missing_ok=True)
    except OSError:
        pass


_last_checked = False


def _verify_last_attempt() -> str | None:
    """After a restart: did the update we started actually take? Returns a message if it did not."""
    global _last_checked
    if _last_checked:
        return _state.get("last_failed")
    _last_checked = True
    fe = UPDATES / "finish_error.json"
    if fe.exists():
        try:
            e = json.loads(fe.read_text())
            msg = (f"Không chép được bản mới vào {e.get('install')} ({e.get('error')}). App đang chạy bản mới từ "
                   f"{e.get('staged')}. Đóng mọi cửa sổ Lồng tiếng và cập nhật lại, hoặc cài lại từ file zip.")
            fe.unlink(missing_ok=True)
            _set(last_failed=msg)
            return msg
        except (OSError, ValueError):
            pass
    f = UPDATES / "attempt.json"
    try:
        a = json.loads(f.read_text())
    except (OSError, ValueError):
        return None
    f.unlink(missing_ok=True)
    if _ver(APP_VERSION) < _ver(a.get("to", "0")):
        log = USER_DIR / "logs" / "update.log"
        msg = (f"Lần cập nhật lên {a['to']} trước đó chưa áp dụng được, app vẫn là bản {APP_VERSION}. "
               f"Chi tiết ở {log}. Có thể tải bản mới từ trang releases trên GitHub và cài lại.")
        _set(last_failed=msg)
        return msg
    return None


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
    """Mac: script that waits for this process to exit, swaps in the new app (full update) and relaunches."""
    pid = os.getpid()
    target = _install_location()
    q = lambda p: "'" + str(p).replace("'", "'\\''") + "'"  # noqa: E731
    log = USER_DIR / "logs" / "update.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    lines = ["#!/bin/sh", f"exec >> {q(log)} 2>&1", 'echo "== $(date) cập nhật"',
             f"while kill -0 {pid} 2>/dev/null; do sleep 0.3; done", "sleep 0.5"]
    if new_app:
        old = UPDATES / "old.app"
        lines += [f"rm -rf {q(old)}",
                  f"mv {q(target)} {q(old)} && mv {q(new_app)} {q(target)} && echo \"đã thay app: $?\" "
                  f"|| {{ echo \"thay app LỖI, trả lại bản cũ\"; mv {q(old)} {q(target)}; }}",
                  f"rm -rf {q(old)} {q(new_app.parent)}"]
    lines.append(f"open -n {q(target)}" if IS_MAC else q(sys.executable) + " &")
    script = UPDATES / "restart.sh"
    script.write_text("\n".join(lines) + "\n")
    script.chmod(0o755)
    return script


def _launch(script: Path) -> None:
    subprocess.Popen(["/bin/sh", str(script)], start_new_session=True, close_fds=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def check_in_background() -> None:
    if enabled():
        _cleanup_staged()
        threading.Thread(target=check, daemon=True).start()
