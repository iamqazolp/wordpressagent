"""
modules/searcher.py
Tìm kiếm bài viết tham khảo trên Google qua SerpAPI.
Hỗ trợ cả tìm tự động và nhập URL tay.
"""
from __future__ import annotations
import logging
from config import settings

logger = logging.getLogger(__name__)


def search_articles(product_name: str, extra_urls: list[str] | None = None) -> list[dict]:
    """
    Tìm bài viết liên quan đến sản phẩm.

    Args:
        product_name: Tên sản phẩm cần tìm (tiếng Việt).
        extra_urls:   Danh sách URL người dùng nhập tay thêm.

    Returns:
        List[{"url": str, "title": str, "source": "google"|"manual"}]
    """
    results: list[dict] = []

    # 1. Tìm tự động qua SerpAPI
    if settings.SERP_API_KEY:
        results.extend(_search_via_serpapi(product_name))
    else:
        logger.warning("Chưa cấu hình SERP_API_KEY → bỏ qua tìm kiếm tự động")

    # 2. Thêm URL người dùng nhập tay
    if extra_urls:
        for url in extra_urls:
            url = url.strip()
            if url and url.startswith("http"):
                results.append({
                    "url": url,
                    "title": f"URL tham khảo: {url}",
                    "source": "manual",
                })
                logger.info(f"Thêm URL thủ công: {url}")

    logger.info(f"Tổng cộng {len(results)} nguồn tham khảo")
    return results


def _search_via_serpapi(product_name: str) -> list[dict]:
    """Gọi SerpAPI để tìm bài viết tiếng Việt trên Google."""
    try:
        from serpapi import GoogleSearch  # type: ignore
    except ImportError:
        logger.error("Chưa cài thư viện serpapi. Chạy: pip install google-search-results")
        return []

    query = f"{product_name} là gì thông số kỹ thuật đánh giá"

    params = {
        "engine": "google",
        "q": query,
        "hl": "vi",                          # Kết quả tiếng Việt
        "gl": "vn",                          # Khu vực Việt Nam
        "num": settings.SEARCH_RESULT_COUNT,
        "api_key": settings.SERP_API_KEY,
    }

    try:
        search = GoogleSearch(params)
        data = search.get_dict()
    except Exception as e:
        logger.error(f"Lỗi SerpAPI: {e}")
        return []

    results = []
    for item in data.get("organic_results", []):
        url   = item.get("link", "")
        title = item.get("title", url)
        if url:
            results.append({"url": url, "title": title, "source": "google"})
            logger.info(f"Tìm thấy: {title[:60]}...")

    return results
