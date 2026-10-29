"""ffmpeg / ffprobe / yt-dlp helpers."""

import json
import re
import subprocess
from pathlib import Path

import numpy as np

from . import cancel
from .config import FFMPEG, FFPROBE, SAMPLE_RATE, YTDLP_CMD, YTDLP_COOKIES_BROWSER, YTDLP_COOKIES_FILE


class MediaError(Exception):
    pass


def run(cmd: list[str], timeout: float | None = 900, **kw) -> subprocess.CompletedProcess:
    """Run a tool; killable by Huỷ and never allowed to hang forever."""
    r = cancel.run(cmd, timeout=timeout, **kw)
    if r.returncode != 0:
        tail = "\n".join((r.stderr or "").strip().splitlines()[-8:])
        raise MediaError(f"{Path(cmd[0]).name} lỗi:\n{tail}")
    return r


def probe(path: Path) -> dict:
    try:
        r = run([FFPROBE, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
                timeout=60)
    except MediaError as e:
        if "Library not loaded" in str(e) or "dyld" in str(e):  # the tool itself cannot start, not a bad file
            raise MediaError("Bộ xử lý video (ffmpeg) trong app không chạy được trên máy này, nên chưa đọc được video. "
                             "Hãy cập nhật app lên bản mới nhất (bấm “Có bản mới”) hoặc tải lại app từ trang releases.\n"
                             f"(Chi tiết: {str(e).strip().splitlines()[-1][:200]})")
        detail = str(e).strip().splitlines()[-1].split(": ")[-1]
        raise MediaError("Không đọc được file video: file có thể bị hỏng hoặc tải lên chưa xong. "
                         f"Thử tải lại file, hoặc lưu lại thành .mp4 rồi upload.\n(Chi tiết: {detail})")
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


def probe_audio(path: Path) -> float:
    """Duration of an audio file; raises if it has no audio stream."""
    r = run([FFPROBE, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)])
    info = json.loads(r.stdout)
    if not any(s["codec_type"] == "audio" for s in info.get("streams", [])):
        raise MediaError("File không có âm thanh.")
    return float(info["format"].get("duration") or 0)


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
    r = cancel.run(cmd, timeout=120, text=False)
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


_DOUYIN_ID = re.compile(r"(?:modal_id=|/video/|/note/)(\d{15,})")


def normalize_url(url: str) -> str:
    """yt-dlp only knows douyin.com/video/<id>; the web app's share links often look like
    douyin.com/jingxuan?modal_id=<id> or douyin.com/user/...?modal_id=<id>."""
    if "douyin.com" in url and "v.douyin.com" not in url:
        m = _DOUYIN_ID.search(url)
        if m:
            return f"https://www.douyin.com/video/{m.group(1)}"
    return url


def download_url(url: str, out_dir: Path, on_progress=None) -> Path:
    url = normalize_url(url)
    cmd = [
        *YTDLP_CMD, "--no-playlist", "--newline", "--no-warnings", "--socket-timeout", "30", "--retries", "3",
        "--max-filesize", "500M",
        "-f", "bv*[vcodec^=avc1]+ba[ext=m4a]/bv*+ba/b",
        "--merge-output-format", "mp4",
        "--ffmpeg-location", str(Path(FFMPEG).parent),
        "-o", str(out_dir / "source.%(ext)s"),
        url,
    ]
    if YTDLP_COOKIES_FILE:
        if not Path(YTDLP_COOKIES_FILE).is_file():
            raise MediaError(f"Không thấy file cookie: {YTDLP_COOKIES_FILE} (YTDLP_COOKIES_FILE trong .env).")
        cmd[len(YTDLP_CMD):len(YTDLP_CMD)] = ["--cookies", YTDLP_COOKIES_FILE]
    elif YTDLP_COOKIES_BROWSER:
        cmd[len(YTDLP_CMD):len(YTDLP_CMD)] = ["--cookies-from-browser", YTDLP_COOKIES_BROWSER]
    proc = cancel.popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    log = []
    try:
        for line in proc.stdout:
            log.append(line.rstrip())
            m = _PCT_RE.search(line)
            if m and on_progress:
                on_progress(float(m.group(1)) / 100)
        proc.wait()
    finally:
        cancel.release(proc)
    cancel.check()
    files = [f for f in out_dir.glob("source.*") if f.suffix not in (".part", ".ytdl")]
    if proc.returncode != 0 or not files:
        err = "\n".join(l for l in log if "ERROR" in l)[-600:] or "\n".join(log[-5:])
        hint = ""
        if "douyin" in url and "Fresh cookies" in err:
            # yt-dlp can't produce Douyin's request signatures; better cookies won't help
            raise MediaError(
                "Douyin đang chặn tải tự động bằng link (yt-dlp chưa vượt được cơ chế chống bot mới của Douyin).\n"
                "Cách làm: tải video về máy (app Douyin → Chia sẻ → Lưu video) rồi dùng “Tải file lên”.\n"
                "Thỉnh thoảng chạy `brew upgrade yt-dlp`; khi yt-dlp sửa xong thì dán link sẽ chạy lại.")
        if "douyin" in url and not (YTDLP_COOKIES_BROWSER or YTDLP_COOKIES_FILE):
            hint = ("\nDouyin hay chặn tải tự động. Thử điền YTDLP_COOKIES_BROWSER=chrome trong .env "
                    "(sau khi mở douyin.com trên Chrome), hoặc tải video về máy rồi upload file.")
        elif "douyin" in url and "cookie" in err.lower():
            hint = ("\nCookie Douyin không dùng được. Cách chắc ăn nhất: xuất cookies.txt từ douyin.com "
                    "(extension 'Get cookies.txt LOCALLY') rồi đặt YTDLP_COOKIES_FILE=cookies.txt trong .env. "
                    "Hoặc tải video về máy rồi upload file.")
        raise MediaError(f"Không tải được video từ link.\n{err}{hint}")
    return files[0]
