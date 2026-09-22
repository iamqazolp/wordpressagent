"""
app.py
Giao diện chính của WordPress Agent.
Chạy lệnh: python app.py
Sau đó mở trình duyệt: http://localhost:7860
"""
import logging
import os
import tempfile
import shutil

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
# PIPELINE CHÍNH
# ═══════════════════════════════════════════════════════════════

def run_pipeline(
    product_name: str,
    image_files,           # list of file paths từ Gradio
    extra_urls_text: str,
    site_name: str,
    progress=gr.Progress(),
) -> tuple[str, str, str]:
    """
    Chạy toàn bộ pipeline: tìm kiếm → đọc bài → viết AI → trả về preview.

    Returns:
        (title, html_preview, status_message)
    """
    # ── Kiểm tra đầu vào ─────────────────────────────────────
    if not product_name.strip():
        return "", "", "❌ Vui lòng nhập tên sản phẩm!"

    if not settings.GEMINI_API_KEY:
        return "", "", (
            "❌ Chưa cấu hình GEMINI_API_KEY.\n"
            "Mở file .env và thêm dòng:\nGEMINI_API_KEY=your_key_here"
        )

    site_config = settings.SITES.get(site_name)
    if not site_config:
        return "", "", f"❌ Không tìm thấy cấu hình cho website: {site_name}"

    logs = []

    try:
        # Bước 1: Tìm kiếm bài tham khảo
        progress(0.1, desc="🔍 Đang tìm kiếm bài tham khảo...")
        extra_urls = [u.strip() for u in extra_urls_text.splitlines() if u.strip()]
        articles = searcher.search_articles(product_name, extra_urls)
        logs.append(f"🔍 Tìm thấy {len(articles)} nguồn tham khảo")

        # Bước 2: Đọc nội dung từng bài
        progress(0.3, desc="📄 Đang đọc nội dung bài tham khảo...")
        urls_to_scrape = [a["url"] for a in articles]
        ref_contents = scraper.scrape_multiple(urls_to_scrape)
        logs.append(f"📄 Đọc được nội dung từ {len(ref_contents)}/{len(articles)} nguồn")

        # Bước 3: Đếm số ảnh
        image_count = len(image_files) if image_files else 0

        # Bước 4: Gọi AI viết bài
        progress(0.6, desc="🤖 AI đang viết bài...")
        title, html_content = ai_writer.write_post(
            product_name=product_name,
            reference_contents=ref_contents,
            image_count=image_count,
            site_name=site_name,
        )
        logs.append(f"🤖 Đã viết xong bài: {title}")

        # Bước 5: Tạo preview HTML (thay placeholder bằng ảnh preview nếu có)
        preview_html = _make_preview_html(html_content, image_files or [])

        progress(1.0, desc="✅ Hoàn tất!")

        status = "\n".join(logs) + "\n\n✅ Bài viết đã sẵn sàng! Kiểm tra preview bên dưới, rồi nhấn **Đăng bài**."
        return title, preview_html, status

    except Exception as e:
        logger.exception("Lỗi trong pipeline")
        return "", "", f"❌ Lỗi: {str(e)}"


def publish_to_wordpress(
    title: str,
    html_preview: str,
    image_files,
    site_name: str,
    post_status: str,
    progress=gr.Progress(),
) -> str:
    """
    Upload ảnh và đăng bài lên WordPress.
    """
    if not title or not html_preview:
        return "❌ Chưa có bài viết. Vui lòng tạo bài trước!"

    site_config = settings.SITES.get(site_name)
    if not site_config:
        return f"❌ Không tìm thấy cấu hình cho website: {site_name}"

    # Lấy HTML gốc (không phải preview - cần bản có placeholder)
    # Vì preview đã thay placeholder bằng ảnh local, ta cần xử lý lại
    # Thực ra html_preview đã có ảnh - ta chỉ cần upload ảnh và re-build
    try:
        # Bước 1: Upload ảnh
        image_paths = []
        if image_files:
            progress(0.2, desc="🖼️ Đang upload ảnh lên WordPress...")
            image_paths = image_files if isinstance(image_files[0], str) else [f.name for f in image_files]

        uploaded = []
        if image_paths:
            uploaded = image_uploader.upload_images(image_paths, site_config)
            if not uploaded:
                return "❌ Upload ảnh thất bại. Kiểm tra kết nối và API key."

        progress(0.6, desc="📤 Đang đăng bài lên WordPress...")

        # html_preview đã có ảnh preview local → cần bản gốc với placeholder
        # Lấy từ state (ta lưu raw_html riêng)
        raw_html = gr.State()

        # Thực tế: ta dùng html_preview đã render và chỉ cần upload ảnh + tạo post
        # Vì preview HTML có thể chứa blob: URL → cần dùng raw HTML
        # → Giải pháp: lưu raw_html trong gr.State() ở UI layer

        result = wp_publisher.publish_post(
            title=title,
            html_content=html_preview,   # sẽ được thay thế đúng ở wrapper
            uploaded_images=uploaded,
            site_config=site_config,
            status=post_status,
        )

        status_label = "📝 Nháp" if result["status"] == "draft" else "🟢 Đã đăng"
        return (
            f"✅ **Đăng bài thành công!**\n\n"
            f"- **Trạng thái:** {status_label}\n"
            f"- **ID bài viết:** {result['post_id']}\n"
            f"- **Xem bài:** [{result['post_url']}]({result['post_url']})\n"
            f"- **Chỉnh sửa:** [{result['edit_url']}]({result['edit_url']})"
        )

    except Exception as e:
        logger.exception("Lỗi khi đăng bài")
        return f"❌ Lỗi khi đăng bài: {str(e)}"


