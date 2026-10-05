from __future__ import annotations

import logging
from pathlib import Path
import gradio as gr
import pandas as pd

from core.timeutil import now_vn, fmt_vn, TZ_LABEL
from services import posts as post_service
from services import sites as site_service
from services.errors import PublishError, ServiceError
from ui import taxonomy_records as tr
from ui.common import extract_file_paths, extract_id_from_choice, merge_image_selection
from ui.preview import make_preview_html
from ui.sync_panel import build_history_sync

logger = logging.getLogger(__name__)

ALL = "Tất cả"
_STATUS_FILTERS = {
    "💾 Đã lưu nháp": post_service.STATUS_SAVED,
    "✅ Đã đăng": ("published",),
    "📝 Nháp WP": ("draft",),
    "❌ Lỗi": post_service.STATUS_FAILED,
}
_STATUS_LABELS = {
    "saved": "💾 Đã lưu nháp",
    "published": "✅ Đã đăng",
    "draft": "📝 Nháp WP",
    "failed": "❌ Lỗi",
    "trashed": "🗑️ Thùng rác WP",
    "missing": "❓ Không còn trên WP",
}
_CHOICE_STATUS = {
    "saved": "Đã lưu", "published": "Đã đăng", "draft": "Nháp WP", "trashed": "Thùng rác WP", "missing": "Không còn trên WP",
}
_TABLE_COLUMNS = ["ID", "Sản phẩm", "Tiêu đề", "Website", "Loại", "Trạng thái", "Ảnh", "Giá gốc", "Giá KM",
                  "Danh mục / Tag", "Ngày tạo (GMT+7)", "Link WP"]
_NO_DETAIL = ("", "", "", "", "Sản phẩm WooCommerce", "draft", "", "", "*(Chưa chọn bài viết)*", None, None)


def _site_arg(site_filter: str) -> str | None:
    return None if (not site_filter or site_filter == ALL) else site_filter


def _statuses(status_filter: str):
    return _STATUS_FILTERS.get(status_filter) if status_filter and status_filter != ALL else None


def fetch_history_data(site_filter: str = ALL, status_filter: str = ALL) -> pd.DataFrame:
    """Lấy dữ liệu lịch sử và kho bài viết từ CSDL với bộ lọc."""
    try:
        rows = post_service.list_posts(_site_arg(site_filter), _statuses(status_filter))
    except Exception as e:
        logger.error(f"Lỗi khi lấy kho bài viết: {e}")
        return pd.DataFrame()

    data = [{
        "ID": r.id,
        "Sản phẩm": r.product_name,
        "Tiêu đề": r.title,
        "Website": r.site_name,
        "Loại": "WooCommerce" if r.post_type == "product" else "Blog",
        "Trạng thái": _STATUS_LABELS.get(r.status, r.status),
        "Ảnh": f"{r.image_count} ảnh" if r.image_count > 0 else "-",
        "Giá gốc": r.regular_price or "-",
        "Giá KM": r.sale_price or "-",
        "Danh mục / Tag": r.taxonomy_summary,
        "Ngày tạo (GMT+7)": fmt_vn(r.created_at, "%Y-%m-%d %H:%M", ""),
        "Link WP": r.wp_post_url,
    } for r in rows]
    return pd.DataFrame(data) if data else pd.DataFrame(columns=_TABLE_COLUMNS)


def get_history_post_choices(site_filter: str = ALL, status_filter: str = ALL) -> list[str]:
    """Tạo danh sách lựa chọn bài viết cho Dropdown."""
    choices = []
    for r in post_service.list_posts(_site_arg(site_filter), _statuses(status_filter)):
        status_text = _CHOICE_STATUS.get(r.status, "Lỗi")
        choices.append(f"#{r.id} - {r.product_name[:35]} ({r.site_name}) [{status_text}]")
    return choices if choices else ["(Chưa có bài viết nào)"]


