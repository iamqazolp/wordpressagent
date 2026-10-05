"""
services/schedules.py — lịch đăng bài hẹn giờ: tạo, liệt kê, hủy, xóa và sửa danh mục/tag của lịch còn chờ.

Tách khỏi ui/tab_scheduler.py, ui/taxonomy_records.py và schedule_post_ui. Trả dataclass thuần (không ORM).
Thời gian hẹn luôn là giờ GMT+7 dạng naive (xem core/timeutil.py).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime

from core import taxonomy_service
from core import scheduler as core_scheduler
from core.timeutil import TZ_LABEL, fmt_vn, now_vn
from db import crud
from db.database import session_scope
from services import taxonomy as taxonomy_svc
from services.errors import ServiceError
from services.taxonomy import (
    TaxControls,
    controls_with_warnings,
    ensure_cache_once,
    loads_list,
    normalize_category_ids,
    parse_tags,
    scope_of,
    summarize_selection,
    sync_report_text,
)

logger = logging.getLogger(__name__)

NO_JOB_MSG = "ℹ️ Chọn một lịch đăng (bấm vào dòng trong bảng hoặc nhập ID) để xem/sửa danh mục và tag."
LOCKED_MSG = "🔒 Lịch này không còn ở trạng thái **chờ** nên không thể sửa danh mục/tag."

STATUS_LABELS = {
    "pending": "⏳ Đang chờ",
    "running": "⚡ Đang đăng...",
    "completed": "✅ Hoàn tất",
    "partially_completed": "⚠️ Xong một phần",
    "failed": "❌ Thất bại",
    "cancelled": "🚫 Đã hủy",
}


# ── Tạo lịch ─────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ScheduleResult:
    job_id: int
    product_name: str
    scheduled_time: datetime
    site_names: list[str]
    post_status: str


def schedule_post(
    articles: dict,
    image_paths: list[str],
    post_status: str,
    post_type: str,
    scheduled_time: datetime,
    regular_price: str = "",
    sale_price: str = "",
) -> ScheduleResult:
    """Tạo lịch đăng tự động. Raise ServiceError nếu thiếu bài hoặc thời gian không ở tương lai."""
    if not articles:
        raise ServiceError("Chưa có nội dung bài viết nào để lên lịch! Hãy tạo bài viết trước.")
    now = now_vn()
    if scheduled_time <= now:
        raise ServiceError(
            f"Thời gian hẹn ({scheduled_time.strftime('%d/%m/%Y %H:%M')} {TZ_LABEL}) phải ở trong tương lai "
            f"(sau hiện tại: {now.strftime('%d/%m/%Y %H:%M')} {TZ_LABEL})."
        )
    first = articles[next(iter(articles))]
    product_name = first.get("product_name") or first.get("title", "Sản phẩm")

    job_id = core_scheduler.schedule_publish_job(
        product_name=product_name,
        articles=articles,
        site_names=list(articles.keys()),
        scheduled_time=scheduled_time,
        post_type=post_type,
        post_status=post_status,
        regular_price=regular_price,
        sale_price=sale_price,
        image_files=image_paths,
    )
    return ScheduleResult(job_id, product_name, scheduled_time, list(articles.keys()), post_status)


# ── Danh sách / hủy / xóa ────────────────────────────────────────────────────

@dataclass(frozen=True)
class JobRow:
    id: int
    product_name: str
    sites: str
    taxonomy_summary: str
    scheduled_time: str      # đã định dạng GMT+7
    status: str              # nhãn hiển thị
    executed_at: str         # đã định dạng GMT+7
    result_message: str


def summarize_job(db, job, cache: dict | None = None) -> str:
    """Mỗi site 1 dòng khi job có nhiều site; 1 site thì không cần nhãn."""
    try:
        articles = json.loads(job.article_data_json or "{}")
        sites = json.loads(job.site_names_json or "[]")
    except Exception:
        return "-"
    scope = scope_of(job.post_type)
    lines = []
    for site in sites:
        art = articles.get(site) or {}
        ids = taxonomy_service.effective_category_ids(art, job.post_type)
        text = summarize_selection(db, site, scope, ids, art.get("tags") or [], cache)
        lines.append(text if len(sites) == 1 else f"{site}: {text}")
    return "\n".join(lines) if lines else "-"


def list_jobs(limit: int = 100) -> list[JobRow]:
    with session_scope() as db:
        jobs = crud.get_scheduled_posts(db, limit=limit)
        rows: list[JobRow] = []
        tax_cache: dict = {}  # tên danh mục theo (site, loại) — tránh truy vấn lặp cho từng dòng
        for j in jobs:
            try:
                sites_str = ", ".join(json.loads(j.site_names_json))
            except Exception:
                sites_str = j.site_names_json or "-"
            rows.append(JobRow(
                id=j.id,
                product_name=j.product_name,
                sites=sites_str,
                taxonomy_summary=summarize_job(db, j, tax_cache),
                scheduled_time=fmt_vn(j.scheduled_time),
                status=STATUS_LABELS.get(j.status, j.status),
                executed_at=fmt_vn(j.executed_at),
                result_message=j.result_message or "-",
            ))
        return rows


def parse_job_id(raw) -> int | None:
    try:
        return int(str(raw if raw is not None else "").strip().lstrip("#"))
    except ValueError:
        return None


def cancel_job(job_id: int) -> bool:
    return bool(core_scheduler.cancel_scheduled_job(job_id))


def delete_job(job_id: int) -> bool:
    """Hủy job trên APScheduler (nếu còn) rồi xóa bản ghi. True nếu có bản ghi bị xóa."""
    core_scheduler.cancel_scheduled_job(job_id)
    with session_scope() as db:
        return bool(crud.delete_scheduled_post(db, job_id))


# ── Danh mục & tag của lịch còn chờ ──────────────────────────────────────────

def _job_articles(job) -> dict:
    try:
        data = json.loads(job.article_data_json or "{}")
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _job_sites(job) -> list[str]:
    return [str(s) for s in loads_list(job.site_names_json)]


def _job_art(job, site: str) -> dict:
    art = dict(_job_articles(job).get(site) or {})
    art.setdefault("category_scope", scope_of(job.post_type))
    return art


def _write_job_art(db, job, site: str, **fields) -> None:
    """Ghi đè một số trường của bài cho `site` trong article_data_json (giữ nguyên phần còn lại)."""
    articles = _job_articles(job)
    art = articles.setdefault(site, {})
    art.update(fields)
    art["category_scope"] = scope_of(job.post_type)
    job.article_data_json = json.dumps(articles, ensure_ascii=False)
    db.commit()


def _job_context(db, job_id_raw, site: str | None):
    """(job, lỗi) — kiểm tra job tồn tại, còn pending và site thuộc job."""
    job_id = parse_job_id(job_id_raw)
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


def _site_id(db, site: str) -> int:
    s = crud.get_site_by_name(db, site)
    return s.id if s else -1


def _job_controls(db, job, site: str, extra: str = "") -> TaxControls:
    pending = job.status == "pending"
    if pending:
        ensure_cache_once(db, _site_id(db, site), site, scope_of(job.post_type))
    notes = extra if pending else (f"{LOCKED_MSG}\n\n{extra}" if extra else LOCKED_MSG)
    return controls_with_warnings(db, _job_art(job, site), site, job.post_type, notes, interactive=pending)


def job_controls(job_id_raw) -> TaxControls:
    """Nạp lịch được chọn: danh sách site của lịch + danh mục/tag của site đầu tiên."""
    job_id = parse_job_id(job_id_raw)
    if job_id is None:
        return TaxControls.empty(NO_JOB_MSG)
    try:
        with session_scope() as db:
            job = crud.get_scheduled_post(db, job_id)
            if not job:
                return TaxControls.empty(f"❌ Không tìm thấy lịch đăng #{job_id}.")
            sites = _job_sites(job)
            if not sites:
                return TaxControls.empty("ℹ️ Lịch này không có website nào.")
            c = _job_controls(db, job, sites[0])
            c.sites, c.site = sites, sites[0]
            return c
    except Exception as e:
        logger.exception("Lỗi nạp danh mục cho lịch đăng")
        return TaxControls.unchanged(f"⚠️ Không nạp được: {e}")


def job_site_controls(job_id_raw, site: str) -> TaxControls:
    job_id = parse_job_id(job_id_raw)
    if job_id is None or not site:
        return TaxControls.unchanged(NO_JOB_MSG)
    try:
        with session_scope() as db:
            job = crud.get_scheduled_post(db, job_id)
            if not job or site not in _job_sites(job):
                return TaxControls.empty("❌ Website không thuộc lịch đăng này.")
            return _job_controls(db, job, site)
    except Exception as e:
        logger.exception("Lỗi đổi website trong lịch đăng")
        return TaxControls.unchanged(f"⚠️ Lỗi: {e}")


def save_job_categories(selected, job_id_raw, site: str) -> str:
    try:
        with session_scope() as db:
            job, err = _job_context(db, job_id_raw, site)
            if err:
                return err
            ids = normalize_category_ids(selected)
            _write_job_art(db, job, site, category_ids=ids)
            return f"💾 Đã lưu {len(ids)} danh mục cho lịch #{job.id} · {site}."
    except Exception as e:
        logger.exception("Lỗi lưu danh mục của lịch đăng")
        return f"❌ Không lưu được danh mục: {e}"


def save_job_tags(text: str, job_id_raw, site: str) -> str:
    try:
        with session_scope() as db:
            job, err = _job_context(db, job_id_raw, site)
            if err:
                return err
            tags = parse_tags(text)
            _write_job_art(db, job, site, tags=tags)
            return f"💾 Đã lưu {len(tags)} tag cho lịch #{job.id} · {site}."
    except Exception as e:
        logger.exception("Lỗi lưu tag của lịch đăng")
        return f"❌ Không lưu được tag: {e}"


def suggest_for_job(job_id_raw, site: str) -> TaxControls:
    try:
        with session_scope() as db:
            job, err = _job_context(db, job_id_raw, site)
            if err:
                return TaxControls.unchanged(err)
            art = _job_art(job, site)
            result = taxonomy_svc._suggest_for_site(db, art, site, job.post_type, allow_network=True)
            if "error" in result:
                c = _job_controls(db, job, site)
                c.status = f"⚠️ AI chưa gợi ý được ({result['error']}). Bạn vẫn có thể chọn tay.\n\n{c.status}"
                return c
            _write_job_art(db, job, site, category_ids=normalize_category_ids(art["category_ids"]), tags=art["tags"])
            return _job_controls(db, job, site, taxonomy_svc.ai_note(result, f"lịch #{job.id} · {site}"))
    except Exception as e:
        logger.exception("Lỗi AI gợi ý cho lịch đăng")
        return TaxControls.unchanged(f"❌ Lỗi: {e}")


def sync_for_job(job_id_raw, site: str) -> TaxControls:
    try:
        with session_scope() as db:
            job, err = _job_context(db, job_id_raw, site)
            if err and err != LOCKED_MSG:  # job không tồn tại / site sai; job đã khóa vẫn cho làm mới danh sách (chỉ xem)
                return TaxControls.unchanged(err)
            report = taxonomy_service.sync_site_categories(db, site)
            return _job_controls(db, job, site, sync_report_text(report, scope_of(job.post_type)))
    except Exception as e:
        logger.exception("Lỗi làm mới danh mục")
        return TaxControls.unchanged(f"❌ Lỗi làm mới danh mục: {e}")


def schedule_post_per_site(
    articles: dict,
    image_paths: list[str],
    post_status: str,
    post_type: str,
    times: dict[str, datetime],
    regular_price: str = "",
    sale_price: str = "",
) -> list[ScheduleResult]:
    """Hẹn giờ riêng cho từng website: mỗi website một lịch với giờ của nó. Website không có giờ bị bỏ qua."""
    results = []
    for site, when in times.items():
        if site in articles and when is not None:
            results.append(schedule_post({site: articles[site]}, image_paths, post_status, post_type, when,
                                         regular_price, sale_price))
    if not results:
        raise ServiceError("Chưa có website nào được chọn giờ đăng.")
    return results
