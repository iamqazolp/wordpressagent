from __future__ import annotations
import csv
import io
import pandas as pd
import gradio as gr
import logging
from db.database import SessionLocal
from db import crud
from core.pipeline import generate_articles, publish_articles

logger = logging.getLogger(__name__)

def load_sites() -> list[str]:
    db = SessionLocal()
    try:
        return crud.get_site_names(db)
    except Exception as e:
        logger.error(f"Error loading sites: {e}")
        return []
    finally:
        db.close()

def load_templates() -> list[str]:
    db = SessionLocal()
    try:
        return crud.get_all_templates(db)
    except Exception as e:
        logger.error(f"Error loading templates: {e}")
        return []
    finally:
        db.close()

def parse_csv_file(file) -> tuple:
    """Parse uploaded CSV file.
    Returns: (preview_dataframe, parsed_products_state, status_msg)
    parsed_products_state is a list of dicts with keys: product_name, ref_urls, notes, regular_price, sale_price
    """
    if not file:
        return pd.DataFrame(), [], "❌ Vui lòng tải lên file CSV."
    
    parsed_products_state = []
    try:
        with open(file.name, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Clean up keys in case of whitespace/BOM issues
                cleaned_row = {k.strip(): v.strip() if v else "" for k, v in row.items() if k}
                
                if "product_name" not in cleaned_row or not cleaned_row["product_name"]:
                    continue # Skip rows without product name
                    
                parsed_products_state.append({
                    "product_name": cleaned_row.get("product_name", ""),
                    "ref_urls": cleaned_row.get("ref_urls", ""),
                    "notes": cleaned_row.get("notes", ""),
                    "regular_price": cleaned_row.get("regular_price", ""),
                    "sale_price": cleaned_row.get("sale_price", "")
                })
        
        if not parsed_products_state:
            return pd.DataFrame(), [], "❌ File CSV không có dữ liệu hợp lệ (cần cột product_name)."
            
        df = pd.DataFrame(parsed_products_state)
        return df, parsed_products_state, f"✅ Đã tải {len(parsed_products_state)} sản phẩm."
    except Exception as e:
        logger.error(f"CSV Parse error: {e}")
        return pd.DataFrame(), [], f"❌ Lỗi đọc file: {str(e)}"

def run_bulk_generate(parsed_products, selected_sites, template_choice, randomize_enabled, progress=gr.Progress()) -> tuple:
    """Generate articles for all products in the list.
    Process sequentially (one product at a time).
    Returns: (results_state, results_dataframe, status_markdown)
    results_state is a list of dicts: {product_name, articles: {site: {title, raw_html}}, status, error}
    """
    if not parsed_products:
        return [], pd.DataFrame(), "❌ Không có sản phẩm nào để xử lý."
    if not selected_sites:
        return [], pd.DataFrame(), "❌ Vui lòng chọn ít nhất 1 website."
    if not template_choice:
        return [], pd.DataFrame(), "❌ Vui lòng chọn template."
        
    total = len(parsed_products)
    results_state = []
    rows = []
    
    for i, prod in enumerate(parsed_products):
        p_name = prod.get("product_name", f"Product {i}")
        progress(i/total, desc=f"Đang xử lý {i+1}/{total}: {p_name}")
        
        ref_urls_raw = prod.get("ref_urls", "")
        ref_urls = [url.strip() for url in ref_urls_raw.split(";") if url.strip()]
        
        try:
            topic = f"{p_name}. {prod.get('notes', '')}".strip()
            # Generate articles
            generated_results = generate_articles(topic=topic, ref_urls=ref_urls, template=template_choice, randomize=randomize_enabled)
            
            results_state.append({
                "product_name": p_name,
                "articles": generated_results,
                "status": "success",
                "error": ""
            })
            rows.append([i+1, p_name, "✅ Tạo xong", "-", "-", ""])
            
        except Exception as e:
            logger.error(f"Lỗi tạo bài cho {p_name}: {e}")
            results_state.append({
                "product_name": p_name,
                "articles": {},
                "status": "error",
                "error": str(e)
            })
            rows.append([i+1, p_name, "❌ Lỗi", "-", "-", str(e)])
            
    df_res = pd.DataFrame(rows, columns=["STT", "Tên sản phẩm", "Trạng thái", "Website", "Link WP", "Lỗi"])
    return results_state, df_res, f"✅ Đã xử lý xong {total} sản phẩm (chỉ tạo bài)."

def run_bulk_generate_and_publish(parsed_products, selected_sites, template_choice, randomize_enabled, post_type, post_status, progress=gr.Progress()) -> tuple:
    """Generate AND publish articles for all products.
    Returns: (results_dataframe, status_markdown)
    """
    if not parsed_products:
        return pd.DataFrame(), "❌ Không có sản phẩm nào để xử lý."
    if not selected_sites:
        return pd.DataFrame(), "❌ Vui lòng chọn ít nhất 1 website."
    if not template_choice:
        return pd.DataFrame(), "❌ Vui lòng chọn template."
        
    total = len(parsed_products)
    rows = []
    
    db = SessionLocal()
    try:
        configs = crud.get_all_site_configs(db)
        site_configs = {c.site_name: {"url": c.wp_url, "username": c.wp_username, "password_encrypted": c.wp_password_encrypted} for c in configs if c.site_name in selected_sites}
        
        wp_post_type = "product" if "Sản phẩm" in post_type else "post"
        wp_status = "publish" if "publish" in post_status.lower() else "draft"
        
        stt = 1
        for i, prod in enumerate(parsed_products):
            p_name = prod.get("product_name", f"Product {i}")
            progress(i/total, desc=f"Đang xử lý {i+1}/{total}: {p_name}")
            
            ref_urls_raw = prod.get("ref_urls", "")
            ref_urls = [url.strip() for url in ref_urls_raw.split(";") if url.strip()]
            
            topic = f"{p_name}. {prod.get('notes', '')}".strip()
            
            # 1. Generate
            try:
                generated_results = generate_articles(topic=topic, ref_urls=ref_urls, template=template_choice, randomize=randomize_enabled)
            except Exception as e:
                logger.error(f"Lỗi tạo bài cho {p_name}: {e}")
                rows.append([stt, p_name, "❌ Lỗi Tạo", "-", "-", str(e)])
                stt += 1
                continue
                
            # 2. Publish
            try:
                pub_results = publish_articles(
                    articles=generated_results,
                    site_configs=site_configs,
                    post_type=wp_post_type,
                    status=wp_status
                )
                
                for site_name, res in pub_results.items():
                    if res.get("success"):
                        post_url = res.get("url", "")
                        rows.append([stt, p_name, "✅ Đăng thành công", site_name, post_url, ""])
                        
                        crud.create_post_history(
                            db=db,
                            site_name=site_name,
                            post_url=post_url,
                            post_title=generated_results.get(site_name, {}).get("title", p_name),
                            status="Success"
                        )
                    else:
                        err = res.get("error", "Unknown error")
                        rows.append([stt, p_name, "❌ Lỗi Đăng", site_name, "-", err])
                        
                        crud.create_post_history(
                            db=db,
                            site_name=site_name,
                            post_url="",
                            post_title=generated_results.get(site_name, {}).get("title", p_name),
                            status=f"Failed: {err}"
                        )
                    stt += 1
                    
            except Exception as e:
                logger.error(f"Lỗi đăng bài cho {p_name}: {e}")
                rows.append([stt, p_name, "❌ Lỗi Đăng", "-", "-", str(e)])
                stt += 1
                
    finally:
        db.close()
        
    df_res = pd.DataFrame(rows, columns=["STT", "Tên sản phẩm", "Trạng thái", "Website", "Link WP", "Lỗi"])
    return df_res, f"✅ Đã xử lý xong {total} sản phẩm (Tạo & Đăng)."

def build_tab_bulk() -> dict:
    """Build the bulk import tab. Returns dict of components."""
    components = {}
    
    with gr.Tab("Tạo Hàng Loạt (CSV)"):
        gr.Markdown("### Nhập dữ liệu hàng loạt từ CSV")
        
        with gr.Row():
            with gr.Column(scale=1):
                file_input = gr.File(label="Tải lên file CSV", file_types=[".csv"])
                gr.Markdown("""
**Định dạng CSV mẫu:**
```csv
product_name,ref_urls,notes,regular_price,sale_price
Pa Lăng Cáp Điện 1T,https://ex.com,Lõi đồng,5500000,4900000
```
*(Các cột bắt buộc: `product_name`)*
                """)
                parse_btn = gr.Button("Đọc file CSV", variant="secondary")
            
            with gr.Column(scale=2):
                preview_df = gr.Dataframe(label="Dữ liệu xem trước", interactive=False)
                parsed_state = gr.State([])
                parse_status = gr.Markdown("")
        
        gr.Markdown("### Cấu hình đăng bài")
        with gr.Row():
            with gr.Column():
                sites_selector = gr.CheckboxGroup(label="Chọn Website", choices=load_sites())
                components['sites_selector'] = sites_selector
                template_selector = gr.Dropdown(label="Mẫu Template", choices=load_templates())
                randomize_chk = gr.Checkbox(label="Trộn nội dung (Randomize)", value=True)
            
            with gr.Column():
                post_type_radio = gr.Radio(label="Loại bài đăng", choices=["Sản phẩm WooCommerce", "Bài viết Blog"], value="Sản phẩm WooCommerce")
                post_status_radio = gr.Radio(label="Trạng thái", choices=["draft", "publish"], value="draft")
        
        gr.Markdown("### Hành động")
        with gr.Row():
            gen_btn = gr.Button("Tạo bài hàng loạt", variant="primary")
            gen_pub_btn = gr.Button("Tạo & Đăng bài hàng loạt", variant="primary")
            
        status_area = gr.Markdown("Sẵn sàng.")
        
        results_df = gr.Dataframe(label="Kết quả chi tiết", headers=["STT", "Tên sản phẩm", "Trạng thái", "Website", "Link WP", "Lỗi"], interactive=False)
        results_state = gr.State([])
        
        # Events
        parse_btn.click(
            fn=parse_csv_file,
            inputs=[file_input],
            outputs=[preview_df, parsed_state, parse_status]
        )
        
        gen_btn.click(
            fn=run_bulk_generate,
            inputs=[parsed_state, sites_selector, template_selector, randomize_chk],
            outputs=[results_state, results_df, status_area]
        )
        
        gen_pub_btn.click(
            fn=run_bulk_generate_and_publish,
            inputs=[parsed_state, sites_selector, template_selector, randomize_chk, post_type_radio, post_status_radio],
            outputs=[results_df, status_area]
        )
        
    return components
