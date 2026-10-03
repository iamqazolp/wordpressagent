import unicodedata

from core.seo_scorer import (
    FAIL,
    PARTIAL,
    PASS,
    count_words,
    extract_text,
    score_article,
)

PRODUCT = "Quạt công nghiệp Hồng Phúc 750W"


def words(n: int, token: str = "chất") -> str:
    return " ".join([token] * n)


def table(rows: int) -> str:
    body = "".join(f"<tr><td>Thông số {i}</td><td>Giá trị {i}</td></tr>" for i in range(rows))
    return f"<table><thead><tr><th>Thông số</th><th>Giá trị</th></tr></thead><tbody>{body}</tbody></table>"


def good_html(filler_words: int = 430) -> str:
    return (
        f"<p>{PRODUCT} là dòng quạt dành cho nhà xưởng. {words(20)}</p>"
        "<h3>Tổng quan</h3>"
        f"<p>{words(filler_words // 2)}</p>"
        f"{table(5)}"
        "[IMAGE_PLACEHOLDER_1]"
        "<h3>Cấu tạo</h3>"
        f"<p>Model {PRODUCT} dùng động cơ đồng. {words(filler_words // 2)}</p>"
        f"<p>Chọn {PRODUCT} cho xưởng lớn.</p>"
    )


def check(report, key):
    return next(c for c in report.checks if c.key == key)


def test_weights_sum_to_100():
    r = score_article("t", "<p>x</p>")
    assert sum(c.weight for c in r.checks) == 100


def test_good_article_scores_high():
    r = score_article(
        PRODUCT, good_html(), product_name=PRODUCT, image_count=1,
        short_description=table(5), post_type="Sản phẩm WooCommerce",
    )
    assert r.score >= 80, r.to_dict()
    assert r.level == "good"
    assert all(c.status == PASS for c in r.checks), [(c.key, c.status, c.detail) for c in r.checks if c.status != PASS]


def test_empty_article_scores_poor():
    r = score_article("", "", product_name="", image_count=0)
    assert r.score == 0
    assert r.level == "poor"
    assert all(c.status == FAIL for c in r.checks)
    assert all(c.hint for c in r.checks)  # mỗi check trượt đều có gợi ý


def test_level_thresholds():
    # 80 -> good, 79 -> ok, 50 -> ok, 49 -> poor (kiểm tra qua _level)
    from core.seo_scorer import _level
    assert [_level(s) for s in (100, 80, 79, 50, 49, 0)] == ["good", "good", "ok", "ok", "poor", "poor"]


def test_title_boundaries_blog():
    def status(n):
        return check(score_article("a" * n, "<p>x</p>", post_type="Bài viết Blog"), "title_length").status
    assert status(39) == FAIL
    assert status(40) == PARTIAL
    assert status(49) == PARTIAL
    assert status(50) == PASS
    assert status(60) == PASS
    assert status(61) == PARTIAL
    assert status(70) == PARTIAL
    assert status(71) == FAIL


def test_title_product_band_is_wider():
    def status(n):
        return check(score_article("a" * n, "<p>x</p>", post_type="product"), "title_length").status
    assert status(25) == PASS and status(70) == PASS
    assert status(15) == PARTIAL and status(90) == PARTIAL
    assert status(14) == FAIL and status(91) == FAIL


def test_title_hint_gives_concrete_numbers():
    c = check(score_article("a" * 38, "<p>x</p>", post_type="blog"), "title_length")
    assert "38" in c.hint and "12" in c.hint


def test_word_count_boundaries():
    def status(n):
        return check(score_article("t", f"<p>{words(n)}</p>"), "word_count").status
    assert status(249) == FAIL
    assert status(250) == PARTIAL
    assert status(399) == PARTIAL
    assert status(400) == PASS
    assert status(800) == PASS
    assert status(801) == PARTIAL
    assert status(1200) == PARTIAL
    assert status(1201) == FAIL


