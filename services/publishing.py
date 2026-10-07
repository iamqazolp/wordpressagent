"""
services/publishing.py — đăng bài lên website và ghi lịch sử (PostHistory); lưu nháp vào Kho bài viết.

Dùng chung cho: Đăng ngay, Lưu nháp, Tạo hàng loạt. (Job hẹn giờ ở core/scheduler.py ghi lịch sử tương tự.)
`articles` có dạng {site: {title, raw_html, short_description, product_name, category_ids, tags, category_scope}}.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass

from core import pipeline, taxonomy_service
from db import crud
from db.database import session_scope
from services import images as image_service
from services import sites as site_service
from services import taxonomy as taxonomy_svc

logger = logging.getLogger(__name__)

Progress = Callable[[float, str], None]


@dataclass(frozen=True)
class SaveDraftsResult:
    saved_count: int
    image_count: int
    saved: tuple[tuple[str, int], ...] = ()   # (tên website, id bài trong kho)


def _record(db, site, article: dict, post_type: str, status: str, regular_price: str, sale_price: str,
            image_paths: list[str], default_name: str, result: dict | None = None) -> int | None:
    """Ghi một dòng PostHistory từ bài + (nếu có) kết quả đăng."""
    result = result or {}
    row = crud.create_post_history(
        db,
        site_id=site.id,
        product_name=article.get("product_name") or article.get("title", default_name),
        title=article.get("title", ""),
        raw_html=article.get("raw_html", ""),
        post_type=taxonomy_svc.scope_of(post_type),
        status=status,
        wp_post_id=str(result.get("post_id", "")) if result.get("post_id") else None,
        wp_post_url=result.get("post_url"),
        error_message=result.get("error"),
        short_description=article.get("short_description", ""),
        regular_price=regular_price,
        sale_price=sale_price,
        image_paths_json=json.dumps(image_paths, ensure_ascii=False),
        category_ids_json=json.dumps(taxonomy_service.effective_category_ids(article, post_type)),
        tags_json=json.dumps(article.get("tags") or [], ensure_ascii=False),
    )
    return row.id if row else None


def publish_and_record(
    articles: dict[str, dict],
    image_paths: list[str] | None,
    post_type: str,
    post_status: str,
    regular_price: str = "",
    sale_price: str = "",
    optimize_images: bool = True,
    remove_bg: bool = False,
    progress: Progress | None = None,
    apply_watermark: bool = True,
) -> list[dict]:
    """
    Đăng lần lượt lên từng website rồi ghi lịch sử (thành công → 'published', lỗi → 'failed').
    Trả danh sách kết quả của core.pipeline.publish_one (success, post_url, edit_url, cảnh báo...).
    """
    # Lưu bản sao vào data/post_images: đường dẫn tạm của Gradio bị dọn sau đó -> đăng lại từ kho sẽ mất ảnh
    image_paths = image_service.persist_images(image_paths or [])
    configs = site_service.get_site_configs()
    results = pipeline.publish_articles(
        articles=articles,
        image_files=image_paths,
        site_configs=configs,
        post_type=post_type,
        post_status=post_status,
        regular_price=regular_price,
        sale_price=sale_price,
        progress_callback=progress,
        optimize_images=optimize_images,
        remove_bg=remove_bg,
        apply_watermark=apply_watermark,
    )
    with session_scope() as db:
        for result in results:
            site = crud.get_site_by_name(db, result["site_name"])
            if not site:
                continue
            _record(
                db, site, articles.get(result["site_name"], {}), post_type,
                ("published" if post_status == "publish" else "draft") if result["success"] else "failed",
                regular_price, sale_price, image_paths, "", result,
            )
    return results


def save_drafts(
    articles: dict[str, dict],
    image_paths: list[str] | None,
    post_type: str,
    regular_price: str = "",
    sale_price: str = "",
) -> SaveDraftsResult:
    """
    Lưu bài vào Kho bài viết (status 'saved'). Chưa đẩy lên WordPress.

    Lưu ẢNH GỐC: nén WebP / watermark / tách nền chỉ áp dụng lúc đăng (theo logo hiện tại của website và
    tuỳ chọn người dùng chọn khi đăng), nên có thể đổi hoặc bỏ watermark sau khi đã lưu bài.
    """
    image_paths = image_service.persist_images(image_paths or [])
    saved: list[tuple[str, int]] = []
    with session_scope() as db:
        for site_name, art in articles.items():
            site = crud.get_site_by_name(db, site_name)
            if not site:
                continue
            row_id = _record(db, site, art, post_type, "saved", regular_price, sale_price, image_paths, "Sản phẩm")
            if row_id:
                saved.append((site_name, row_id))
    return SaveDraftsResult(saved_count=len(saved), image_count=len(image_paths), saved=tuple(saved))
