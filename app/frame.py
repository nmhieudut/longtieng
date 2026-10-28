"""Output framing: change the aspect ratio (e.g. landscape -> 9:16 for Reels) and zoom.

geom() says where the source picture lands on the output canvas; the subtitle/mask/logo layout
uses the same numbers so everything stays lined up whatever the framing.
"""

ASPECTS = {"9:16": (9, 16), "16:9": (16, 9), "1:1": (1, 1), "4:5": (4, 5)}


def _even(x: float) -> int:
    return max(2, int(round(x / 2)) * 2)


def canvas(media: dict, fr: dict) -> tuple[int, int]:
    w, h = media["width"], media["height"]
    if fr.get("aspect", "original") not in ASPECTS:
        return w, h
    a, b = ASPECTS[fr["aspect"]]
    src_long = max(w, h)
    long = 1920 if src_long >= 1500 else 1280 if src_long >= 900 else _even(src_long)
    return (long, _even(long * b / a)) if a >= b else (_even(long * a / b), long)


def geom(media: dict, fr: dict) -> dict:
    """W,H: output size. s: scale of the source. ox,oy: top-left of the scaled source on the canvas."""
    w, h = media["width"], media["height"]
    W, H = canvas(media, fr)
    zoom = float(fr.get("zoom", 1.0))
    active = (W, H) != (w, h) or zoom > 1.001
    if not active:
        return {"W": w, "H": h, "s": 1.0, "ox": 0, "oy": 0, "sw": w, "sh": h, "active": False, "blur": False}
    cover = fr.get("fit") == "crop"
    s = (max(W / w, H / h) if cover else min(W / w, H / h)) * zoom
    sw, sh = _even(w * s), _even(h * s)
    ox, oy = (W - sw) // 2, (H - sh) // 2
    return {"W": W, "H": H, "s": s, "ox": ox, "oy": oy, "sw": sw, "sh": sh, "active": True,
            "blur": sw < W or sh < H}  # some canvas left uncovered -> blurred background there


def video_filter(g: dict, v_in: str, v_out: str) -> str:
    W, H, sw, sh, ox, oy = g["W"], g["H"], g["sw"], g["sh"], g["ox"], g["oy"]
    if not g["blur"]:  # the picture covers the canvas: scale, then cut the edges
        return f"{v_in}scale={sw}:{sh},crop={W}:{H}:{-ox}:{-oy},setsar=1{v_out}"
    # blurred, slightly darkened copy behind (blurred at 1/4 size: much faster, looks the same)
    bw, bh = _even(W / 4), _even(H / 4)
    return (f"{v_in}split[fra][frb];"
            f"[fra]scale={bw}:{bh}:force_original_aspect_ratio=increase,crop={bw}:{bh},"
            f"boxblur=10:2,eq=brightness=-0.06,scale={W}:{H},setsar=1[frbg];"
            f"[frb]scale={sw}:{sh},setsar=1[frfg];"
            f"[frbg][frfg]overlay={ox}:{oy}{v_out}")


def map_y(g: dict, y_src: float) -> float:
    """A y position (pixels from the top of the source) on the output canvas."""
    return g["oy"] + y_src * g["s"]
