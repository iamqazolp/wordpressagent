import json
from datetime import datetime, timedelta

import pytest
import requests
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core import pipeline, taxonomy_service, wp_client
from core.taxonomy_ai import (
    MAX_CATEGORIES,
    MAX_TAGS,
    category_labels,
    parse_and_validate,
    suggest_taxonomy,
)
from db import crud
from db.models import Base, PostHistory, Site

SITE_CFG = {
    "url": "https://shop.example.com/",
    "client_key": "ck_x",
    "client_secret": "cs_x",
    "wp_user": "admin",
    "wp_app_password": "app pass",
}


class FakeResp:
    def __init__(self, data=None, status=200, headers=None):
        self._data, self.status_code, self.headers, self.text = data, status, headers or {}, json.dumps(data)

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"{self.status_code}")


# ── fetch_categories ─────────────────────────────────────────

def _cat(i, parent=0, name=None):
    return {"id": i, "name": name or f"Cat {i}", "parent": parent}


def test_fetch_categories_paginates_until_short_page(monkeypatch):
    pages = {1: [_cat(i) for i in range(100)], 2: [_cat(i) for i in range(100, 200)], 3: [_cat(i) for i in range(200, 237)]}
    calls = []

    def fake_get(url, auth=None, timeout=None, params=None):
        calls.append((url, params["page"]))
        return FakeResp(pages[params["page"]])

    monkeypatch.setattr(wp_client.requests, "get", fake_get)
    cats = wp_client.fetch_categories(SITE_CFG, "product")
    assert len(cats) == 237
    assert [c[1] for c in calls] == [1, 2, 3]


def test_fetch_categories_stops_on_400_past_last_page(monkeypatch):
    def fake_get(url, auth=None, timeout=None, params=None):
        if params["page"] == 1:
            return FakeResp([_cat(i) for i in range(100)])
        return FakeResp({"code": "rest_post_invalid_page_number"}, status=400)

    monkeypatch.setattr(wp_client.requests, "get", fake_get)
    assert len(wp_client.fetch_categories(SITE_CFG, "post")) == 100


def test_fetch_categories_uses_correct_endpoint_and_auth_per_scope(monkeypatch):
    seen = {}

    def fake_get(url, auth=None, timeout=None, params=None):
        seen[url] = (auth.username, auth.password)
        return FakeResp([])

    monkeypatch.setattr(wp_client.requests, "get", fake_get)
    wp_client.fetch_categories(SITE_CFG, "product")
    wp_client.fetch_categories(SITE_CFG, "post")
    assert seen["https://shop.example.com/wp-json/wc/v3/products/categories"] == ("ck_x", "cs_x")
    assert seen["https://shop.example.com/wp-json/wp/v2/categories"] == ("admin", "app pass")


def test_fetch_categories_unescapes_names_and_raises_on_error(monkeypatch):
    monkeypatch.setattr(wp_client.requests, "get", lambda *a, **k: FakeResp([_cat(1, name="Quạt &amp; Máy")]))
    assert wp_client.fetch_categories(SITE_CFG, "post")[0]["name"] == "Quạt & Máy"

    monkeypatch.setattr(wp_client.requests, "get", lambda *a, **k: FakeResp({"err": 1}, status=500))
    with pytest.raises(requests.exceptions.HTTPError):
        wp_client.fetch_categories(SITE_CFG, "post")

    monkeypatch.setattr(wp_client.requests, "get", lambda *a, **k: FakeResp({"not": "a list"}))
    with pytest.raises(ValueError):
        wp_client.fetch_categories(SITE_CFG, "post")


# ── ensure_tags ──────────────────────────────────────────────

def test_ensure_tags_matches_existing_case_insensitively_and_creates_missing(monkeypatch):
    created = []

    def fake_get(url, auth=None, timeout=None, params=None):
        if params["search"].casefold() == "quạt công nghiệp":
            return FakeResp([{"id": 7, "name": "Quạt Công Nghiệp"}, {"id": 8, "name": "Quạt công nghiệp lớn"}])
        return FakeResp([])

    def fake_post(url, auth=None, json=None, timeout=None):
        created.append(json["name"])
        return FakeResp({"id": 99, "name": json["name"]}, status=201)

    monkeypatch.setattr(wp_client.requests, "get", fake_get)
    monkeypatch.setattr(wp_client.requests, "post", fake_post)
    ids = wp_client.ensure_tags(SITE_CFG, "product", ["quạt công nghiệp", "Pa lăng xích"])
    assert ids == [7, 99]
    assert created == ["Pa lăng xích"]  # tag đã có thì không tạo lại


