"""
ui/taxonomy_records.py
Danh mục (category) & tag cho bài ĐÃ LƯU (tab Kho Bài Viết) và bài ĐÃ HẸN GIỜ (tab Lịch Đăng Bài).

Khác tab Tạo bài (lưu trong articles_state), ở đây dữ liệu nằm trong DB nên mọi thao tác chọn đều
được ghi thẳng vào DB — để lúc đăng/chạy lịch không bao giờ dùng giá trị cũ.

- Bài đã lưu  : PostHistory.category_ids_json / tags_json; phạm vi (product|post) = PostHistory.post_type.
- Lịch hẹn    : ScheduledPost.article_data_json[site]['category_ids' | 'tags' | 'category_scope'];
                chỉ sửa được khi job còn 'pending'.
Mọi handler không raise ra UI.
"""
from __future__ import annotations

import json
import logging
import re

import gradio as gr

from core import taxonomy_service
from core.taxonomy_ai import category_labels
from db import crud
from db.database import SessionLocal
from ui import taxonomy_panel as tp

logger = logging.getLogger(__name__)

NO_POST_MSG = "ℹ️ Chọn một bài viết để xem/sửa danh mục và tag."
NO_JOB_MSG = "ℹ️ Chọn một lịch đăng (bấm vào dòng trong bảng hoặc nhập ID) để xem/sửa danh mục và tag."
LOCKED_MSG = "🔒 Lịch này không còn ở trạng thái **chờ** nên không thể sửa danh mục/tag."


# ── Hiển thị tóm tắt (dùng cho cột trong bảng) ───────────────────────────────

def _scope_of(post_type: str | None) -> str:
    return taxonomy_service.scope_for_post_type(post_type or "")


def _loads_list(raw: str | None) -> list:
    try:
        val = json.loads(raw or "[]")
        return val if isinstance(val, list) else []
    except Exception:
        return []


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


def summarize_history(db, h, cache: dict | None = None) -> str:
    site_name = h.site.name if h.site else ""
    return summarize_selection(db, site_name, _scope_of(h.post_type), _loads_list(h.category_ids_json), _loads_list(h.tags_json), cache)


def summarize_job(db, job, cache: dict | None = None) -> str:
    """Mỗi site 1 dòng khi job có nhiều site; 1 site thì không cần nhãn."""
    try:
        articles = json.loads(job.article_data_json or "{}")
        sites = json.loads(job.site_names_json or "[]")
    except Exception:
        return "-"
    scope = _scope_of(job.post_type)
    lines = []
    for site in sites:
        art = articles.get(site) or {}
        ids = taxonomy_service.effective_category_ids(art, job.post_type)
        text = summarize_selection(db, site, scope, ids, art.get("tags") or [], cache)
        lines.append(text if len(sites) == 1 else f"{site}: {text}")
    return "\n".join(lines) if lines else "-"


# ── Dựng ô điều khiển ────────────────────────────────────────────────────────

def build_taxonomy_widgets(title_md: str, with_site_picker: bool = False, initial_status: str = "") -> dict:
    """Tạo cụm ô chọn danh mục/tag (gọi trong ngữ cảnh gr.Blocks)."""
    widgets: dict = {}
    with gr.Group():
        gr.Markdown(title_md)
        if with_site_picker:
            widgets["site"] = gr.Dropdown(label="Website cần chỉnh", choices=[], value=None, interactive=True)
        widgets["categories"] = gr.Dropdown(
            label="Danh mục (Category)",
            choices=[],
            value=[],
            multiselect=True,
            interactive=True,
            info="Lưu ngay khi chọn. Danh sách lấy từ website (bấm 🔄 nếu thiếu).",
        )
        widgets["tags"] = gr.Textbox(
            label="Tag (cách nhau bằng dấu phẩy)",
            placeholder="VD: quạt công nghiệp, quạt hút xưởng",
            lines=1,
            info="Lưu khi nhấn Enter hoặc rời khỏi ô. Tag chưa có trên website sẽ được tạo khi đăng.",
        )
        with gr.Row():
            widgets["btn_ai"] = gr.Button("🤖 AI gợi ý danh mục & tag", size="sm")
            widgets["btn_sync"] = gr.Button("🔄 Làm mới danh mục", size="sm")
        widgets["status"] = gr.Markdown(value=initial_status)
    return widgets


def _cat_ids(selected) -> list[int]:
    out: list[int] = []
    for c in selected or []:
        try:
            cid = int(c)
        except (TypeError, ValueError):
            continue
        if cid not in out:
            out.append(cid)
    return out


