"""
ui/seo_panel.py
Hiển thị điểm SEO (core/seo_scorer.py) dưới dạng thanh điểm + checklist trong tab Tạo & Đăng Bài.
"""
from __future__ import annotations

import html as _html
import logging

from core.seo_scorer import FAIL, PARTIAL, PASS, SeoReport, score_article

logger = logging.getLogger(__name__)

_COLORS = {"good": "#16a34a", "ok": "#d97706", "poor": "#dc2626"}
_EMOJI = {"good": "🟢", "ok": "🟡", "poor": "🔴"}
_LABEL = {"good": "Tốt", "ok": "Khá", "poor": "Cần cải thiện"}
_STATUS_ICON = {PASS: "✅", PARTIAL: "🟡", FAIL: "❌"}

EMPTY_PANEL = (
    '<div style="padding:10px;color:#888;border:1px dashed #ccc;border-radius:8px;">'
    "📊 Điểm SEO sẽ hiển thị sau khi tạo bài viết."
    "</div>"
)


def render_seo_html(report: SeoReport) -> str:
    """Dựng HTML (đã escape) cho thanh điểm và checklist."""
    color = _COLORS[report.level]
    rows = []
    for c in report.checks:
        hint = (
            f'<div style="color:#92400e;font-size:0.9em;margin-top:2px;">💡 {_html.escape(c.hint)}</div>'
            if c.hint
            else ""
        )
        rows.append(
            '<div style="padding:6px 0;border-bottom:1px solid #eee;">'
            f"<b>{_STATUS_ICON[c.status]} {_html.escape(c.label)}</b> "
            f'<span style="color:#666;">— {_html.escape(c.detail)}</span> '
            f'<span style="float:right;color:#999;">{c.earned:g}/{c.weight}</span>'
            f"{hint}</div>"
        )
    return (
        '<div style="border:1px solid #e5e7eb;border-radius:8px;padding:12px;">'
        '<div style="display:flex;align-items:center;gap:12px;">'
        f'<div style="font-size:1.6em;font-weight:700;color:{color};">{report.score}/100</div>'
        f'<div style="flex:1;"><div style="background:#e5e7eb;border-radius:6px;height:12px;">'
        f'<div style="width:{report.score}%;background:{color};height:12px;border-radius:6px;"></div></div>'
        f'<div style="color:{color};font-weight:600;margin-top:4px;">{_EMOJI[report.level]} {_LABEL[report.level]}'
        f' <span style="color:#888;font-weight:400;">· {report.word_count} từ · chỉ mang tính tham khảo, không chặn đăng bài</span></div>'
        "</div></div>"
        f'<div style="margin-top:8px;">{"".join(rows)}</div>'
        "</div>"
    )


def refresh_seo_panel(articles_state, current_site, image_files, post_type) -> str:
    """
    Tính điểm cho bài của website đang xem. Không bao giờ ném lỗi ra UI:
    lỗi chấm điểm chỉ làm panel hiện thông báo, không ảnh hưởng luồng đăng.
    """
    try:
        if not articles_state or current_site not in articles_state:
            return EMPTY_PANEL
        art = articles_state[current_site]

        from ui.common import extract_file_paths

        report = score_article(
            title=art.get("title", ""),
            html=art.get("raw_html", ""),
            product_name=art.get("product_name", ""),
            image_count=len(extract_file_paths(image_files)),
            short_description=art.get("short_description", ""),
            post_type=post_type or "product",
        )
        return render_seo_html(report)
    except Exception as e:  # pragma: no cover - phòng thủ
        logger.exception("Lỗi chấm điểm SEO")
        return f'<div style="color:#b91c1c;">⚠️ Không chấm được điểm SEO: {_html.escape(str(e))}</div>'
