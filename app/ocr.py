"""Find the burned-in subtitle band with Apple Vision OCR (macOS, runs locally).

Idea: grab frames while people are talking, read the text on them, and keep the
horizontal band where text shows up in many frames *and changes* between frames.
Static text (watermarks, channel names, titles) repeats the same string, so it is ignored.
"""

import re
import tempfile
from collections import defaultdict
from pathlib import Path

from . import cancel
from .config import FFMPEG

_CJK = re.compile("[\u4e00-\u9fff]")
MAX_FRAMES = 14


def available() -> bool:
    try:
        import Vision  # noqa: F401
        return True
    except ImportError:
        return False


def _read_text(png: Path) -> list[dict]:
    """Text lines on one image. y/h are fractions of the height, measured from the BOTTOM."""
    import Vision
    from Foundation import NSURL

    handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(NSURL.fileURLWithPath_(str(png)), None)
    req = Vision.VNRecognizeTextRequest.alloc().init()
    req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    req.setRecognitionLanguages_(["zh-Hans", "zh-Hant"])
    req.setUsesLanguageCorrection_(False)
    ok, _err = handler.performRequests_error_([req], None)
    if not ok:
        return []
    out = []
    for obs in req.results() or []:
        cands = obs.topCandidates_(1)
        if not cands:
            continue
        text = str(cands[0].string())
        bb = obs.boundingBox()
        out.append({"text": text, "y": bb.origin.y, "h": bb.size.height, "w": bb.size.width})
    return out


def _times(segments: list[dict], duration: float) -> list[float]:
    """Middle of spoken lines, spread across the video."""
    mids = [(s["start"] + s["end"]) / 2 for s in segments if s["end"] - s["start"] > 0.6]
    if not mids:
        mids = [duration * k / 10 for k in range(1, 10)]
    if len(mids) > MAX_FRAMES:
        step = len(mids) / MAX_FRAMES
        mids = [mids[int(i * step)] for i in range(MAX_FRAMES)]
    return mids


def detect(src: Path, segments: list[dict], duration: float) -> dict | None:
    """Return {"bottom": %, "height": %} (from the bottom edge) or None if no subtitle band found."""
    if not available():
        return None
    times = _times(segments, duration)
    hits = []  # (frame_index, line)
    with tempfile.TemporaryDirectory() as tmp:
        for i, t in enumerate(times):
            cancel.check()
            png = Path(tmp) / f"f{i}.png"
            r = cancel.run([FFMPEG, "-v", "error", "-ss", f"{t:.2f}", "-i", str(src), "-frames:v", "1",
                            "-vf", "scale=720:-2", str(png)], timeout=60)
            if r.returncode != 0 or not png.exists():
                continue
            for line in _read_text(png):
                if len(_CJK.findall(line["text"])) >= 2 and line["w"] > 0.08:
                    hits.append((i, line))
    if not hits:
        return None

    # group lines by vertical position (3% bins on the line's centre)
    bins: dict[int, list] = defaultdict(list)
    for i, line in hits:
        bins[int((line["y"] + line["h"] / 2) / 0.03)].append((i, line))

    n = len(times)
    best, best_score = None, 0.0
    for b, items in bins.items():
        # merge neighbours: a two-line subtitle or slight jitter spans adjacent bins
        group = items + bins.get(b - 1, []) + bins.get(b + 1, [])
        frames = {i for i, _ in group}
        texts = {re.sub(r"\W", "", l["text"]) for _, l in group}
        coverage = len(frames) / n
        variety = len(texts) / max(1, len(group))
        if coverage < 0.3 or variety < 0.5:  # rare text, or the same text everywhere (watermark)
            continue
        score = coverage * variety
        if score > best_score:
            best, best_score = group, score
    if not best:
        return None

    lo = min(l["y"] for _, l in best)
    hi = max(l["y"] + l["h"] for _, l in best)
    pad = 0.012
    lo, hi = max(0.0, lo - pad), min(1.0, hi + pad)
    return {"bottom": round(lo * 100, 1), "height": round(max(2.0, (hi - lo) * 100), 1)}
