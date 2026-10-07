from __future__ import annotations

import json
import logging
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger

from db import crud, database
from core.pipeline import publish_articles
from core.timeutil import now_vn, TZ_NAME
from core import taxonomy_service, wp_client

logger = logging.getLogger(__name__)

class _SessionLocalProxy:
    def __call__(self, *args, **kwargs):
        return database.SessionLocal(*args, **kwargs)

SessionLocal = _SessionLocalProxy()

# Đủ lớn để nạp hết lịch chờ khi khởi động (crud mặc định chỉ lấy 100 bản ghi)
_MAX_JOBS = 100_000


class ScheduleSyncError(Exception):
    """Không đổi được trạng thái bài trên WordPress khi hủy/xóa lịch; lịch được giữ nguyên để thử lại."""


_scheduler: BackgroundScheduler | None = None


def get_scheduler() -> BackgroundScheduler:
    """Khởi tạo hoặc lấy BackgroundScheduler singleton."""
    global _scheduler
    if _scheduler is None:
        # misfire_grace_time=None: máy ngủ/bận đúng giờ hẹn thì vẫn chạy khi thức dậy (mặc định chỉ trễ được 1 giây)
        _scheduler = BackgroundScheduler(timezone=TZ_NAME, job_defaults={"misfire_grace_time": None, "coalesce": True})
        _scheduler.start()
        logger.info("✓ APScheduler đã được khởi động.")
    return _scheduler


def _add_aps_job(job_id: int, run_date: datetime | None = None, publish_missing: bool = True) -> None:
    """Hẹn APScheduler chạy job lúc `run_date` (None = chạy ngay trong luồng nền)."""
    get_scheduler().add_job(
        func=execute_scheduled_job,
        trigger=DateTrigger(run_date=run_date) if run_date else None,
        args=[job_id, publish_missing],
        id=f"wp_post_job_{job_id}",
        replace_existing=True,
    )


def _remove_aps_job(job_id: int) -> None:
    try:
        get_scheduler().remove_job(f"wp_post_job_{job_id}")
    except Exception:
        pass


def _is_publish(post_status: str | None) -> bool:
    # "future": job lưu bởi bản trước, khi mọi lịch đều tạo bài hẹn giờ trên WordPress
    return (post_status or "") in ("publish", "future")


def _load_articles(job) -> dict:
    try:
        data = json.loads(job.article_data_json or "{}")
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _load_list(raw: str | None) -> list:
    try:
        data = json.loads(raw or "[]")
    except Exception:
        return []
    return data if isinstance(data, list) else []


def _site_of(db, site_name: str, art: dict):
    """Site theo site_id đã lưu (vẫn đúng sau khi đổi tên website), dự phòng tra theo tên."""
    site_id = art.get("site_id")
    site = crud.get_site(db, int(site_id)) if site_id else None
    return site or crud.get_site_by_name(db, site_name)


def _site_config_of(db, site_name: str, art: dict) -> dict | None:
    site = _site_of(db, site_name, art)
    return crud.get_site_config(db, site.id) if site else None


def _record_history(db, job, site_name: str, art: dict, outcome: dict, status: str):
    """Cập nhật bản ghi kho của bài (history_id) hoặc tạo mới nếu chưa có. Trả bản ghi (hoặc None)."""
    wp_post_id = str(outcome["post_id"]) if outcome.get("post_id") else None
    hist = crud.get_post_history_by_id(db, int(art["history_id"])) if art.get("history_id") else None
    if hist:
        hist.status = status
        hist.wp_post_id = wp_post_id or hist.wp_post_id
        hist.wp_post_url = outcome.get("post_url") or hist.wp_post_url
        hist.error_message = outcome.get("error")
        if status in ("published", "draft"):
            hist.published_at = now_vn()
        db.commit()
        return hist
    site = _site_of(db, site_name, art)
    if not site:
        return None
    return crud.create_post_history(
        db,
        site_id=site.id,
        product_name=job.product_name,
        title=art.get("title", job.product_name),
        raw_html=art.get("raw_html", ""),
        post_type=job.post_type,
        status=status,
        wp_post_id=wp_post_id,
        wp_post_url=outcome.get("post_url"),
        error_message=outcome.get("error"),
        category_ids_json=json.dumps(taxonomy_service.effective_category_ids(art, job.post_type)),
        tags_json=json.dumps(art.get("tags") or [], ensure_ascii=False),
    )


