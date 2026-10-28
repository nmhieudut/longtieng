"""Translate segments to Vietnamese: OpenAI first, Google as fallback."""

import json
from concurrent.futures import ThreadPoolExecutor, as_completed

from .config import OPENAI_MODEL, VI_CHARS_PER_SEC, lang_info, openai_key

BATCH = 40          # review mode: runs one batch after another so the narration flows
PAR_BATCH = 24      # faithful translation: small batches, several at once
PAR_WORKERS = 4
CONTEXT = 6

SYSTEM = """Bạn là biên dịch viên lồng tiếng video ngắn (Douyin/TikTok/Reels) từ {src} sang tiếng Việt.
Yêu cầu:
- Dịch tự nhiên như người Việt nói, đúng văn nói, giữ giọng điệu gốc.
- Bản dịch sẽ được đọc lồng tiếng nên PHẢI NGẮN GỌN: không vượt quá max_chars ký tự của mỗi câu. Lược bớt từ thừa nếu cần, giữ ý chính.
- Đọc cả các câu xung quanh để hiểu ngữ cảnh, nhưng mỗi id dịch riêng, không gộp, không tách.
- {names}
- Không thêm chú thích, không thêm dấu ngoặc giải thích.
Trả về JSON: {"items":[{"id":<số>,"vi":"<bản dịch>"}]} với đúng mọi id được gửi."""


REVIEW_SYSTEM = """Bạn là người dẫn chuyện của một kênh video ngắn tiếng Việt. Từ lời thoại gốc ({src}) của từng đoạn,
viết LỜI DẪN tiếng Việt để lồng tiếng thay cho lời thoại, theo phong cách: {style}
Yêu cầu:
- Kể lại / bình luận chuyện đang diễn ra thay vì dịch sát từng chữ. Có thể đổi sang ngôi kể thứ ba
  ("cô gái", "anh chàng", "ông chủ"...), thêm cảm xúc, câu dẫn dắt, nhưng KHÔNG bịa chi tiết trái với lời gốc.
- Các đoạn nối liền thành một mạch kể trôi chảy; đọc context_before để nối tiếp cho tự nhiên.
- Mỗi id đúng một câu dẫn, KHÔNG vượt quá max_chars ký tự (lời sẽ được đọc trong đúng thời lượng đoạn đó).
- Đoạn chỉ là tiếng cảm thán / không có ý nghĩa: viết một câu dẫn rất ngắn (2–5 chữ).
- {names}
Trả về JSON: {{"items":[{{"id":<số>,"vi":"<lời dẫn>"}}]}} với đúng mọi id được gửi."""

# Narration styles for "review" mode: label shown in the app, and the instruction given to the AI.
REVIEW_STYLES = {
    "drama": ("Review phim kịch tính",
              "giọng kể review phim cuốn hút, hồi hộp, nhấn vào tình tiết và cảm xúc nhân vật, tạo tò mò cho đoạn sau."),
    "funny": ("Kể chuyện hài hước",
              "giọng kể dí dỏm, bình luận vui, chơi chữ nhẹ nhàng kiểu người Việt, nhưng vẫn kể đúng chuyện."),
    "summary": ("Tóm tắt nhanh",
                "ngắn gọn, rõ ý, giọng bản tin / tóm tắt, đi thẳng vào chuyện gì đang xảy ra."),
    "explain": ("Giải thích, chia sẻ kiến thức",
                "như người hướng dẫn đang giải thích cho người xem: làm gì, vì sao, mẹo gì, dễ hiểu."),
    "product": ("Review sản phẩm",
                "giọng review sản phẩm / affiliate: nêu công dụng, điểm nổi bật, cảm nhận khi dùng, gợi mở mua thử."),
}


def budget(seconds: float, rate: float) -> int:
    return max(4, int(seconds * VI_CHARS_PER_SEC * rate))


def available_secs(segs: list[dict], i: int, duration: float) -> float:
    nxt = segs[i + 1]["start"] if i + 1 < len(segs) else duration
    return max(0.3, nxt - segs[i]["start"])


