"""
ui/sync_panel.py — giao diện đồng bộ WordPress: kiểm tra bài trùng, liên kết, làm mới trạng thái, thùng rác.

Chỉ dựng widget và định dạng Markdown; nghiệp vụ nằm ở services/sync.py. Mọi handler trả chuỗi Markdown,
không raise ra UI.
"""
from __future__ import annotations

import logging
from collections.abc import Callable

import gradio as gr

from services import sync as sync_service
from services.errors import ServiceError
from ui.common import extract_id_from_choice

logger = logging.getLogger(__name__)

NO_POST_MSG = "❌ Vui lòng chọn một bài viết trong kho trước."
_STATUS_VN = {"publish": "đã đăng", "draft": "nháp", "pending": "chờ duyệt", "private": "riêng tư", "future": "hẹn giờ"}


def format_duplicates(results: list[sync_service.DuplicateResult]) -> str:
    """Markdown báo cáo trùng cho từng website. Chỉ là cảnh báo — không chặn việc đăng."""
    if not results:
        return "ℹ️ Chưa có bài viết nào để kiểm tra."
    blocks: list[str] = []
    for r in results:
        if r.error:
            blocks.append(f"#### {r.site_name}\n⚠️ Không kiểm tra được: {r.error}")
        elif not r.matches:
            blocks.append(f"#### {r.site_name}\n✅ Không thấy bài nào trùng tên trên website.")
        else:
            lines = [f"#### {r.site_name}\n⚠️ Có **{len(r.matches)}** bài/sản phẩm giống tên trên website:"]
            for m in r.matches:
                link = f"[{m.title}]({m.url})" if m.url else m.title
                local = f" · trong kho: bài #{m.local_post_id}" if m.local_post_id else ""
                lines.append(
                    f"- {link} — WP ID `{m.wp_id}` · {_STATUS_VN.get(m.status, m.status)} · giống {int(m.similarity * 100)}%{local}"
                )
            lines.append(
                "\n*Lựa chọn: **Đăng mới** (bỏ qua cảnh báo), **Cập nhật bài cũ** (tab Kho bài viết → liên kết bài WP rồi bấm "
                "“Cập nhật”), hoặc **Bỏ qua** (không đăng).*"
            )
            blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def check_duplicates_for_articles(articles_state, post_type) -> str:
    """Tab Tạo & Đăng Bài: kiểm tra trùng cho bài đang soạn trên từng website đã chọn."""
    if not articles_state:
        return "❌ Chưa có bài viết nào — hãy tạo bài trước."
    try:
        return format_duplicates(sync_service.check_articles(articles_state, post_type))
    except Exception as e:  # noqa: BLE001
        logger.exception("Lỗi kiểm tra bài trùng")
        return f"❌ Lỗi: {e}"


def check_duplicates_for_history(choice: str) -> str:
    post_id = extract_id_from_choice(choice)
    if not post_id:
        return NO_POST_MSG
    try:
        return format_duplicates([sync_service.check_saved_post(post_id)])
    except ServiceError as e:
        return f"❌ {e.message}"
    except Exception as e:  # noqa: BLE001
        logger.exception("Lỗi kiểm tra bài trùng")
        return f"❌ Lỗi: {e}"


def link_history_post(choice: str, wp_id_text: str) -> str:
    post_id = extract_id_from_choice(choice)
    if not post_id:
        return NO_POST_MSG
    try:
        wp_id = int(str(wp_id_text or "").strip().lstrip("#"))
    except ValueError:
        return "❌ ID bài WordPress phải là một số nguyên (xem cột WP ID ở danh sách trùng / tab 🌐 Trên WordPress)."
    try:
        status = sync_service.link_remote(post_id, wp_id)
    except ServiceError as e:
        return f"❌ {e.message}"
    except Exception as e:  # noqa: BLE001
        logger.exception("Lỗi liên kết bài WP")
        return f"❌ Lỗi: {e}"
    return f"✅ Đã liên kết bài #{post_id} với bài WP `{wp_id}` (trạng thái hiện tại: `{status}`). Từ giờ nút “Cập nhật” sẽ ghi đè đúng bài này."


