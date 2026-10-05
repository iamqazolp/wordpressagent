from __future__ import annotations

import logging
import pandas as pd
import gradio as gr

from services import bulk as bulk_service
from services import templates as template_service
from services.errors import ServiceError

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
            for s_name in selected_sites:
                rows.append([len(rows) + 1, item["product_name"], "💾 Đã lưu nháp trên Web", s_name, "-", "Đã lưu vào Kho Bài Viết"])
        else:
            rows.append([len(rows) + 1, item["product_name"], "❌ Lỗi tạo bài", "-", "-", item["error"]])

    df_res = pd.DataFrame(rows, columns=_RESULT_COLUMNS)
    msg = (
        f"### 💾 Hoàn tất tạo và lưu nháp bài viết cho {len(parsed_products)} sản phẩm vào hệ thống!\n\n"
        f"- Toàn bộ nội dung đã được lưu an toàn trong cơ sở dữ liệu.\n"
        f"- Bạn có thể qua tab **📚 Kho Bài Viết & Lịch Sử** để kiểm tra từng bài và bấm đăng lên WooCommerce khi sẵn sàng."
    )
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


def build_tab_bulk() -> dict:
    """Dựng giao diện cho tab Tạo & Đăng Hàng Loạt qua CSV."""
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
            post_status_radio = gr.Radio(label="Khi đăng", choices=["draft", "publish"], value="draft")
            with gr.Row():
                gen_btn = gr.Button("Chỉ tạo bài", variant="secondary")
                gen_pub_btn = gr.Button("Tạo và đăng", variant="primary")
            status_area = gr.Markdown("")

        with gr.Column(scale=2, min_width=420):
            parse_status = gr.Markdown("Chưa tải file.")
            preview_df = gr.Dataframe(label="Dữ liệu đọc được", interactive=False, wrap=True, max_height=260)
            parsed_state = gr.State([])
            results_df = gr.Dataframe(
                label="Kết quả",
                headers=["STT", "Tên sản phẩm", "Trạng thái", "Website", "Link WP", "Chi tiết / Lỗi"],
                interactive=False,
                wrap=True,
                max_height=300,
            )
    results_state = gr.State([])

    # WIRING SỰ KIỆN NỘI BỘ TAB
    parse_btn.click(
        fn=parse_csv_file,
        inputs=[file_input],
        outputs=[preview_df, parsed_state, parse_status],
    )

    gen_btn.click(
        fn=run_bulk_generate,
        inputs=[parsed_state, sites_selector, template_selector, randomize_chk],
        outputs=[results_state, results_df, status_area],
        show_progress=True,
    )

    gen_pub_btn.click(
        fn=run_bulk_generate_and_publish,
        inputs=[parsed_state, sites_selector, template_selector, randomize_chk, post_type_radio, post_status_radio],
        outputs=[results_df, status_area],
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
        "gen_pub_btn": gen_pub_btn,
        "results_df": results_df,
        "results_state": results_state,
        "status_area": status_area,
    }
