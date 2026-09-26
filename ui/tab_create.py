from __future__ import annotations

import logging
import gradio as gr

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


def publish_to_sites_ui(articles_state, image_files, post_status, post_type, regular_price="", sale_price="", progress=gr.Progress()):
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
        )
        
        # Ghi lại lịch sử đăng bài vào CSDL
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
        publish_btn = gr.Button("📤 Đăng lên tất cả các website đã chọn", variant="secondary", size="lg")

    publish_result = gr.Markdown()

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
        'publish_btn': publish_btn,
        'publish_result': publish_result,
    }