def _controls_with_warnings(db, art: dict, site: str, post_type: str, extra: str = "", interactive: bool = True):
    """tp._controls + cảnh báo: lệch loại nội dung, id không còn trên website. Trả (dropdown, tags, status)."""
    scope = _scope_of(post_type)
    notes = [extra] if extra else []
    saved_ids = _cat_ids(art.get("category_ids"))
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
    drop, tags, status = tp._controls(db, art, site, post_type, "\n\n".join(notes))
    if not interactive:
        drop["interactive"] = False
    return drop, tags, status


def _ensure_cache_once(db, site_id: int, site_name: str, scope: str) -> None:
    """Lần đầu xem site chưa từng đồng bộ danh mục -> đồng bộ 1 lần (lỗi mạng chỉ bỏ qua, có nút 🔄)."""
    try:
        if crud.get_categories_fetched_at(db, site_id, scope) is None:
            taxonomy_service.sync_site_categories(db, site_name, (scope,))
    except Exception:
        logger.exception("Không đồng bộ được danh mục lần đầu")


def _sync_report_text(report: dict, scope: str) -> str:
    lines = []
    for sc, label in (("product", "WooCommerce"), ("post", "Blog")):
        r = report[sc]
        lines.append(f"- {label}: ✅ {r['count']} danh mục" if r["ok"] else f"- {label}: ❌ {r['error']}")
    extra = "**Kết quả làm mới:**\n" + "\n".join(lines)
    if not report[scope]["ok"]:
        extra += "\n\n⚠️ Đang dùng danh mục cũ (nếu có) cho loại nội dung hiện tại."
    return extra


# ══ BÀI ĐÃ LƯU (tab Kho Bài Viết) ════════════════════════════════════════════

def _history_id(choice: str | None) -> int | None:
    m = re.match(r"\s*#(\d+)\b", choice or "")
    return int(m.group(1)) if m else None


def _history_art(h) -> dict:
    return {
        "title": h.title or h.product_name or "",
        "short_description": h.short_description or "",
        "raw_html": h.raw_html or "",
        "category_ids": _cat_ids(_loads_list(h.category_ids_json)),
        "tags": [str(t) for t in _loads_list(h.tags_json)],
        "category_scope": _scope_of(h.post_type),
    }


def _history_empty(msg: str):
    return gr.update(choices=[], value=[]), "", msg


def history_load(choice: str, post_type_label: str):
    """Nạp danh mục/tag đã lưu của bài đang chọn (theo loại nội dung đang chọn ở form)."""
    post_id = _history_id(choice)
    if not post_id:
        return _history_empty(NO_POST_MSG)
    db = SessionLocal()
    try:
        h = crud.get_post_history_by_id(db, post_id)
        if not h or not h.site:
            return _history_empty("❌ Không tìm thấy bài viết.")
        _ensure_cache_once(db, h.site_id, h.site.name, _scope_of(post_type_label))
        return _controls_with_warnings(db, _history_art(h), h.site.name, post_type_label)
    except Exception as e:
        logger.exception("Lỗi nạp danh mục cho bài đã lưu")
        return gr.update(), gr.update(), f"⚠️ Không nạp được danh mục: {e}"
    finally:
        db.close()


def history_save_categories(selected, choice: str, post_type_label: str) -> str:
    """Ghi danh mục vào bài. Đồng thời đặt post_type của bài = loại đang chọn để phạm vi id luôn khớp."""
    post_id = _history_id(choice)
    if not post_id:
        return NO_POST_MSG
    db = SessionLocal()
    try:
        h = crud.get_post_history_by_id(db, post_id)
        if not h:
            return "❌ Không tìm thấy bài viết."
        h.category_ids_json = json.dumps(_cat_ids(selected))
        h.post_type = _scope_of(post_type_label)
        db.commit()
        return f"💾 Đã lưu {len(_cat_ids(selected))} danh mục cho bài #{post_id}."
    except Exception as e:
        db.rollback()
        logger.exception("Lỗi lưu danh mục")
        return f"❌ Không lưu được danh mục: {e}"
    finally:
        db.close()


def history_save_tags(text: str, choice: str) -> str:
    post_id = _history_id(choice)
    if not post_id:
        return NO_POST_MSG
    db = SessionLocal()
    try:
        h = crud.get_post_history_by_id(db, post_id)
        if not h:
            return "❌ Không tìm thấy bài viết."
        tags = tp.parse_tags(text)
        h.tags_json = json.dumps(tags, ensure_ascii=False)
        db.commit()
        return f"💾 Đã lưu {len(tags)} tag cho bài #{post_id}."
    except Exception as e:
        db.rollback()
        logger.exception("Lỗi lưu tag")
        return f"❌ Không lưu được tag: {e}"
    finally:
        db.close()


