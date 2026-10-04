"""services/sync (trùng, liệt kê, làm mới, liên kết, thùng rác, cập nhật) và services/dashboard — mock WordPress, không gradio."""
import json
from datetime import date, datetime, timedelta

import pytest

from core import pipeline, wp_client
from core.timeutil import now_vn
from db import crud
from db.models import PostHistory, ScheduledPost, Site
from services import dashboard as dash
from services import posts as post_svc
from services import sync
from services.errors import PublishError, ServiceError

CFG = {"url": "https://shop.example.com", "client_key": "k", "client_secret": "s", "wp_user": "u", "wp_app_password": "p"}


def item(i, title, status="publish", url=None):
    return {"id": i, "title": title, "status": status, "url": url or f"https://shop.example.com/p/{i}",
            "modified": "2026-10-01", "type": "product"}


@pytest.fixture
def env(mem_db, monkeypatch):
    s = mem_db()
    site = Site(name="shop", url="https://shop.example.com")
    s.add(site)
    s.commit()

    def mk(**kw):
        base = dict(site_id=site.id, product_name="Quạt hút công nghiệp", title="Quạt hút công nghiệp", raw_html="<p>x</p>",
                    post_type="product", status="saved", created_at=now_vn())
        base.update(kw)
        h = PostHistory(**base)
        s.add(h)
        s.commit()
        return h.id

    ids = {
        "saved": mk(),
        "live": mk(status="draft", wp_post_id="100", wp_post_url="old-url"),
        "gone": mk(product_name="Bơm", title="Bơm", status="published", wp_post_id="200"),
        "failed": mk(status="failed"),
    }
    s.close()
    monkeypatch.setattr(crud, "get_site_config", lambda d, i: CFG)
    return mem_db, ids


# ── thuần ────────────────────────────────────────────────────────────────────

def test_similarity_ignores_accents_case_and_containment():
    assert sync.similarity("Quạt hút công nghiệp", "QUAT HUT CONG NGHIEP") == 1.0
    assert sync.similarity("Quạt hút", "Quạt hút công nghiệp 600mm") >= 0.9
    assert sync.similarity("Máy bơm", "Pa lăng cáp điện") < 0.5
    assert sync.similarity("", "x") == 0.0


def test_remote_modified_time_is_converted_from_utc_to_gmt7(env, monkeypatch):
    it = item(1, "A")
    it.update(modified="2026-10-04T09:30:00", modified_gmt="2026-10-04T09:30:00")      # site đặt múi giờ UTC
    it2 = item(2, "B")
    it2.update(modified="2026-10-04T16:30:00", modified_gmt="2026-10-04T09:30:00")     # site đặt GMT+7: vẫn cùng một thời điểm
    it3 = item(3, "C")
    it3.update(modified="", modified_gmt="")
    monkeypatch.setattr(wp_client, "list_items", lambda *a, **k: ([it, it2, it3], 3))
    page = sync.list_remote("shop", "product")
    assert [i.modified for i in page.items] == ["04/10/2026 16:30", "04/10/2026 16:30", "-"]


def test_utc_iso_to_vn():
    from core.timeutil import utc_iso_to_vn
    assert utc_iso_to_vn("2026-10-04T17:30:00") == "05/10/2026 00:30"          # qua nửa đêm
    assert utc_iso_to_vn("2026-10-04T09:30:00Z") == "04/10/2026 16:30"
    assert utc_iso_to_vn("") == "-" and utc_iso_to_vn("rác") == "-" and utc_iso_to_vn(None, empty="") == ""


def test_local_status_mapping():
    assert [sync.local_status_for(x) for x in ("publish", "draft", "pending", "trash", None, "weird")] == \
        ["published", "draft", "draft", "trashed", "missing", "draft"]


# ── trùng / liệt kê ──────────────────────────────────────────────────────────

def test_find_duplicates_filters_trash_and_low_similarity(env, monkeypatch):
    monkeypatch.setattr(wp_client, "list_items", lambda *a, **k: ([
        item(1, "Quạt hút công nghiệp 600mm"), item(2, "Pa lăng cáp điện"), item(3, "Quạt hút công nghiệp", "trash"),
        item(100, "Quạt hút công nghiệp", "draft")], 4))
    ms = sync.find_duplicates("shop", "Quạt hút công nghiệp", "Sản phẩm WooCommerce")
    assert [m.wp_id for m in ms] == [100, 1]            # trùng tên đứng đầu; thùng rác & khác chủ đề bị loại
    assert ms[0].local_post_id is not None and ms[1].local_post_id is None


