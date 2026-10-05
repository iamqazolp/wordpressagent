from __future__ import annotations

import logging
import re
import pandas as pd
import gradio as gr

from services import schedules as sched_svc
from ui import taxonomy_records as tr

logger = logging.getLogger(__name__)

_COLUMNS = [
    "ID", "Sản phẩm", "Website", "Danh mục & Tag", "Thời gian hẹn (GMT+7)", "Trạng thái", "Thời gian chạy (GMT+7)", "Kết quả"
]


def fetch_scheduler_data() -> pd.DataFrame:
    """Truy vấn danh sách lịch đăng từ CSDL và định dạng thành DataFrame."""
    try:
        jobs = sched_svc.list_jobs(limit=100)
        if not jobs:
            return pd.DataFrame(columns=_COLUMNS)
        return pd.DataFrame([{
            "ID": j.id,
            "Sản phẩm": j.product_name,
            "Website": j.sites,
            "Danh mục & Tag": j.taxonomy_summary,
            "Thời gian hẹn (GMT+7)": j.scheduled_time,
            "Trạng thái": j.status,
            "Thời gian chạy (GMT+7)": j.executed_at,
            "Kết quả": j.result_message,
        } for j in jobs])
    except Exception:
        logger.exception("Lỗi khi tải danh sách lịch đăng")
        return pd.DataFrame(columns=["Lỗi"])


def handle_cancel_job(job_id_input: str) -> tuple[pd.DataFrame, str]:
    """Hủy lịch đăng của một job."""
    if not job_id_input or not job_id_input.strip():
        return fetch_scheduler_data(), "❌ Vui lòng nhập ID lịch đăng cần hủy."

    try:
        job_id = int(job_id_input.strip())
    except ValueError:
        return fetch_scheduler_data(), "❌ ID phải là một số nguyên hợp lệ."

    if sched_svc.cancel_job(job_id):
        return fetch_scheduler_data(), f"✅ Đã hủy lịch đăng #{job_id} thành công!"
    return fetch_scheduler_data(), f"❌ Không tìm thấy hoặc không thể hủy lịch đăng #{job_id}."


def handle_delete_job(job_id_input: str) -> tuple[pd.DataFrame, str]:
    """Xóa hoàn toàn một lịch đăng khỏi CSDL."""
    if not job_id_input or not job_id_input.strip():
        return fetch_scheduler_data(), "❌ Vui lòng nhập ID lịch đăng cần xóa."

    try:
        job_id = int(job_id_input.strip())
    except ValueError:
        return fetch_scheduler_data(), "❌ ID phải là một số nguyên hợp lệ."

    if sched_svc.delete_job(job_id):
        return fetch_scheduler_data(), f"✅ Đã xóa vĩnh viễn lịch đăng #{job_id}!"
    return fetch_scheduler_data(), f"❌ Không tìm thấy lịch đăng #{job_id} để xóa."


def _job_choices() -> list[str]:
    try:
        return [f"#{j.id} · {j.product_name} · {j.sites} · {j.status}" for j in sched_svc.list_jobs(limit=100)]
    except Exception:
        logger.exception("Lỗi khi tải danh sách lịch đăng")
        return []


def handle_batch_jobs(picked, action: str, confirm: bool = False) -> tuple:
    """Huỷ hoặc xoá nhiều lịch đăng đã chọn. Trả (bảng, thông báo, ô chọn cập nhật)."""
    ids = [int(m.group(1)) for c in (picked or []) if (m := re.match(r"#(\d+)", c))]
    if not ids:
        return fetch_scheduler_data(), "❌ Chưa chọn lịch nào.", gr.update()
    if action == "Xoá" and not confirm:
        return fetch_scheduler_data(), "❌ Tick ô xác nhận để xoá.", gr.update()
    fn = sched_svc.delete_job if action == "Xoá" else sched_svc.cancel_job
    done = sum(1 for i in ids if fn(i))
    verb = "xoá" if action == "Xoá" else "huỷ"
    return fetch_scheduler_data(), f"✅ Đã {verb} {done}/{len(ids)} lịch.", gr.update(choices=_job_choices(), value=[])