def refresh_statuses_ui(site_filter: str) -> str:
    site = None if (not site_filter or site_filter == "Tất cả") else site_filter
    try:
        rep = sync_service.refresh_statuses(site)
    except ServiceError as e:
        return f"❌ {e.message}"
    except Exception as e:  # noqa: BLE001
        logger.exception("Lỗi làm mới trạng thái")
        return f"❌ Lỗi: {e}"
    if rep.checked == 0 and not rep.errors:
        return "ℹ️ Không có bài nào đã đăng lên WordPress để kiểm tra."
    lines = [f"🔄 Đã kiểm tra **{rep.checked}** bài trên WordPress (chỉ đọc)."]
    if rep.changes:
        lines.append(f"**{len(rep.changes)} bài đổi trạng thái:**")
        lines += [f"- bài #{c.post_id}: `{c.old}` → `{c.new}`" for c in rep.changes]
    else:
        lines.append("Không có thay đổi nào.")
    if rep.errors:
        lines.append("⚠️ Không kiểm tra được:\n" + "\n".join(f"- {e}" for e in rep.errors))
    return "\n".join(lines)


def trash_history_post(choice: str, confirmed: bool):
    """Trả (markdown, ô xác nhận về False) — luôn bỏ tick sau mỗi lần bấm để tránh xóa nhầm lần sau."""
    post_id = extract_id_from_choice(choice)
    if not post_id:
        return NO_POST_MSG, False
    try:
        return f"🗑️ {sync_service.trash_post(post_id, bool(confirmed))}", False
    except ServiceError as e:
        return f"❌ {e.message}", False
    except Exception as e:  # noqa: BLE001
        logger.exception("Lỗi chuyển bài vào thùng rác")
        return f"❌ Lỗi: {e}", False


def build_history_sync(
    post_selector, site_filter, status_filter, history_table, refresh_table: Callable
) -> dict:
    """Dựng khu 'Đồng bộ với WordPress' trong tab Kho bài và nối sự kiện. `refresh_table(site, status)` -> DataFrame."""
    with gr.Accordion("🔄 Đồng bộ với WordPress", open=False):
        gr.Markdown(
            "Các thao tác đọc **không thay đổi gì** trên website. “Chuyển vào thùng rác” chỉ đưa bài vào thùng rác WordPress "
            "(khôi phục được trong wp-admin), **không xóa vĩnh viễn** và không xóa bản ghi trong kho."
        )
        with gr.Row():
            check_btn = gr.Button("🔍 Kiểm tra bài trùng trên website", size="sm")
            refresh_btn = gr.Button("🔄 Làm mới trạng thái các bài đã đăng", size="sm")
        with gr.Row():
            link_id = gr.Textbox(label="ID bài trên WordPress để liên kết", placeholder="VD: 20925", scale=2)
            link_btn = gr.Button("🔗 Liên kết với bài WP có sẵn", size="sm", scale=1)
        with gr.Row():
            trash_confirm = gr.Checkbox(
                label="Tôi xác nhận chuyển bài WP của bài này vào thùng rác", value=False, scale=2
            )
            trash_btn = gr.Button("🗑️ Chuyển bài WP vào thùng rác", variant="stop", size="sm", scale=1)
        result = gr.Markdown("")

    _refresh = dict(fn=refresh_table, inputs=[site_filter, status_filter], outputs=[history_table])
    check_btn.click(fn=check_duplicates_for_history, inputs=[post_selector], outputs=[result])
    refresh_btn.click(fn=refresh_statuses_ui, inputs=[site_filter], outputs=[result]).then(**_refresh)
    link_btn.click(fn=link_history_post, inputs=[post_selector, link_id], outputs=[result]).then(**_refresh)
    trash_btn.click(fn=trash_history_post, inputs=[post_selector, trash_confirm], outputs=[result, trash_confirm]).then(**_refresh)
    return {"result": result, "check_btn": check_btn, "link_btn": link_btn, "trash_btn": trash_btn, "trash_confirm": trash_confirm}