def _confirm_scheduled_post(site_config: dict | None, scope: str, art: dict) -> dict:
    """
    Đến giờ hẹn: kiểm tra bài đã hẹn giờ trên WordPress. WP-Cron chỉ chạy khi có người truy cập site
    nên hay bị nhỡ lịch -> bài còn 'future' thì chủ động chuyển sang 'publish'.
    """
    wp_id = art["post_id"]
    out = {"ok": False, "post_id": wp_id, "post_url": art.get("post_url"), "error": None}
    if not site_config:
        out["error"] = "Không tìm thấy cấu hình website"
        return out
    try:
        item = wp_client.get_item(site_config, scope, wp_id)
        if item is None:
            out["error"] = f"Bài #{wp_id} không còn trên WordPress"
            return out
        if item.get("status") == "future":
            item = wp_client.update_item_status(site_config, scope, wp_id, "publish")
    except Exception as e:
        # Bài đã ở dạng hẹn giờ trên WordPress nên nhiều khả năng vẫn tự lên; chỉ ghi chú, không coi là lỗi
        logger.warning(f"Không kiểm tra được bài #{wp_id} trên WordPress: {e}")
        out.update(ok=True, note=f"chưa kiểm tra được bài #{wp_id} ({e})")
        return out
    status = item.get("status")
    if status not in ("publish", "future"):  # 'future' còn lại: lệch giờ máy chủ, WordPress sẽ tự đăng
        out["error"] = f"Bài #{wp_id} đang ở trạng thái '{status}' trên WordPress"
        return out
    out.update(ok=True, post_url=item.get("url") or out["post_url"])
    return out


def execute_scheduled_job(job_id: int, publish_missing: bool = True):
    """
    Chạy khi đến giờ hẹn; mỗi website xử lý riêng:
    - đã có bài hẹn giờ trên WordPress (post_id): xác nhận bài đã lên (xem _confirm_scheduled_post);
    - chưa có (lịch đăng nháp, hoặc tạo bài lúc đặt lịch bị lỗi): đăng ngay.
      `publish_missing=False` (lịch quá hạn khi ứng dụng tắt) thì không đăng muộn mà ghi nhỡ lịch.
    """
    logger.info(f"⏰ Bắt đầu thực thi scheduled job #{job_id}...")
    db = SessionLocal()
    try:
        job = crud.get_scheduled_post(db, job_id)
        if not job:
            logger.warning(f"Không tìm thấy scheduled job #{job_id}")
            return

        if job.status != "pending":
            logger.info(f"Job #{job_id} đang ở trạng thái '{job.status}'. Bỏ qua.")
            return

        crud.update_scheduled_post(db, job_id, status="running")

        articles = _load_articles(job)
        site_names = [s for s in _load_list(job.site_names_json) if isinstance(articles.get(s), dict)]
        scope = taxonomy_service.scope_for_post_type(job.post_type)
        go_live = _is_publish(job.post_status)

        outcomes: dict[str, dict] = {}
        missing: list[str] = []
        for s_name in site_names:
            art = articles[s_name]
            if art.get("post_id"):
                outcomes[s_name] = _confirm_scheduled_post(_site_config_of(db, s_name, art), scope, art)
            else:
                missing.append(s_name)

        if missing and publish_missing:
            results = publish_articles(
                articles={s: articles[s] for s in missing},
                image_files=_load_list(job.image_paths_json),
                site_configs={s: _site_config_of(db, s, articles[s]) for s in missing},
                post_type=job.post_type,
                post_status="publish" if go_live else "draft",
                regular_price=job.regular_price or "",
                sale_price=job.sale_price or "",
            )
            for res in results:
                outcomes[res.get("site_name", "")] = {
                    "ok": bool(res.get("success")), "post_id": res.get("post_id"),
                    "post_url": res.get("post_url"), "error": res.get("error"),
                }
        else:
            for s_name in missing:
                outcomes[s_name] = {"ok": False, "error": "Bị nhỡ lịch khi ứng dụng tắt."}

        live_status = "published" if go_live else "draft"
        for s_name, out in outcomes.items():
            art = articles.get(s_name)
            if isinstance(art, dict):
                _record_history(db, job, s_name, art, out, live_status if out["ok"] else "failed")

        success_count = sum(1 for o in outcomes.values() if o["ok"])
        total_count = len(outcomes)
        if total_count and success_count == total_count:
            final_status = "completed"
        else:
            final_status = "failed" if success_count == 0 else "partially_completed"
        notes = [f"{s}: {o['error']}" for s, o in outcomes.items() if o.get("error")]
        notes += [f"{s}: {o['note']}" for s, o in outcomes.items() if o.get("note")]
        summary_msg = f"Đã đăng thành công {success_count}/{total_count} website."
        if notes:
            summary_msg += " " + "; ".join(notes)

        crud.update_scheduled_post(
            db,
            job_id,
            status=final_status,
            result_message=summary_msg,
            executed_at=now_vn(),
        )
        logger.info(f"✓ Hoàn tất scheduled job #{job_id}: {summary_msg}")
    except Exception as e:
        logger.exception(f"Lỗi nghiêm trọng khi chạy scheduled job #{job_id}: {e}")
        try:
            crud.update_scheduled_post(
                db,
                job_id,
                status="failed",
                result_message=f"Lỗi: {str(e)}",
                executed_at=now_vn(),
            )
        except Exception:
            pass
    finally:
        db.close()


