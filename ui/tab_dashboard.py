"""
ui/tab_dashboard.py — tab Dashboard: số liệu tổng quan, biểu đồ 30 ngày, bài gần đây, tình trạng website.

Chỉ dựng giao diện và đổi dữ liệu thuần của services/dashboard.py thành DataFrame/Markdown.
Kiểm tra kết nối website KHÔNG chạy khi mở trang (chỉ hiện kết quả cache nếu có); bấm nút để kiểm tra.
"""
from __future__ import annotations

import logging

import gradio as gr
import pandas as pd

from services import dashboard as dash_service

logger = logging.getLogger(__name__)

DAYS = 30
_BUCKET_LABELS = {"published": "✅ Đã đăng", "saved": "💾 Đã lưu nháp", "failed": "❌ Lỗi"}
_STATUS_LABELS = {
    "saved": "💾 Đã lưu nháp", "published": "✅ Đã đăng", "draft": "📝 Nháp WP", "failed": "❌ Lỗi",
    "trashed": "🗑️ Thùng rác WP", "missing": "❓ Không còn trên WP",
}
_DAILY_COLS = ["Ngày", "Loại", "Số bài"]
_SITE_COLS = ["Website", "Tổng", "Đã đăng", "Đã lưu", "Lỗi"]
_RECENT_COLS = ["ID", "Tiêu đề", "Website", "Trạng thái", "Ngày tạo (GMT+7)", "Xem bài", "Sửa trong WP"]
_HEALTH_COLS = ["Website", "WordPress", "WooCommerce", "Ghi chú", "Kiểm tra lúc (GMT+7)"]


def _stats() -> dash_service.DashboardStats | None:
    try:
        return dash_service.get_stats(days=DAYS)
    except Exception:
        logger.exception("Lỗi tải thống kê dashboard")
        return None


def cards_markdown() -> str:
    st = _stats()
    if st is None:
        return "⚠️ Không tải được thống kê."
    t = st.totals
    nxt = f" · sắp chạy: **{st.next_job_time}** (GMT+7)" if st.next_job_time else ""
    return (
        f"| 📚 Tổng bài | ✅ Đã đăng | 💾 Đã lưu nháp | ❌ Lỗi | 🗑️ Thùng rác/mất | ⏳ Lịch đang chờ |\n"
        f"|:-:|:-:|:-:|:-:|:-:|:-:|\n"
        f"| **{t['total']}** | **{t['published']}** | **{t['saved']}** | **{t['failed']}** | **{t['trashed']}** | **{st.pending_jobs}** |\n"
        f"{nxt}"
    )


def daily_dataframe() -> pd.DataFrame:
    st = _stats()
    if st is None:
        return pd.DataFrame(columns=_DAILY_COLS)
    rows = []
    for d in st.daily:
        rows += [
            {"Ngày": d.day, "Loại": _BUCKET_LABELS["published"], "Số bài": d.published},
            {"Ngày": d.day, "Loại": _BUCKET_LABELS["saved"], "Số bài": d.saved},
            {"Ngày": d.day, "Loại": _BUCKET_LABELS["failed"], "Số bài": d.failed},
        ]
    return pd.DataFrame(rows, columns=_DAILY_COLS)


def site_dataframe() -> pd.DataFrame:
    st = _stats()
    if st is None:
        return pd.DataFrame(columns=_SITE_COLS)
    return pd.DataFrame(
        [{"Website": s.site_name, "Tổng": s.total, "Đã đăng": s.published, "Đã lưu": s.saved, "Lỗi": s.failed} for s in st.by_site],
        columns=_SITE_COLS,
    )


def recent_dataframe() -> pd.DataFrame:
    st = _stats()
    if st is None:
        return pd.DataFrame(columns=_RECENT_COLS)
    return pd.DataFrame(
        [{
            "ID": r.id, "Tiêu đề": r.title, "Website": r.site_name, "Trạng thái": _STATUS_LABELS.get(r.status, r.status),
            "Ngày tạo (GMT+7)": r.created_at, "Xem bài": r.url or "-", "Sửa trong WP": r.admin_url or "-",
        } for r in st.recent],
        columns=_RECENT_COLS,
    )


