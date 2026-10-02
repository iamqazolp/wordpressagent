from __future__ import annotations

import logging
import os
import re
import shutil
from pathlib import Path
import gradio as gr

from core.image_processor import WATERMARK_POSITIONS

logger = logging.getLogger(__name__)

LOGOS_DIR = Path("data") / "logos"
LOGOS_DIR.mkdir(parents=True, exist_ok=True)


def _safe_filename(name: str) -> str:
    """Tạo tên file an toàn từ tên website."""
    clean = re.sub(r"[^\w\-.]", "_", name.strip().lower())
    return clean or "site"


def get_sites_table_md() -> str:
    """Trả về bảng Markdown hiển thị danh sách các website hiện có từ CSDL kèm trạng thái Watermark."""
    from db.database import SessionLocal
    from db import crud
    
    db = SessionLocal()
    try:
        sites = crud.get_all_sites(db)
        if not sites:
            return "*Chưa có website nào được cấu hình.*"

        md = "| Tên Website | URL | WooCommerce Key | WordPress App Password | Watermark Logo |\n"
        md += "| :--- | :--- | :--- | :--- | :--- |\n"
        for site in sites:
            config = crud.get_site_config(db, site.id)
            if not config:
                continue
                
            ck_masked = config.get("client_key", "")[:8] + "..." if config.get("client_key") else "Chưa có"
            has_wp = "✅ Đã cấu hình" if config.get("wp_user") and config.get("wp_app_password") else "Chưa có"

            # Trạng thái Watermark
            wm_path = config.get("watermark_path", "")
            if wm_path and Path(wm_path).exists():
                wm_pos_lbl = WATERMARK_POSITIONS.get(config.get("watermark_position", "bottom-right"), "Dưới phải")
                wm_status = f"✅ Có logo ({wm_pos_lbl})"
            else:
                wm_status = "Chưa có"

            md += f"| **{site.name}** | {site.url} | `{ck_masked}` | {has_wp} | {wm_status} |\n"
        return md
    finally:
        db.close()