def test_ensure_tags_dedupes_input_and_handles_term_exists(monkeypatch):
    monkeypatch.setattr(wp_client.requests, "get", lambda *a, **k: FakeResp([]))
    posts = []

    def fake_post(url, auth=None, json=None, timeout=None):
        posts.append(json["name"])
        return FakeResp({"code": "term_exists", "data": {"term_id": 55}}, status=400)

    monkeypatch.setattr(wp_client.requests, "post", fake_post)
    ids = wp_client.ensure_tags(SITE_CFG, "post", ["Tag A", "tag a", "  TAG   A ", ""])
    assert ids == [55]
    assert len(posts) == 1

    def fake_post_woo(url, auth=None, json=None, timeout=None):
        return FakeResp({"code": "term_exists", "data": {"resource_id": 66}}, status=400)

    monkeypatch.setattr(wp_client.requests, "post", fake_post_woo)
    assert wp_client.ensure_tags(SITE_CFG, "product", ["x1"]) == [66]


def test_ensure_tags_skips_failing_tag_but_keeps_others(monkeypatch):
    def fake_get(url, auth=None, timeout=None, params=None):
        if params["search"] == "bad":
            raise requests.exceptions.ConnectionError("down")
        return FakeResp([])

    monkeypatch.setattr(wp_client.requests, "get", fake_get)
    monkeypatch.setattr(wp_client.requests, "post", lambda *a, **k: FakeResp({"id": 5}, status=201))
    assert wp_client.ensure_tags(SITE_CFG, "post", ["bad", "good"]) == [5]


# ── publish payload ──────────────────────────────────────────

def test_publish_product_and_post_send_categories_and_tags(monkeypatch):
    sent = {}

    def fake_post(url, auth=None, json=None, timeout=None):
        sent[url] = json
        return FakeResp({"id": 1, "permalink": "p", "link": "l"}, status=201)

    monkeypatch.setattr(wp_client.requests, "post", fake_post)
    wp_client.publish_product("T", "<p>x</p>", [], SITE_CFG, category_ids=[3, 4], tag_ids=[9])
    wp_client.publish_post("T", "<p>x</p>", [], SITE_CFG, category_ids=[3, 4], tag_ids=[9])
    prod = sent["https://shop.example.com/wp-json/wc/v3/products"]
    post = sent["https://shop.example.com/wp-json/wp/v2/posts"]
    assert prod["categories"] == [{"id": 3}, {"id": 4}] and prod["tags"] == [{"id": 9}]
    assert post["categories"] == [3, 4] and post["tags"] == [9]


def test_publish_without_taxonomy_omits_keys(monkeypatch):
    sent = {}
    monkeypatch.setattr(wp_client.requests, "post", lambda url, auth=None, json=None, timeout=None: sent.update(json) or FakeResp({"id": 1, "permalink": "p"}, 201))
    wp_client.publish_product("T", "<p>x</p>", [], SITE_CFG)
    assert "categories" not in sent and "tags" not in sent


# ── pipeline integration ─────────────────────────────────────

def test_publish_articles_passes_category_and_resolved_tags(monkeypatch):
    got = {}
    monkeypatch.setattr(taxonomy_service, "resolve_tag_ids", lambda cfg, pt, names: ([11, 12], "cảnh báo thử") if names == ["a", "b"] else ([], None))
    monkeypatch.setattr(wp_client, "publish_product", lambda **kw: got.update(kw) or {"post_id": 1, "post_url": "u", "edit_url": "e", "status": "draft"})

    res = pipeline.publish_articles(
        articles={"s1": {"title": "T", "raw_html": "<p>x</p>", "category_ids": ["5", 6], "tags": ["a", "b"]}},
        image_files=None,
        site_configs={"s1": SITE_CFG},
        post_type="Sản phẩm WooCommerce",
        post_status="draft",
    )
    assert got["category_ids"] == [5, 6] and got["tag_ids"] == [11, 12]
    assert res[0]["success"] and res[0]["taxonomy_warning"] == "cảnh báo thử"


def test_publish_articles_without_taxonomy_still_works(monkeypatch):
    got = {}
    monkeypatch.setattr(wp_client, "publish_product", lambda **kw: got.update(kw) or {"post_id": 1, "post_url": "u", "edit_url": "e", "status": "draft"})
    res = pipeline.publish_articles(
        articles={"s1": {"title": "T", "raw_html": "<p>x</p>"}},
        image_files=None, site_configs={"s1": SITE_CFG}, post_type="product", post_status="draft",
    )
    assert res[0]["success"] and got["category_ids"] == [] and got["tag_ids"] == []


