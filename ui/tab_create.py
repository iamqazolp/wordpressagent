from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any
import gradio as gr

from core.image_processor import format_processing_summary
from core.timeutil import now_vn, to_vn_naive, VN_TZ, TZ_LABEL, TZ_NAME
from services import generation as generation_service
from services import images as image_service
from services import publishing as publishing_service
from services import schedules as schedule_service
from services import sites as site_service
from services import templates as template_service
from services.errors import ServiceError
from ui.preview import make_preview_html
from ui.common import extract_file_paths
from ui.seo_panel import EMPTY_PANEL as EMPTY_SEO_PANEL

logger = logging.getLogger(__name__)

def run_pipeline_ui(product_name, image_files, extra_urls_text, user_notes_text, selected_sites, randomize_enabled, template_choice, progress=gr.Progress()):
    """
    Wrapper that calls services.generation.generate_for_sites().
    Returns: (preview_dropdown, title, short_description, preview_html, articles_state, current_site, status_msg)
    """
    empty_dropdown = gr.Dropdown(choices=["(Chưa có bài viết)"], value="(Chưa có bài viết)")
    try:
        image_paths = extract_file_paths(image_files)
        articles = generation_service.generate_for_sites(
            product_name=product_name,
            site_names=selected_sites,
            image_paths=image_paths,
            extra_urls=[u.strip() for u in extra_urls_text.splitlines() if u.strip()],
            user_notes=user_notes_text,
            randomize=randomize_enabled,
            template_name=template_choice,
            progress=lambda val, desc: progress(val, desc=desc),
        )

        # Bản xem trước (đường dẫn ảnh kiểu Gradio) chỉ là chuyện hiển thị nên làm ở lớp UI
        for art in articles.values():
            art['preview_html'] = make_preview_html(art['raw_html'], image_paths)

        # Dữ liệu cho trang xem trước đầu tiên
        first_site = list(articles.keys())[0]
        first_article = articles[first_site]

        updated_dropdown = gr.Dropdown(
            choices=selected_sites,
            value=first_site,
            interactive=True,
        )

        status_msg = f"✅ Đã tạo xong nội dung cho {len(selected_sites)} website! Bạn có thể chọn từng website ở ô bên dưới để xem trước hoặc chỉnh sửa trước khi đăng."

        return (
            updated_dropdown,
            first_article.get("title", ""),
            first_article.get("short_description", ""),
            first_article.get("preview_html", ""),
            articles,
            first_site,
            status_msg,
        )
    except ServiceError as e:
        return empty_dropdown, "", "", "", {}, "", f"❌ {e.message}"
    except Exception as e:
        logger.exception("Lỗi trong pipeline UI")
        return empty_dropdown, "", "", "", {}, "", f"❌ Lỗi: {str(e)}"


def publish_to_sites_ui(
    articles_state,
    image_files,
    post_status,
    post_type,
    regular_price="",
    sale_price="",
    optimize_images: bool = True,
    remove_bg: bool = False,
    progress=gr.Progress(),
):
    """
    Wrapper that calls services.publishing.publish_and_record(): đăng lên các website và ghi PostHistory.
    """
    if not articles_state:
        return "❌ Chưa có nội dung bài viết nào để đăng! Hãy tạo bài viết trước."

    results = publishing_service.publish_and_record(
        articles=articles_state,
        image_paths=extract_file_paths(image_files),
        post_type=post_type,
        post_status=post_status,
        regular_price=regular_price,
        sale_price=sale_price,
        optimize_images=optimize_images,
        remove_bg=remove_bg,
        progress=lambda val, desc: progress(val, desc=desc),
    )

    # Định dạng kết quả thành markdown
    report = ['### 📋 Kết Quả Đăng Bài:\n']
    for r in results:
        if r['success']:
            status_lbl = '📝 Nháp' if r['status'] == 'draft' else '🟢 Công khai'
            line = f"- **{r['site_name']}**: ✅ Thành công ({status_lbl}) | [Xem]({r['post_url']}) | [Sửa]({r['edit_url']})"
            if r.get('image_warning'):
                line += f"\n  - ⚠️ *Lưu ý về hình ảnh:* {r['image_warning']}"
            if r.get('taxonomy_warning'):
                line += f"\n  - ⚠️ *Lưu ý về tag:* {r['taxonomy_warning']}"
            if r.get('category_warning'):
                line += f"\n  - ⚠️ *Lưu ý về danh mục:* {r['category_warning']}"
            report.append(line)
        else:
            report.append(f"- **{r['site_name']}**: ❌ {r['error']}")
    return '\n\n'.join(report)


