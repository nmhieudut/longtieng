"""Cut / split / reorder / duplicate: a non-destructive edit list on top of the project's source video.

The project keeps its original video and its lines (times in the SOURCE video). `p["timeline"]["clips"]` says which
parts of the source make the output, in what order: [{"id", "start", "end"}, ...]. A part may appear twice
(duplicate) and the order is free. No timeline, or one clip covering everything, means "not edited" and the whole
pipeline runs exactly as before.

On export, `virtual()` returns a copy of the project in OUTPUT time: lines re-timed to where their clip lands, the
output duration, and a source file `edit.mp4` (the clips cut and joined). Everything after that (voices, mix,
subtitles, colour, logo, music) is the existing code reading that copy.
"""

import hashlib
import json
import secrets
import subprocess
import threading
from pathlib import Path

from . import cancel
from .config import FFMPEG, FFPROBE
from .media import MediaError

MIN_CLIP = 0.2   # shortest part we accept, seconds
MAX_CLIPS = 80
EDGE = 0.05      # "covers the whole video" tolerance
MIN_SPEED, MAX_SPEED = 0.25, 4.0
MAX_VOLUME = 2.0
MAX_FADE = 2.0
PROP_DEFAULTS = {"src": 0, "speed": 1.0, "volume": 1.0, "fade_in": 0.0, "fade_out": 0.0}


def speed(c: dict) -> float:
    return float(c.get("speed") or 1.0)


def clip_len(c: dict) -> float:
    """Seconds the clip lasts in the export (a 2x clip is half as long as the part of the source it covers)."""
    return (c["end"] - c["start"]) / speed(c)


def plain(c: dict) -> bool:
    """No speed / volume / fade / other-video: just a part of the main video."""
    return all(c.get(k, d) == d for k, d in PROP_DEFAULTS.items())


def clips_of(p: dict) -> list[dict]:
    return list((p.get("timeline") or {}).get("clips") or [])


def is_edited(p: dict) -> bool:
    clips = clips_of(p)
    if not clips:
        return False
    d = (p.get("media") or {}).get("duration") or 0
    c = clips[0]
    return not (len(clips) == 1 and c["start"] <= EDGE and c["end"] >= d - EDGE and plain(c))


def validate(raw, duration: float, durations: dict[int, float] | None = None, max_total: float | None = None) -> list[dict]:
    """Clean up what the browser sent. ValueError (with a message for the user) if it cannot be used.
    durations: length of each source video by index (0 = the main one)."""
    durations = durations or {0: duration}
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_CLIPS:
        raise ValueError(f"Timeline cần từ 1 đến {MAX_CLIPS} đoạn.")
    out, seen = [], set()
    for c in raw:
        try:
            src = int(c.get("src", 0))
            a, b = round(float(c["start"]), 2), round(float(c["end"]), 2)
            spd = round(min(MAX_SPEED, max(MIN_SPEED, float(c.get("speed", 1.0)))), 2)
            vol = round(min(MAX_VOLUME, max(0.0, float(c.get("volume", 1.0)))), 2)
            fi = round(min(MAX_FADE, max(0.0, float(c.get("fade_in", 0.0)))), 2)
            fo = round(min(MAX_FADE, max(0.0, float(c.get("fade_out", 0.0)))), 2)
        except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
            raise ValueError("Có đoạn không hợp lệ.") from None
        if src not in durations:
            raise ValueError("Đoạn thuộc về một video không còn trong dự án.")
        a, b = max(0.0, a), min(durations[src], b)
        if b - a < MIN_CLIP:
            raise ValueError(f"Mỗi đoạn phải dài ít nhất {MIN_CLIP:g} giây.")
        cid = str(c.get("id") or "")[:12]
        if not cid or cid in seen:
            cid = secrets.token_hex(3)
        seen.add(cid)
        length = (b - a) / spd
        out.append({"id": cid, "src": src, "start": a, "end": b, "speed": spd, "volume": vol,
                    "fade_in": min(fi, length / 2), "fade_out": min(fo, length / 2)})
    if max_total is not None and out_duration(out) > max_total:
        raise ValueError(f"Video sau khi chỉnh dài {out_duration(out) / 60:.1f} phút, vượt giới hạn {max_total / 60:g} phút.")
    return out


def layout(clips: list[dict]) -> list[tuple[dict, float]]:
    """Each clip with the output time at which it starts."""
    t, rows = 0.0, []
    for c in clips:
        rows.append((c, t))
        t += clip_len(c)
    return rows