def on_select_site_for_edit(selected_choice: str):
    """Khi người dùng chọn 1 website trong dropdown để xem hoặc sửa."""
    if not selected_choice or selected_choice == "➕ Thêm website mới":
        return "", "", "", "", "", "", "bottom-right", 0.7, None, None, "Điền thông tin để thêm website mới."

    from db.database import SessionLocal
    from db import crud
    
    db = SessionLocal()
    try:
        site = crud.get_site_by_name(db, selected_choice)
        if not site:
            return "", "", "", "", "", "", "bottom-right", 0.7, None, None, "Không tìm thấy dữ liệu website."

        config = crud.get_site_config(db, site.id)
        if not config:
            return "", "", "", "", "", "", "bottom-right", 0.7, None, None, "Không thể đọc dữ liệu cấu hình website."
            
        wm_path = config.get("watermark_path", "")
        preview_img = wm_path if (wm_path and Path(wm_path).exists()) else None

        return (
            config.get("name", ""),
            config.get("url", ""),
            config.get("client_key", ""),
            config.get("client_secret", ""),
            config.get("wp_user", ""),
            config.get("wp_app_password", ""),
            config.get("watermark_position", "bottom-right") or "bottom-right",
            float(config.get("watermark_opacity", 0.7) or 0.7),
            preview_img,
            None,  # Reset input file upload
            f"Đang xem thông tin website: {selected_choice}",
        )
    finally:
        db.close()


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
    from db.database import SessionLocal
    from db import crud
    
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

    db = SessionLocal()
    try:
        is_new = not edit_dropdown_value or edit_dropdown_value == "➕ Thêm website mới"
        
        # Xử lý lưu file watermark nếu có upload mới
        new_wm_path = None
        if watermark_file:
            raw_path = watermark_file.name if hasattr(watermark_file, "name") else str(watermark_file)
            if Path(raw_path).exists():
                ext = Path(raw_path).suffix.lower() or ".png"
                dest_path = LOGOS_DIR / f"{_safe_filename(name)}_watermark{ext}"
                shutil.copy2(raw_path, dest_path)
                new_wm_path = str(dest_path)
                logger.info(f"Đã lưu logo watermark cho {name} tại {dest_path}")

        if is_new:
            # Add new
            existing = crud.get_site_by_name(db, name)
            if existing:
                msg = f"❌ Tên website '{name}' đã tồn tại!"
                ok = False
            else:
                site = crud.create_site(
                    db,
                    name=name,
                    url=url,
                    client_key=client_key,
                    client_secret=client_secret,
                    wp_user=wp_user,
                    wp_app_password=wp_app_password,
                    watermark_path=new_wm_path or "",
                    watermark_position=watermark_pos or "bottom-right",
                    watermark_opacity=float(watermark_opacity or 0.7),
                )
                if site:
                    msg = f"✅ Đã thêm website mới: {name}"
                    ok = True
                else:
                    msg = f"❌ Lỗi khi thêm website {name}"
                    ok = False
        else:
            # Update existing
            site = crud.get_site_by_name(db, edit_dropdown_value)
            if not site:
                msg = f"❌ Không tìm thấy website '{edit_dropdown_value}' để cập nhật."
                ok = False
            else:
                # Nếu đổi tên, kiểm tra trùng lặp
                if name != edit_dropdown_value and crud.get_site_by_name(db, name):
                    msg = f"❌ Tên website mới '{name}' đã được sử dụng."
                    ok = False
                else:
                    update_kwargs = {
                        "name": name,
                        "url": url,
                        "client_key": client_key,
                        "client_secret": client_secret,
                        "wp_user": wp_user,
                        "wp_app_password": wp_app_password,
                        "watermark_position": watermark_pos or "bottom-right",
                        "watermark_opacity": float(watermark_opacity or 0.7),
                    }
                    if new_wm_path:
                        update_kwargs["watermark_path"] = new_wm_path

                    updated = crud.update_site(db, site.id, **update_kwargs)
                    if updated:
                        msg = f"✅ Đã cập nhật website: {name}"
                        ok = True
                    else:
                        msg = f"❌ Lỗi khi cập nhật website {name}"
                        ok = False

        site_names = crud.get_site_names(db)
        dropdown_choices = ["➕ Thêm website mới"] + site_names
        new_table_md = get_sites_table_md()

        # Lấy lại watermark hiện tại để update preview
        current_site = crud.get_site_by_name(db, name if ok else edit_dropdown_value)
        current_wm = current_site.watermark_path if current_site else ""
        current_wm_img = current_wm if (current_wm and Path(current_wm).exists()) else None

        return (
            msg,
            new_table_md,
            gr.update(choices=dropdown_choices, value=name if ok else edit_dropdown_value),
            gr.update(choices=site_names, value=site_names), # Update sites_selector in tab 1
            current_wm_img,
            None, # Reset file input
        )
    finally:
        db.close()


def handle_delete_site(edit_dropdown_value: str):
    """Xóa website được chọn khỏi CSDL."""
    from db.database import SessionLocal
    from db import crud
    
    if not edit_dropdown_value or edit_dropdown_value == "➕ Thêm website mới":
        return (
            "❌ Vui lòng chọn một website cụ thể từ danh sách để xóa!",
            get_sites_table_md(),
            gr.update(),
            gr.update(),
            None,
        )

    db = SessionLocal()
    try:
        site = crud.get_site_by_name(db, edit_dropdown_value)
        if not site:
            msg = f"❌ Không tìm thấy website '{edit_dropdown_value}'."
        else:
            ok = crud.delete_site(db, site.id)
            if ok:
                msg = f"✅ Đã xóa website: {edit_dropdown_value}"
            else:
                msg = f"❌ Không thể xóa website '{edit_dropdown_value}' (có thể đây là website cuối cùng)."
                
        site_names = crud.get_site_names(db)
        dropdown_choices = ["➕ Thêm website mới"] + site_names
        new_table_md = get_sites_table_md()

        return (
            msg,
            new_table_md,
            gr.update(choices=dropdown_choices, value="➕ Thêm website mới"),
            gr.update(choices=site_names, value=site_names), # Update sites_selector in tab 1
            None,
        )
    finally:
        db.close()