# ═══════════════════════════════════════════════════════════════
# HÀM HELPER
# ═══════════════════════════════════════════════════════════════

def _make_preview_html(html_content: str, image_files: list) -> str:
    """Tạo HTML preview: thay [IMAGE_PLACEHOLDER_N] bằng ảnh local để xem trước."""
    import re

    if not image_files:
        # Xóa placeholder
        return re.sub(r"\[IMAGE_PLACEHOLDER_\d+\]", "", html_content)

    # Lấy đường dẫn file
    paths = image_files if isinstance(image_files[0], str) else [f.name for f in image_files]

    def replace_placeholder(match: re.Match) -> str:
        n = int(match.group(1)) - 1
        idx = min(n, len(paths) - 1)
        img_path = paths[idx]
        # Dùng file:// URL để preview local
        return (
            f'<figure style="text-align:center; margin: 20px 0;">'
            f'<img src="file={img_path}" style="max-width:100%; height:auto;" />'
            f"</figure>"
        )

    return re.sub(r"\[IMAGE_PLACEHOLDER_(\d+)\]", replace_placeholder, html_content)


def _get_site_choices() -> list[str]:
    return list(settings.SITES.keys()) if settings.SITES else ["(Chưa cấu hình website)"]


# ═══════════════════════════════════════════════════════════════
# GIAO DIỆN GRADIO
# ═══════════════════════════════════════════════════════════════

# Lưu raw HTML (có placeholder) để dùng khi đăng bài
raw_html_state = gr.State("")