def history_ai_suggest(choice: str, post_type_label: str):
    post_id = _history_id(choice)
    if not post_id:
        return gr.update(), gr.update(), NO_POST_MSG
    db = SessionLocal()
    try:
        h = crud.get_post_history_by_id(db, post_id)
        if not h or not h.site:
            return gr.update(), gr.update(), "❌ Không tìm thấy bài viết."
        art = _history_art(h)
        result = tp._suggest_for_site(db, art, h.site.name, post_type_label, allow_network=True)
        if "error" in result:
            drop, tags, status = _controls_with_warnings(db, art, h.site.name, post_type_label)
            return drop, tags, f"⚠️ AI chưa gợi ý được ({result['error']}). Bạn vẫn có thể chọn tay.\n\n{status}"
        h.category_ids_json = json.dumps(_cat_ids(art["category_ids"]))
        h.tags_json = json.dumps(art["tags"], ensure_ascii=False)
        h.post_type = _scope_of(post_type_label)
        db.commit()
        note = f"🤖 Đã điền và **lưu** gợi ý của AI cho bài #{post_id} — hãy kiểm tra lại trước khi đăng."
        if not result["category_ids"]:
            note += " (AI không thấy danh mục nào thật sự phù hợp.)"
        return _controls_with_warnings(db, art, h.site.name, post_type_label, note)
    except Exception as e:
        db.rollback()
        logger.exception("Lỗi AI gợi ý cho bài đã lưu")
        return gr.update(), gr.update(), f"❌ Lỗi: {e}"
    finally:
        db.close()


def history_sync(choice: str, post_type_label: str):
    post_id = _history_id(choice)
    if not post_id:
        return gr.update(), gr.update(), NO_POST_MSG
    db = SessionLocal()
    try:
        h = crud.get_post_history_by_id(db, post_id)
        if not h or not h.site:
            return gr.update(), gr.update(), "❌ Không tìm thấy bài viết."
        report = taxonomy_service.sync_site_categories(db, h.site.name)
        return _controls_with_warnings(
            db, _history_art(h), h.site.name, post_type_label, _sync_report_text(report, _scope_of(post_type_label))
        )
    except Exception as e:
        logger.exception("Lỗi làm mới danh mục")
        return gr.update(), gr.update(), f"❌ Lỗi làm mới danh mục: {e}"
    finally:
        db.close()


# ══ LỊCH HẸN GIỜ (tab Lịch Đăng Bài) ═════════════════════════════════════════

def _job_id(raw: str | None) -> int | None:
    try:
        return int(str(raw or "").strip().lstrip("#"))
    except ValueError:
        return None


def _job_articles(job) -> dict:
    try:
        data = json.loads(job.article_data_json or "{}")
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _job_sites(job) -> list[str]:
    return [str(s) for s in _loads_list(job.site_names_json)]


def _job_art(job, site: str) -> dict:
    art = dict(_job_articles(job).get(site) or {})
    art.setdefault("category_scope", _scope_of(job.post_type))
    return art


def _write_job_art(db, job, site: str, **fields) -> None:
    """Ghi đè một số trường của bài cho `site` trong article_data_json (giữ nguyên phần còn lại)."""
    articles = _job_articles(job)
    art = articles.setdefault(site, {})
    art.update(fields)
    art["category_scope"] = _scope_of(job.post_type)
    job.article_data_json = json.dumps(articles, ensure_ascii=False)
    db.commit()


def _job_context(db, job_id_raw: str, site: str | None):
    """(job, lỗi) — kiểm tra job tồn tại, còn pending và site thuộc job."""
    job_id = _job_id(job_id_raw)
    if job_id is None:
        return None, NO_JOB_MSG
    job = crud.get_scheduled_post(db, job_id)
    if not job:
        return None, f"❌ Không tìm thấy lịch đăng #{job_id}."
    if job.status != "pending":
        return job, LOCKED_MSG
    if site is not None and site not in _job_sites(job):
        return job, "❌ Website này không thuộc lịch đăng đang chọn."
    return job, None


def _job_empty(msg: str):
    return gr.update(choices=[], value=None), gr.update(choices=[], value=[]), "", msg


def sched_load(job_id_raw: str):
    """Nạp lịch được chọn: danh sách site của lịch + danh mục/tag của site đầu tiên."""
    job_id = _job_id(job_id_raw)
    if job_id is None:
        return _job_empty(NO_JOB_MSG)
    db = SessionLocal()
    try:
        job = crud.get_scheduled_post(db, job_id)
        if not job:
            return _job_empty(f"❌ Không tìm thấy lịch đăng #{job_id}.")
        sites = _job_sites(job)
        if not sites:
            return _job_empty("ℹ️ Lịch này không có website nào.")
        site_update = gr.update(choices=sites, value=sites[0])
        drop, tags, status = _sched_controls(db, job, sites[0])
        return site_update, drop, tags, status
    except Exception as e:
        logger.exception("Lỗi nạp danh mục cho lịch đăng")
        return gr.update(), gr.update(), gr.update(), f"⚠️ Không nạp được: {e}"
    finally:
        db.close()


