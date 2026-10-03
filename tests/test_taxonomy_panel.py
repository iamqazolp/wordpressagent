import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core import taxonomy_service, wp_client
from db import crud
from db.models import Base, Site
from ui import taxonomy_panel as tp

SITE_CFG = {"url": "https://shop.example.com", "client_key": "k", "client_secret": "s", "wp_user": "", "wp_app_password": ""}


@pytest.fixture
def env(monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    seed = Session()
    site = Site(name="shop", url="https://shop.example.com")
    seed.add(site)
    seed.commit()
    site_id = site.id
    crud.replace_site_categories(seed, site_id, "product", [
        {"id": 1, "name": "Quạt", "parent": 0},
        {"id": 2, "name": "Quạt công nghiệp", "parent": 1},
    ])
    crud.replace_site_categories(seed, site_id, "post", [{"id": 50, "name": "Tin tức", "parent": 0}])
    seed.close()
    monkeypatch.setattr(tp, "SessionLocal", Session)
    monkeypatch.setattr(crud, "get_site_config", lambda d, i: SITE_CFG)
    return Session


def state(**art):
    base = {"title": "Quạt hút X", "raw_html": "<p>x</p>", "short_description": ""}
    base.update(art)
    return {"shop": base}


def test_parse_tags():
    assert tp.parse_tags("a, B ,#c\nb;; ,  d  e ") == ["a", "B", "c", "d e"]
    assert tp.parse_tags("") == [] and tp.parse_tags(None) == []


def test_refresh_without_articles(env):
    drop, tags, status = tp.refresh_taxonomy_controls({}, "", "product")
    assert drop["choices"] == [] and tags == "" and "Tạo bài viết trước" in status
    drop, _, _ = tp.refresh_taxonomy_controls(state(), "ghost-site", "product")
    assert drop["choices"] == []


def test_refresh_lists_choices_and_filters_selection(env):
    st = state(category_ids=[2, 999], category_scope="product", tags=["quạt hút", "xưởng"])
    drop, tags, status = tp.refresh_taxonomy_controls(st, "shop", "Sản phẩm WooCommerce")
    labels = [c[0] for c in drop["choices"]]
    assert "Quạt › Quạt công nghiệp" in labels
    assert drop["value"] == [2]                    # 999 không tồn tại -> không hiển thị
    assert tags == "quạt hút, xưởng"
    assert "2 danh mục" in status


def test_refresh_hides_selection_from_other_scope(env):
    st = state(category_ids=[2], category_scope="product")
    drop, _, _ = tp.refresh_taxonomy_controls(st, "shop", "Bài viết Blog")
    assert [c[1] for c in drop["choices"]] == [50]
    assert drop["value"] == []                     # id của product không dùng cho blog
    assert st["shop"]["category_ids"] == [2]       # nhưng không xoá dữ liệu gốc


def test_manual_input_handlers_store_scope_and_tags():
    st = state()
    tp.on_categories_input([2, "1"], "shop", st, "Sản phẩm WooCommerce")
    assert st["shop"]["category_ids"] == [2, 1] and st["shop"]["category_scope"] == "product"
    tp.on_tags_input("a, b", "shop", st)
    assert st["shop"]["tags"] == ["a", "b"]
    # site lạ / state rỗng không lỗi
    assert tp.on_categories_input([1], "x", st, "product") is st
    assert tp.on_tags_input("a", "x", None) is None


def test_ai_suggest_writes_validated_result(env, monkeypatch):
    seen = {}

    def fake_suggest(title, short, html, cats):
        seen["cats"] = [c["id"] for c in cats]
        return {"category_ids": [2], "tags": ["quạt hút"]}

    monkeypatch.setattr(tp, "suggest_taxonomy", fake_suggest)
    st = state()
    new_state, drop, tags, status = tp.on_ai_suggest(st, "shop", "product")
    assert sorted(seen["cats"]) == [1, 2]
    assert new_state["shop"]["category_ids"] == [2] and new_state["shop"]["category_scope"] == "product"
    assert new_state["shop"]["tags"] == ["quạt hút"] and tags == "quạt hút"
    assert drop["value"] == [2] and "AI" in status


def test_ai_suggest_failure_leaves_selection_untouched(env, monkeypatch):
    monkeypatch.setattr(tp, "suggest_taxonomy", lambda *a: {"category_ids": [], "tags": [], "error": "hết hạn mức"})
    st = state(category_ids=[1], category_scope="product", tags=["giữ nguyên"])
    new_state, drop, tags, status = tp.on_ai_suggest(st, "shop", "product")
    assert new_state["shop"]["category_ids"] == [1] and new_state["shop"]["tags"] == ["giữ nguyên"]
    assert "hết hạn mức" in status


def test_autofill_skips_sites_with_selection_and_never_raises(env, monkeypatch):
    calls = []
    monkeypatch.setattr(tp, "suggest_taxonomy", lambda title, *a: calls.append(title) or {"category_ids": [1], "tags": ["t1"]})
    st = {
        "shop": {"title": "A", "raw_html": "", "short_description": ""},
        "keep": {"title": "B", "raw_html": "", "tags": ["đã chọn"]},
    }
    out = tp.autofill_taxonomy(st, "product")
    assert out["shop"]["category_ids"] == [1] and out["shop"]["tags"] == ["t1"]
    assert out["keep"]["tags"] == ["đã chọn"] and calls == ["A"]

    monkeypatch.setattr(tp, "_suggest_for_site", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert tp.autofill_taxonomy({"shop": {"title": "A"}}, "product") == {"shop": {"title": "A"}}
    assert tp.autofill_taxonomy({}, "product") == {}


def test_autofill_uses_cache_without_network(env, monkeypatch):
    def no_network(*a, **k):
        raise AssertionError("không được gọi mạng khi đã có cache")

    monkeypatch.setattr(wp_client, "fetch_categories", no_network)
    monkeypatch.setattr(tp, "suggest_taxonomy", lambda *a: {"category_ids": [1], "tags": []})
    st = {"shop": {"title": "A", "raw_html": "", "short_description": ""}}
    assert tp.autofill_taxonomy(st, "product")["shop"]["category_ids"] == [1]


def test_sync_button_reports_each_scope(env, monkeypatch):
    def fake_fetch(cfg, scope, **kw):
        if scope == "post":
            raise RuntimeError("401 Unauthorized")
        return [{"id": 7, "name": "Mới", "parent": 0}]

    monkeypatch.setattr(wp_client, "fetch_categories", fake_fetch)
    drop, tags, status = tp.on_sync_categories(state(), "shop", "product")
    assert [c[1] for c in drop["choices"]] == [7]
    assert "WooCommerce: ✅ 1" in status and "Blog: ❌ 401" in status


def test_effective_category_ids_scope_rules():
    f = taxonomy_service.effective_category_ids
    assert f({"category_ids": ["3", 3, "x", 4]}, "product") == [3, 4]          # không scope (dữ liệu cũ) -> hợp lệ
    assert f({"category_ids": [3], "category_scope": "product"}, "Sản phẩm WooCommerce") == [3]
    assert f({"category_ids": [3], "category_scope": "product"}, "Bài viết Blog") == []
    assert f({}, "product") == []
