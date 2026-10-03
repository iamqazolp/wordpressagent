"""
services/generation.py — tạo nội dung bài viết bằng AI cho một hoặc nhiều website.

Bọc core.pipeline.generate_articles: nạp cấu hình website + template theo TÊN, chạy tìm kiếm → trích xuất → viết,
rồi bổ sung các trường mà luồng đăng/lưu cần (product_name, short_description).
Định dạng bài (state dùng xuyên suốt): {site: {title, raw_html, short_description, product_name, ...}}.
"""
from __future__ import annotations

import re
from collections.abc import Callable

from core import pipeline
from services import sites as site_service
from services import templates as template_service
from services.errors import ServiceError

Progress = Callable[[float, str], None]

_TABLE_RE = re.compile(r"(<table\b.*?>.*?</table>)", re.DOTALL | re.IGNORECASE)


def extract_short_description(raw_html: str) -> str:
    """Mô tả ngắn mặc định = bảng thông số kỹ thuật đầu tiên trong bài (nếu có)."""
    m = _TABLE_RE.search(raw_html or "")
    return m.group(1) if m else ""


def generate_for_sites(
    product_name: str,
    site_names: list[str],
    image_paths: list[str] | None = None,
    extra_urls: list[str] | None = None,
    user_notes: str = "",
    randomize: bool = False,
    template_name: str | None = None,
    progress: Progress | None = None,
) -> dict[str, dict]:
    """
    Tạo bài cho các website được chọn. Raise ServiceError khi thiếu dữ liệu hoặc không tạo được bài nào;
    các lỗi từ pipeline (thiếu GEMINI_API_KEY, lỗi mạng...) được giữ nguyên để nơi gọi hiển thị.
    """
    if not (product_name or "").strip():
        raise ServiceError("Vui lòng nhập tên sản phẩm!")
    if not site_names:
        raise ServiceError("Vui lòng tích chọn ít nhất 1 website đăng bài!")

    all_configs = site_service.get_site_configs()
    selected = {name: all_configs[name] for name in site_names if name in all_configs}

    articles = pipeline.generate_articles(
        product_name=product_name,
        image_files=image_paths if image_paths else None,
        extra_urls=extra_urls or [],
        user_notes=user_notes,
        selected_sites=selected,
        randomize_enabled=randomize,
        template_content=template_service.get_template_content(template_name),
        progress_callback=progress,
    )
    if not articles:
        raise ServiceError("Không tạo được bài viết nào.")

    for art in articles.values():
        art["product_name"] = product_name
        art["short_description"] = extract_short_description(art.get("raw_html", ""))
    return articles
