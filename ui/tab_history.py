from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
import gradio as gr
import pandas as pd

from db.database import SessionLocal
from db import crud
from core import wp_client, pipeline

logger = logging.getLogger(__name__)


def _extract_id_from_choice(choice_str: str) -> int | None:
    """Trích xuất ID từ chuỗi hiển thị '#12 - Tên sản phẩm...'"""
    if not choice_str or not choice_str.startswith("#"):
        return None
    try:
        id_part = choice_str.split(" - ")[0].replace("#", "").strip()
        return int(id_part)
    except Exception:
        return None


def fetch_history_data(site_filter: str = "Tất cả", status_filter: str = "Tất cả") -> pd.DataFrame:
    """Lấy dữ liệu lịch sử và kho bài viết từ CSDL với bộ lọc."""
    db = SessionLocal()
    try:
        site_id = None
        if site_filter and site_filter != "Tất cả":
            site = crud.get_site_by_name(db, site_filter)
            site_id = site.id if site else -1

        histories = crud.get_post_history(db, site_id=site_id, limit=200)

        data = []
        for h in histories:
            site_name = h.site.name if h.site else "Unknown"

            # Xác định nhãn trạng thái thân thiện
            if h.status == "saved":
                status_lbl = "💾 Đã lưu nháp"
            elif h.status == "published":
                status_lbl = "✅ Đã đăng"
            elif h.status == "draft":
                status_lbl = "📝 Nháp WP"
            elif h.status == "failed":
                status_lbl = "❌ Lỗi"
            else:
                status_lbl = h.status

            # Áp dụng bộ lọc trạng thái
            if status_filter and status_filter != "Tất cả":
                if status_filter == "💾 Đã lưu nháp" and h.status != "saved":
                    continue
                elif status_filter == "✅ Đã đăng" and h.status not in ["published", "draft"]:
                    continue
                elif status_filter == "❌ Lỗi" and h.status != "failed":
                    continue

            date_str = h.created_at.strftime("%Y-%m-%d %H:%M") if h.created_at else ""

            data.append({
                "ID": h.id,
                "Sản phẩm": h.product_name,
                "Tiêu đề": h.title,
                "Website": site_name,
                "Loại": "WooCommerce" if h.post_type == "product" else "Blog",
                "Trạng thái": status_lbl,
                "Giá gốc": h.regular_price or "-",
                "Ngày tạo": date_str,
                "Link WP": h.wp_post_url or "",
            })

        if not data:
            return pd.DataFrame(columns=["ID", "Sản phẩm", "Tiêu đề", "Website", "Loại", "Trạng thái", "Giá gốc", "Ngày tạo", "Link WP"])

        return pd.DataFrame(data)
    except Exception as e:
        logger.error(f"Lỗi khi lấy kho bài viết: {e}")
        return pd.DataFrame()
    finally:
        db.close()


def get_history_post_choices(site_filter: str = "Tất cả", status_filter: str = "Tất cả") -> list[str]:
    """Tạo danh sách lựa chọn bài viết cho Dropdown."""
    db = SessionLocal()
    try:
        site_id = None
        if site_filter and site_filter != "Tất cả":
            site = crud.get_site_by_name(db, site_filter)
            site_id = site.id if site else -1

        histories = crud.get_post_history(db, site_id=site_id, limit=200)
        choices = []
        for h in histories:
            if status_filter and status_filter != "Tất cả":
                if status_filter == "💾 Đã lưu nháp" and h.status != "saved":
                    continue
                elif status_filter == "✅ Đã đăng" and h.status not in ["published", "draft"]:
                    continue
                elif status_filter == "❌ Lỗi" and h.status != "failed":
                    continue

            site_name = h.site.name if h.site else "Site"
            status_text = "Đã lưu" if h.status == "saved" else ("Đã đăng" if h.status in ["published", "draft"] else "Lỗi")
            choices.append(f"#{h.id} - {h.product_name[:35]} ({site_name}) [{status_text}]")

        return choices if choices else ["(Chưa có bài viết nào)"]
    finally:
        db.close()


