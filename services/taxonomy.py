"""
services/taxonomy.py — danh mục & tag: phần dùng chung (phạm vi, chuẩn hóa, tóm tắt hiển thị).

Gồm: phần dùng chung (phạm vi, chuẩn hóa, tóm tắt), cụm điều khiển danh mục/tag dạng dữ liệu thuần
(`TaxControls`), thao tác cho bài đang soạn (articles_state) và bài đã lưu (PostHistory). Phần lịch hẹn giờ
nằm ở services/schedules.py. Logic cốt lõi: core/taxonomy_service.py và core/taxonomy_ai.py.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

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


# ══ Điều khiển (dropdown danh mục + ô tag + dòng trạng thái) dưới dạng dữ liệu thuần ══════════════════

import logging
import re

from core.taxonomy_ai import suggest_taxonomy
from db import crud
from db.database import session_scope

logger = logging.getLogger(__name__)

NO_ARTICLE_MSG = "ℹ️ Tạo bài viết trước để chọn danh mục và tag."
NO_POST_MSG = "ℹ️ Chọn một bài viết để xem/sửa danh mục và tag."
POST_NOT_FOUND_MSG = "❌ Không tìm thấy bài viết."


@dataclass
class TaxControls:
    """
    Trạng thái cụm ô chọn danh mục/tag. UI chuyển thành gr.update (hoặc component khác).
    choices=None nghĩa là "giữ nguyên ô hiện tại, chỉ cập nhật dòng trạng thái" (khi lỗi/chưa chọn gì).
    """
    status: str = ""
    choices: list[tuple[str, int]] | None = None
    selected: list[int] = field(default_factory=list)
    tags: str = ""
    interactive: bool = True
    sites: list[str] | None = None   # chỉ dùng cho lịch hẹn giờ: danh sách site để đổ vào dropdown
    site: str | None = None

    @classmethod
    def empty(cls, status: str) -> "TaxControls":
        return cls(status=status, choices=[], selected=[], tags="")

    @classmethod
    def unchanged(cls, status: str) -> "TaxControls":
        return cls(status=status)


def parse_tags(text: str | None) -> list[str]:
    """'a, b\\nc' -> ['a','b','c'] (bỏ rỗng, bỏ trùng không phân biệt hoa/thường, giữ thứ tự)."""
    seen: set[str] = set()
    out: list[str] = []
    for part in re.split(r"[,\n;]", text or ""):
        tag = re.sub(r"\s+", " ", part).strip().lstrip("#").strip()
        if tag and tag.casefold() not in seen:
            seen.add(tag.casefold())
            out.append(tag)
    return out


def _controls(db, art: dict, site: str, post_type: str, status_extra: str = "") -> TaxControls:
    """Dựng điều khiển cho 1 bài/site."""
    scope = taxonomy_service.scope_for_post_type(post_type)
    choices = taxonomy_service.get_category_choices(db, site, scope)
    valid = {cid for _, cid in choices}
    selected = [cid for cid in taxonomy_service.effective_category_ids(art, post_type) if cid in valid]
    status = taxonomy_service.cache_status_text(db, site, scope)
    if status_extra:
        status = f"{status_extra}\n\n{status}"
    return TaxControls(status=status, choices=list(choices), selected=selected, tags=", ".join(art.get("tags") or []))


def controls_with_warnings(db, art: dict, site: str, post_type: str, extra: str = "", interactive: bool = True) -> TaxControls:
    """_controls + cảnh báo: lệch loại nội dung, id không còn trên website."""
    scope = scope_of(post_type)
    notes = [extra] if extra else []
    saved_ids = normalize_category_ids(art.get("category_ids"))
    saved_scope = art.get("category_scope")
    if saved_ids and saved_scope is not None and saved_scope != scope:
        names = {"product": "sản phẩm WooCommerce", "post": "bài viết Blog"}
        notes.append(
            f"⚠️ Danh mục đã lưu thuộc loại **{names.get(saved_scope, saved_scope)}** nên **không áp dụng** cho loại "
            f"**{names.get(scope, scope)}** đang chọn — hãy chọn lại danh mục cho loại này."
        )
    else:
        valid = {cid for _, cid in taxonomy_service.get_category_choices(db, site, scope)}
        missing = [i for i in saved_ids if i not in valid]
        if saved_ids and missing:
            notes.append(f"⚠️ Danh mục đã lưu không còn trong danh sách của website: {', '.join('#' + str(i) for i in missing)}.")
    c = _controls(db, art, site, post_type, "\n\n".join(notes))
    c.interactive = interactive
    return c


def ensure_cache_once(db, site_id: int, site_name: str, scope: str) -> None:
    """Lần đầu xem site chưa từng đồng bộ danh mục -> đồng bộ 1 lần (lỗi mạng chỉ bỏ qua, có nút 🔄)."""
    try:
        if crud.get_categories_fetched_at(db, site_id, scope) is None:
            taxonomy_service.sync_site_categories(db, site_name, (scope,))
    except Exception:
        logger.exception("Không đồng bộ được danh mục lần đầu")


def sync_report_text(report: dict, scope: str) -> str:
    lines = []
    for sc, label in (("product", "WooCommerce"), ("post", "Blog")):
        r = report[sc]
        lines.append(f"- {label}: ✅ {r['count']} danh mục" if r["ok"] else f"- {label}: ❌ {r['error']}")
    extra = "**Kết quả làm mới:**\n" + "\n".join(lines)
    if not report[scope]["ok"]:
        extra += "\n\n⚠️ Đang dùng danh mục cũ (nếu có) cho loại nội dung hiện tại."
    return extra


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


def ai_note(result: dict, what: str, tail: str = "hãy kiểm tra lại") -> str:
    note = f"🤖 Đã điền và **lưu** gợi ý của AI cho {what} — {tail}."
    if not result["category_ids"]:
        note += " (AI không thấy danh mục nào thật sự phù hợp.)"
    return note


# ── Bài đang soạn (tab Tạo & Đăng Bài): dữ liệu nằm trong articles_state ───────────────────────

def article_controls(articles_state: dict | None, site: str, post_type: str) -> TaxControls:
    if not articles_state or site not in articles_state:
        return TaxControls.empty(NO_ARTICLE_MSG)
    try:
        with session_scope() as db:
            return _controls(db, articles_state[site], site, post_type)
    except Exception as e:
        logger.exception("Lỗi nạp danh mục")
        return TaxControls.unchanged(f"⚠️ Không nạp được danh mục: {e}")


def set_article_categories(articles_state: dict | None, site: str, selected, post_type: str) -> None:
    """Lưu danh mục vào bài (kèm scope để không dùng nhầm id khi đổi loại nội dung)."""
    if articles_state and site in articles_state:
        art = articles_state[site]
        art["category_ids"] = [int(c) for c in (selected or [])]
        art["category_scope"] = taxonomy_service.scope_for_post_type(post_type)


def set_article_tags(articles_state: dict | None, site: str, text: str) -> None:
    if articles_state and site in articles_state:
        articles_state[site]["tags"] = parse_tags(text)


def sync_article_categories(articles_state: dict | None, site: str, post_type: str) -> TaxControls:
    """Lấy lại danh mục từ WordPress cho site đang xem (cả product và post)."""
    if not articles_state or site not in articles_state:
        return TaxControls.unchanged(NO_ARTICLE_MSG)
    try:
        with session_scope() as db:
            report = taxonomy_service.sync_site_categories(db, site)
            extra = sync_report_text(report, taxonomy_service.scope_for_post_type(post_type))
            return _controls(db, articles_state[site], site, post_type, extra)
    except Exception as e:
        logger.exception("Lỗi làm mới danh mục")
        return TaxControls.unchanged(f"❌ Lỗi làm mới danh mục: {e}")


def suggest_for_article(articles_state: dict | None, site: str, post_type: str) -> TaxControls:
    """AI gợi ý cho site đang xem (ghi đè lựa chọn hiện tại trong articles_state)."""
    if not articles_state or site not in articles_state:
        return TaxControls.unchanged(NO_ARTICLE_MSG)
    try:
        with session_scope() as db:
            art = articles_state[site]
            result = _suggest_for_site(db, art, site, post_type, allow_network=True)
            if "error" in result:
                c = _controls(db, art, site, post_type)
                c.status = f"⚠️ AI chưa gợi ý được ({result['error']}). Bạn vẫn có thể chọn tay.\n\n{c.status}"
                return c
            note = "🤖 Đã điền gợi ý của AI — hãy kiểm tra lại trước khi đăng."
            if not result["category_ids"]:
                note += " (AI không thấy danh mục nào thật sự phù hợp.)"
            return _controls(db, art, site, post_type, note)
    except Exception as e:
        logger.exception("Lỗi AI gợi ý danh mục")
        return TaxControls.unchanged(f"❌ Lỗi: {e}")


def autofill(articles_state: dict | None, post_type: str) -> dict | None:
    """
    Sau khi tạo bài: tự điền gợi ý cho MỌI site chưa có lựa chọn. Ưu tiên cache (kể cả cũ) để không làm chậm
    việc tạo bài; chỉ gọi mạng nếu site chưa có cache nào. Không bao giờ raise.
    """
    if not articles_state:
        return articles_state
    with session_scope() as db:
        for site, art in articles_state.items():
            if art.get("category_ids") or art.get("tags"):
                continue
            try:
                _suggest_for_site(db, art, site, post_type, allow_network=False)
            except Exception:
                logger.exception(f"Autofill taxonomy lỗi cho {site}")
    return articles_state


# ── Bài đã lưu (tab Kho Bài Viết): ghi thẳng vào DB ────────────────────────────────────────────

def _history_art(h) -> dict:
    return {
        "title": h.title or h.product_name or "",
        "short_description": h.short_description or "",
        "raw_html": h.raw_html or "",
        "category_ids": normalize_category_ids(loads_list(h.category_ids_json)),
        "tags": [str(t) for t in loads_list(h.tags_json)],
        "category_scope": scope_of(h.post_type),
    }


def history_controls(post_id: int | None, post_type_label: str) -> TaxControls:
    """Nạp danh mục/tag đã lưu của bài (theo loại nội dung đang chọn ở form)."""
    if not post_id:
        return TaxControls.empty(NO_POST_MSG)
    try:
        with session_scope() as db:
            h = crud.get_post_history_by_id(db, post_id)
            if not h or not h.site:
                return TaxControls.empty(POST_NOT_FOUND_MSG)
            ensure_cache_once(db, h.site_id, h.site.name, scope_of(post_type_label))
            return controls_with_warnings(db, _history_art(h), h.site.name, post_type_label)
    except Exception as e:
        logger.exception("Lỗi nạp danh mục cho bài đã lưu")
        return TaxControls.unchanged(f"⚠️ Không nạp được danh mục: {e}")


def save_history_categories(post_id: int | None, selected, post_type_label: str) -> str:
    """Ghi danh mục vào bài. Đồng thời đặt post_type của bài = loại đang chọn để phạm vi id luôn khớp."""
    if not post_id:
        return NO_POST_MSG
    try:
        with session_scope() as db:
            h = crud.get_post_history_by_id(db, post_id)
            if not h:
                return POST_NOT_FOUND_MSG
            h.category_ids_json = json.dumps(normalize_category_ids(selected))
            h.post_type = scope_of(post_type_label)
            db.commit()
            return f"💾 Đã lưu {len(normalize_category_ids(selected))} danh mục cho bài #{post_id}."
    except Exception as e:
        logger.exception("Lỗi lưu danh mục")
        return f"❌ Không lưu được danh mục: {e}"


def save_history_tags(post_id: int | None, text: str) -> str:
    if not post_id:
        return NO_POST_MSG
    try:
        with session_scope() as db:
            h = crud.get_post_history_by_id(db, post_id)
            if not h:
                return POST_NOT_FOUND_MSG
            tags = parse_tags(text)
            h.tags_json = json.dumps(tags, ensure_ascii=False)
            db.commit()
            return f"💾 Đã lưu {len(tags)} tag cho bài #{post_id}."
    except Exception as e:
        logger.exception("Lỗi lưu tag")
        return f"❌ Không lưu được tag: {e}"


def suggest_for_history(post_id: int | None, post_type_label: str) -> TaxControls:
    if not post_id:
        return TaxControls.unchanged(NO_POST_MSG)
    try:
        with session_scope() as db:
            h = crud.get_post_history_by_id(db, post_id)
            if not h or not h.site:
                return TaxControls.unchanged(POST_NOT_FOUND_MSG)
            art = _history_art(h)
            result = _suggest_for_site(db, art, h.site.name, post_type_label, allow_network=True)
            if "error" in result:
                c = controls_with_warnings(db, art, h.site.name, post_type_label)
                c.status = f"⚠️ AI chưa gợi ý được ({result['error']}). Bạn vẫn có thể chọn tay.\n\n{c.status}"
                return c
            h.category_ids_json = json.dumps(normalize_category_ids(art["category_ids"]))
            h.tags_json = json.dumps(art["tags"], ensure_ascii=False)
            h.post_type = scope_of(post_type_label)
            db.commit()
            return controls_with_warnings(db, art, h.site.name, post_type_label, ai_note(result, f"bài #{post_id}", "hãy kiểm tra lại trước khi đăng"))
    except Exception as e:
        logger.exception("Lỗi AI gợi ý cho bài đã lưu")
        return TaxControls.unchanged(f"❌ Lỗi: {e}")


def sync_for_history(post_id: int | None, post_type_label: str) -> TaxControls:
    if not post_id:
        return TaxControls.unchanged(NO_POST_MSG)
    try:
        with session_scope() as db:
            h = crud.get_post_history_by_id(db, post_id)
            if not h or not h.site:
                return TaxControls.unchanged(POST_NOT_FOUND_MSG)
            report = taxonomy_service.sync_site_categories(db, h.site.name)
            return controls_with_warnings(
                db, _history_art(h), h.site.name, post_type_label, sync_report_text(report, scope_of(post_type_label))
            )
    except Exception as e:
        logger.exception("Lỗi làm mới danh mục")
        return TaxControls.unchanged(f"❌ Lỗi làm mới danh mục: {e}")


def summarize_history(db, h, cache: dict | None = None) -> str:
    site_name = h.site.name if h.site else ""
    return summarize_selection(db, site_name, scope_of(h.post_type), loads_list(h.category_ids_json), loads_list(h.tags_json), cache)
