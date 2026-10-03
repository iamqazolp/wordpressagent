from __future__ import annotations

import json
import logging
import pandas as pd
import gradio as gr
from datetime import datetime

from db.database import SessionLocal
from db import crud
from core.scheduler import cancel_scheduled_job
from core.timeutil import fmt_vn
from ui import taxonomy_records as tr

logger = logging.getLogger(__name__)


def fetch_scheduler_data() -> pd.DataFrame:
    """Truy vấn danh sách lịch đăng từ CSDL và định dạng thành DataFrame."""
    db = SessionLocal()
    try:
        jobs = crud.get_scheduled_posts(db, limit=100)
        if not jobs:
            return pd.DataFrame(columns=[
                "ID", "Sản phẩm", "Website", "Danh mục & Tag", "Thời gian hẹn (GMT+7)", "Trạng thái", "Thời gian chạy (GMT+7)", "Kết quả"
            ])

        rows = []
        tax_cache: dict = {}  # tên danh mục theo (site, loại) — tránh truy vấn lặp cho từng dòng
        for j in jobs:
            # Parse sites
            try:
                sites = json.loads(j.site_names_json)
                sites_str = ", ".join(sites)
            except Exception:
                sites_str = j.site_names_json or "-"

            # Format status
            status_map = {
                "pending": "⏳ Đang chờ",
                "running": "⚡ Đang đăng...",
                "completed": "✅ Hoàn tất",
                "partially_completed": "⚠️ Xong một phần",
                "failed": "❌ Thất bại",
                "cancelled": "🚫 Đã hủy",
            }
            status_display = status_map.get(j.status, j.status)

            sched_time_str = fmt_vn(j.scheduled_time)
            exec_time_str = fmt_vn(j.executed_at)

            rows.append({
                "ID": j.id,
                "Sản phẩm": j.product_name,
                "Website": sites_str,
                "Danh mục & Tag": tr.summarize_job(db, j, tax_cache),
                "Thời gian hẹn (GMT+7)": sched_time_str,
                "Trạng thái": status_display,
                "Thời gian chạy (GMT+7)": exec_time_str,
                "Kết quả": j.result_message or "-",
            })

        return pd.DataFrame(rows)
    except Exception as e:
        logger.exception("Lỗi khi tải danh sách lịch đăng")
        return pd.DataFrame(columns=["Lỗi"])
    finally:
        db.close()


def handle_cancel_job(job_id_input: str) -> tuple[pd.DataFrame, str]:
    """Hủy lịch đăng của một job."""
    if not job_id_input or not job_id_input.strip():
        return fetch_scheduler_data(), "❌ Vui lòng nhập ID lịch đăng cần hủy."

    try:
        job_id = int(job_id_input.strip())
    except ValueError:
        return fetch_scheduler_data(), "❌ ID phải là một số nguyên hợp lệ."

    success = cancel_scheduled_job(job_id)
    if success:
        return fetch_scheduler_data(), f"✅ Đã hủy lịch đăng #{job_id} thành công!"
    else:
        return fetch_scheduler_data(), f"❌ Không tìm thấy hoặc không thể hủy lịch đăng #{job_id}."


def handle_delete_job(job_id_input: str) -> tuple[pd.DataFrame, str]:
    """Xóa hoàn toàn một lịch đăng khỏi CSDL."""
    if not job_id_input or not job_id_input.strip():
        return fetch_scheduler_data(), "❌ Vui lòng nhập ID lịch đăng cần xóa."

    try:
        job_id = int(job_id_input.strip())
    except ValueError:
        return fetch_scheduler_data(), "❌ ID phải là một số nguyên hợp lệ."

    cancel_scheduled_job(job_id)

    db = SessionLocal()
    try:
        deleted = crud.delete_scheduled_post(db, job_id)
        if deleted:
            return fetch_scheduler_data(), f"✅ Đã xóa vĩnh viễn lịch đăng #{job_id}!"
        else:
            return fetch_scheduler_data(), f"❌ Không tìm thấy lịch đăng #{job_id} để xóa."
    finally:
        db.close()


def build_tab_scheduler() -> dict:
    """Dựng giao diện cho tab Quản Lý Lịch Đăng."""
    gr.Markdown("""
    <div style="margin-bottom: 15px;">
        <h3>📅 Quản Lý Lịch Đăng Bài Tự Động (Post Scheduler)</h3>
        <p style="color: #666;">Theo dõi các bài viết được hẹn giờ đăng tự động. Hệ thống sẽ tự động đăng đúng giờ ngay cả khi bạn không tương tác với trình duyệt.</p>
    </div>
    """)

    with gr.Row():
        refresh_btn = gr.Button("🔄 Làm mới danh sách", variant="secondary")

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
                cancel_btn = gr.Button("🚫 Hủy lịch đã hẹn", variant="stop")
                delete_btn = gr.Button("🗑️ Xóa bản ghi", variant="secondary")
        with gr.Column(scale=2):
            action_status = gr.Markdown("")

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
