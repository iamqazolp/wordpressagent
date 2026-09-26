"""
app.py
Giao diện chính của WordPress Agent.
Chạy lệnh: python app.py
Sau đó mở trình duyệt: http://localhost:7860
"""
import logging
import re
import gradio as gr

from config import settings
from modules import scraper, searcher, ai_writer, image_uploader, wp_publisher

# ── Cấu hình logging ─────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# PIPELINE CHÍNH (ĐA WEBSITE & RANDOMIZE)
# ═══════════════════════════════════════════════════════════════

def run_pipeline(
    product_name: str,
    image_files,
    extra_urls_text: str,
    user_notes_text: str,
    selected_sites: list[str],
    randomize_enabled: bool,
    progress=gr.Progress(),
):
    """
    Chạy pipeline: tìm kiếm → đọc bài → tạo nội dung cho từng website.
    Returns:
        (preview_site_dropdown, title_output, preview_output, articles_state, current_site_state, status_message)
    """
    empty_dropdown = gr.Dropdown(choices=["(Chưa có bài viết)"], value="(Chưa có bài viết)")
    if not product_name.strip():
        return empty_dropdown, "", "", {}, "", "❌ Vui lòng nhập tên sản phẩm!"

    if not selected_sites:
        return empty_dropdown, "", "", {}, "", "❌ Vui lòng tích chọn ít nhất 1 website đăng bài!"

    if not settings.GEMINI_API_KEY:
        return empty_dropdown, "", "", {}, "", (
            "❌ Chưa cấu hình GEMINI_API_KEY.\n"
            "Mở file .env và thêm dòng:\nGEMINI_API_KEY=your_key_here"
        )

    logs = []
    articles = {}

    try:
        # Bước 1: Tìm kiếm bài tham khảo
        progress(0.1, desc="🔍 Đang tìm kiếm tài liệu tham khảo...")
        extra_urls = [u.strip() for u in extra_urls_text.splitlines() if u.strip()]
        search_results = searcher.search_articles(product_name, extra_urls)
        logs.append(f"🔍 Tìm thấy {len(search_results)} nguồn tham khảo")

        # Bước 2: Đọc nội dung từng bài
        progress(0.25, desc="📄 Đang trích xuất nội dung kỹ thuật...")
        urls_to_scrape = [a["url"] for a in search_results]
        ref_contents = scraper.scrape_multiple(urls_to_scrape)
        logs.append(f"📄 Đọc thành công {len(ref_contents)}/{len(search_results)} nguồn")

        image_count = len(image_files) if image_files else 0
        total_sites = len(selected_sites)

        # Bước 3: Tạo bài viết cho từng website
        if randomize_enabled and total_sites > 1:
            logs.append(f"🎲 Chế độ Randomize: Đang tạo {total_sites} phiên bản nội dung độc bản khác nhau...")
            for idx, site_name in enumerate(selected_sites, 1):
                p_val = 0.35 + (0.55 * (idx / total_sites))
                progress(p_val, desc=f"🤖 AI đang viết bài riêng cho {site_name} ({idx}/{total_sites})...")
                title, raw_html = ai_writer.write_post(
                    product_name=product_name,
                    reference_contents=ref_contents,
                    image_count=image_count,
                    site_name=site_name,
                    user_notes=user_notes_text,
                    variation_index=idx,
                    total_variations=total_sites,
                )
                preview_html = _make_preview_html(raw_html, image_files or [])
                articles[site_name] = {
                    "title": title,
                    "raw_html": raw_html,
                    "preview_html": preview_html,
                }
                logs.append(f"  ✓ {site_name}: {title}")
        else:
            # Tạo 1 bài duy nhất và chia sẻ cho tất cả các site
            progress(0.6, desc="🤖 AI đang viết bài...")
            first_site = selected_sites[0]
            title, raw_html = ai_writer.write_post(
                product_name=product_name,
                reference_contents=ref_contents,
                image_count=image_count,
                site_name=first_site,
                user_notes=user_notes_text,
                variation_index=0,
                total_variations=1,
            )
            preview_html = _make_preview_html(raw_html, image_files or [])
            for s in selected_sites:
                articles[s] = {
                    "title": title,
                    "raw_html": raw_html,
                    "preview_html": preview_html,
                }
            logs.append(f"🤖 Đã tạo bài chung: {title}")

        progress(1.0, desc="✅ Hoàn tất!")
        first_site = selected_sites[0]
        first_article = articles[first_site]

        updated_dropdown = gr.Dropdown(
            choices=selected_sites,
            value=first_site,
            interactive=True,
        )

        status_msg = (
            "\n".join(logs)
            + f"\n\n✅ Đã tạo xong nội dung cho {total_sites} website! "
            "Bạn có thể chọn từng website ở ô bên dưới để xem trước hoặc chỉnh sửa trước khi đăng."
        )

        return (
            updated_dropdown,
            first_article["title"],
            first_article["preview_html"],
            articles,
            first_site,
            status_msg,
        )

    except Exception as e:
        logger.exception("Lỗi trong pipeline")
        return empty_dropdown, "", "", {}, "", f"❌ Lỗi: {str(e)}"


