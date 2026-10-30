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
                           data={"settings": '{"lang":"zh","voice":"google:vi","color":{"brightness":8,"contrast":10,"saturation":20,'
                                        '"temperature":25,"sharpness":30,"vignette":30}}'})
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
            size_vi = len(r.content) // 1024

            # the same video dubbed into Japanese: new language -> rewrite the lines -> export (CJK subtitles + voice)
            r = c.patch(f"/api/projects/{pid}/settings", json={"target": "ja", "voice": "google:ja"})
            r.raise_for_status()
            if c.post(f"/api/projects/{pid}/render", json={"preview_start": None}).status_code != 400:
                raise RuntimeError("đổi ngôn ngữ đích mà vẫn xuất được khi chưa viết lại lời thoại")
            c.post(f"/api/projects/{pid}/rewrite").raise_for_status()
            p = _wait(c, pid, {"review"}, 600)
            seg = p["segments"][0]
            line = seg["vi"]
            if p.get("translated_to") != "ja":
                raise RuntimeError(f"lời thoại chưa chuyển sang tiếng Nhật (translated_to={p.get('translated_to')!r})")
            if not any("\u3040" <= ch <= "\u30ff" or "\u4e00" <= ch <= "\u9fff" for ch in line):
                # Google Translate sometimes answers nothing to a CI machine; this check is about the export, so
                # put a Japanese line in by hand rather than failing on the network
                print(f"       (Google không dịch được: {line!r}) dùng câu mẫu", flush=True)
                c.patch(f"/api/projects/{pid}/segments/{seg['id']}",
                        json={"vi": "皆さんこんにちは、私のチャンネルへようこそ。"}).raise_for_status()
            else:
                print(f"       ja: {line}", flush=True)
            c.post(f"/api/projects/{pid}/render", json={"preview_start": None}).raise_for_status()
            p = _wait(c, pid, {"done"}, 900)
            r = c.get(f"/api/projects/{pid}/files/{p['outputs']['final']['file']}")
            if r.status_code != 200 or len(r.content) < 10_000:
                raise RuntimeError("video tiếng Nhật xuất ra rỗng")
            ja_kb = len(r.content) // 1024

            # timeline: cut the middle out, repeat the opening part. The export must be exactly that long.
            D = p["media"]["duration"]
            # (the first part at 2x with a fade in, the second quieter with a fade out)
            clips = [{"start": 0, "end": D * 0.4, "speed": 2, "fade_in": 0.2},
                     {"start": D * 0.7, "end": D, "volume": 0.5, "fade_out": 0.3},
                     {"start": 0, "end": D * 0.4}]
            expect = D * 0.4 / 2 + D * 0.3 + D * 0.4
            r = c.put(f"/api/projects/{pid}/timeline", json={"clips": clips})
            r.raise_for_status()
            c.post(f"/api/projects/{pid}/render", json={"preview_start": None}).raise_for_status()
            p = _wait(c, pid, {"done"}, 900)
            from app import cancel, config, store

            out = store.pdir(pid) / "out" / "final.mp4"
            pr = cancel.run([config.FFPROBE, "-v", "error", "-show_entries", "format=duration:stream=codec_type",
                             "-of", "json", str(out)], timeout=60)
            import json as _json

            info = _json.loads(pr.stdout)
            got = float(info["format"]["duration"])
            kinds = {s_["codec_type"] for s_ in info["streams"]}
            if abs(got - expect) > 0.8 or kinds != {"video", "audio"}:
                raise RuntimeError(f"timeline: video dài {got:.1f}s (cần {expect:.1f}s), luồng {sorted(kinds)}")

            # two more videos: one another size and without sound, one with speech (recognised and translated too)
            home = clip.parent
            silent = home / "silent.mp4"
            r = cancel.run([config.FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=0x993333:s=320x240:r=30",
                            "-t", "3", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(silent)], timeout=60)
            if r.returncode != 0:
                raise RuntimeError(r.stderr[-300:])
            n_lines = len(p["segments"])
            for path, name in ((silent, "silent.mp4"), (clip, "again.mp4")):
                with open(path, "rb") as f:
                    c.post(f"/api/projects/{pid}/sources", files={"file": (name, f, "video/mp4")}).raise_for_status()
                p = _wait(c, pid, {"review"}, 900)
            extra = p.get("extra_sources", [])
            added = [s_ for s_ in p["segments"] if s_.get("src_id", 0) == 2]
            ids = [s_["id"] for s_ in p["segments"]]
            if len(extra) != 2 or not added or len(set(ids)) != len(ids) or len(p["segments"]) <= n_lines:
                raise RuntimeError(f"ghép nhiều video: {len(extra)} video thêm, {len(added)} câu của video 2, id trùng={len(set(ids)) != len(ids)}")
            expect2 = expect + 3.0 + extra[1]["duration"]
            c.post(f"/api/projects/{pid}/render", json={"preview_start": None}).raise_for_status()
            p = _wait(c, pid, {"done"}, 900)
            pr = cancel.run([config.FFPROBE, "-v", "error", "-show_entries", "format=duration:stream=codec_type",
                             "-of", "json", str(out)], timeout=60)
            info = _json.loads(pr.stdout)
            got2 = float(info["format"]["duration"])
            kinds = {s_["codec_type"] for s_ in info["streams"]}
            if abs(got2 - expect2) > 1.0 or kinds != {"video", "audio"}:
                raise RuntimeError(f"ghép nhiều video: dài {got2:.1f}s (cần {expect2:.1f}s), luồng {sorted(kinds)}")
            return f"final.mp4 {size_vi} KB, tiếng Nhật {ja_kb} KB, timeline {got:.1f}s, ghép 3 video {got2:.1f}s"
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
