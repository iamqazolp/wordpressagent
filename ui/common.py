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


def extract_id_from_choice(choice_str: str | None) -> int | None:
    """Trích xuất ID từ chuỗi hiển thị '#12 - Tên sản phẩm...'"""
    if not choice_str or not choice_str.startswith("#"):
        return None
    try:
        id_part = choice_str.split(" - ")[0].replace("#", "").strip()
        return int(id_part)
    except Exception:
        return None
