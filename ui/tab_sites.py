from __future__ import annotations

import logging
import gradio as gr

from core.image_processor import WATERMARK_POSITIONS
from services import sites as site_service
from services.errors import ServiceError

logger = logging.getLogger(__name__)

NEW_SITE_CHOICE = "➕ Thêm website mới"


def get_sites_table_md() -> str:
    """Trả về bảng Markdown hiển thị danh sách các website hiện có từ CSDL kèm trạng thái Watermark."""
    sites = site_service.list_sites_overview()
    if not sites:
        return "*Chưa có website nào được cấu hình.*"

    md = "| Tên Website | URL | WooCommerce Key | WordPress App Password | Watermark Logo |\n"
    md += "| :--- | :--- | :--- | :--- | :--- |\n"
    for site in sites:
        ck_masked = site.client_key_preview + "..." if site.client_key_preview else "Chưa có"
        has_wp = "✅ Đã cấu hình" if site.has_wp_credentials else "Chưa có"
        if site.watermark_path:
            wm_pos_lbl = WATERMARK_POSITIONS.get(site.watermark_position, "Dưới phải")
            wm_status = f"✅ Có logo ({wm_pos_lbl})"
        else:
            wm_status = "Chưa có"
        md += f"| **{site.name}** | {site.url} | `{ck_masked}` | {has_wp} | {wm_status} |\n"
    return md


def on_select_site_for_edit(selected_choice: str):
    """Khi người dùng chọn 1 website trong dropdown để xem hoặc sửa."""
    if not selected_choice or selected_choice == NEW_SITE_CHOICE:
        return "", "", "", "", "", "", "bottom-right", 0.7, None, None, "Điền thông tin để thêm website mới."

    config = site_service.get_site_config(selected_choice)
    if not config:
        return "", "", "", "", "", "", "bottom-right", 0.7, None, None, "Không tìm thấy dữ liệu website."

    return (
        config.get("name", ""),
        config.get("url", ""),
        config.get("client_key", ""),
        config.get("client_secret", ""),
        config.get("wp_user", ""),
        config.get("wp_app_password", ""),
        config.get("watermark_position", "bottom-right") or "bottom-right",
        float(config.get("watermark_opacity", 0.7) or 0.7),
        site_service.get_watermark_preview(selected_choice),
        None,  # Reset input file upload
        f"Đang xem thông tin website: {selected_choice}",
    )


def handle_save_site(
    name: str,
    url: str,
    client_key: str,
    client_secret: str,
    wp_user: str,
    wp_app_password: str,
    watermark_file,
    watermark_pos: str,
    watermark_opacity: float,
    edit_dropdown_value: str,
):
    """Lưu thêm mới hoặc cập nhật website vào CSDL kèm cấu hình Watermark."""
    name = (name or "").strip()
    url = (url or "").strip()

    if not name or not url:
        return (
            "❌ Vui lòng nhập tên website và URL!",
            get_sites_table_md(),
            gr.update(),
            gr.update(),
            gr.update(),
            gr.update(),
        )

    wm_source = None
    if watermark_file:
        wm_source = watermark_file.name if hasattr(watermark_file, "name") else str(watermark_file)
    current = None if (not edit_dropdown_value or edit_dropdown_value == NEW_SITE_CHOICE) else edit_dropdown_value

    try:
        _, created = site_service.save_site(
            name, url, client_key, client_secret, wp_user, wp_app_password,
            wm_source, watermark_pos, watermark_opacity, current,
        )
        ok = True
        msg = f"✅ Đã thêm website mới: {name}" if created else f"✅ Đã cập nhật website: {name}"
    except ServiceError as e:
        ok = False
        msg = f"❌ {e.message}"

    site_names = site_service.list_site_names()
    shown = name if ok else edit_dropdown_value
    return (
        msg,
        get_sites_table_md(),
        gr.update(choices=[NEW_SITE_CHOICE] + site_names, value=shown),
        gr.update(choices=site_names, value=site_names),  # Update sites_selector in tab 1
        site_service.get_watermark_preview(shown) if shown else None,
        None,  # Reset file input
    )


def handle_delete_site(edit_dropdown_value: str):
    """Xóa website được chọn khỏi CSDL."""
    if not edit_dropdown_value or edit_dropdown_value == NEW_SITE_CHOICE:
        return (
            "❌ Vui lòng chọn một website cụ thể từ danh sách để xóa!",
            get_sites_table_md(),
            gr.update(),
            gr.update(),
            None,
        )

    try:
        site_service.delete_site(edit_dropdown_value)
        msg = f"✅ Đã xóa website: {edit_dropdown_value}"
    except ServiceError as e:
        msg = f"❌ {e.message}"

    site_names = site_service.list_site_names()
    return (
        msg,
        get_sites_table_md(),
        gr.update(choices=[NEW_SITE_CHOICE] + site_names, value=NEW_SITE_CHOICE),
        gr.update(choices=site_names, value=site_names),  # Update sites_selector in tab 1
        None,
    )


