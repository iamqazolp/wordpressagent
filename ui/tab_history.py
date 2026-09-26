from __future__ import annotations

import logging
import gradio as gr
import pandas as pd

logger = logging.getLogger(__name__)


def fetch_history_data(site_filter: str = "Tất cả") -> pd.DataFrame:
    """Lấy dữ liệu lịch sử đăng bài từ CSDL."""
    from db.database import SessionLocal
    from db import crud
    
    db = SessionLocal()
    try:
        if site_filter and site_filter != "Tất cả":
            site = crud.get_site_by_name(db, site_filter)
            if site:
                histories = crud.get_post_history(db, site_id=site.id, limit=100)
            else:
                histories = []
        else:
            histories = crud.get_post_history(db, limit=100)
            
        data = []
        for h in histories:
            site_name = h.site.name if h.site else "Unknown"
            status = "✅ Đã đăng" if h.status == 'published' else ("❌ Lỗi" if h.status == 'failed' else h.status)
            date_str = h.created_at.strftime("%Y-%m-%d %H:%M") if h.created_at else ""
            
            data.append({
                "ID": h.id,
                "Sản phẩm": h.product_name,
                "Tiêu đề": h.title,
                "Website": site_name,
                "Loại": h.post_type,
                "Trạng thái": status,
                "Ngày tạo": date_str,
                "Link WP": h.wp_post_url or ""
            })
            
        if not data:
            return pd.DataFrame(columns=["ID", "Sản phẩm", "Tiêu đề", "Website", "Loại", "Trạng thái", "Ngày tạo", "Link WP"])
            
        return pd.DataFrame(data)
    except Exception as e:
        logger.error(f"Lỗi khi lấy lịch sử đăng bài: {e}")
        return pd.DataFrame()
    finally:
        db.close()


def build_tab_history(db_session=None) -> dict:
    """Build the post history tab."""
    from db.database import SessionLocal
    from db import crud
    
    db = SessionLocal() if db_session is None else db_session
    try:
        site_names = crud.get_site_names(db)
        filter_choices = ["Tất cả"] + site_names
    finally:
        if db_session is None:
            db.close()

    with gr.Row():
        site_filter = gr.Dropdown(
            label="Lọc theo website",
            choices=filter_choices,
            value="Tất cả",
        )
        refresh_btn = gr.Button("🔄 Làm mới danh sách")
        
    history_table = gr.Dataframe(
        value=fetch_history_data("Tất cả"),
        headers=["ID", "Sản phẩm", "Tiêu đề", "Website", "Loại", "Trạng thái", "Ngày tạo", "Link WP"],
        interactive=False,
        wrap=True,
    )
    
    return {
        'site_filter': site_filter,
        'refresh_btn': refresh_btn,
        'history_table': history_table,
    }
