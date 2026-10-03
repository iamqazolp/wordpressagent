import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from db import crud
from db.models import Base, PostHistory, ScheduledPost, Site
from core.timeutil import now_vn
from ui import taxonomy_panel as tp
from ui import taxonomy_records as tr
from datetime import timedelta

SITE_CFG = {"url": "https://shop.example.com", "client_key": "k", "client_secret": "s", "wp_user": "", "wp_app_password": ""}


@pytest.fixture
def env(monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    site = Site(name="shop", url="https://shop.example.com")
    s.add(site)
    s.commit()
    crud.replace_site_categories(s, site.id, "product", [
        {"id": 1, "name": "Quạt", "parent": 0},
        {"id": 2, "name": "Quạt công nghiệp", "parent": 1},
    ])
    crud.replace_site_categories(s, site.id, "post", [{"id": 50, "name": "Tin tức", "parent": 0}])
    h = PostHistory(site_id=site.id, product_name="Quạt X", title="Quạt X", raw_html="<p>x</p>", post_type="product",
                    status="saved", category_ids_json="[2]", tags_json='["quạt hút"]')
    job = ScheduledPost(
        product_name="Quạt X", post_type="product", post_status="draft", status="pending",
        scheduled_time=now_vn() + timedelta(days=1),
        site_names_json=json.dumps(["shop"]),
        article_data_json=json.dumps({"shop": {"title": "T", "raw_html": "<p>x</p>", "category_ids": [1],
                                               "category_scope": "product", "tags": ["a"]}}),
    )
    s.add_all([h, job])
    s.commit()
    ids = (h.id, job.id)
    s.close()
    for mod in (tr, tp):
        monkeypatch.setattr(mod, "SessionLocal", Session)
    monkeypatch.setattr(crud, "get_site_config", lambda d, i: SITE_CFG)
    return Session, ids


def choice(hid):
    return f"#{hid} - Quạt X (shop) [Đã lưu]"


# ── bài đã lưu ───────────────────────────────────────────────────────────────

def test_summarize_history_and_job(env):
    Session, (hid, jid) = env
    db = Session()
    assert tr.summarize_history(db, db.get(PostHistory, hid)) == "📂 Quạt › Quạt công nghiệp · 🏷️ quạt hút"
    assert tr.summarize_job(db, db.get(ScheduledPost, jid)) == "📂 Quạt · 🏷️ a"
    h = db.get(PostHistory, hid)
    h.category_ids_json, h.tags_json = "[]", "[]"
    assert tr.summarize_history(db, h) == "-"
    h.category_ids_json = "[999]"
    assert tr.summarize_history(db, h) == "📂 #999"   # id không còn trong cache vẫn hiện, không crash
    db.close()


def test_history_load_shows_saved_values(env):
    _, (hid, _) = env
    drop, tags, status = tr.history_load(choice(hid), "Sản phẩm WooCommerce")
    assert drop["value"] == [2] and tags == "quạt hút"
    assert "2 danh mục" in status and "⚠️" not in status


def test_history_load_scope_mismatch_warns_and_hides(env):
    _, (hid, _) = env
    drop, _, status = tr.history_load(choice(hid), "Bài viết Blog")
    assert drop["value"] == []
    assert [c[1] for c in drop["choices"]] == [50]
    assert "không áp dụng" in status


def test_history_load_without_selection(env):
    drop, tags, status = tr.history_load("(Chưa có bài viết nào)", "Sản phẩm WooCommerce")
    assert drop["choices"] == [] and "Chọn một bài viết" in status


def test_history_save_categories_and_tags_persist(env):
    Session, (hid, _) = env
    assert "Đã lưu 2 danh mục" in tr.history_save_categories([1, 2, 2], choice(hid), "Sản phẩm WooCommerce")
    assert "Đã lưu 2 tag" in tr.history_save_tags("x, #y, X", choice(hid))
    db = Session()
    h = db.get(PostHistory, hid)
    assert json.loads(h.category_ids_json) == [1, 2]
    assert json.loads(h.tags_json) == ["x", "y"]
    db.close()


def test_history_save_categories_switches_post_type_to_keep_scope_consistent(env):
    Session, (hid, _) = env
    tr.history_save_categories([50], choice(hid), "Bài viết Blog")
    db = Session()
    h = db.get(PostHistory, hid)
    assert h.post_type == "post" and json.loads(h.category_ids_json) == [50]
    db.close()
    drop, _, _ = tr.history_load(choice(hid), "Bài viết Blog")
    assert drop["value"] == [50]


def test_history_ai_suggest_persists_validated_result(env, monkeypatch):
    Session, (hid, _) = env
    monkeypatch.setattr(tp, "suggest_taxonomy", lambda *a, **k: {"category_ids": [2], "tags": ["ai-tag"]})
    drop, tags, status = tr.history_ai_suggest(choice(hid), "Sản phẩm WooCommerce")
    assert drop["value"] == [2] and tags == "ai-tag" and "lưu" in status
    db = Session()
    assert json.loads(db.get(PostHistory, hid).tags_json) == ["ai-tag"]
    db.close()


def test_history_ai_failure_keeps_saved_values(env, monkeypatch):
    Session, (hid, _) = env
    monkeypatch.setattr(tp, "suggest_taxonomy", lambda *a, **k: {"category_ids": [], "tags": [], "error": "quota"})
    drop, tags, status = tr.history_ai_suggest(choice(hid), "Sản phẩm WooCommerce")
    assert "quota" in status and tags == "quạt hút"
    db = Session()
    assert json.loads(db.get(PostHistory, hid).category_ids_json) == [2]
    db.close()


# ── lịch hẹn giờ ─────────────────────────────────────────────────────────────

def test_sched_load(env):
    _, (_, jid) = env
    site, drop, tags, status = tr.sched_load(str(jid))
    assert site["choices"] == ["shop"] and site["value"] == "shop"
    assert drop["value"] == [1]
    assert tags["value"] == "a" and tags["interactive"] is True


def test_sched_load_invalid_and_missing(env):
    assert "Chọn một lịch" in tr.sched_load("")[3]
    assert "Chọn một lịch" in tr.sched_load("abc")[3]
    assert "Không tìm thấy" in tr.sched_load("9999")[3]


def test_sched_save_updates_only_taxonomy_keys(env):
    Session, (_, jid) = env
    assert "Đã lưu 2 danh mục" in tr.sched_save_categories([1, 2], str(jid), "shop")
    assert "Đã lưu 2 tag" in tr.sched_save_tags("p, q", str(jid), "shop")
    db = Session()
    art = json.loads(db.get(ScheduledPost, jid).article_data_json)["shop"]
    assert art["category_ids"] == [1, 2] and art["tags"] == ["p", "q"]
    assert art["title"] == "T" and art["raw_html"] == "<p>x</p>" and art["category_scope"] == "product"
    db.close()


@pytest.mark.parametrize("status", ["running", "completed", "failed", "cancelled"])
def test_sched_non_pending_is_locked(env, status):
    Session, (_, jid) = env
    db = Session()
    db.get(ScheduledPost, jid).status = status
    db.commit()
    db.close()
    assert "không còn ở trạng thái" in tr.sched_save_categories([2], str(jid), "shop")
    assert "không còn ở trạng thái" in tr.sched_save_tags("zzz", str(jid), "shop")
    site, drop, tags, st = tr.sched_load(str(jid))
    assert drop["interactive"] is False and tags["interactive"] is False and "🔒" in st
    db = Session()
    art = json.loads(db.get(ScheduledPost, jid).article_data_json)["shop"]
    assert art["category_ids"] == [1] and art["tags"] == ["a"]   # không bị đổi
    db.close()


def test_sched_rejects_site_not_in_job(env):
    _, (_, jid) = env
    assert "không thuộc" in tr.sched_save_tags("x", str(jid), "other-site")


def test_sched_ai_suggest_saves(env, monkeypatch):
    Session, (_, jid) = env
    monkeypatch.setattr(tp, "suggest_taxonomy", lambda *a, **k: {"category_ids": [2], "tags": ["t1", "t2"]})
    drop, tags, status = tr.sched_ai_suggest(str(jid), "shop")
    assert drop["value"] == [2] and tags["value"] == "t1, t2"
    db = Session()
    art = json.loads(db.get(ScheduledPost, jid).article_data_json)["shop"]
    assert art["category_ids"] == [2] and art["tags"] == ["t1", "t2"]
    db.close()


def test_scheduler_table_has_taxonomy_column(env, monkeypatch):
    Session, _ = env
    from ui import tab_scheduler
    monkeypatch.setattr(tab_scheduler, "SessionLocal", Session)
    df = tab_scheduler.fetch_scheduler_data()
    assert "Danh mục & Tag" in df.columns
    assert df.iloc[0]["Danh mục & Tag"] == "📂 Quạt · 🏷️ a"


def test_history_table_has_taxonomy_column(env, monkeypatch):
    Session, _ = env
    from db import database
    from ui import tab_history
    monkeypatch.setattr(database, "SessionLocal", Session)
    df = tab_history.fetch_history_data()
    assert df.iloc[0]["Danh mục / Tag"].startswith("📂 Quạt › Quạt công nghiệp")
