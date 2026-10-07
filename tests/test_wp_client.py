import pytest


def test_upload_images_reports_reason_on_401(tmp_path, monkeypatch):
    from core import wp_client

    img = tmp_path / "Bơm dầu (1).jpg"
    img.write_bytes(b"\xff\xd8\xff\xd9")

    class R:
        status_code = 401
        text = "x"

        def json(self):
            return {"message": "Sorry, you are not allowed"}

    monkeypatch.setattr(wp_client.requests, "post", lambda *a, **k: R())
    errs: list[str] = []
    cfg = {"url": "https://x.test", "wp_user": "u", "wp_app_password": "p", "client_key": "", "client_secret": ""}
    assert wp_client.upload_images([str(img)], cfg, optimize=False, errors=errs) == []
    assert "401" in errs[0] and "Application Password" in errs[0]


def test_check_wp_credentials(monkeypatch):
    from core import wp_client

    assert "chưa điền" in wp_client.check_wp_credentials({"url": "https://x", "wp_user": "", "wp_app_password": ""})

    class R:
        def __init__(self, code):
            self.status_code, self.text = code, ""

        def json(self):
            return {"message": "bad"}

    cfg = {"url": "https://x", "wp_user": "u", "wp_app_password": "p"}
    monkeypatch.setattr(wp_client.requests, "get", lambda *a, **k: R(200))
    assert wp_client.check_wp_credentials(cfg) is None
    monkeypatch.setattr(wp_client.requests, "get", lambda *a, **k: R(401))
    assert "không hợp lệ" in wp_client.check_wp_credentials(cfg)


def test_upload_images_webp_mime(tmp_path, monkeypatch):
    from core import wp_client

    img = tmp_path / "sample.webp"
    img.write_bytes(b"RIFF....WEBP")
    seen_headers = {}

    class R:
        status_code = 201

        def json(self):
            return {"id": 99, "source_url": "https://x/sample.webp"}

    monkeypatch.setattr(wp_client.requests, "post", lambda url, **kw: seen_headers.update(kw.get("headers", {})) or R())
    cfg = {"url": "https://x.test", "wp_user": "u", "wp_app_password": "p", "client_key": "", "client_secret": ""}
    res = wp_client.upload_images([str(img)], cfg, optimize=False)
    assert len(res) == 1
    assert seen_headers.get("Content-Type") == "image/webp"

def test_should_retry_http():
    from core.wp_client import _should_retry_http
    import requests

    assert not _should_retry_http(ValueError("invalid price"))

    class FakeErr(requests.exceptions.HTTPError):
        def __init__(self, code):
            super().__init__()
            self.response = type("Resp", (), {"status_code": code})()

    assert not _should_retry_http(FakeErr(401))
    assert not _should_retry_http(FakeErr(403))
    assert not _should_retry_http(FakeErr(404))
    assert _should_retry_http(FakeErr(500))
    assert _should_retry_http(requests.exceptions.ConnectionError("network err"))


def test_ensure_tags_stops_on_401_or_403(monkeypatch):
    from core import wp_client
    import requests

    calls = []

    class R:
        status_code = 401
        text = "Unauthorized"

        def raise_for_status(self):
            raise requests.exceptions.HTTPError("401", response=self)

    def fake_get(url, **kw):
        calls.append(url)
        return R()

    monkeypatch.setattr(wp_client.requests, "get", fake_get)
    cfg = {"url": "https://x.test", "client_key": "ck", "client_secret": "cs", "wp_user": "u", "wp_app_password": "p"}
    res = wp_client.ensure_tags(cfg, "product", ["tag1", "tag2", "tag3"])
    assert res == []
    assert len(calls) == 1


def test_publish_product_passes_query_param_auth(monkeypatch):
    from core import wp_client

    captured_params = {}

    class FakeResp:
        status_code = 201
        text = '{"id": 1, "permalink": "https://x/p/1"}'

        def json(self):
            return {"id": 1, "permalink": "https://x/p/1"}

        def raise_for_status(self):
            pass

    def fake_post(url, **kwargs):
        captured_params.update(kwargs.get("params", {}))
        return FakeResp()

    monkeypatch.setattr(wp_client.requests, "post", fake_post)
    cfg = {"url": "https://x.test", "client_key": "my_ck", "client_secret": "my_cs"}
    wp_client.publish_product("Product", "<p>x</p>", [], cfg)
    assert captured_params.get("consumer_key") == "my_ck"
    assert captured_params.get("consumer_secret") == "my_cs"


