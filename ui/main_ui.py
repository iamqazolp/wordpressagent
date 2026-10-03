from __future__ import annotations

import logging
import gradio as gr

from ui.tab_create import (
    build_tab_create, run_pipeline_ui, publish_to_sites_ui, schedule_post_ui, save_draft_articles_ui,
    on_change_preview_site, on_edit_title, on_edit_short_desc, on_toggle_edit_mode, on_save_html_edit
)
from ui.tab_bulk import build_tab_bulk
from ui.tab_scheduler import build_tab_scheduler
from ui.tab_templates import (
    build_tab_templates, handle_save_template, handle_delete_template
)
from ui.tab_sites import (
    build_tab_sites, handle_save_site, handle_delete_site, handle_test_connection_ui, on_select_site_for_edit, handle_clear_watermark
)
from ui.tab_history import (
    build_tab_history, fetch_history_data, get_history_post_choices, on_select_history_post
)

logger = logging.getLogger(__name__)

force_light_js = """                                                                                                                                           
     () => {
         document.body.classList.remove('dark');
     }
""" 
def create_app() -> gr.Blocks:
    """Build and return the complete Gradio Blocks app."""
    with gr.Blocks(
        title="WordPress Agent - Đa Website & Tự Động Hóa",
        theme=gr.themes.Soft(),
        js=force_light_js
    ) as demo:
        # State lưu trữ danh sách bài viết theo từng site: {site_name: {title, raw_html, preview_html}}
        articles_state = gr.State({})
        current_preview_site_state = gr.State("")

        gr.HTML("""
        <div style="text-align:center;padding:15px 0 10px;">
            <h1 style="font-size:2em;margin:0;color:#1381f0;">🌟 WordPress Agent</h1>
            <p style="color:#666;margin:5px 0 0;">Quản lý đa website • Tự động viết & đăng sản phẩm • Chống trùng lặp SEO • Lên lịch tự động</p>
        </div>
        """)

        with gr.Tabs():
            # Tab 1: Tạo & Đăng Bài đơn lẻ
            with gr.TabItem("✍️ Tạo & Đăng Bài"):
                create_comps = build_tab_create()

            # Tab 2: Tạo & Đăng Hàng Loạt (CSV / Excel)
            with gr.TabItem("📦 Tạo Hàng Loạt"):
                bulk_comps = build_tab_bulk()

            # Tab 3: Lịch Đăng Bài (Scheduler)
            with gr.TabItem("📅 Lịch Đăng Bài"):
                scheduler_comps = build_tab_scheduler()

            # Tab 4: Kho bài viết & Lịch sử
            with gr.TabItem("📚 Kho Bài Viết & Lịch Sử") as tab_history_item:
                history_comps = build_tab_history()

            # Tab 5: Quản lý Template
            with gr.TabItem("📝 Quản Lý Template"):
                templates_comps = build_tab_templates()

            # Tab 6: Quản Lý Website
            with gr.TabItem("⚙️ Quản Lý Website"):
                sites_comps = build_tab_sites()

        # =====================================================================
        # EVENT WIRING (Tab 1: Tạo & Đăng Bài)
        # =====================================================================
        create_comps['create_btn'].click(
            fn=run_pipeline_ui,
            inputs=[
                create_comps['product_input'],
                create_comps['image_input'],
                create_comps['extra_urls_input'],
                create_comps['user_notes_input'],
                create_comps['sites_selector'],
                create_comps['randomize_checkbox'],
                create_comps['template_selector'],
            ],
            outputs=[
                create_comps['preview_site_selector'],
                create_comps['title_output'],
                create_comps['short_desc_editor'],
                create_comps['preview_output'],
                articles_state,
                current_preview_site_state,
                create_comps['status_box'],
            ],
            show_progress=True,
        )

        create_comps['preview_site_selector'].change(
            fn=on_change_preview_site,
            inputs=[
                create_comps['preview_site_selector'],
                articles_state,
                create_comps['edit_mode_state']
            ],
            outputs=[
                create_comps['title_output'],
                create_comps['short_desc_editor'],
                create_comps['preview_output'],
                create_comps['html_editor'],
                current_preview_site_state,
            ],
        )

        create_comps['title_output'].change(
            fn=on_edit_title,
            inputs=[create_comps['title_output'], current_preview_site_state, articles_state],
            outputs=[articles_state],
        )

        create_comps['short_desc_editor'].change(
            fn=on_edit_short_desc,
            inputs=[create_comps['short_desc_editor'], current_preview_site_state, articles_state],
            outputs=[articles_state],
        )

        create_comps['toggle_edit_btn'].click(
            fn=on_toggle_edit_mode,
            inputs=[create_comps['edit_mode_state'], current_preview_site_state, articles_state],
            outputs=[
                create_comps['preview_output'],
                create_comps['html_editor'],
                create_comps['save_html_btn'],
                create_comps['edit_mode_state'],
            ],
        )

        create_comps['save_html_btn'].click(
            fn=on_save_html_edit,
            inputs=[
                create_comps['html_editor'],
                current_preview_site_state,
                articles_state,
                create_comps['image_input']
            ],
            outputs=[articles_state],
        ).then(
            fn=on_change_preview_site,
            inputs=[
                current_preview_site_state,
                articles_state,
                create_comps['edit_mode_state']
            ],
            outputs=[
                create_comps['title_output'],
                create_comps['short_desc_editor'],
                create_comps['preview_output'],
                create_comps['html_editor'],
                current_preview_site_state,
            ],
        )

        history_detail_outputs = [
            history_comps['title_input'],
            history_comps['short_desc_input'],
            history_comps['reg_price_input'],
            history_comps['sale_price_input'],
            history_comps['post_type_selector'],
            history_comps['post_status_selector'],
            history_comps['preview_output'],
            history_comps['html_editor'],
            history_comps['post_info_box'],
            history_comps['images_gallery'],
            history_comps['images_upload'],
        ]

        def _on_publish_and_sync(art_state, imgs, p_status, p_type, r_price, s_price, opt_img, rem_bg, s_filter, st_filter):
            msg = publish_to_sites_ui(art_state, imgs, p_status, p_type, r_price, s_price, optimize_images=opt_img, remove_bg=rem_bg)
            df = fetch_history_data(s_filter, st_filter)
            choices = get_history_post_choices(s_filter, st_filter)
            new_val = choices[0] if choices else None
            return msg, df, gr.update(choices=choices, value=new_val)

        create_comps['publish_btn'].click(
            fn=_on_publish_and_sync,
            inputs=[
                articles_state,
                create_comps['image_input'],
                create_comps['post_status_selector'],
                create_comps['post_type_selector'],
                create_comps['regular_price_input'],
                create_comps['sale_price_input'],
                create_comps['img_optimize_chk'],
                create_comps['img_remove_bg_chk'],
                history_comps['site_filter'],
                history_comps['status_filter'],
            ],
            outputs=[
                create_comps['publish_result'],
                history_comps['history_table'],
                history_comps['post_selector'],
            ],
            show_progress=True,
        ).then(
            fn=on_select_history_post,
            inputs=[history_comps['post_selector']],
            outputs=history_detail_outputs,
        )

        def _on_save_draft_and_sync(art_state, imgs, p_type, r_price, s_price, opt_img, rem_bg, s_filter, st_filter):
            msg = save_draft_articles_ui(art_state, imgs, p_type, r_price, s_price, optimize_images=opt_img, remove_bg=rem_bg)
            df = fetch_history_data(s_filter, st_filter)
            choices = get_history_post_choices(s_filter, st_filter)
            new_val = choices[0] if choices else None
            return msg, df, gr.update(choices=choices, value=new_val)

        create_comps['save_draft_btn'].click(
            fn=_on_save_draft_and_sync,
            inputs=[
                articles_state,
                create_comps['image_input'],
                create_comps['post_type_selector'],
                create_comps['regular_price_input'],
                create_comps['sale_price_input'],
                create_comps['img_optimize_chk'],
                create_comps['img_remove_bg_chk'],
                history_comps['site_filter'],
                history_comps['status_filter'],
            ],
            outputs=[
                create_comps['publish_result'],
                history_comps['history_table'],
                history_comps['post_selector'],
            ],
        ).then(
            fn=on_select_history_post,
            inputs=[history_comps['post_selector']],
            outputs=history_detail_outputs,
        )

        create_comps['schedule_btn'].click(
            fn=schedule_post_ui,
            inputs=[
                articles_state,
                create_comps['image_input'],
                create_comps['post_status_selector'],
                create_comps['post_type_selector'],
                create_comps['regular_price_input'],
                create_comps['sale_price_input'],
                create_comps['schedule_datetime_picker'],
            ],
            outputs=[create_comps['schedule_result']],
        )

        # =====================================================================
        # EVENT WIRING (Tab 4: Kho Bài Viết & Lịch Sử)
        # Tự động đồng bộ và nạp dữ liệu mới nhất khi người dùng chuyển sang Tab 4
        # =====================================================================
        def _on_switch_to_history_tab(site_f, status_f, current_choice):
            df = fetch_history_data(site_f, status_f)
            choices = get_history_post_choices(site_f, status_f)
            val = current_choice if (current_choice and current_choice in choices) else (choices[0] if choices else None)
            return df, gr.update(choices=choices, value=val)

        tab_history_item.select(
            fn=_on_switch_to_history_tab,
            inputs=[history_comps['site_filter'], history_comps['status_filter'], history_comps['post_selector']],
            outputs=[history_comps['history_table'], history_comps['post_selector']],
        ).then(
            fn=on_select_history_post,
            inputs=[history_comps['post_selector']],
            outputs=history_detail_outputs,
        )

        # =====================================================================
        # EVENT WIRING (Tab 5: Quản lý Template)
        # =====================================================================
        def _on_save_template_sync(name, category, content, is_default, current_sel):
            msg, updated_dd, val, create_choices = handle_save_template(name, category, content, is_default, current_sel)
            # Đồng bộ dropdown cho cả tab tạo bài và tab tạo hàng loạt
            return msg, updated_dd, val, create_choices, create_choices

        def _on_delete_template_sync(current_sel):
            msg, updated_dd, val, create_choices = handle_delete_template(current_sel)
            return msg, updated_dd, val, create_choices, create_choices

        templates_comps['btn_save'].click(
            fn=_on_save_template_sync,
            inputs=[
                templates_comps['input_name'],
                templates_comps['input_category'],
                templates_comps['input_content'],
                templates_comps['input_is_default'],
                templates_comps['template_selector'],
            ],
            outputs=[
                templates_comps['status_output'],
                templates_comps['template_selector'],
                templates_comps['input_name'],
                create_comps['template_selector'],
                bulk_comps['template_selector'],
            ],
        )

        templates_comps['btn_delete'].click(
            fn=_on_delete_template_sync,
            inputs=[templates_comps['template_selector']],
            outputs=[
                templates_comps['status_output'],
                templates_comps['template_selector'],
                templates_comps['input_name'],
                create_comps['template_selector'],
                bulk_comps['template_selector'],
            ],
        )

        # =====================================================================
        # EVENT WIRING (Tab 6: Quản Lý Website)
        # =====================================================================
        sites_comps['site_select_edit'].change(
            fn=on_select_site_for_edit,
            inputs=[sites_comps['site_select_edit']],
            outputs=[
                sites_comps['input_site_name'],
                sites_comps['input_site_url'],
                sites_comps['input_client_key'],
                sites_comps['input_client_secret'],
                sites_comps['input_wp_user'],
                sites_comps['input_wp_pass'],
                sites_comps['input_watermark_pos'],
                sites_comps['input_watermark_opacity'],
                sites_comps['current_watermark_preview'],
                sites_comps['input_watermark_file'],
                sites_comps['manage_status'],
            ],
        )

        def _sync_sites_on_save(name, url, key, secret, user, pwd, wm_file, wm_pos, wm_opacity, current_sel):
            status_msg, table_md, edit_dd, create_cb, wm_preview, wm_input = handle_save_site(
                name, url, key, secret, user, pwd, wm_file, wm_pos, wm_opacity, current_sel
            )
            # gr.update() trả về dict, không phải component → dùng dict access
            cb_choices = create_cb.get("choices", []) if isinstance(create_cb, dict) else []
            cb_value = create_cb.get("value", []) if isinstance(create_cb, dict) else []
            bulk_cb = gr.update(choices=cb_choices, value=cb_value)
            return status_msg, table_md, edit_dd, create_cb, bulk_cb, wm_preview, wm_input

        def _sync_sites_on_delete(current_sel):
            status_msg, table_md, edit_dd, create_cb, wm_preview = handle_delete_site(current_sel)
            cb_choices = create_cb.get("choices", []) if isinstance(create_cb, dict) else []
            cb_value = create_cb.get("value", []) if isinstance(create_cb, dict) else []
            bulk_cb = gr.update(choices=cb_choices, value=cb_value)
            return status_msg, table_md, edit_dd, create_cb, bulk_cb, wm_preview

        sites_comps['btn_save_site'].click(
            fn=_sync_sites_on_save,
            inputs=[
                sites_comps['input_site_name'],
                sites_comps['input_site_url'],
                sites_comps['input_client_key'],
                sites_comps['input_client_secret'],
                sites_comps['input_wp_user'],
                sites_comps['input_wp_pass'],
                sites_comps['input_watermark_file'],
                sites_comps['input_watermark_pos'],
                sites_comps['input_watermark_opacity'],
                sites_comps['site_select_edit'],
            ],
            outputs=[
                sites_comps['manage_status'],
                sites_comps['sites_table_view'],
                sites_comps['site_select_edit'],
                create_comps['sites_selector'],
                bulk_comps['sites_selector'],
                sites_comps['current_watermark_preview'],
                sites_comps['input_watermark_file'],
            ],
        )

        sites_comps['btn_delete_site'].click(
            fn=_sync_sites_on_delete,
            inputs=[sites_comps['site_select_edit']],
            outputs=[
                sites_comps['manage_status'],
                sites_comps['sites_table_view'],
                sites_comps['site_select_edit'],
                create_comps['sites_selector'],
                bulk_comps['sites_selector'],
                sites_comps['current_watermark_preview'],
            ],
        )

        sites_comps['btn_clear_watermark'].click(
            fn=handle_clear_watermark,
            inputs=[sites_comps['site_select_edit']],
            outputs=[
                sites_comps['manage_status'],
                sites_comps['current_watermark_preview'],
                sites_comps['sites_table_view'],
            ],
        )

        sites_comps['btn_test_site'].click(
            fn=handle_test_connection_ui,
            inputs=[
                sites_comps['input_site_url'],
                sites_comps['input_client_key'],
                sites_comps['input_client_secret'],
                sites_comps['input_wp_user'],
                sites_comps['input_wp_pass']
            ],
            outputs=[sites_comps['manage_status']],
        )

    return demo