def build_tab_scheduler() -> dict:
    """Dựng giao diện cho tab Quản Lý Lịch Đăng."""
    with gr.Row():
        refresh_btn = gr.Button("Làm mới", variant="secondary")

    jobs_table = gr.Dataframe(
        value=fetch_scheduler_data,
        label="Danh sách các tác vụ hẹn giờ đăng",
        interactive=False,
        wrap=True,
    )

    with gr.Row():
        with gr.Column(scale=1):
            job_id_input = gr.Textbox(label="Nhập ID lịch đăng", placeholder="VD: 1, 2...")
            with gr.Row():
                cancel_btn = gr.Button("Huỷ lịch (giữ bản ghi)", variant="stop")
                delete_btn = gr.Button("Xoá khỏi danh sách", variant="secondary")
        with gr.Column(scale=2):
            action_status = gr.Markdown("")

    with gr.Accordion("Chọn nhiều lịch để huỷ / xoá", open=False) as multi_box:
        job_pick = gr.CheckboxGroup(label="Chọn lịch", choices=_job_choices(), value=[])
        with gr.Row():
            multi_action = gr.Radio(label="Làm gì", choices=["Huỷ lịch", "Xoá"], value="Huỷ lịch", scale=2)
            multi_confirm = gr.Checkbox(label="Xác nhận xoá", value=False, scale=1)
            multi_btn = gr.Button("Thực hiện", variant="primary", scale=1)
        multi_status = gr.Markdown("")
    multi_box.expand(fn=lambda: gr.update(choices=_job_choices(), value=[]), outputs=[job_pick])
    multi_btn.click(
        fn=handle_batch_jobs, inputs=[job_pick, multi_action, multi_confirm],
        outputs=[jobs_table, multi_status, job_pick],
    )

    tax = tr.build_taxonomy_widgets(
        "#### 🏷️ Danh mục & Tag của lịch đăng\n"
        "*Bấm vào một dòng trong bảng (hoặc nhập ID ở trên) rồi chỉnh. Chỉ sửa được khi lịch còn **chờ**; "
        "thay đổi được lưu ngay và áp dụng khi đến giờ đăng.*",
        with_site_picker=True,
        initial_status=tr.NO_JOB_MSG,
    )
    tax_outputs = [tax["categories"], tax["tags"], tax["status"]]

    # Events
    refresh_btn.click(
        fn=fetch_scheduler_data,
        inputs=[],
        outputs=[jobs_table],
    )

    cancel_btn.click(
        fn=handle_cancel_job,
        inputs=[job_id_input],
        outputs=[jobs_table, action_status],
    )

    delete_btn.click(
        fn=handle_delete_job,
        inputs=[job_id_input],
        outputs=[jobs_table, action_status],
    )

    def _on_row_select(evt: gr.SelectData):
        """Bấm vào dòng -> điền ID lịch đăng (cột đầu tiên)."""
        try:
            row = evt.row_value
            return str(row[0]) if row else gr.update()
        except Exception:
            return gr.update()

    jobs_table.select(fn=_on_row_select, inputs=[], outputs=[job_id_input]).then(
        fn=tr.sched_load, inputs=[job_id_input], outputs=[tax["site"], *tax_outputs]
    )
    job_id_input.submit(fn=tr.sched_load, inputs=[job_id_input], outputs=[tax["site"], *tax_outputs])
    job_id_input.blur(fn=tr.sched_load, inputs=[job_id_input], outputs=[tax["site"], *tax_outputs])
    tax["site"].input(fn=tr.sched_site_change, inputs=[job_id_input, tax["site"]], outputs=tax_outputs)
    # Lưu xong mới làm mới bảng (chuỗi .then) để cột "Danh mục & Tag" luôn khớp dữ liệu vừa lưu
    tax["categories"].input(
        fn=tr.sched_save_categories, inputs=[tax["categories"], job_id_input, tax["site"]], outputs=[tax["status"]]
    ).then(fn=fetch_scheduler_data, inputs=[], outputs=[jobs_table])
    tax["tags"].blur(
        fn=tr.sched_save_tags, inputs=[tax["tags"], job_id_input, tax["site"]], outputs=[tax["status"]]
    ).then(fn=fetch_scheduler_data, inputs=[], outputs=[jobs_table])
    tax["tags"].submit(
        fn=tr.sched_save_tags, inputs=[tax["tags"], job_id_input, tax["site"]], outputs=[tax["status"]]
    ).then(fn=fetch_scheduler_data, inputs=[], outputs=[jobs_table])
    tax["btn_ai"].click(fn=tr.sched_ai_suggest, inputs=[job_id_input, tax["site"]], outputs=tax_outputs).then(
        fn=fetch_scheduler_data, inputs=[], outputs=[jobs_table]
    )
    tax["btn_sync"].click(fn=tr.sched_sync, inputs=[job_id_input, tax["site"]], outputs=tax_outputs)

    return {
        "taxonomy": tax,
        "refresh_btn": refresh_btn,
        "jobs_table": jobs_table,
        "job_id_input": job_id_input,
        "cancel_btn": cancel_btn,
        "delete_btn": delete_btn,
        "action_status": action_status,
    }