def _create_future_posts(db, job, articles: dict, image_files: list[str] | None) -> list[str]:
    """
    Lịch đăng công khai: tạo ngay bài status='future' trên WordPress (WordPress tự đăng đúng giờ).
    Site lỗi được ghi `schedule_error` và sẽ đăng lại khi đến giờ. Trả các dòng mô tả kết quả.
    """
    results = publish_articles(
        articles=articles,
        image_files=image_files,
        site_configs={s: _site_config_of(db, s, art) for s, art in articles.items()},
        post_type=job.post_type,
        post_status="future",
        regular_price=job.regular_price or "",
        sale_price=job.sale_price or "",
        scheduled_time=job.scheduled_time,
    )
    lines = []
    for res in results:
        s_name = res.get("site_name", "")
        art = articles.get(s_name)
        if art is None:
            continue
        if res.get("success") and res.get("post_id"):
            art.update(post_id=res["post_id"], post_url=res.get("post_url"), edit_url=res.get("edit_url"))
            art.pop("schedule_error", None)
            lines.append(f"{s_name}: ID={res['post_id']} ({res.get('post_url')})")
        else:
            art["schedule_error"] = res.get("error") or "Không rõ lỗi"
            lines.append(f"{s_name}: Lỗi ({art['schedule_error']}) — sẽ thử đăng lại khi đến giờ")
        hist = _record_history(
            db, job, s_name, art,
            {"post_id": art.get("post_id"), "post_url": art.get("post_url"), "error": art.get("schedule_error")},
            "scheduled",
        )
        if hist:
            art["history_id"] = hist.id
    return lines


def schedule_publish_job(
    product_name: str,
    articles: dict[str, dict],
    site_names: list[str],
    scheduled_time: datetime,
    post_type: str = "product",
    post_status: str = "draft",
    regular_price: str = "",
    sale_price: str = "",
    image_files: list[str] | None = None,
) -> int:
    """
    Tạo lịch đăng trong DB và hẹn giờ qua APScheduler.
    post_status='publish': tạo luôn bài hẹn giờ (status='future') trên WordPress — lỗi từng site ghi vào
    `schedule_error` của bài đó (xem get_schedule_errors). post_status='draft': chỉ đăng (dạng nháp) khi đến giờ.
    """
    db = SessionLocal()
    try:
        articles = {k: dict(v) for k, v in articles.items() if k in site_names}
        for s_name, art in articles.items():
            site = crud.get_site_by_name(db, s_name)
            if site:
                art["site_id"] = site.id

        job = crud.create_scheduled_post(
            db,
            product_name=product_name,
            article_data_json=json.dumps(articles, ensure_ascii=False),
            site_names_json=json.dumps(site_names, ensure_ascii=False),
            scheduled_time=scheduled_time,
            post_type=post_type,
            post_status=post_status,
            regular_price=regular_price,
            sale_price=sale_price,
            image_paths_json=json.dumps(image_files or [], ensure_ascii=False),
        )
        if job is None:
            raise RuntimeError("Không lưu được lịch đăng vào CSDL.")
        job_id = job.id

        if _is_publish(post_status):
            lines = _create_future_posts(db, job, articles, image_files)
            result_message = f"Đã lên lịch trên WordPress: {'; '.join(lines)}" if lines else "Đã lên lịch trên WordPress."
        else:
            result_message = "Sẽ đăng dạng nháp khi đến giờ."
        crud.update_scheduled_post(
            db,
            job_id,
            article_data_json=json.dumps(articles, ensure_ascii=False),
            result_message=result_message,
        )

        _add_aps_job(job_id, scheduled_time)
        logger.info(f"✓ Đã đặt lịch đăng job #{job_id} cho '{product_name}' vào lúc {scheduled_time.strftime('%Y-%m-%d %H:%M:%S')}")
        return job_id
    finally:
        db.close()


def get_schedule_errors(job_id: int) -> dict[str, str]:
    """Các site chưa tạo được bài hẹn giờ trên WordPress lúc đặt lịch: {site: lỗi}."""
    db = SessionLocal()
    try:
        job = crud.get_scheduled_post(db, job_id)
        arts = _load_articles(job) if job else {}
        return {s: a["schedule_error"] for s, a in arts.items() if isinstance(a, dict) and a.get("schedule_error")}
    finally:
        db.close()