def _health_frame(items: list[dash_service.SiteHealth]) -> pd.DataFrame:
    return pd.DataFrame(
        [{
            "Website": h.site_name,
            "WordPress": "🟢 OK" if h.wp_ok else "🔴 Lỗi",
            "WooCommerce": "🟢 OK" if h.wc_ok else "🔴 Lỗi",
            "Ghi chú": h.message or "-",
            "Kiểm tra lúc (GMT+7)": h.checked_at,
        } for h in items],
        columns=_HEALTH_COLS,
    )


def cached_health_dataframe() -> pd.DataFrame:
    """Hiện kết quả kiểm tra gần nhất (còn hạn cache); không gọi mạng."""
    cached = dash_service.cached_site_health()
    return _health_frame(cached) if cached else pd.DataFrame(columns=_HEALTH_COLS)


def check_health(force: bool = True) -> tuple[pd.DataFrame, str]:
    """Nút 🩺: kiểm tra kết nối song song (có timeout)."""
    try:
        items = dash_service.check_sites(force=force)
    except Exception as e:  # noqa: BLE001
        logger.exception("Lỗi kiểm tra kết nối website")
        return pd.DataFrame(columns=_HEALTH_COLS), f"❌ Lỗi: {e}"
    if not items:
        return pd.DataFrame(columns=_HEALTH_COLS), "ℹ️ Chưa có website nào được cấu hình."
    bad = [h.site_name for h in items if not h.ok]
    return _health_frame(items), (f"⚠️ {len(bad)}/{len(items)} website có vấn đề: {', '.join(bad)}" if bad else f"✅ {len(items)}/{len(items)} website kết nối tốt (kết quả được nhớ 5 phút).")


def refresh_all():
    return cards_markdown(), daily_dataframe(), site_dataframe(), recent_dataframe()


def build_tab_dashboard() -> dict:
    gr.Markdown("### 📊 Tổng quan")
    with gr.Row():
        refresh_btn = gr.Button("🔄 Làm mới số liệu", size="sm", scale=0)
    cards = gr.Markdown(value=cards_markdown)

    daily_plot = gr.BarPlot(
        value=daily_dataframe, x="Ngày", y="Số bài", color="Loại",
        title=f"Số bài tạo mỗi ngày ({DAYS} ngày gần nhất)", height=280, x_label_angle=-45,
        color_map={_BUCKET_LABELS["published"]: "#16a34a", _BUCKET_LABELS["saved"]: "#2563eb", _BUCKET_LABELS["failed"]: "#dc2626"},
    )

    with gr.Row():
        with gr.Column(scale=1):
            gr.Markdown("#### 🌐 Theo website")
            sites_table = gr.Dataframe(value=site_dataframe, interactive=False, wrap=True)
        with gr.Column(scale=2):
            gr.Markdown("#### 🕘 10 bài gần nhất")
            recent_table = gr.Dataframe(value=recent_dataframe, interactive=False, wrap=True)

    gr.Markdown("#### 🩺 Tình trạng website")
    with gr.Row():
        health_btn = gr.Button("🩺 Kiểm tra kết nối các website", size="sm", scale=0)
        health_msg = gr.Markdown("*Chưa kiểm tra. Kiểm tra không chạy tự động khi mở trang.*")
    health_table = gr.Dataframe(value=cached_health_dataframe, interactive=False, wrap=True)

    refresh_btn.click(fn=refresh_all, inputs=[], outputs=[cards, daily_plot, sites_table, recent_table])
    health_btn.click(fn=check_health, inputs=[], outputs=[health_table, health_msg])

    return {
        "refresh_btn": refresh_btn, "cards": cards, "daily_plot": daily_plot, "sites_table": sites_table,
        "recent_table": recent_table, "health_btn": health_btn, "health_table": health_table, "health_msg": health_msg,
    }
