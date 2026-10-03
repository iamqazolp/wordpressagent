"""
core/seo_scorer.py
Chấm điểm SEO on-page cho bài viết/sản phẩm trước khi đăng.

Hàm thuần (không gọi mạng, không đụng DB) nên dễ test. Điểm chỉ mang tính cảnh báo,
KHÔNG chặn đăng bài.

Tổng trọng số = 100:
  title_length 20 | word_count 20 | spec_table 15 | headings 15 | keyword 15 | images 10 | short_desc 5
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field, asdict

from bs4 import BeautifulSoup

PASS, PARTIAL, FAIL = "pass", "partial", "fail"
_PARTIAL_RATIO = 0.5

_PLACEHOLDER_RE = re.compile(r"\[IMAGE_PLACEHOLDER_\d+\]")


@dataclass
class SeoCheck:
    key: str
    label: str
    weight: int
    status: str          # pass | partial | fail
    detail: str          # kết quả đo được
    hint: str = ""       # gợi ý cải thiện (rỗng nếu đã đạt)

    @property
    def earned(self) -> float:
        if self.status == PASS:
            return float(self.weight)
        if self.status == PARTIAL:
            return self.weight * _PARTIAL_RATIO
        return 0.0


@dataclass
class SeoReport:
    score: int
    level: str                       # good (>=80) | ok (50-79) | poor (<50)
    checks: list[SeoCheck] = field(default_factory=list)
    word_count: int = 0

    def to_dict(self) -> dict:
        return {
            "score": self.score,
            "level": self.level,
            "word_count": self.word_count,
            "checks": [{**asdict(c), "earned": c.earned} for c in self.checks],
        }


# ── Helpers ──────────────────────────────────────────────────

def _norm(text: str) -> str:
    """NFC + casefold + gộp khoảng trắng — để so khớp tiếng Việt ổn định."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text or "")).strip().casefold()


def _is_product(post_type: str) -> bool:
    t = _norm(post_type)
    return "product" in t or "sản phẩm" in t or "woocommerce" in t


def _level(score: int) -> str:
    if score >= 80:
        return "good"
    if score >= 50:
        return "ok"
    return "poor"


def extract_text(html: str) -> str:
    """Text thuần của bài: bỏ tag, comment, script/style và placeholder ảnh."""
    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = soup.get_text(" ")
    text = _PLACEHOLDER_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def count_words(text: str) -> int:
    return len([t for t in text.split() if re.search(r"\w", t)])


# ── Từng check ───────────────────────────────────────────────

def _check_title(title: str, is_product: bool) -> SeoCheck:
    n = len((title or "").strip())
    # Tên sản phẩm WooCommerce thường ngắn hơn tiêu đề blog nên dải "tốt" rộng hơn.
    full, near = ((25, 70), (15, 90)) if is_product else ((50, 60), (40, 70))
    target = f"{full[0]}–{full[1]}"
    if n == 0:
        return SeoCheck("title_length", "Độ dài tiêu đề", 20, FAIL, "Chưa có tiêu đề", "Nhập tiêu đề cho bài viết.")
    if full[0] <= n <= full[1]:
        return SeoCheck("title_length", "Độ dài tiêu đề", 20, PASS, f"{n} ký tự")
    status = PARTIAL if near[0] <= n <= near[1] else FAIL
    if n < full[0]:
        hint = f"Tiêu đề {n} ký tự, nên thêm khoảng {full[0] - n}+ ký tự (mục tiêu {target})."
    else:
        hint = f"Tiêu đề {n} ký tự, nên rút bớt khoảng {n - full[1]} ký tự (mục tiêu {target})."
    return SeoCheck("title_length", "Độ dài tiêu đề", 20, status, f"{n} ký tự", hint)