def translate_all(segs: list[dict], duration: float, src_lang: str, rate: float, on_progress=None,
                  script: dict | None = None) -> list[str]:
    """Fills seg['vi'] in place. Returns list of warnings.
    script = {"mode": "review", "style": ...} asks the AI for narration instead of a faithful translation."""
    warnings = []
    todo = list(range(len(segs)))
    review = bool(script and script.get("mode") == "review")
    if review and not openai_key():
        warnings.append("Chế độ review cần OpenAI API key, nên đang dịch sát nghĩa bằng Google.")
    if openai_key():
        try:
            _openai(segs, duration, rate, src_lang, on_progress, script if review else None)
        except Exception as e:  # auth / quota / network — fall back to Google
            warnings.append(f"OpenAI lỗi ({type(e).__name__}: {str(e)[:160]}). Đã chuyển sang Google Dịch.")
        todo = [i for i, s in enumerate(segs) if not s["vi"].strip()]
        if todo and not warnings:
            warnings.append(f"{len(todo)} câu OpenAI trả thiếu, đã dịch bằng Google.")
    else:
        warnings.append("Chưa nhập OpenAI API key, đang dùng Google Dịch (chất lượng thấp hơn).")
    if todo:
        _google(segs, todo, src_lang, on_progress)
    missing = sum(1 for s in segs if not s["vi"].strip())
    if missing:
        warnings.append(f"{missing} câu không dịch được (mạng hoặc Google chặn). Hãy tự điền bản dịch cho các câu trống.")
    return warnings


def _ask(client, system: str, user: dict, want: set, temperature: float) -> dict:
    """One batch → {id: text}. Tries twice if the model skipped some ids."""
    got: dict = {}
    for _attempt in range(2):
        r = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
            ],
            response_format={"type": "json_object"},
            temperature=temperature,
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
    return got


def _items(segs, duration, rate, rng):
    return [{
        "id": segs[i]["id"],
        "text": segs[i]["src"],
        "max_chars": budget(available_secs(segs, i, duration), rate),
    } for i in rng]


def _openai(segs, duration, rate, src_lang, on_progress, script=None):
    from openai import OpenAI

    client = OpenAI(api_key=openai_key(), max_retries=2, timeout=90)
    info = lang_info(src_lang)
    if script:
        style = REVIEW_STYLES.get(script.get("style"), REVIEW_STYLES["drama"])[1]
        system = REVIEW_SYSTEM.format(src=info["name"], style=style, names=info["names"])
        return _openai_narrate(client, system, segs, duration, rate, on_progress)
    system = SYSTEM.replace("{src}", info["name"]).replace("{names}", info["names"])

    # Batches don't depend on each other (context is the neighbouring *source* lines), so run them together.
    ranges = [range(b, min(b + PAR_BATCH, len(segs))) for b in range(0, len(segs), PAR_BATCH)]

    def job(rng):
        a, z = rng.start, rng.stop
        user = {"context_before": [segs[i]["src"] for i in range(max(0, a - CONTEXT), a)],
                "context_after": [segs[i]["src"] for i in range(z, min(len(segs), z + 2))],
                "items": _items(segs, duration, rate, rng)}
        return rng, _ask(client, system, user, {x["id"] for x in user["items"]}, 0.3)

    pool = ThreadPoolExecutor(max_workers=min(PAR_WORKERS, len(ranges)))
    try:
        futures = [pool.submit(job, r) for r in ranges]
        done = 0
        for f in as_completed(futures):
            rng, got = f.result()
            for i in rng:
                segs[i]["vi"] = got.get(segs[i]["id"], "")
            done += 1
            if on_progress:
                on_progress(done / len(ranges))  # from this thread, so a cancel raised here stops the job
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def _openai_narrate(client, system, segs, duration, rate, on_progress):
    """Review mode: each batch continues from the narration written so far, so it runs in order."""
    done_ctx: list[str] = []
    for b in range(0, len(segs), BATCH):
        chunk = range(b, min(b + BATCH, len(segs)))
        items = _items(segs, duration, rate, chunk)
        user = {"context_before": done_ctx[-CONTEXT:], "items": items}
        got = _ask(client, system, user, {x["id"] for x in items}, 0.75)
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

    src = lang_info(src_lang)["google"]

    def one(i):
        for attempt in range(3):
            try:
                segs[i]["vi"] = _gtx(segs[i]["src"], src)
                return
            except Exception:
                time.sleep(1.5 * (attempt + 1))

    # a few at a time: much faster than one by one, still gentle enough not to get blocked
    pool = ThreadPoolExecutor(max_workers=5)
    try:
        futures = [pool.submit(one, i) for i in idxs]
        for n, f in enumerate(as_completed(futures), 1):
            f.result()
            if on_progress:
                on_progress(n / len(idxs))
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
