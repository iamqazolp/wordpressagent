"""
services/ — lớp nghiệp vụ, độc lập với giao diện.

Quy tắc (được test trong tests/test_architecture.py):
  * KHÔNG import gradio (hay bất kỳ framework UI/web nào).
  * Tự mở/đóng session bằng db.database.session_scope(); trả về dict/dataclass thuần,
    không trả ORM object (phiên đã đóng).
  * Tiến độ truyền qua callback progress(value: float, text: str) do nơi gọi cung cấp.
  * Không dựng Markdown/HTML trình bày (bảng, hộp báo cáo); việc đó thuộc về ui/ hoặc API. Chỉ cho phép
    thông điệp trạng thái ngắn bằng tiếng Việt và nhãn hiển thị (vd. nhãn trạng thái lịch).

Người gọi hợp lệ: ui/ (Gradio), api/ (sau này), core/scheduler.py (job chạy nền).
"""
