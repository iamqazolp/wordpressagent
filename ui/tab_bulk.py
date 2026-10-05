from __future__ import annotations

import logging
import re
import pandas as pd
import gradio as gr

from core.timeutil import TZ_LABEL, TZ_NAME, now_vn
from datetime import timedelta
from services import bulk as bulk_service
from services import posts as post_service
from services import templates as template_service
from services.errors import ServiceError
from ui.tab_create import parse_scheduled_datetime

logger = logging.getLogger(__name__)

_RESULT_COLUMNS = ["STT", "Tên sản phẩm", "Trạng thái", "Website", "Link WP", "Chi tiết / Lỗi"]


def load_sites() -> list[str]:
    try:
        return bulk_service.list_site_names()
    except Exception as e:
        logger.error(f"Lỗi tải danh sách website: {e}")
        return []


def load_templates() -> list[str]:
    try:
        return [template_service.DEFAULT_CHOICE] + template_service.list_template_names()
    except Exception as e:
        logger.error(f"Lỗi tải danh sách template: {e}")
        return [template_service.DEFAULT_CHOICE]


def parse_csv_file(file) -> tuple:
    """
    Phân tích file CSV hoặc Excel (.xlsx, .xls) tải lên.
    Trả về: (preview_dataframe, parsed_products_state, status_msg)
    """
    if not file:
        return pd.DataFrame(), [], "❌ Vui lòng tải lên file CSV hoặc Excel."

    file_path = file.name if hasattr(file, "name") else str(file)
    try:
        products, file_type = bulk_service.parse_product_file(file_path)
    except ServiceError as e:
        return pd.DataFrame(), [], f"❌ {e.message}"

    display_df = pd.DataFrame(products).rename(columns={
        "product_name": "Tên sản phẩm",
        "ref_urls": "URL tham khảo",
        "notes": "Ghi chú AI",
        "regular_price": "Giá gốc",
        "sale_price": "Giá KM",
    })
    return display_df, products, f"✅ Đã tải thành công {len(products)} sản phẩm từ file {file_type}!"


def run_bulk_generate(
    parsed_products: list[dict],
    selected_sites: list[str],
    template_choice: str,
    randomize_enabled: bool,
    progress=gr.Progress(),
) -> tuple:
    """Tạo bài viết hàng loạt từ danh sách sản phẩm (chưa đăng)."""
    try:
        results_state = bulk_service.generate_and_save(
            parsed_products, selected_sites, template_choice, randomize_enabled,
            progress=lambda val, desc: progress(val, desc=desc),
        )
    except ServiceError as e:
        return [], pd.DataFrame(), f"❌ {e.message}"

    rows = []
    for item in results_state:
        if item["status"] == "success":
            for s_name, post_id in item.get("saved", ()):
                rows.append([len(rows) + 1, item["product_name"], "💾 Đã lưu nháp trên Web", s_name, "-", f"Kho bài #{post_id}"])
        else:
            rows.append([len(rows) + 1, item["product_name"], "❌ Lỗi tạo bài", "-", "-", item["error"]])

    df_res = pd.DataFrame(rows, columns=_RESULT_COLUMNS)
    ok = sum(1 for i in results_state if i["status"] == "success")
    msg = f"Đã tạo và lưu {ok}/{len(parsed_products)} sản phẩm vào kho. Chọn bài ở bên dưới để đăng hoặc hẹn giờ."
    return results_state, df_res, msg


def run_bulk_generate_and_publish(
    parsed_products: list[dict],
    selected_sites: list[str],
    template_choice: str,
    randomize_enabled: bool,
    post_type: str,
    post_status: str,
    progress=gr.Progress(),
) -> tuple:
    """Tạo và đăng bài viết hàng loạt từ danh sách sản phẩm."""
    try:
        outcome = bulk_service.generate_and_publish(
            parsed_products, selected_sites, template_choice, randomize_enabled, post_type, post_status,
            progress=lambda val, desc: progress(val, desc=desc),
        )
    except ServiceError as e:
        return pd.DataFrame(), f"❌ {e.message}"

    rows = []
    for r in outcome:
        if r.kind == "create_failed":
            rows.append([len(rows) + 1, r.product_name, "❌ Lỗi tạo bài", "-", "-", r.detail])
        elif r.kind == "published":
            rows.append([len(rows) + 1, r.product_name, f"✅ Đăng thành công ({r.wp_status})", r.site_name, r.url, ""])
        else:
            rows.append([len(rows) + 1, r.product_name, "❌ Lỗi đăng", r.site_name, r.url, r.detail])

    df_res = pd.DataFrame(rows, columns=_RESULT_COLUMNS)
    return df_res, f"🎉 Hoàn tất quá trình tạo và đăng cho {len(parsed_products)} sản phẩm!"


def _batch_choices(results_state) -> list[str]:
    return [
        f"#{post_id} · {item['product_name']} · {site}"
        for item in results_state if item.get("status") == "success"
        for site, post_id in item.get("saved", ())
    ]


def generate_and_offer(parsed_products, selected_sites, template_choice, randomize_enabled, progress=gr.Progress()):
    """Tạo bài hàng loạt, rồi nạp danh sách bài vừa tạo vào ô chọn để xử lý từng bài."""
    results_state, df_res, msg = run_bulk_generate(
        parsed_products, selected_sites, template_choice, randomize_enabled, progress=progress,
    )
    choices = _batch_choices(results_state)
    return results_state, df_res, msg, gr.update(choices=choices, value=choices), ""


def _ids_from(picked) -> list[int]:
    return [int(m.group(1)) for c in (picked or []) if (m := re.match(r"#(\d+)", c))]