# ═══════════════════════════════════════════════════════════════
# ĐĂNG LÊN NHIỀU WEBSITE
# ═══════════════════════════════════════════════════════════════

def publish_to_selected_sites(
    articles_state: dict,
    image_files,
    post_status: str,
    post_type: str,
    progress=gr.Progress(),
):
    """
    Đăng bài viết lên tất cả các website có trong articles_state.
    """
    if not articles_state:
        return "❌ Chưa có nội dung bài viết nào để đăng! Hãy tạo bài viết trước."

    image_paths = []
    if image_files:
        image_paths = image_files if isinstance(image_files[0], str) else [f.name for f in image_files]

    results_report = ["### 📋 Kết Quả Đăng Bài Lên Các Website:\n"]
    total = len(articles_state)

    for i, (site_name, article_data) in enumerate(articles_state.items(), 1):
        progress((i / total), desc=f"📤 Đang đăng lên {site_name} ({i}/{total})...")
        site_config = settings.SITES.get(site_name)

        if not site_config:
            results_report.append(f"- **{site_name}**: ❌ Không tìm thấy thông tin cấu hình trong hệ thống.")
            continue

        # Upload ảnh nếu có WP Application Password
        uploaded = []
        if image_paths and site_config.get("wp_user"):
            try:
                uploaded = image_uploader.upload_images(image_paths, site_config)
            except Exception as e:
                logger.warning(f"Upload ảnh thất bại tại {site_name}: {e}")

        title = article_data.get("title", "")
        raw_html = article_data.get("raw_html", "")

        try:
            if "Sản phẩm" in post_type:
                res = wp_publisher.publish_product(
                    title=title,
                    html_content=raw_html,
                    uploaded_images=uploaded,
                    site_config=site_config,
                    status=post_status,
                )
                type_str = "Sản phẩm"
            else:
                if not site_config.get("wp_user"):
                    results_report.append(
                        f"- **{site_name}**: ❌ Chưa cấu hình WP_USER & WP_APP_PASSWORD để đăng Blog Post (chỉ có thể đăng WooCommerce Sản phẩm)."
                    )
                    continue
                res = wp_publisher.publish_post(
                    title=title,
                    html_content=raw_html,
                    uploaded_images=uploaded,
                    site_config=site_config,
                    status=post_status,
                )
                type_str = "Bài viết"

            status_lbl = "📝 Nháp" if res["status"] == "draft" else "🟢 Công khai"
            results_report.append(
                f"- **{site_name}**: ✅ Đăng {type_str} thành công ({status_lbl}) | "
                f"[Xem sản phẩm]({res['post_url']}) | [Chỉnh sửa]({res['edit_url']})"
            )
        except Exception as e:
            logger.exception(f"Lỗi đăng bài lên {site_name}")
            results_report.append(f"- **{site_name}**: ❌ Thất bại: {str(e)}")

    return "\n\n".join(results_report)


# ═══════════════════════════════════════════════════════════════
# QUẢN LÝ WEBSITE (THÊM / SỬA / XÓA)
# ═══════════════════════════════════════════════════════════════

def get_sites_table_md() -> str:
    """Trả về bảng Markdown hiển thị danh sách các website hiện có."""
    sites = settings.load_sites()
    if not sites:
        return "*Chưa có website nào được cấu hình.*"

    md = "| Tên Website | URL | WooCommerce Key | WordPress App Password |\n"
    md += "| :--- | :--- | :--- | :--- |\n"
    for name, data in sites.items():
        ck_masked = data.get("client_key", "")[:8] + "..." if data.get("client_key") else "Chưa có"
        has_wp = "✅ Đã cấu hình" if data.get("wp_user") and data.get("wp_app_password") else "Chưa có"
        md += f"| **{name}** | {data.get('url')} | `{ck_masked}` | {has_wp} |\n"
    return md


