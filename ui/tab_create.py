from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from PIL import Image
import gradio as gr

from core.image_processor import (
    process_image_batch,
    format_processing_summary,
)

logger = logging.getLogger(__name__)

def _extract_file_paths(files) -> list[str]:
    """Trích xuất danh sách đường dẫn file an toàn từ Gradio input."""
    if not files:
        return []
    paths = []
    for f in files:
        if isinstance(f, str):
            paths.append(f)
        elif hasattr(f, "name"):
            paths.append(f.name)
        else:
            paths.append(str(f))
    return paths


def run_pipeline_ui(product_name, image_files, extra_urls_text, user_notes_text, selected_sites, randomize_enabled, template_choice, progress=gr.Progress()):
    """
    Wrapper that calls core.pipeline.generate_articles().
    Gets site configs from DB, gets template content from DB if selected.
    Returns: (preview_dropdown, title, preview_html, articles_state, current_site, status_msg)
    """
    from db.database import SessionLocal
    from db import crud
    from core.pipeline import generate_articles, make_preview_html
    
    empty_dropdown = gr.Dropdown(choices=["(Chưa có bài viết)"], value="(Chưa có bài viết)")
    if not product_name.strip():
        return empty_dropdown, "", "", "", {}, "", "❌ Vui lòng nhập tên sản phẩm!"

    if not selected_sites:
        return empty_dropdown, "", "", "", {}, "", "❌ Vui lòng tích chọn ít nhất 1 website đăng bài!"

    db = SessionLocal()
    try:
        # Lấy cấu hình các site được chọn
        all_configs = crud.get_all_site_configs(db)
        selected_configs = {name: all_configs[name] for name in selected_sites if name in all_configs}
        
        # Lấy nội dung template nếu được chọn
        template_content = None
        if template_choice and template_choice != '(Mặc định)':
            templates = crud.get_all_templates(db)
            for t in templates:
                if t.name == template_choice:
                    template_content = t.content
                    break
        
        # Chạy pipeline
        image_paths = _extract_file_paths(image_files)
        extra_urls = [u.strip() for u in extra_urls_text.splitlines() if u.strip()]
        
        articles = generate_articles(
            product_name=product_name,
            image_files=image_paths if image_paths else None,
            extra_urls=extra_urls,
            user_notes=user_notes_text,
            selected_sites=selected_configs,
            randomize_enabled=randomize_enabled,
            template_content=template_content,
            progress_callback=lambda val, desc: progress(val, desc=desc),
        )
        
        if not articles:
            return empty_dropdown, "", "", "", {}, "", "❌ Không tạo được bài viết nào."

        # Thêm preview_html, product_name và short_description cho mỗi bài viết
        import re
        for site_name, art in articles.items():
            art['preview_html'] = make_preview_html(art['raw_html'], image_paths)
            art['product_name'] = product_name
            # Tự động trích xuất bảng thông số kỹ thuật cho mô tả ngắn nếu có
            table_match = re.search(r"(<table\b.*?>.*?</table>)", art['raw_html'], re.DOTALL | re.IGNORECASE)
            art['short_description'] = table_match.group(1) if table_match else ""
            
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
    except Exception as e:
        logger.exception("Lỗi trong pipeline UI")
        return empty_dropdown, "", "", "", {}, "", f"❌ Lỗi: {str(e)}"
    finally:
        db.close()


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
    Wrapper that calls core.pipeline.publish_articles().
    Also records PostHistory in DB for each result.
    """
    if not articles_state:
        return "❌ Chưa có nội dung bài viết nào để đăng! Hãy tạo bài viết trước."
        
    from db.database import SessionLocal
    from db import crud
    from core.pipeline import publish_articles
    
    db = SessionLocal()
    try:
        all_configs = crud.get_all_site_configs(db)
        image_paths = _extract_file_paths(image_files)
        
        results = publish_articles(
            articles=articles_state,
            image_files=image_paths,
            site_configs=all_configs,
            post_type=post_type,
            post_status=post_status,
            regular_price=regular_price,
            sale_price=sale_price,
            progress_callback=lambda val, desc: progress(val, desc=desc),
            optimize_images=optimize_images,
            remove_bg=remove_bg,
        )
        
        # Ghi lại lịch sử đăng bài vào CSDL
        import json
        image_paths_json = json.dumps(image_paths, ensure_ascii=False)
        for result in results:
            site = crud.get_site_by_name(db, result['site_name'])
            if site:
                article = articles_state.get(result['site_name'], {})
                prod_name = article.get('product_name') or article.get('title', '')
                is_prod = 'product' in post_type.lower() or 'sản phẩm' in post_type.lower()
                crud.create_post_history(
                    db,
                    site_id=site.id,
                    product_name=prod_name,
                    title=article.get('title', ''),
                    raw_html=article.get('raw_html', ''),
                    post_type='product' if is_prod else 'post',
                    status='published' if result['success'] else 'failed',
                    wp_post_id=str(result.get('post_id', '')) if result.get('post_id') else None,
                    wp_post_url=result.get('post_url'),
                    error_message=result.get('error'),
                    short_description=article.get('short_description', ''),
                    regular_price=regular_price,
                    sale_price=sale_price,
                    image_paths_json=image_paths_json,
                )
        
        # Định dạng kết quả thành markdown
        report = ['### 📋 Kết Quả Đăng Bài:\n']
        for r in results:
            if r['success']:
                status_lbl = '📝 Nháp' if r['status'] == 'draft' else '🟢 Công khai'
                line = f"- **{r['site_name']}**: ✅ Thành công ({status_lbl}) | [Xem]({r['post_url']}) | [Sửa]({r['edit_url']})"
                if r.get('image_warning'):
                    line += f"\n  - ⚠️ *Lưu ý về hình ảnh:* {r['image_warning']}"
                report.append(line)
            else:
                report.append(f"- **{r['site_name']}**: ❌ {r['error']}")
        return '\n\n'.join(report)
    finally:
        db.close()


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

    import json
    from db.database import SessionLocal
    from db import crud

    db = SessionLocal()
    saved_count = 0
    try:
        image_paths = _extract_file_paths(image_files)
        is_prod = 'product' in post_type.lower() or 'sản phẩm' in post_type.lower()

        for site_name, art in articles_state.items():
            site = crud.get_site_by_name(db, site_name)
            if not site:
                continue

            site_image_paths = image_paths
            # Tối ưu ảnh cho site này nếu có ảnh và bật cờ
            if optimize_images and image_paths:
                try:
                    from core.image_processor import process_image_batch
                    batch_res = process_image_batch(
                        image_paths,
                        options={
                            "max_width": 1200,
                            "max_height": 1200,
                            "format": "WEBP",
                            "quality": 85,
                            "remove_bg": remove_bg,
                            "watermark_path": site.watermark_path or None,
                            "watermark_position": site.watermark_position or "bottom-right",
                            "watermark_opacity": site.watermark_opacity or 0.7,
                        },
                    )
                    site_image_paths = [r["output_path"] for r in batch_res if r.get("output_path")] or image_paths
                except Exception as e:
                    logger.warning(f"Lỗi tối ưu ảnh khi lưu nháp cho {site_name}: {e}")
                    site_image_paths = image_paths

            site_image_paths_json = json.dumps(site_image_paths, ensure_ascii=False)
            prod_name = art.get('product_name') or art.get('title', 'Sản phẩm')
            crud.create_post_history(
                db,
                site_id=site.id,
                product_name=prod_name,
                title=art.get('title', ''),
                raw_html=art.get('raw_html', ''),
                post_type='product' if is_prod else 'post',
                status='saved',
                short_description=art.get('short_description', ''),
                regular_price=regular_price,
                sale_price=sale_price,
                image_paths_json=site_image_paths_json,
            )
            saved_count += 1

        gr.Info(f"✅ Đã lưu {saved_count} bài viết vào hệ thống!")
        return (
            f"### 💾 Đã lưu thành công {saved_count} bài viết vào hệ thống!\n\n"
            f"- **Trạng thái:** `Đã lưu nháp trên Web` (chưa đẩy lên WordPress/WooCommerce).\n"
            f"- **Hình ảnh:** Đã nạp danh sách {len(image_paths)} ảnh kèm tối ưu.\n"
            f"- **Bước tiếp theo:** Bạn có thể qua tab **📚 Kho Bài Viết & Lịch Sử** để xem lại danh sách, "
            f"chỉnh sửa bài viết hoặc bấm nút đăng lên website bất cứ khi nào bạn muốn."
        )
    except Exception as e:
        logger.exception("Lỗi khi lưu bài viết vào hệ thống")
        return f"❌ Lỗi khi lưu bài viết: {str(e)}"
    finally:
        db.close()


def handle_preview_processed_images(
    image_files,
    selected_site: str,
    do_optimize: bool,
    do_watermark: bool,
    do_remove_bg: bool,
) -> tuple:
    """Xử lý thử nghiệm ảnh và hiển thị preview kèm báo cáo nén dung lượng."""
    paths = _extract_file_paths(image_files)
    if not paths:
        return None, "❌ Vui lòng tải lên ít nhất 1 ảnh ở trên để xem trước."

    from db.database import SessionLocal
    from db import crud
    from core.image_processor import process_image_batch, format_processing_summary

    wm_path = None
    wm_pos = "bottom-right"
    wm_opacity = 0.7

    if do_watermark and selected_site:
        db = SessionLocal()
        try:
            site = crud.get_site_by_name(db, selected_site)
            if site and site.watermark_path:
                wm_path = site.watermark_path
                wm_pos = site.watermark_position or "bottom-right"
                wm_opacity = site.watermark_opacity or 0.7
        finally:
            db.close()

    results = process_image_batch(
        paths,
        options={
            "max_width": 1200 if do_optimize else 9999,
            "max_height": 1200 if do_optimize else 9999,
            "format": "WEBP" if do_optimize else "JPEG",
            "quality": 85,
            "remove_bg": do_remove_bg,
            "watermark_path": wm_path if do_watermark else None,
            "watermark_position": wm_pos,
            "watermark_opacity": wm_opacity,
        },
    )

    processed_paths = [r["output_path"] for r in results if r.get("output_path")]
    summary_md = format_processing_summary(results)
    return processed_paths if processed_paths else None, summary_md





def schedule_post_ui(
    articles_state,
    image_files,
    post_status,
    post_type,
    regular_price="",
    sale_price="",
    delay_type="Sau số phút",
    delay_value="30",
) -> str:
    """Lên lịch đăng bài tự động qua APScheduler."""
    if not articles_state:
        return "❌ Chưa có nội dung bài viết nào để lên lịch! Hãy tạo bài viết trước."

    from datetime import datetime, timedelta
    from core.scheduler import schedule_publish_job

    now = datetime.now()
    val_str = str(delay_value).strip()

    try:
        if "phút" in delay_type.lower():
            minutes = int(val_str) if val_str else 30
            if minutes < 1:
                return "❌ Số phút hẹn phải lớn hơn hoặc bằng 1."
            target_time = now + timedelta(minutes=minutes)
        elif "giờ" in delay_type.lower():
            hours = float(val_str) if val_str else 1.0
            if hours <= 0:
                return "❌ Số giờ hẹn phải lớn hơn 0."
            target_time = now + timedelta(hours=hours)
        else:
            # Parse datetime string
            target_time = datetime.strptime(val_str, "%Y-%m-%d %H:%M")
            if target_time <= now:
                return f"❌ Thời gian hẹn ({val_str}) phải ở trong tương lai (sau hiện tại: {now.strftime('%Y-%m-%d %H:%M')})."
    except Exception as e:
        return f"❌ Định dạng thời gian hẹn không hợp lệ: {e}. Ví dụ: '30' (phút), hoặc '2026-09-27 15:30'"

    image_paths = _extract_file_paths(image_files)
    first_site = list(articles_state.keys())[0]
    prod_name = articles_state[first_site].get("product_name") or articles_state[first_site].get("title", "Sản phẩm")

    try:
        job_id = schedule_publish_job(
            product_name=prod_name,
            articles=articles_state,
            site_names=list(articles_state.keys()),
            scheduled_time=target_time,
            post_type=post_type,
            post_status=post_status,
            regular_price=regular_price,
            sale_price=sale_price,
            image_files=image_paths,
        )

        sites_count = len(articles_state)
        return (
            f"### ⏰ Đặt Lịch Đăng Thành Công!\n"
            f"- **Mã lịch hẹn (Job ID):** `#{job_id}`\n"
            f"- **Sản phẩm:** {prod_name}\n"
            f"- **Thời gian đăng dự kiến:** `{target_time.strftime('%d/%m/%Y %H:%M')}`\n"
            f"- **Áp dụng cho:** {sites_count} website ({', '.join(articles_state.keys())})\n"
            f"- **Trạng thái:** Sẽ tự động đăng dưới dạng `{post_status}`\n\n"
            f"👉 *Bạn có thể theo dõi tiến độ hoặc hủy lịch bất kỳ lúc nào tại tab **📅 Lịch Đăng Bài**.*"
        )
    except Exception as e:
        logger.exception("Lỗi khi lên lịch đăng bài")
        return f"❌ Có lỗi xảy ra khi lên lịch đăng: {str(e)}"



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
        from core.pipeline import make_preview_html
        image_paths = _extract_file_paths(image_files)
        articles_state[current_site]['raw_html'] = new_html
        articles_state[current_site]['preview_html'] = make_preview_html(new_html, image_paths)
        gr.Info("✅ Đã lưu thay đổi nội dung HTML!")
    return articles_state


def build_tab_create(db_session=None) -> dict:
    """Build the create & publish tab. Returns all Gradio components that need external event wiring."""
    from db.database import SessionLocal
    from db import crud
    
    db = SessionLocal() if db_session is None else db_session
    try:
        site_names = crud.get_site_names(db)
        templates = crud.get_all_templates(db)
        template_choices = ['(Mặc định)'] + [t.name for t in templates]
    finally:
        if db_session is None:
            db.close()

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

    publish_result = gr.Markdown()

    with gr.Accordion("⏰ Lên lịch hẹn giờ đăng tự động (Post Scheduler)", open=False):
        gr.Markdown("Hẹn giờ đăng bài tự động mà không cần treo máy hoặc đăng ngay lập tức. Hệ thống sẽ tự động đăng vào thời điểm được chỉ định.")
        with gr.Row():
            schedule_type = gr.Radio(
                label="Kiểu hẹn giờ",
                choices=["Sau số phút", "Sau số giờ", "Thời gian cụ thể (YYYY-MM-DD HH:MM)"],
                value="Sau số phút",
            )
            schedule_val = gr.Textbox(
                label="Giá trị thời gian",
                value="30",
                placeholder="VD: 30 (phút), hoặc 2 (giờ), hoặc 2026-09-27 16:00",
            )
        schedule_btn = gr.Button("⏰ Xác nhận Lên Lịch Đăng", variant="primary", size="lg")
        schedule_result = gr.Markdown()

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
        'html_editor': html_editor,
        'save_html_btn': save_html_btn,
        'post_type_selector': post_type_selector,
        'post_status_selector': post_status_selector,
        'save_draft_btn': save_draft_btn,
        'publish_btn': publish_btn,
        'publish_result': publish_result,
        'schedule_type': schedule_type,
        'schedule_val': schedule_val,
        'schedule_btn': schedule_btn,
        'schedule_result': schedule_result,
        'img_optimize_chk': img_optimize_chk,
        'img_watermark_chk': img_watermark_chk,
        'img_remove_bg_chk': img_remove_bg_chk,
        'btn_preview_images': btn_preview_images,
        'processed_images_gallery': processed_images_gallery,
        'img_process_summary': img_process_summary,
    }

