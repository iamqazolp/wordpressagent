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
    assert calls == [5, ids["done"], ids["done"]]


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
