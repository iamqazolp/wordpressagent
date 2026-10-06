"""
core/searcher.py
Tìm kiếm bài viết tham khảo trên Google qua SerpAPI (hoặc DuckDuckGo dự phòng).
Hỗ trợ cả tìm tự động và nhập URL tay.
Tối ưu hiệu năng:
- Xây dựng từ khóa thông minh (chỉ thêm 'thông số kỹ thuật' khi là máy móc/kỹ thuật).
- Lọc độ liên quan (bỏ kết quả lạc đề như 'bàn chải' khi tìm 'bún chả').
- Chạy song song SerpAPI + DuckDuckGo với cơ chế race (ưu tiên kết quả nhanh <1.5s).
- Tự động unwrap link Google Translate.
"""
from __future__ import annotations
import concurrent.futures
import logging
import re
import unicodedata
import urllib.parse
import httpx
from bs4 import BeautifulSoup

from config import settings

logger = logging.getLogger(__name__)

# Các domain mạng xã hội hoặc không chứa thông số kỹ thuật sản phẩm
BLOCKED_DOMAINS = [
    "facebook.com",
    "instagram.com",
    "tiktok.com",
    "youtube.com",
    "twitter.com",
    "x.com",
    "pinterest.com",
    "threads.net",
    "wikipedia.org",
]

# Các từ khóa nhận diện sản phẩm kỹ thuật/máy móc để thêm hậu tố tìm kiếm
TECHNICAL_KEYWORDS = {
    "may", "thiet bi", "dien thoai", "laptop", "motor", "bom", "pin",
    "cong suat", "khoan", "mai", "cua", "dong co", "bien tan", "may moc",
    "module", "cam bien", "ic", "chip", "linh kien", "cong nghiep", "robot",
}


def _clean_ascii(text: str) -> str:
    """Loại bỏ dấu tiếng Việt và chuyển về chữ thường để so sánh."""
    text = (text or "").replace("đ", "d").replace("Đ", "d")
    text = unicodedata.normalize("NFD", text)
    return "".join(c for c in text if unicodedata.category(c) != "Mn").lower()


def _build_search_query(product_name: str) -> str:
    """
    Xây dựng câu tìm kiếm tự nhiên:
    - Với máy móc, công cụ kỹ thuật: thêm 'thông số kỹ thuật' để tìm spec sheet.
    - Với ẩm thực, thời trang, nội thất, dịch vụ: giữ nguyên tên sản phẩm để tránh lạc đề.
    """
    p_clean = _clean_ascii(product_name)
    is_tech = any(kw in p_clean for kw in TECHNICAL_KEYWORDS)
    if is_tech and "thong so" not in p_clean:
        return f"{product_name.strip()} thông số kỹ thuật"
    return product_name.strip()


def _is_relevant(product_name: str, title: str, url: str) -> bool:
    """
    Kiểm tra độ liên quan giữa tên sản phẩm và bài viết tìm thấy.
    Loại bỏ trường hợp DuckDuckGo gộp nhầm âm (vd tìm 'Bún chả' ra 'Bàn chải').
    """
    clean_p = _clean_ascii(product_name).strip()
    p_tokens = [w for w in re.split(r"\s+", clean_p) if len(w) >= 2]
    if not p_tokens:
        return True

    clean_target = _clean_ascii(f"{title} {url}").strip()
    target_tokens = set(re.split(r"[^a-z0-9]+", clean_target))

    # Cụm từ đầy đủ xuất hiện trong tiêu đề hoặc link
    if clean_p in clean_target:
        return True

    # Sản phẩm ngắn (1-2 từ như 'bún chả'): yêu cầu TẤT CẢ các từ phải xuất hiện
    if len(p_tokens) <= 2:
        return all(tok in target_tokens for tok in p_tokens)

    # Sản phẩm dài (>= 3 từ): yêu cầu ít nhất 50% số từ khóa chính xuất hiện
    matched = sum(1 for tok in p_tokens if tok in target_tokens)
    return (matched / len(p_tokens)) >= 0.5


def _unwrap_url(url: str) -> str:
    """
    Giải mã các URL bị bọc qua translate.google.com hoặc google.com/url.
    Nếu không phải URL bọc, trả lại URL gốc.
    """
    if not url:
        return ""
    if "translate.google.com" in url or "google.com/url" in url:
        parsed = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        real = parsed.get("u") or parsed.get("url") or parsed.get("q")
        if real and real[0].startswith("http"):
            return real[0]
    return url