def test_publish_product_future_status_includes_date_created_gmt(monkeypatch):
    from datetime import datetime
    from core import wp_client

    captured_payload = {}

    class FakeResp:
        status_code = 201
        text = '{"id": 10, "permalink": "https://x/p/10"}'

        def json(self):
            return {"id": 10, "permalink": "https://x/p/10"}

        def raise_for_status(self):
            pass

    def fake_post(url, **kwargs):
        captured_payload.update(kwargs.get("json", {}))
        return FakeResp()

    monkeypatch.setattr(wp_client.requests, "post", fake_post)
    cfg = {"url": "https://x.test", "client_key": "k", "client_secret": "s"}
    sched_time = datetime(2026, 12, 14, 14, 30, 0)
    res = wp_client.publish_product(
        title="Future Product",
        html_content="<p>content</p>",
        uploaded_images=[],
        site_config=cfg,
        status="future",
        scheduled_time=sched_time,
    )
    assert res["post_id"] == 10
    assert captured_payload["status"] == "future"
    assert captured_payload["date_created_gmt"] == "2026-12-14T07:30:00"


def test_publish_post_future_status_includes_date_gmt(monkeypatch):
    from datetime import datetime
    from core import wp_client

    captured_payload = {}

    class FakeResp:
        status_code = 201
        text = '{"id": 20, "link": "https://x/b/20"}'

        def json(self):
            return {"id": 20, "link": "https://x/b/20"}

        def raise_for_status(self):
            pass

    def fake_post(url, **kwargs):
        captured_payload.update(kwargs.get("json", {}))
        return FakeResp()

    monkeypatch.setattr(wp_client.requests, "post", fake_post)
    cfg = {"url": "https://x.test", "wp_user": "u", "wp_app_password": "p"}
    sched_time = datetime(2026, 12, 14, 14, 30, 0)
    res = wp_client.publish_post(
        title="Future Post",
        html_content="<p>content</p>",
        uploaded_images=[],
        site_config=cfg,
        status="future",
        scheduled_time=sched_time,
    )
    assert res["post_id"] == 20
    assert captured_payload["status"] == "future"
    assert captured_payload["date_gmt"] == "2026-12-14T07:30:00"


def test_update_item_status(monkeypatch):
    from core import wp_client

    captured = {}

    class FakeResp:
        status_code = 200
        text = '{"id": 15, "status": "draft", "name": "Item 15", "permalink": "https://x/15"}'

        def json(self):
            return {"id": 15, "status": "draft", "name": "Item 15", "permalink": "https://x/15"}

        def raise_for_status(self):
            pass

    def fake_put(url, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs.get("json")
        return FakeResp()

    monkeypatch.setattr(wp_client.requests, "put", fake_put)
    cfg = {"url": "https://x.test", "client_key": "k", "client_secret": "s", "wp_user": "u", "wp_app_password": "p"}
    res = wp_client.update_item_status(cfg, "product", 15, "draft")
    assert res["id"] == 15
    assert res["status"] == "draft"
    assert captured["json"] == {"status": "draft"}
    assert captured["url"] == "https://x.test/wp-json/wc/v3/products/15"


def test_update_item_taxonomy_payload_per_scope(monkeypatch):
    from core import wp_client

    sent = []

    class FakeResp:
        status_code = 200

        def json(self):
            return {"id": 3, "status": "future"}

        def raise_for_status(self):
            pass

    monkeypatch.setattr(wp_client.requests, "put", lambda url, **kw: sent.append((url, kw.get("json"))) or FakeResp())
    cfg = {"url": "https://x.test", "client_key": "k", "client_secret": "s", "wp_user": "u", "wp_app_password": "p"}
    wp_client.update_item_taxonomy(cfg, "product", 3, [1, 2], [9])
    wp_client.update_item_taxonomy(cfg, "post", 3, [1, 2], [9])
    assert sent[0] == ("https://x.test/wp-json/wc/v3/products/3",
                       {"categories": [{"id": 1}, {"id": 2}], "tags": [{"id": 9}]})
    assert sent[1] == ("https://x.test/wp-json/wp/v2/posts/3", {"categories": [1, 2], "tags": [9]})


def test_create_is_not_retried_after_read_timeout(monkeypatch):
    import requests
    from core import wp_client

    calls = []

    def fake_post(url, **kw):
        calls.append(url)
        raise requests.exceptions.ReadTimeout("server slow")

    monkeypatch.setattr(wp_client.requests, "post", fake_post)
    monkeypatch.setattr(wp_client.publish_post.retry, "sleep", lambda s: None)
    cfg = {"url": "https://x.test", "client_key": "k", "client_secret": "s", "wp_user": "u", "wp_app_password": "p"}
    with pytest.raises(requests.exceptions.ReadTimeout):
        wp_client.publish_post("T", "<p>x</p>", [], cfg)
    assert len(calls) == 1                                    # không gửi lại -> không sinh bài trùng

    calls.clear()

    def refused(url, **kw):
        calls.append(url)
        raise requests.exceptions.ConnectionError("refused")

    monkeypatch.setattr(wp_client.requests, "post", refused)
    with pytest.raises(requests.exceptions.ConnectionError):
        wp_client.publish_post("T", "<p>x</p>", [], cfg)
    assert len(calls) == 2                                    # chưa tới máy chủ -> thử lại an toàn