def _sched_controls(db, job, site: str, extra: str = ""):
    pending = job.status == "pending"
    if pending:
        _ensure_cache_once(db, _site_id(db, site), site, _scope_of(job.post_type))
    notes = extra if pending else (f"{LOCKED_MSG}\n\n{extra}" if extra else LOCKED_MSG)
    drop, tags, status = _controls_with_warnings(db, _job_art(job, site), site, job.post_type, notes, interactive=pending)
    return drop, gr.update(value=tags, interactive=pending), status


def _site_id(db, site: str) -> int:
    s = crud.get_site_by_name(db, site)
    return s.id if s else -1


def sched_site_change(job_id_raw: str, site: str):
    job_id = _job_id(job_id_raw)
    if job_id is None or not site:
        return gr.update(), gr.update(), NO_JOB_MSG
    db = SessionLocal()
    try:
        job = crud.get_scheduled_post(db, job_id)
        if not job or site not in _job_sites(job):
            return gr.update(choices=[], value=[]), "", "❌ Website không thuộc lịch đăng này."
        return _sched_controls(db, job, site)
    except Exception as e:
        logger.exception("Lỗi đổi website trong lịch đăng")
        return gr.update(), gr.update(), f"⚠️ Lỗi: {e}"
    finally:
        db.close()


def sched_save_categories(selected, job_id_raw: str, site: str) -> str:
    db = SessionLocal()
    try:
        job, err = _job_context(db, job_id_raw, site)
        if err:
            return err
        ids = _cat_ids(selected)
        _write_job_art(db, job, site, category_ids=ids)
        return f"💾 Đã lưu {len(ids)} danh mục cho lịch #{job.id} · {site}."
    except Exception as e:
        db.rollback()
        logger.exception("Lỗi lưu danh mục của lịch đăng")
        return f"❌ Không lưu được danh mục: {e}"
    finally:
        db.close()


def sched_save_tags(text: str, job_id_raw: str, site: str) -> str:
    db = SessionLocal()
    try:
        job, err = _job_context(db, job_id_raw, site)
        if err:
            return err
        tags = tp.parse_tags(text)
        _write_job_art(db, job, site, tags=tags)
        return f"💾 Đã lưu {len(tags)} tag cho lịch #{job.id} · {site}."
    except Exception as e:
        db.rollback()
        logger.exception("Lỗi lưu tag của lịch đăng")
        return f"❌ Không lưu được tag: {e}"
    finally:
        db.close()


def sched_ai_suggest(job_id_raw: str, site: str):
    db = SessionLocal()
    try:
        job, err = _job_context(db, job_id_raw, site)
        if err:
            return gr.update(), gr.update(), err
        art = _job_art(job, site)
        result = tp._suggest_for_site(db, art, site, job.post_type, allow_network=True)
        if "error" in result:
            drop, tags, status = _sched_controls(db, job, site)
            return drop, tags, f"⚠️ AI chưa gợi ý được ({result['error']}). Bạn vẫn có thể chọn tay.\n\n{status}"
        _write_job_art(db, job, site, category_ids=_cat_ids(art["category_ids"]), tags=art["tags"])
        note = f"🤖 Đã điền và **lưu** gợi ý của AI cho lịch #{job.id} · {site} — hãy kiểm tra lại."
        if not result["category_ids"]:
            note += " (AI không thấy danh mục nào thật sự phù hợp.)"
        return _sched_controls(db, job, site, note)
    except Exception as e:
        db.rollback()
        logger.exception("Lỗi AI gợi ý cho lịch đăng")
        return gr.update(), gr.update(), f"❌ Lỗi: {e}"
    finally:
        db.close()


def sched_sync(job_id_raw: str, site: str):
    db = SessionLocal()
    try:
        job, err = _job_context(db, job_id_raw, site)
        if err and err != LOCKED_MSG:  # job không tồn tại / site sai; job đã khóa vẫn cho làm mới danh sách (chỉ xem)
            return gr.update(), gr.update(), err
        report = taxonomy_service.sync_site_categories(db, site)
        return _sched_controls(db, job, site, _sync_report_text(report, _scope_of(job.post_type)))
    except Exception as e:
        logger.exception("Lỗi làm mới danh mục")
        return gr.update(), gr.update(), f"❌ Lỗi làm mới danh mục: {e}"
    finally:
        db.close()
