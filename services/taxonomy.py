"""
services/taxonomy.py — danh mục & tag: phần dùng chung (phạm vi, chuẩn hóa, tóm tắt hiển thị).

Các thao tác đồng bộ/AI/lưu cho bài đã lưu và lịch hẹn giờ sẽ được gom vào đây ở bước tiếp theo;
logic cốt lõi nằm ở core/taxonomy_service.py và core/taxonomy_ai.py.
"""
from __future__ import annotations

import json

from core import taxonomy_service
from core.taxonomy_ai import category_labels


def scope_of(post_type: str | None) -> str:
    """'product' | 'post' từ giá trị post_type hoặc nhãn hiển thị."""
    return taxonomy_service.scope_for_post_type(post_type or "")


def loads_list(raw: str | None) -> list:
    """JSON list an toàn: chuỗi rỗng/hỏng -> []."""
    try:
        val = json.loads(raw or "[]")
        return val if isinstance(val, list) else []
    except Exception:
        return []


def normalize_category_ids(selected) -> list[int]:
    """Ép về list[int], bỏ giá trị lạ và trùng, giữ thứ tự."""
    out: list[int] = []
    for c in selected or []:
        try:
            cid = int(c)
        except (TypeError, ValueError):
            continue
        if cid not in out:
            out.append(cid)
    return out


def _label_map(db, site_name: str, scope: str, cache: dict | None = None) -> dict[int, str]:
    key = (site_name, scope)
    if cache is not None and key in cache:
        return cache[key]
    labels = category_labels(taxonomy_service.get_categories(db, site_name, scope))
    if cache is not None:
        cache[key] = labels
    return labels


def summarize_selection(db, site_name: str, scope: str, category_ids: list, tags: list, cache: dict | None = None) -> str:
    """'📂 A, B · 🏷️ t1, t2' — tên danh mục tra từ cache; id lạ hiện '#id'. Trống -> '-'."""
    labels = _label_map(db, site_name, scope, cache)
    cats = []
    for c in category_ids or []:
        try:
            cid = int(c)
        except (TypeError, ValueError):
            continue
        cats.append(labels.get(cid) or f"#{cid}")
    parts = []
    if cats:
        parts.append("📂 " + ", ".join(cats))
    if tags:
        parts.append("🏷️ " + ", ".join(str(t) for t in tags))
    return " · ".join(parts) if parts else "-"