def search_articles(product_name: str, extra_urls: list[str] | None = None) -> list[dict]:
    """
    Tìm bài viết liên quan đến sản phẩm.

    Args:
        product_name: Tên sản phẩm cần tìm (tiếng Việt).
        extra_urls:   Danh sách URL người dùng nhập tay thêm.

    Returns:
        List[{"url": str, "title": str, "source": "google"|"duckduckgo"|"manual"}]
    """
    # Chuẩn hoá Unicode NFC để sửa lỗi gõ tiếng Việt trên macOS/Windows
    product_name = unicodedata.normalize("NFC", product_name).strip()
    results: list[dict] = []
    seen_urls = set()

    # 1. Thêm URL người dùng nhập tay trước (ưu tiên cao nhất)
    if extra_urls:
        for url in extra_urls:
            url = url.strip()
            if url and url.startswith("http") and url not in seen_urls:
                seen_urls.add(url)
                results.append({
                    "url": url,
                    "title": f"URL tham khảo: {url}",
                    "source": "manual",
                })
                logger.info(f"Thêm URL thủ công: {url}")

    limit = getattr(settings, "SEARCH_RESULT_COUNT", 5)

    # 2. Tìm kiếm: nếu có SerpAPI key thì chạy song song SerpAPI + DuckDuckGo
    if getattr(settings, "SERP_API_KEY", ""):
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            serp_fut = executor.submit(_search_via_serpapi, product_name, limit=limit)
            ddg_fut = executor.submit(_search_via_duckduckgo, product_name, limit=limit)

            # Ưu tiên kiểm tra SerpAPI trong 1.5 giây (cache hit thường trả về trong 0.2 - 0.5s)
            try:
                serp_results = serp_fut.result(timeout=1.5)
            except concurrent.futures.TimeoutError:
                serp_results = None

            if serp_results:
                for r in serp_results:
                    if r["url"] not in seen_urls:
                        seen_urls.add(r["url"])
                        results.append(r)
                    if len(results) >= limit:
                        break

            # Nếu SerpAPI chưa xong trong 1.5s, dùng kết quả DuckDuckGo (thường xong trong 0.8s)
            if len(results) < limit:
                try:
                    ddg_results = ddg_fut.result(timeout=1.0)
                except concurrent.futures.TimeoutError:
                    ddg_results = []

                for r in ddg_results:
                    if r["url"] not in seen_urls:
                        seen_urls.add(r["url"])
                        results.append(r)
                    if len(results) >= limit:
                        break

            # Nếu vẫn chưa đủ và SerpAPI chưa xong, đợi SerpAPI hoàn tất
            if len(results) < limit and serp_results is None:
                try:
                    rem_serp = serp_fut.result()
                    for r in rem_serp:
                        if r["url"] not in seen_urls:
                            seen_urls.add(r["url"])
                            results.append(r)
                        if len(results) >= limit:
                            break
                except Exception:
                    pass
    else:
        logger.info(f"Đang tìm kiếm qua DuckDuckGo cho '{product_name}'...")
        ddg_results = _search_via_duckduckgo(product_name, limit=limit)
        for r in ddg_results:
            if r["url"] not in seen_urls:
                seen_urls.add(r["url"])
                results.append(r)
            if len(results) >= limit:
                break

    logger.info(f"Tổng cộng {len(results)} nguồn tham khảo cho '{product_name}'")
    return results[:limit]


def _search_via_serpapi(product_name: str, limit: int = 5, timeout: int | None = None) -> list[dict]:
    """Gọi SerpAPI để tìm bài viết tiếng Việt trên Google."""
    try:
        from serpapi import GoogleSearch  # type: ignore
    except ImportError:
        logger.error("Chưa cài thư viện serpapi. Chạy: pip install google-search-results")
        return []

    timeout = timeout or getattr(settings, "SERP_TIMEOUT", 8)
    query = _build_search_query(product_name)
    logger.info(f"🔍 Tìm kiếm Google qua SerpAPI: {query} (timeout={timeout}s)")

    params = {
        'engine': 'google',
        'q': query,
        'hl': 'vi',
        'gl': 'vn',
        'num': max(limit * 2, 8),
        'api_key': settings.SERP_API_KEY,
    }

    try:
        search = GoogleSearch(params)
        search.timeout = timeout
        data = search.get_dict()
    except Exception as e:
        logger.warning(f"SerpAPI không phản hồi hoặc phản hồi quá chậm ({e}), chuyển sang nguồn khác.")
        return []

    results = []
    for item in data.get('organic_results', []):
        url = _unwrap_url(item.get('link', ''))
        title = item.get('title', url)
        if not url:
            continue

        url_lower = url.lower()
        if any(bad in url_lower for bad in BLOCKED_DOMAINS) or "translate.google.com" in url_lower:
            continue

        if not _is_relevant(product_name, title, url):
            continue

        results.append({'url': url, 'title': title, 'source': 'google'})
        logger.info(f"SerpAPI tìm thấy: {title[:60]}... ({url})")
        if len(results) >= limit:
            break

    return results


def _search_via_duckduckgo(product_name: str, limit: int = 4) -> list[dict]:
    """Tìm kiếm dự phòng qua DuckDuckGo HTML khi không có SerpAPI key."""
    query = _build_search_query(product_name)
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
        "Referer": "https://html.duckduckgo.com/",
    }
    results = []
    try:
        resp = httpx.post(
            "https://html.duckduckgo.com/html/",
            data={"q": query},
            headers=headers,
            timeout=8,
            follow_redirects=True,
        )
        if resp.status_code != 200:
            return []

        soup = BeautifulSoup(resp.text, "lxml")
        for link_elem in soup.select(".result__body"):
            title_elem = link_elem.select_one(".result__title a")
            url_elem = link_elem.select_one(".result__url")
            if not title_elem:
                continue

            raw_href = title_elem.get("href", "")
            if "uddg=" in raw_href:
                parsed = urllib.parse.parse_qs(urllib.parse.urlparse(raw_href).query)
                url = parsed.get("uddg", [raw_href])[0]
            elif raw_href.startswith("http"):
                url = raw_href
            elif url_elem:
                url_text = url_elem.get_text(strip=True)
                url = f"https://{url_text}" if not url_text.startswith("http") else url_text
            else:
                continue

            url = _unwrap_url(url)
            url_lower = url.lower()
            if any(bad in url_lower for bad in BLOCKED_DOMAINS) or "duckduckgo.com" in url_lower or "translate.google.com" in url_lower:
                continue

            title = title_elem.get_text(strip=True) or url
            if not _is_relevant(product_name, title, url):
                continue

            results.append({"url": url, "title": title, "source": "duckduckgo"})
            logger.info(f"DuckDuckGo tìm thấy: {title[:60]}... ({url})")
            if len(results) >= limit:
                break

    except Exception as e:
        logger.warning(f"Lỗi tìm kiếm dự phòng DuckDuckGo: {e}")

    return results
