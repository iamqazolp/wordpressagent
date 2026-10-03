from core.seo_scorer import score_article
from ui.seo_panel import EMPTY_PANEL, refresh_seo_panel, render_seo_html


def _state(title="Pa lăng xích điện 1 tấn", html="<h3>A</h3><h3>B</h3><p>x</p>", **extra):
    art = {"title": title, "raw_html": html, "product_name": "Pa lăng xích", "short_description": ""}
    art.update(extra)
    return {"site1": art}


def test_render_contains_score_and_all_checks():
    report = score_article("Tiêu đề", "<p>x</p>")
    out = render_seo_html(report)
    assert f"{report.score}/100" in out
    for c in report.checks:
        assert c.label in out


def test_render_escapes_untrusted_text():
    # tiêu đề/keyword do AI hoặc người dùng nhập -> không được lọt HTML thô vào panel
    report = score_article("<script>alert(1)</script>", "<p>x</p>", product_name="<img src=x onerror=alert(1)>")
    out = render_seo_html(report)
    assert "<script>" not in out
    assert "<img src=x" not in out


def test_render_colors_follow_level():
    assert "#dc2626" in render_seo_html(score_article("", ""))              # poor -> đỏ


def test_refresh_empty_when_no_articles_or_unknown_site():
    assert refresh_seo_panel({}, "", [], "product") == EMPTY_PANEL
    assert refresh_seo_panel(None, "site1", [], "product") == EMPTY_PANEL
    assert refresh_seo_panel(_state(), "other-site", [], "product") == EMPTY_PANEL


def test_refresh_scores_current_site_only():
    state = _state()
    state["site2"] = {"title": "", "raw_html": "", "product_name": "", "short_description": ""}
    a = refresh_seo_panel(state, "site1", [], "product")
    b = refresh_seo_panel(state, "site2", [], "product")
    assert a != b and "/100" in a and "0/100" in b


def test_refresh_counts_uploaded_images():
    html = "<p>x</p>[IMAGE_PLACEHOLDER_1]"
    without = refresh_seo_panel(_state(html=html), "site1", [], "product")
    with_img = refresh_seo_panel(_state(html=html), "site1", ["/tmp/a.jpg"], "product")
    assert "Chưa có ảnh" in without
    assert "Chưa có ảnh" not in with_img


def test_refresh_never_raises(monkeypatch):
    import ui.seo_panel as mod
    monkeypatch.setattr(mod, "score_article", lambda **kw: (_ for _ in ()).throw(RuntimeError("boom")))
    out = refresh_seo_panel(_state(), "site1", [], "product")
    assert "Không chấm được điểm SEO" in out and "boom" in out
