"""Cut the dead air out of a clip: find the silent stretches and keep what is between them.

Only proposes (a list of parts to keep); the browser puts them on the timeline as ordinary clips, so the user can
still move any edge or undo the whole thing."""

import re
from pathlib import Path

from . import cancel
from .config import FFMPEG
from .media import MediaError

# profile: (noise floor dB, shortest silence that is cut, seconds of the silence left on each side)
PROFILES = {
    "natural": (-32.0, 0.70, 0.18),   # only the long pauses; keeps the rhythm of speech
    "default": (-32.0, 0.45, 0.12),
    "tight": (-30.0, 0.28, 0.06),     # jump-cut style
}
MIN_KEEP = 0.25
MAX_PARTS = 60


def analyze(src: Path, start: float, end: float, profile: str = "default") -> dict:
    """{"keep": [[a, b], ...] in seconds of the file, "removed": seconds cut, "total": seconds looked at}."""
    db, min_sil, pad = PROFILES.get(profile, PROFILES["default"])
    length = max(0.0, end - start)
    if length < 1.0:
        raise MediaError("Đoạn quá ngắn để dò khoảng lặng.")
    r = cancel.run([FFMPEG, "-hide_banner", "-nostats", "-ss", f"{start:.3f}", "-t", f"{length:.3f}", "-i", str(src),
                    "-vn", "-af", f"silencedetect=noise={db}dB:d={min_sil}", "-f", "null", "-"], timeout=300)
    text = r.stderr or ""
    if r.returncode != 0:
        raise MediaError("Không đọc được âm thanh của đoạn này.\n" + "\n".join(text.strip().splitlines()[-3:]))
    starts = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", text)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", text)]
    if len(starts) > len(ends):   # still silent at the end of the clip
        ends.append(length)
    cuts = []
    for s, e in zip(starts, ends):
        s = max(0.0, s)
        a, b = s + pad, e - pad   # keep a little of the silence on both sides so words do not sound clipped
        if b - a >= 0.1:
            cuts.append((a, min(b, length)))
    keep, t = [], 0.0
    for a, b in cuts:
        if a - t >= MIN_KEEP:
            keep.append([t, a])
        t = max(t, b)
    if length - t >= MIN_KEEP:
        keep.append([t, length])
    if not keep:
        return {"keep": [[start, end]], "removed": 0.0, "total": length}
    while len(keep) > MAX_PARTS:   # too many parts: join the pair with the shortest gap between them
        k = min(range(len(keep) - 1), key=lambda i: keep[i + 1][0] - keep[i][1])
        keep[k] = [keep[k][0], keep[k + 1][1]]
        del keep[k + 1]
    kept = sum(b - a for a, b in keep)
    return {"keep": [[round(start + a, 2), round(start + b, 2)] for a, b in keep],
            "removed": round(length - kept, 2), "total": round(length, 2)}
