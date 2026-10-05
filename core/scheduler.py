from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger

from db.database import SessionLocal
from db import crud
from core.pipeline import publish_articles
from core.timeutil import now_vn, TZ_NAME
from core import taxonomy_service

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def get_scheduler() -> BackgroundScheduler:
    """Khởi tạo hoặc lấy BackgroundScheduler singleton."""
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler(timezone=TZ_NAME)
        _scheduler.start()
        logger.info("✓ APScheduler đã được khởi động.")
    return _scheduler


def execute_scheduled_job(job_id: int):
    """Hàm thực thi đăng bài được kích hoạt bởi APScheduler."""
    logger.info(f"⏰ Bắt đầu thực thi scheduled job #{job_id}...")
    db = SessionLocal()
    try:
        job = crud.get_scheduled_post(db, job_id)
        if not job:
            logger.warning(f"Không tìm thấy scheduled job #{job_id}")
            return

        if job.status == "cancelled":
            logger.info(f"Job #{job_id} đã bị hủy trước đó. Bỏ qua.")
            return

        crud.update_scheduled_post(db, job_id, status="running")

        articles = json.loads(job.article_data_json)
        site_names = json.loads(job.site_names_json)
        image_files = json.loads(job.image_paths_json) if job.image_paths_json else []
        all_configs = crud.get_all_site_configs(db)

        # Lọc các bài viết theo danh sách site được lên lịch
        articles_to_pub = {k: v for k, v in articles.items() if k in site_names}

        results = publish_articles(
            articles=articles_to_pub,
            image_files=image_files,
            site_configs=all_configs,
            post_type=job.post_type,
            post_status=job.post_status,
            regular_price=job.regular_price or "",
            sale_price=job.sale_price or "",
        )

        success_count = sum(1 for r in results if r.get("success"))
        total_count = len(results)

        # Ghi nhận vào post_history
        for res in results:
            s_name = res.get("site_name", "")
            site_obj = crud.get_site_by_name(db, s_name)
            if site_obj:
                art = articles.get(s_name, {})
                ok = bool(res.get("success"))
                ok_status = "published" if job.post_status == "publish" else "draft"
                history_id = art.get("history_id")
                existing = crud.get_post_history_by_id(db, int(history_id)) if history_id else None
                if existing:
                    existing.status = ok_status if ok else "failed"
                    existing.wp_post_id = str(res.get("post_id", "")) if res.get("post_id") else existing.wp_post_id
                    existing.wp_post_url = res.get("post_url") or existing.wp_post_url
                    existing.error_message = None if ok else res.get("error")
                    existing.published_at = now_vn()
                    db.commit()
                    continue
                crud.create_post_history(
                    db,
                    site_id=site_obj.id,
                    product_name=job.product_name,
                    title=art.get("title", job.product_name),
                    raw_html=art.get("raw_html", ""),
                    post_type=job.post_type,
                    status=ok_status if ok else "failed",
                    wp_post_id=str(res.get("post_id", "")) if res.get("post_id") else None,
                    wp_post_url=res.get("post_url"),
                    error_message=res.get("error"),
                    category_ids_json=json.dumps(taxonomy_service.effective_category_ids(art, job.post_type)),
                    tags_json=json.dumps(art.get("tags") or [], ensure_ascii=False),
                )

        final_status = "completed" if success_count == total_count else ("failed" if success_count == 0 else "partially_completed")
        summary_msg = f"Đã đăng thành công {success_count}/{total_count} website."

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
    """Tạo lịch đăng bài mới trong DB và hẹn giờ qua APScheduler."""
    db = SessionLocal()
    try:
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
        job_id = job.id

        sched = get_scheduler()
        sched.add_job(
            func=execute_scheduled_job,
            trigger=DateTrigger(run_date=scheduled_time),
            args=[job_id],
            id=f"wp_post_job_{job_id}",
            replace_existing=True,
        )
        logger.info(f"✓ Đã đặt lịch đăng job #{job_id} cho '{product_name}' vào lúc {scheduled_time.strftime('%Y-%m-%d %H:%M:%S')}")
        return job_id
    finally:
        db.close()


def cancel_scheduled_job(job_id: int) -> bool:
    """Hủy một lịch đăng bài đã đặt."""
    sched = get_scheduler()
    aps_job_id = f"wp_post_job_{job_id}"
    try:
        if sched.get_job(aps_job_id):
            sched.remove_job(aps_job_id)
    except Exception as e:
        logger.warning(f"Không thể remove job từ APScheduler: {e}")

    db = SessionLocal()
    try:
        updated = crud.update_scheduled_post(db, job_id, status="cancelled", result_message="Người dùng đã hủy lịch.")
        return bool(updated)
    finally:
        db.close()


def init_scheduler():
    """Khởi động scheduler và nạp lại các job đang chờ từ DB."""
    sched = get_scheduler()
    db = SessionLocal()
    try:
        pending_jobs = crud.get_scheduled_posts(db, status="pending")
        now = now_vn()
        loaded_count = 0
        for job in pending_jobs:
            if job.scheduled_time and job.scheduled_time > now:
                sched.add_job(
                    func=execute_scheduled_job,
                    trigger=DateTrigger(run_date=job.scheduled_time),
                    args=[job.id],
                    id=f"wp_post_job_{job.id}",
                    replace_existing=True,
                )
                loaded_count += 1
            elif job.scheduled_time and job.scheduled_time <= now:
                # Quá hạn khi server tắt → đánh dấu để kiểm tra lại
                crud.update_scheduled_post(db, job.id, status="failed", result_message="Bị nhỡ lịch khi server tắt.")
        if loaded_count > 0:
            logger.info(f"✓ Đã nạp lại {loaded_count} lịch đăng đang chờ từ CSDL.")
    finally:
        db.close()