def _check_word_count(words: int) -> SeoCheck:
    if 400 <= words <= 800:
        return SeoCheck("word_count", "Độ dài bài viết", 20, PASS, f"{words} từ")
    if 250 <= words < 400 or 800 < words <= 1200:
        status = PARTIAL
    else:
        status = FAIL
    hint = (
        f"Bài {words} từ, nên viết thêm khoảng {400 - words}+ từ (mục tiêu 400–800)."
        if words < 400
        else f"Bài {words} từ, nên rút gọn bớt (mục tiêu 400–800)."
    )
    return SeoCheck("word_count", "Độ dài bài viết", 20, status, f"{words} từ", hint)


def _check_table(soup: BeautifulSoup) -> SeoCheck:
    tables = soup.find_all("table")
    if not tables:
        return SeoCheck("spec_table", "Bảng thông số", 15, FAIL, "Không có bảng", "Thêm bảng thông số kỹ thuật (<table>) ít nhất 3 dòng.")
    best_rows = max(len(t.find_all("tr")) for t in tables)
    if best_rows >= 3:
        return SeoCheck("spec_table", "Bảng thông số", 15, PASS, f"{best_rows} dòng")
    return SeoCheck(
        "spec_table", "Bảng thông số", 15, PARTIAL, f"Bảng chỉ có {best_rows} dòng",
        "Bổ sung thêm dòng thông số (nên có từ 3 dòng trở lên, gồm cả dòng tiêu đề).",
    )


def _check_headings(soup: BeautifulSoup) -> SeoCheck:
    heads = [int(h.name[1]) for h in soup.find_all(re.compile(r"^h[1-6]$"))]
    main = [lv for lv in heads if lv in (2, 3)]
    if not heads:
        return SeoCheck("headings", "Cấu trúc heading", 15, FAIL, "Không có heading", "Chia bài thành các mục bằng thẻ <h3> (hoặc <h2>).")

    problems: list[str] = []
    if 1 in heads:
        problems.append("có <h1> trong nội dung (theme WordPress đã dùng <h1> cho tiêu đề)")
    prev = None
    for lv in heads:
        if lv == 1:
            continue
        if (prev is None and lv > 3) or (prev is not None and lv - prev > 1):
            problems.append(f"nhảy cấp heading (h{prev if prev else '?'} → h{lv})")
            break
        prev = lv
    if len(main) < 2:
        problems.append(f"mới có {len(main)} mục <h2>/<h3>, nên có ít nhất 2")

    if not problems:
        return SeoCheck("headings", "Cấu trúc heading", 15, PASS, f"{len(main)} mục h2/h3, phân cấp hợp lý")
    status = PARTIAL if main else FAIL
    return SeoCheck("headings", "Cấu trúc heading", 15, status, f"{len(heads)} heading", "Cần sửa: " + "; ".join(problems) + ".")


def _check_keyword(text: str, title: str, product_name: str, words: int) -> SeoCheck:
    kw = _norm(product_name) or _norm(title)
    if not kw:
        return SeoCheck("keyword", "Từ khoá (tên sản phẩm)", 15, FAIL, "Chưa có từ khoá", "Nhập tên sản phẩm.")
    if words == 0:
        return SeoCheck("keyword", "Từ khoá (tên sản phẩm)", 15, FAIL, "Bài chưa có nội dung", "Tạo nội dung bài viết.")
    # Ngưỡng mật độ thấp (0.2%) vì prompt chủ động yêu cầu AI không lặp nguyên tên sản phẩm.
    occ = _norm(text).count(kw)
    density = occ / words * 100
    detail = f"{occ} lần, mật độ {density:.2f}%"
    if occ == 0:
        return SeoCheck("keyword", "Từ khoá (tên sản phẩm)", 15, FAIL, detail, f"Tên sản phẩm “{product_name.strip()}” chưa xuất hiện trong bài. Nhắc tên ở đoạn mở đầu.")
    if density > 3.5:
        return SeoCheck("keyword", "Từ khoá (tên sản phẩm)", 15, FAIL, detail, "Lặp tên sản phẩm quá nhiều (nhồi từ khoá). Dùng từ thay thế như “model này”, “sản phẩm”.")
    if density > 2.5:
        return SeoCheck("keyword", "Từ khoá (tên sản phẩm)", 15, PARTIAL, detail, "Mật độ hơi cao, nên giảm bớt (mục tiêu 0.2–2.5%).")
    if occ < 2 or density < 0.2:
        return SeoCheck("keyword", "Từ khoá (tên sản phẩm)", 15, PARTIAL, detail, "Nên nhắc tên sản phẩm thêm 1–2 lần (mục tiêu 0.2–2.5%).")
    return SeoCheck("keyword", "Từ khoá (tên sản phẩm)", 15, PASS, detail)


