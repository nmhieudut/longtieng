# Longtieng — Web app lồng tiếng video cá nhân (Trung → Việt)

Tool cá nhân, chạy local trên Mac (M3, 16GB). Không đăng nhập, không thanh toán.

## 1. Luồng chính

1. **Đưa video vào**: upload file (mp4/mov/webm, tối đa 500MB / 15 phút — cấu hình được) hoặc dán link (yt-dlp; Douyin lỗi thì báo rõ, gợi ý upload file).
2. **Nhận dạng** (tự động): tách audio → mlx-whisper `large-v3-turbo` (fallback faster-whisper). Ngôn ngữ mặc định `zh`, có tùy chọn tự nhận diện. Bật VAD, lọc câu lặp/ảo giác ở đoạn nhạc, chuẩn hoá chữ Trung về giản thể.
3. **Dịch** (tự động): OpenAI model mini (tên model trong `.env`), dịch theo lô có ngữ cảnh, yêu cầu câu ngắn gọn vừa thời lượng. Fallback: Google (deep-translator) khi không có key/hết quota.
4. **Chỉnh sửa**: bảng câu gốc + bản dịch, sửa từng câu, click câu → video nhảy tới đúng chỗ, nghe thử/tạo lại giọng từng câu, câu tràn thời lượng tô đỏ.
5. **Lồng tiếng**: edge-tts (`vi-VN-HoaiMyNeural` mặc định, `vi-VN-NamMinhNeural`), tốc độ chung 0.8–1.3x.
6. **Xuất**: preview đoạn ngắn (~30s) trước, rồi render full.

Dự án được lưu xuống đĩa (`data/projects/<id>/`), tải lại trang không mất việc.

## 2. Khớp thời lượng (bắt buộc)

Câu Việt dài hơn câu Trung → xử lý 3 lớp:
1. Prompt dịch yêu cầu ngắn gọn theo số giây của câu.
2. Clip TTS dài hơn khung → tăng tốc riêng clip đó (atempo, tối đa ~1.4x).
3. Vẫn dài → lấn sang khoảng lặng phía sau (không đè câu kế tiếp). Còn tràn → đánh dấu đỏ để người dùng sửa ngắn.

## 3. Cài đặt (sidebar)

- Giọng đọc, tốc độ nói (0.8–1.3x)
- Âm thanh gốc: **giảm volume + trộn** (mặc định, slider) | **tách nhạc nền bằng demucs** | tắt hẳn
- Phụ đề: burn-in | file .srt riêng | không phụ đề; cỡ chữ, vị trí
- **Che phụ đề Trung có sẵn**: làm mờ / phủ dải màu vùng đáy (chiều cao chỉnh được)
- Ngôn ngữ nguồn: Trung (mặc định) | tự nhận diện

## 4. Đầu ra

- MP4 đã lồng tiếng (+ phụ đề nếu chọn)
- `.srt` tiếng Việt
- Transcript gốc + bản dịch (`.json`, `.txt`)

## 5. Tech stack

| Thành phần | Công nghệ |
|---|---|
| Backend | FastAPI (Python 3.12, uv), job chạy nền, trạng thái lưu `project.json` |
| Frontend | Next.js (static export) + Tailwind + shadcn/ui trong `web/`; FastAPI phục vụ `web/out` |
| STT | mlx-whisper (fallback faster-whisper) |
| Dịch | OpenAI (model mini) → fallback deep-translator |
| TTS | edge-tts |
| Tách vocal | demucs (tùy chọn) |
| Video/audio | ffmpeg trực tiếp (`ffmpeg-full` để có libass cho phụ đề cứng), yt-dlp |

## 6. Giới hạn bản đầu

- 1 người nói chính, không multi-speaker
- Không lip-sync, không voice cloning
- Không OCR chữ trên màn hình (chỉ che vùng)

## 7. Roadmap

Multi-speaker · voice cloning · OCR dịch chữ trên hình · batch nhiều video · timeline kéo thả phụ đề · chèn logo · đổi khung hình 9:16/16:9.
