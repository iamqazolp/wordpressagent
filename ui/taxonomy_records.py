"""
ui/taxonomy_records.py
Danh mục (category) & tag cho bài ĐÃ LƯU (tab Kho Bài Viết) và bài ĐÃ HẸN GIỜ (tab Lịch Đăng Bài).

Khác tab Tạo bài (lưu trong articles_state), ở đây dữ liệu nằm trong DB nên mọi thao tác chọn đều
được ghi thẳng vào DB — để lúc đăng/chạy lịch không bao giờ dùng giá trị cũ.

Nghiệp vụ nằm ở services/taxonomy.py (bài đã lưu) và services/schedules.py (lịch hẹn);
file này chỉ dựng widget và đổi dữ liệu thuần sang gr.update. Mọi handler không raise ra UI.
"""
from __future__ import annotations

import re

import gradio as gr

from services import schedules as sched_svc
from services import taxonomy as svc
from services.schedules import LOCKED_MSG, NO_JOB_MSG, summarize_job
from services.taxonomy import NO_POST_MSG, TaxControls, summarize_history
from ui.taxonomy_panel import controls_outputs, dropdown_update

# Tên giữ lại cho nơi gọi/test cũ (hàm thật nằm trong services/)
__all__ = ["LOCKED_MSG", "NO_JOB_MSG", "NO_POST_MSG", "summarize_job", "summarize_history"]


# ── Dựng ô điều khiển ────────────────────────────────────────────────────────

def build_taxonomy_widgets(title_md: str, with_site_picker: bool = False, initial_status: str = "") -> dict:
    """Tạo cụm ô chọn danh mục/tag (gọi trong ngữ cảnh gr.Blocks)."""
    widgets: dict = {}
    with gr.Group():
        gr.Markdown(title_md)
        if with_site_picker:
            widgets["site"] = gr.Dropdown(label="Website cần chỉnh", choices=[], value=None, interactive=True)
        widgets["categories"] = gr.Dropdown(
            label="Danh mục (Category)",
            choices=[],
            value=[],
            multiselect=True,
            interactive=True,
            info="Lưu ngay khi chọn. Danh sách lấy từ website (bấm 🔄 nếu thiếu).",
        )
        widgets["tags"] = gr.Textbox(
            label="Tag (cách nhau bằng dấu phẩy)",
            placeholder="VD: quạt công nghiệp, quạt hút xưởng",
            lines=1,
            info="Lưu khi nhấn Enter hoặc rời khỏi ô. Tag chưa có trên website sẽ được tạo khi đăng.",
        )
        with gr.Row():
            widgets["btn_ai"] = gr.Button("🤖 AI gợi ý danh mục & tag", size="sm")
            widgets["btn_sync"] = gr.Button("🔄 Làm mới danh mục", size="sm")
        widgets["status"] = gr.Markdown(value=initial_status)
    return widgets


# ══ BÀI ĐÃ LƯU (tab Kho Bài Viết) ════════════════════════════════════════════

def _history_id(choice: str | None) -> int | None:
    m = re.match(r"\s*#(\d+)\b", choice or "")
    return int(m.group(1)) if m else None


def history_load(choice: str, post_type_label: str):
    """Nạp danh mục/tag đã lưu của bài đang chọn (theo loại nội dung đang chọn ở form)."""
    return controls_outputs(svc.history_controls(_history_id(choice), post_type_label))


def history_save_categories(selected, choice: str, post_type_label: str) -> str:
    """Ghi danh mục vào bài. Đồng thời đặt post_type của bài = loại đang chọn để phạm vi id luôn khớp."""
    return svc.save_history_categories(_history_id(choice), selected, post_type_label)


def history_save_tags(text: str, choice: str) -> str:
    return svc.save_history_tags(_history_id(choice), text)


def history_ai_suggest(choice: str, post_type_label: str):
    return controls_outputs(svc.suggest_for_history(_history_id(choice), post_type_label))


def history_sync(choice: str, post_type_label: str):
    return controls_outputs(svc.sync_for_history(_history_id(choice), post_type_label))


# ══ LỊCH HẸN GIỜ (tab Lịch Đăng Bài) ═════════════════════════════════════════

def _sched_outputs(c: TaxControls):
    """(dropdown, tags, status) cho lịch: khi lịch đã khóa thì cả hai ô không sửa được."""
    if c.choices is None:
        return gr.update(), gr.update(), c.status
    return dropdown_update(c), gr.update(value=c.tags, interactive=c.interactive), c.status


def sched_load(job_id_raw: str):
    """Nạp lịch được chọn: danh sách site của lịch + danh mục/tag của site đầu tiên."""
    c = sched_svc.job_controls(job_id_raw)
    if c.choices is None:
        return gr.update(), gr.update(), gr.update(), c.status
    if c.sites is None:  # không có lịch/ site để hiển thị
        return gr.update(choices=[], value=None), gr.update(choices=[], value=[]), "", c.status
    drop, tags, status = _sched_outputs(c)
    return gr.update(choices=c.sites, value=c.site), drop, tags, status


def sched_site_change(job_id_raw: str, site: str):
    return _sched_outputs(sched_svc.job_site_controls(job_id_raw, site))


def sched_save_categories(selected, job_id_raw: str, site: str) -> str:
    return sched_svc.save_job_categories(selected, job_id_raw, site)


def sched_save_tags(text: str, job_id_raw: str, site: str) -> str:
    return sched_svc.save_job_tags(text, job_id_raw, site)


def sched_ai_suggest(job_id_raw: str, site: str):
    return _sched_outputs(sched_svc.suggest_for_job(job_id_raw, site))


def sched_sync(job_id_raw: str, site: str):
    return _sched_outputs(sched_svc.sync_for_job(job_id_raw, site))
