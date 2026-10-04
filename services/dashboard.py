"""
services/dashboard.py — số liệu tổng quan cho trang Dashboard: thống kê bài, lịch sắp chạy, bài gần đây
và tình trạng kết nối các website.

Chỉ đọc. Trả dataclass thuần để UI nào cũng vẽ được (Gradio, web khác, API). Kiểm tra kết nối chạy song song,
có timeout và cache 5 phút — không gọi mạng mỗi lần mở trang.
"""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from core import wp_client
from core.timeutil import fmt_vn, now_vn
from db import crud
from db.database import session_scope
from db.models import PostHistory, ScheduledPost
from services.sync import edit_url

logger = logging.getLogger(__name__)

HEALTH_TTL_SECONDS = 300
HEALTH_TIMEOUT_SECONDS = 25

# Nhóm trạng thái trong kho bài -> nhóm hiển thị
BUCKET_OF = {
    "saved": "saved",
    "published": "published",
    "draft": "published",       # đã lên WordPress (ở dạng nháp WP) vẫn tính là đã đăng từ app
    "failed": "failed",
    "trashed": "trashed",
    "missing": "trashed",
}
BUCKETS = ("published", "saved", "failed", "trashed")


@dataclass(frozen=True)
class DayCount:
    day: str                     # 'YYYY-MM-DD'
    published: int
    saved: int
    failed: int


@dataclass(frozen=True)
class SiteCount:
    site_name: str
    total: int
    published: int
    saved: int
    failed: int


@dataclass(frozen=True)
class RecentPost:
    id: int
    title: str
    site_name: str
    post_type: str
    status: str
    created_at: str              # GMT+7 đã định dạng
    url: str                     # link bài trên website ('' nếu chưa đăng)
    admin_url: str               # link sửa trong wp-admin ('' nếu chưa đăng)


@dataclass(frozen=True)
class DashboardStats:
    days: int
    totals: dict[str, int]       # published/saved/failed/trashed + 'total'
    daily: list[DayCount]        # đủ `days` ngày, ngày không có bài = 0
    by_site: list[SiteCount]
    pending_jobs: int
    next_job_time: str           # '' nếu không có lịch chờ
    recent: list[RecentPost]


@dataclass(frozen=True)
class SiteHealth:
    site_name: str
    url: str
    wp_ok: bool
    wc_ok: bool
    message: str
    checked_at: str              # GMT+7 đã định dạng

    @property
    def ok(self) -> bool:
        return self.wp_ok and self.wc_ok


def get_stats(days: int = 30, recent_limit: int = 10, today: date | None = None) -> DashboardStats:
    """Thống kê theo trạng thái / ngày (`days` ngày gần nhất, tính cả hôm nay) / website, lịch chờ và bài gần đây."""
    today = today or now_vn().date()
    start_day = today - timedelta(days=days - 1)
    start_dt = datetime.combine(start_day, datetime.min.time())

    with session_scope() as db:
        posts = db.query(PostHistory).all()
        site_url = {s.id: (s.name, s.url) for s in crud.get_all_sites(db)}

        totals = {b: 0 for b in BUCKETS}
        per_day: dict[str, dict[str, int]] = {
            (start_day + timedelta(days=i)).isoformat(): {b: 0 for b in BUCKETS} for i in range(days)
        }
        per_site: dict[int, dict[str, int]] = {}
        for h in posts:
            bucket = BUCKET_OF.get(h.status or "", "saved")
            totals[bucket] += 1
            s = per_site.setdefault(h.site_id, {b: 0 for b in BUCKETS})
            s[bucket] += 1
            if h.created_at and h.created_at >= start_dt:
                key = h.created_at.date().isoformat()
                if key in per_day:
                    per_day[key][bucket] += 1
        totals["total"] = len(posts)

        daily = [DayCount(d, v["published"], v["saved"], v["failed"]) for d, v in per_day.items()]
        by_site = sorted(
            (SiteCount(site_url.get(sid, ("(đã xóa)", ""))[0], sum(v.values()), v["published"], v["saved"], v["failed"])
             for sid, v in per_site.items()),
            key=lambda x: x.total, reverse=True,
        )

        pending = (
            db.query(ScheduledPost).filter(ScheduledPost.status == "pending")
            .order_by(ScheduledPost.scheduled_time).all()
        )

        recent_rows = crud.get_recent_posts(db, limit=recent_limit)
        recent = []
        for h in recent_rows:
            name, url = site_url.get(h.site_id, ("(đã xóa)", ""))
            live = h.status in ("published", "draft")
            recent.append(RecentPost(
                id=h.id,
                title=h.title or h.product_name,
                site_name=name,
                post_type=h.post_type or "product",
                status=h.status or "",
                created_at=fmt_vn(h.created_at),
                url=(h.wp_post_url or "") if live else "",
                admin_url=edit_url(url, h.wp_post_id) if (live and h.wp_post_id and url) else "",
            ))

        return DashboardStats(
            days=days, totals=totals, daily=daily, by_site=by_site,
            pending_jobs=len(pending),
            next_job_time=fmt_vn(pending[0].scheduled_time) if pending else "",
            recent=recent,
        )


# ── Tình trạng website (song song + cache) ───────────────────────────────────

_health_lock = threading.Lock()
_health_cache: tuple[float, list[SiteHealth]] | None = None


def _check_one(name: str, url: str, config: dict) -> SiteHealth:
    try:
        r = wp_client.test_connection(config)
        return SiteHealth(name, url, bool(r.get("wp_ok")), bool(r.get("wc_ok")), r.get("message", ""), fmt_vn(now_vn()))
    except Exception as e:  # noqa: BLE001 — một site lỗi không được làm hỏng cả bảng
        return SiteHealth(name, url, False, False, f"Lỗi: {e}", fmt_vn(now_vn()))


def cached_site_health(clock=time.monotonic) -> list[SiteHealth] | None:
    """Kết quả kiểm tra gần nhất nếu còn hạn (không gọi mạng); None nếu chưa có/đã hết hạn."""
    with _health_lock:
        if _health_cache and clock() - _health_cache[0] < HEALTH_TTL_SECONDS:
            return list(_health_cache[1])
    return None


def check_sites(force: bool = False, clock=time.monotonic) -> list[SiteHealth]:
    """
    Kiểm tra kết nối từng website song song. Dùng cache 5 phút trừ khi force=True.
    Site nào quá HEALTH_TIMEOUT_SECONDS thì báo "quá thời gian" thay vì treo cả trang.
    """
    global _health_cache
    if not force:
        cached = cached_site_health(clock)
        if cached is not None:
            return cached

    with session_scope() as db:
        targets = []
        for s in crud.get_all_sites(db):
            cfg = crud.get_site_config(db, s.id)
            if cfg:
                targets.append((s.name, s.url, cfg))

    results: list[SiteHealth] = []
    if targets:
        pool = ThreadPoolExecutor(max_workers=min(4, len(targets)))
        try:
            futures = [(n, u, pool.submit(_check_one, n, u, c)) for n, u, c in targets]
            deadline = time.monotonic() + HEALTH_TIMEOUT_SECONDS
            for n, u, f in futures:
                try:
                    results.append(f.result(timeout=max(0.1, deadline - time.monotonic())))
                except FutureTimeout:
                    results.append(SiteHealth(n, u, False, False, "Quá thời gian chờ kiểm tra kết nối.", fmt_vn(now_vn())))
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    with _health_lock:
        _health_cache = (clock(), results)
    return list(results)


def clear_health_cache() -> None:
    global _health_cache
    with _health_lock:
        _health_cache = None