def handle_clear_watermark(edit_dropdown_value: str):
    """Xóa logo watermark của website đang chọn."""
    if not edit_dropdown_value or edit_dropdown_value == NEW_SITE_CHOICE:
        return "❌ Vui lòng chọn một website để xóa watermark!", None, get_sites_table_md()
    try:
        site_service.clear_watermark(edit_dropdown_value)
    except ServiceError as e:
        return f"❌ {e.message}", None, get_sites_table_md()
    return f"✅ Đã xóa logo watermark của website '{edit_dropdown_value}'.", None, get_sites_table_md()


def handle_test_connection_ui(url: str, client_key: str, client_secret: str, wp_user: str, wp_pass: str):
    """Kiểm tra kết nối trực tiếp với thông tin đang nhập trên form."""
    try:
        res = site_service.test_connection(url, client_key, client_secret, wp_user, wp_pass)
    except ServiceError as e:
        return f"❌ {e.message}"

    if res.wp_configured:
        if res.wp_ok:
            wp_info = f"\n✅ WordPress Application Password: Đã xác thực (user: {wp_user})"
        else:
            wp_info = "\n❌ WordPress Application Password: Xác thực thất bại"
    else:
        wp_info = "\n⚠️ Chưa có Application Password (vẫn đăng được WooCommerce Sản phẩm, chỉ chưa đăng được Blog Post)."

    if res.wc_ok:
        return f"✅ Kết nối WooCommerce thành công tới {url}!{wp_info}"
    return f"❌ Không thể kết nối WooCommerce tới {url}. Vui lòng kiểm tra lại URL hoặc cặp khóa API Key.{wp_info}"


def build_tab_sites(db_session=None) -> dict:
    """Build the site management tab. Returns components dict."""
    site_names = site_service.list_site_names()

    gr.Markdown("### Website")
    sites_table_view = gr.Markdown(value=get_sites_table_md())

    gr.Markdown("---")

    dropdown_init_choices = ["➕ Thêm website mới"] + site_names
    site_select_edit = gr.Dropdown(
        label="Sửa / xoá website",
        choices=dropdown_init_choices,
        value="➕ Thêm website mới",
        interactive=True,
    )

    with gr.Row():
        input_site_name = gr.Textbox(
            label="Tên định danh website",
            placeholder="VD: khodentrangtri.com hoặc Web Cơ Khí 2",
        )
        input_site_url = gr.Textbox(
            label="URL Website",
            placeholder="VD: https://khodentrangtri.com",
        )

    with gr.Row():
        input_client_key = gr.Textbox(
            label="WooCommerce Client Key",
            placeholder="ck_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        )
        input_client_secret = gr.Textbox(
            label="WooCommerce Client Secret",
            placeholder="cs_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
            type="password",
        )

    with gr.Row():
        input_wp_user = gr.Textbox(
            label="WordPress Username",
            placeholder="admin",
        )
        input_wp_pass = gr.Textbox(
            label="Application Password (cần để tải ảnh lên)",
            placeholder="xxxx xxxx xxxx xxxx",
            type="password",
        )

    # PHẦN WATERMARK LOGO
    gr.Markdown("#### Watermark")
    with gr.Row():
        with gr.Column(scale=1):
            input_watermark_file = gr.File(
                label="Logo (PNG / WebP nền trong)",
                file_types=["image"],
                type="filepath",
            )
            btn_clear_watermark = gr.Button("Xoá logo", variant="secondary", size="sm")

        with gr.Column(scale=1):
            input_watermark_pos = gr.Dropdown(
                label="Vị trí",
                choices=[
                    ("Góc dưới phải (Mặc định)", "bottom-right"),
                    ("Góc dưới trái", "bottom-left"),
                    ("Góc trên phải", "top-right"),
                    ("Góc trên trái", "top-left"),
                    ("Chính giữa", "center"),
                ],
                value="bottom-right",
            )
            input_watermark_opacity = gr.Slider(
                label="Độ mờ",
                minimum=0.1,
                maximum=1.0,
                value=0.7,
                step=0.05,
            )
            current_watermark_preview = gr.Image(
                label="Logo hiện có của website",
                interactive=False,
                height=90,
            )

    with gr.Row():
        btn_save_site = gr.Button("💾 Lưu cấu hình website", variant="primary")
        btn_delete_site = gr.Button("🗑️ Xóa website này", variant="stop")
        btn_test_site = gr.Button("🔌 Kiểm tra kết nối", variant="secondary")

    manage_status = gr.Textbox(label="Kết quả xử lý", lines=3, interactive=False)

    return {
        'sites_table_view': sites_table_view,
        'site_select_edit': site_select_edit,
        'input_site_name': input_site_name,
        'input_site_url': input_site_url,
        'input_client_key': input_client_key,
        'input_client_secret': input_client_secret,
        'input_wp_user': input_wp_user,
        'input_wp_pass': input_wp_pass,
        'input_watermark_file': input_watermark_file,
        'input_watermark_pos': input_watermark_pos,
        'input_watermark_opacity': input_watermark_opacity,
        'current_watermark_preview': current_watermark_preview,
        'btn_clear_watermark': btn_clear_watermark,
        'btn_save_site': btn_save_site,
        'btn_delete_site': btn_delete_site,
        'btn_test_site': btn_test_site,
        'manage_status': manage_status,
    }
