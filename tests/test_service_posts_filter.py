"""services/posts.list_posts: lọc trạng thái trong SQL (trước LIMIT)."""
from datetime import timedelta

from core.timeutil import now_vn
from db.models import PostHistory, Site
from services import posts


def test_status_filter_applies_before_limit(mem_db):
    s = mem_db()
    site = Site(name="shop", url="https://shop.example.com")
    s.add(site)
    s.commit()
    old = now_vn() - timedelta(days=30)
    s.add(PostHistory(site_id=site.id, product_name="Cũ lỗi", title="x", raw_html="<p>x</p>", status="failed", created_at=old))
    s.add_all([PostHistory(site_id=site.id, product_name=f"P{i}", title="t", raw_html="<p>" + "x" * 1000 + "</p>",
                           status="saved", created_at=now_vn()) for i in range(205)])
    s.commit()
    s.close()

    failed = posts.list_posts(statuses=("failed",))
    assert [r.product_name for r in failed] == ["Cũ lỗi"]      # trước đây: [] vì 200 bài mới nhất toàn 'saved'
    rows = posts.list_posts()
    assert len(rows) == 200 and rows[0].site_name == "shop"


def test_migrate_from_json_keeps_file_when_a_site_fails(mem_db, tmp_path, monkeypatch):
    import json as _json
    from db import crud

    src = tmp_path / "sites.json"
    src.write_text("﻿" + _json.dumps({"ok": {"url": "https://a"}, "bad": {"url": "https://b"}}), encoding="utf-8")
    real = crud.create_site
    monkeypatch.setattr(crud, "create_site", lambda db, name, **kw: None if name == "bad" else real(db, name, **kw))
    s = mem_db()
    assert crud.migrate_from_json(s, src) == 1
    assert src.exists() and not src.with_suffix(".json.bak").exists()   # còn site lỗi -> chưa đổi tên file
    monkeypatch.setattr(crud, "create_site", real)
    assert crud.migrate_from_json(s, src) == 1                          # lần sau nhập nốt site còn thiếu
    assert not src.exists() and src.with_suffix(".json.bak").exists()
    s.close()