def out_duration(clips: list[dict]) -> float:
    return sum(clip_len(c) for c in clips)


def map_segments(clips: list[dict], segs: list[dict]) -> list[dict]:
    """The lines in output time. A line belongs to the clip that contains its middle (and comes from the same
    video); a clip used twice brings its lines twice (same id). Lines in cut-out parts are dropped. The copies
    are not saved anywhere."""
    out = []
    for c, o in layout(clips):
        k = speed(c)
        for s in segs:
            if s.get("src_id", 0) != c.get("src", 0):
                continue
            mid = (s["start"] + s["end"]) / 2
            if not c["start"] <= mid < c["end"]:
                continue
            v = dict(s)
            v["src_id"] = 0  # in the edited video every line is on one timeline, whichever video it came from
            v["start"] = round(o + (max(s["start"], c["start"]) - c["start"]) / k, 3)
            v["end"] = round(o + (min(s["end"], c["end"]) - c["start"]) / k, 3)
            out.append(v)
    return out


def slots(clips: list[dict], segs: list[dict], dub_slot) -> dict[int, float]:
    """id -> seconds a line may speak in the edited video (first occurrence if a clip is duplicated)."""
    v = map_segments(clips, segs)
    dur = out_duration(clips)
    res: dict[int, float] = {}
    for i, s in enumerate(v):
        res.setdefault(s["id"], dub_slot(v, i, dur))
    return res


# ---------- the source videos

def extra_sources(p: dict) -> list[dict]:
    """Videos added to this project besides the main one: [{"id": 1, "file", "name", "duration", ...}]."""
    return list(p.get("extra_sources") or [])


def source_path(proj_dir: Path, p: dict, src: int) -> Path:
    if src == 0:
        return proj_dir / p["source"]["file"]
    info = next((e for e in extra_sources(p) if e["id"] == src), None)
    if not info:
        raise MediaError("Một đoạn trên timeline thuộc video đã bị xoá khỏi dự án.")
    return proj_dir / info["file"]


def source_durations(p: dict) -> dict[int, float]:
    d = {0: (p.get("media") or {}).get("duration") or 0.0}
    d.update({e["id"]: e["duration"] for e in extra_sources(p)})
    return d


# ---------- building edit.mp4

def _atempo(k: float) -> str:
    """ffmpeg's atempo only covers 0.5 .. 2 per instance: chain them for the rest."""
    parts = []
    while k > 2.0:
        parts.append("atempo=2.0")
        k /= 2.0
    while k < 0.5:
        parts.append("atempo=0.5")
        k /= 0.5
    parts.append(f"atempo={k:.4f}")
    return ",".join(parts)


def _fps(path: Path) -> float:
    try:
        r = cancel.run([FFPROBE, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=avg_frame_rate",
                        "-of", "csv=p=0", str(path)], timeout=30)
        a, _, b = r.stdout.strip().partition("/")
        v = float(a) / float(b or 1)
    except (ValueError, ZeroDivisionError):
        v = 30.0
    return min(60.0, max(15.0, v or 30.0))


def _key(proj_dir: Path, p: dict, clips: list[dict]) -> str:
    files = {}
    for src in sorted({c.get("src", 0) for c in clips}):
        f = source_path(proj_dir, p, src)
        st = f.stat()
        files[src] = [f.name, st.st_size, int(st.st_mtime)]
    raw = json.dumps([clips, files, (p.get("media") or {}).get("width"), (p.get("media") or {}).get("height")],
                     sort_keys=True)
    return hashlib.sha1(raw.encode()).hexdigest()


