"""
services/templates.py — quản lý template prompt viết bài.

Nghiệp vụ tách khỏi ui/tab_templates.py: kiểm tra đầu vào, chống trùng tên, đặt mặc định,
không cho xóa template cuối cùng. Không phụ thuộc giao diện.
"""
from __future__ import annotations

from dataclasses import dataclass

from db import crud
from db.database import session_scope
from services.errors import ServiceError

DEFAULT_CHOICE = "(Mặc định)"  # nhãn "không chọn template" ở các màn hình tạo bài


@dataclass(frozen=True)
class TemplateInfo:
    id: int
    name: str
    category: str
    content: str
    is_default: bool


def _info(t) -> TemplateInfo:
    return TemplateInfo(
        id=t.id,
        name=t.name,
        category=t.category or "general",
        content=t.content or "",
        is_default=bool(t.is_default),
    )


def list_templates() -> list[TemplateInfo]:
    with session_scope() as db:
        return [_info(t) for t in crud.get_all_templates(db) if t.name]


def list_template_names() -> list[str]:
    return [t.name for t in list_templates()]


def get_template(name: str) -> TemplateInfo | None:
    with session_scope() as db:
        t = next((t for t in crud.get_all_templates(db) if t.name == name), None)
        return _info(t) if t else None


def get_template_content(name: str | None) -> str | None:
    """Nội dung template theo tên; None nếu không chọn (hoặc chọn '(Mặc định)') / không tồn tại."""
    if not name or name == DEFAULT_CHOICE:
        return None
    t = get_template(name)
    return t.content if t else None


def save_template(
    name: str,
    category: str,
    content: str,
    is_default: bool,
    current_name: str | None = None,
) -> tuple[TemplateInfo, bool]:
    """
    Tạo mới (current_name rỗng) hoặc cập nhật template đang chọn.
    Trả (template, created). Raise ServiceError khi dữ liệu không hợp lệ.
    """
    if not name or not name.strip():
        raise ServiceError("Tên template không được để trống.")
    if not content or not content.strip():
        raise ServiceError("Nội dung template không được để trống.")

    with session_scope() as db:
        templates = crud.get_all_templates(db)
        if not current_name:
            if any(t.name == name for t in templates):
                raise ServiceError("Tên template đã tồn tại. Vui lòng chọn tên khác.")
            saved = crud.create_template(db, name=name, content=content, category=category, is_default=is_default)
            created = True
        else:
            target = next((t for t in templates if t.name == current_name), None)
            if not target:
                raise ServiceError("Không tìm thấy template để cập nhật.")
            if name != current_name and any(t.name == name for t in templates):
                raise ServiceError("Tên template mới đã tồn tại. Vui lòng chọn tên khác.")
            saved = crud.update_template(
                db, target.id, name=name, content=content, category=category, is_default=is_default
            )
            created = False
        if saved is None:
            raise ServiceError("Không lưu được template.")
        return _info(saved), created


def delete_template(name: str) -> None:
    """Xóa template theo tên. Không xóa được template cuối cùng."""
    if not name:
        raise ServiceError("Vui lòng chọn một template để xóa.")
    with session_scope() as db:
        target = next((t for t in crud.get_all_templates(db) if t.name == name), None)
        if not target:
            raise ServiceError("Không tìm thấy template để xóa.")
        if not crud.delete_template(db, target.id):
            raise ServiceError("Có lỗi xảy ra khi xóa template.")
