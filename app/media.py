"""ffmpeg / ffprobe / yt-dlp helpers."""

import json
import re
import subprocess
from pathlib import Path

import numpy as np

from .config import FFMPEG, FFPROBE, SAMPLE_RATE, YTDLP, YTDLP_COOKIES_BROWSER


class MediaError(Exception):
    pass


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        tail = "\n".join((r.stderr or "").strip().splitlines()[-8:])
        raise MediaError(f"{Path(cmd[0]).name} lỗi:\n{tail}")
    return r


def probe(path: Path) -> dict:
    r = run([FFPROBE, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)])
    info = json.loads(r.stdout)
    v = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
    if not v:
        raise MediaError("File không có hình (không phải video).")
    w, h = int(v["width"]), int(v["height"])
    rot = 0
    for sd in v.get("side_data_list", []) or []:
        if "rotation" in sd:
            rot = abs(int(sd["rotation"]))
    if rot in (90, 270):
        w, h = h, w
    return {
        "duration": float(info["format"].get("duration") or v.get("duration") or 0),
        "width": w,
        "height": h,
        "vcodec": v.get("codec_name"),
        "has_audio": a is not None,
    }


def extract_audio_16k(src: Path, dst: Path) -> None:
    run([FFMPEG, "-y", "-v", "error", "-i", str(src), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(dst)])


def extract_audio_full(src: Path, dst: Path) -> None:
    run([FFMPEG, "-y", "-v", "error", "-i", str(src), "-vn", "-ac", "2", "-ar", str(SAMPLE_RATE), str(dst)])


def decode_mono(path: Path, atempo: float = 1.0) -> np.ndarray:
    """Decode any audio file to mono float32 at SAMPLE_RATE."""
    cmd = [FFMPEG, "-v", "error", "-i", str(path)]
    if abs(atempo - 1.0) > 0.005:
        cmd += ["-filter:a", f"atempo={atempo:.4f}"]
    cmd += ["-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "f32le", "-"]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        raise MediaError(r.stderr.decode(errors="ignore")[-500:])
    return np.frombuffer(r.stdout, dtype=np.float32).copy()


def trim_silence(x: np.ndarray, thresh_db: float = -42.0, pad: float = 0.03) -> np.ndarray:
    if x.size == 0:
        return x
    win = int(SAMPLE_RATE * 0.01)
    n = x.size // win
    if n == 0:
        return x
    rms = np.sqrt(np.mean(x[: n * win].reshape(n, win) ** 2, axis=1) + 1e-12)
    loud = np.where(20 * np.log10(rms) > thresh_db)[0]
    if loud.size == 0:
        return x[:0]
    p = int(pad * SAMPLE_RATE)
    a = max(0, loud[0] * win - p)
    b = min(x.size, (loud[-1] + 1) * win + p)
    return x[a:b]


_PCT_RE = re.compile(r"\[download\]\s+([\d.]+)%")


def download_url(url: str, out_dir: Path, on_progress=None) -> Path:
    cmd = [
        YTDLP, "--no-playlist", "--newline", "--no-warnings",
        "--max-filesize", "500M",
        "-f", "bv*[vcodec^=avc1]+ba[ext=m4a]/bv*+ba/b",
        "--merge-output-format", "mp4",
        "--ffmpeg-location", str(Path(FFMPEG).parent),
        "-o", str(out_dir / "source.%(ext)s"),
        url,
    ]
    if YTDLP_COOKIES_BROWSER:
        cmd[1:1] = ["--cookies-from-browser", YTDLP_COOKIES_BROWSER]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    log = []
    for line in proc.stdout:
        log.append(line.rstrip())
        m = _PCT_RE.search(line)
        if m and on_progress:
            on_progress(float(m.group(1)) / 100)
    proc.wait()
    files = [f for f in out_dir.glob("source.*") if f.suffix not in (".part", ".ytdl")]
    if proc.returncode != 0 or not files:
        err = "\n".join(l for l in log if "ERROR" in l)[-600:] or "\n".join(log[-5:])
        hint = ""
        if "douyin" in url:
            hint = ("\nDouyin hay chặn tải tự động. Thử điền YTDLP_COOKIES_BROWSER=chrome trong .env "
                    "(sau khi mở douyin.com trên Chrome), hoặc tải video về máy rồi upload file.")
        raise MediaError(f"Không tải được video từ link.\n{err}{hint}")
    return files[0]
