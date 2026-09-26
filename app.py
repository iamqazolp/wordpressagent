"""
app.py
Giao diện chính của WordPress Agent.
Chạy lệnh: python app.py
Sau đó mở trình duyệt: http://localhost:7860
"""
import logging

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

def run_pipeline(product_name, image_files, extra_urls_text, user_notes_text, site_name, progress=gr.Progress()):
    """
    Chạy toàn bộ pipeline: tìm kiếm → đọc bài → viết AI → trả về preview.
    Returns: (title, html_preview, raw_html, status_message)
    """
    if not product_name.strip():
        return "", "", "", "❌ Vui lòng nhập tên sản phẩm!"

    if not settings.GEMINI_API_KEY:
        return "", "", "", (
            "❌ Chưa cấu hình GEMINI_API_KEY.\n"
            "Mở file .env và thêm dòng:\nGEMINI_API_KEY=your_key_here"
        )

    site_config = settings.SITES.get(site_name)
    if not site_config:
        return "", "", "", f"❌ Không tìm thấy cấu hình cho website: {site_name}"

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
        title, raw_html = ai_writer.write_post(
            product_name=product_name,
            reference_contents=ref_contents,
            image_count=image_count,
            site_name=site_name,
            user_notes=user_notes_text,
        )
        logs.append(f"🤖 Đã viết xong bài: {title}")

        # Bước 5: Tạo preview HTML
        preview_html = _make_preview_html(raw_html, image_files or [])

        progress(1.0, desc="✅ Hoàn tất!")
        status = "\n".join(logs) + "\n\n✅ Bài viết đã sẵn sàng! Kiểm tra preview bên dưới, rồi nhấn **Đăng bài**."
        return title, preview_html, raw_html, status

    except Exception as e:
        logger.exception("Lỗi trong pipeline")
        return "", "", "", f"❌ Lỗi: {str(e)}"


def publish_to_wordpress(title, raw_html, image_files, site_name, post_status, post_type="Sản phẩm WooCommerce"):
    """Upload ảnh và đăng sản phẩm hoặc bài viết lên website."""
    if not title or not raw_html:
        return "❌ Chưa có bài viết. Vui lòng tạo bài trước!"

    site_config = settings.SITES.get(site_name)
    if not site_config:
        return f"❌ Không tìm thấy cấu hình cho website: {site_name}"

    image_paths = []
    if image_files:
        image_paths = image_files if isinstance(image_files[0], str) else [f.name for f in image_files]

    uploaded = []
    if image_paths and site_config.get("wp_user"):
        uploaded = image_uploader.upload_images(image_paths, site_config)

    try:
        if "Sản phẩm" in post_type:
            result = wp_publisher.publish_product(
                title=title,
                html_content=raw_html,
                uploaded_images=uploaded,
                site_config=site_config,
                status=post_status,
            )
            type_label = "Sản phẩm WooCommerce"
        else:
            if not site_config.get("wp_user"):
                return (
                    "❌ Để đăng bài viết (Blog Post), bạn cần cấu hình WP_USER và WP_APP_PASSWORD trong .env.\n\n"
                    "💡 **Gợi ý:** Chọn mục **'Sản phẩm WooCommerce'** để đăng ngay bằng API key sẵn có."
                )
            result = wp_publisher.publish_post(
                title=title,
                html_content=raw_html,
                uploaded_images=uploaded,
                site_config=site_config,
                status=post_status,
            )
            type_label = "Bài viết Blog"

        status_label = "📝 Nháp (Draft)" if result["status"] == "draft" else "🟢 Đã xuất bản"
        return (
            f"✅ **Đăng {type_label} thành công!**\n\n"
            f"- **Trạng thái:** {status_label}\n"
            f"- **ID:** {result['post_id']}\n"
            f"- **Xem trên web:** [{result['post_url']}]({result['post_url']})\n"
            f"- **Chỉnh sửa trong Admin:** [{result['edit_url']}]({result['edit_url']})"
        )
    except Exception as e:
        logger.exception("Lỗi khi đăng bài")
        return f"❌ Lỗi khi đăng: {str(e)}"


