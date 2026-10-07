"""
core/pipeline.py
Orchestrator for running the end-to-end flow.
"""
from __future__ import annotations
from datetime import datetime
import concurrent.futures
import logging
import threading

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
        site_items = list(enumerate(selected_sites.items(), 1))
        progress_lock = threading.Lock()
        completed_sites = 0

        def _write_for_site(idx: int, site_name: str, site_config: dict) -> tuple[str, dict]:
            nonlocal completed_sites
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
            with progress_lock:
                completed_sites += 1
                p_val = 0.35 + (0.55 * (completed_sites / total_sites))
                _progress(p_val, f'🤖 AI đang viết bài riêng cho {site_name} ({completed_sites}/{total_sites})...')
            return site_name, {'title': title, 'raw_html': raw_html}

        with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, total_sites)) as executor:
            future_to_site = [
                executor.submit(_write_for_site, idx, s_name, s_cfg)
                for idx, (s_name, s_cfg) in site_items
            ]
            for fut in future_to_site:
                s_name, art_dict = fut.result()
                articles[s_name] = art_dict
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
    scheduled_time: datetime | None = None,
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
        profile_problem = wp_client.check_wp_credentials(site_config)
        if profile_problem:
            image_warning = f"ẢNH CHƯA ĐƯỢC TẢI LÊN ({len(image_paths)} ảnh): {profile_problem}."
        else:
            upload_errors: list[str] = []
            try:
                uploaded = wp_client.upload_images(
                    image_paths,
                    site_config,
                    optimize=optimize_images,
                    remove_bg=remove_bg,
                    apply_watermark=apply_watermark,
                    errors=upload_errors,
                )
                reasons = "; ".join(upload_errors[:3]) or "xem log để biết chi tiết"
                if not uploaded:
                    image_warning = f"Tải ảnh thất bại: {reasons}"
                elif len(uploaded) < len(image_paths):
                    image_warning = f"Chỉ tải được {len(uploaded)}/{len(image_paths)} ảnh lên WordPress: {reasons}"
            except Exception as e:
                logger.warning(f'Upload ảnh thất bại tại {site_name}: {e}')
                image_warning = f"Lỗi upload ảnh: {e}"

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
                scheduled_time=scheduled_time,
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
                scheduled_time=scheduled_time,
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
    scheduled_time: datetime | None = None,
) -> list[dict]:
    """
    Publish articles to WordPress sites.
    Returns list of result dicts.
    """
    if not articles:
        return []

    total = len(articles)
    progress_lock = threading.Lock()
    completed = 0

    def _publish_worker(site_name: str, article_data: dict) -> dict:
        nonlocal completed
        site_cfg = site_configs.get(site_name) if site_configs else None
        res = publish_one(
            site_name,
            site_cfg,
            article_data,
            image_files,
            post_type,
            post_status,
            regular_price=regular_price,
            sale_price=sale_price,
            optimize_images=optimize_images,
            remove_bg=remove_bg,
            apply_watermark=apply_watermark,
            scheduled_time=scheduled_time,
        )
        if progress_callback:
            with progress_lock:
                completed += 1
                progress_callback(completed / total, f'📤 Đang đăng lên {site_name} ({completed}/{total})...')
        return res

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, total)) as executor:
        future_to_site = [
            executor.submit(_publish_worker, site_name, articles[site_name])
            for site_name in articles.keys()
        ]
        results = [fut.result() for fut in future_to_site]

    return results