def _status_text(d: post_service.PostDetail) -> str:
    if d.status == "saved":
        return "💾 Đã lưu nháp trên Web"
    if d.status == "published":
        return "✅ Đã đăng lên Website"
    return _STATUS_LABELS.get(d.status, d.status)


def _info_md(d: post_service.PostDetail, date_label: str, date_value: str, image_count: int, status_text: str | None = None,
             link_label: str = "Xem sản phẩm trên Web", extra: list[str] | None = None) -> str:
    """Khung thông tin bài viết hiển thị phía trên form (dùng chung cho xem / lưu / đăng)."""
    lines = [
        f"### 📄 Bài viết #{d.id}: **{d.product_name}**",
        f"- **Website đích:** `{d.site_name}` ({d.site_url})",
        f"- **Trạng thái:** `{status_text or _status_text(d)}`",
        f"- **Số lượng ảnh đính kèm:** {image_count} ảnh",
        f"- **{date_label} ({TZ_LABEL}):** {date_value}",
    ]
    lines += extra or []
    if d.wp_post_url:
        lines.append(f"- **Link WordPress:** [{link_label}]({d.wp_post_url})")
    return "\n".join(lines)


_UNSET = object()


def _final_images(gallery_images, new_images_input) -> list[str] | None:
    """
    Bộ ảnh sẽ lưu/đăng. Có album (UI): ảnh còn lại trong album + ảnh mới thêm (xoá hết → danh sách rỗng).
    Không có album (gọi trực tiếp): hành vi cũ — ảnh tải lên thay thế, không có thì giữ nguyên (None).
    """
    if gallery_images is _UNSET:
        return extract_file_paths(new_images_input) or None
    return merge_image_selection(gallery_images, new_images_input)


def on_select_history_post(choice_str: str) -> tuple:
    """Tải thông tin chi tiết và hình ảnh của bài viết được chọn."""
    post_id = extract_id_from_choice(choice_str)
    if not post_id:
        return _NO_DETAIL

    d = post_service.get_post(post_id)
    if not d:
        return "", "", "", "", "Sản phẩm WooCommerce", "draft", "", "", "❌ Không tìm thấy bài viết!", None, None

    existing = d.existing_image_paths
    extra = [f"- **Lỗi trước đó:** `{d.error_message}`"] if d.error_message else []
    # (thứ tự dòng cũ: link WordPress rồi mới tới lỗi trước đó)
    info_md = _info_md(d, "Ngày lưu", fmt_vn(d.created_at, "%Y-%m-%d %H:%M", ""), len(existing))
    if any("_optimized" in Path(p).stem for p in existing):
        info_md += (
            "\n- ⚠️ **Ảnh của bài này là ảnh đã xử lý (tên có `_optimized`), có thể đã dính watermark từ trước** — "
            "bỏ tick watermark cũng không gỡ được. Hãy xoá các ảnh đó khỏi album, thêm lại ảnh gốc rồi mới đăng."
        )
    if extra:
        info_md += "\n" + "\n".join(extra)

    return (
        d.title,
        d.short_description,
        d.regular_price,
        d.sale_price,
        "Sản phẩm WooCommerce" if d.post_type == "product" else "Bài viết Blog",
        "draft",
        make_preview_html(d.raw_html, existing),
        d.raw_html,
        info_md,
        existing if existing else None,
        None,
    )


