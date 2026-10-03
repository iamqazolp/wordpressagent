"""ui/preview.py — dựng HTML xem trước trong Gradio (đường dẫn ảnh /file=... là đặc thù của Gradio)."""
from __future__ import annotations

import re


def make_preview_html(html_content: str, image_files: list[str] | None) -> str:
    """Thay [IMAGE_PLACEHOLDER_N] bằng ảnh local để preview."""
    if not image_files:
        return re.sub(r'\[IMAGE_PLACEHOLDER_\d+\]', '', html_content)
    
    paths = image_files if isinstance(image_files[0], str) else [f.name for f in image_files]
    
    def replace_placeholder(match):
        n = int(match.group(1)) - 1
        idx = min(n, len(paths) - 1)
        return (
            f'<figure style="text-align:center;margin:20px 0;">'
            f'<img src="/file={paths[idx]}" style="max-width:100%;height:auto;border-radius:4px;" />'
            f'</figure>'
        )
    
    return re.sub(r'\[IMAGE_PLACEHOLDER_(\d+)\]', replace_placeholder, html_content)