def on_select_site_for_edit(selected_choice: str):
    """Khi người dùng chọn 1 website trong dropdown để xem hoặc sửa."""
    if not selected_choice or selected_choice == "➕ Thêm website mới":
        return "", "", "", "", "", "", "Điền thông tin để thêm website mới."

    site_data = settings.SITES.get(selected_choice)
    if not site_data:
        return "", "", "", "", "", "", "Không tìm thấy dữ liệu website."

    return (
        site_data.get("name", ""),
        site_data.get("url", ""),
        site_data.get("client_key", ""),
        site_data.get("client_secret", ""),
        site_data.get("wp_user", ""),
        site_data.get("wp_app_password", ""),
        f"Đang xem thông tin website: {selected_choice}",
    )


def handle_save_site(
    name: str,
    url: str,
    client_key: str,
    client_secret: str,
    wp_user: str,
    wp_app_password: str,
    edit_dropdown_value: str,
):
    """Lưu thêm mới hoặc cập nhật website."""
    old_name = "" if edit_dropdown_value == "➕ Thêm website mới" else edit_dropdown_value
    ok, msg = settings.save_site(
        name=name,
        url=url,
        client_key=client_key,
        client_secret=client_secret,
        wp_user=wp_user,
        wp_app_password=wp_app_password,
        old_name=old_name,
    )

    choices = settings.get_site_choices()
    dropdown_choices = ["➕ Thêm website mới"] + choices
    new_table_md = get_sites_table_md()

    # Cập nhật cả checkbox group ở tab 1
    return (
        msg,
        new_table_md,
        gr.Dropdown(choices=dropdown_choices, value=name if ok else edit_dropdown_value),
        gr.CheckboxGroup(choices=choices, value=choices),
    )


def handle_delete_site(edit_dropdown_value: str):
    """Xóa website được chọn."""
    if not edit_dropdown_value or edit_dropdown_value == "➕ Thêm website mới":
        return (
            "❌ Vui lòng chọn một website cụ thể từ danh sách để xóa!",
            get_sites_table_md(),
            gr.Dropdown(),
            gr.CheckboxGroup(),
        )

    ok, msg = settings.delete_site(edit_dropdown_value)
    choices = settings.get_site_choices()
    dropdown_choices = ["➕ Thêm website mới"] + choices
    new_table_md = get_sites_table_md()

    return (
        msg,
        new_table_md,
        gr.Dropdown(choices=dropdown_choices, value="➕ Thêm website mới"),
        gr.CheckboxGroup(choices=choices, value=choices[:1] if choices else []),
    )


def handle_test_connection_ui(url: str, client_key: str, client_secret: str, wp_user: str, wp_pass: str):
    """Kiểm tra kết nối trực tiếp với thông tin đang nhập trên form."""
    if not url or not client_key or not client_secret:
        return "❌ Vui lòng điền đủ URL, WooCommerce Client Key và Client Secret trước khi kiểm tra!"

    temp_config = {
        "url": url,
        "client_key": client_key,
        "client_secret": client_secret,
        "wp_user": wp_user,
        "wp_app_password": wp_pass,
    }
    ok = wp_publisher.test_connection(temp_config)
    wp_info = ""
    if wp_user and wp_pass:
        wp_info = f"\n✅ WordPress Application Password: Đã xác thực (user: {wp_user})"
    else:
        wp_info = "\n⚠️ Chưa có Application Password (vẫn đăng được WooCommerce Sản phẩm, chỉ chưa đăng được Blog Post)."

    if ok:
        return f"✅ Kết nối thành công tới {url}!{wp_info}"
    else:
        return f"❌ Không thể kết nối tới {url}. Vui lòng kiểm tra lại URL hoặc cặp khóa API Key."


# ═══════════════════════════════════════════════════════════════
# HELPER GIAO DIỆN
# ═══════════════════════════════════════════════════════════════

def _make_preview_html(html_content, image_files):
    """Thay [IMAGE_PLACEHOLDER_N] bằng ảnh local để preview."""
    if not image_files:
        return re.sub(r"\[IMAGE_PLACEHOLDER_\d+\]", "", html_content)

    paths = image_files if (image_files and isinstance(image_files[0], str)) else [f.name for f in image_files]

    def replace_placeholder(match):
        n = int(match.group(1)) - 1
        idx = min(n, len(paths) - 1)
        return (
            f'<figure style="text-align:center;margin:20px 0;">'
            f'<img src="/file={paths[idx]}" style="max-width:100%;height:auto;border-radius:4px;" />'
            f"</figure>"
        )

    return re.sub(r"\[IMAGE_PLACEHOLDER_(\d+)\]", replace_placeholder, html_content)


