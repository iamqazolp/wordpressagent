

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
