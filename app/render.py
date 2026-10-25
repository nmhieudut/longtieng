"""Subtitles (SRT/ASS) and final ffmpeg render."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

from .config import FFMPEG, FONTS_DIR, SUB_FONT
from .media import MediaError, extract_audio_full


def _ts_srt(t: float) -> str:
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def _ts_ass(t: float) -> str:
    cs = max(0, int(round(t * 100)))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def _sub_times(segs, i, duration):
    """Show each line from its start until its speech ends (at least the original end)."""
    s = segs[i]
    end = s["end"]
    if s.get("tts"):
        end = max(end, s["start"] + s["tts"]["secs"])
    nxt = segs[i + 1]["start"] if i + 1 < len(segs) else duration
    return s["start"], min(end, nxt)


def write_srt(segs, duration, path: Path) -> None:
    lines = []
    n = 0
    for i, s in enumerate(segs):
        if not s["vi"].strip():
            continue
        n += 1
        a, b = _sub_times(segs, i, duration)
        lines += [str(n), f"{_ts_srt(a)} --> {_ts_srt(b)}", s["vi"].strip(), ""]
    path.write_text("\n".join(lines), "utf-8")


def write_transcript(segs, json_path: Path, txt_path: Path) -> None:
    data = [{"id": s["id"], "start": s["start"], "end": s["end"], "src": s["src"], "vi": s["vi"]} for s in segs]
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=1), "utf-8")
    txt_path.write_text(
        "\n\n".join(f"[{_ts_srt(s['start'])}]\n{s['src']}\n{s['vi']}" for s in segs), "utf-8")


def sub_layout(media: dict, st: dict) -> tuple[int, int]:
    """Font size and bottom margin in pixels."""
    w, h = media["width"], media["height"]
    size = int(0.058 * min(w, h) * st["sub_size"])
    m = st["mask"]
    if m["enabled"]:
        band_center = h * (m["bottom"] + m["height"] / 2) / 100
        margin = int(band_center - size * 0.6)
    else:
        margin = int(h * st["sub_margin"] / 100)
    return size, max(0, margin)


def write_ass(segs, duration, media, st, path: Path, offset: float = 0.0, window: float | None = None) -> None:
    w, h = media["width"], media["height"]
    size, margin = sub_layout(media, st)
    outline = max(2, size // 14)
    side = int(w * 0.06)
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{SUB_FONT},{size},&H00FFFFFF,&H000000FF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,{outline},1,2,{side},{side},{margin},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    rows = []
    for i, s in enumerate(segs):
        text = s["vi"].strip().replace("\n", " ").replace("{", "(").replace("}", ")")
        if not text:
            continue
        a, b = _sub_times(segs, i, duration)
        a, b = a - offset, b - offset
        if b <= 0 or (window is not None and a >= window):
            continue
        rows.append(f"Dialogue: 0,{_ts_ass(max(0, a))},{_ts_ass(b)},Default,,0,0,0,,{text}")
    path.write_text(head + "\n".join(rows) + "\n", "utf-8")


def separate_background(proj_dir: Path, src: Path) -> Path:
    """demucs → background without vocals (cached per project)."""
    out = proj_dir / "bg_demucs.wav"
    if out.exists():
        return out
    try:
        import demucs  # noqa: F401
    except ImportError:
        raise MediaError("Chưa cài demucs. Chạy: uv sync --extra demucs  (hoặc chọn chế độ 'Giảm âm gốc').")
    full = proj_dir / "audio_full.wav"
    if not full.exists():
        extract_audio_full(src, full)
    tmp = proj_dir / "demucs_tmp"
    cmd = [sys.executable, "-m", "demucs", "--two-stems=vocals", "-n", "htdemucs",
           "-d", "mps", "-o", str(tmp), str(full)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:  # MPS can fail on some ops; retry on CPU
        cmd[cmd.index("mps")] = "cpu"
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise MediaError("demucs lỗi:\n" + r.stderr[-600:])
    next(tmp.rglob("no_vocals.wav")).replace(out)
    shutil.rmtree(tmp, ignore_errors=True)
    return out


def build_filters(proj_dir: Path, proj: dict, bg_label: str | None, start: float, length: float | None) -> str:
    st, media = proj["settings"], proj["media"]
    chain = []
    v = "[0:v]"
    m = st["mask"]
    if m["enabled"]:
        y = f"ih*{(100 - m['bottom'] - m['height']) / 100:.4f}"
        bh = f"ih*{m['height'] / 100:.4f}"
        if m["style"] == "box":
            chain.append(f"{v}drawbox=x=0:y={y}:w=iw:h={bh}:color=black@0.82:t=fill[vm]")
        else:
            chain.append(
                f"{v}split[vb][vc];[vc]crop=iw:{bh}:0:{y},"
                f"boxblur=luma_radius=min(h\\,w)/4:luma_power=3:chroma_radius=min(cw\\,ch)/4:chroma_power=3[blr];"
                f"[vb][blr]overlay=0:{y.replace('ih', 'main_h')}[vm]")
        v = "[vm]"
    if st["subtitle_mode"] == "burn":
        ass = proj_dir / ("subs_preview.ass" if length else "subs.ass")
        write_ass(proj["segments"], media["duration"], media, st, ass, offset=start, window=length)
        chain.append(f"{v}subtitles=filename={ass.name}:fontsdir={FONTS_DIR}[vs]")
        v = "[vs]"
    if v == "[0:v]":
        chain.append("[0:v]null[vout]")
    else:
        last = chain[-1]
        chain[-1] = last[: last.rfind("[")] + "[vout]"

    if bg_label and st["orig_volume"] > 0:
        chain.append(f"[{bg_label}]volume={st['orig_volume']:.3f}[bga];"
                     f"[1:a][bga]amix=inputs=2:normalize=0:duration=first[aout]")
    else:
        chain.append("[1:a]anull[aout]")
    return ";".join(chain)


def render(proj_dir: Path, proj: dict, out: Path, bg: Path | None,
           start: float = 0.0, length: float | None = None, on_progress=None) -> None:
    """bg: None = no background, the source file = its own audio, or a separate wav."""
    media = proj["media"]
    src = proj_dir / proj["source"]["file"]
    seek = ["-ss", f"{start:.3f}"] if start > 0 else []

    cmd = [FFMPEG, "-y", "-v", "error", "-progress", "pipe:1", "-nostats"]
    cmd += seek + ["-i", str(src)] + seek + ["-i", str(proj_dir / "dub.wav")]
    bg_label = None
    if bg is not None:
        if bg == src:
            bg_label = "0:a"
        else:
            cmd += seek + ["-i", str(bg)]
            bg_label = "2:a"
    filters = build_filters(proj_dir, proj, bg_label, start, length)
    cmd += ["-filter_complex", filters, "-map", "[vout]", "-map", "[aout]"]
    if length:
        cmd += ["-t", f"{length:.3f}"]
    cmd += ["-c:v", "libx264", "-preset", "ultrafast" if length else "veryfast", "-crf", "20",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
            str(out)]

    total = length or media["duration"]
    proc = subprocess.Popen(cmd, cwd=proj_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    for line in proc.stdout:
        if line.startswith("out_time_us=") and on_progress:
            try:
                on_progress(min(1.0, int(line.split("=")[1]) / 1e6 / total))
            except ValueError:
                pass
    err = proc.stderr.read()
    proc.wait()
    if proc.returncode != 0:
        raise MediaError("Render lỗi:\n" + "\n".join(err.strip().splitlines()[-8:]))
