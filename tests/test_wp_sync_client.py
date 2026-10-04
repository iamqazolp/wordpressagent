"""core/wp_client: cập nhật (PUT), đọc danh sách/1 bài, đưa vào thùng rác — toàn bộ bằng HTTP giả, không chạm mạng."""
import inspect

import pytest

from core import wp_client

CFG = {"url": "https://shop.example.com/", "client_key": "ck", "client_secret": "cs", "wp_user": "u", "wp_app_password": "p"}


class Resp:
    def __init__(self, data, status=200, headers=None):
        self._d, self.status_code, self.headers, self.text = data, status, headers or {}, str(data)

    def json(self):
        return self._d

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.exceptions.HTTPError(f"HTTP {self.status_code}")


@pytest.fixture
def calls(monkeypatch):
    log = []

    def make(method, resp):
        def fn(url, **kw):
            log.append((method, url, kw))
            return resp
        return fn

    def install(**resps):
        for m, r in resps.items():
            monkeypatch.setattr(wp_client.requests, m, make(m.upper(), r))
        return log

    return install


def test_publish_product_creates_with_post_and_updates_with_put(calls):
    log = calls(post=Resp({"id": 5, "permalink": "u"}), put=Resp({"id": 9, "permalink": "u9"}))
    r = wp_client.publish_product("T", "<p>x</p>", [], CFG)
    assert log[-1][0] == "POST" and log[-1][1].endswith("/wc/v3/products") and r["post_id"] == 5
    r = wp_client.publish_product("T", "<p>x</p>", [], CFG, existing_wp_id=9)
    assert log[-1][0] == "PUT" and log[-1][1].endswith("/wc/v3/products/9") and r["post_id"] == 9


def test_publish_post_updates_with_put(calls):
    log = calls(put=Resp({"id": 7, "link": "l"}))
    r = wp_client.publish_post("T", "<p>x</p>", [], CFG, existing_wp_id="7")
    assert log[-1][0] == "PUT" and log[-1][1].endswith("/wp/v2/posts/7") and r["post_id"] == 7


def test_list_items_normalizes_product_and_post(calls):
    log = calls(get=Resp([{"id": 1, "name": "Quạt &amp; Máy", "status": "draft", "permalink": "p", "date_modified": "2026-01-01T09:00:00", "date_modified_gmt": "2026-01-01T02:00:00"}],
                         headers={"X-WP-Total": "41"}))
    items, total = wp_client.list_items(CFG, "product", search="quạt")
    assert total == 41 and items[0] == {"id": 1, "title": "Quạt & Máy", "status": "draft", "url": "p",
                                        "modified": "2026-01-01T09:00:00", "modified_gmt": "2026-01-01T02:00:00",
                                        "type": "product"}
    assert log[-1][2]["params"]["search"] == "quạt" and log[-1][2]["params"]["status"] == "any"
    calls(get=Resp([{"id": 2, "title": {"rendered": "Bài"}, "status": "publish", "link": "l", "modified": "m"}]))
    items, total = wp_client.list_items(CFG, "post")
    assert items[0]["title"] == "Bài" and items[0]["type"] == "post" and total == 1


def test_list_items_raises_on_http_error_and_bad_payload(calls):
    calls(get=Resp({}, status=500))
    with pytest.raises(Exception):
        wp_client.list_items(CFG, "product")
    calls(get=Resp({"code": "x"}))
    with pytest.raises(ValueError):
        wp_client.list_items(CFG, "product")


def test_get_item_none_on_404(calls):
    calls(get=Resp({}, status=404))
    assert wp_client.get_item(CFG, "product", 3) is None
    calls(get=Resp({"id": 3, "name": "A", "status": "publish", "permalink": "p"}))
    assert wp_client.get_item(CFG, "product", 3)["status"] == "publish"


def test_trash_item_never_forces(calls):
    log = calls(delete=Resp({"id": 8, "name": "A", "status": "trash"}))
    for scope in ("product", "post"):
        item = wp_client.trash_item(CFG, scope, 8)
        method, url, kw = log[-1]
        assert method == "DELETE" and url.endswith("/8") and kw["params"] == {"force": "false"}
        assert item["status"] == "trash"
    assert "force" not in inspect.signature(wp_client.trash_item).parameters


def test_ascii_filename_vietnamese():
    from core.wp_client import ascii_filename
    out = ascii_filename("Bơm dầu thuỷ lực Cp-180 (1)_optimized.webp")
    assert out == "bom-dau-thuy-luc-cp-180-1-optimized.webp"
    out.encode("latin-1")
    assert ascii_filename("ĐÈN.JPG") == "den.jpg"
    assert ascii_filename("???.png") == "image.png"


def test_upload_header_is_latin1_safe(tmp_path, monkeypatch):
    from core import wp_client
    img = tmp_path / "Bơm dầu.jpg"
    img.write_bytes(b"x")
    seen = {}

    class R:
        status_code = 201
        def json(self):
            return {"id": 1, "source_url": "https://x/a.jpg"}

    def fake_post(url, **kw):
        kw["headers"]["Content-Disposition"].encode("latin-1")
        seen.update(kw["headers"])
        return R()

    monkeypatch.setattr(wp_client.requests, "post", fake_post)
    res = wp_client.upload_images(
        [str(img)], {"url": "https://x", "wp_user": "u", "wp_app_password": "p"}, optimize=False
    )
    assert len(res) == 1
    assert "bom-dau.jpg" in seen["Content-Disposition"]
