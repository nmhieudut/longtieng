"""Quick checks of the exported video: loudness, black frames, frozen picture, silent tail, audio/video length."""

import json
import re
import time
from pathlib import Path

from . import cancel
from .config import FFMPEG, FFPROBE

TARGET_LUFS = -14.0


def _item(level: str, title: str, detail: str = "") -> dict:
    return {"level": level, "title": title, "detail": detail}


def check(path: Path) -> dict:
    """{"at": time, "items": [{"level": "ok"|"warn", "title", "detail"}]}. Never raises."""
    items: list[dict] = []
    try:
        probe = json.loads(cancel.run([FFPROBE, "-v", "error", "-print_format", "json", "-show_format", "-show_streams",
                                       str(path)], timeout=60).stdout)
        dur = float(probe["format"].get("duration") or 0)
        v = next((s for s in probe["streams"] if s["codec_type"] == "video"), None)
        a = next((s for s in probe["streams"] if s["codec_type"] == "audio"), None)
        if dur < 3:
            items.append(_item("warn", "Video rất ngắn", f"Chỉ {dur:.1f} giây."))
        elif dur > 600:
            items.append(_item("warn", "Video dài hơn 10 phút", "Reels và TikTok thường giới hạn ngắn hơn."))
        if v and a and v.get("duration") and a.get("duration") and abs(float(v["duration"]) - float(a["duration"])) > 0.5:
            items.append(_item("warn", "Hình và tiếng lệch độ dài", f"Hình {float(v['duration']):.1f}s, tiếng {float(a['duration']):.1f}s."))
        if a:
            r = cancel.run([FFMPEG, "-hide_banner", "-nostats", "-i", str(path), "-vn", "-af",
                            "silencedetect=noise=-50dB:d=4,loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"], timeout=300)
            text = r.stderr or ""
            m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", text, re.S)
            if m:
                j = json.loads(m.group(0))
                lufs, tp = float(j["input_i"]), float(j["input_tp"])
                if lufs < -80:
                    items.append(_item("warn", "Không có tiếng", "Video gần như im lặng."))
                else:
                    if abs(lufs - TARGET_LUFS) > 4:
                        items.append(_item("warn", f"Âm lượng {lufs:.1f} LUFS", f"TikTok, Reels, Shorts phát ở khoảng {TARGET_LUFS:.0f}. "
                                           "Bật “Chuẩn hoá âm lượng” trong mục Xuất, hoặc chỉnh âm thanh gốc và nhạc."))
                    if tp > -1.0:
                        items.append(_item("warn", f"Đỉnh âm {tp:.1f} dB", "Dễ bị rè khi nền tảng nén lại."))
            tail = [(float(s), float(e)) for s, e in re.findall(r"silence_start: ([\d.]+)[\s\S]*?silence_end: ([\d.]+)", text)]
            starts = re.findall(r"silence_start: ([\d.]+)", text)
            if starts and dur and (dur - float(starts[-1])) >= 4 and (len(re.findall(r"silence_end", text)) < len(starts) or (tail and dur - tail[-1][1] < 0.3)):
                items.append(_item("warn", "Đuôi video im lặng", f"Từ giây {float(starts[-1]):.0f} đến hết không có tiếng. Có thể cắt bớt."))
        if v:
            r = cancel.run([FFMPEG, "-hide_banner", "-nostats", "-i", str(path), "-an", "-vf",
                            "blackdetect=d=0.5:pix_th=0.03,freezedetect=n=0.003:d=2", "-f", "null", "-"], timeout=600)
            text = r.stderr or ""
            blacks = re.findall(r"black_start:([\d.]+)\s+black_end:([\d.]+)", text)
            blacks = [(float(s), float(e)) for s, e in blacks if float(s) > 0.05 and float(e) < dur - 0.05 or (float(s) > 0.05 and float(e) - float(s) > 1.5)]
            if blacks:
                items.append(_item("warn", f"{len(blacks)} chỗ màn hình đen", "Tại giây " + ", ".join(f"{s:.0f}" for s, _ in blacks[:5]) +
                                   ". Nếu không cố ý (khoảng trống), kiểm tra lại timeline."))
            frozen = re.findall(r"freeze_start: ([\d.]+)", text)
            if frozen:
                items.append(_item("warn", f"{len(frozen)} chỗ hình đứng yên từ 2 giây", "Tại giây " + ", ".join(f"{float(s):.0f}" for s in frozen[:5]) + "."))
    except Exception as e:  # a failed check must never get in the way of the export
        return {"at": time.time(), "items": [_item("warn", "Chưa kiểm tra được", str(e)[:160])]}
    if not items:
        items.append(_item("ok", "Không thấy vấn đề", "Âm lượng, hình đen, hình đứng và đuôi video đều ổn."))
    return {"at": time.time(), "items": items}