# ═══════════════════════════════════════════════════════════════
# HELPER
# ═══════════════════════════════════════════════════════════════

def _make_preview_html(html_content, image_files):
    """Thay [IMAGE_PLACEHOLDER_N] bằng ảnh local để preview."""
    import re

    if not image_files:
        return re.sub(r"\[IMAGE_PLACEHOLDER_\d+\]", "", html_content)

    paths = image_files if (image_files and isinstance(image_files[0], str)) else [f.name for f in image_files]

    def replace_placeholder(match):
        n = int(match.group(1)) - 1
        idx = min(n, len(paths) - 1)
        return (
            f'<figure style="text-align:center;margin:20px 0;">'
            f'<img src="/file={paths[idx]}" style="max-width:100%;height:auto;" />'
            f"</figure>"
        )

    return re.sub(r"\[IMAGE_PLACEHOLDER_(\d+)\]", replace_placeholder, html_content)


def _get_site_choices():
    return list(settings.SITES.keys()) if settings.SITES else ["(Chưa cấu hình website)"]


def _test_connection(site_name):
    site_config = settings.SITES.get(site_name)
    if not site_config:
        return f"Không tìm thấy cấu hình cho: {site_name}"
    ok = wp_publisher.test_connection(site_config)
    wp_info = ""
    if site_config.get("wp_user"):
        wp_info = f"\n✅ Application Password: đã cấu hình (user: {site_config['wp_user']})"
    else:
        wp_info = "\n⚠️ WP_USER/WP_APP_PASSWORD chưa cấu hình (chưa đăng bài được)"
    if ok:
        return f"✅ Kết nối thành công tới {site_config['url']}{wp_info}"
    else:
        return f"❌ Không kết nối được tới {site_config['url']}"


# ═══════════════════════════════════════════════════════════════
# GIAO DIỆN GRADIO
# ═══════════════════════════════════════════════════════════════

