"""Test services/schedules + phần TaxControls của services/taxonomy (không cần gradio)."""
import json
from datetime import timedelta

import pytest

from core.timeutil import now_vn
from db import crud
from db.models import PostHistory, ScheduledPost, Site
from services import schedules as svc
from services import taxonomy as tax
from services.errors import ServiceError

SITE_CFG = {"url": "https://shop.example.com", "client_key": "k", "client_secret": "s", "wp_user": "", "wp_app_password": ""}


@pytest.fixture
def env(mem_db, monkeypatch):
    s = mem_db()
    site = Site(name="shop", url="https://shop.example.com")
    s.add(site)
    s.commit()
    crud.replace_site_categories(s, site.id, "product", [
        {"id": 1, "name": "Quạt", "parent": 0}, {"id": 2, "name": "Quạt công nghiệp", "parent": 1}])
    job = ScheduledPost(
        product_name="Quạt X", post_type="product", post_status="draft", status="pending",
        scheduled_time=now_vn() + timedelta(days=1), site_names_json=json.dumps(["shop"]),
        article_data_json=json.dumps({"shop": {"title": "T", "raw_html": "<p>x</p>", "category_ids": [1],
                                               "category_scope": "product", "tags": ["a"]}}))
    done = ScheduledPost(
        product_name="Cũ", post_type="product", post_status="draft", status="completed",
        scheduled_time=now_vn() - timedelta(days=1), site_names_json=json.dumps(["shop"]), article_data_json="{}")
    h = PostHistory(site_id=site.id, product_name="Quạt X", title="Quạt X", raw_html="<p>x</p>", post_type="product",
                    status="saved", category_ids_json="[2]", tags_json='["quạt hút"]')
    s.add_all([job, done, h])
    s.commit()
    ids = {"job": job.id, "done": done.id, "post": h.id}
    s.close()
    monkeypatch.setattr(crud, "get_site_config", lambda d, i: SITE_CFG)
    return mem_db, ids


def test_schedule_post_validations(monkeypatch):
    with pytest.raises(ServiceError, match="Chưa có nội dung"):
        svc.schedule_post({}, [], "draft", "product", now_vn() + timedelta(hours=1))
    with pytest.raises(ServiceError, match="phải ở trong tương lai"):
        svc.schedule_post({"s": {"title": "t"}}, [], "draft", "product", now_vn() - timedelta(minutes=1))


def test_schedule_post_delegates_to_scheduler(monkeypatch):
    seen = {}

    def fake(**kw):
        seen.update(kw)
        return 7

    monkeypatch.setattr(svc.core_scheduler, "schedule_publish_job", fake)
    when = now_vn() + timedelta(hours=2)
    res = svc.schedule_post({"s": {"title": "Tiêu đề", "product_name": "SP"}}, ["a.jpg"], "publish", "product", when, "10", "5")
    assert (res.job_id, res.product_name, res.site_names, res.post_status) == (7, "SP", ["s"], "publish")
    assert seen["site_names"] == ["s"] and seen["image_files"] == ["a.jpg"] and seen["sale_price"] == "5"


def test_schedule_post_persists_images(tmp_path, monkeypatch):
    from pathlib import Path
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(svc.image_service, "DATA_DIR", data)
    monkeypatch.setattr(svc.image_service, "POST_IMAGES_DIR", data / "post_images")

    seen = {}
    monkeypatch.setattr(svc.core_scheduler, "schedule_publish_job", lambda **kw: seen.update(kw) or 9)

    temp_img = tmp_path / "temp_photo.png"
    temp_img.write_bytes(b"PNGDATA")

    when = now_vn() + timedelta(hours=3)
    res = svc.schedule_post(
        {"s": {"title": "Tiêu đề", "product_name": "SP"}},
        [str(temp_img)],
        "publish",
        "product",
        when,
    )
    assert res.job_id == 9
    saved_path = seen["image_files"][0]
    assert saved_path != str(temp_img)
    assert saved_path.startswith(str(data / "post_images"))
    assert Path(saved_path).read_bytes() == b"PNGDATA"



