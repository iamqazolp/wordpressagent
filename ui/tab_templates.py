from __future__ import annotations

import gradio as gr
from db.database import SessionLocal
from db import crud

NEW_TEMPLATE_CHOICE = '➕ Tạo mới'
CATEGORIES = ['industrial', 'electronics', 'general', 'fashion', 'custom']

def _get_template_choices(db=None) -> list[str]:
    """Return list of template names for dropdown, with '➕ Tạo mới' at the start."""
    local_db = False
    if db is None:
        db = SessionLocal()
        local_db = True
        
    try:
        templates = crud.get_all_templates(db)
        choices = [NEW_TEMPLATE_CHOICE] + [t.name for t in templates if t.name]
        return choices
    finally:
        if local_db:
            db.close()

def on_select_template(selected_choice: str) -> tuple:
    """When user selects a template from dropdown, populate form fields.
    Returns: (name, category, content, is_default, status_msg)
    If '➕ Tạo mới', clear all fields."""
    if not selected_choice or selected_choice == NEW_TEMPLATE_CHOICE:
        return ("", "general", "", False, "")
        
    db = SessionLocal()
    try:
        templates = crud.get_all_templates(db)
        template = next((t for t in templates if t.name == selected_choice), None)
        
        if template:
            return (
                template.name,
                template.category or "general",
                template.content or "",
                template.is_default or False,
                ""
            )
        else:
            return ("", "general", "", False, "❌ Không tìm thấy template.")
    finally:
        db.close()

def handle_save_template(name: str, category: str, content: str, is_default: bool, current_selection: str) -> tuple:
    """Save (create or update) template.
    If current_selection is '➕ Tạo mới', create new.
    Otherwise, find template by name from current_selection and update.
    Returns: (status_msg, updated_dropdown, updated_dropdown_value, template_choices_for_create_tab)
    """
    if not name or not name.strip():
        return ("❌ Tên template không được để trống.", gr.Dropdown(), gr.Dropdown(), gr.Dropdown())
        
    if not content or not content.strip():
        return ("❌ Nội dung template không được để trống.", gr.Dropdown(), gr.Dropdown(), gr.Dropdown())
        
    db = SessionLocal()
    try:
        templates = crud.get_all_templates(db)
        
        if not current_selection or current_selection == NEW_TEMPLATE_CHOICE:
            # Create new
            existing = next((t for t in templates if t.name == name), None)
            if existing:
                return ("❌ Tên template đã tồn tại. Vui lòng chọn tên khác.", gr.Dropdown(), gr.Dropdown(), gr.Dropdown())
                
            crud.create_template(db, name=name, content=content, category=category, is_default=is_default)
            msg = "✅ Đã tạo template thành công."
        else:
            # Update existing
            template = next((t for t in templates if t.name == current_selection), None)
            if not template:
                return ("❌ Không tìm thấy template để cập nhật.", gr.Dropdown(), gr.Dropdown(), gr.Dropdown())
                
            # If name changed, check for duplicate
            if name != current_selection:
                existing = next((t for t in templates if t.name == name), None)
                if existing:
                    return ("❌ Tên template mới đã tồn tại. Vui lòng chọn tên khác.", gr.Dropdown(), gr.Dropdown(), gr.Dropdown())
            
            crud.update_template(db, template.id, name=name, content=content, category=category, is_default=is_default)
            msg = "✅ Đã cập nhật template thành công."
            
        choices = _get_template_choices(db)
        create_tab_choices = ['(Mặc định)'] + [c for c in choices if c != NEW_TEMPLATE_CHOICE]
        
        return (
            msg,
            gr.Dropdown(choices=choices, value=name),
            name,
            gr.Dropdown(choices=create_tab_choices)
        )
    finally:
        db.close()

def handle_delete_template(current_selection: str) -> tuple:
    """Delete the selected template.
    Returns: (status_msg, updated_dropdown, updated_dropdown_value, template_choices_for_create_tab)"""
    if not current_selection or current_selection == NEW_TEMPLATE_CHOICE:
        return ("❌ Vui lòng chọn một template để xóa.", gr.Dropdown(), gr.Dropdown(), gr.Dropdown())
        
    db = SessionLocal()
    try:
        templates = crud.get_all_templates(db)
        template = next((t for t in templates if t.name == current_selection), None)
        
        if not template:
            return ("❌ Không tìm thấy template để xóa.", gr.Dropdown(), gr.Dropdown(), gr.Dropdown())
            
        success = crud.delete_template(db, template.id)
        if success:
            msg = "✅ Đã xóa template thành công."
            choices = _get_template_choices(db)
            create_tab_choices = ['(Mặc định)'] + [c for c in choices if c != NEW_TEMPLATE_CHOICE]
            
            return (
                msg,
                gr.Dropdown(choices=choices, value=NEW_TEMPLATE_CHOICE),
                NEW_TEMPLATE_CHOICE,
                gr.Dropdown(choices=create_tab_choices)
            )
        else:
            return ("❌ Có lỗi xảy ra khi xóa template.", gr.Dropdown(), gr.Dropdown(), gr.Dropdown())
    finally:
        db.close()

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