def on_select_history_post(choice_str: str) -> tuple:
    """Tải thông tin chi tiết của bài viết được chọn."""
    post_id = _extract_id_from_choice(choice_str)
    if not post_id:
        return "", "", "", "", "Sản phẩm WooCommerce", "draft", "", "", "*(Chưa chọn bài viết)*"

    db = SessionLocal()
    try:
        h = crud.get_post_history_by_id(db, post_id)
        if not h:
            return "", "", "", "", "Sản phẩm WooCommerce", "draft", "", "", "❌ Không tìm thấy bài viết!"

        site_name = h.site.name if h.site else "Unknown"
        post_type_label = "Sản phẩm WooCommerce" if h.post_type == "product" else "Bài viết Blog"
        
        info_lines = [
            f"### 📄 Bài viết #{h.id}: **{h.product_name}**",
            f"- **Website đích:** `{site_name}` ({h.site.url if h.site else ''})",
            f"- **Trạng thái:** `{'💾 Đã lưu nháp trên Web' if h.status == 'saved' else ('✅ Đã đăng lên Website' if h.status == 'published' else h.status)}`",
            f"- **Ngày lưu:** {h.created_at.strftime('%Y-%m-%d %H:%M') if h.created_at else ''}",
        ]
        if h.wp_post_url:
            info_lines.append(f"- **Link WordPress:** [Xem sản phẩm trên Web]({h.wp_post_url})")
        if h.error_message:
            info_lines.append(f"- **Lỗi trước đó:** `{h.error_message}`")

        info_md = "\n".join(info_lines)

        # Image preview
        image_paths = []
        if h.image_paths_json:
            try:
                image_paths = json.loads(h.image_paths_json)
            except Exception:
                pass
        
        preview_html = pipeline.make_preview_html(h.raw_html, image_paths)

        return (
            h.title or "",
            h.short_description or "",
            h.regular_price or "",
            h.sale_price or "",
            post_type_label,
            "draft",
            preview_html,
            h.raw_html or "",
            info_md,
        )
    finally:
        db.close()


def on_save_history_edits(
    choice_str: str,
    title: str,
    short_desc: str,
    reg_price: str,
    sale_price: str,
    raw_html: str,
) -> tuple:
    """Lưu các thay đổi nội dung của bài viết vào database."""
    post_id = _extract_id_from_choice(choice_str)
    if not post_id:
        return "❌ Vui lòng chọn một bài viết để lưu!", gr.update()

    db = SessionLocal()
    try:
        h = crud.get_post_history_by_id(db, post_id)
        if not h:
            return "❌ Không tìm thấy bài viết để cập nhật!", gr.update()

        h.title = title.strip()
        h.short_description = short_desc.strip()
        h.regular_price = reg_price.strip()
        h.sale_price = sale_price.strip()
        h.raw_html = raw_html.strip()
        db.commit()

        # Update preview
        image_paths = []
        if h.image_paths_json:
            try:
                image_paths = json.loads(h.image_paths_json)
            except Exception:
                pass
        updated_preview = pipeline.make_preview_html(h.raw_html, image_paths)

        gr.Info(f"✅ Đã lưu cập nhật cho bài #{h.id}!")
        return f"✅ **Đã lưu cập nhật thành công cho bài #{h.id} ({h.product_name})!**", updated_preview
    except Exception as e:
        db.rollback()
        logger.exception("Lỗi khi lưu bài viết đã chọn")
        return f"❌ Lỗi khi lưu: {str(e)}", gr.update()
    finally:
        db.close()


def on_publish_history_post(
    choice_str: str,
    title: str,
    short_desc: str,
    reg_price: str,
    sale_price: str,
    raw_html: str,
    post_type: str,
    post_status: str,
) -> tuple:
    """Đăng ngay bài viết đã lưu lên WordPress/WooCommerce."""
    post_id = _extract_id_from_choice(choice_str)
    if not post_id:
        return "❌ Vui lòng chọn một bài viết để đăng!", gr.update(), gr.update()

    db = SessionLocal()
    try:
        h = crud.get_post_history_by_id(db, post_id)
        if not h or not h.site:
            return "❌ Không tìm thấy bài viết hoặc website cấu hình!", gr.update(), gr.update()

        site_config = crud.get_site_config(db, h.site_id)
        if not site_config:
            return "❌ Không tìm thấy thông tin xác thực của website!", gr.update(), gr.update()

        # Upload ảnh nếu có
        image_paths = []
        if h.image_paths_json:
            try:
                image_paths = json.loads(h.image_paths_json)
            except Exception:
                pass

        uploaded_images = []
        image_warning = None
        if image_paths and site_config.get("wp_user") and site_config.get("wp_app_password"):
            try:
                uploaded_images = wp_client.upload_images(image_paths, site_config)
            except Exception as e:
                image_warning = str(e)

        # Đăng bài
        is_product = "product" in post_type.lower() or "sản phẩm" in post_type.lower()
        if is_product:
            res = wp_client.publish_product(
                title=title.strip() or h.product_name,
                html_content=raw_html,
                uploaded_images=uploaded_images,
                site_config=site_config,
                status=post_status,
                regular_price=reg_price.strip(),
                sale_price=sale_price.strip(),
                short_description=short_desc.strip(),
            )
        else:
            res = wp_client.publish_post(
                title=title.strip() or h.product_name,
                html_content=raw_html,
                uploaded_images=uploaded_images,
                site_config=site_config,
                status=post_status,
            )

        # Cập nhật CSDL
        h.title = title.strip()
        h.raw_html = raw_html
        h.short_description = short_desc.strip()
        h.regular_price = reg_price.strip()
        h.sale_price = sale_price.strip()
        h.status = "published" if post_status == "publish" else "draft"
        h.wp_post_id = str(res.get("post_id", ""))
        h.wp_post_url = res.get("post_url")
        h.published_at = datetime.now()
        h.error_message = None
        db.commit()

        status_badge = "🟢 Công khai" if post_status == "publish" else "📝 Nháp"
        result_msg = (
            f"### 🎉 Đăng thành công lên {h.site.name}!\n\n"
            f"- **Trạng thái:** {status_badge}\n"
            f"- **Link xem:** [{res.get('post_url')}]({res.get('post_url')})\n"
            f"- **Link sửa WP:** [Chỉnh sửa sản phẩm]({res.get('edit_url')})\n"
        )
        if image_warning:
            result_msg += f"- ⚠️ *Cảnh báo ảnh:* {image_warning}\n"

        gr.Info(f"🎉 Đã đăng thành công lên {h.site.name}!")
        updated_table = fetch_history_data()
        updated_choices = get_history_post_choices()
        return result_msg, updated_table, gr.update(choices=updated_choices)

    except Exception as e:
        logger.exception("Lỗi khi đăng bài đã lưu")
        return f"❌ Đăng thất bại: {str(e)}", gr.update(), gr.update()
    finally:
        db.close()