with gr.Blocks(
    title="WordPress Agent - Kho Đèn Trang Trí",
) as demo:

    # State lưu raw HTML (có placeholder) dùng khi đăng bài
    raw_html_state = gr.State("")

    gr.HTML("""
    <div style="text-align:center;padding:20px 0 10px;">
        <h1 style="font-size:2em;margin:0;">🌟 WordPress Agent</h1>
        <p style="color:#666;margin:5px 0 0;">Tự động tìm kiếm, viết bài và đăng lên website</p>
    </div>
    """)

    with gr.Tabs():

        # ── Tab 1: Tạo bài ──────────────────────────────────
        with gr.TabItem("✍️ Tạo bài viết"):
            with gr.Row():
                with gr.Column(scale=1):
                    product_input = gr.Textbox(
                        label="🏷️ Tên sản phẩm",
                        placeholder="VD: đèn chùm pha lê K9, đèn thả thông tầng...",
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
                        placeholder="VD: Nhấn mạnh lõi đồng 100%, bảo hành 18 tháng, tặng kèm móc phụ, phù hợp cho xưởng mộc...",
                        lines=3,
                    )
                    site_selector = gr.Dropdown(
                        label="🌐 Website đăng bài",
                        choices=_get_site_choices(),
                        value=settings.DEFAULT_SITE or _get_site_choices()[0],
                    )
                    create_btn = gr.Button("🚀 Tạo bài viết", variant="primary", size="lg")

                with gr.Column(scale=2):
                    status_box = gr.Textbox(label="📋 Trạng thái", lines=5, interactive=False)
                    title_output = gr.Textbox(
                        label="📝 Tiêu đề bài viết (có thể chỉnh sửa)",
                        lines=2,
                        interactive=True,
                    )

            preview_output = gr.HTML(label="👁️ Preview bài viết")

            with gr.Row():
                post_type_selector = gr.Radio(
                    label="Loại nội dung đăng",
                    choices=["Sản phẩm WooCommerce", "Bài viết Blog"],
                    value="Sản phẩm WooCommerce",
                    info="Sản phẩm dùng API Key có sẵn trong .env (không cần Application Password)",
                )
                post_status_selector = gr.Radio(
                    label="Trạng thái khi đăng",
                    choices=["draft", "publish"],
                    value="draft",
                    info="'draft' = nháp (khuyến nghị), 'publish' = công khai ngay",
                )
                publish_btn = gr.Button("📤 Đăng lên Website", variant="secondary", size="lg")

            publish_result = gr.Markdown()

        # ── Tab 2: Kiểm tra ─────────────────────────────────
        with gr.TabItem("⚙️ Cài đặt & Kiểm tra"):
            gr.Markdown("### Kiểm tra kết nối")
            test_site_selector = gr.Dropdown(
                label="Chọn website",
                choices=_get_site_choices(),
                value=settings.DEFAULT_SITE or _get_site_choices()[0],
            )
            test_btn = gr.Button("🔌 Kiểm tra kết nối WordPress", variant="secondary")
            test_result = gr.Textbox(label="Kết quả", lines=4, interactive=False)

            gr.Markdown("""
### Hướng dẫn thêm API Keys vào `.env`

```
GEMINI_API_KEY=...        # https://aistudio.google.com/app/apikey (miễn phí)
SERP_API_KEY=...          # https://serpapi.com (miễn phí 100 lần/tháng)
WP_USER=admin             # Tên đăng nhập WordPress
WP_APP_PASSWORD=xxxx xxxx xxxx xxxx    # Tạo tại WP Admin → Users → Profile → Application Passwords
```

### Thêm website mới vào `.env`
```
SITE2_NAME=ten-website-2
SITE2_URL=https://website2.com
SITE2_CLIENT_KEY=ck_xxx
SITE2_CLIENT_SECRET=cs_xxx
SITE2_WP_USER=admin
SITE2_WP_APP_PASSWORD=xxxx xxxx
```
Sau đó khởi động lại app.
            """)

    # ── Kết nối sự kiện ─────────────────────────────────────

    def _on_create(product, images, extra_urls, user_notes, site, progress=gr.Progress()):
        title, preview, raw_html, status = run_pipeline(product, images, extra_urls, user_notes, site, progress)
        return title, preview, raw_html, status

    create_btn.click(
        fn=_on_create,
        inputs=[product_input, image_input, extra_urls_input, user_notes_input, site_selector],
        outputs=[title_output, preview_output, raw_html_state, status_box],
        show_progress=True,
    )

    publish_btn.click(
        fn=publish_to_wordpress,
        inputs=[title_output, raw_html_state, image_input, site_selector, post_status_selector, post_type_selector],
        outputs=[publish_result],
    )

    test_btn.click(
        fn=_test_connection,
        inputs=[test_site_selector],
        outputs=[test_result],
    )


# ═══════════════════════════════════════════════════════════════
# KHỞI ĐỘNG
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n" + "=" * 50)
    print("  WordPress Agent - Kho Đèn Trang Trí")
    print("=" * 50)

    if not settings.GEMINI_API_KEY:
        print("⚠️  CẢNH BÁO: Chưa có GEMINI_API_KEY trong .env")
    if not settings.SERP_API_KEY:
        print("⚠️  CẢNH BÁO: Chưa có SERP_API_KEY (tìm kiếm tự động bị tắt)")
    if settings.SITES:
        site = settings.SITES.get(settings.DEFAULT_SITE, {})
        wp_status = "✓ Đã cấu hình" if site.get("wp_user") else "⚠ Chưa cấu hình (chưa đăng bài được)"
        print(f"✓  Website: {', '.join(settings.SITES.keys())}")
        print(f"   Application Password: {wp_status}")
    else:
        print("⚠️  CẢNH BÁO: Chưa có website nào được cấu hình")

    print("\n👉 Mở trình duyệt tại: http://localhost:7860\n")

    demo.launch(
        server_name="127.0.0.1",
        server_port=7860,
        share=False,
        inbrowser=True,
        theme=gr.themes.Soft(primary_hue="blue"),
    )