# ── DB cache ─────────────────────────────────────────────────

@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    site = Site(name="shop", url="https://shop.example.com")
    session.add(site)
    session.commit()
    yield session
    session.close()


def test_replace_categories_replaces_only_that_scope_and_dedupes(db):
    sid = db.query(Site).first().id
    crud.replace_site_categories(db, sid, "product", [_cat(1), _cat(2), _cat(2)])
    crud.replace_site_categories(db, sid, "post", [_cat(10)])
    assert len(crud.get_site_categories(db, sid, "product")) == 2
    crud.replace_site_categories(db, sid, "product", [_cat(3)])
    assert [r.wp_id for r in crud.get_site_categories(db, sid, "product")] == [3]
    assert [r.wp_id for r in crud.get_site_categories(db, sid, "post")] == [10]


def test_staleness_ttl(db):
    sid = db.query(Site).first().id
    assert crud.is_categories_stale(db, sid, "product")  # chưa có cache
    crud.replace_site_categories(db, sid, "product", [_cat(1)])
    assert not crud.is_categories_stale(db, sid, "product")
    assert crud.is_categories_stale(db, sid, "product", now=datetime.now() + timedelta(hours=25))
    assert not crud.is_categories_stale(db, sid, "product", now=datetime.now() + timedelta(hours=23))


def test_deleting_site_removes_its_taxonomy(db):
    site = db.query(Site).first()
    crud.replace_site_categories(db, site.id, "product", [_cat(1)])
    db.delete(site)
    db.commit()
    assert db.query(crud.SiteTaxonomy).count() == 0


def test_post_history_stores_category_and_tags(db):
    sid = db.query(Site).first().id
    h = crud.create_post_history(db, site_id=sid, product_name="p", category_ids_json=json.dumps([1, 2]), tags_json=json.dumps(["x"]))
    assert json.loads(h.category_ids_json) == [1, 2] and json.loads(h.tags_json) == ["x"]


# ── service ──────────────────────────────────────────────────

def test_sync_failure_keeps_old_cache_and_other_scope_still_updates(db, monkeypatch):
    sid = db.query(Site).first().id
    crud.replace_site_categories(db, sid, "product", [_cat(1, name="Cũ")])
    monkeypatch.setattr(crud, "get_site_config", lambda d, i: SITE_CFG)

    def fake_fetch(cfg, scope, **kw):
        if scope == "product":
            raise requests.exceptions.ConnectionError("down")
        return [_cat(20, name="Blog cat")]

    monkeypatch.setattr(wp_client, "fetch_categories", fake_fetch)
    report = taxonomy_service.sync_site_categories(db, "shop")
    assert report["product"]["ok"] is False and "down" in report["product"]["error"]
    assert report["post"] == {"ok": True, "count": 1, "error": None}
    assert [r.name for r in crud.get_site_categories(db, sid, "product")] == ["Cũ"]   # cache cũ còn nguyên
    assert [r.name for r in crud.get_site_categories(db, sid, "post")] == ["Blog cat"]


def test_sync_unknown_site_reports_error(db):
    report = taxonomy_service.sync_site_categories(db, "nope")
    assert all(not v["ok"] for v in report.values())


def test_category_choices_show_hierarchy_labels(db, monkeypatch):
    sid = db.query(Site).first().id
    crud.replace_site_categories(db, sid, "product", [_cat(1, name="Quạt"), _cat(2, parent=1, name="Quạt công nghiệp")])
    choices = taxonomy_service.get_category_choices(db, "shop", "product")
    assert ("Quạt › Quạt công nghiệp", 2) in choices and ("Quạt", 1) in choices


def test_ensure_fresh_syncs_only_when_stale(db, monkeypatch):
    sid = db.query(Site).first().id
    monkeypatch.setattr(crud, "get_site_config", lambda d, i: SITE_CFG)
    calls = []
    monkeypatch.setattr(wp_client, "fetch_categories", lambda cfg, scope, **kw: calls.append(scope) or [_cat(1)])
    assert taxonomy_service.ensure_fresh_categories(db, "shop", "product") is True
    assert taxonomy_service.ensure_fresh_categories(db, "shop", "product") is True
    assert calls == ["product"]  # lần 2 dùng cache


