from __future__ import annotations

import csv
import logging
import re
import pandas as pd
import gradio as gr

from db.database import SessionLocal
from db import crud
from core.pipeline import generate_articles, publish_articles

logger = logging.getLogger(__name__)


def load_sites() -> list[str]:
    db = SessionLocal()
    try:
        return crud.get_site_names(db)
    except Exception as e:
        logger.error(f"Lỗi tải danh sách website: {e}")
        return []
    finally:
        db.close()


def load_templates() -> list[str]:
    db = SessionLocal()
    try:
        templates = crud.get_all_templates(db)
        return ["(Mặc định)"] + [t.name for t in templates if t.name]
    except Exception as e:
        logger.error(f"Lỗi tải danh sách template: {e}")
        return ["(Mặc định)"]
    finally:
        db.close()


def parse_csv_file(file) -> tuple:
    """
    Phân tích file CSV tải lên.
    Trả về: (preview_dataframe, parsed_products_state, status_msg)
    """
    if not file:
        return pd.DataFrame(), [], "❌ Vui lòng tải lên file CSV."

    parsed_products_state = []
    file_path = file.name if hasattr(file, "name") else str(file)

    try:
        with open(file_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                return pd.DataFrame(), [], "❌ File CSV rỗng hoặc không đúng định dạng."

            # Chuẩn hóa tên các cột (bỏ khoảng trắng và chữ hoa)
            for row in reader:
                cleaned_row = {
                    k.strip().lower(): (v.strip() if v else "")
                    for k, v in row.items()
                    if k
                }

                # Tìm cột tên sản phẩm linh hoạt (product_name, ten_san_pham, name, san_pham)
                p_name = (
                    cleaned_row.get("product_name")
                    or cleaned_row.get("ten_san_pham")
                    or cleaned_row.get("name")
                    or cleaned_row.get("san_pham")
                    or ""
                )

                if not p_name:
                    continue

                ref_urls = (
                    cleaned_row.get("ref_urls")
                    or cleaned_row.get("url")
                    or cleaned_row.get("link")
                    or ""
                )
                notes = (
                    cleaned_row.get("notes")
                    or cleaned_row.get("ghi_chu")
                    or cleaned_row.get("note")
                    or ""
                )
                regular_price = (
                    cleaned_row.get("regular_price")
                    or cleaned_row.get("gia_goc")
                    or cleaned_row.get("price")
                    or ""
                )
                sale_price = (
                    cleaned_row.get("sale_price")
                    or cleaned_row.get("gia_khuyen_mai")
                    or cleaned_row.get("sale")
                    or ""
                )

                parsed_products_state.append({
                    "product_name": p_name,
                    "ref_urls": ref_urls,
                    "notes": notes,
                    "regular_price": regular_price,
                    "sale_price": sale_price,
                })

        if not parsed_products_state:
            return (
                pd.DataFrame(),
                [],
                "❌ Không tìm thấy dòng dữ liệu hợp lệ nào (cần cột 'product_name').",
            )

        df = pd.DataFrame(parsed_products_state)
        # Đổi tên cột hiển thị cho thân thiện
        display_df = df.rename(columns={
            "product_name": "Tên sản phẩm",
            "ref_urls": "URL tham khảo",
            "notes": "Ghi chú AI",
            "regular_price": "Giá gốc",
            "sale_price": "Giá KM",
        })
        return display_df, parsed_products_state, f"✅ Đã tải thành công {len(parsed_products_state)} sản phẩm!"
    except Exception as e:
        logger.exception("Lỗi khi đọc file CSV")
        return pd.DataFrame(), [], f"❌ Lỗi đọc file CSV: {str(e)}"


def run_bulk_generate(
    parsed_products: list[dict],
    selected_sites: list[str],
    template_choice: str,
    randomize_enabled: bool,
    progress=gr.Progress(),
) -> tuple:
    """Tạo bài viết hàng loạt từ danh sách sản phẩm (chưa đăng)."""
    if not parsed_products:
        return [], pd.DataFrame(), "❌ Không có sản phẩm nào để xử lý. Vui lòng tải file CSV trước."
    if not selected_sites:
        return [], pd.DataFrame(), "❌ Vui lòng chọn ít nhất 1 website đăng bài."

    db = SessionLocal()
    try:
        all_configs = crud.get_all_site_configs(db)
        selected_configs = {s: all_configs[s] for s in selected_sites if s in all_configs}

        template_content = None
        if template_choice and template_choice != "(Mặc định)":
            templates = crud.get_all_templates(db)
            for t in templates:
                if t.name == template_choice:
                    template_content = t.content
                    break
    finally:
        db.close()

    total = len(parsed_products)
    results_state = []
    rows = []

    for i, prod in enumerate(parsed_products):
        p_name = prod.get("product_name", f"Sản phẩm {i+1}")
        ref_urls_raw = prod.get("ref_urls", "")
        # Tách URL bằng dấu chấm phẩy hoặc dấu phẩy hoặc xuống dòng
        extra_urls = [u.strip() for u in re.split(r"[;\n,]+", ref_urls_raw) if u.strip().startswith("http")]
        user_notes = prod.get("notes", "")

        progress((i / total), desc=f"🤖 [{i+1}/{total}] Đang viết: {p_name[:30]}...")

        try:
            articles = generate_articles(
                product_name=p_name,
                image_files=None,
                extra_urls=extra_urls,
                user_notes=user_notes,
                selected_sites=selected_configs,
                randomize_enabled=randomize_enabled,
                template_content=template_content,
            )

            # Trích xuất mô tả ngắn tự động
            for s_name, art in articles.items():
                art["product_name"] = p_name
                tbl_match = re.search(r"(<table\b.*?>.*?</table>)", art.get("raw_html", ""), re.DOTALL | re.IGNORECASE)
                art["short_description"] = tbl_match.group(1) if tbl_match else ""

            results_state.append({
                "product_name": p_name,
                "articles": articles,
                "regular_price": prod.get("regular_price", ""),
                "sale_price": prod.get("sale_price", ""),
                "status": "success",
            })
            for s_name in selected_sites:
                rows.append([len(rows) + 1, p_name, "✅ Đã tạo bài", s_name, "-", ""])
        except Exception as e:
            logger.exception(f"Lỗi khi tạo bài hàng loạt cho {p_name}")
            results_state.append({
                "product_name": p_name,
                "articles": {},
                "regular_price": prod.get("regular_price", ""),
                "sale_price": prod.get("sale_price", ""),
                "status": "error",
                "error": str(e),
            })
            rows.append([len(rows) + 1, p_name, "❌ Lỗi tạo bài", "-", "-", str(e)])

    df_res = pd.DataFrame(rows, columns=["STT", "Tên sản phẩm", "Trạng thái", "Website", "Link WP", "Chi tiết / Lỗi"])
    msg = f"✅ Hoàn tất tạo bài cho {total} sản phẩm! Tổng cộng {len(results_state)} kết quả."
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
    if not parsed_products:
        return pd.DataFrame(), "❌ Không có sản phẩm nào để xử lý. Vui lòng tải file CSV trước."
    if not selected_sites:
        return pd.DataFrame(), "❌ Vui lòng chọn ít nhất 1 website đăng bài."

    db = SessionLocal()
    try:
        all_configs = crud.get_all_site_configs(db)
        selected_configs = {s: all_configs[s] for s in selected_sites if s in all_configs}

        template_content = None
        if template_choice and template_choice != "(Mặc định)":
            templates = crud.get_all_templates(db)
            for t in templates:
                if t.name == template_choice:
                    template_content = t.content
                    break

        total = len(parsed_products)
        rows = []

        for i, prod in enumerate(parsed_products):
            p_name = prod.get("product_name", f"Sản phẩm {i+1}")
            ref_urls_raw = prod.get("ref_urls", "")
            extra_urls = [u.strip() for u in re.split(r"[;\n,]+", ref_urls_raw) if u.strip().startswith("http")]
            user_notes = prod.get("notes", "")
            reg_price = prod.get("regular_price", "")
            sale_price = prod.get("sale_price", "")

            progress((i / total), desc=f"🚀 [{i+1}/{total}] Đang xử lý: {p_name[:30]}...")

            # 1. Tạo bài viết
            try:
                articles = generate_articles(
                    product_name=p_name,
                    image_files=None,
                    extra_urls=extra_urls,
                    user_notes=user_notes,
                    selected_sites=selected_configs,
                    randomize_enabled=randomize_enabled,
                    template_content=template_content,
                )

                for s_name, art in articles.items():
                    art["product_name"] = p_name
                    tbl_match = re.search(r"(<table\b.*?>.*?</table>)", art.get("raw_html", ""), re.DOTALL | re.IGNORECASE)
                    art["short_description"] = tbl_match.group(1) if tbl_match else ""
            except Exception as e:
                logger.exception(f"Lỗi tạo bài: {p_name}")
                rows.append([len(rows) + 1, p_name, "❌ Lỗi tạo bài", "-", "-", str(e)])
                continue

            # 2. Đăng bài lên từng site
            try:
                pub_results = publish_articles(
                    articles=articles,
                    image_files=None,
                    site_configs=all_configs,
                    post_type=post_type,
                    post_status=post_status,
                    regular_price=reg_price,
                    sale_price=sale_price,
                )

                for res in pub_results:
                    s_name = res.get("site_name", "")
                    site_obj = crud.get_site_by_name(db, s_name)
                    art = articles.get(s_name, {})
                    is_prod = "product" in post_type.lower() or "sản phẩm" in post_type.lower()

                    if res.get("success"):
                        wp_url = res.get("post_url", "")
                        status_str = f"✅ Đăng thành công ({res.get('status', 'draft')})"
                        rows.append([len(rows) + 1, p_name, status_str, s_name, wp_url, ""])

                        if site_obj:
                            crud.create_post_history(
                                db,
                                site_id=site_obj.id,
                                product_name=p_name,
                                title=art.get("title", p_name),
                                raw_html=art.get("raw_html", ""),
                                post_type="product" if is_prod else "post",
                                status="published",
                                wp_post_id=str(res.get("post_id", "")) if res.get("post_id") else None,
                                wp_post_url=wp_url,
                            )
                    else:
                        err_str = res.get("error", "Lỗi không xác định")
                        rows.append([len(rows) + 1, p_name, "❌ Lỗi đăng", s_name, "-", err_str])

                        if site_obj:
                            crud.create_post_history(
                                db,
                                site_id=site_obj.id,
                                product_name=p_name,
                                title=art.get("title", p_name),
                                raw_html=art.get("raw_html", ""),
                                post_type="product" if is_prod else "post",
                                status="failed",
                                error_message=err_str,
                            )
            except Exception as e:
                logger.exception(f"Lỗi đăng bài cho {p_name}")
                rows.append([len(rows) + 1, p_name, "❌ Lỗi đăng", "-", "-", str(e)])

    finally:
        db.close()

    df_res = pd.DataFrame(rows, columns=["STT", "Tên sản phẩm", "Trạng thái", "Website", "Link WP", "Chi tiết / Lỗi"])
    msg = f"🎉 Hoàn tất quá trình tạo và đăng cho {len(parsed_products)} sản phẩm!"
    return df_res, msg


def build_tab_bulk() -> dict:
    """Dựng giao diện cho tab Tạo & Đăng Hàng Loạt qua CSV."""
    gr.Markdown("""
    <div style="margin-bottom: 15px;">
        <h3>📦 Tạo & Đăng Bài Hàng Loạt Từ File CSV / Excel</h3>
        <p style="color: #666;">Nhập danh sách sản phẩm qua file CSV để tự động tìm kiếm, tạo bài viết độc bản và đăng lên hàng loạt website.</p>
    </div>
    """)

    with gr.Row():
        with gr.Column(scale=1):
            file_input = gr.File(
                label="📁 Tải lên file CSV sản phẩm",
                file_types=[".csv"],
                file_count="single",
            )
            gr.Markdown("""
            **📋 Cấu trúc các cột trong file CSV (hỗ trợ tiếng Việt hoặc tiếng Anh):**
            - `product_name` *(bắt buộc)*: Tên sản phẩm
            - `ref_urls` *(tùy chọn)*: URL tham khảo (phân cách bằng dấu `;`)
            - `notes` *(tùy chọn)*: Ghi chú, yêu cầu riêng cho AI
            - `regular_price` *(tùy chọn)*: Giá gốc (VNĐ)
            - `sale_price` *(tùy chọn)*: Giá khuyến mại (VNĐ)
            """)
            parse_btn = gr.Button("📑 Đọc & Kiểm tra File CSV", variant="secondary")

        with gr.Column(scale=2):
            parse_status = gr.Markdown("Chưa tải file.")
            preview_df = gr.Dataframe(
                label="Bảng dữ liệu sản phẩm đọc được từ CSV",
                interactive=False,
                wrap=True,
            )
            parsed_state = gr.State([])

    gr.Markdown("---")
    gr.Markdown("### ⚙️ Cấu hình đăng bài hàng loạt")

    with gr.Row():
        with gr.Column():
            sites_selector = gr.CheckboxGroup(
                label="🌐 Chọn các website áp dụng",
                choices=load_sites(),
                value=load_sites(),
            )
            template_selector = gr.Dropdown(
                label="📄 Mẫu Prompt (Template)",
                choices=load_templates(),
                value="(Mặc định)",
            )
            randomize_chk = gr.Checkbox(
                label="🎲 Bật Randomize (Nội dung độc bản cho từng website)",
                value=True,
            )

        with gr.Column():
            post_type_radio = gr.Radio(
                label="Loại nội dung đăng",
                choices=["Sản phẩm WooCommerce", "Bài viết Blog"],
                value="Sản phẩm WooCommerce",
            )
            post_status_radio = gr.Radio(
                label="Trạng thái khi đăng",
                choices=["draft", "publish"],
                value="draft",
            )

    with gr.Row():
        gen_btn = gr.Button("🚀 1. Chỉ tạo bài hàng loạt (không đăng)", variant="secondary", size="lg")
        gen_pub_btn = gr.Button("⚡ 2. Tạo & Đăng lên Website ngay", variant="primary", size="lg")

    status_area = gr.Markdown("")
    results_df = gr.Dataframe(
        label="📊 Kết quả thực hiện",
        headers=["STT", "Tên sản phẩm", "Trạng thái", "Website", "Link WP", "Chi tiết / Lỗi"],
        interactive=False,
        wrap=True,
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