def save_draft_articles_ui(
    articles_state,
    image_files,
    post_type,
    regular_price="",
    sale_price="",
    optimize_images: bool = True,
    remove_bg: bool = False,
):
    """
    Lưu toàn bộ bài viết đã tạo vào hệ thống (bảng PostHistory) với trạng thái 'saved'.
    Tự động tối ưu WebP và gắn watermark theo từng website nếu được chọn.
    """
    if not articles_state:
        return "❌ Chưa có nội dung bài viết nào để lưu! Hãy bấm '🚀 Tạo bài viết' trước."

    try:
        res = publishing_service.save_drafts(
            articles_state,
            extract_file_paths(image_files),
            post_type,
            regular_price,
            sale_price,
            optimize_images=optimize_images,
            remove_bg=remove_bg,
        )
    except Exception as e:
        logger.exception("Lỗi khi lưu bài viết vào hệ thống")
        return f"❌ Lỗi khi lưu bài viết: {str(e)}"

    gr.Info(f"✅ Đã lưu {res.saved_count} bài viết vào hệ thống!")
    return (
        f"### 💾 Đã lưu thành công {res.saved_count} bài viết vào hệ thống!\n\n"
        f"- **Trạng thái:** `Đã lưu nháp trên Web` (chưa đẩy lên WordPress/WooCommerce).\n"
        f"- **Hình ảnh:** Đã nạp danh sách {res.image_count} ảnh kèm tối ưu.\n"
        f"- **Bước tiếp theo:** Bạn có thể qua tab **📚 Kho Bài Viết & Lịch Sử** để xem lại danh sách, "
        f"chỉnh sửa bài viết hoặc bấm nút đăng lên website bất cứ khi nào bạn muốn."
    )


def handle_preview_processed_images(
    image_files,
    selected_site: str,
    do_optimize: bool,
    do_watermark: bool,
    do_remove_bg: bool,
) -> tuple:
    """Xử lý thử nghiệm ảnh và hiển thị preview kèm báo cáo nén dung lượng."""
    paths = extract_file_paths(image_files)
    if not paths:
        return None, "❌ Vui lòng tải lên ít nhất 1 ảnh ở trên để xem trước."

    processed_paths, results = image_service.preview_processed(
        paths, selected_site, do_optimize, do_watermark, do_remove_bg
    )
    return processed_paths if processed_paths else None, format_processing_summary(results)


def parse_scheduled_datetime(val: Any) -> datetime | None:
    """Chuyển đổi linh hoạt các định dạng ngày giờ sang datetime object."""
    if val is None:
        return None
    if isinstance(val, datetime):
        return to_vn_naive(val)
    if isinstance(val, (int, float)):
        return to_vn_naive(datetime.fromtimestamp(val, VN_TZ))
    if isinstance(val, str):
        val = val.strip()
        if not val:
            return None
        for fmt in (
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M",
            "%d/%m/%Y %H:%M",
            "%d/%m/%Y %H:%M:%S",
        ):
            try:
                return datetime.strptime(val, fmt)
            except ValueError:
                continue
    return None


def format_time_preview(dt_val: Any) -> str:
    """Tạo dòng thông báo thời gian dự kiến đăng bài thân thiện với người dùng."""
    dt = parse_scheduled_datetime(dt_val)
    if not dt:
        return "⚠️ *Chưa chọn thời gian hợp lệ.*"
    now = now_vn()
    if dt <= now:
        return f"⚠️ **Thời gian đã qua hoặc quá gần hiện tại:** `{dt.strftime('%d/%m/%Y %H:%M')} ({TZ_LABEL})`. Vui lòng chọn thời điểm trong tương lai."
    diff = dt - now
    total_seconds = int(diff.total_seconds())
    days = total_seconds // 86400
    hours = (total_seconds % 86400) // 3600
    minutes = (total_seconds % 3600) // 60

    parts = []
    if days > 0:
        parts.append(f"{days} ngày")
    if hours > 0:
        parts.append(f"{hours} giờ")
    if minutes > 0 or not parts:
        parts.append(f"{minutes} phút")
    human_diff = " ".join(parts)

    weekday_names = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]
    weekday = weekday_names[dt.weekday()]
    return f"🕒 **Dự kiến đăng vào:** `{dt.strftime('%H:%M')} ({TZ_LABEL}) - {weekday}, ngày {dt.strftime('%d/%m/%Y')}` *(sau khoảng {human_diff} nữa)*"


