"""Cooperative cancellation for background jobs.

A job binds its project id to the worker thread. Long steps call `check()` (directly or from
progress callbacks), and every external process is started through `run`/`popen` here so that
`cancel(pid)` can kill it on the spot.
"""

import subprocess
import threading


class Cancelled(Exception):
    pass


_local = threading.local()
_flags: dict[str, threading.Event] = {}
_procs: dict[str, set[subprocess.Popen]] = {}
_guard = threading.Lock()


def bind(pid: str | None) -> None:
    """Attach this worker thread to a project (None to detach)."""
    _local.pid = pid


def current() -> str | None:
    return getattr(_local, "pid", None)


def reset(pid: str) -> None:
    with _guard:
        _flags[pid] = threading.Event()


def requested(pid: str | None = None) -> bool:
    pid = pid or current()
    ev = _flags.get(pid) if pid else None
    return bool(ev and ev.is_set())


def check(pid: str | None = None) -> None:
    if requested(pid):
        raise Cancelled()


def cancel(pid: str) -> None:
    with _guard:
        _flags.setdefault(pid, threading.Event()).set()
        procs = list(_procs.get(pid, ()))
    for p in procs:
        try:
            p.kill()
        except OSError:
            pass


def popen(cmd: list[str], pid: str | None = None, **kw) -> subprocess.Popen:
    pid = pid or current()
    check(pid)
    p = subprocess.Popen(cmd, **kw)
    if pid:
        with _guard:
            _procs.setdefault(pid, set()).add(p)
    return p


def release(p: subprocess.Popen, pid: str | None = None) -> None:
    pid = pid or current()
    if pid:
        with _guard:
            _procs.get(pid, set()).discard(p)


def run(cmd: list[str], timeout: float | None = None, text: bool = True, pid: str | None = None,
        **kw) -> subprocess.CompletedProcess:
    """Like subprocess.run(capture_output=True) but killable by cancel() and bounded by timeout."""
    pid = pid or current()
    p = popen(cmd, pid, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=text, **kw)
    try:
        out, err = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        p.kill()
        p.communicate()
        raise TimeoutError(f"{cmd[0].rsplit('/', 1)[-1]} chạy quá {int(timeout)} giây nên đã bị dừng.")
    finally:
        release(p, pid)
    if requested(pid):
        raise Cancelled()
    return subprocess.CompletedProcess(cmd, p.returncode, out, err)