def _check_images(soup: BeautifulSoup, raw_html: str, image_count: int) -> SeoCheck:
    if image_count <= 0:
        return SeoCheck("images", "Hình ảnh", 10, FAIL, "Chưa có ảnh", "Tải lên ít nhất 1 ảnh sản phẩm.")
    imgs = soup.find_all("img")
    placeholders = len(_PLACEHOLDER_RE.findall(raw_html or ""))
    if not imgs and placeholders == 0:
        return SeoCheck("images", "Hình ảnh", 10, PARTIAL, f"{image_count} ảnh, chưa chèn vào bài", "Bài chưa có vị trí chèn ảnh ([IMAGE_PLACEHOLDER_n]); ảnh sẽ không hiển thị trong nội dung.")
    missing_alt = [i for i in imgs if not (i.get("alt") or "").strip()]
    if missing_alt:
        return SeoCheck("images", "Hình ảnh", 10, PARTIAL, f"{len(missing_alt)}/{len(imgs)} ảnh thiếu alt", "Thêm thuộc tính alt mô tả cho mọi ảnh.")
    return SeoCheck("images", "Hình ảnh", 10, PASS, f"{image_count} ảnh, {max(len(imgs), placeholders)} vị trí trong bài")


def _check_short_desc(short_description: str) -> SeoCheck:
    # Mô tả ngắn của sản phẩm thường là bảng thông số HTML nên chỉ kiểm tra có nội dung hay không.
    if extract_text(short_description):
        return SeoCheck("short_desc", "Mô tả ngắn", 5, PASS, "Có mô tả ngắn")
    return SeoCheck("short_desc", "Mô tả ngắn", 5, FAIL, "Chưa có", "Thêm mô tả ngắn (hiển thị cạnh ảnh sản phẩm và trong kết quả tìm kiếm).")


# ── API chính ────────────────────────────────────────────────

def score_article(
    title: str,
    html: str,
    product_name: str = "",
    image_count: int = 0,
    short_description: str = "",
    post_type: str = "product",
) -> SeoReport:
    """
    Chấm điểm 0–100.

    Args:
        title:             Tiêu đề / tên sản phẩm sẽ đăng.
        html:              raw_html của bài (có thể chứa [IMAGE_PLACEHOLDER_n]).
        product_name:      Tên sản phẩm gốc người dùng nhập (từ khoá chính). Rỗng thì dùng title.
        image_count:       Số ảnh người dùng đã tải lên.
        short_description: Mô tả ngắn (HTML hoặc text).
        post_type:         "product"/"Sản phẩm WooCommerce" hoặc bài blog — ảnh hưởng dải độ dài tiêu đề.
    """
    html = html or ""
    soup = BeautifulSoup(html, "html.parser")
    text = extract_text(html)
    words = count_words(text)

    checks = [
        _check_title(title, _is_product(post_type)),
        _check_word_count(words),
        _check_table(soup),
        _check_headings(soup),
        _check_keyword(text, title, product_name, words),
        _check_images(soup, html, image_count),
        _check_short_desc(short_description),
    ]
    score = int(round(sum(c.earned for c in checks)))
    return SeoReport(score=score, level=_level(score), checks=checks, word_count=words)
