

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

