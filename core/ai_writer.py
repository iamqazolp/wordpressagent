"""
core/ai_writer.py
Dùng Google Gemini để viết bài quảng cáo sản phẩm HTML hoàn chỉnh từ các tài liệu tham khảo.
"""
from __future__ import annotations
import logging
import re
from pathlib import Path
import nh3

from google import genai
from google.genai import types
from tenacity import retry, stop_after_attempt, wait_exponential

from config import settings

logger = logging.getLogger(__name__)

# Đường dẫn file prompt template
PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "write_post.txt"

_ALLOWED_TAGS = {'p','h1','h2','h3','h4','h5','h6','table','thead','tbody','tr','th','td',
                 'ul','ol','li','strong','em','b','i','a','img','figure','figcaption',
                 'span','br','hr','div','sup','sub'}
_ALLOWED_ATTRS = {
    'a': {'href','title','target'},
    'img': {'src','alt','width','height','style','decoding','class'},
    'span': {'style'},
    'figure': {'id','style','class'},
    'td': {'colspan','rowspan'},
    'th': {'colspan','rowspan'},
    'table': {'class','style'},
    'div': {'class','style'},
}

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

VARIATION_ANGLES = [
    "Nhấn mạnh vào hiệu năng vận hành thực tế, công suất tải và khả năng làm việc liên tục.",
    "Nhấn mạnh vào độ an toàn kỹ thuật, hệ thống ngắt tự động và độ tin cậy cơ khí.",
    "Nhấn mạnh vào ứng dụng đa ngành trong công xưởng, kho bãi và bài toán tối ưu chi phí.",
    "Nhấn mạnh vào chất lượng vật liệu gia công, độ bền chi tiết và hướng dẫn kỹ thuật chuẩn.",
    "Nhấn mạnh vào tính tiện dụng khi lắp đặt, bảo dưỡng định kỳ và tuổi thọ sử dụng lâu dài.",
    "Nhấn mạnh vào khả năng tiết kiệm điện năng, tối ưu hóa không gian và vận hành êm ái.",
    "Nhấn mạnh vào tiêu chuẩn chứng nhận chất lượng, chế độ bảo hành và nguồn gốc sản phẩm.",
    "Nhấn mạnh vào trải nghiệm thực tế của người dùng, phân tích ưu/nhược điểm khách quan.",
]

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=30), reraise=True)
def _call_gemini(client, model, prompt, temperature):
    return client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=8192,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        ),
    )