def test_placeholders_comments_and_scripts_not_counted():
    html = f"<p>{words(10)}</p>[IMAGE_PLACEHOLDER_1]<!-- {words(50)} --><script>{words(50)}</script>"
    assert count_words(extract_text(html)) == 10


def test_table_check():
    assert check(score_article("t", "<p>x</p>"), "spec_table").status == FAIL
    assert check(score_article("t", table(1)), "spec_table").status == PARTIAL  # header + 1 = 2 dòng
    assert check(score_article("t", table(2)), "spec_table").status == PASS      # header + 2 = 3 dòng


def test_headings():
    h = lambda html: check(score_article("t", html), "headings").status
    assert h("<p>x</p>") == FAIL
    assert h("<h3>a</h3><p>x</p><h3>b</h3>") == PASS
    assert h("<h2>a</h2><h3>b</h3><h3>c</h3>") == PASS
    assert h("<h3>a</h3>") == PARTIAL                         # chỉ 1 mục
    assert h("<h2>a</h2><h4>b</h4><h3>c</h3>") == PARTIAL     # nhảy h2 -> h4
    assert h("<h4>a</h4><h4>b</h4>") == FAIL                  # không có h2/h3 nào
    assert h("<h1>a</h1><h3>b</h3><h3>c</h3>") == PARTIAL     # h1 trong nội dung


def test_keyword_density_and_stuffing():
    def kw(occurrences, filler):
        html = f"<p>{words(filler)} " + " ".join([PRODUCT] * occurrences) + "</p>"
        return check(score_article(PRODUCT, html, product_name=PRODUCT), "keyword")
    assert kw(0, 500).status == FAIL
    assert kw(1, 500).status == PARTIAL      # chỉ 1 lần
    assert kw(3, 500).status == PASS         # ~0.6%
    stuffed = kw(40, 100)
    assert stuffed.status == FAIL and "nhồi" in stuffed.hint


def test_keyword_matches_vietnamese_regardless_of_unicode_form():
    decomposed = unicodedata.normalize("NFD", PRODUCT)
    html = f"<p>{words(300)} {decomposed} {decomposed} {decomposed}</p>"
    c = check(score_article(PRODUCT, html, product_name=PRODUCT), "keyword")
    assert c.status == PASS, c.detail


def test_keyword_is_case_insensitive_and_falls_back_to_title():
    html = f"<p>{words(300)} {PRODUCT.upper()} {PRODUCT.lower()} {PRODUCT}</p>"
    assert check(score_article(PRODUCT, html, product_name=""), "keyword").status == PASS


def test_images_check():
    img = lambda html, n: check(score_article("t", html, image_count=n), "images").status
    assert img("<p>x</p>", 0) == FAIL
    assert img("<p>x</p>", 2) == PARTIAL                       # có ảnh nhưng bài không chèn
    assert img("<p>x</p>[IMAGE_PLACEHOLDER_1]", 2) == PASS
    assert img('<img src="a.jpg">', 1) == PARTIAL              # thiếu alt
    assert img('<img src="a.jpg" alt="Quạt">', 1) == PASS


def test_short_desc_accepts_html_table():
    assert check(score_article("t", "<p>x</p>", short_description=table(3)), "short_desc").status == PASS
    assert check(score_article("t", "<p>x</p>", short_description="<p> </p>"), "short_desc").status == FAIL
    assert check(score_article("t", "<p>x</p>", short_description=""), "short_desc").status == FAIL


def test_to_dict_is_serializable():
    import json
    d = score_article(PRODUCT, good_html(), product_name=PRODUCT, image_count=1).to_dict()
    json.dumps(d)
    assert {"score", "level", "checks", "word_count"} <= d.keys()
    assert all("earned" in c for c in d["checks"])


def test_none_inputs_do_not_crash():
    r = score_article(None, None, product_name=None, short_description=None)
    assert r.score == 0