def handle_clear_watermark(edit_dropdown_value: str):
    """Xóa logo watermark của website đang chọn."""
    if not edit_dropdown_value or edit_dropdown_value == "➕ Thêm website mới":
        return "❌ Vui lòng chọn một website để xóa watermark!", None, get_sites_table_md()

    from db.database import SessionLocal
    from db import crud

    db = SessionLocal()
    try:
        site = crud.get_site_by_name(db, edit_dropdown_value)
        if not site:
            return f"❌ Không tìm thấy website '{edit_dropdown_value}'.", None, get_sites_table_md()

        # Xóa file vật lý nếu có
        if site.watermark_path and Path(site.watermark_path).exists():
            try:
                Path(site.watermark_path).unlink()
            except Exception as e:
                logger.warning(f"Không thể xóa file watermark cũ: {e}")

        crud.update_site(db, site.id, watermark_path="")
        return f"✅ Đã xóa logo watermark của website '{edit_dropdown_value}'.", None, get_sites_table_md()
    finally:
        db.close()


def handle_test_connection_ui(url: str, client_key: str, client_secret: str, wp_user: str, wp_pass: str):
    """Kiểm tra kết nối trực tiếp với thông tin đang nhập trên form."""
    if not url or not client_key or not client_secret:
        return "❌ Vui lòng điền đủ URL, WooCommerce Client Key và Client Secret trước khi kiểm tra!"

    from core import wp_client
    
    temp_config = {
        "url": url,
        "client_key": client_key,
        "client_secret": client_secret,
        "wp_user": wp_user,
        "wp_app_password": wp_pass,
    }
    
    res = wp_client.test_connection(temp_config)
    wp_ok = res.get("wp_ok", False)
    wc_ok = res.get("wc_ok", False)
    
    wp_info = ""
    if wp_user and wp_pass:
        if wp_ok:
            wp_info = f"\n✅ WordPress Application Password: Đã xác thực (user: {wp_user})"
        else:
            wp_info = f"\n❌ WordPress Application Password: Xác thực thất bại"
    else:
        wp_info = "\n⚠️ Chưa có Application Password (vẫn đăng được WooCommerce Sản phẩm, chỉ chưa đăng được Blog Post)."

    if wc_ok:
        return f"✅ Kết nối WooCommerce thành công tới {url}!{wp_info}"
    else:
        return f"❌ Không thể kết nối WooCommerce tới {url}. Vui lòng kiểm tra lại URL hoặc cặp khóa API Key.{wp_info}"


def build_tab_sites(db_session=None) -> dict:
    """Build the site management tab. Returns components dict."""
    from db.database import SessionLocal
    from db import crud
    
    db = SessionLocal() if db_session is None else db_session
    try:
        site_names = crud.get_site_names(db)
    finally:
        if db_session is None:
            db.close()

    gr.Markdown("### 🌐 Danh Sách Các Website Đang Kết Nối")
    sites_table_view = gr.Markdown(value=get_sites_table_md())

    gr.Markdown("---")
    gr.Markdown("### 🛠️ Thêm Mới / Chỉnh Sửa / Xóa Website")

    dropdown_init_choices = ["➕ Thêm website mới"] + site_names
    site_select_edit = gr.Dropdown(
        label="Chọn website cần sửa/xóa (hoặc chọn '➕ Thêm website mới'):",
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
            label="WordPress Username (Tùy chọn - để đăng Blog/upload ảnh)",
            placeholder="admin",
        )
        input_wp_pass = gr.Textbox(
            label="WordPress Application Password (Tùy chọn)",
            placeholder="xxxx xxxx xxxx xxxx",
            type="password",
        )

    # PHẦN WATERMARK LOGO
    gr.Markdown("#### 🏷️ Cấu Hình Watermark / Logo Thương Hiệu Cho Website (Phase 3)")
    with gr.Row():
        with gr.Column(scale=1):
            input_watermark_file = gr.File(
                label="Tải lên file Logo thương hiệu (PNG / WebP trong suốt)",
                file_types=["image"],
                type="filepath",
            )
            btn_clear_watermark = gr.Button("🗑️ Xóa logo watermark hiện tại", variant="secondary", size="sm")

        with gr.Column(scale=1):
            input_watermark_pos = gr.Dropdown(
                label="Vị trí đóng dấu Watermark trên ảnh",
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
                label="Độ mờ Logo (Opacity)",
                minimum=0.1,
                maximum=1.0,
                value=0.7,
                step=0.05,
                info="0.7 = mờ 70% (vừa vặn không che sản phẩm)",
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
