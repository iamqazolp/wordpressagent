"""
core/pipeline.py
Orchestrator for running the end-to-end flow.
"""
from __future__ import annotations
import logging

from typing import Callable

from config import settings
from core import scraper, searcher, ai_writer, wp_client, taxonomy_service

logger = logging.getLogger(__name__)


def generate_articles(
    product_name: str,
    image_files: list[str] | None,
    extra_urls: list[str],
    user_notes: str,
    selected_sites: dict[str, dict],   # {site_name: site_config_dict}
    randomize_enabled: bool,
    template_content: str | None = None,
    progress_callback: Callable[[float, str], None] | None = None,
) -> dict[str, dict]:
    """
    Run full pipeline: search → scrape → AI write.
    Returns {site_name: {'title': str, 'raw_html': str}}
    """
    # Validate inputs
    if not product_name.strip():
        raise ValueError('Vui lòng nhập tên sản phẩm!')
    if not selected_sites:
        raise ValueError('Vui lòng chọn ít nhất 1 website!')
    if not settings.GEMINI_API_KEY:
        raise ValueError('Chưa cấu hình GEMINI_API_KEY. Thêm vào file .env')
    
    def _progress(val, desc):
        if progress_callback:
            progress_callback(val, desc)
    
    articles = {}
    
    # Step 1: Search
    _progress(0.1, '🔍 Đang tìm kiếm tài liệu tham khảo...')
    search_results = searcher.search_articles(product_name, extra_urls)
    
    # Step 2: Scrape
    _progress(0.25, '📄 Đang trích xuất nội dung kỹ thuật...')
    urls_to_scrape = [a['url'] for a in search_results]
    ref_contents = scraper.scrape_multiple(urls_to_scrape)
    
    image_count = len(image_files) if image_files else 0
    total_sites = len(selected_sites)
    
    # Step 3: Generate for each site
    if randomize_enabled and total_sites > 1:
        for idx, (site_name, site_config) in enumerate(selected_sites.items(), 1):
            p_val = 0.35 + (0.55 * (idx / total_sites))
            _progress(p_val, f'🤖 AI đang viết bài riêng cho {site_name} ({idx}/{total_sites})...')
            title, raw_html = ai_writer.write_post(
                product_name=product_name,
                reference_contents=ref_contents,
                image_count=image_count,
                site_name=site_name,
                user_notes=user_notes,
                variation_index=idx,
                total_variations=total_sites,
                template_content=template_content,
            )
            articles[site_name] = {'title': title, 'raw_html': raw_html}
    else:
        _progress(0.6, '🤖 AI đang viết bài...')
        first_site_name = list(selected_sites.keys())[0]
        title, raw_html = ai_writer.write_post(
            product_name=product_name,
            reference_contents=ref_contents,
            image_count=image_count,
            site_name=first_site_name,
            user_notes=user_notes,
            variation_index=0,
            total_variations=1,
            template_content=template_content,
        )
        for site_name in selected_sites:
            articles[site_name] = {'title': title, 'raw_html': raw_html}
    
    _progress(1.0, '✅ Hoàn tất!')
    return articles


def is_product_type(post_type: str) -> bool:
    """'product' / 'Sản phẩm WooCommerce' -> True; còn lại (blog) -> False."""
    t = (post_type or '').lower()
    return 'product' in t or 'sản phẩm' in t


