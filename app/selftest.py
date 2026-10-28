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
    try:
        out = fn()
        print(f"[ OK ] {name} ({time.time() - t:.1f}s){'  ' + str(out) if out else ''}", flush=True)
        return out
    except Exception:
        print(f"[FAIL] {name}", flush=True)
        traceback.print_exc()
        raise


def run() -> int:
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
        _step("webview import", lambda: __import__("webview") and None)
        clip = _step("tạo video thử", lambda: _make_clip(config, home))
        _step("toàn bộ quy trình qua server", lambda: _pipeline(clip))
    except Exception:
        return 1
    print("SELFTEST PASSED", flush=True)
    return 0


def _check_ffmpeg(config):
    from app import cancel

    r = cancel.run([config.FFMPEG, "-hide_banner", "-filters"], timeout=60)
    if " subtitles " not in r.stdout:
        raise RuntimeError("ffmpeg thiếu filter subtitles (libass)")
    r = cancel.run([config.FFPROBE, "-version"], timeout=60)
    return r.stdout.splitlines()[0]


def _check_ocr(ocr):
    if not ocr.available():
        raise RuntimeError("OCR không import được")


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
