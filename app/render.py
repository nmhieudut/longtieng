"""Subtitles (SRT/ASS) and final ffmpeg render."""

import json
import shutil
import subprocess
import sys
import threading
from pathlib import Path

from . import cancel
from . import frame
from .config import FFMPEG, SUB_FONT, fonts_rel, sub_font, target_info
from .media import MediaError, extract_audio_full, probe_audio


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


# ASS colours are &HAABBGGRR (AA = transparency). BorderStyle 1 = outline, 3 = box behind the text.
SUB_STYLES = {
    "classic":    {"label": "Trắng viền đen", "text": "&H00FFFFFF", "edge": "&H00000000", "border": 1},
    "yellow":     {"label": "Vàng viền đen", "text": "&H0000E6FF", "edge": "&H00000000", "border": 1},
    "box_dark":   {"label": "Chữ trắng, nền đen", "text": "&H00FFFFFF", "edge": "&H50000000", "border": 3},
    "box_yellow": {"label": "Chữ đen, nền vàng", "text": "&H00000000", "edge": "&H0000E6FF", "border": 3},
}


def sub_layout(media: dict, st: dict) -> tuple[int, int]:
    """Font size and bottom margin in pixels, on the output canvas."""
    g = frame.geom(media, st["frame"])
    W, H = g["W"], g["H"]
    size = int(0.058 * min(W, H) * st["sub_size"])
    m = st["mask"]
    margin = int(H * st["sub_margin"] / 100)
    if m["enabled"]:
        # put the Vietnamese line where the original subtitles were (now hidden under the mask)
        band_center = media["height"] * (1 - (m["bottom"] + m["height"] / 2) / 100)
        y = frame.map_y(g, band_center)
        if 0 < y < H:
            margin = int(H - y - size * 0.6)
    return size, max(0, margin)


def _ass_head(W: int, H: int, styles: list[str]) -> str:
    return f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
{chr(10).join(styles)}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _clean(text: str) -> str:
    return text.strip().replace("\n", " ").replace("{", "(").replace("}", ")")


_CJK_BREAK_AFTER = "，。！？；：、,.!?;:…）」』"


def _wrap_cjk(text: str, max_chars: int) -> str:
    """Chinese, Japanese and Korean text has no spaces, and the subtitle renderer only breaks lines at spaces,
    so a long sentence would run off both sides of the video. Break it ourselves, preferably after punctuation."""
    if len(text) <= max_chars:
        return text
    clauses, cur = [], ""
    for ch in text:
        cur += ch
        if ch in _CJK_BREAK_AFTER:
            clauses.append(cur)
            cur = ""
    if cur:
        clauses.append(cur)
    lines, line = [], ""
    for c in clauses:
        while len(c) > max_chars:  # a clause with no punctuation at all
            if line:
                lines.append(line)
                line = ""
            lines.append(c[:max_chars])
            c = c[max_chars:]
        if len(line) + len(c) > max_chars and line:
            lines.append(line)
            line = ""
        line += c
    if line:
        lines.append(line)
    return "\\N".join(l.strip() for l in lines if l.strip())


def logo_text_style(st: dict, W: int, H: int) -> tuple[str, str] | None:
    """Channel name in a corner (only when no logo image is set): (style line, dialogue line)."""
    lg = st["logo"]
    if not lg["text"] or lg["image"]:
        return None
    size = max(14, int(min(W, H) * 0.035 * (lg["size"] / 0.16) ** 0.5))
    align = {"tl": 7, "tr": 9, "bl": 1, "br": 3}[lg["position"]]
    alpha = f"{int((1 - lg['opacity']) * 255):02X}"
    pad = int(min(W, H) * 0.04)
    style = (f"Style: Logo,{SUB_FONT},{size},&H{alpha}FFFFFF,&H000000FF,&H{alpha}000000,&H00000000,-1,0,0,0,"
             f"100,100,0,0,1,{max(1, size // 12)},0,{align},{pad},{pad},{pad},1")
    return style, f"Dialogue: 1,0:00:00.00,9:59:59.00,Logo,,0,0,0,,{_clean(lg['text'])}"


