"""Text and picture stickers placed on the exported video at chosen moments.

Times are in OUTPUT time (seconds of the edited video), so they stay where they were put when clips are cut or
reordered. Text is drawn through the subtitle renderer (a font with a colour, optional dark box); pictures come
from the same library as the channel logo and are laid over with ffmpeg. Colour emoji are not supported by the
subtitle renderer, so stickers are pictures.
"""

import re
import secrets

from . import logos

MAX_OVERLAYS = 40
MIN_LEN = 0.2
_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


def validate(raw) -> list[dict]:
    """Clean up what the browser sent. ValueError (message for the user) if it cannot be used."""
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > MAX_OVERLAYS:
        raise ValueError(f"Tối đa {MAX_OVERLAYS} chữ và hình dán.")
    out, seen = [], set()
    for o in raw:
        try:
            kind = o["kind"]
            a, b = round(float(o["start"]), 2), round(float(o["end"]), 2)
            x, y = float(o.get("x", 0.5)), float(o.get("y", 0.5))
            size = float(o.get("size", 0.06 if kind == "text" else 0.25))
        except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
            raise ValueError("Có chữ hoặc hình dán không hợp lệ.") from None
        if kind not in ("text", "image"):
            raise ValueError("Loại không hợp lệ.")
        a = max(0.0, a)
        if b - a < MIN_LEN:
            raise ValueError(f"Mỗi chữ/hình dán phải hiện ít nhất {MIN_LEN:g} giây.")
        item = {"id": "", "kind": kind, "start": a, "end": b, "x": min(1.0, max(0.0, x)), "y": min(1.0, max(0.0, y)),
                "size": round(min(0.8, max(0.02, size)), 3)}
        if kind == "text":
            text = str(o.get("text", "")).strip()[:200]
            if not text:
                raise ValueError("Chữ không được để trống.")
            color = str(o.get("color", "#ffffff"))
            item |= {"text": text, "color": color if _COLOR.match(color) else "#ffffff",
                     "box": bool(o.get("box", False)), "bold": bool(o.get("bold", True))}
        else:
            if not logos.get(str(o.get("image") or "")):
                raise ValueError("Hình dán không còn trong thư viện.")
            item["image"] = str(o["image"])
        oid = str(o.get("id") or "")[:12]
        if not oid or oid in seen:
            oid = secrets.token_hex(3)
        seen.add(oid)
        item["id"] = oid
        out.append(item)
    return out


def ass_color(hex_rgb: str) -> str:
    """#RRGGBB -> ASS &HBBGGRR&"""
    r, g, b = hex_rgb[1:3], hex_rgb[3:5], hex_rgb[5:7]
    return f"&H{b}{g}{r}&".upper()


def in_window(o: dict, offset: float, window: float | None) -> tuple[float, float] | None:
    """(start, end) of the overlay on the clock of the file being made (it may start at `offset`), or None."""
    a, b = o["start"] - offset, o["end"] - offset
    if b <= 0 or (window is not None and a >= window):
        return None
    return max(0.0, a), b if window is None else min(b, window)


def image_filters(items: list[tuple[str, dict]], v_in: str, W: int, H: int, offset: float,
                  window: float | None) -> tuple[list[str], str]:
    """items = [(input label like "3:v", overlay)]; returns the filter parts and the output label."""
    parts, v = [], v_in
    for k, (label, o) in enumerate(items):
        span = in_window(o, offset, window)
        if span is None:
            continue
        w = max(16, int(W * o["size"]) // 2 * 2)
        parts.append(f"[{label}]scale={w}:-2,format=rgba[ovi{k}]")
        out = f"[ovo{k}]"
        parts.append(f"{v}[ovi{k}]overlay=x=main_w*{o['x']:.4f}-overlay_w/2:y=main_h*{o['y']:.4f}-overlay_h/2"
                     f":enable='between(t,{span[0]:.3f},{span[1]:.3f})':format=auto{out}")
        v = out
    return parts, v
