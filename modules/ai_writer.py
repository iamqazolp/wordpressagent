"""
modules/ai_writer.py
Dùng Google Gemini để viết bài quảng cáo sản phẩm HTML hoàn chỉnh từ các tài liệu tham khảo.
"""
from __future__ import annotations
import logging
import re
from pathlib import Path

from google import genai
from google.genai import types

from config import settings

logger = logging.getLogger(__name__)

# Đường dẫn file prompt template
PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "write_post.txt"


def _get_client() -> genai.Client:
    """Khởi tạo Gemini client hỗ trợ base_url tùy chỉnh (như shopaikey proxy)."""
    if not settings.GEMINI_API_KEY:
        raise ValueError(
            "Chưa cấu hình GEMINI_API_KEY. "
            "Thêm dòng GEMINI_API_KEY=... vào file .env"
        )

    http_options = None
    if settings.GEMINI_BASE_URL:
        http_options = types.HttpOptions(base_url=settings.GEMINI_BASE_URL)

    return genai.Client(
        api_key=settings.GEMINI_API_KEY,
        http_options=http_options,
    )


def write_post(
    product_name: str,
    reference_contents: list[dict],
    image_count: int = 0,
    site_name: str = "Website",
) -> tuple[str, str]:
    """
    Dùng Gemini viết bài blog/quảng cáo sản phẩm HTML hoàn chỉnh với nhiều thành phần phong phú.

    Args:
        product_name:        Tên sản phẩm.
        reference_contents:  List[{"url": str, "content": str}] từ scraper.
        image_count:         Số ảnh sẽ chèn (để đặt placeholder).
        site_name:           Tên website hiển thị trong bài.

    Returns:
        Tuple (title: str, html_content: str)
        - title: Tiêu đề bài viết
        - html_content: Nội dung bài dạng HTML phong phú
    """
    # Ghép nội dung tham khảo
    if reference_contents:
        ref_text = ""
        for i, ref in enumerate(reference_contents, 1):
            ref_text += f"\n--- Nguồn {i}: {ref['url']} ---\n"
            ref_text += ref["content"][:3000]
            ref_text += "\n"
    else:
        ref_text = "(Không có tài liệu tham khảo - hãy viết dựa trên kiến thức chuyên môn về sản phẩm này)"

    # Đọc prompt template
    prompt_template = PROMPT_PATH.read_text(encoding="utf-8")

    # Điền thông tin vào template
    prompt = prompt_template.format(
        product_name=product_name,
        site_name=site_name,
        reference_articles=ref_text,
        image_count=image_count,
    )

    logger.info(f"Đang gọi Gemini ({settings.GEMINI_MODEL}) để viết bài về: {product_name}")

    try:
        client = _get_client()
        response = client.models.generate_content(
            model=settings.GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.7,
                max_output_tokens=8192,
            ),
        )
        html_content = response.text.strip()

    except Exception as e:
        logger.error(f"Lỗi khi gọi Gemini: {e}")
        raise

    # Dọn code block nếu model vô tình bọc trong ```html
    html_content = re.sub(r"^```html?\s*", "", html_content, flags=re.IGNORECASE)
    html_content = re.sub(r"\s*```$", "", html_content)
    html_content = html_content.strip()

    title = _generate_title(product_name, html_content)
    logger.info(f"✓ Viết xong bài: {title}")
    return title, html_content


def _generate_title(product_name: str, html_content: str) -> str:
    """Lấy tiêu đề từ H1 đầu tiên trong HTML nếu có, fallback về tiêu đề chuẩn."""
    h1_match = re.search(r"<h1[^>]*>(.*?)</h1>", html_content, re.IGNORECASE | re.DOTALL)
    if h1_match:
        title = re.sub(r"<[^>]+>", "", h1_match.group(1)).strip()
        if title:
            return title
    return f"{product_name.capitalize()} – Thông Số Kỹ Thuật, Đặc Điểm & Báo Giá Mới Nhất"


def suggest_title(product_name: str) -> str:
    """Đề xuất 1 tiêu đề SEO cho bài viết sản phẩm."""
    if not settings.GEMINI_API_KEY:
        return f"{product_name} – Thông Số Kỹ Thuật & Đánh Giá Chi Tiết"
    try:
        client = _get_client()
        prompt = (
            f"Hãy viết 1 tiêu đề bài viết giới thiệu/quảng cáo SEO bằng tiếng Việt về sản phẩm '{product_name}'. "
            "Tiêu đề chuyên nghiệp, hấp dẫn, dưới 70 ký tự. "
            "Chỉ trả lời duy nhất tiêu đề, không giải thích thêm."
        )
        response = client.models.generate_content(
            model=settings.GEMINI_MODEL,
            contents=prompt,
        )
        return response.text.strip().strip('"').strip("'")
    except Exception as e:
        logger.warning(f"Không tạo được tiêu đề gợi ý: {e}")
        return f"{product_name} – Thông Số Kỹ Thuật & Đánh Giá Chi Tiết"
