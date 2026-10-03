"""
core/taxonomy_service.py
Đồng bộ + cache category theo website, và áp dụng category/tag khi đăng.
Là lớp mỏng nối wp_client (mạng) với crud (SQLite) để UI/pipeline không phải biết chi tiết.
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from core import wp_client
from core.taxonomy_ai import category_labels
from db import crud

logger = logging.getLogger(__name__)

SCOPES = ("product", "post")


def scope_for_post_type(post_type: str) -> str:
    """'Sản phẩm WooCommerce' / 'product' -> 'product'; còn lại -> 'post'."""
    t = (post_type or "").lower()
    return "product" if ("product" in t or "sản phẩm" in t) else "post"


def sync_site_categories(db: Session, site_name: str, scopes: tuple[str, ...] = SCOPES) -> dict[str, dict]:
    """
    Lấy category từ WordPress/WooCommerce và ghi cache. Mỗi scope độc lập:
    scope lỗi giữ nguyên cache cũ và báo lỗi, scope khác vẫn được cập nhật.
    Trả về {scope: {"ok": bool, "count": int, "error": str|None}}.
    """
    site = crud.get_site_by_name(db, site_name)
    if not site:
        return {s: {"ok": False, "count": 0, "error": f"Không tìm thấy website '{site_name}'"} for s in scopes}
    config = crud.get_site_config(db, site.id)

    report: dict[str, dict] = {}
    for scope in scopes:
        try:
            cats = wp_client.fetch_categories(config, scope)
            count = crud.replace_site_categories(db, site.id, scope, cats)
            report[scope] = {"ok": True, "count": count, "error": None}
        except Exception as e:
            logger.warning(f"Đồng bộ category ({scope}) của {site_name} thất bại: {e}")
            report[scope] = {"ok": False, "count": 0, "error": str(e)}
    return report


def ensure_fresh_categories(db: Session, site_name: str, scope: str) -> bool:
    """Đồng bộ lại nếu chưa có cache hoặc cache quá 24h. Trả True nếu sau đó có dữ liệu để dùng."""
    site = crud.get_site_by_name(db, site_name)
    if not site:
        return False
    if crud.is_categories_stale(db, site.id, scope):
        sync_site_categories(db, site_name, (scope,))
    return bool(crud.get_site_categories(db, site.id, scope))


def get_categories(db: Session, site_name: str, scope: str) -> list[dict]:
    """Category đang cache của site: [{"id", "name", "parent"}]."""
    site = crud.get_site_by_name(db, site_name)
    if not site:
        return []
    return [
        {"id": r.wp_id, "name": r.name, "parent": r.parent_id or 0}
        for r in crud.get_site_categories(db, site.id, scope)
    ]


def get_category_choices(db: Session, site_name: str, scope: str) -> list[tuple[str, int]]:
    """[(nhãn 'Cha › Con', id)] sắp xếp theo nhãn — dùng cho Dropdown."""
    cats = get_categories(db, site_name, scope)
    labels = category_labels(cats)
    # Site thật có thể có 2 danh mục trùng tên (vd "Dây Cáp Vải" #463 và #464) -> thêm id để phân biệt.
    counts: dict[str, int] = {}
    for label in labels.values():
        counts[label] = counts.get(label, 0) + 1
    shown = {cid: (f"{label} · #{cid}" if counts[label] > 1 else label) for cid, label in labels.items()}
    return sorted(((shown[c["id"]], c["id"]) for c in cats), key=lambda x: x[0].casefold())


def cache_status_text(db: Session, site_name: str, scope: str) -> str:
    site = crud.get_site_by_name(db, site_name)
    if not site:
        return ""
    fetched = crud.get_categories_fetched_at(db, site.id, scope)
    if fetched is None:
        return "ℹ️ Chưa có danh mục của website này — bấm **🔄 Làm mới danh mục**."
    n = len(crud.get_site_categories(db, site.id, scope))
    stale = " ⚠️ *cache đã cũ (>24h), nên làm mới*" if crud.is_categories_stale(db, site.id, scope) else ""
    return f"📂 {n} danh mục · cập nhật {fetched.strftime('%d/%m %H:%M')}{stale}"


def resolve_tag_ids(site_config: dict, post_type: str, tag_names: list[str]) -> tuple[list[int], str | None]:
    """
    Đổi tên tag -> id trên site (tạo nếu chưa có). Không bao giờ raise.
    Trả về (ids, warning|None); warning có nội dung khi có tag không xử lý được.
    """
    names = [t for t in (tag_names or []) if t and t.strip()]
    if not names:
        return [], None
    try:
        ids = wp_client.ensure_tags(site_config, scope_for_post_type(post_type), names)
    except Exception as e:
        logger.warning(f"Không xử lý được tag: {e}")
        return [], f"Không thêm được tag: {e}"
    warning = None
    if len(ids) < len({t.strip().casefold() for t in names}):
        warning = f"Chỉ thêm được {len(ids)}/{len(names)} tag (xem log để biết tag nào bị bỏ qua)."
    return ids, warning


def effective_category_ids(article: dict, post_type: str) -> list[int]:
    """
    Category id đã chọn cho bài, CHỈ khi chúng thuộc đúng loại nội dung sẽ đăng.
    Id của category WooCommerce (product) và category blog (post) là 2 tập khác nhau; nếu người dùng
    chọn xong rồi đổi loại nội dung thì phải bỏ id cũ thay vì gửi id sai lên WordPress.
    Bài không ghi `category_scope` (dữ liệu cũ) được coi là hợp lệ.
    """
    scope = article.get("category_scope")
    if scope is not None and scope != scope_for_post_type(post_type):
        return []
    ids: list[int] = []
    for c in article.get("category_ids") or []:
        try:
            cid = int(c)
        except (TypeError, ValueError):
            continue
        if cid not in ids:
            ids.append(cid)
    return ids