def write_ass(segs, duration, media, st, path: Path, offset: float = 0.0, window: float | None = None,
              subs: bool = True, only_at: float | None = None) -> None:
    """Burned-in subtitles (+ the channel-name watermark). only_at: a single line for a still preview."""
    g = frame.geom(media, st["frame"])
    W, H = g["W"], g["H"]
    size, margin = sub_layout(media, st)
    sty = SUB_STYLES.get(st.get("sub_style"), SUB_STYLES["classic"])
    side = int(W * 0.06)
    if sty["border"] == 3:
        edge_w, shadow = max(4, size // 4), 0  # box padding
    else:
        edge_w, shadow = max(2, size // 14), 1
    styles = [f"Style: Default,{sub_font(st['target'])},{size},{sty['text']},&H000000FF,{sty['edge']},&H64000000,-1,0,0,0,"
              f"100,100,0,0,{sty['border']},{edge_w},{shadow},2,{side},{side},{margin},1"]
    cjk = target_info(st["target"])["cjk"]
    per_line = max(6, int((W - 2 * side - 2 * edge_w) / (size * 1.08)))

    def line_text(raw: str) -> str:
        t = _clean(raw)
        return _wrap_cjk(t, per_line) if cjk else t

    rows = []
    logo = logo_text_style(st, W, H)
    if logo:
        styles.append(logo[0])
        rows.append(logo[1])
    if subs and only_at is not None:
        lines = [s for s in segs if s["vi"].strip()]
        if lines:  # the line on screen at that moment, else the nearest one
            best = min(lines, key=lambda s: 0 if s["start"] <= only_at <= s["end"] else abs(s["start"] - only_at))
            rows.append(f"Dialogue: 0,0:00:00.00,9:59:59.00,Default,,0,0,0,,{line_text(best['vi'])}")
    elif subs:
        for i, s in enumerate(segs):
            text = line_text(s["vi"])
            if not text:
                continue
            a, b = _sub_times(segs, i, duration)
            a, b = a - offset, b - offset
            if b <= 0 or (window is not None and a >= window):
                continue
            rows.append(f"Dialogue: 0,{_ts_ass(max(0, a))},{_ts_ass(b)},Default,,0,0,0,,{text}")
    path.write_text(_ass_head(W, H, styles) + "\n".join(rows) + "\n", "utf-8")


def logo_path(st: dict) -> Path | None:
    from . import logos

    item = logos.get(st["logo"].get("image"))
    return logos.path(item) if item and logos.path(item).exists() else None


def logo_filter(st: dict, g: dict, logo_in: str, v_in: str, v_out: str) -> str:
    lg = st["logo"]
    lw = max(16, int(g["W"] * lg["size"]) // 2 * 2)
    pad = int(min(g["W"], g["H"]) * 0.04)
    x = pad if lg["position"] in ("tl", "bl") else f"main_w-overlay_w-{pad}"
    y = pad if lg["position"] in ("tl", "tr") else f"main_h-overlay_h-{pad}"
    return (f"{logo_in}scale={lw}:-2,format=rgba,colorchannelmixer=aa={lg['opacity']:.2f}[lgo];"
            f"{v_in}[lgo]overlay={x}:{y}:format=auto{v_out}")


def video_chain(proj: dict, ass: Path | None, cwd: Path, logo_in: str | None) -> tuple[list[str], str]:
    """Mask the original subtitles -> reframe -> burn subtitles/watermark -> logo. Returns (filters, label)."""
    st, media = proj["settings"], proj["media"]
    chain, v = [], "[0:v]"
    if st["mask"]["enabled"]:
        chain.append(mask_filter(st["mask"], v, "[vm]"))
        v = "[vm]"
    g = frame.geom(media, st["frame"])
    if g["active"]:
        chain.append(frame.video_filter(g, v, "[vf]"))
        v = "[vf]"
    if ass:
        chain.append(f"{v}subtitles=filename={ass.name}:fontsdir={fonts_rel(cwd)}[vs]")
        v = "[vs]"
    if logo_in:
        chain.append(logo_filter(st, g, logo_in, v, "[vl]"))
        v = "[vl]"
    return chain, v


def still(proj_dir: Path, proj: dict, t: float, out: Path, width: int | None = None) -> Path:
    """One frame exactly as the export will look (framing, mask, subtitle style, logo)."""
    src = proj_dir / proj["source"]["file"]
    st = proj["settings"]
    ass = None
    if st["subtitle_mode"] == "burn" or logo_text_style(st, 2, 2):
        ass = proj_dir / "still.ass"
        write_ass(proj["segments"], proj["media"]["duration"], proj["media"], st, ass,
                  subs=st["subtitle_mode"] == "burn", only_at=t)
    cmd = [FFMPEG, "-y", "-v", "error", "-ss", f"{t:.3f}", "-i", str(src)]
    lp = logo_path(st)
    if lp:
        cmd += ["-i", str(lp)]
    chain, v = video_chain(proj, ass, proj_dir, "[1:v]" if lp else None)
    if width:
        chain.append(f"{v}scale={width}:-2[vw]")
        v = "[vw]"
    if not chain:
        chain, v = ["[0:v]null[vn]"], "[vn]"
    cmd += ["-filter_complex", ";".join(chain), "-map", v, "-frames:v", "1", "-q:v", "3", str(out)]
    r = cancel.run(cmd, timeout=60, cwd=proj_dir)
    if r.returncode != 0 or not out.exists():
        raise MediaError("Không tạo được ảnh xem trước:\n" + r.stderr[-400:])
    return out


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
    r = cancel.run(cmd, timeout=3600)
    if r.returncode != 0:  # MPS can fail on some ops; retry on CPU
        cmd[cmd.index("mps")] = "cpu"
        r = cancel.run(cmd, timeout=3600)
        if r.returncode != 0:
            raise MediaError("demucs lỗi:\n" + r.stderr[-600:])
    next(tmp.rglob("no_vocals.wav")).replace(out)
    shutil.rmtree(tmp, ignore_errors=True)
    return out


def mask_filter(m: dict, v_in: str, v_out: str) -> str:
    """Blur or black out the band where the original subtitles sit (on the source picture)."""
    y = f"ih*{(100 - m['bottom'] - m['height']) / 100:.4f}"
    bh = f"ih*{m['height'] / 100:.4f}"
    if m["style"] == "box":
        return f"{v_in}drawbox=x=0:y={y}:w=iw:h={bh}:color=black@0.82:t=fill{v_out}"
    return (f"{v_in}split[vb][vc];[vc]crop=iw:{bh}:0:{y},"
            f"boxblur=luma_radius=min(h\\,w)/4:luma_power=3:chroma_radius=min(cw\\,ch)/4:chroma_power=3[blr];"
            f"[vb][blr]overlay=0:{y.replace('ih', 'main_h')}{v_out}")


MUSIC_REF_DB = -16.0  # reference RMS level a track is normalised to before the volume slider


def mean_volume_db(path: Path) -> float:
    r = cancel.run([FFMPEG, "-v", "info", "-i", str(path), "-vn", "-af", "volumedetect", "-f", "null", "-"],
                   timeout=180)
    for line in r.stderr.splitlines():
        if "mean_volume:" in line:
            try:
                return float(line.split("mean_volume:")[1].split("dB")[0])
            except ValueError:
                break
    return MUSIC_REF_DB


def music_path(proj: dict) -> Path | None:
    from . import music

    tid = (proj["settings"].get("music") or {}).get("track")
    m = music.get(tid) if tid else None
    return music.path(m) if m and music.path(m).exists() else None


def build_filters(proj_dir: Path, proj: dict, bg_label: str | None, start: float, length: float | None,
                  music_label: str | None = None, logo_label: str | None = None) -> str:
    st, media = proj["settings"], proj["media"]
    ass = None
    if st["subtitle_mode"] == "burn" or logo_text_style(st, 2, 2):
        ass = proj_dir / ("subs_preview.ass" if length else "subs.ass")
        write_ass(proj["segments"], media["duration"], media, st, ass, offset=start, window=length,
                  subs=st["subtitle_mode"] == "burn")
    chain, v = video_chain(proj, ass, proj_dir, f"[{logo_label}]" if logo_label else None)
    if v == "[0:v]":
        chain.append("[0:v]null[vout]")
    else:
        last = chain[-1]
        chain[-1] = last[: last.rfind("[")] + "[vout]"

    mix = ["[dub]"]
    music = st.get("music") or {}
    if music_label:
        chain.append("[1:a]asplit=2[dub][sc]")
    else:
        chain.append("[1:a]anull[dub]")
    if bg_label and st["orig_volume"] > 0:
        chain.append(f"[{bg_label}]volume={st['orig_volume']:.3f}[bga]")
        mix.append("[bga]")
    if music_label:
        total = length or media["duration"]
        fade = min(2.0, total / 4)
        gain = 10 ** (music.get("_norm_db", 0.0) / 20) * music["volume"]
        m = (f"[{music_label}]aresample=48000,volume={gain:.4f},"
             f"afade=t=in:d=0.5,afade=t=out:st={max(0.0, total - fade):.3f}:d={fade:.3f}")
        if music.get("duck", True):
            # the dub voice drives a compressor on the music: louder voice → quieter music
            chain.append(f"{m}[mraw]")
            chain.append("[mraw][sc]sidechaincompress=threshold=0.05:ratio=3:attack=20:release=500:makeup=1[mus]")
        else:
            chain.append(f"{m}[mus]")
            chain.append("[sc]anullsink")
        mix.append("[mus]")
    if len(mix) == 1:
        chain.append("[dub]anull[aout]")
    else:
        chain.append(f"{''.join(mix)}amix=inputs={len(mix)}:normalize=0:duration=first,alimiter=limit=0.95[aout]")
    return ";".join(chain)


def render(proj_dir: Path, proj: dict, out: Path, bg: Path | None,
           start: float = 0.0, length: float | None = None, on_progress=None) -> None:
    """bg: None = no background, the source file = its own audio, or a separate wav."""
    media = proj["media"]
    src = proj_dir / proj["source"]["file"]
    seek = ["-ss", f"{start:.3f}"] if start > 0 else []

    # write next to the target and swap in only on success: a cancelled or failed export
    # must never replace the last good video with a truncated one
    part = out.with_name(out.stem + ".part" + out.suffix)
    cmd = [FFMPEG, "-y", "-v", "error", "-progress", "pipe:1", "-nostats"]
    cmd += seek + ["-i", str(src)] + seek + ["-i", str(proj_dir / "dub.wav")]
    bg_label = None
    if bg is not None:
        if bg == src:
            bg_label = "0:a"
        else:
            cmd += seek + ["-i", str(bg)]
            bg_label = "2:a"
    music_label = None
    track = music_path(proj)
    if track:
        mu = proj["settings"]["music"]
        mdur = probe_audio(track)
        # bring every track to the same loudness so "40%" sounds alike whatever the file's mastering
        proj = proj | {"settings": proj["settings"] | {"music": mu | {"_norm_db": MUSIC_REF_DB - mean_volume_db(track)}}}
        offset = mu["start"] + start
        if mdur > 0:
            offset %= mdur  # the track loops, so any offset maps into one pass
        n = sum(1 for x in cmd if x == "-i")
        cmd += ["-stream_loop", "-1", "-ss", f"{offset:.3f}", "-i", str(track)]
        music_label = f"{n}:a"
    logo_label = None
    lp = logo_path(proj["settings"])
    if lp:
        logo_label = f"{sum(1 for x in cmd if x == '-i')}:v"
        cmd += ["-i", str(lp)]
    filters = build_filters(proj_dir, proj, bg_label, start, length, music_label, logo_label)
    cmd += ["-filter_complex", filters, "-map", "[vout]", "-map", "[aout]"]
    cmd += ["-t", f"{(length or media['duration']):.3f}"]
    cmd += ["-c:v", "libx264", "-preset", "ultrafast" if length else "veryfast", "-crf", "20",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
            str(part)]

    total = length or media["duration"]
    proc = cancel.popen(cmd, cwd=proj_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    errs: list[str] = []
    # drain stderr on the side so a chatty ffmpeg can never block on a full pipe
    t = threading.Thread(target=lambda: errs.extend(proc.stderr), daemon=True)
    t.start()
    try:
        for line in proc.stdout:
            if line.startswith("out_time_us=") and on_progress:
                try:
                    on_progress(min(1.0, int(line.split("=")[1]) / 1e6 / total))
                except ValueError:
                    pass
    except BaseException:
        proc.kill()  # e.g. Huỷ raised from the progress callback
        proc.wait()
        part.unlink(missing_ok=True)
        raise
    finally:
        proc.wait()
        t.join(timeout=5)
        cancel.release(proc)
    err = "".join(errs)
    if cancel.requested() or proc.returncode != 0:
        part.unlink(missing_ok=True)
    cancel.check()
    if proc.returncode != 0:
        raise MediaError("Render lỗi:\n" + "\n".join(err.strip().splitlines()[-8:]))
    part.replace(out)
