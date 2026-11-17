"""TTS per line, fit each line into its time slot, and mix the dub track."""

import hashlib
import threading
import time
from pathlib import Path

import numpy as np
import soundfile as sf

from .config import DATA_DIR, FFMPEG, MAX_ATEMPO, MAX_VOICE_SPEEDUP, SAMPLE_RATE, target_info
from . import cancel
from .media import decode_mono, trim_silence

OVERLAP_TOL = 0.12   # seconds a line may run past its slot (the next line starts under its tail); the tail is faded


def slot(segs: list[dict], i: int, duration: float) -> float:
    """Seconds a line may use: from its start until the next line of the same video starts.
    `duration` is the main video's length; the lines of an added video (src_id > 0) end a second after their own end."""
    vid = segs[i].get("src_id", 0)
    for j in range(i + 1, len(segs)):
        if segs[j].get("src_id", 0) == vid and segs[j]["start"] > segs[i]["start"]:
            return max(0.3, segs[j]["start"] - segs[i]["start"])
    end = duration if vid == 0 else segs[i]["end"] + 1.0
    return max(0.3, end - segs[i]["start"])


def classify(speech_secs: float, slot_secs: float, speed: float = 1.0) -> dict:
    """Single source of truth for a line's fit status (UI badge + renderer).

    speech_secs: length at the user's chosen rate (before per-line speed-up).
    """
    need = speech_secs / (slot_secs + OVERLAP_TOL) if slot_secs > 0 else 99   # a line may run a hair into the next one
    max_speed = MAX_VOICE_SPEEDUP * MAX_ATEMPO
    if need <= 1.02:
        status = "ok"
    elif need <= max_speed:
        status = "fast"
    else:
        status = "overflow"
    return {"status": status, "need": round(need, 2), "speed": round(speed, 2)}


def estimate(text: str, slot_secs: float, rate: float, target: str = "vi") -> dict:
    secs = len(text) / (target_info(target)["cps"] * rate)
    return classify(secs, slot_secs) | {"estimated": True}


# Neither engine has a speed setting: fetch once at 1.0x (cached, so speed-up retries cost nothing),
# then change the tempo with ffmpeg.
_CACHE = DATA_DIR.parent / "tts_cache"


def _cached(engine: str, voice: str, text: str, make, ext: str = ".mp3") -> Path:
    key = hashlib.sha1(f"{voice}|{text}".encode()).hexdigest()
    p = _CACHE / engine / f"{key}{ext}"
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(f"{p.stem}.{threading.get_ident()}{ext}")  # keeps the real extension
        make(tmp)
        tmp.replace(p)
    return p


def _tempo(src: Path, rate: float, out: Path) -> None:
    if abs(rate - 1.0) < 0.005:
        out.write_bytes(src.read_bytes())
        return
    filters, r = [], rate
    while r > 2.0:
        filters.append("atempo=2.0")
        r /= 2.0
    filters.append(f"atempo={r:.4f}")
    res = cancel.run([FFMPEG, "-y", "-v", "error", "-i", str(src), "-filter:a", ",".join(filters), str(out)],
                     timeout=60)
    if res.returncode != 0:
        raise RuntimeError("ffmpeg atempo lỗi: " + res.stderr[-300:])


def _encode(src: Path, rate: float, out: Path) -> None:
    """Any audio file -> `out` (mp3), sped up by `rate` when it isn't 1.0."""
    filters, r = [], rate
    if abs(rate - 1.0) >= 0.005:
        while r > 2.0:
            filters.append("atempo=2.0")
            r /= 2.0
        filters.append(f"atempo={r:.4f}")
    cmd = [FFMPEG, "-y", "-v", "error", "-i", str(src)]
    if filters:
        cmd += ["-filter:a", ",".join(filters)]
    res = cancel.run(cmd + ["-ac", "1", "-c:a", "libmp3lame", "-q:a", "2", str(out)], timeout=60)
    if res.returncode != 0:
        raise RuntimeError("ffmpeg lỗi: " + res.stderr[-300:])


def _google_raw(text: str, out: Path, lang: str = "vi") -> None:
    from gtts import gTTS

    gTTS(text, lang=lang, timeout=30).save(str(out))


def _synth(text: str, voice: str, rate: float, out: Path) -> None:
    if voice.startswith("vieneu:"):
        # no speed setting: read once at 1.0x (cached), then change the tempo with ffmpeg
        from . import vieneu_tts

        vid = voice.split(":", 1)[1]
        base = _cached("vieneu", voice, text, lambda p: vieneu_tts.synth_wav(text, vid, p), ext=".wav")
        return _encode(base, rate, out)
    if voice.startswith("google:"):
        engine, last = "google", None
        code = voice.split(":", 1)[1] or "vi"  # google:vi, google:en, google:zh-CN ...
        make = lambda t, p: _google_raw(t, p, code)  # noqa: E731
        for attempt in range(3):
            try:
                base = _cached(engine, voice, text, lambda p: make(text, p))
                return _tempo(base, rate, out)
            except RuntimeError:
                raise
            except Exception as e:  # network hiccup
                last = e
                time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"Google TTS lỗi: {last}")
    raise RuntimeError(f"Không có giọng {voice!r}. Chọn lại giọng trong phần Giọng đọc.")


def synth(text: str, voice: str, rate: float, out: Path) -> None:
    _synth(text, voice, rate, out)


