"""
core/taxonomy_ai.py
Gợi ý category + tag cho bài viết bằng 1 prompt nhỏ tới Gemini.

Nguyên tắc: AI chỉ ĐỀ XUẤT. Mọi id category AI trả về đều được đối chiếu với danh sách category thật của site
(chống AI bịa id), tag được làm sạch/khử trùng lặp/giới hạn số lượng. Lỗi AI không bao giờ chặn luồng đăng bài.
"""
from __future__ import annotations

import json
import logging
import re
import unicodedata

from core.seo_scorer import extract_text

logger = logging.getLogger(__name__)

MAX_CATEGORIES = 2
MAX_TAGS = 8
_TAG_MIN_LEN, _TAG_MAX_LEN = 2, 40


def category_labels(categories: list[dict]) -> dict[int, str]:
    """{id: 'Cha › Con'} — dựng đường dẫn từ parent, chống vòng lặp do dữ liệu lỗi."""
    by_id = {c["id"]: c for c in categories}
    labels: dict[int, str] = {}
    for c in categories:
        parts, seen, cur = [], set(), c
        while cur is not None and cur["id"] not in seen:
            seen.add(cur["id"])
            parts.append(cur.get("name", ""))
            cur = by_id.get(cur.get("parent") or 0)
        labels[c["id"]] = " › ".join(reversed(parts))
    return labels


def build_prompt(title: str, short_description: str, content: str, categories: list[dict]) -> str:
    labels = category_labels(categories)
    cat_lines = "\n".join(f"{cid}: {label}" for cid, label in labels.items())
    excerpt = extract_text(content)[:1500]
    short = extract_text(short_description)[:400]
    return (
        "Bạn là biên tập viên SEO cho website thương mại điện tử tiếng Việt.\n"
        f"Sản phẩm/bài viết: {title}\n"
        f"Mô tả ngắn: {short or '(không có)'}\n"
        f"Trích đoạn nội dung: {excerpt or '(không có)'}\n\n"
        "DANH SÁCH CATEGORY HIỆN CÓ (định dạng `id: tên`):\n"
        f"{cat_lines}\n\n"
        f"NHIỆM VỤ:\n"
        f"1. Chọn tối đa {MAX_CATEGORIES} category PHÙ HỢP NHẤT từ danh sách trên. Chỉ dùng id có trong danh sách. "
        "Nếu không có category nào thực sự phù hợp thì trả mảng rỗng.\n"
        f"2. Đề xuất {MAX_TAGS - 3}–{MAX_TAGS} tag ngắn (1–4 từ, tiếng Việt, từ khoá người mua có thể tìm), "
        "không lặp nhau, không dùng ký tự # hay dấu phẩy trong tag.\n\n"
        'CHỈ TRẢ VỀ JSON đúng dạng: {"category_ids": [123], "tags": ["tag 1", "tag 2"]}. Không giải thích, không markdown.'
    )


def _clean_tag(raw) -> str:
    if not isinstance(raw, str):
        return ""
    tag = unicodedata.normalize("NFC", raw).strip().lstrip("#").strip()
    tag = re.sub(r"[<>,;]", " ", tag)
    tag = re.sub(r"\s+", " ", tag).strip()
    return tag if _TAG_MIN_LEN <= len(tag) <= _TAG_MAX_LEN else ""


def parse_and_validate(raw_text: str, categories: list[dict]) -> dict:
    """
    Phân tích phản hồi của AI và loại bỏ mọi thứ không hợp lệ.
    Trả về {"category_ids": [int], "tags": [str]} (luôn hợp lệ, có thể rỗng).
    """
    text = (raw_text or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("AI không trả về JSON")
    data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("JSON của AI không phải object")

    valid_ids = {c["id"] for c in categories}
    cat_ids: list[int] = []
    for v in data.get("category_ids") or []:
        try:
            cid = int(v)
        except (TypeError, ValueError):
            continue
        if cid in valid_ids and cid not in cat_ids:
            cat_ids.append(cid)
    cat_ids = cat_ids[:MAX_CATEGORIES]

    tags: list[str] = []
    seen: set[str] = set()
    for raw in data.get("tags") or []:
        tag = _clean_tag(raw)
        key = tag.casefold()
        if tag and key not in seen:
            seen.add(key)
            tags.append(tag)
    return {"category_ids": cat_ids, "tags": tags[:MAX_TAGS]}


def suggest_taxonomy(
    title: str,
    short_description: str,
    content: str,
    categories: list[dict],
    generate=None,
) -> dict:
    """
    Gợi ý category + tag. `generate(prompt) -> str` có thể truyền vào để test; mặc định gọi Gemini.
    Không bao giờ raise: lỗi -> {"category_ids": [], "tags": [], "error": "..."}.
    """
    empty = {"category_ids": [], "tags": []}
    try:
        prompt = build_prompt(title, short_description, content, categories)
        if generate is None:
            generate = _gemini_generate
        result = parse_and_validate(generate(prompt), categories)
        if not categories:
            result["category_ids"] = []
        return result
    except Exception as e:
        logger.warning(f"AI gợi ý category/tag thất bại: {e}")
        return {**empty, "error": str(e)}


def _gemini_generate(prompt: str) -> str:
    from config import settings
    from core.ai_writer import _get_client
    from google.genai import types

    client = _get_client()
    response = client.models.generate_content(
        model=settings.GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.2,
            max_output_tokens=4096,  # model "thinking" tiêu tốn token trước phần trả lời (đo thực tế ~540), 512 làm JSON bị cắt cụt
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        ),
    )
    return response.text or ""
