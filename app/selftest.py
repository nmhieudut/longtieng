"""End-to-end check of a packaged build, without a window: `Longtieng --selftest`.

Makes a short Chinese clip (gTTS voice over a plain video), then runs the whole pipeline through
the real HTTP server: upload -> speech recognition -> subtitle OCR -> translate -> dub -> render
with burned-in Vietnamese subtitles. Needs internet (model download, Google TTS/Translate).
Uses a throwaway data folder and the tiny Whisper model unless told otherwise.
"""

import os
import sys
import tempfile
import time
import traceback
from pathlib import Path


def _step(name, fn):
    t = time.time()
    print(f"[ .. ] {name}", flush=True)
    try:
        out = fn()
        print(f"[ OK ] {name} ({time.time() - t:.1f}s){'  ' + str(out) if out else ''}", flush=True)
        return out
    except BaseException as e:  # SystemExit from a library too: say where it happened
        print(f"[FAIL] {name}: {type(e).__name__}: {e}", flush=True)
        traceback.print_exc(file=sys.stdout)
        sys.stdout.flush()
        raise RuntimeError(name) from e


def _check_dotnet():
    """pywebview draws the Windows window through pythonnet; this is what fails on a blocked download."""
    if sys.platform != "win32":
        return
    import clr  # noqa: F401  loads Python.Runtime.dll
    clr.AddReference("System.Windows.Forms")


def run() -> int:
    import faulthandler

    faulthandler.enable(file=sys.stdout)  # native crashes (DLL problems) still leave a trace
    home = Path(tempfile.mkdtemp(prefix="longtieng-selftest-"))
    os.environ.setdefault("LONGTIENG_HOME", str(home))
    os.environ.setdefault("FASTER_WHISPER_MODEL", "tiny")
    os.environ.setdefault("WHISPER_MODEL", "mlx-community/whisper-tiny")
    os.environ["OPENAI_API_KEY"] = ""  # exercise the free path (Google)

    from app import config, ocr, stt

    print(f"frozen={config.FROZEN} data={config.USER_DIR} stt={stt.engine()} ocr={ocr._engine()}", flush=True)
    try:
        _step("ffmpeg có libass", lambda: _check_ffmpeg(config))
        _step("yt-dlp", lambda: _check_ytdlp(config))
        _step("OCR sẵn sàng", lambda: _check_ocr(ocr))
        # the model is large: keep it between runs on this machine (CI downloads it once per build)
        os.environ.setdefault("LONGTIENG_VIENEU_DIR", str(Path(tempfile.gettempdir()) / "longtieng-selftest-vieneu"))
        _step("giọng VieNeu (offline)", _check_vieneu)
        _step("webview import", lambda: __import__("webview") and None)
        _step(".NET cho cửa sổ (pythonnet)", _check_dotnet)
        clip = _step("tạo video thử", lambda: _make_clip(config, home))
        if stt.engine() == "mlx" and not _metal_ok():
            # GitHub's macOS runners are VMs without a usable GPU; the same app is tested on a real Mac
            print("[SKIP] toàn bộ quy trình: máy này không có GPU Metal (máy ảo CI)", flush=True)
            _step("server + giao diện", _server_only)
        else:
            _step("toàn bộ quy trình qua server", lambda: _pipeline(clip))
    except Exception:
        return 1
    print("SELFTEST PASSED", flush=True)
    return 0


def _metal_ok() -> bool:
    try:
        import mlx.core as mx
        return bool(mx.metal.is_available())
    except Exception:
        return False


def _server_only():
    import httpx

    from app.desktop import _free_port, _start_server

    port = _free_port()
    server = _start_server(port)
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=60) as c:
            assert c.get("/").status_code == 200, "giao diện không tải được"
            assert c.get("/api/config").status_code == 200
            return c.get("/api/app-settings").json()["version"]
    finally:
        server.should_exit = True


def _check_ffmpeg(config):
    from app import cancel

    r = cancel.run([config.FFMPEG, "-hide_banner", "-filters"], timeout=60)
    if " subtitles " not in r.stdout:
        raise RuntimeError("ffmpeg thiếu filter subtitles (libass)")
    r = cancel.run([config.FFPROBE, "-version"], timeout=60)
    return r.stdout.splitlines()[0]


