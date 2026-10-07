"""
ui/tab_remote.py — tab "Trên WordPress": xem (CHỈ ĐỌC) sản phẩm/bài đang có trên website.

Chỉ dựng giao diện; việc gọi WordPress nằm ở services/sync.py. Tab này không ghi/xóa gì trên website.
"""
from __future__ import annotations

import logging

import gradio as gr
import pandas as pd

from services import sites as site_service
from services import sync as sync_service
from services.errors import ServiceError

logger = logging.getLogger(__name__)

_COLS = ["WP ID", "Tiêu đề", "Trạng thái WP", "Cập nhật", "Link", "Bài trong kho"]
_TYPE_CHOICES = ["Sản phẩm WooCommerce", "Bài viết Blog"]
_STATUS_CHOICES = ["any", "publish", "draft", "pending", "private", "trash"]
PER_PAGE = 20


def load_remote(site: str, post_type: str, status: str, search: str, page) -> tuple[pd.DataFrame, str]:
    """Tải 1 trang danh sách từ website. Lỗi hiện thành thông báo, không raise."""
    if not site:
        return pd.DataFrame(columns=_COLS), "❌ Vui lòng chọn website."
    try:
        page_no = max(1, int(page or 1))
    except (TypeError, ValueError):
        page_no = 1
    try:
        res = sync_service.list_remote(site, post_type, status or "any", search or "", page_no, PER_PAGE)
    except ServiceError as e:
        return pd.DataFrame(columns=_COLS), f"❌ {e.message}"
    except Exception as e:  # noqa: BLE001
        logger.exception("Lỗi tải danh sách WordPress")
        return pd.DataFrame(columns=_COLS), f"❌ Lỗi: {e}"
    df = pd.DataFrame(
        [{
            "WP ID": i.id, "Tiêu đề": i.title, "Trạng thái WP": i.status, "Cập nhật": i.modified, "Link": i.url or "-",
            "Bài trong kho": f"#{i.local_post_id}" if i.local_post_id else "-",
        } for i in res.items],
        columns=_COLS,
    )
    pages = max(1, -(-res.total // PER_PAGE))
    return df, f"📥 {site}: **{res.total}** mục · trang {res.page}/{pages} (chỉ đọc, không thay đổi website)."


def refresh_sites(current: str | None = None):
    """Cập nhật danh sách website khi mở tab; giữ website đang chọn nếu nó vẫn còn."""
    names = site_service.list_site_names()
    value = current if current in names else (names[0] if names else None)
    return gr.update(choices=names, value=value)


def build_tab_remote() -> dict:
    names = site_service.list_site_names()
    with gr.Row():
        site = gr.Dropdown(label="Website", choices=names, value=names[0] if names else None, scale=2)
        post_type = gr.Radio(label="Loại nội dung", choices=_TYPE_CHOICES, value=_TYPE_CHOICES[0], scale=2)
        status = gr.Dropdown(label="Trạng thái", choices=_STATUS_CHOICES, value="any", scale=1)
    with gr.Row():
        search = gr.Textbox(label="Tìm theo tên", placeholder="để trống = tất cả", scale=3)
        page = gr.Number(label="Trang", value=1, precision=0, minimum=1, scale=1)
        load_btn = gr.Button("📥 Tải danh sách", variant="primary", scale=1)
    info = gr.Markdown("")
    table = gr.Dataframe(value=pd.DataFrame(columns=_COLS), interactive=False, wrap=True)
    load_btn.click(fn=load_remote, inputs=[site, post_type, status, search, page], outputs=[table, info])
    return {"site": site, "post_type": post_type, "status": status, "search": search, "page": page, "load_btn": load_btn, "table": table, "info": info}