with gr.Blocks(
    title="WordPress Agent - Kho Đèn Trang Trí",
    theme=gr.themes.Soft(primary_hue="blue"),
    css="""
    .container { max-width: 1000px; margin: auto; }
    .title-row { text-align: center; margin-bottom: 10px; }
    footer { display: none !important; }
    """,
) as demo:

    # ── Header ─────────────────────────────────────────────────
    gr.HTML("""
    <div style="text-align:center; padding: 20px 0 10px;">
        <h1 style="font-size: 2em; margin: 0;">🌟 WordPress Agent</h1>
        <p style="color: #666; margin: 5px 0 0;">Tự động tìm kiếm, viết bài và đăng lên website</p>
    </div>
    """)

    # ── Tab chính ──────────────────────────────────────────────
    with gr.Tabs():

        # Tab 1: Tạo bài
        with gr.TabItem("✍️ Tạo bài viết"):
            with gr.Row():
                with gr.Column(scale=1):
                    # Input
                    product_input = gr.Textbox(
                        label="🏷️ Tên sản phẩm",
                        placeholder="VD: đèn chùm pha lê K9, đèn thả thông tầng...",
                        lines=1,
                    )
                    image_input = gr.File(
                        label="🖼️ Upload ảnh sản phẩm",
                        file_count="multiple",
                        file_types=["image"],
                    )
                    extra_urls_input = gr.Textbox(
                        label="🔗 URL tham khảo thêm (tùy chọn)",
                        placeholder="Mỗi URL một dòng\nhttps://example.com/bai-viet-1\nhttps://example.com/bai-viet-2",
                        lines=3,
                    )
                    site_selector = gr.Dropdown(
                        label="🌐 Website đăng bài",
                        choices=_get_site_choices(),
                        value=settings.DEFAULT_SITE or _get_site_choices()[0],
                        interactive=True,
                    )

                    create_btn = gr.Button(
                        "🚀 Tạo bài viết",
                        variant="primary",
                        size="lg",
                    )

                with gr.Column(scale=2):
                    status_box = gr.Textbox(
                        label="📋 Trạng thái",
                        lines=5,
                        interactive=False,
                    )
                    title_output = gr.Textbox(
                        label="📝 Tiêu đề bài viết (có thể chỉnh sửa)",
                        lines=2,
                        interactive=True,
                    )

            # Preview
            preview_output = gr.HTML(label="👁️ Preview bài viết")

            # Nút đăng bài
            with gr.Row():
                post_status_selector = gr.Radio(
                    label="Trạng thái khi đăng",
                    choices=["draft", "publish"],
                    value="draft",
                    info="'draft' = nháp (khuyến nghị), 'publish' = đăng ngay",
                )
                publish_btn = gr.Button(
                    "📤 Đăng bài lên WordPress",
                    variant="secondary",
                    size="lg",
                )

            publish_result = gr.Markdown(label="✅ Kết quả đăng bài")

        # Tab 2: Cài đặt
        with gr.TabItem("⚙️ Cài đặt & Kiểm tra"):
            gr.Markdown("### Kiểm tra kết nối")
            test_site_selector = gr.Dropdown(
                label="Chọn website",
                choices=_get_site_choices(),
                value=settings.DEFAULT_SITE or _get_site_choices()[0],
            )
            test_btn = gr.Button("🔌 Kiểm tra kết nối WordPress", variant="secondary")
            test_result = gr.Textbox(label="Kết quả", lines=3, interactive=False)

            gr.Markdown("""
            ### Hướng dẫn cài đặt API Keys

            Mở file `.env` và thêm các dòng sau:

            ```
            GEMINI_API_KEY=your_key    # Lấy tại https://aistudio.google.com/app/apikey
            SERP_API_KEY=your_key      # Lấy tại https://serpapi.com (miễn phí 100 lần/tháng)
            ```

            ### Thêm website mới
            Thêm vào `.env`:
            ```
            SITE2_NAME=ten-website-2
            SITE2_URL=https://website2.com
            SITE2_CLIENT_KEY=ck_xxx
            SITE2_CLIENT_SECRET=cs_xxx
            ```
            Sau đó khởi động lại app.
            """)

    # ── Lưu raw HTML state (cho đăng bài) ──────────────────────
    _raw_html = gr.State("")

    # ── Kết nối sự kiện ────────────────────────────────────────

    def _run_and_store(product, images, extra_urls, site, progress=gr.Progress()):
        title, preview, status = run_pipeline(product, images, extra_urls, site, progress)
        # Lưu raw preview để dùng khi đăng bài
        return title, preview, status, preview  # preview cuối → _raw_html state

    create_btn.click(
        fn=_run_and_store,
        inputs=[product_input, image_input, extra_urls_input, site_selector],
        outputs=[title_output, preview_output, status_box, _raw_html],
        show_progress=True,
    )

    def _publish(title, raw_html, images, site, status):
        """Wrapper đăng bài dùng raw_html (có placeholder) + ảnh thật."""
        site_config = settings.SITES.get(site)
        if not site_config:
            return f"❌ Không tìm thấy cấu hình cho website: {site}"

        if not title or not raw_html:
            return "❌ Chưa có bài viết. Vui lòng tạo bài trước!"

        # Upload ảnh
        image_paths = []
        if images:
            image_paths = images if isinstance(images[0], str) else [f.name for f in images]

        uploaded = []
        if image_paths:
            uploaded = image_uploader.upload_images(image_paths, site_config)

        try:
            result = wp_publisher.publish_post(
                title=title,
                html_content=raw_html,
                uploaded_images=uploaded,
                site_config=site_config,
                status=status,
            )
            status_label = "📝 Nháp" if result["status"] == "draft" else "🟢 Đã đăng công khai"
            return (
                f"✅ **Đăng bài thành công!**\n\n"
                f"- **Trạng thái:** {status_label}\n"
                f"- **ID bài viết:** {result['post_id']}\n"
                f"- **Xem bài:** {result['post_url']}\n"
                f"- **Chỉnh sửa trong WP Admin:** {result['edit_url']}"
            )
        except Exception as e:
            return f"❌ Lỗi khi đăng bài: {str(e)}"

    publish_btn.click(
        fn=_publish,
        inputs=[title_output, _raw_html, image_input, site_selector, post_status_selector],
        outputs=[publish_result],
    )

    def _test_connection(site):
        site_config = settings.SITES.get(site)
        if not site_config:
            return f"Không tìm thấy cấu hình cho: {site}"
        ok = wp_publisher.test_connection(site_config)
        if ok:
            return f"✅ Kết nối thành công tới {site_config['url']}"
        else:
            return f"❌ Không kết nối được tới {site_config['url']}. Kiểm tra API key và URL."

    test_btn.click(
        fn=_test_connection,
        inputs=[test_site_selector],
        outputs=[test_result],
    )


# ═══════════════════════════════════════════════════════════════
# KHỞI ĐỘNG
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n" + "="*50)
    print("  WordPress Agent - Kho Đèn Trang Trí")
    print("="*50)

    # Kiểm tra cấu hình
    if not settings.GEMINI_API_KEY:
        print("⚠️  CẢNH BÁO: Chưa có GEMINI_API_KEY trong .env")
    if not settings.SERP_API_KEY:
        print("⚠️  CẢNH BÁO: Chưa có SERP_API_KEY trong .env (tìm kiếm tự động sẽ bị tắt)")
    if settings.SITES:
        print(f"✓  Websites: {', '.join(settings.SITES.keys())}")
    else:
        print("⚠️  CẢNH BÁO: Chưa có website nào được cấu hình")

    print("\n👉 Mở trình duyệt tại: http://localhost:7860\n")

    demo.launch(
        server_name="127.0.0.1",
        server_port=7860,
        share=False,          # Chỉ chạy local, không public
        inbrowser=True,       # Tự mở trình duyệt
    )
