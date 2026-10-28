"""Facebook Reels kit: AI caption (title, description, hashtags) and a cover image with the title on it."""

import json
import re
import unicodedata
from pathlib import Path

import numpy as np

from . import cancel
from .config import FFMPEG, OPENAI_MODEL, SUB_FONT, fonts_rel, openai_key
from .media import MediaError
from .render import mask_filter

CAPTION_SYSTEM = """Bạn là admin một fanpage Facebook giải trí/review ở Việt Nam, chuyên đăng Reels lồng tiếng video Douyin.
Dựa vào nội dung video (bản dịch tiếng Việt), viết caption để đăng Reels:
- title: 1 dòng, tối đa 70 ký tự, gây tò mò, giọng thân thiện tự nhiên kiểu người Việt, có 1–2 emoji phù hợp. Không giật tít sai sự thật.
- description: 2–3 câu ngắn tóm ý hấp dẫn, kết thúc bằng một câu hỏi mời bình luận.
- hashtags: 6–8 hashtag tiếng Việt không dấu viết liền, chữ thường. Mỗi hashtag phải nói về đúng thứ xuất hiện trong video
  (đồ vật, nghề, món ăn, hành động, cảm xúc người xem), là từ người Việt hay tìm kiếm, ví dụ video tách vàng từ điện thoại cũ:
  #tachvang #dienthoaicu #taiche #nghethucong #hayvala. Không dùng hashtag chung chung hay không liên quan.
  Thêm #reels và #xuhuong ở cuối. Mỗi phần tử bắt đầu bằng #.
Trả về JSON: {"title": "...", "description": "...", "hashtags": ["#...", ...]}"""


def _no_accents(s: str) -> str:
    s = unicodedata.normalize("NFD", s.replace("đ", "d").replace("Đ", "D"))
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def make_caption(proj: dict) -> dict:
    if not openai_key():
        raise MediaError("Cần OpenAI API key để AI viết caption. Nhập key trong Cài đặt (biểu tượng bánh răng).")
    from openai import OpenAI

    lines = [s["vi"].strip() for s in proj["segments"] if s["vi"].strip()]
    text = "\n".join(lines)[:6000]
    user = {"tieu_de_goc": proj.get("title", ""), "noi_dung_video": text}
    client = OpenAI(api_key=openai_key(), max_retries=2, timeout=60)
    r = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[{"role": "system", "content": CAPTION_SYSTEM},
                  {"role": "user", "content": json.dumps(user, ensure_ascii=False)}],
        response_format={"type": "json_object"},
        temperature=0.7,
    )
    try:
        d = json.loads(r.choices[0].message.content)
    except (json.JSONDecodeError, TypeError):
        raise MediaError("AI trả về caption không hợp lệ, bấm Viết lại.")
    tags = d.get("hashtags") or []
    if isinstance(tags, str):
        tags = tags.split()
    tags = ["#" + re.sub(r"[^\w]", "", _no_accents(str(t).lstrip("#")).lower()) for t in tags]
    return {
        "title": str(d.get("title", "")).strip()[:150],
        "description": str(d.get("description", "")).strip()[:1000],
        "hashtags": [t for t in tags if len(t) > 1][:12],
    }


# ---------- cover image

def _grab_gray(src: Path, t: float, w: int = 160) -> np.ndarray | None:
    r = cancel.run([FFMPEG, "-v", "error", "-ss", f"{t:.2f}", "-i", str(src), "-frames:v", "1",
                    "-vf", f"scale={w}:-2,format=gray", "-f", "rawvideo", "-"], timeout=60, text=False)
    if r.returncode != 0 or not r.stdout:
        return None
    a = np.frombuffer(r.stdout, np.uint8).astype(np.float32)
    return a.reshape(-1, w) if a.size % w == 0 else None


def _score(g: np.ndarray) -> float:
    """Sharp, well-lit, not flat frames score high."""
    mean = g.mean()
    if mean < 25 or mean > 235:  # black / white flash
        return 0.0
    lap = g[1:-1, 1:-1] * 4 - g[:-2, 1:-1] - g[2:, 1:-1] - g[1:-1, :-2] - g[1:-1, 2:]
    return float(lap.var()) * (1 - abs(mean - 128) / 256) * (g.std() / 64)


