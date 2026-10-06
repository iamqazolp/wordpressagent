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