def test_list_jobs_formats_rows(env):
    _, ids = env
    rows = {r.id: r for r in svc.list_jobs()}
    r = rows[ids["job"]]
    assert r.status == "⏳ Đang chờ" and r.sites == "shop" and r.taxonomy_summary == "📂 Quạt · 🏷️ a"
    assert rows[ids["done"]].status == "✅ Hoàn tất"


def test_cancel_and_delete(env, monkeypatch):
    mem_db, ids = env
    calls = []
    monkeypatch.setattr(svc.core_scheduler, "cancel_scheduled_job", lambda i: calls.append(i) or True)
    assert svc.cancel_job(5) is True
    assert svc.delete_job(ids["done"]) is True and svc.delete_job(ids["done"]) is False
    assert calls == [5]                      # lịch đã chạy: chỉ xóa bản ghi, không hủy/động tới WordPress


def test_job_controls_and_lock(env):
    _, ids = env
    c = svc.job_controls(str(ids["job"]))
    assert (c.sites, c.site, c.selected, c.tags, c.interactive) == (["shop"], "shop", [1], "a", True)
    locked = svc.job_controls(str(ids["done"]))
    assert locked.sites == ["shop"]
    assert svc.save_job_tags("x", ids["done"], "shop") == svc.LOCKED_MSG
    assert svc.job_controls("abc").status == svc.NO_JOB_MSG and svc.job_controls("9999").choices == []


def test_save_job_taxonomy_keeps_other_fields(env):
    mem_db, ids = env
    assert "Đã lưu 2 danh mục" in svc.save_job_categories([1, "2", 2], ids["job"], "shop")
    assert "Đã lưu 2 tag" in svc.save_job_tags("p, #q", ids["job"], "shop")
    assert "không thuộc" in svc.save_job_tags("x", ids["job"], "other")
    db = mem_db()
    art = json.loads(db.get(ScheduledPost, ids["job"]).article_data_json)["shop"]
    assert art["category_ids"] == [1, 2] and art["tags"] == ["p", "q"] and art["title"] == "T"
    db.close()


def test_suggest_for_job_saves_and_failure_keeps(env, monkeypatch):
    mem_db, ids = env
    monkeypatch.setattr(tax, "suggest_taxonomy", lambda *a, **k: {"category_ids": [2], "tags": ["t1"]})
    c = svc.suggest_for_job(ids["job"], "shop")
    assert c.selected == [2] and c.tags == "t1" and "lưu" in c.status
    monkeypatch.setattr(tax, "suggest_taxonomy", lambda *a, **k: {"category_ids": [], "tags": [], "error": "quota"})
    c = svc.suggest_for_job(ids["job"], "shop")
    assert "quota" in c.status and c.selected == [2]


def test_history_controls_and_saves(env):
    mem_db, ids = env
    c = tax.history_controls(ids["post"], "Sản phẩm WooCommerce")
    assert c.selected == [2] and c.tags == "quạt hút"
    assert tax.history_controls(None, "x").choices == [] and tax.history_controls(99999, "x").choices == []
    assert "Đã lưu 1 danh mục" in tax.save_history_categories(ids["post"], ["2"], "Bài viết Blog")
    db = mem_db()
    assert db.get(PostHistory, ids["post"]).post_type == "post"
    db.close()