def candidates(proj_dir: Path, proj: dict, n: int = 6) -> list[dict]:
    """Pick n good-looking frames spread over the video; small previews saved in thumbs/."""
    src = proj_dir / proj["source"]["file"]
    dur = proj["media"]["duration"]
    pool = 18
    times = [dur * (0.05 + 0.9 * i / (pool - 1)) for i in range(pool)]
    scored = []
    for t in times:
        g = _grab_gray(src, t)
        if g is not None:
            scored.append((t, _score(g)))
    # best frame from each of n equal windows keeps the picks spread out
    picks = []
    for k in range(n):
        lo, hi = dur * k / n, dur * (k + 1) / n
        window = [x for x in scored if lo <= x[0] < hi]
        if window:
            picks.append(max(window, key=lambda x: x[1])[0])
    out_dir = proj_dir / "thumbs"
    out_dir.mkdir(exist_ok=True)
    for old in out_dir.glob("cand_*.jpg"):
        old.unlink()
    res = []
    for i, t in enumerate(picks):
        f = out_dir / f"cand_{i}.jpg"
        _frame(proj, src, t, f, width=360)
        res.append({"t": round(t, 2), "file": f"thumbs/{f.name}"})
    return res


def _frame(proj: dict, src: Path, t: float, out: Path, width: int | None = None, ass: Path | None = None) -> None:
    chain, v = [], "[0:v]"
    m = proj["settings"]["mask"]
    if m["enabled"]:
        chain.append(mask_filter(m, v, "[vm]"))
        v = "[vm]"
    if ass:
        chain.append(f"{v}subtitles=filename={ass.name}:fontsdir={fonts_rel(ass.parent)}[vt]")
        v = "[vt]"
    if width:
        chain.append(f"{v}scale={width}:-2[vs]")
        v = "[vs]"
    if not chain:
        chain.append("[0:v]null[vs]")
        v = "[vs]"
    cmd = [FFMPEG, "-y", "-v", "error", "-ss", f"{t:.3f}", "-i", str(src), "-filter_complex", ";".join(chain),
           "-map", v, "-frames:v", "1", "-q:v", "2", str(out)]
    r = cancel.run(cmd, timeout=60, cwd=ass.parent if ass else None)
    if r.returncode != 0 or not out.exists():
        raise MediaError("Không tạo được ảnh:\n" + r.stderr[-400:])


_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿️‍]+")


def strip_emoji(s: str) -> str:
    return re.sub(r"\s{2,}", " ", _EMOJI.sub("", s)).strip()


def cover(proj_dir: Path, proj: dict, t: float, title: str, position: str) -> Path:
    """Full-size cover JPG: the frame at t (original subs masked) + big title text."""
    media = proj["media"]
    w, h = media["width"], media["height"]
    src = proj_dir / proj["source"]["file"]
    out_dir = proj_dir / "thumbs"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / "cover.jpg"
    title = strip_emoji(title).replace("{", "(").replace("}", ")").replace("\n", "\\N")
    ass = None
    if title:
        size = int(0.1 * min(w, h))
        align = {"top": 8, "middle": 5, "bottom": 2}.get(position, 8)
        margin_v = int(h * 0.1)
        side = int(w * 0.06)
        ass = out_dir / "cover.ass"
        ass.write_text(f"""[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: T,{SUB_FONT},{size},&H00FFFFFF,&H000000FF,&H00000000,&H96000000,-1,0,0,0,100,100,0,0,1,{max(4, size // 9)},{max(2, size // 18)},{align},{side},{side},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,9:00:00.00,T,,0,0,0,,{{\\c&H3DE6FF&}}{title.upper()}
""", "utf-8")
        # the ASS clock starts at the seek point, so the line is on screen for the grabbed frame
    _frame(proj, src, t, out, ass=ass)
    return out
