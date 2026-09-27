"""
core/scraper.py
Đọc nội dung chính từ một URL web.
Tự động lọc bỏ: menu, header, footer, sidebar, quảng cáo.
"""
from __future__ import annotations
import httpx
from bs4 import BeautifulSoup
import re
import logging
from concurrent.futures import ThreadPoolExecutor
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception

logger = logging.getLogger(__name__)

# Timeout tối đa khi tải trang (giây) - giảm xuống để không làm đơ pipeline
REQUEST_TIMEOUT = 7

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

_scrape_cache: dict[str, str] = {}


def _is_retryable_error(exc: BaseException) -> bool:
    """Không thử lại nếu gặp mã lỗi 4xx của client (400, 403, 404...)."""
    if isinstance(exc, httpx.HTTPStatusError):
        if 400 <= exc.response.status_code < 500:
            return False
    return True


@retry(
    stop=stop_after_attempt(2),
    wait=wait_fixed(1),
    retry=retry_if_exception(_is_retryable_error),
    reraise=True,
)
def _fetch_html(url: str) -> str:
    """Tải HTML từ URL với cơ chế tự động thử lại (retry)."""
    response = httpx.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT, follow_redirects=True)
    response.raise_for_status()
    return response.text


def scrape_article(url: str) -> str:
    """
    Tải và trích xuất nội dung văn bản chính từ một URL.

    Args:
        url: Địa chỉ bài viết cần đọc.

    Returns:
        Chuỗi văn bản thuần, đã lọc bỏ nội dung thừa.
        Trả về chuỗi rỗng nếu không tải được.
    """
    if url in _scrape_cache:
        logger.info(f"Dùng cache cho URL: {url}")
        return _scrape_cache[url]

    try:
        logger.info(f"Đang tải: {url}")
        html_text = _fetch_html(url)
    except Exception as e:
        logger.warning(f"Không tải được {url} sau các lần thử: {e}")
        return ""

    soup = BeautifulSoup(html_text, "lxml")

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

    # Trích xuất bảng thông số kỹ thuật (table) — rất quan trọng cho sản phẩm công nghiệp
    for table in main_content.find_all("table"):
        rows = []
        for tr in table.find_all("tr"):
            cells = [td.get_text(separator=" ", strip=True) for td in tr.find_all(["th", "td"])]
            if cells:
                rows.append(" | ".join(cells))
        if rows:
            lines.append("Bảng thông số:\n" + "\n".join(rows))

    # Trích xuất definition list (dl/dt/dd) — nhiều trang dùng thay cho table
    for dl in main_content.find_all("dl"):
        items = []
        for dt, dd in zip(dl.find_all("dt"), dl.find_all("dd")):
            dt_text = dt.get_text(strip=True)
            dd_text = dd.get_text(strip=True)
            if dt_text and dd_text:
                items.append(f"{dt_text}: {dd_text}")
        if items:
            lines.append("\n".join(items))

    content = "\n\n".join(lines)

    # Dọn khoảng trắng thừa
    content = re.sub(r"\n{3,}", "\n\n", content)
    content = re.sub(r" {2,}", " ", content)

    final_content = content.strip()
    _scrape_cache[url] = final_content
    return final_content


def scrape_multiple(urls: list[str]) -> list[dict]:
    """
    Tải nhiều URL, trả về danh sách kết quả (dùng ThreadPoolExecutor).

    Args:
        urls: Danh sách URL cần đọc.

    Returns:
        List[{"url": str, "content": str}]
    """
    results = []
    
    def worker(u: str) -> dict | None:
        content = scrape_article(u)
        if content:
            logger.info(f"✓ Đọc được {len(content)} ký tự từ {u}")
            return {"url": u, "content": content}
        else:
            logger.warning(f"✗ Bỏ qua {u} (không đọc được nội dung)")
            return None

    with ThreadPoolExecutor(max_workers=5) as executor:
        for res in executor.map(worker, urls):
            if res:
                results.append(res)
                
    return results
