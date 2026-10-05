"""ui/app_control.py — nút ⏻ Tắt ứng dụng ở đầu trang (bấm 2 lần để xác nhận, chỉ hoạt động từ chính máy chạy app)."""
from __future__ import annotations

import gradio as gr

from services import system as system_service

_OFF_MSG = "✅ **Ứng dụng đang tắt.** Bạn có thể đóng tab trình duyệt này. Muốn dùng lại, mở ứng dụng từ biểu tượng khởi động."
_REMOTE_MSG = "❌ Chỉ tắt được ứng dụng từ chính máy đang chạy nó (không tắt từ xa/qua link chia sẻ)."


def on_request_shutdown():
    """Bước 1: hiện khung xác nhận."""
    return gr.update(visible=False), gr.update(visible=True)


def on_cancel_shutdown():
    return gr.update(visible=True), gr.update(visible=False), ""


def on_confirm_shutdown(request: gr.Request | None = None):
    """Bước 2: kiểm tra yêu cầu có đến từ máy cục bộ rồi hẹn tắt tiến trình."""
    host = getattr(getattr(request, "client", None), "host", None)
    headers = getattr(request, "headers", None)
    if not system_service.is_local_request(host, headers):
        return gr.update(visible=True), gr.update(visible=False), _REMOTE_MSG
    system_service.schedule_shutdown()
    return gr.update(visible=False), gr.update(visible=False), _OFF_MSG


def build_app_control() -> dict:
    """Dựng hàng nút ở đầu trang và nối sự kiện. Trả các component (để test/mở rộng)."""
    with gr.Row(equal_height=True):
        gr.HTML("<span></span>")
        with gr.Column(scale=0, min_width=260):
            off_btn = gr.Button("⏻ Tắt ứng dụng", variant="stop", size="sm")
            with gr.Row(visible=False) as confirm_row:
                yes_btn = gr.Button("Xác nhận tắt", variant="stop", size="sm")
                no_btn = gr.Button("Hủy", size="sm")
    off_msg = gr.Markdown("")

    off_btn.click(on_request_shutdown, inputs=[], outputs=[off_btn, confirm_row])
    no_btn.click(on_cancel_shutdown, inputs=[], outputs=[off_btn, confirm_row, off_msg])
    yes_btn.click(on_confirm_shutdown, inputs=[], outputs=[off_btn, confirm_row, off_msg])
    return {"off_btn": off_btn, "confirm_row": confirm_row, "yes_btn": yes_btn, "no_btn": no_btn, "off_msg": off_msg}
