from __future__ import annotations

import logging
import gradio as gr

from ui.tab_create import (
    build_tab_create, run_pipeline_ui, publish_to_sites_ui,
    on_change_preview_site, on_edit_title, on_toggle_edit_mode, on_save_html_edit
)
from ui.tab_sites import (
    build_tab_sites, handle_save_site, handle_delete_site, handle_test_connection_ui, on_select_site_for_edit
)
from ui.tab_history import (
    build_tab_history, fetch_history_data
)

logger = logging.getLogger(__name__)

def create_app() -> gr.Blocks:
    """Build and return the complete Gradio Blocks app."""
    with gr.Blocks(
        title="WordPress Agent - Đa Website & Tự Động Hóa",
    ) as demo:
        # State lưu trữ danh sách bài viết theo từng site: {site_name: {title, raw_html, preview_html}}
        articles_state = gr.State({})
        current_preview_site_state = gr.State("")

        gr.HTML("""
        <div style="text-align:center;padding:15px 0 10px;">
            <h1 style="font-size:2em;margin:0;color:#1381f0;">🌟 WordPress Agent</h1>
            <p style="color:#666;margin:5px 0 0;">Quản lý đa website • Tự động viết & đăng sản phẩm • Chống trùng lặp SEO</p>
        </div>
        """)

        with gr.Tabs():
            # Tab 1: Tạo & Đăng Bài
            with gr.TabItem("✍️ Tạo & Đăng Bài"):
                create_comps = build_tab_create()

            # Tab 2: Lịch sử đăng bài
            with gr.TabItem("🕒 Lịch Sử Đăng"):
                history_comps = build_tab_history()

            # Tab 3: Quản Lý Website
            with gr.TabItem("⚙️ Quản Lý Website"):
                sites_comps = build_tab_sites()

        # =====================================================================
        # EVENT WIRING (Tạo & Đăng Bài)
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
                create_comps['preview_output'],
                create_comps['html_editor'],
                current_preview_site_state,
            ],
        )

        create_comps['publish_btn'].click(
            fn=publish_to_sites_ui,
            inputs=[
                articles_state,
                create_comps['image_input'],
                create_comps['post_status_selector'],
                create_comps['post_type_selector']
            ],
            outputs=[create_comps['publish_result']],
            show_progress=True,
        )

        # =====================================================================
        # EVENT WIRING (Lịch sử đăng bài)
        # =====================================================================
        history_comps['refresh_btn'].click(
            fn=fetch_history_data,
            inputs=[history_comps['site_filter']],
            outputs=[history_comps['history_table']],
        )
        
        history_comps['site_filter'].change(
            fn=fetch_history_data,
            inputs=[history_comps['site_filter']],
            outputs=[history_comps['history_table']],
        )

        # =====================================================================
        # EVENT WIRING (Quản lý Website)
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
                sites_comps['manage_status'],
            ],
        )

        sites_comps['btn_save_site'].click(
            fn=handle_save_site,
            inputs=[
                sites_comps['input_site_name'],
                sites_comps['input_site_url'],
                sites_comps['input_client_key'],
                sites_comps['input_client_secret'],
                sites_comps['input_wp_user'],
                sites_comps['input_wp_pass'],
                sites_comps['site_select_edit'],
            ],
            outputs=[
                sites_comps['manage_status'],
                sites_comps['sites_table_view'],
                sites_comps['site_select_edit'],
                create_comps['sites_selector'],
            ],
        )

        sites_comps['btn_delete_site'].click(
            fn=handle_delete_site,
            inputs=[sites_comps['site_select_edit']],
            outputs=[
                sites_comps['manage_status'],
                sites_comps['sites_table_view'],
                sites_comps['site_select_edit'],
                create_comps['sites_selector'],
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