def build_edit(proj_dir: Path, p: dict, clips: list[dict], on_progress=None) -> Path:
    """Cut the clips out of their videos and join them into edit.mp4. Reused while nothing changed."""
    out = proj_dir / "edit.mp4"
    meta = proj_dir / "edit.json"
    key = _key(proj_dir, p, clips)
    try:
        if out.exists() and json.loads(meta.read_text()).get("key") == key:
            return out
    except (OSError, ValueError):
        pass
    meta.unlink(missing_ok=True)  # written again only after a complete build, so a cancelled one is never reused
    for stale in proj_dir.glob("*_edit.wav"):  # demucs files made from an older cut
        stale.unlink(missing_ok=True)
    cmd = [FFMPEG, "-y", "-v", "error", "-progress", "pipe:1", "-nostats"]
    # one input per clip: with a single input ffmpeg must keep decoded frames of the clips concat is not reading yet
    for c in clips:
        cmd += ["-ss", f"{c['start']:.3f}", "-t", f"{c['end'] - c['start']:.3f}", "-i",
                str(source_path(proj_dir, p, c.get("src", 0)))]
    n = len(clips)
    # another video can have another size, frame rate, no sound: bring every clip to the main video's format
    mixed = any(c.get("src", 0) != 0 for c in clips)
    W, H = int(p["media"]["width"]) // 2 * 2, int(p["media"]["height"]) // 2 * 2
    fps = _fps(proj_dir / p["source"]["file"]) if mixed else 30.0
    extras = {e["id"]: e for e in extra_sources(p)}
    chains, ins = [], n  # `ins` = next free input index (silence for videos without sound goes after the clips)
    for i, c in enumerate(clips):
        L, k = clip_len(c), speed(c)
        vf = []
        if mixed:
            vf += [f"scale={W}:{H}:force_original_aspect_ratio=decrease", f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2",
                   "setsar=1", f"fps={fps:.3f}", "format=yuv420p"]
        vf.append("setpts=(PTS-STARTPTS)" + (f"/{k:.4f}" if k != 1 else ""))
        if c.get("fade_in"):
            vf.append(f"fade=t=in:st=0:d={c['fade_in']:.2f}")
        if c.get("fade_out"):
            vf.append(f"fade=t=out:st={max(0.0, L - c['fade_out']):.3f}:d={c['fade_out']:.2f}")
        silent = c.get("src", 0) != 0 and not extras.get(c["src"], {}).get("has_audio", True)
        if silent:
            cmd += ["-f", "lavfi", "-t", f"{L:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
            a_in, ins = f"[{ins}:a]", ins + 1
            af = []
        else:
            a_in, af = f"[{i}:a:0]", ["asetpts=PTS-STARTPTS"]
            if mixed:
                af = ["aresample=48000", "aformat=sample_fmts=fltp:channel_layouts=stereo", "asetpts=PTS-STARTPTS"]
            if k != 1:
                af.append(_atempo(k))
        if c.get("volume", 1.0) != 1.0:
            af.append(f"volume={c['volume']:.2f}")
        if c.get("fade_in"):
            af.append(f"afade=t=in:st=0:d={c['fade_in']:.2f}")
        if c.get("fade_out"):
            af.append(f"afade=t=out:st={max(0.0, L - c['fade_out']):.3f}:d={c['fade_out']:.2f}")
        chains.append(f"[{i}:v:0]{','.join(vf)}[v{i}]")
        chains.append(f"{a_in}{','.join(af) if af else 'anull'}[a{i}]")
    graph = ";".join(chains) + ";" + "".join(f"[v{i}][a{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=1[v][a]"
    part = out.with_name("edit.part.mp4")
    cmd += ["-filter_complex", graph, "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "ultrafast",
            "-crf", "16", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(part)]
    total = out_duration(clips)
    proc = cancel.popen(cmd, cwd=proj_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    errs: list[str] = []
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
        proc.kill()
        proc.wait()
        part.unlink(missing_ok=True)
        raise
    finally:
        proc.wait()
        t.join(timeout=5)
        cancel.release(proc)
    if cancel.requested() or proc.returncode != 0:
        part.unlink(missing_ok=True)
    cancel.check()
    if proc.returncode != 0:
        raise MediaError("Cắt ghép video lỗi:\n" + "\n".join("".join(errs).strip().splitlines()[-8:]))
    part.replace(out)
    meta.write_text(json.dumps({"key": key, "duration": total}))
    return out


def virtual(proj_dir: Path, p: dict, on_progress=None) -> dict:
    """The project as the export sees it. Unchanged (the very same dict) when there is no edit."""
    if not is_edited(p):
        if extra_sources(p):  # videos added to the project but not on the timeline: their lines are not part of this one
            return p | {"segments": [s for s in p["segments"] if s.get("src_id", 0) == 0]}
        return p
    clips = clips_of(p)
    build_edit(proj_dir, p, clips, on_progress)
    return p | {
        "segments": map_segments(clips, p["segments"]),
        "media": p["media"] | {"duration": out_duration(clips)},
        "source": p["source"] | {"file": "edit.mp4"},
    }