def make_line(proj_dir: Path, seg: dict, slot_secs: float, voice: str, rate: float) -> dict:
    """Synthesize one line and fit it to slot_secs. Returns the seg's new tts+fit."""
    text = seg["vi"].strip()
    ver = ((seg.get("tts") or {}).get("ver") or 0) + 1
    raw = proj_dir / "tts" / f"{seg['id']}_raw.mp3"
    if not text:
        return {"tts": None, "fit": None}

    _synth(text, voice, rate, raw)
    audio = trim_silence(decode_mono(raw))
    base_secs = audio.size / SAMPLE_RATE
    fit = classify(base_secs, slot_secs)
    speed = 1.0

    if fit["status"] != "ok":
        # 1) read it faster
        read_speed = min(MAX_VOICE_SPEEDUP, fit["need"] * 1.03)
        _synth(text, voice, rate * read_speed, raw)
        audio = trim_silence(decode_mono(raw))
        speed = read_speed
        # 2) still long: time-stretch the remainder
        over = (audio.size / SAMPLE_RATE) / (slot_secs + OVERLAP_TOL)
        if over > 1.02:
            tempo = min(MAX_ATEMPO, over * 1.02)
            audio = trim_silence(decode_mono(raw, atempo=tempo))
            speed *= tempo
        fit = classify(base_secs, slot_secs, speed)
        # mix() cuts whatever still runs past the slot, so that is an overflow whatever the ratio says
        if audio.size / SAMPLE_RATE > (slot_secs + OVERLAP_TOL) * 1.02:
            fit["status"] = "overflow"

    for old in (proj_dir / "tts").glob(f"{seg['id']}_v*.wav"):
        old.unlink(missing_ok=True)
    out = proj_dir / "tts" / f"{seg['id']}_v{ver}.wav"
    sf.write(out, audio, SAMPLE_RATE, subtype="PCM_16")
    raw.unlink(missing_ok=True)
    return {
        "tts": {
            "file": f"tts/{out.name}",
            "ver": ver,
            "secs": round(audio.size / SAMPLE_RATE, 2),
            "text": text,
            "voice": voice,
            "rate": rate,
            "slot": round(slot_secs, 2),  # what the speed was fitted to; a cut can make the slot shorter later
        },
        "fit": fit,
    }


def pauses(x: np.ndarray, rel_db: float = 22.0, min_len: float = 0.06) -> list[tuple[float, float]]:
    """Breaths inside a spoken line: (from, to) in seconds. "Quiet" is measured against the clip's own speech
    level, because a sped-up line has short pauses and not every engine leaves digital silence."""
    win = int(SAMPLE_RATE * 0.01)
    n = x.size // win
    if n < 3:
        return []
    rms = 20 * np.log10(np.sqrt(np.mean(x[: n * win].reshape(n, win) ** 2, axis=1)) + 1e-6)
    ref = float(np.median(rms[rms > rms.max() - 30]))
    quiet = rms < ref - rel_db
    out, k = [], 0
    while k < n:
        if not quiet[k]:
            k += 1
            continue
        j = k
        while j < n and quiet[j]:
            j += 1
        if k > 0 and j < n and (j - k) * 0.01 >= min_len:   # not the clip's own head or tail
            out.append((round(k * 0.01, 2), round(j * 0.01, 2)))
        k = j
    return out


_pause_cache: dict[tuple[str, float], list] = {}


def with_pauses(proj_dir: Path, segs: list[dict]) -> list[dict]:
    """Copies of the lines with `_pauses` (the breaths in each line's voice clip), for the subtitle timing.
    Read from the clip files, so lines voiced by an older version get them too. Nothing is saved."""
    out = []
    for s in segs:
        f = proj_dir / s["tts"]["file"] if s.get("tts") else None
        if f is None or not f.exists():
            out.append(s)
            continue
        key = (str(f), f.stat().st_mtime)
        if key not in _pause_cache:   # the live preview asks again on every change: read each clip once
            if len(_pause_cache) > 5000:
                _pause_cache.clear()
            clip, _ = sf.read(f, dtype="float32")
            _pause_cache[key] = pauses(clip if clip.ndim == 1 else clip.mean(axis=1))
        out.append(s | {"_pauses": _pause_cache[key]})
    return out


def needs_tts(seg: dict, voice: str, rate: float) -> bool:
    t = seg.get("tts")
    if not seg["vi"].strip():
        return False
    return not t or t["text"] != seg["vi"].strip() or t["voice"] != voice or abs(t["rate"] - rate) > 1e-3


def mix(proj_dir: Path, segs: list[dict], duration: float, out: Path) -> None:
    n = int(duration * SAMPLE_RATE) + SAMPLE_RATE
    track = np.zeros(n, dtype=np.float32)
    fade = int(0.08 * SAMPLE_RATE)
    for i, s in enumerate(segs):
        if not s.get("tts"):
            continue
        clip, _ = sf.read(proj_dir / s["tts"]["file"], dtype="float32")
        limit = int((slot(segs, i, duration) + OVERLAP_TOL) * SAMPLE_RATE)
        if clip.size > limit:  # overflow policy: cut at next line, short fade
            clip = clip[:limit].copy()
            f = min(fade, clip.size)
            clip[-f:] *= np.linspace(1, 0, f, dtype=np.float32)
        a = int(s["start"] * SAMPLE_RATE)
        b = min(n, a + clip.size)
        track[a:b] += clip[: b - a]
    peak = float(np.max(np.abs(track))) if track.size else 0
    if peak > 0.98:
        track *= 0.98 / peak
    sf.write(out, track[: int(duration * SAMPLE_RATE)], SAMPLE_RATE, subtype="PCM_16")