def on_save_history_edits(
    choice_str: str,
    title: str,
    short_desc: str,
    reg_price: str,
    sale_price: str,
    raw_html: str,
    new_images_input=None,
    site_filter: str = ALL,
    status_filter: str = ALL,
    gallery_images=_UNSET,
) -> tuple:
    """Lưu các thay đổi nội dung và hình ảnh của bài viết vào database, cập nhật bảng và giữ nguyên bài đang chọn."""
    post_id = extract_id_from_choice(choice_str)
    if not post_id:
        return "❌ Vui lòng chọn một bài viết để lưu!", gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update()

    try:
        d = post_service.save_post_edits(
            post_id, title, short_desc, reg_price, sale_price, raw_html, _final_images(gallery_images, new_images_input)
        )
    except ServiceError as e:
        return f"❌ {e.message}", gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update()
    except Exception as e:
        logger.exception("Lỗi khi lưu bài viết đã chọn")
        return f"❌ Lỗi khi lưu: {str(e)}", gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update()

    existing = d.existing_image_paths
    choices = get_history_post_choices(site_filter, status_filter)
    current_choice = next((c for c in choices if c.startswith(f"#{d.id} - ")), choice_str)
    info_md = _info_md(d, "Ngày cập nhật", now_vn().strftime("%Y-%m-%d %H:%M"), len(existing))

    gr.Info(f"✅ Đã lưu cập nhật cho bài #{d.id}!")
    return (
        f"✅ **Đã lưu cập nhật thành công cho bài #{d.id} ({d.product_name})!** (Hình ảnh: {len(existing)} ảnh)",
        make_preview_html(d.raw_html, existing),
        existing if existing else None,
        fetch_history_data(site_filter, status_filter),
        gr.update(choices=choices, value=current_choice),
        info_md,
        None,
    )


def on_publish_history_post(
    choice_str: str,
    title: str,
    short_desc: str,
    reg_price: str,
    sale_price: str,
    raw_html: str,
    post_type: str,
    post_status: str,
    new_images_input=None,
    site_filter: str = ALL,
    status_filter: str = ALL,
    gallery_images=_UNSET,
    optimize_images: bool = True,
    apply_watermark: bool = True,
    remove_bg: bool = False,
) -> tuple:
    """Đăng ngay bài viết đã lưu kèm hình ảnh lên WordPress/WooCommerce và cập nhật trạng thái."""
    return _publish_history(
        False, choice_str, title, short_desc, reg_price, sale_price, raw_html, post_type, post_status,
        new_images_input, site_filter, status_filter, gallery_images,
        optimize_images, apply_watermark, remove_bg,
    )


def on_update_history_post(
    choice_str: str,
    title: str,
    short_desc: str,
    reg_price: str,
    sale_price: str,
    raw_html: str,
    post_type: str,
    post_status: str,
    new_images_input=None,
    site_filter: str = ALL,
    status_filter: str = ALL,
    gallery_images=_UNSET,
    optimize_images: bool = True,
    apply_watermark: bool = True,
    remove_bg: bool = False,
) -> tuple:
    """Cập nhật (ghi đè) bài WordPress đã đăng/đã liên kết của bài này thay vì đăng thêm bản mới."""
    return _publish_history(
        True, choice_str, title, short_desc, reg_price, sale_price, raw_html, post_type, post_status,
        new_images_input, site_filter, status_filter, gallery_images,
        optimize_images, apply_watermark, remove_bg,
    )