def write_post(
    product_name: str,
    reference_contents: list[dict],
    image_count: int = 0,
    site_name: str = "Website",
    user_notes: str = "",
    variation_index: int = 0,
    total_variations: int = 1,
    template_content: str | None = None,
) -> tuple[str, str]:
    """
    Dùng Gemini viết bài blog/quảng cáo sản phẩm HTML hoàn chỉnh với nhiều thành phần phong phú.
    Hỗ trợ tạo nội dung độc bản (randomize/variation) khi đăng lên nhiều website khác nhau.

    Args:
        product_name:        Tên sản phẩm.
        reference_contents:  List[{"url": str, "content": str}] từ scraper.
        image_count:         Số ảnh sẽ chèn (để đặt placeholder).
        site_name:           Tên website hiển thị trong bài.
        user_notes:          Gợi ý, ghi chú hoặc yêu cầu riêng từ người dùng.
        variation_index:     Chỉ số phiên bản (1, 2, 3...) khi bật randomize cho nhiều site.
        total_variations:    Tổng số website cần tạo bài khác nhau.
        template_content:    Nội dung prompt template tùy chỉnh. Nếu None, dùng template mặc định.

    Returns:
        Tuple (title: str, html_content: str)
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

    # Nếu có yêu cầu biến thể độc bản (Randomize)
    variation_instruction = ""
    temperature = 0.7
    if total_variations > 1 and variation_index > 0:
        angle = VARIATION_ANGLES[(variation_index - 1) % len(VARIATION_ANGLES)]
        temperature = 0.85  # Tăng tính sáng tạo để từ ngữ phong phú hơn
        variation_instruction = (
            f"\n\n==== YÊU CẦU ĐỘC BẢN CHO WEBSITE {site_name} (Phiên bản {variation_index}/{total_variations}) ====\n"
            f"- MỤC TIÊU: Tạo bài viết ĐỘC LẬP về câu chữ để tránh thuật toán trùng lặp nội dung (Duplicate Content) của Google.\n"
            f"- Góc nhìn trọng tâm cho phiên bản này: {angle}\n"
            f"- Hãy thay đổi cách mở bài, dùng các từ đồng nghĩa và cấu trúc câu khác biệt khi phân tích cấu tạo, ưu điểm và ứng dụng.\n"
            f"- Bắt buộc giữ nguyên và bảo lưu 100% các thông số kỹ thuật chuẩn xác trong bảng <table>.\n"
            f"==== HẾT YÊU CẦU ĐỘC BẢN ===="
        )

    # Đọc prompt template
    if template_content is not None:
        prompt_template = template_content
    else:
        prompt_template = PROMPT_PATH.read_text(encoding="utf-8")

    # Bảo vệ các dấu ngoặc nhọn đơn lẻ trong dữ liệu đầu vào tránh lỗi .format()
    safe_ref_text = ref_text.replace("{", "{{").replace("}", "}}")
    safe_user_notes = (user_notes.strip() if user_notes and user_notes.strip() else "(Không có yêu cầu riêng)")
    safe_user_notes = safe_user_notes.replace("{", "{{").replace("}", "}}") + variation_instruction

    # Điền thông tin vào template
    prompt = prompt_template.format(
        product_name=product_name,
        site_name=site_name,
        reference_articles=safe_ref_text,
        image_count=image_count,
        user_notes=safe_user_notes,
    )

    logger.info(f"Đang gọi Gemini ({settings.GEMINI_MODEL}) để viết bài về '{product_name}' cho site '{site_name}' (var={variation_index}/{total_variations})...")

    try:
        client = _get_client()
        response = _call_gemini(client, settings.GEMINI_MODEL, prompt, temperature)
        html_content = response.text.strip()

    except Exception as e:
        logger.error(f"Lỗi khi gọi Gemini: {e}")
        raise

    # Dọn code block nếu model vô tình bọc trong ```html
    html_content = re.sub(r"^```html?\s*", "", html_content, flags=re.IGNORECASE)
    html_content = re.sub(r"\s*```$", "", html_content)
    html_content = html_content.strip()

    html_content = nh3.clean(html_content, tags=_ALLOWED_TAGS, attributes=_ALLOWED_ATTRS)

    title = _generate_title(product_name, html_content)
    logger.info(f"✓ Viết xong bài cho {site_name}: {title}")
    return title, html_content


def _generate_title(product_name: str, html_content: str) -> str:
    """Tạo tên sản phẩm chuẩn phong cách WooCommerce như web mẫu."""
    # Thử lấy từ 'Tổng quan về ...' trong H3
    h3_match = re.search(
        r"<h3>(?:<span[^>]*>)?\s*Tổng quan về\s*(.*?)(?:</span>)?\s*</h3>",
        html_content,
        re.IGNORECASE,
    )
    if h3_match:
        extracted = re.sub(r"<[^>]+>", "", h3_match.group(1)).strip()
        if extracted and len(extracted) < 80:
            return extracted
    # Fallback: Chuẩn hóa chữ hoa đầu từ cho product_name
    return " ".join(w.capitalize() for w in product_name.strip().split())


def suggest_title(product_name: str) -> str:
    """Đề xuất tên sản phẩm chuẩn SEO."""
    return " ".join(w.capitalize() for w in product_name.strip().split())
