"""Translate segments to Vietnamese: OpenAI first, Google as fallback."""

import json

from .config import OPENAI_API_KEY, OPENAI_MODEL, VI_CHARS_PER_SEC

BATCH = 40
CONTEXT = 6

SYSTEM = """Bạn là biên dịch viên lồng tiếng video ngắn (Douyin/TikTok) sang tiếng Việt.
Yêu cầu:
- Dịch tự nhiên như người Việt nói, đúng văn nói, giữ giọng điệu gốc.
- Bản dịch sẽ được đọc lồng tiếng nên PHẢI NGẮN GỌN: không vượt quá max_chars ký tự của mỗi câu. Lược bớt từ thừa nếu cần, giữ ý chính.
- Đọc cả các câu xung quanh để hiểu ngữ cảnh, nhưng mỗi id dịch riêng, không gộp, không tách.
- Tên riêng tiếng Trung: dùng Hán Việt nếu phổ biến, nếu không giữ phiên âm.
- Không thêm chú thích, không thêm dấu ngoặc giải thích.
Trả về JSON: {"items":[{"id":<số>,"vi":"<bản dịch>"}]} với đúng mọi id được gửi."""


def budget(seconds: float, rate: float) -> int:
    return max(4, int(seconds * VI_CHARS_PER_SEC * rate))


def available_secs(segs: list[dict], i: int, duration: float) -> float:
    nxt = segs[i + 1]["start"] if i + 1 < len(segs) else duration
    return max(0.3, nxt - segs[i]["start"])


def translate_all(segs: list[dict], duration: float, src_lang: str, rate: float, on_progress=None) -> list[str]:
    """Fills seg['vi'] in place. Returns list of warnings."""
    warnings = []
    todo = list(range(len(segs)))
    if OPENAI_API_KEY:
        try:
            _openai(segs, duration, rate, on_progress)
        except Exception as e:  # auth / quota / network — fall back to Google
            warnings.append(f"OpenAI lỗi ({type(e).__name__}: {str(e)[:160]}). Đã chuyển sang Google Dịch.")
        todo = [i for i, s in enumerate(segs) if not s["vi"].strip()]
        if todo and not warnings:
            warnings.append(f"{len(todo)} câu OpenAI trả thiếu, đã dịch bằng Google.")
    else:
        warnings.append("Chưa có OPENAI_API_KEY, đang dùng Google Dịch (chất lượng thấp hơn).")
    if todo:
        _google(segs, todo, src_lang, on_progress)
    missing = sum(1 for s in segs if not s["vi"].strip())
    if missing:
        warnings.append(f"{missing} câu không dịch được (mạng hoặc Google chặn). Hãy tự điền bản dịch cho các câu trống.")
    return warnings


def _openai(segs, duration, rate, on_progress):
    from openai import OpenAI

    client = OpenAI(api_key=OPENAI_API_KEY, max_retries=2, timeout=90)
    done_ctx: list[str] = []
    for b in range(0, len(segs), BATCH):
        chunk = range(b, min(b + BATCH, len(segs)))
        items = [{
            "id": segs[i]["id"],
            "text": segs[i]["src"],
            "max_chars": budget(available_secs(segs, i, duration), rate),
        } for i in chunk]
        user = {"context_before": done_ctx[-CONTEXT:], "items": items}
        want = {s["id"] for s in items}
        got = {}
        for _attempt in range(2):
            r = client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
                ],
                response_format={"type": "json_object"},
                temperature=0.3,
            )
            try:
                data = json.loads(r.choices[0].message.content)
                for it in data.get("items", []):
                    if it.get("id") in want and str(it.get("vi", "")).strip():
                        got[it["id"]] = str(it["vi"]).strip()
            except (json.JSONDecodeError, TypeError, AttributeError):
                pass
            if want <= got.keys():
                break
        for i in chunk:
            segs[i]["vi"] = got.get(segs[i]["id"], "")
            if segs[i]["vi"]:
                done_ctx.append(segs[i]["vi"])
        if on_progress:
            on_progress(min(1.0, (b + BATCH) / len(segs)))


def _gtx(text: str, src: str) -> str:
    """Google Translate's public `gtx` endpoint (the one deep-translator uses is often 429)."""
    import urllib.parse
    import urllib.request

    q = urllib.parse.urlencode({"client": "gtx", "sl": src, "tl": "vi", "dt": "t", "q": text})
    req = urllib.request.Request("https://translate.googleapis.com/translate_a/single?" + q,
                                 headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.loads(r.read().decode("utf-8"))
    return "".join(part[0] for part in data[0] if part and part[0]).strip()


def _google(segs, idxs, src_lang, on_progress=None):
    import time

    src = "zh-CN" if src_lang.startswith("zh") else "auto"
    for n, i in enumerate(idxs):
        for attempt in range(3):
            try:
                segs[i]["vi"] = _gtx(segs[i]["src"], src)
                break
            except Exception:
                time.sleep(1.5 * (attempt + 1))
        if not segs[i]["vi"]:
            try:  # last resort
                from deep_translator import GoogleTranslator
                segs[i]["vi"] = (GoogleTranslator(source=src, target="vi").translate(segs[i]["src"]) or "").strip()
            except Exception:
                pass
        if on_progress:
            on_progress((n + 1) / len(idxs))
        time.sleep(0.15)
