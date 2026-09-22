"""
modules/scraper.py
Đọc nội dung chính từ một URL web.
Tự động lọc bỏ: menu, header, footer, sidebar, quảng cáo.
"""
from __future__ import annotations
import httpx
from bs4 import BeautifulSoup
import re
import logging

logger = logging.getLogger(__name__)

# Timeout tối đa khi tải trang (giây)
REQUEST_TIMEOUT = 15

# User-Agent giả browser để tránh bị chặn
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
}

# Các thẻ HTML chứa nội dung không liên quan → xóa đi
TAGS_TO_REMOVE = [
    "script", "style", "nav", "header", "footer",
    "aside", "form", "iframe", "noscript", "svg",
    "figure[class*='ad']", "div[class*='banner']",
    "div[class*='popup']", "div[class*='cookie']",
    "div[id*='comment']", "div[class*='related']",
    "div[class*='sidebar']",
]


def scrape_article(url: str) -> str:
    """
    Tải và trích xuất nội dung văn bản chính từ một URL.

    Args:
        url: Địa chỉ bài viết cần đọc.

    Returns:
        Chuỗi văn bản thuần, đã lọc bỏ nội dung thừa.
        Trả về chuỗi rỗng nếu không tải được.
    """
    try:
        logger.info(f"Đang tải: {url}")
        response = httpx.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT, follow_redirects=True)
        response.raise_for_status()
    except Exception as e:
        logger.warning(f"Không tải được {url}: {e}")
        return ""

    soup = BeautifulSoup(response.text, "lxml")

    # Xóa các thẻ không cần thiết
    for selector in TAGS_TO_REMOVE:
        for tag in soup.select(selector):
            tag.decompose()

    # Ưu tiên tìm thẻ chứa nội dung chính
    main_content = (
        soup.find("article")
        or soup.find("main")
        or soup.find("div", class_=re.compile(r"(post|entry|content|article)-?(body|content|text)?", re.I))
        or soup.find("div", id=re.compile(r"(post|entry|content|article)", re.I))
        or soup.body
    )

    if main_content is None:
        return ""

    # Lấy text, giữ dòng trống giữa các đoạn
    lines = []
    for element in main_content.find_all(["p", "h1", "h2", "h3", "h4", "li"]):
        text = element.get_text(separator=" ", strip=True)
        if text and len(text) > 20:  # Bỏ qua dòng quá ngắn (thường là label, nút bấm)
            lines.append(text)

    content = "\n\n".join(lines)

    # Dọn khoảng trắng thừa
    content = re.sub(r"\n{3,}", "\n\n", content)
    content = re.sub(r" {2,}", " ", content)

    return content.strip()


def scrape_multiple(urls: list[str]) -> list[dict]:
    """
    Tải nhiều URL, trả về danh sách kết quả.

    Args:
        urls: Danh sách URL cần đọc.

    Returns:
        List[{"url": str, "content": str}]
    """
    results = []
    for url in urls:
        content = scrape_article(url)
        if content:
            results.append({"url": url, "content": content})
            logger.info(f"✓ Đọc được {len(content)} ký tự từ {url}")
        else:
            logger.warning(f"✗ Bỏ qua {url} (không đọc được nội dung)")
    return results
