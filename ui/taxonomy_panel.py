"""
ui/taxonomy_panel.py
Ô chọn Danh mục (Category) + Tag cho website đang xem trong tab Tạo & Đăng Bài.

Lựa chọn được lưu trong articles_state[site]['category_ids' | 'tags' | 'category_scope'] — cùng chỗ với
tiêu đề/HTML — nên tự đi theo luồng Đăng ngay / Lưu nháp / Hẹn giờ mà không cần thêm state riêng.
Nghiệp vụ nằm ở services/taxonomy.py; file này chỉ đổi dữ liệu thuần sang gr.update.
Mọi handler đều không raise ra UI.
"""
from __future__ import annotations

import gradio as gr

from services import taxonomy as svc
from services.taxonomy import NO_ARTICLE_MSG, TaxControls, parse_tags

# Tên giữ lại cho nơi gọi/test cũ (hàm thật nằm trong services/taxonomy.py)
__all__ = ["NO_ARTICLE_MSG", "parse_tags"]


def dropdown_update(c: TaxControls):
    """TaxControls -> gr.update cho ô danh mục (giữ nguyên nếu choices=None)."""
    if c.choices is None:
        return gr.update()
    upd = gr.update(choices=c.choices, value=c.selected)
    if not c.interactive:
        upd["interactive"] = False
    return upd


def controls_outputs(c: TaxControls):
    """(dropdown_update, tags_text, status_md) — định dạng đầu ra chung của các handler."""
    if c.choices is None:
        return gr.update(), gr.update(), c.status
    return dropdown_update(c), c.tags, c.status


def refresh_taxonomy_controls(articles_state, current_site, post_type):
    """Đồng bộ ô chọn với bài của site đang xem (gọi khi tạo bài / đổi site / đổi loại nội dung)."""
    return controls_outputs(svc.article_controls(articles_state, current_site, post_type))


def on_categories_input(selected, current_site, articles_state, post_type):
    """Người dùng đổi danh mục -> lưu vào bài (kèm scope để không dùng nhầm id khi đổi loại nội dung)."""
    svc.set_article_categories(articles_state, current_site, selected, post_type)
    return articles_state


def on_tags_input(text, current_site, articles_state):
    svc.set_article_tags(articles_state, current_site, text)
    return articles_state


def on_sync_categories(articles_state, current_site, post_type):
    """Nút 🔄: lấy lại danh mục từ WordPress cho site đang xem (cả product và post)."""
    return controls_outputs(svc.sync_article_categories(articles_state, current_site, post_type))


def on_ai_suggest(articles_state, current_site, post_type):
    """Nút 🤖: AI gợi ý cho site đang xem (ghi đè lựa chọn hiện tại)."""
    return (articles_state, *controls_outputs(svc.suggest_for_article(articles_state, current_site, post_type)))


def autofill_taxonomy(articles_state, post_type):
    """Sau khi tạo bài: tự điền gợi ý cho MỌI site chưa có lựa chọn. Không bao giờ raise."""
    return svc.autofill(articles_state, post_type)
