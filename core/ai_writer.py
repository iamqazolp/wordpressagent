"""
core/ai_writer.py
Dùng Google Gemini để viết bài quảng cáo sản phẩm HTML hoàn chỉnh từ các tài liệu tham khảo.
"""
from __future__ import annotations
import logging
import re
import threading
from pathlib import Path
from typing import TYPE_CHECKING
import nh3

from tenacity import retry, stop_after_attempt, wait_exponential

from config import settings

if TYPE_CHECKING:
    from google import genai

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

# Mặc định google-genai không có timeout: một kết nối treo làm đứng cả lượt viết bài cho nhiều website.
# Model "thinking" viết bài dài có thể mất 1-2 phút, nên để rộng tay. Đơn vị: mili giây.
GEMINI_TIMEOUT_MS = 180_000

_clients: dict[tuple[str, str], genai.Client] = {}
_clients_lock = threading.Lock()


def _get_client() -> genai.Client:
    """Gemini client (dùng lại theo key + base_url, giữ kết nối) hỗ trợ base_url tùy chỉnh (như shopaikey proxy)."""
    if not settings.GEMINI_API_KEY:
        raise ValueError(
            "Chưa cấu hình GEMINI_API_KEY. "
            "Thêm dòng GEMINI_API_KEY=... vào file .env"
        )

    # Nạp google-genai khi cần (~0.1-0.4 giây) thay vì lúc khởi động app
    from google import genai
    from google.genai import types

    key = (settings.GEMINI_API_KEY, settings.GEMINI_BASE_URL or "")
    with _clients_lock:
        client = _clients.get(key)
        if client is None:
            http_options = types.HttpOptions(base_url=settings.GEMINI_BASE_URL or None, timeout=GEMINI_TIMEOUT_MS)
            client = genai.Client(api_key=settings.GEMINI_API_KEY, http_options=http_options)
            _clients[key] = client
        return client


def _response_text(response) -> str:
    """response.text là None khi bị chặn an toàn hoặc hết token -> báo lỗi rõ ràng thay vì AttributeError."""
    text = getattr(response, "text", None)
    if not text:
        reason = ""
        try:
            reason = str(response.candidates[0].finish_reason)
        except Exception:
            pass
        raise RuntimeError(f"Gemini không trả về nội dung{f' ({reason})' if reason else ''}. Hãy thử lại.")
    return text

_PLACEHOLDER_RE = re.compile(r"\{\{|\}\}|\{(\w+)\}")


def fill_template(template: str, **values) -> str:
    """
    Thay {product_name}, {site_name}... trong template. Khác str.format: ngoặc nhọn khác (CSS, JSON mẫu
    trong template tùy chỉnh) được giữ nguyên thay vì làm lỗi; {{ }} kiểu format vẫn ra { }; và giá trị
    điền vào (tài liệu tham khảo, ghi chú) không bị quét lại hay nhân đôi ngoặc.
    """
    def sub(m: re.Match) -> str:
        token = m.group(0)
        if token in ("{{", "}}"):
            return token[0]
        key = m.group(1)
        return str(values[key]) if key in values else token

    return _PLACEHOLDER_RE.sub(sub, template)


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
    from google.genai import types

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

    notes = user_notes.strip() if user_notes and user_notes.strip() else "(Không có yêu cầu riêng)"

    # Điền thông tin vào template
    prompt = fill_template(
        prompt_template,
        product_name=product_name,
        site_name=site_name,
        reference_articles=ref_text,
        image_count=image_count,
        user_notes=notes + variation_instruction,
    )

    logger.info(f"Đang gọi Gemini ({settings.GEMINI_MODEL}) để viết bài về '{product_name}' cho site '{site_name}' (var={variation_index}/{total_variations})...")

    try:
        client = _get_client()
        response = _call_gemini(client, settings.GEMINI_MODEL, prompt, temperature)
        html_content = _response_text(response).strip()

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


def write_short_description(product_name: str, article_html: str, note: str) -> str:
    """Viết mô tả ngắn (HTML) cho sản phẩm theo ghi chú của người dùng, dựa trên nội dung bài đã có."""
    context = re.sub(r"<[^>]+>", " ", article_html or "")
    context = re.sub(r"\s+", " ", context).strip()[:4000].replace("{", "(").replace("}", ")")
    prompt = (
        f"Viết MÔ TẢ NGẮN (HTML đơn giản: <p>, <ul>, <li>, <strong>) cho sản phẩm '{product_name}'.\n"
        f"Yêu cầu của người dùng: {note.strip()}\n\n"
        f"Nội dung bài đầy đủ để tham khảo (giữ đúng thông số, không bịa):\n{context}\n\n"
        "Chỉ trả về HTML, không giải thích, không bọc trong code block."
    )
    response = _call_gemini(_get_client(), settings.GEMINI_MODEL, prompt, 0.4)
    html = re.sub(r"^```html?\s*", "", _response_text(response).strip(), flags=re.IGNORECASE)
    html = re.sub(r"\s*```$", "", html).strip()
    return nh3.clean(html, tags=_ALLOWED_TAGS, attributes=_ALLOWED_ATTRS)


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
