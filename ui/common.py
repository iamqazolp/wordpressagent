"""Tiện ích dùng chung cho các tab Gradio (đọc giá trị component, không chứa nghiệp vụ)."""
from __future__ import annotations


def extract_file_paths(files) -> list[str]:
    """Trích xuất danh sách đường dẫn file an toàn từ Gradio input."""
    if not files:
        return []
    paths = []
    for f in files:
        if isinstance(f, str):
            paths.append(f)
        elif hasattr(f, "name"):
            paths.append(f.name)
        else:
            paths.append(str(f))
    return paths


def extract_gallery_paths(items) -> list[str]:
    """Trích đường dẫn ảnh từ giá trị gr.Gallery (tuple (path, caption), dict hoặc str)."""
    paths: list[str] = []
    for it in items or []:
        if isinstance(it, (tuple, list)) and it:
            it = it[0]
        if isinstance(it, dict):
            it = it.get("path") or (it.get("image") or {}).get("path") or it.get("name")
        elif not isinstance(it, str):
            it = getattr(getattr(it, "image", it), "path", None)
        if it and str(it) not in paths:
            paths.append(str(it))
    return paths


def merge_image_selection(gallery_items, new_files) -> list[str]:
    """Bộ ảnh cuối cùng = ảnh còn lại trong album (sau khi xoá) + ảnh mới tải thêm, giữ thứ tự, bỏ trùng."""
    merged = extract_gallery_paths(gallery_items)
    for p in extract_file_paths(new_files):
        if p not in merged:
            merged.append(p)
    return merged


def extract_id_from_choice(choice_str: str | None) -> int | None:
    """Trích xuất ID từ chuỗi hiển thị '#12 - Tên sản phẩm...'"""
    if not choice_str or not choice_str.startswith("#"):
        return None
    try:
        id_part = choice_str.split(" - ")[0].replace("#", "").strip()
        return int(id_part)
    except Exception:
        return None