def set_quick_schedule(preset_type: str) -> tuple[datetime, str]:
    """Tính toán mốc thời gian đăng nhanh và trả về datetime cùng chuỗi diễn giải."""
    now = now_vn()
    if preset_type == "30m":
        target = now + timedelta(minutes=30)
    elif preset_type == "1h":
        target = now + timedelta(hours=1)
    elif preset_type == "2h":
        target = now + timedelta(hours=2)
    elif preset_type == "tomorrow_8am":
        tomorrow = now + timedelta(days=1)
        target = tomorrow.replace(hour=8, minute=0, second=0, microsecond=0)
    elif preset_type == "tomorrow_14pm":
        tomorrow = now + timedelta(days=1)
        target = tomorrow.replace(hour=14, minute=0, second=0, microsecond=0)
    elif preset_type == "tomorrow_20pm":
        tomorrow = now + timedelta(days=1)
        target = tomorrow.replace(hour=20, minute=0, second=0, microsecond=0)
    else:
        target = now + timedelta(hours=1)
    return target, format_time_preview(target)


def schedule_post_ui(
    articles_state,
    image_files,
    post_status,
    post_type,
    regular_price="",
    sale_price="",
    scheduled_datetime=None,
) -> str:
    """Lên lịch đăng bài tự động qua APScheduler bằng bộ chọn ngày giờ trực quan."""
    if not articles_state:
        return "❌ Chưa có nội dung bài viết nào để lên lịch! Hãy tạo bài viết trước."

    target_time = parse_scheduled_datetime(scheduled_datetime)
    if not target_time:
        return "❌ Vui lòng chọn ngày và giờ đăng bài hợp lệ."

    try:
        res = schedule_service.schedule_post(
            articles=articles_state,
            image_paths=extract_file_paths(image_files),
            post_status=post_status,
            post_type=post_type,
            scheduled_time=target_time,
            regular_price=regular_price,
            sale_price=sale_price,
        )
    except ServiceError as e:
        return f"❌ {e}"
    except Exception as e:
        logger.exception("Lỗi khi lên lịch đăng bài")
        return f"❌ Có lỗi xảy ra khi lên lịch đăng: {str(e)}"

    weekday_names = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]
    weekday = weekday_names[res.scheduled_time.weekday()]
    return (
        f"### ⏰ Đặt Lịch Đăng Thành Công!\n"
        f"- **Mã lịch hẹn (Job ID):** `#{res.job_id}`\n"
        f"- **Sản phẩm:** {res.product_name}\n"
        f"- **Thời gian đăng dự kiến:** `{res.scheduled_time.strftime('%H:%M')} ({TZ_LABEL}) - {weekday}, ngày {res.scheduled_time.strftime('%d/%m/%Y')}`\n"
        f"- **Áp dụng cho:** {len(res.site_names)} website ({', '.join(res.site_names)})\n"
        f"- **Trạng thái:** Sẽ tự động đăng dưới dạng `{res.post_status}`\n\n"
        f"👉 *Bạn có thể theo dõi tiến độ hoặc hủy lịch bất kỳ lúc nào tại tab **📅 Lịch Đăng Bài**.*"
    )


def on_change_preview_site(selected_site, articles_state, edit_mode_active):
    """Khi đổi dropdown xem trước của site nào."""
    if not articles_state or selected_site not in articles_state:
        return "", "", "", "", selected_site
    art = articles_state[selected_site]
    short_desc = art.get("short_description", "")
    if edit_mode_active:
        return art.get("title", ""), short_desc, gr.update(visible=False), gr.update(visible=True, value=art.get("raw_html", "")), selected_site
    else:
        return art.get("title", ""), short_desc, gr.update(visible=True, value=art.get("preview_html", "")), gr.update(visible=False), selected_site


def on_edit_title(new_title, current_site, articles_state):
    """Khi người dùng chỉnh sửa tiêu đề của website hiện tại."""
    if articles_state and current_site in articles_state:
        articles_state[current_site]["title"] = new_title
    return articles_state