def process_batch(picked, action, post_status, start, post_gap, site_gap) -> str:
    """Đăng ngay hoặc hẹn giờ các bài đã chọn trong đợt vừa tạo."""
    ids = _ids_from(picked)
    if not ids:
        return "❌ Chưa chọn bài nào."
    if action == "Hẹn giờ":
        when = parse_scheduled_datetime(start)
        if not when:
            return "❌ Chưa chọn giờ bắt đầu."
        items = post_service.schedule_saved_batch(ids, post_status, when, int(post_gap or 0), int(site_gap or 0))
        lines = [f"- {'✅' if i.ok else '❌'} #{i.post_id} {i.product_name} · {i.site_name} · "
                 + (i.when.strftime('%d/%m %H:%M') if i.ok and i.when else i.detail) for i in items]
        done = sum(1 for i in items if i.ok)
        head = f"**Đã hẹn giờ {done}/{len(items)} bài.** Xem ở tab Lịch đăng."
    else:
        gr.Info("Đang đăng, vui lòng chờ…")
        items = post_service.publish_saved_batch(ids, post_status)
        lines = [f"- {'✅' if i.ok else '❌'} #{i.post_id} {i.product_name} · {i.site_name} · {i.detail}" for i in items]
        done = sum(1 for i in items if i.ok)
        head = f"**Đã đăng {done}/{len(items)} bài.**"
    return head + "\n\n" + "\n".join(lines)


def build_tab_bulk() -> dict:
    """Dựng giao diện cho tab Tạo hàng loạt qua CSV."""
    with gr.Row(equal_height=False):
        with gr.Column(scale=1, min_width=360):
            file_input = gr.File(
                label="File CSV / Excel",
                file_types=[".csv", ".xlsx", ".xls"],
                file_count="single",
                height=110,
            )
            gr.Markdown(
                "Cột: `product_name` (bắt buộc), `ref_urls` (cách nhau bằng `;`), `notes`, `regular_price`, `sale_price`.",
            )
            parse_btn = gr.Button("Đọc file", size="sm")
            sites_selector = gr.CheckboxGroup(label="Website", choices=load_sites(), value=load_sites())
            with gr.Row():
                template_selector = gr.Dropdown(
                    label="Mẫu prompt", choices=load_templates(), value="(Mặc định)", scale=2,
                )
                randomize_chk = gr.Checkbox(label="Mỗi site một bản riêng", value=True, scale=1)
            post_type_radio = gr.Radio(
                choices=["Sản phẩm WooCommerce", "Bài viết Blog"], value="Sản phẩm WooCommerce", visible=False,
            )
            gen_btn = gr.Button("Tạo bài", variant="primary")
            status_area = gr.Markdown("")

        with gr.Column(scale=2, min_width=420):
            parse_status = gr.Markdown("Chưa tải file.")
            preview_df = gr.Dataframe(label="Dữ liệu đọc được", interactive=False, wrap=False, max_height=360)
            parsed_state = gr.State([])
            results_df = gr.Dataframe(
                label="Bài đã tạo",
                headers=_RESULT_COLUMNS,
                interactive=False,
                wrap=False,
                max_height=360,
            )
    results_state = gr.State([])

    gr.Markdown("### Xử lý bài đã tạo")
    batch_pick = gr.CheckboxGroup(label="Chọn bài", choices=[], value=[])
    with gr.Row():
        batch_action = gr.Radio(label="Làm gì", choices=["Đăng ngay", "Hẹn giờ"], value="Đăng ngay", scale=1)
        post_status_radio = gr.Radio(label="Khi đăng", choices=["draft", "publish"], value="draft", scale=1)
    with gr.Group(visible=False) as schedule_box:
        with gr.Row():
            batch_start = gr.DateTime(
                label=f"Giờ bắt đầu ({TZ_LABEL})", type="datetime", timezone=TZ_NAME,
                value=now_vn() + timedelta(hours=1), include_time=True, scale=2,
            )
            batch_post_gap = gr.Number(label="Cách nhau giữa các sản phẩm (phút)", value=30, precision=0, scale=1)
            batch_site_gap = gr.Number(label="Cách nhau giữa các website (phút)", value=0, precision=0, scale=1)
    batch_btn = gr.Button("Thực hiện", variant="primary")
    batch_result = gr.Markdown("")

    # WIRING SỰ KIỆN NỘI BỘ TAB
    parse_btn.click(
        fn=parse_csv_file,
        inputs=[file_input],
        outputs=[preview_df, parsed_state, parse_status],
    )

    gen_btn.click(
        fn=generate_and_offer,
        inputs=[parsed_state, sites_selector, template_selector, randomize_chk],
        outputs=[results_state, results_df, status_area, batch_pick, batch_result],
        show_progress=True,
    )

    batch_action.change(
        fn=lambda a: gr.update(visible=(a == "Hẹn giờ")), inputs=[batch_action], outputs=[schedule_box],
    )
    batch_btn.click(fn=lambda: "⏳ Đang xử lý, vui lòng không đóng trang…", outputs=[batch_result], queue=False).then(
        fn=process_batch,
        inputs=[batch_pick, batch_action, post_status_radio, batch_start, batch_post_gap, batch_site_gap],
        outputs=[batch_result],
        show_progress=True,
    )

    return {
        "file_input": file_input,
        "parse_btn": parse_btn,
        "preview_df": preview_df,
        "parsed_state": parsed_state,
        "sites_selector": sites_selector,
        "template_selector": template_selector,
        "randomize_chk": randomize_chk,
        "post_type_radio": post_type_radio,
        "post_status_radio": post_status_radio,
        "gen_btn": gen_btn,
        "batch_pick": batch_pick,
        "batch_btn": batch_btn,
        "results_df": results_df,
        "results_state": results_state,
        "status_area": status_area,
    }