def test_article_state_helpers_and_autofill_never_raise(env, monkeypatch):
    st = {"shop": {"title": "T"}}
    tax.set_article_categories(st, "shop", ["2", 1], "Sản phẩm WooCommerce")
    tax.set_article_tags(st, "shop", "a, A, b")
    assert st["shop"]["category_ids"] == [2, 1] and st["shop"]["category_scope"] == "product" and st["shop"]["tags"] == ["a", "b"]
    assert tax.article_controls({}, "shop", "product").status == tax.NO_ARTICLE_MSG
    monkeypatch.setattr(tax, "_suggest_for_site", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert tax.autofill({"shop": {"title": "A"}}, "product") == {"shop": {"title": "A"}}


def test_core_schedule_publish_job_creates_future_post_and_pending_db(env, monkeypatch):
    mem_db, ids = env
    from core import scheduler as core_sched

    published_calls = []

    def fake_publish_articles(**kwargs):
        published_calls.append(kwargs)
        return [
            {
                "site_name": "shop",
                "success": True,
                "post_id": 123,
                "post_url": "https://shop.example.com/p/123",
                "edit_url": "https://shop.example.com/wp-admin/post.php?post=123",
                "status": "future",
            }
        ]

    monkeypatch.setattr(core_sched, "publish_articles", fake_publish_articles)

    when = now_vn() + timedelta(hours=5)
    articles = {
        "shop": {
            "title": "Quạt Đứng Tương Lai",
            "raw_html": "<p>Nội dung</p>",
            "category_ids": [1],
        }
    }

    job_id = core_sched.schedule_publish_job(
        product_name="Quạt Đứng",
        articles=articles,
        site_names=["shop"],
        scheduled_time=when,
        post_type="product",
        post_status="publish",
    )

    assert len(published_calls) == 1
    call = published_calls[0]
    assert call["post_status"] == "future"
    assert call["scheduled_time"] == when

    # Kiểm tra job trong DB
    db = mem_db()
    job = db.get(ScheduledPost, job_id)
    assert job is not None
    assert job.status == "pending"
    assert job.post_status == "publish"
    assert job.executed_at is None
    assert "ID=123" in job.result_message
    saved_articles = json.loads(job.article_data_json)
    assert saved_articles["shop"]["post_id"] == 123
    assert saved_articles["shop"]["post_url"] == "https://shop.example.com/p/123"

    # Kiểm tra PostHistory
    hist = db.query(PostHistory).filter(PostHistory.wp_post_id == "123").first()
    assert hist is not None
    assert hist.status == "scheduled"
    assert hist.wp_post_url == "https://shop.example.com/p/123"
    db.close()


def test_core_cancel_scheduled_job_updates_wp_to_draft(env, monkeypatch):
    mem_db, ids = env
    from core import scheduler as core_sched
    from core import wp_client

    status_updates = []

    def fake_update_status(site_config, scope, wp_id, new_status):
        status_updates.append((scope, wp_id, new_status))
        return {"id": wp_id, "status": new_status}

    monkeypatch.setattr(wp_client, "update_item_status", fake_update_status)

    db = mem_db()
    job = ScheduledPost(
        product_name="Sản phẩm Hủy",
        post_type="product",
        post_status="future",
        status="pending",
        scheduled_time=now_vn() + timedelta(days=2),
        site_names_json=json.dumps(["shop"]),
        article_data_json=json.dumps({"shop": {"title": "SP", "post_id": 789}}),
    )
    db.add(job)
    db.commit()
    job_id = job.id
    db.close()

    ok = core_sched.cancel_scheduled_job(job_id)
    assert ok is True
    assert ("product", 789, "draft") in status_updates

    db = mem_db()
    updated_job = db.get(ScheduledPost, job_id)
    assert updated_job.status == "cancelled"
    assert "bản nháp" in updated_job.result_message
    db.close()


def test_execute_scheduled_job_with_existing_post_marks_completed(env, monkeypatch):
    mem_db, ids = env
    from core import scheduler as core_sched

    from core import wp_client

    pub_called = []
    monkeypatch.setattr(core_sched, "publish_articles", lambda **kw: pub_called.append(kw) or [])
    # WP-Cron nhỡ lịch: bài vẫn 'future' -> scheduler tự chuyển sang publish
    monkeypatch.setattr(wp_client, "get_item", lambda cfg, scope, wp_id: {"id": wp_id, "status": "future", "url": ""})
    pushed = []
    monkeypatch.setattr(wp_client, "update_item_status", lambda cfg, scope, wp_id, st: pushed.append(st) or
                        {"id": wp_id, "status": "publish", "url": "https://shop.example.com/p/999"})

    db = mem_db()
    job = ScheduledPost(
        product_name="Bài tương lai",
        post_type="product",
        post_status="future",
        status="pending",
        scheduled_time=now_vn() - timedelta(minutes=1),
        site_names_json=json.dumps(["shop"]),
        article_data_json=json.dumps({"shop": {"title": "SP", "post_id": 999}}),
    )
    db.add(job)
    db.commit()
    job_id = job.id
    db.close()

    core_sched.execute_scheduled_job(job_id)

    # Không gọi lại publish_articles vì WordPress đã tự động xuất bản
    assert len(pub_called) == 0

    db = mem_db()
    j = db.get(ScheduledPost, job_id)
    assert j.status == "completed"
    assert pushed == ["publish"]
    assert "1/1" in j.result_message
    db.close()


def test_core_delete_scheduled_job_trashes_and_deletes(env, monkeypatch):
    mem_db, ids = env
    from core import scheduler as core_sched
    from core import wp_client

    trashed = []
    monkeypatch.setattr(wp_client, "trash_item", lambda cfg, scope, wp_id: trashed.append((scope, wp_id)))
    monkeypatch.setattr(wp_client, "update_item_status", lambda *a, **k: None)

    db = mem_db()
    job = ScheduledPost(
        product_name="SP Xóa",
        post_type="product",
        post_status="future",
        status="pending",
        scheduled_time=now_vn() + timedelta(days=2),
        site_names_json=json.dumps(["shop"]),
        article_data_json=json.dumps({"shop": {"title": "SP", "post_id": 555}}),
    )
    db.add(job)
    db.commit()
    j_id = job.id
    db.close()

    ok = core_sched.delete_scheduled_job(j_id)
    assert ok is True
    assert ("product", 555) in trashed

    db = mem_db()
    assert db.get(ScheduledPost, j_id) is None
    db.close()


def _add_job(mem_db, **kw):
    fields = dict(product_name="SP", post_type="product", post_status="publish", status="pending",
                  scheduled_time=now_vn() + timedelta(days=2), site_names_json=json.dumps(["shop"]),
                  article_data_json=json.dumps({"shop": {"title": "SP", "post_id": 42}}))
    fields.update(kw)
    db = mem_db()
    job = ScheduledPost(**fields)
    db.add(job)
    db.commit()
    job_id = job.id
    db.close()
    return job_id


def test_draft_schedule_does_not_touch_wordpress_until_due(env, monkeypatch):
    mem_db, _ = env
    from core import scheduler as core_sched

    calls = []
    monkeypatch.setattr(core_sched, "publish_articles", lambda **kw: calls.append(kw) or [
        {"site_name": "shop", "success": True, "post_id": 5, "post_url": "u"}])
    job_id = core_sched.schedule_publish_job(
        product_name="SP", articles={"shop": {"title": "T", "raw_html": "<p>x</p>"}}, site_names=["shop"],
        scheduled_time=now_vn() + timedelta(hours=1), post_type="product", post_status="draft")
    assert calls == []
    db = mem_db()
    job = db.get(ScheduledPost, job_id)
    assert job.post_status == "draft" and job.status == "pending"
    job.scheduled_time = now_vn() - timedelta(seconds=1)
    db.commit()
    db.close()

    core_sched.execute_scheduled_job(job_id)
    assert len(calls) == 1 and calls[0]["post_status"] == "draft"
    db = mem_db()
    assert db.get(ScheduledPost, job_id).status == "completed"
    assert db.query(PostHistory).filter(PostHistory.wp_post_id == "5").one().status == "draft"
    db.close()


def test_cancel_and_delete_never_touch_wordpress_for_finished_jobs(env, monkeypatch):
    mem_db, _ = env
    from core import scheduler as core_sched
    from core import wp_client

    touched = []
    monkeypatch.setattr(wp_client, "update_item_status", lambda *a: touched.append(("status", a)))
    monkeypatch.setattr(wp_client, "trash_item", lambda *a: touched.append(("trash", a)))
    job_id = _add_job(mem_db, status="completed")
    assert core_sched.cancel_scheduled_job(job_id) is False
    assert core_sched.delete_scheduled_job(job_id) is True
    assert touched == []


def test_cancel_uses_product_scope_for_display_label(env, monkeypatch):
    mem_db, _ = env
    from core import scheduler as core_sched
    from core import wp_client

    scopes = []
    monkeypatch.setattr(wp_client, "update_item_status", lambda cfg, scope, wp_id, st: scopes.append(scope))
    job_id = _add_job(mem_db, post_type="Sản phẩm WooCommerce")
    assert core_sched.cancel_scheduled_job(job_id) is True
    assert scopes == ["product"]


def test_cancel_keeps_job_pending_when_wordpress_fails(env, monkeypatch):
    mem_db, _ = env
    from core import wp_client

    def boom(*a):
        raise RuntimeError("503")

    monkeypatch.setattr(wp_client, "update_item_status", boom)
    job_id = _add_job(mem_db)
    with pytest.raises(ServiceError, match="503"):
        svc.cancel_job(job_id)
    with pytest.raises(ServiceError):
        svc.delete_job(job_id)
    db = mem_db()
    assert db.get(ScheduledPost, job_id).status == "pending"
    db.close()


def test_execute_retries_sites_that_failed_when_scheduling(env, monkeypatch):
    mem_db, _ = env
    from core import scheduler as core_sched
    from core import wp_client

    db = mem_db()
    db.add(Site(name="blog", url="https://blog.example.com"))
    db.commit()
    db.close()
    monkeypatch.setattr(wp_client, "get_item", lambda cfg, scope, wp_id: {"id": wp_id, "status": "publish", "url": "u"})
    calls = []
    monkeypatch.setattr(core_sched, "publish_articles", lambda **kw: calls.append(kw) or [
        {"site_name": "blog", "success": False, "error": "401"}])
    job_id = _add_job(
        mem_db, scheduled_time=now_vn() - timedelta(minutes=1), site_names_json=json.dumps(["shop", "blog"]),
        article_data_json=json.dumps({"shop": {"title": "SP", "post_id": 42},
                                      "blog": {"title": "SP", "schedule_error": "timeout"}}))
    core_sched.execute_scheduled_job(job_id)
    assert list(calls[0]["articles"]) == ["blog"] and calls[0]["post_status"] == "publish"
    db = mem_db()
    job = db.get(ScheduledPost, job_id)
    assert job.status == "partially_completed" and "blog: 401" in job.result_message
    db.close()


def test_overdue_job_without_post_is_not_published_late(env, monkeypatch):
    mem_db, _ = env
    from core import scheduler as core_sched

    calls = []
    monkeypatch.setattr(core_sched, "publish_articles", lambda **kw: calls.append(kw) or [])
    job_id = _add_job(mem_db, post_status="draft", article_data_json=json.dumps({"shop": {"title": "SP"}}))
    core_sched.execute_scheduled_job(job_id, publish_missing=False)
    assert calls == []
    db = mem_db()
    assert db.get(ScheduledPost, job_id).status == "failed"
    db.close()


def test_save_job_tags_updates_scheduled_post_on_wordpress(env, monkeypatch):
    mem_db, ids = env
    from core import taxonomy_service
    from core import wp_client

    db = mem_db()
    job = db.get(ScheduledPost, ids["job"])
    arts = json.loads(job.article_data_json)
    arts["shop"]["post_id"] = 77
    job.article_data_json = json.dumps(arts)
    db.commit()
    db.close()
    monkeypatch.setattr(taxonomy_service.wp_client, "ensure_tags", lambda cfg, scope, names: [11, 12])
    pushed = []
    monkeypatch.setattr(wp_client, "update_item_taxonomy", lambda *a: pushed.append(a))
    msg = svc.save_job_tags("x, y", ids["job"], "shop")
    assert msg.startswith("💾")
    assert pushed and pushed[0][1:] == ("product", 77, [1], [11, 12])