def test_find_duplicates_network_error_is_service_error_and_check_articles_never_raises(env, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("timeout")
    monkeypatch.setattr(wp_client, "list_items", boom)
    with pytest.raises(ServiceError, match="timeout"):
        sync.find_duplicates("shop", "x", "product")
    res = sync.check_articles({"shop": {"title": "A"}, "ghost": {"title": "B"}}, "product")
    assert all(r.error and not r.matches for r in res)


def test_check_saved_post_skips_own_linked_wp_post(env, monkeypatch):
    _, ids = env
    monkeypatch.setattr(wp_client, "list_items", lambda *a, **k: ([item(100, "Quạt hút công nghiệp", "draft"), item(7, "Quạt hút công nghiệp")], 2))
    res = sync.check_saved_post(ids["live"])
    assert [m.wp_id for m in res.matches] == [7]


def test_list_remote_links_local_ids(env, monkeypatch):
    _, ids = env
    monkeypatch.setattr(wp_client, "list_items", lambda *a, **k: ([item(100, "A"), item(5, "B")], 12))
    page = sync.list_remote("shop", "product")
    assert page.total == 12 and {i.id: i.local_post_id for i in page.items} == {100: ids["live"], 5: None}
    with pytest.raises(ServiceError):
        sync.list_remote("ghost", "product")


# ── làm mới / liên kết / thùng rác ───────────────────────────────────────────

def test_refresh_statuses_updates_and_collects_errors(env, monkeypatch):
    mem_db, ids = env

    def get(cfg, scope, wp_id):
        if str(wp_id) == "100":
            return item(100, "Quạt", "publish", "new-url")
        return None                                     # bài 200 đã bị xóa trên WP

    monkeypatch.setattr(wp_client, "get_item", get)
    rep = sync.refresh_statuses()
    assert rep.checked == 2 and rep.errors == []
    assert {(c.post_id, c.old, c.new) for c in rep.changes} == {(ids["live"], "draft", "published"), (ids["gone"], "published", "missing")}
    db = mem_db()
    assert db.get(PostHistory, ids["live"]).wp_post_url == "new-url"
    assert db.get(PostHistory, ids["saved"]).status == "saved"          # không đụng bài chưa đăng
    db.close()
    assert sync.refresh_statuses().checked == 1                          # 'missing' không bị kiểm tra lại


def test_refresh_statuses_error_does_not_stop_run(env, monkeypatch):
    def get(cfg, scope, wp_id):
        if str(wp_id) == "100":
            raise RuntimeError("net")
        return item(200, "Bơm", "trash")
    monkeypatch.setattr(wp_client, "get_item", get)
    rep = sync.refresh_statuses("shop")
    assert len(rep.errors) == 1 and [c.new for c in rep.changes] == ["trashed"]


def test_link_remote(env, monkeypatch):
    mem_db, ids = env
    monkeypatch.setattr(wp_client, "get_item", lambda c, s, i: item(i, "A", "draft", "u"))
    assert sync.link_remote(ids["saved"], 55) == "draft"
    db = mem_db()
    h = db.get(PostHistory, ids["saved"])
    assert (h.wp_post_id, h.wp_post_url, h.status) == ("55", "u", "draft")
    db.close()
    monkeypatch.setattr(wp_client, "get_item", lambda c, s, i: None)
    with pytest.raises(ServiceError, match="Không có bài"):
        sync.link_remote(ids["saved"], 99)


def test_trash_requires_confirm_and_wp_id_and_never_deletes_record(env, monkeypatch):
    mem_db, ids = env
    trashed = []
    monkeypatch.setattr(wp_client, "trash_item", lambda c, s, i: trashed.append((s, str(i))) or item(i, "A", "trash"))
    with pytest.raises(ServiceError, match="xác nhận"):
        sync.trash_post(ids["live"], confirm=False)
    with pytest.raises(ServiceError, match="chưa được đăng"):
        sync.trash_post(ids["saved"], confirm=True)
    assert trashed == []
    assert "thùng rác" in sync.trash_post(ids["live"], confirm=True)
    assert trashed == [("product", "100")]
    db = mem_db()
    assert db.get(PostHistory, ids["live"]).status == "trashed"      # bản ghi vẫn còn
    db.close()


def test_trash_failure_keeps_status(env, monkeypatch):
    mem_db, ids = env
    monkeypatch.setattr(wp_client, "trash_item", lambda *a: (_ for _ in ()).throw(RuntimeError("403")))
    with pytest.raises(ServiceError, match="403"):
        sync.trash_post(ids["live"], confirm=True)
    db = mem_db()
    assert db.get(PostHistory, ids["live"]).status == "draft"
    db.close()


# ── cập nhật bài đã đăng (PUT) ───────────────────────────────────────────────

def _publish(monkeypatch, seen, ok=True):
    def fake(site_name, cfg, article, images, ptype, pstatus, **kw):
        seen.update(kw)
        if not ok:
            return {"success": False, "error": "WP từ chối"}
        return {"success": True, "post_id": kw.get("existing_wp_id") or 321, "post_url": "u", "edit_url": "e", "uploaded_count": 0}
    monkeypatch.setattr(pipeline, "publish_one", fake)


def _edit_args(pid):
    return dict(post_id=pid, title="T", short_description="", regular_price="", sale_price="", raw_html="<p>n</p>",
                post_type="product", post_status="publish")


def test_publish_saved_post_update_existing_passes_wp_id(env, monkeypatch):
    mem_db, ids = env
    seen = {}
    _publish(monkeypatch, seen)
    out = post_svc.publish_saved_post(**_edit_args(ids["live"]), update_existing=True)
    assert seen["existing_wp_id"] == "100" and out.updated is True
    db = mem_db()
    h = db.get(PostHistory, ids["live"])
    assert h.wp_post_id == "100" and h.status == "published"
    db.close()


def test_publish_saved_post_update_without_wp_id_is_error_and_default_creates_new(env, monkeypatch):
    _, ids = env
    seen = {}
    _publish(monkeypatch, seen)
    with pytest.raises(ServiceError, match="chưa có ID"):
        post_svc.publish_saved_post(**_edit_args(ids["saved"]), update_existing=True)
    out = post_svc.publish_saved_post(**_edit_args(ids["saved"]))
    assert seen["existing_wp_id"] is None and out.updated is False


def test_update_failure_raises_publish_error(env, monkeypatch):
    _, ids = env
    _publish(monkeypatch, {}, ok=False)
    with pytest.raises(PublishError):
        post_svc.publish_saved_post(**_edit_args(ids["live"]), update_existing=True)


# ── dashboard ────────────────────────────────────────────────────────────────

def test_get_stats_buckets_days_sites_and_recent(env):
    mem_db, ids = env
    db = mem_db()
    site = db.query(Site).first()
    old = PostHistory(site_id=site.id, product_name="Cũ", title="Cũ", status="published", created_at=now_vn() - timedelta(days=90))
    db.add(old)
    db.add(ScheduledPost(product_name="J", post_type="product", post_status="draft", status="pending",
                         scheduled_time=now_vn() + timedelta(days=2), site_names_json="[]", article_data_json="{}"))
    db.commit()
    db.close()
    st = dash.get_stats(days=30)
    assert st.totals == {"published": 3, "saved": 1, "failed": 1, "trashed": 0, "total": 5}   # draft + published = đã đăng
    assert len(st.daily) == 30 and sum(d.published + d.saved + d.failed for d in st.daily) == 4   # bài 90 ngày trước ngoài khoảng
    today = st.daily[-1]
    assert (today.published, today.saved, today.failed) == (2, 1, 1)
    assert st.by_site[0].site_name == "shop" and st.by_site[0].total == 5
    assert st.pending_jobs == 1 and st.next_job_time
    live = next(r for r in st.recent if r.id == ids["live"])
    assert live.url == "old-url" and live.admin_url == "https://shop.example.com/wp-admin/post.php?post=100&action=edit"
    assert next(r for r in st.recent if r.id == ids["saved"]).admin_url == ""


def test_site_health_parallel_cached_and_isolated_errors(env, monkeypatch):
    mem_db, _ = env
    db = mem_db()
    db.add(Site(name="shop2", url="https://two.example.com"))
    db.commit()
    db.close()
    calls = []

    def fake(cfg):
        calls.append(cfg["url"])
        return {"wp_ok": True, "wc_ok": True, "message": "ok"}

    monkeypatch.setattr(wp_client, "test_connection", fake)
    dash.clear_health_cache()
    now = [1000.0]
    clock = lambda: now[0]  # noqa: E731
    first = dash.check_sites(clock=clock)
    assert len(first) == 2 and all(h.ok for h in first) and len(calls) == 2
    dash.check_sites(clock=clock)
    assert len(calls) == 2                                   # còn hạn cache -> không gọi lại
    now[0] += dash.HEALTH_TTL_SECONDS + 1
    assert dash.cached_site_health(clock) is None
    dash.check_sites(clock=clock)
    assert len(calls) == 4
    dash.check_sites(force=True, clock=clock)
    assert len(calls) == 6

    monkeypatch.setattr(wp_client, "test_connection", lambda cfg: (_ for _ in ()).throw(RuntimeError("down")))
    res = dash.check_sites(force=True, clock=clock)
    assert all(not h.ok and "down" in h.message for h in res)
    dash.clear_health_cache()