def _publish_history(
    update_existing: bool,
    choice_str: str,
    title: str,
    short_desc: str,
    reg_price: str,
    sale_price: str,
    raw_html: str,
    post_type: str,
    post_status: str,
    new_images_input=None,
    site_filter: str = ALL,
    status_filter: str = ALL,
    gallery_images=_UNSET,
    optimize_images: bool = True,
    apply_watermark: bool = True,
    remove_bg: bool = False,
) -> tuple:
    verb = "cập nhật" if update_existing else "đăng"
    post_id = extract_id_from_choice(choice_str)
    if not post_id:
        return f"❌ Vui lòng chọn một bài viết để {verb}!", gr.update(), gr.update(), gr.update(), gr.update(), gr.update()

    try:
        out = post_service.publish_saved_post(
            post_id, title, short_desc, reg_price, sale_price, raw_html, post_type, post_status,
            _final_images(gallery_images, new_images_input),
            update_existing=update_existing,
            optimize_images=optimize_images, apply_watermark=apply_watermark, remove_bg=remove_bg,
        )
    except PublishError as e:
        logger.error(f"Đăng bài đã lưu #{post_id} thất bại: {e.message}")
        return f"❌ {verb.capitalize()} thất bại: {e.message}", gr.update(), gr.update(), gr.update(), gr.update(), gr.update()
    except ServiceError as e:
        return f"❌ {e.message}", gr.update(), gr.update(), gr.update(), gr.update(), gr.update()
    except Exception as e:
        logger.exception("Lỗi khi đăng bài đã lưu")
        return f"❌ {verb.capitalize()} thất bại: {str(e)}", gr.update(), gr.update(), gr.update(), gr.update(), gr.update()

    status_badge = "🟢 Công khai" if out.post_status == "publish" else "📝 Nháp"
    heading = (
        f"### 🔄 Đã cập nhật bài trên {out.site_name}!\n\n" if out.updated
        else f"### 🎉 Đăng thành công lên {out.site_name}!\n\n" if out.post_status == "publish"
        else f"### 📝 Đã lưu NHÁP lên {out.site_name} (chưa công khai)\n\n"
    )
    result_msg = (
        heading +
        f"- **Trạng thái:** {status_badge}\n"
        f"- **Hình ảnh tải lên WP:** {out.uploaded_count}/{len(out.image_paths)} ảnh\n"
        f"- **Link xem:** [{out.post_url}]({out.post_url})\n"
        f"- **Link sửa WP:** [Chỉnh sửa sản phẩm]({out.edit_url})\n"
    )
    if out.image_warning:
        result_msg += f"- ⚠️ **Cảnh báo ảnh:** {out.image_warning} Bài đã đăng nhưng THIẾU ẢNH.\n"
    if out.taxonomy_warning:
        result_msg += f"- ⚠️ *Cảnh báo tag:* {out.taxonomy_warning}\n"
    if out.category_warning:
        result_msg += f"- ⚠️ *Cảnh báo danh mục:* {out.category_warning}\n"

    if out.image_warning:
        gr.Warning(f"⚠️ {out.site_name}: {out.image_warning}", duration=15)
    gr.Info(
        f"🔄 Đã cập nhật bài trên {out.site_name}!" if out.updated
        else f"🎉 Đã đăng thành công lên {out.site_name}!" if out.post_status == "publish"
        else f"📝 Đã lưu nháp lên {out.site_name} (chưa công khai)"
    )
    updated_choices = get_history_post_choices(site_filter, status_filter)
    current_choice = next((c for c in updated_choices if c.startswith(f"#{out.post_id} - ")), None)

    d = post_service.get_post(out.post_id)
    info_md = "\n".join([
        f"### 📄 Bài viết #{d.id}: **{d.product_name}**",
        f"- **Website đích:** `{d.site_name}` ({d.site_url})",
        f"- **Trạng thái:** `{'✅ Đã đăng công khai' if out.post_status == 'publish' else '📝 Đã đưa lên WordPress ở dạng nháp (chưa công khai)'}`",
        f"- **Số lượng ảnh đính kèm:** {len(out.image_paths)} ảnh",
        f"- **Ngày đăng ({TZ_LABEL}):** {fmt_vn(d.published_at, '%Y-%m-%d %H:%M', '')}",
        f"- **Link WordPress:** [Xem sản phẩm trên Web]({out.post_url})",
    ])
    return (
        result_msg,
        fetch_history_data(site_filter, status_filter),
        gr.update(choices=updated_choices, value=current_choice),
        out.image_paths if out.image_paths else None,
        info_md,
        None,
    )


