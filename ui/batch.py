"""ui/batch.py — thao tác nhiều bản ghi cùng lúc (đăng ngay / hẹn giờ / xoá), dùng chung cho tab Hàng loạt và Kho bài viết."""
from __future__ import annotations

import re
from datetime import timedelta

import gradio as gr

from core.timeutil import TZ_LABEL, TZ_NAME, now_vn
from services import posts as post_service
from ui.tab_create import parse_scheduled_datetime

PUBLISH, SCHEDULE, DELETE = "Đăng ngay", "Hẹn giờ", "Xoá"


def ids_from(picked) -> list[int]:
    """Lấy id từ nhãn dạng '#12 · ...' hoặc '#12 - ...'."""
    return [int(m.group(1)) for c in (picked or []) if (m := re.match(r"#(\d+)", c))]


def process_batch(picked, action, post_status, start, post_gap, site_gap, confirm_delete=False) -> str:
    ids = ids_from(picked)
    if not ids:
        return "❌ Chưa chọn bài nào."
    if action == DELETE:
        if not confirm_delete:
            return "❌ Tick ô xác nhận để xoá."
        items = post_service.delete_posts_batch(ids)
        done = sum(1 for i in items if i.ok)
        head = f"**Đã xoá {done}/{len(items)} bản ghi** (bài trên WordPress không bị ảnh hưởng)."
        lines = [f"- {'✅' if i.ok else '❌'} #{i.post_id} {i.product_name} · {i.site_name} {i.detail}" for i in items]
    elif action == SCHEDULE:
        when = parse_scheduled_datetime(start)
        if not when:
            return "❌ Chưa chọn giờ bắt đầu."
        items = post_service.schedule_saved_batch(ids, post_status, when, int(post_gap or 0), int(site_gap or 0))
        lines = [f"- {'✅' if i.ok else '❌'} #{i.post_id} {i.product_name} · {i.site_name} · "
                 + (i.when.strftime('%d/%m %H:%M') if i.ok and i.when else i.detail) for i in items]
        head = f"**Đã hẹn giờ {sum(1 for i in items if i.ok)}/{len(items)} bài.** Xem ở tab Lịch đăng."
    else:
        gr.Info("Đang đăng, vui lòng chờ…")
        items = post_service.publish_saved_batch(ids, post_status)
        lines = [f"- {'✅' if i.ok else '❌'} #{i.post_id} {i.product_name} · {i.site_name} · {i.detail}" for i in items]
        head = f"**Đã đăng {sum(1 for i in items if i.ok)}/{len(items)} bài.**"
    return head + "\n\n" + "\n".join(lines)


def build_batch_controls(actions: tuple[str, ...] = (PUBLISH, SCHEDULE, DELETE)) -> dict:
    """Dựng khung chọn hành động + hẹn giờ + nút thực hiện. Chưa gắn sự kiện chạy (nơi gọi tự nối để làm mới danh sách)."""
    with gr.Row():
        action = gr.Radio(label="Làm gì", choices=list(actions), value=actions[0], scale=2)
        status = gr.Radio(label="Khi đăng", choices=["draft", "publish"], value="draft", scale=1)
    with gr.Group(visible=False) as schedule_box:
        with gr.Row():
            start = gr.DateTime(
                label=f"Giờ bắt đầu ({TZ_LABEL})", type="datetime", timezone=TZ_NAME,
                value=now_vn() + timedelta(hours=1), include_time=True, scale=2,
            )
            post_gap = gr.Number(label="Cách nhau giữa các sản phẩm (phút)", value=30, precision=0, scale=1)
            site_gap = gr.Number(label="Cách nhau giữa các website (phút)", value=0, precision=0, scale=1)
    confirm = gr.Checkbox(label="Xác nhận xoá các bản ghi đã chọn", value=False, visible=False)
    button = gr.Button("Thực hiện", variant="primary")
    result = gr.Markdown("")

    action.change(
        fn=lambda a: (gr.update(visible=(a == SCHEDULE)), gr.update(visible=(a == DELETE), value=False),
                      gr.update(visible=(a != DELETE))),
        inputs=[action], outputs=[schedule_box, confirm, status],
    )
    return {"action": action, "status": status, "start": start, "post_gap": post_gap, "site_gap": site_gap,
            "confirm": confirm, "button": button, "result": result}


def wire_batch(c: dict, picked, then_outputs=None, then_fn=None, then_inputs=None):
    """Nối nút Thực hiện: hiện dòng chờ → chạy → (tuỳ chọn) làm mới danh sách."""
    ev = c["button"].click(fn=lambda: "⏳ Đang xử lý, vui lòng không đóng trang…", outputs=[c["result"]], queue=False).then(
        fn=process_batch,
        inputs=[picked, c["action"], c["status"], c["start"], c["post_gap"], c["site_gap"], c["confirm"]],
        outputs=[c["result"]],
        show_progress=True,
    )
    if then_fn:
        ev.then(fn=then_fn, inputs=then_inputs or [], outputs=then_outputs or [])
    return ev
