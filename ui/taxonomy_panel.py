"""
ui/taxonomy_panel.py
Ô chọn Danh mục (Category) + Tag cho website đang xem trong tab Tạo & Đăng Bài.

Lựa chọn được lưu trong articles_state[site]['category_ids' | 'tags' | 'category_scope'] — cùng chỗ với
tiêu đề/HTML — nên tự đi theo luồng Đăng ngay / Lưu nháp / Hẹn giờ mà không cần thêm state riêng.
Mọi handler đều không raise ra UI.
"""
from __future__ import annotations

import logging
import re

import gradio as gr

from core import taxonomy_service
from core.taxonomy_ai import suggest_taxonomy
from db.database import SessionLocal

logger = logging.getLogger(__name__)

NO_ARTICLE_MSG = "ℹ️ Tạo bài viết trước để chọn danh mục và tag."


def parse_tags(text: str) -> list[str]:
    """'a, b\\nc' -> ['a','b','c'] (bỏ rỗng, bỏ trùng không phân biệt hoa/thường, giữ thứ tự)."""
    seen: set[str] = set()
    out: list[str] = []
    for part in re.split(r"[,\n;]", text or ""):
        tag = re.sub(r"\s+", " ", part).strip().lstrip("#").strip()
        if tag and tag.casefold() not in seen:
            seen.add(tag.casefold())
            out.append(tag)
    return out


def _controls(db, art: dict, site: str, post_type: str, status_extra: str = ""):
    """Dựng (dropdown_update, tags_text, status_md) cho 1 bài/site."""
    scope = taxonomy_service.scope_for_post_type(post_type)
    choices = taxonomy_service.get_category_choices(db, site, scope)
    valid = {cid for _, cid in choices}
    selected = [cid for cid in taxonomy_service.effective_category_ids(art, post_type) if cid in valid]
    status = taxonomy_service.cache_status_text(db, site, scope)
    if status_extra:
        status = f"{status_extra}\n\n{status}"
    return gr.update(choices=choices, value=selected), ", ".join(art.get("tags") or []), status


def refresh_taxonomy_controls(articles_state, current_site, post_type):
    """Đồng bộ ô chọn với bài của site đang xem (gọi khi tạo bài / đổi site / đổi loại nội dung)."""
    if not articles_state or current_site not in articles_state:
        return gr.update(choices=[], value=[]), "", NO_ARTICLE_MSG
    db = SessionLocal()
    try:
        return _controls(db, articles_state[current_site], current_site, post_type)
    except Exception as e:
        logger.exception("Lỗi nạp danh mục")
        return gr.update(), gr.update(), f"⚠️ Không nạp được danh mục: {e}"
    finally:
        db.close()


def on_categories_input(selected, current_site, articles_state, post_type):
    """Người dùng đổi danh mục -> lưu vào bài (kèm scope để không dùng nhầm id khi đổi loại nội dung)."""
    if articles_state and current_site in articles_state:
        art = articles_state[current_site]
        art["category_ids"] = [int(c) for c in (selected or [])]
        art["category_scope"] = taxonomy_service.scope_for_post_type(post_type)
    return articles_state


def on_tags_input(text, current_site, articles_state):
    if articles_state and current_site in articles_state:
        articles_state[current_site]["tags"] = parse_tags(text)
    return articles_state


def on_sync_categories(articles_state, current_site, post_type):
    """Nút 🔄: lấy lại danh mục từ WordPress cho site đang xem (cả product và post)."""
    if not articles_state or current_site not in articles_state:
        return gr.update(), gr.update(), NO_ARTICLE_MSG
    db = SessionLocal()
    try:
        report = taxonomy_service.sync_site_categories(db, current_site)
        scope = taxonomy_service.scope_for_post_type(post_type)
        lines = []
        for sc, label in (("product", "WooCommerce"), ("post", "Blog")):
            r = report[sc]
            lines.append(f"- {label}: ✅ {r['count']} danh mục" if r["ok"] else f"- {label}: ❌ {r['error']}")
        extra = "**Kết quả làm mới:**\n" + "\n".join(lines)
        if not report[scope]["ok"]:
            extra += "\n\n⚠️ Đang dùng danh mục cũ (nếu có) cho loại nội dung hiện tại."
        return _controls(db, articles_state[current_site], current_site, post_type, extra)
    except Exception as e:
        logger.exception("Lỗi làm mới danh mục")
        return gr.update(), gr.update(), f"❌ Lỗi làm mới danh mục: {e}"
    finally:
        db.close()


def _suggest_for_site(db, art: dict, site: str, post_type: str, allow_network: bool) -> dict:
    """Gợi ý + ghi vào `art`. allow_network=True cho phép đồng bộ khi cache cũ; False chỉ đồng bộ nếu chưa có cache."""
    scope = taxonomy_service.scope_for_post_type(post_type)
    if allow_network:
        taxonomy_service.ensure_fresh_categories(db, site, scope)
    elif not taxonomy_service.get_categories(db, site, scope):
        taxonomy_service.ensure_fresh_categories(db, site, scope)
    cats = taxonomy_service.get_categories(db, site, scope)
    result = suggest_taxonomy(art.get("title", ""), art.get("short_description", ""), art.get("raw_html", ""), cats)
    if "error" not in result:
        art["category_ids"] = result["category_ids"]
        art["category_scope"] = scope
        art["tags"] = result["tags"]
    return result


def on_ai_suggest(articles_state, current_site, post_type):
    """Nút 🤖: AI gợi ý cho site đang xem (ghi đè lựa chọn hiện tại)."""
    if not articles_state or current_site not in articles_state:
        return articles_state, gr.update(), gr.update(), NO_ARTICLE_MSG
    db = SessionLocal()
    try:
        art = articles_state[current_site]
        result = _suggest_for_site(db, art, current_site, post_type, allow_network=True)
        if "error" in result:
            drop, tags, status = _controls(db, art, current_site, post_type)
            return articles_state, drop, tags, f"⚠️ AI chưa gợi ý được ({result['error']}). Bạn vẫn có thể chọn tay.\n\n{status}"
        note = "🤖 Đã điền gợi ý của AI — hãy kiểm tra lại trước khi đăng."
        if not result["category_ids"]:
            note += " (AI không thấy danh mục nào thật sự phù hợp.)"
        drop, tags, status = _controls(db, art, current_site, post_type, note)
        return articles_state, drop, tags, status
    except Exception as e:
        logger.exception("Lỗi AI gợi ý danh mục")
        return articles_state, gr.update(), gr.update(), f"❌ Lỗi: {e}"
    finally:
        db.close()


def autofill_taxonomy(articles_state, post_type):
    """
    Sau khi tạo bài: tự điền gợi ý cho MỌI site chưa có lựa chọn. Ưu tiên cache (kể cả cũ) để không làm chậm
    việc tạo bài; chỉ gọi mạng nếu site chưa có cache nào. Không bao giờ raise.
    """
    if not articles_state:
        return articles_state
    db = SessionLocal()
    try:
        for site, art in articles_state.items():
            if art.get("category_ids") or art.get("tags"):
                continue
            try:
                _suggest_for_site(db, art, site, post_type, allow_network=False)
            except Exception:
                logger.exception(f"Autofill taxonomy lỗi cho {site}")
    finally:
        db.close()
    return articles_state