def on_delete_history_post(choice_str: str) -> tuple:
    """Xóa bài viết khỏi CSDL."""
    post_id = _extract_id_from_choice(choice_str)
    if not post_id:
        return "❌ Vui lòng chọn bài viết cần xóa!", gr.update(), gr.update()

    db = SessionLocal()
    try:
        success = crud.delete_post_history(db, post_id)
        if success:
            gr.Info(f"🗑️ Đã xóa bài viết #{post_id}!")
            msg = f"✅ Đã xóa thành công bài viết #{post_id} khỏi hệ thống."
        else:
            msg = f"❌ Không thể xóa bài viết #{post_id}."
        
        updated_table = fetch_history_data()
        updated_choices = get_history_post_choices()
        return msg, updated_table, gr.update(choices=updated_choices, value=updated_choices[0] if updated_choices else None)
    finally:
        db.close()


def build_tab_history(db_session=None) -> dict:
    """Xây dựng giao diện cho tab Kho Bài Viết & Lịch Sử Đăng."""
    from db.database import SessionLocal
    from db import crud

    db = SessionLocal() if db_session is None else db_session
    try:
        site_names = crud.get_site_names(db)
        filter_choices = ["Tất cả"] + site_names
        initial_choices = get_history_post_choices()
    finally:
        if db_session is None:
            db.close()

    gr.Markdown("""
    <div style="margin-bottom: 15px;">
        <h3>📚 Kho Bài Viết & Lịch Sử Đăng</h3>
        <p style="color: #666;">Quản lý toàn bộ bài viết đã lưu trên web và lịch sử đăng lên WordPress/WooCommerce. Bạn có thể xem lại, chỉnh sửa hoặc đăng bất kỳ bài nào bất cứ lúc nào.</p>
    </div>
    """)

    with gr.Row():
        site_filter = gr.Dropdown(
            label="🌐 Lọc theo website",
            choices=filter_choices,
            value="Tất cả",
            scale=1,
        )
        status_filter = gr.Dropdown(
            label="📌 Lọc theo trạng thái",
            choices=["Tất cả", "💾 Đã lưu nháp", "✅ Đã đăng", "❌ Lỗi"],
            value="Tất cả",
            scale=1,
        )
        refresh_btn = gr.Button("🔄 Làm mới dữ liệu", scale=1)

    history_table = gr.Dataframe(
        value=fetch_history_data("Tất cả", "Tất cả"),
        headers=["ID", "Sản phẩm", "Tiêu đề", "Website", "Loại", "Trạng thái", "Giá gốc", "Ngày tạo", "Link WP"],
        interactive=False,
        wrap=True,
    )

    gr.Markdown("---")
    gr.Markdown("### 🔍 Chi Tiết & Thao Tác Với Bài Viết")

    with gr.Row():
        post_selector = gr.Dropdown(
            label="👉 Chọn bài viết để xem chi tiết / chỉnh sửa / đăng bài:",
            choices=initial_choices,
            value=initial_choices[0] if initial_choices else None,
            interactive=True,
        )

    post_info_box = gr.Markdown("*(Chọn một bài viết ở trên để xem chi tiết)*")

    with gr.Row():
        with gr.Column(scale=1):
            title_input = gr.Textbox(label="📝 Tiêu đề sản phẩm", lines=1, interactive=True)
            short_desc_input = gr.Code(label="📑 Mô tả ngắn (HTML)", language="html", lines=4, interactive=True)
            
            with gr.Row():
                reg_price_input = gr.Textbox(label="💵 Giá gốc (VNĐ)", lines=1, interactive=True)
                sale_price_input = gr.Textbox(label="🏷️ Giá KM (VNĐ)", lines=1, interactive=True)

            with gr.Row():
                post_type_selector = gr.Radio(
                    label="Loại nội dung",
                    choices=["Sản phẩm WooCommerce", "Bài viết Blog"],
                    value="Sản phẩm WooCommerce",
                )
                post_status_selector = gr.Radio(
                    label="Trạng thái khi đăng",
                    choices=["draft", "publish"],
                    value="draft",
                    info="'draft' = lưu nháp WP, 'publish' = công khai ngay",
                )

            with gr.Row():
                save_edits_btn = gr.Button("💾 Lưu thay đổi nội dung", variant="secondary")
                publish_single_btn = gr.Button("🚀 Đăng bài này lên Website ngay", variant="primary", size="lg")
                delete_btn = gr.Button("🗑️ Xóa bài này", variant="stop")

            action_result_box = gr.Markdown("")

        with gr.Column(scale=1):
            with gr.Row():
                toggle_history_edit_btn = gr.Button("🔄 Chuyển đổi (Xem / Sửa HTML)")
            history_edit_mode = gr.State(False)

            preview_output = gr.HTML(label="Xem trước bài viết", visible=True)
            html_editor = gr.Code(label="Chỉnh sửa mã HTML", language="html", visible=False, interactive=True)

    # XỬ LÝ SỰ KIỆN NỘI BỘ
    def _on_filter_change(site_f, status_f):
        df = fetch_history_data(site_f, status_f)
        choices = get_history_post_choices(site_f, status_f)
        return df, gr.update(choices=choices, value=choices[0] if choices else None)

    site_filter.change(
        fn=_on_filter_change,
        inputs=[site_filter, status_filter],
        outputs=[history_table, post_selector],
    )
    status_filter.change(
        fn=_on_filter_change,
        inputs=[site_filter, status_filter],
        outputs=[history_table, post_selector],
    )
    refresh_btn.click(
        fn=_on_filter_change,
        inputs=[site_filter, status_filter],
        outputs=[history_table, post_selector],
    )

    post_selector.change(
        fn=on_select_history_post,
        inputs=[post_selector],
        outputs=[
            title_input,
            short_desc_input,
            reg_price_input,
            sale_price_input,
            post_type_selector,
            post_status_selector,
            preview_output,
            html_editor,
            post_info_box,
        ],
    )

    def _on_toggle_history_mode(mode_val, html_val):
        new_mode = not bool(mode_val)
        return (
            gr.update(visible=not new_mode),
            gr.update(visible=new_mode, value=html_val),
            new_mode,
        )

    toggle_history_edit_btn.click(
        fn=_on_toggle_history_mode,
        inputs=[history_edit_mode, html_editor],
        outputs=[preview_output, html_editor, history_edit_mode],
    )

    save_edits_btn.click(
        fn=on_save_history_edits,
        inputs=[post_selector, title_input, short_desc_input, reg_price_input, sale_price_input, html_editor],
        outputs=[action_result_box, preview_output],
    ).then(
        fn=_on_filter_change,
        inputs=[site_filter, status_filter],
        outputs=[history_table, post_selector],
    )

    publish_single_btn.click(
        fn=on_publish_history_post,
        inputs=[
            post_selector,
            title_input,
            short_desc_input,
            reg_price_input,
            sale_price_input,
            html_editor,
            post_type_selector,
            post_status_selector,
        ],
        outputs=[action_result_box, history_table, post_selector],
        show_progress=True,
    )

    delete_btn.click(
        fn=on_delete_history_post,
        inputs=[post_selector],
        outputs=[action_result_box, history_table, post_selector],
    )

    return {
        "site_filter": site_filter,
        "status_filter": status_filter,
        "refresh_btn": refresh_btn,
        "history_table": history_table,
        "post_selector": post_selector,
        "title_input": title_input,
        "short_desc_input": short_desc_input,
        "reg_price_input": reg_price_input,
        "sale_price_input": sale_price_input,
        "post_type_selector": post_type_selector,
        "post_status_selector": post_status_selector,
        "save_edits_btn": save_edits_btn,
        "publish_single_btn": publish_single_btn,
        "delete_btn": delete_btn,
        "preview_output": preview_output,
        "html_editor": html_editor,
        "action_result_box": action_result_box,
    }