def on_edit_short_desc(new_short_desc, current_site, articles_state):
    """Khi người dùng chỉnh sửa mô tả ngắn của website hiện tại."""
    if articles_state and current_site in articles_state:
        articles_state[current_site]["short_description"] = new_short_desc
    return articles_state


def on_toggle_edit_mode(edit_mode_active, current_site, articles_state):
    """Chuyển đổi giữa chế độ xem trước (Preview) và trình sửa mã HTML."""
    new_mode = not bool(edit_mode_active)
    if not articles_state or current_site not in articles_state:
        return (
            gr.update(visible=not new_mode),
            gr.update(visible=new_mode),
            gr.update(visible=new_mode),
            new_mode,
        )
    art = articles_state[current_site]
    if new_mode:
        # Chuyển SANG chế độ edit: ẩn preview, hiện code editor với raw_html, hiện nút Lưu
        return (
            gr.update(visible=False),
            gr.update(visible=True, value=art.get('raw_html', '')),
            gr.update(visible=True),
            new_mode,
        )
    else:
        # Chuyển VỀ chế độ preview: hiện preview_html, ẩn code editor, ẩn nút Lưu
        return (
            gr.update(visible=True, value=art.get('preview_html', '')),
            gr.update(visible=False),
            gr.update(visible=False),
            new_mode,
        )


def on_save_html_edit(new_html, current_site, articles_state, image_files):
    """Lưu mã HTML đã sửa vào articles_state và cập nhật lại bản preview."""
    if articles_state and current_site in articles_state:
        image_paths = extract_file_paths(image_files)
        articles_state[current_site]['raw_html'] = new_html
        articles_state[current_site]['preview_html'] = make_preview_html(new_html, image_paths)
        gr.Info("✅ Đã lưu thay đổi nội dung HTML!")
    return articles_state