def cancel_scheduled_job(job_id: int) -> bool:
    """
    Hủy lịch còn chờ; bài đã hẹn giờ trên WordPress được chuyển về nháp. False nếu không có lịch hoặc lịch
    không còn chờ (đã chạy/đã hủy: không động tới WordPress). WordPress lỗi -> ScheduleSyncError, lịch giữ nguyên.
    """
    db = SessionLocal()
    try:
        job = crud.get_scheduled_post(db, job_id)
        if not job or job.status != "pending":
            return False

        articles = _load_articles(job)
        scope = taxonomy_service.scope_for_post_type(job.post_type)
        failures = []
        reverted = False
        for s_name, art in articles.items():
            if not isinstance(art, dict) or not art.get("post_id"):
                continue
            cfg = _site_config_of(db, s_name, art)
            try:
                if not cfg:
                    raise RuntimeError("không tìm thấy cấu hình website")
                wp_client.update_item_status(cfg, scope, art["post_id"], "draft")
                reverted = True
                logger.info(f"Đã chuyển bài #{art['post_id']} trên {s_name} về draft")
            except Exception as e:
                failures.append(f"{s_name} (bài #{art['post_id']}): {e}")
        if failures:
            raise ScheduleSyncError(
                f"Chưa hủy được lịch #{job_id}: không chuyển được bài về nháp trên WordPress — "
                + "; ".join(failures) + ". Lịch vẫn được giữ, hãy thử lại."
            )

        _remove_aps_job(job_id)
        for art in articles.values():
            if isinstance(art, dict) and art.get("history_id"):
                hist = crud.get_post_history_by_id(db, int(art["history_id"]))
                if hist and hist.status == "scheduled":
                    hist.status = "draft" if art.get("post_id") else "saved"
                    db.commit()

        updated = crud.update_scheduled_post(
            db,
            job_id,
            status="cancelled",
            result_message=(
                "Đã hủy lịch (đã chuyển bài trên WordPress về bản nháp)." if reverted else "Người dùng đã hủy lịch."
            ),
        )
        return bool(updated)
    finally:
        db.close()


def delete_scheduled_job(job_id: int) -> bool:
    """
    Xóa lịch khỏi DB. Lịch còn chờ: hủy trước rồi đưa bài hẹn giờ trên WordPress vào thùng rác.
    Lịch đã chạy/đã hủy: CHỈ xóa bản ghi, không động tới bài trên WordPress.
    WordPress lỗi khi hủy -> ScheduleSyncError và không xóa gì.
    """
    db = SessionLocal()
    try:
        job = crud.get_scheduled_post(db, job_id)
        if not job:
            return False

        if job.status == "pending":
            if not cancel_scheduled_job(job_id):  # vừa chuyển sang chạy -> không đụng tới bài
                return False
            articles = _load_articles(job)
            scope = taxonomy_service.scope_for_post_type(job.post_type)
            for s_name, art in articles.items():
                if not isinstance(art, dict) or not art.get("post_id"):
                    continue
                cfg = _site_config_of(db, s_name, art)
                if not cfg:
                    continue
                try:
                    wp_client.trash_item(cfg, scope, art["post_id"])
                    logger.info(f"Đã chuyển bài #{art['post_id']} trên {s_name} vào thùng rác")
                except Exception as e:  # bài đã về nháp nên không còn nguy cơ tự đăng
                    logger.warning(f"Không thể chuyển bài #{art['post_id']} trên {s_name} vào thùng rác: {e}")
                    continue
                hist = crud.get_post_history_by_id(db, int(art["history_id"])) if art.get("history_id") else None
                if hist:
                    hist.status = "trashed"
                    db.commit()

        _remove_aps_job(job_id)
        return bool(crud.delete_scheduled_post(db, job_id))
    finally:
        db.close()


def init_scheduler():
    """Khởi động scheduler và nạp lại các job đang chờ từ DB."""
    get_scheduler()
    db = SessionLocal()
    overdue: list[int] = []
    try:
        for job in crud.get_scheduled_posts(db, status="running", limit=_MAX_JOBS):
            crud.update_scheduled_post(
                db, job.id, status="failed", executed_at=now_vn(),
                result_message="Bị gián đoạn khi ứng dụng tắt giữa chừng — hãy kiểm tra lại bài trên WordPress.",
            )

        now = now_vn()
        loaded_count = 0
        for job in crud.get_scheduled_posts(db, status="pending", limit=_MAX_JOBS):
            if job.scheduled_time and job.scheduled_time > now:
                _add_aps_job(job.id, job.scheduled_time)
                loaded_count += 1
            elif job.scheduled_time:
                overdue.append(job.id)
        if loaded_count > 0:
            logger.info(f"✓ Đã nạp lại {loaded_count} lịch đăng đang chờ từ CSDL.")
    finally:
        db.close()

    # Quá hạn khi ứng dụng tắt: xác nhận bài đã hẹn giờ trên WordPress, site chưa có bài thì ghi nhỡ lịch
    for job_id in overdue:
        _add_aps_job(job_id, publish_missing=False)