def test_resolve_tag_ids_never_raises(monkeypatch):
    monkeypatch.setattr(wp_client, "ensure_tags", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    ids, warn = taxonomy_service.resolve_tag_ids(SITE_CFG, "product", ["a"])
    assert ids == [] and "x" in warn
    assert taxonomy_service.resolve_tag_ids(SITE_CFG, "product", []) == ([], None)
    monkeypatch.setattr(wp_client, "ensure_tags", lambda *a, **k: [1])
    ids, warn = taxonomy_service.resolve_tag_ids(SITE_CFG, "product", ["a", "b"])
    assert ids == [1] and "1/2" in warn


def test_scope_for_post_type():
    assert taxonomy_service.scope_for_post_type("Sản phẩm WooCommerce") == "product"
    assert taxonomy_service.scope_for_post_type("product") == "product"
    assert taxonomy_service.scope_for_post_type("Bài viết Blog") == "post"


# ── AI validation ────────────────────────────────────────────

CATS = [_cat(1, name="Quạt"), _cat(2, parent=1, name="Quạt công nghiệp"), _cat(3, name="Pa lăng")]


def test_parse_filters_invented_ids_dupes_and_caps():
    raw = json.dumps({"category_ids": [2, "2", 999, "abc", 3, 1], "tags": ["#Quạt", "quạt", "Pa lăng", "a", "x" * 50, 5, "ok, tag"]})
    out = parse_and_validate(raw, CATS)
    assert out["category_ids"] == [2, 3]            # 999/abc bị loại, trùng bị loại, cắt còn MAX_CATEGORIES
    assert len(out["category_ids"]) <= MAX_CATEGORIES
    assert out["tags"] == ["Quạt", "Pa lăng", "ok tag"]   # "a" quá ngắn, 50 ký tự quá dài, số bị loại, trùng không phân biệt hoa/thường


def test_parse_caps_tags_and_accepts_markdown_fence():
    raw = "```json\n" + json.dumps({"category_ids": [], "tags": [f"tag số {i}" for i in range(20)]}) + "\n```"
    assert len(parse_and_validate(raw, CATS)["tags"]) == MAX_TAGS


@pytest.mark.parametrize("raw", ["", "không có json", "[1,2,3]", "{bad json}"])
def test_parse_rejects_garbage(raw):
    with pytest.raises(Exception):
        parse_and_validate(raw, CATS)


def test_suggest_never_raises_and_reports_error():
    out = suggest_taxonomy("t", "", "<p>x</p>", CATS, generate=lambda p: (_ for _ in ()).throw(TimeoutError("slow")))
    assert out["category_ids"] == [] and out["tags"] == [] and "slow" in out["error"]


def test_suggest_happy_path_and_prompt_contains_real_categories():
    captured = {}

    def gen(prompt):
        captured["p"] = prompt
        return json.dumps({"category_ids": [2], "tags": ["quạt hút", "nhà xưởng"]})

    out = suggest_taxonomy("Quạt hút X", "", "<p>mô tả</p>", CATS, generate=gen)
    assert out == {"category_ids": [2], "tags": ["quạt hút", "nhà xưởng"]}
    assert "2: Quạt › Quạt công nghiệp" in captured["p"]


def test_suggest_without_categories_returns_no_category():
    out = suggest_taxonomy("t", "", "", [], generate=lambda p: json.dumps({"category_ids": [1], "tags": ["abc"]}))
    assert out["category_ids"] == [] and out["tags"] == ["abc"]


def test_category_labels_survive_cycles():
    cyc = [{"id": 1, "name": "A", "parent": 2}, {"id": 2, "name": "B", "parent": 1}]
    labels = category_labels(cyc)   # không được lặp vô hạn
    assert set(labels) == {1, 2}


def test_duplicate_category_names_are_disambiguated_with_id(db):
    sid = db.query(Site).first().id
    crud.replace_site_categories(db, sid, "product", [_cat(463, name="Dây Cáp Vải"), _cat(464, name="Dây Cáp Vải"), _cat(5, name="Quạt")])
    labels = dict((cid, label) for label, cid in taxonomy_service.get_category_choices(db, "shop", "product"))
    assert labels[463] == "Dây Cáp Vải · #463" and labels[464] == "Dây Cáp Vải · #464"
    assert labels[5] == "Quạt"                     # tên duy nhất thì giữ nguyên


def test_truncated_ai_json_is_reported_not_crashed():
    # Lỗi thật đã gặp: model hết token giữa chừng -> JSON cụt
    out = suggest_taxonomy("t", "", "", CATS, generate=lambda p: '{"category_ids": [], "tags": ["quạt cây công nghiệp", "quạt công nghiệp')
    assert out["category_ids"] == [] and out["tags"] == [] and out["error"]