def on_change_preview_site(selected_site, articles_state):
    """Khi đổi dropdown xem trước của site nào."""
    if not articles_state or selected_site not in articles_state:
        return "", "", selected_site
    art = articles_state[selected_site]
    return art.get("title", ""), art.get("preview_html", ""), selected_site


def on_edit_title(new_title, current_site, articles_state):
    """Khi người dùng chỉnh sửa tiêu đề của website hiện tại."""
    if articles_state and current_site in articles_state:
        articles_state[current_site]["title"] = new_title
    return articles_state


# ═══════════════════════════════════════════════════════════════
# GIAO DIỆN CHÍNH (GRADIO BLOCKS)
# ═══════════════════════════════════════════════════════════════

with gr.Blocks(
    title="WordPress Agent - Đa Website & Tự Động Hóa",
) as demo:

    # State lưu trữ danh sách bài viết theo từng site: {site_name: {title, raw_html, preview_html}}
    articles_state = gr.State({})
    current_preview_site_state = gr.State("")

    gr.HTML("""
    <div style="text-align:center;padding:15px 0 10px;">
        <h1 style="font-size:2em;margin:0;color:#1381f0;">🌟 WordPress Agent</h1>
        <p style="color:#666;margin:5px 0 0;">Quản lý đa website • Tự động viết & đăng sản phẩm • Chống trùng lặp SEO</p>
    </div>
    """)

    with gr.Tabs():

        # ═══════════════════════════════════════════════════════
        # TAB 1: TẠO VÀ ĐĂNG BÀI
        # ═══════════════════════════════════════════════════════
        with gr.TabItem("✍️ Tạo & Đăng Bài"):
            with gr.Row():
                with gr.Column(scale=1):
                    product_input = gr.Textbox(
                        label="🏷️ Tên sản phẩm",
                        placeholder="VD: Pa lăng cáp điện 1T x 12M, máy cắt góc JL...",
                    )
                    image_input = gr.File(
                        label="🖼️ Upload ảnh sản phẩm",
                        file_count="multiple",
                        file_types=["image"],
                    )
                    extra_urls_input = gr.Textbox(
                        label="🔗 URL tham khảo thêm (tùy chọn)",
                        placeholder="Mỗi URL một dòng\nhttps://example.com/bai-viet-1",
                        lines=2,
                    )
                    user_notes_input = gr.Textbox(
                        label="💡 Gợi ý / Yêu cầu riêng cho AI (Tùy chọn)",
                        placeholder="VD: Nhấn mạnh lõi đồng 100%, bảo hành 24 tháng, tặng kèm móc phụ...",
                        lines=2,
                    )

                    sites_selector = gr.CheckboxGroup(
                        label="🌐 Chọn các website đăng bài (chọn nhiều)",
                        choices=settings.get_site_choices(),
                        value=settings.get_site_choices(),
                    )

                    randomize_checkbox = gr.Checkbox(
                        label="🎲 Bật Randomize (Mỗi website một phiên bản riêng - Tránh phạt SEO)",
                        value=True,
                        info="Nếu bật: Mỗi website sẽ có tiêu đề, lời mở đầu và hành văn độc bản.",
                    )

                    create_btn = gr.Button("🚀 Tạo bài viết cho các website đã chọn", variant="primary", size="lg")

                with gr.Column(scale=2):
                    status_box = gr.Textbox(label="📋 Trạng thái tạo bài", lines=5, interactive=False)

                    with gr.Group():
                        gr.Markdown("### 👁️ Xem trước nội dung theo từng website")
                        preview_site_selector = gr.Dropdown(
                            label="Chọn website để xem bài viết tương ứng:",
                            choices=settings.get_site_choices(),
                            value=settings.get_site_choices()[0] if settings.get_site_choices() else None,
                            interactive=True,
                        )
                        title_output = gr.Textbox(
                            label="📝 Tiêu đề sản phẩm cho website này (có thể chỉnh sửa)",
                            lines=1,
                            interactive=True,
                        )
                        preview_output = gr.HTML(label="Nội dung bài viết")

            with gr.Row():
                post_type_selector = gr.Radio(
                    label="Loại nội dung đăng",
                    choices=["Sản phẩm WooCommerce", "Bài viết Blog"],
                    value="Sản phẩm WooCommerce",
                    info="Sản phẩm WooCommerce dùng trực tiếp API Key sẵn có mà không cần Application Password",
                )
                post_status_selector = gr.Radio(
                    label="Trạng thái khi đăng",
                    choices=["draft", "publish"],
                    value="draft",
                    info="'draft' = lưu nháp (khuyến nghị), 'publish' = công khai ngay",
                )
                publish_btn = gr.Button("📤 Đăng lên tất cả các website đã chọn", variant="secondary", size="lg")

            publish_result = gr.Markdown()

        # ═══════════════════════════════════════════════════════
        # TAB 2: QUẢN LÝ DANH SÁCH WEBSITE
        # ═══════════════════════════════════════════════════════
        with gr.TabItem("⚙️ Quản Lý Website"):
            gr.Markdown("### 🌐 Danh Sách Các Website Đang Kết Nối")
            sites_table_view = gr.Markdown(value=get_sites_table_md())

            gr.Markdown("---")
            gr.Markdown("### 🛠️ Thêm Mới / Chỉnh Sửa / Xóa Website")

            dropdown_init_choices = ["➕ Thêm website mới"] + settings.get_site_choices()
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

            with gr.Row():
                btn_save_site = gr.Button("💾 Lưu cấu hình website", variant="primary")
                btn_delete_site = gr.Button("🗑️ Xóa website này", variant="stop")
                btn_test_site = gr.Button("🔌 Kiểm tra kết nối", variant="secondary")

            manage_status = gr.Textbox(label="Kết quả xử lý", lines=3, interactive=False)

    # ═══════════════════════════════════════════════════════════
    # KẾT NỐI SỰ KIỆN (EVENT WIRING)
    # ═══════════════════════════════════════════════════════════

    # Sự kiện tạo bài viết
    create_btn.click(
        fn=run_pipeline,
        inputs=[
            product_input,
            image_input,
            extra_urls_input,
            user_notes_input,
            sites_selector,
            randomize_checkbox,
        ],
        outputs=[
            preview_site_selector,
            title_output,
            preview_output,
            articles_state,
            current_preview_site_state,
            status_box,
        ],
        show_progress=True,
    )

    # Khi đổi website trong dropdown preview
    preview_site_selector.change(
        fn=on_change_preview_site,
        inputs=[preview_site_selector, articles_state],
        outputs=[title_output, preview_output, current_preview_site_state],
    )

    # Khi chỉnh sửa tiêu đề ở ô text
    title_output.change(
        fn=on_edit_title,
        inputs=[title_output, current_preview_site_state, articles_state],
        outputs=[articles_state],
    )

    # Sự kiện đăng bài lên tất cả website
    publish_btn.click(
        fn=publish_to_selected_sites,
        inputs=[articles_state, image_input, post_status_selector, post_type_selector],
        outputs=[publish_result],
        show_progress=True,
    )

    # Sự kiện quản lý website: chọn site từ dropdown sửa
    site_select_edit.change(
        fn=on_select_site_for_edit,
        inputs=[site_select_edit],
        outputs=[
            input_site_name,
            input_site_url,
            input_client_key,
            input_client_secret,
            input_wp_user,
            input_wp_pass,
            manage_status,
        ],
    )

    # Sự kiện lưu website
    btn_save_site.click(
        fn=handle_save_site,
        inputs=[
            input_site_name,
            input_site_url,
            input_client_key,
            input_client_secret,
            input_wp_user,
            input_wp_pass,
            site_select_edit,
        ],
        outputs=[manage_status, sites_table_view, site_select_edit, sites_selector],
    )

    # Sự kiện xóa website
    btn_delete_site.click(
        fn=handle_delete_site,
        inputs=[site_select_edit],
        outputs=[manage_status, sites_table_view, site_select_edit, sites_selector],
    )

    # Sự kiện kiểm tra kết nối
    btn_test_site.click(
        fn=handle_test_connection_ui,
        inputs=[input_site_url, input_client_key, input_client_secret, input_wp_user, input_wp_pass],
        outputs=[manage_status],
    )


# ═══════════════════════════════════════════════════════════════
# KHỞI ĐỘNG
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n" + "=" * 50)
    print("  WordPress Agent - Đa Website & Randomize")
    print("=" * 50)

    sites = settings.load_sites()
    print(f"✓  Số lượng website đang quản lý: {len(sites)}")
    for name, data in sites.items():
        print(f"   - {name}: {data['url']}")

    print("\n👉 Mở trình duyệt tại: http://localhost:7860\n")

    demo.launch(
        server_name="127.0.0.1",
        server_port=7860,
        share=False,
        inbrowser=True,
        theme=gr.themes.Soft(primary_hue="blue"),
    )