def _check_ocr(ocr):
    if ocr._engine() == "rapid":
        import rapidocr_onnxruntime  # noqa: F401  (raise the real import error, not just False)
    if not ocr.available():
        raise RuntimeError("OCR không import được")
    import numpy as np

    if ocr._engine() == "rapid":  # load the models once: catches missing model/config files
        from rapidocr_onnxruntime import RapidOCR
        RapidOCR()(np.zeros((64, 64, 3), np.uint8))


def _check_vieneu():
    """Offline voices: download the model, read one line. The only check the packaged bundle gets."""
    import soundfile as sf

    from app import vieneu_tts

    if not vieneu_tts.available():
        raise RuntimeError("VieNeu không có trong bản này")
    vieneu_tts.ensure_model()
    out = Path(tempfile.mkdtemp(prefix="vieneu-")) / "t.wav"
    vieneu_tts.synth_wav("Xin chào các bạn, đây là giọng đọc thử.", "truc_ly", out)
    info = sf.info(str(out))
    if info.duration < 1.0:
        raise RuntimeError(f"giọng quá ngắn ({info.duration:.1f}s)")
    return f"{info.duration:.1f}s âm thanh"


def _check_ytdlp(config):
    from app import cancel

    r = cancel.run([*config.YTDLP_CMD, "--version"], timeout=120)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-300:])
    return r.stdout.strip()


def _make_clip(config, home: Path) -> Path:
    from gtts import gTTS

    from app import cancel

    speech = home / "speech.mp3"
    gTTS("大家好，欢迎来到我的频道。今天我们来做一道非常简单的家常菜。", lang="zh-CN", timeout=30).save(str(speech))
    clip = home / "selftest.mp4"
    r = cancel.run([config.FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=0x336699:s=480x854:r=25",
                    "-i", str(speech), "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                    str(clip)], timeout=120)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-400:])
    return clip


def _pipeline(clip: Path) -> str:
    import httpx

    from app.desktop import _free_port, _start_server

    port = _free_port()
    server = _start_server(port)
    base = f"http://127.0.0.1:{port}"
    try:
        with httpx.Client(base_url=base, timeout=60) as c:
            assert c.get("/").status_code == 200, "giao diện không tải được"
            assert c.get("/api/config").status_code == 200
            with open(clip, "rb") as f:
                r = c.post("/api/projects/upload", files={"file": ("selftest.mp4", f, "video/mp4")},
                           data={"settings": '{"lang":"zh","voice":"google:vi"}'})
            r.raise_for_status()
            pid = r.json()["id"]
            p = _wait(c, pid, {"review"}, 1800)
            if not p["segments"]:
                raise RuntimeError("không nhận dạng được câu nào")
            print(f"       {len(p['segments'])} câu: {p['segments'][0]['src']} -> {p['segments'][0]['vi']}", flush=True)
            r = c.post(f"/api/projects/{pid}/render", json={"preview_start": None})
            r.raise_for_status()
            p = _wait(c, pid, {"done"}, 1800)
            final = p["outputs"].get("final")
            if not final:
                raise RuntimeError("không có video xuất ra")
            r = c.get(f"/api/projects/{pid}/files/{final['file']}")
            if r.status_code != 200 or len(r.content) < 10_000:
                raise RuntimeError("video xuất ra rỗng")
            return f"final.mp4 {len(r.content) // 1024} KB"
    finally:
        server.should_exit = True


def _wait(c, pid: str, want: set[str], limit: float) -> dict:
    t0, last = time.time(), ""
    while time.time() - t0 < limit:
        p = c.get(f"/api/projects/{pid}").json()
        st = p["status"]
        msg = f"{st['stage']} {st.get('message', '')}"
        if msg != last:
            print(f"       … {msg}", flush=True)
            last = msg
        if st["stage"] in want:
            return p
        if st["stage"] == "error":
            raise RuntimeError(st.get("error") or st.get("message"))
        time.sleep(1)
    raise TimeoutError(f"quá {limit}s ở bước {last}")


if __name__ == "__main__":
    sys.exit(run())