def build_tab_create(db_session=None) -> dict:
    """Build the create & publish tab. Returns all Gradio components that need external event wiring."""
    site_names = site_service.list_site_names()
    template_choices = [template_service.DEFAULT_CHOICE] + template_service.list_template_names()

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

            with gr.Accordion("🖼️ Tùy Chọn Tối Ưu Hình Ảnh (Phase 3)", open=False):
                img_optimize_chk = gr.Checkbox(
                    label="⚡ Chuẩn hóa & Nén WebP (max 1200px, giảm 60-80% dung lượng)",
                    value=True,
                )
                img_watermark_chk = gr.Checkbox(
                    label="🏷️ Tự động đóng dấu Watermark logo website",
                    value=True,
                    info="Lấy logo và vị trí đã cấu hình ở tab Quản Lý Website.",
                )
                img_remove_bg_chk = gr.Checkbox(
                    label="✨ Tách nền sản phẩm (Xóa phông rembg)",
                    value=False,
                    info="Chạy local trên máy (yêu cầu cài đặt rembg).",
                )
                btn_preview_images = gr.Button("👁️ Xử lý thử & Xem trước ảnh đã tối ưu", variant="secondary", size="sm")
                processed_images_gallery = gr.Gallery(
                    label="Xem trước ảnh sau khi tối ưu & đóng watermark",
                    columns=4,
                    rows=1,
                    height=130,
                    interactive=False,
                )
                img_process_summary = gr.Markdown("")
            extra_urls_input = gr.Textbox(
                label="🔗 URL tham khảo thêm (tùy chọn)",
                placeholder="Mỗi URL một dòng\nhttps://example.com/bai-viet-1",
                lines=2,
            )
            user_notes_input = gr.Textbox(
                label="💡 Mô tả / Thông số kỹ thuật / Gợi ý riêng cho AI (Tùy chọn)",
                placeholder="VD: Dán thông số kỹ thuật, mô tả chi tiết từ nhà cung cấp, hoặc ghi chú riêng (lõi đồng 100%, bảo hành 24 tháng...)",
                lines=3,
            )
            
            template_selector = gr.Dropdown(
                label="📄 Chọn mẫu Prompt (Template)",
                choices=template_choices,
                value="(Mặc định)",
            )

            sites_selector = gr.CheckboxGroup(
                label="🌐 Chọn các website đăng bài (chọn nhiều)",
                choices=site_names,
                value=site_names,
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
                    choices=site_names,
                    value=site_names[0] if site_names else None,
                    interactive=True,
                )
                title_output = gr.Textbox(
                    label="📝 Tiêu đề sản phẩm cho website này (có thể chỉnh sửa)",
                    lines=1,
                    interactive=True,
                )
                
                short_desc_editor = gr.Code(
                    label="📑 Mô tả ngắn sản phẩm (HTML - mặc định tự động lấy bảng thông số)",
                    language="html",
                    lines=4,
                    interactive=True,
                )

                seo_panel = gr.HTML(value=EMPTY_SEO_PANEL, label="Điểm SEO")

                with gr.Group():
                    gr.Markdown("**🏷️ Danh mục & Tag cho website đang xem** *(mỗi website có danh mục riêng)*")
                    category_dropdown = gr.Dropdown(
                        label="Danh mục (Category)",
                        choices=[],
                        value=[],
                        multiselect=True,
                        interactive=True,
                        info="Tối đa nên chọn 1–2 danh mục. Danh sách lấy từ website (bấm 🔄 nếu thiếu).",
                    )
                    tags_input = gr.Textbox(
                        label="Tag (cách nhau bằng dấu phẩy)",
                        placeholder="VD: quạt công nghiệp, quạt hút xưởng",
                        lines=1,
                        info="Tag chưa có trên website sẽ được tạo tự động khi đăng.",
                    )
                    with gr.Row():
                        btn_ai_taxonomy = gr.Button("🤖 AI gợi ý danh mục & tag", size="sm")
                        btn_sync_categories = gr.Button("🔄 Làm mới danh mục", size="sm")
                    taxonomy_status = gr.Markdown(value="ℹ️ Tạo bài viết trước để chọn danh mục và tag.")

                with gr.Row():
                    toggle_edit_btn = gr.Button("🔄 Chuyển đổi chế độ (Xem / Chỉnh sửa HTML)")
                
                edit_mode_state = gr.State(False)
                
                preview_output = gr.HTML(label="Nội dung bài viết", visible=True)
                
                html_editor = gr.Code(label="Chỉnh sửa mã HTML", language="html", visible=False, interactive=True)
                save_html_btn = gr.Button("💾 Lưu mã HTML đã sửa", visible=False)

    with gr.Row():
        regular_price_input = gr.Textbox(
            label="💵 Giá gốc (Regular Price - VNĐ)",
            placeholder="VD: 5500000 hoặc 5.500.000",
            lines=1,
        )
        sale_price_input = gr.Textbox(
            label="🏷️ Giá khuyến mại (Sale Price - VNĐ, tùy chọn)",
            placeholder="VD: 4900000 hoặc 4.900.000 (để trống nếu không giảm)",
            lines=1,
        )

    with gr.Row():
        post_type_selector = gr.Radio(
            label="Loại nội dung đăng",
            choices=["Sản phẩm WooCommerce", "Bài viết Blog"],
            value="Sản phẩm WooCommerce",
            info="Đăng bài hoặc sản phẩm (lưu ý: để tải ảnh lên website, cần có Application Password ở tab Quản Lý Website)",
        )
        post_status_selector = gr.Radio(
            label="Trạng thái khi đăng",
            choices=["draft", "publish"],
            value="draft",
            info="'draft' = lưu nháp (khuyến nghị), 'publish' = công khai ngay",
        )
    with gr.Row():
        save_draft_btn = gr.Button("💾 Lưu bài vào hệ thống (Không đăng ngay)", variant="primary", size="lg")
        publish_btn = gr.Button("📤 Đăng lên tất cả các website đã chọn", variant="secondary", size="lg")
    check_dup_btn = gr.Button("🔍 Kiểm tra bài trùng trên website (chỉ đọc)", size="sm")
    dup_result = gr.Markdown()

    publish_result = gr.Markdown()

    with gr.Accordion("⏰ Lên lịch hẹn giờ đăng tự động (Post Scheduler)", open=False):
        gr.Markdown(
            "Hẹn giờ đăng bài tự động mà không cần treo máy hoặc đăng ngay lập tức. "
            "Bạn có thể chọn nhanh các mốc thời gian phổ biến hoặc chọn trực tiếp ngày & giờ trên giao diện lịch."
        )
        gr.Markdown("**⚡ Chọn nhanh mốc thời gian:**")
        with gr.Row():
            btn_quick_30m = gr.Button("⚡ +30 phút", size="sm")
            btn_quick_1h = gr.Button("⚡ +1 giờ", size="sm")
            btn_quick_2h = gr.Button("⚡ +2 giờ", size="sm")
            btn_quick_tomorrow_8am = gr.Button("🌅 Sáng mai (08:00)", size="sm")
            btn_quick_tomorrow_14pm = gr.Button("☀️ Chiều mai (14:00)", size="sm")
            btn_quick_tomorrow_20pm = gr.Button("🌙 Tối mai (20:00)", size="sm")

        with gr.Row():
            default_init_time = now_vn() + timedelta(hours=1)
            schedule_datetime_picker = gr.DateTime(
                label=f"📅 Chọn ngày & giờ đăng bài ({TZ_LABEL} · Giờ Việt Nam)",
                type="datetime",
                timezone=TZ_NAME,
                value=default_init_time,
                include_time=True,
            )

        schedule_time_preview = gr.Markdown(
            value=format_time_preview(default_init_time)
        )

        schedule_btn = gr.Button("⏰ Xác nhận Lên Lịch Đăng", variant="primary", size="lg")
        schedule_result = gr.Markdown()

    # Sự kiện chọn nhanh lịch hẹn & tương tác DateTime picker
    btn_quick_30m.click(
        fn=lambda: set_quick_schedule("30m"),
        outputs=[schedule_datetime_picker, schedule_time_preview],
    )
    btn_quick_1h.click(
        fn=lambda: set_quick_schedule("1h"),
        outputs=[schedule_datetime_picker, schedule_time_preview],
    )
    btn_quick_2h.click(
        fn=lambda: set_quick_schedule("2h"),
        outputs=[schedule_datetime_picker, schedule_time_preview],
    )
    btn_quick_tomorrow_8am.click(
        fn=lambda: set_quick_schedule("tomorrow_8am"),
        outputs=[schedule_datetime_picker, schedule_time_preview],
    )
    btn_quick_tomorrow_14pm.click(
        fn=lambda: set_quick_schedule("tomorrow_14pm"),
        outputs=[schedule_datetime_picker, schedule_time_preview],
    )
    btn_quick_tomorrow_20pm.click(
        fn=lambda: set_quick_schedule("tomorrow_20pm"),
        outputs=[schedule_datetime_picker, schedule_time_preview],
    )
    schedule_datetime_picker.change(
        fn=format_time_preview,
        inputs=[schedule_datetime_picker],
        outputs=[schedule_time_preview],
    )

    # Sự kiện xem trước ảnh đã tối ưu & đóng watermark
    btn_preview_images.click(
        fn=handle_preview_processed_images,
        inputs=[
            image_input,
            preview_site_selector,
            img_optimize_chk,
            img_watermark_chk,
            img_remove_bg_chk,
        ],
        outputs=[
            processed_images_gallery,
            img_process_summary,
        ],
    )

    return {
        'product_input': product_input,
        'image_input': image_input,
        'extra_urls_input': extra_urls_input,
        'user_notes_input': user_notes_input,
        'template_selector': template_selector,
        'sites_selector': sites_selector,
        'randomize_checkbox': randomize_checkbox,
        'create_btn': create_btn,
        'status_box': status_box,
        'preview_site_selector': preview_site_selector,
        'title_output': title_output,
        'short_desc_editor': short_desc_editor,
        'regular_price_input': regular_price_input,
        'sale_price_input': sale_price_input,
        'toggle_edit_btn': toggle_edit_btn,
        'edit_mode_state': edit_mode_state,
        'preview_output': preview_output,
        'seo_panel': seo_panel,
        'category_dropdown': category_dropdown,
        'tags_input': tags_input,
        'btn_ai_taxonomy': btn_ai_taxonomy,
        'btn_sync_categories': btn_sync_categories,
        'taxonomy_status': taxonomy_status,
        'html_editor': html_editor,
        'save_html_btn': save_html_btn,
        'post_type_selector': post_type_selector,
        'post_status_selector': post_status_selector,
        'save_draft_btn': save_draft_btn,
        'publish_btn': publish_btn,
        'check_dup_btn': check_dup_btn,
        'dup_result': dup_result,
        'publish_result': publish_result,
        'schedule_datetime_picker': schedule_datetime_picker,
        'schedule_btn': schedule_btn,
        'schedule_result': schedule_result,
        'img_optimize_chk': img_optimize_chk,
        'img_watermark_chk': img_watermark_chk,
        'img_remove_bg_chk': img_remove_bg_chk,
        'btn_preview_images': btn_preview_images,
        'processed_images_gallery': processed_images_gallery,
        'img_process_summary': img_process_summary,
    }

