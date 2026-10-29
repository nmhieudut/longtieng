"""TTS per line, fit each line into its time slot, and mix the dub track."""

import asyncio
import hashlib
import threading
import time
from pathlib import Path

import edge_tts
import numpy as np
import soundfile as sf

from .config import (
    DATA_DIR, FFMPEG, MAX_ATEMPO, MAX_EDGE_SPEEDUP,
    OPENAI_TTS_MODEL, SAMPLE_RATE, VI_CHARS_PER_SEC, openai_key,
)
from . import cancel
from .media import decode_mono, trim_silence

_edge_sem = threading.Semaphore(4)  # edge-tts is an unofficial endpoint; be gentle


def slot(segs: list[dict], i: int, duration: float) -> float:
    """Seconds a line may use: from its start until the next line starts."""
    nxt = segs[i + 1]["start"] if i + 1 < len(segs) else duration
    return max(0.3, nxt - segs[i]["start"])


def classify(speech_secs: float, slot_secs: float, speed: float = 1.0) -> dict:
    """Single source of truth for a line's fit status (UI badge + renderer).

    speech_secs: length at the user's chosen rate (before per-line speed-up).
    """
    need = speech_secs / slot_secs if slot_secs > 0 else 99
    max_speed = MAX_EDGE_SPEEDUP * MAX_ATEMPO
    if need <= 1.02:
        status = "ok"
    elif need <= max_speed:
        status = "fast"
    else:
        status = "overflow"
    return {"status": status, "need": round(need, 2), "speed": round(speed, 2)}


def estimate(text: str, slot_secs: float, rate: float) -> dict:
    secs = len(text) / (VI_CHARS_PER_SEC * rate)
    return classify(secs, slot_secs) | {"estimated": True}


def _rate_str(r: float) -> str:
    return f"{round((r - 1) * 100):+d}%"


_OPENAI_TTS_INSTRUCTIONS = ("Đọc bằng tiếng Việt chuẩn như người Việt bản xứ, tự nhiên, rõ ràng, "
                            "giọng lồng tiếng video ngắn, không đọc quá chậm.")
_openai_client = None
_openai_client_key = ""


def _synth_openai(text: str, name: str, rate: float, out: Path) -> None:
    global _openai_client, _openai_client_key
    from openai import OpenAI

    key = openai_key()
    if not key:
        raise RuntimeError("Giọng OpenAI cần OpenAI API key. Nhập key trong Cài đặt (biểu tượng bánh răng), "
                           "hoặc chọn giọng miễn phí như Chị Google.")
    if _openai_client is None or key != _openai_client_key:
        _openai_client, _openai_client_key = OpenAI(api_key=key, max_retries=2, timeout=60), key
    r = _openai_client.audio.speech.create(
        model=OPENAI_TTS_MODEL, voice=name, input=text, instructions=_OPENAI_TTS_INSTRUCTIONS,
        response_format="mp3", speed=min(4.0, max(0.25, rate)))
    out.write_bytes(r.content)


# Engines without a speed setting: fetch once at 1.0x (cached, so speed-up retries cost nothing),
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


def _google_raw(text: str, out: Path) -> None:
    from gtts import gTTS

    gTTS(text, lang="vi", timeout=30).save(str(out))


def _synth(text: str, voice: str, rate: float, out: Path) -> None:
    if voice.startswith("vieneu:"):
        # no speed setting: read once at 1.0x (cached), then change the tempo with ffmpeg
        from . import vieneu_tts

        vid = voice.split(":", 1)[1]
        base = _cached("vieneu", voice, text, lambda p: vieneu_tts.synth_wav(text, vid, p), ext=".wav")
        return _encode(base, rate, out)
    if voice.startswith("google:"):
        engine, make = "google", _google_raw
        last = None
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
    if voice.startswith("openai:"):
        try:
            return _synth_openai(text, voice.split(":", 1)[1], rate, out)
        except Exception as e:
            raise RuntimeError(f"OpenAI TTS lỗi: {type(e).__name__}: {str(e)[:200]}")

    async def go():
        # hard cap: a half-open websocket can stall forever despite edge-tts' own receive timeout
        limit = 30 + len(text) / 10
        await asyncio.wait_for(
            edge_tts.Communicate(text, voice, rate=_rate_str(rate), connect_timeout=10, receive_timeout=20).save(str(out)),
            timeout=limit)

    last = None
    for attempt in range(3):
        if attempt:
            time.sleep(1.5 * attempt)
        try:
            with _edge_sem:
                asyncio.run(go())
            if out.exists() and out.stat().st_size > 0:
                return
        except Exception as e:
            last = e
    raise RuntimeError(f"Edge TTS lỗi: {last}")


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
        # 1) re-synthesize faster: sounds more natural than time-stretching
        edge_speed = min(MAX_EDGE_SPEEDUP, fit["need"] * 1.03)
        _synth(text, voice, rate * edge_speed, raw)
        audio = trim_silence(decode_mono(raw))
        speed = edge_speed
        # 2) still long: time-stretch the remainder
        over = (audio.size / SAMPLE_RATE) / slot_secs
        if over > 1.02:
            tempo = min(MAX_ATEMPO, over * 1.02)
            audio = trim_silence(decode_mono(raw, atempo=tempo))
            speed *= tempo
        fit = classify(base_secs, slot_secs, speed)
        # mix() cuts whatever still runs past the slot, so that is an overflow whatever the ratio says
        if audio.size / SAMPLE_RATE > slot_secs * 1.02:
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
        },
        "fit": fit,
    }


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
        limit = int(slot(segs, i, duration) * SAMPLE_RATE)
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
