from __future__ import annotations

import gradio as gr

from services import templates as template_service
from services.errors import ServiceError

NEW_TEMPLATE_CHOICE = '➕ Tạo mới'
CATEGORIES = ['industrial', 'electronics', 'general', 'fashion', 'custom']


def _get_template_choices() -> list[str]:
    """Return list of template names for dropdown, with '➕ Tạo mới' at the start."""
    return [NEW_TEMPLATE_CHOICE] + template_service.list_template_names()


def _create_tab_choices(choices: list[str]) -> list[str]:
    return ['(Mặc định)'] + [c for c in choices if c != NEW_TEMPLATE_CHOICE]


def _error(msg: str) -> tuple:
    return (f"❌ {msg}", gr.Dropdown(), gr.Dropdown(), gr.Dropdown())


def on_select_template(selected_choice: str) -> tuple:
    """When user selects a template from dropdown, populate form fields.
    Returns: (name, category, content, is_default, status_msg)
    If '➕ Tạo mới', clear all fields."""
    if not selected_choice or selected_choice == NEW_TEMPLATE_CHOICE:
        return ("", "general", "", False, "")

    template = template_service.get_template(selected_choice)
    if not template:
        return ("", "general", "", False, "❌ Không tìm thấy template.")
    return (template.name, template.category, template.content, template.is_default, "")


def handle_save_template(name: str, category: str, content: str, is_default: bool, current_selection: str) -> tuple:
    """Save (create or update) template.
    If current_selection is '➕ Tạo mới', create new.
    Otherwise, find template by name from current_selection and update.
    Returns: (status_msg, updated_dropdown, updated_dropdown_value, template_choices_for_create_tab)
    """
    current = None if (not current_selection or current_selection == NEW_TEMPLATE_CHOICE) else current_selection
    try:
        _, created = template_service.save_template(name, category, content, is_default, current)
    except ServiceError as e:
        return _error(e.message)

    msg = "✅ Đã tạo template thành công." if created else "✅ Đã cập nhật template thành công."
    choices = _get_template_choices()
    return (
        msg,
        gr.Dropdown(choices=choices, value=name),
        name,
        gr.Dropdown(choices=_create_tab_choices(choices)),
    )


def handle_delete_template(current_selection: str) -> tuple:
    """Delete the selected template.
    Returns: (status_msg, updated_dropdown, updated_dropdown_value, template_choices_for_create_tab)"""
    if not current_selection or current_selection == NEW_TEMPLATE_CHOICE:
        return _error("Vui lòng chọn một template để xóa.")
    try:
        template_service.delete_template(current_selection)
    except ServiceError as e:
        return _error(e.message)

    choices = _get_template_choices()
    return (
        "✅ Đã xóa template thành công.",
        gr.Dropdown(choices=choices, value=NEW_TEMPLATE_CHOICE),
        NEW_TEMPLATE_CHOICE,
        gr.Dropdown(choices=_create_tab_choices(choices)),
    )


def build_tab_templates() -> dict:
    """Build the template management tab. Returns dict of components."""
    with gr.Row():
        with gr.Column(scale=1):
            template_selector = gr.Dropdown(
                label="Chọn Template", 
                choices=_get_template_choices(),
                value=NEW_TEMPLATE_CHOICE,
                interactive=True
            )
            input_name = gr.Textbox(label="Tên Template")
            input_category = gr.Dropdown(
                label="Danh mục", 
                choices=CATEGORIES,
                value="general",
                interactive=True
            )
            input_is_default = gr.Checkbox(label="Là Mặc định (Sẽ ghi đè Mặc định hiện tại)", value=False)
            
            btn_save = gr.Button("Lưu", variant="primary")
            btn_delete = gr.Button("Xóa", variant="stop")
            
            status_output = gr.Textbox(label="Trạng thái", interactive=False)
            
        with gr.Column(scale=2):
            input_content = gr.Code(label="Nội dung Template", language="markdown", lines=25)
            
            gr.Markdown(
                "### 📌 Biến có thể sử dụng trong Template:\n"
                "- `{product_name}` — Tên sản phẩm\n"
                "- `{site_name}` — Tên website\n"
                "- `{reference_articles}` — Nội dung tham khảo từ web\n"
                "- `{image_count}` — Số lượng ảnh sản phẩm\n"
                "- `{user_notes}` — Gợi ý riêng từ người dùng"
            )
            
    template_selector.change(
        fn=on_select_template,
        inputs=[template_selector],
        outputs=[input_name, input_category, input_content, input_is_default, status_output]
    )

    return {
        'template_selector': template_selector,
        'input_name': input_name,
        'input_category': input_category,
        'input_content': input_content,
        'input_is_default': input_is_default,
        'btn_save': btn_save,
        'btn_delete': btn_delete,
        'status_output': status_output
    }