def publish_one(
    site_name: str,
    site_config: dict,
    article_data: dict,         # {'title','raw_html','short_description'?,'category_ids'?,'tags'?,'category_scope'?}
    image_paths: list[str] | None,
    post_type: str,             # 'product' | 'post' (hoặc nhãn hiển thị tương ứng)
    post_status: str,           # 'draft' | 'publish'
    regular_price: str = "",
    sale_price: str = "",
    optimize_images: bool = True,
    remove_bg: bool = False,
    existing_wp_id: int | str | None = None,
    apply_watermark: bool = True,
) -> dict:
    """
    Đăng MỘT bài lên MỘT website: tải ảnh -> tra category/tag -> tạo sản phẩm/bài viết.
    Có `existing_wp_id` -> cập nhật bài đó trên WordPress (PUT) thay vì tạo mới.
    Không raise: lỗi đăng trả về {'success': False, 'error': ...}. Lỗi ảnh/tag chỉ là cảnh báo.
    Kết quả thành công có thêm: uploaded_count, category_warning (id danh mục đã chọn nhưng bị bỏ do
    khác loại nội dung), image_warning, taxonomy_warning.
    """
    if not site_config:
        return {'site_name': site_name, 'success': False, 'error': 'Không tìm thấy cấu hình website'}

    # Upload images if possible
    uploaded = []
    image_warning = None
    image_paths = image_paths or []
    if image_paths:
        if site_config.get('wp_user') and site_config.get('wp_app_password'):
            try:
                uploaded = wp_client.upload_images(
                    image_paths,
                    site_config,
                    optimize=optimize_images,
                    remove_bg=remove_bg,
                    apply_watermark=apply_watermark,
                )
                if not uploaded:
                    image_warning = (
                        "Tải ảnh thất bại (xem log để biết chi tiết, có thể do tên file, "
                        "dung lượng hoặc quyền WordPress Application Password)."
                    )
                elif len(uploaded) < len(image_paths):
                    image_warning = (
                        f"Chỉ tải được {len(uploaded)}/{len(image_paths)} ảnh lên WordPress "
                        "(xem log để biết chi tiết)."
                    )
            except Exception as e:
                logger.warning(f'Upload ảnh thất bại tại {site_name}: {e}')
                image_warning = f"Lỗi upload ảnh: {e}"
        else:
            image_warning = "Chưa cấu hình WordPress Username & Application Password ở tab Quản Lý Website nên chưa tải được ảnh lên WordPress."

    title = article_data.get('title', '')
    raw_html = article_data.get('raw_html', '')
    short_desc = article_data.get('short_description', '')

    # Category (id theo từng site) và tag (tên -> id, tạo nếu chưa có). Lỗi tag chỉ cảnh báo, không chặn đăng.
    category_ids = taxonomy_service.effective_category_ids(article_data, post_type)
    category_warning = None
    if article_data.get('category_ids') and not category_ids:
        category_warning = (
            "Danh mục đã chọn thuộc loại nội dung khác với loại đang đăng nên không được áp dụng. "
            "Hãy chọn lại danh mục cho đúng loại rồi đăng lại nếu cần."
        )
    tag_ids, taxonomy_warning = taxonomy_service.resolve_tag_ids(
        site_config, post_type, article_data.get('tags') or []
    )

    try:
        if is_product_type(post_type):
            res = wp_client.publish_product(
                title=title,
                html_content=raw_html,
                uploaded_images=uploaded,
                site_config=site_config,
                status=post_status,
                regular_price=regular_price,
                sale_price=sale_price,
                short_description=short_desc,
                category_ids=category_ids,
                tag_ids=tag_ids,
                existing_wp_id=existing_wp_id,
            )
        else:
            if not site_config.get('wp_user'):
                return {'site_name': site_name, 'success': False, 'error': 'Chưa cấu hình WP_USER để đăng Blog Post'}
            res = wp_client.publish_post(
                title=title, html_content=raw_html,
                uploaded_images=uploaded, site_config=site_config,
                status=post_status,
                category_ids=category_ids,
                tag_ids=tag_ids,
                existing_wp_id=existing_wp_id,
            )
        return {
            'site_name': site_name, 'success': True,
            'post_id': res.get('post_id'), 'post_url': res.get('post_url'),
            'edit_url': res.get('edit_url'), 'status': res.get('status'),
            'uploaded_count': len(uploaded),
            'image_warning': image_warning,
            'taxonomy_warning': taxonomy_warning,
            'category_warning': category_warning,
            'error': None,
        }
    except Exception as e:
        logger.exception(f'Lỗi đăng bài lên {site_name}')
        return {'site_name': site_name, 'success': False, 'error': str(e)}


def publish_articles(
    articles: dict[str, dict],       # {site_name: {'title': str, 'raw_html': str, 'short_description'?: str}}
    image_files: list[str] | None,
    site_configs: dict[str, dict],   # {site_name: decrypted site_config}
    post_type: str,                  # 'product' or 'post'
    post_status: str,                # 'draft' or 'publish'
    regular_price: str = "",
    sale_price: str = "",
    progress_callback: Callable[[float, str], None] | None = None,
    optimize_images: bool = True,
    remove_bg: bool = False,
    apply_watermark: bool = True,
) -> list[dict]:
    """
    Publish articles to WordPress sites.
    Returns list of result dicts.
    """
    results = []
    total = len(articles)

    for i, (site_name, article_data) in enumerate(articles.items(), 1):
        if progress_callback:
            progress_callback(i / total, f'📤 Đang đăng lên {site_name} ({i}/{total})...')

        results.append(publish_one(
            site_name,
            site_configs.get(site_name),
            article_data,
            image_files,
            post_type,
            post_status,
            regular_price=regular_price,
            sale_price=sale_price,
            optimize_images=optimize_images,
            remove_bg=remove_bg,
            apply_watermark=apply_watermark,
        ))

    return results