def on_delete_history_post(choice_str: str, site_filter: str = ALL, status_filter: str = ALL) -> tuple:
    """Xóa bài viết khỏi CSDL và làm mới danh sách."""
    post_id = extract_id_from_choice(choice_str)
    if not post_id:
        return "❌ Vui lòng chọn bài viết cần xóa!", gr.update(), gr.update(), None, "*(Chưa chọn bài viết)*"

    try:
        post_service.delete_post(post_id)
        gr.Info(f"🗑️ Đã xóa bài viết #{post_id}!")
        msg = f"✅ Đã xóa thành công bài viết #{post_id} khỏi hệ thống."
    except ServiceError as e:
        msg = f"❌ {e.message}"

    updated_choices = get_history_post_choices(site_filter, status_filter)
    return (
        msg,
        fetch_history_data(site_filter, status_filter),
        gr.update(choices=updated_choices, value=updated_choices[0] if updated_choices else None),
        None,
        "*(Đã xóa bài viết - vui lòng chọn bài khác)*",
    )


def build_tab_history(db_session=None) -> dict:
    """Xây dựng giao diện cho tab Kho Bài Viết & Lịch Sử Đăng."""
    filter_choices = ["Tất cả"] + site_service.list_site_names()
    initial_choices = get_history_post_choices()

    first_choice = initial_choices[0] if (initial_choices and not initial_choices[0].startswith("(")) else None
    (
        init_title,
        init_short_desc,
        init_reg_price,
        init_sale_price,
        init_post_type,
        init_post_status,
        init_preview_html,
        init_raw_html,
        init_info_md,
        init_images,
        _,
    ) = (
        on_select_history_post(first_choice)
        if first_choice
        else ("", "", "", "", "Sản phẩm WooCommerce", "draft", "", "", "*(Chưa có bài viết nào trong kho)*", None, None)
    )

    with gr.Row():
        site_filter = gr.Dropdown(
            label="Website",
            choices=filter_choices,
            value="Tất cả",
            scale=1,
        )
        status_filter = gr.Dropdown(
            label="Trạng thái",
            choices=["Tất cả", "💾 Đã lưu nháp", "📝 Nháp WP", "✅ Đã đăng", "❌ Lỗi"],
            value="Tất cả",
            scale=1,
        )
        refresh_btn = gr.Button("Làm mới", scale=1)

    history_table = gr.Dataframe(
        value=fetch_history_data("Tất cả", "Tất cả"),
        headers=["ID", "Sản phẩm", "Tiêu đề", "Website", "Loại", "Trạng thái", "Ảnh", "Giá gốc", "Giá KM", "Danh mục / Tag", "Ngày tạo (GMT+7)", "Link WP"],
        interactive=False,
        wrap=True,
    )


    with gr.Row():
        post_selector = gr.Dropdown(
            label="Bài viết (hoặc bấm một dòng trong bảng)",
            choices=initial_choices,
            value=first_choice if first_choice else (initial_choices[0] if initial_choices else None),
            interactive=True,
        )

    post_info_box = gr.Markdown(init_info_md)

    with gr.Row():
        with gr.Column(scale=1):
            title_input = gr.Textbox(label="Tiêu đề", value=init_title, lines=1, interactive=True)
            with gr.Accordion("Mô tả ngắn (HTML)", open=False):
                short_desc_input = gr.Code(label="HTML", value=init_short_desc, language="html", lines=4, interactive=True)
            
            with gr.Row():
                reg_price_input = gr.Textbox(label="Giá gốc", value=init_reg_price, lines=1, interactive=True)
                sale_price_input = gr.Textbox(label="Giá khuyến mại", value=init_sale_price, lines=1, interactive=True)

            # Phần hình ảnh của bài viết
            images_gallery = gr.Gallery(
                label="Ảnh (bấm ✕ để xoá, ảnh đầu là ảnh đại diện)",
                value=init_images,
                columns=4,
                rows=1,
                height=180,
                object_fit="contain",
                interactive=True,
            )
            images_upload = gr.File(
                label="Thêm ảnh",
                file_count="multiple",
                file_types=["image"],
                interactive=True,
            )
            with gr.Accordion("Xử lý ảnh khi đăng", open=False):
                with gr.Row():
                    opt_img_chk = gr.Checkbox(label="Nén WebP", value=True)
                    watermark_chk = gr.Checkbox(label="Watermark", value=True)
                    remove_bg_chk = gr.Checkbox(label="Tách nền", value=False)

            with gr.Row():
                post_type_selector = gr.Radio(
                    choices=["Sản phẩm WooCommerce", "Bài viết Blog"], value=init_post_type, visible=False,
                )
                post_status_selector = gr.Radio(label="Khi đăng", choices=["draft", "publish"], value=init_post_status)

            tax = tr.build_taxonomy_widgets(
                "**Danh mục & tag**"
            )

            with gr.Row():
                save_edits_btn = gr.Button("Lưu", variant="secondary")
                publish_single_btn = gr.Button("Đăng lên website", variant="primary")
                update_single_btn = gr.Button("Cập nhật bài WP", variant="secondary")
                delete_btn = gr.Button("Xoá", variant="stop")

            action_result_box = gr.Markdown("")

            sync_comps = build_history_sync(post_selector, site_filter, status_filter, history_table, fetch_history_data)

        with gr.Column(scale=1):
            with gr.Row():
                toggle_history_edit_btn = gr.Button("Xem / sửa HTML", size="sm")
            history_edit_mode = gr.State(False)

            preview_output = gr.HTML(label="Xem trước bài viết", value=init_preview_html, visible=True)
            html_editor = gr.Code(label="Chỉnh sửa mã HTML", value=init_raw_html, language="html", visible=False, interactive=True)

    # XỬ LÝ SỰ KIỆN NỘI BỘ
    def _on_filter_change(site_f, status_f):
        df = fetch_history_data(site_f, status_f)
        choices = get_history_post_choices(site_f, status_f)
        new_val = choices[0] if choices else None
        return df, gr.update(choices=choices, value=new_val)

    detail_outputs = [
        title_input,
        short_desc_input,
        reg_price_input,
        sale_price_input,
        post_type_selector,
        post_status_selector,
        preview_output,
        html_editor,
        post_info_box,
        images_gallery,
        images_upload,
    ]

    site_filter.change(
        fn=_on_filter_change,
        inputs=[site_filter, status_filter],
        outputs=[history_table, post_selector],
    ).then(
        fn=on_select_history_post,
        inputs=[post_selector],
        outputs=detail_outputs,
    )

    status_filter.change(
        fn=_on_filter_change,
        inputs=[site_filter, status_filter],
        outputs=[history_table, post_selector],
    ).then(
        fn=on_select_history_post,
        inputs=[post_selector],
        outputs=detail_outputs,
    )

    refresh_btn.click(
        fn=_on_filter_change,
        inputs=[site_filter, status_filter],
        outputs=[history_table, post_selector],
    ).then(
        fn=on_select_history_post,
        inputs=[post_selector],
        outputs=detail_outputs,
    )

    # Click vào dòng trên bảng -> tự động load bài viết đó vào chi tiết
    def _on_table_row_select(evt: gr.SelectData, site_f, status_f):
        try:
            row_idx = evt.index[0]
            df = fetch_history_data(site_f, status_f)
            if not df.empty and row_idx < len(df):
                selected_id = int(df.iloc[row_idx]["ID"])
                choices = get_history_post_choices(site_f, status_f)
                matched = next((c for c in choices if c.startswith(f"#{selected_id} - ")), None)
                if matched:
                    return gr.update(value=matched)
        except Exception as e:
            logger.warning(f"Lỗi select table row: {e}")
        return gr.update()

    history_table.select(
        fn=_on_table_row_select,
        inputs=[site_filter, status_filter],
        outputs=[post_selector],
    ).then(
        fn=on_select_history_post,
        inputs=[post_selector],
        outputs=detail_outputs,
    )

    post_selector.change(
        fn=on_select_history_post,
        inputs=[post_selector],
        outputs=detail_outputs,
    )

    # Danh mục & Tag (độc lập với 11 output chi tiết ở trên; tự lưu thẳng vào DB)
    tax_outputs = [tax["categories"], tax["tags"], tax["status"]]
    post_selector.change(fn=tr.history_load, inputs=[post_selector, post_type_selector], outputs=tax_outputs)
    post_type_selector.change(fn=tr.history_load, inputs=[post_selector, post_type_selector], outputs=tax_outputs)
    _refresh_table = dict(fn=fetch_history_data, inputs=[site_filter, status_filter], outputs=[history_table])
    tax["categories"].input(
        fn=tr.history_save_categories, inputs=[tax["categories"], post_selector, post_type_selector], outputs=[tax["status"]]
    ).then(**_refresh_table)
    tax["tags"].blur(fn=tr.history_save_tags, inputs=[tax["tags"], post_selector], outputs=[tax["status"]]).then(**_refresh_table)
    tax["tags"].submit(fn=tr.history_save_tags, inputs=[tax["tags"], post_selector], outputs=[tax["status"]]).then(**_refresh_table)
    tax["btn_ai"].click(fn=tr.history_ai_suggest, inputs=[post_selector, post_type_selector], outputs=tax_outputs).then(**_refresh_table)
    tax["btn_sync"].click(fn=tr.history_sync, inputs=[post_selector, post_type_selector], outputs=tax_outputs)

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
        inputs=[post_selector, title_input, short_desc_input, reg_price_input, sale_price_input, html_editor, images_upload, site_filter, status_filter, images_gallery],
        outputs=[action_result_box, preview_output, images_gallery, history_table, post_selector, post_info_box, images_upload],
    )

    def _busy_msg(verb):
        return lambda: (
            f"⏳ **Đang {verb}…** tải ảnh (nén/watermark) rồi gửi lên WordPress, thường 10–60 giây. "
            "Vui lòng KHÔNG đóng trang hoặc bấm lại."
        )

    publish_single_btn.click(fn=_busy_msg("đăng bài"), outputs=[action_result_box], queue=False).then(
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
            images_upload,
            site_filter,
            status_filter,
            images_gallery,
            opt_img_chk,
            watermark_chk,
            remove_bg_chk,
        ],
        outputs=[action_result_box, history_table, post_selector, images_gallery, post_info_box, images_upload],
        show_progress=True,
    )

    update_single_btn.click(fn=_busy_msg("cập nhật bài"), outputs=[action_result_box], queue=False).then(
        fn=on_update_history_post,
        inputs=[
            post_selector,
            title_input,
            short_desc_input,
            reg_price_input,
            sale_price_input,
            html_editor,
            post_type_selector,
            post_status_selector,
            images_upload,
            site_filter,
            status_filter,
            images_gallery,
            opt_img_chk,
            watermark_chk,
            remove_bg_chk,
        ],
        outputs=[action_result_box, history_table, post_selector, images_gallery, post_info_box, images_upload],
        show_progress=True,
    )

    delete_btn.click(
        fn=on_delete_history_post,
        inputs=[post_selector, site_filter, status_filter],
        outputs=[action_result_box, history_table, post_selector, images_gallery, post_info_box],
    ).then(
        fn=on_select_history_post,
        inputs=[post_selector],
        outputs=detail_outputs,
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
        "images_gallery": images_gallery,
        "images_upload": images_upload,
        "post_type_selector": post_type_selector,
        "post_status_selector": post_status_selector,
        "save_edits_btn": save_edits_btn,
        "publish_single_btn": publish_single_btn,
        "update_single_btn": update_single_btn,
        "sync": sync_comps,
        "delete_btn": delete_btn,
        "preview_output": preview_output,
        "html_editor": html_editor,
        "action_result_box": action_result_box,
        "post_info_box": post_info_box,
        "taxonomy": tax,
    }
