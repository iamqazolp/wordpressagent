"""ui/preview.py — dựng HTML xem trước trong Gradio (đường dẫn ảnh /file=... là đặc thù của Gradio)."""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import quote


def make_preview_html(html_content: str, image_files: list[str] | None) -> str:
    """Thay [IMAGE_PLACEHOLDER_N] bằng ảnh local để preview."""
    if not image_files:
        return re.sub(r'\[IMAGE_PLACEHOLDER_\d+\]', '', html_content)
    
    paths = image_files if isinstance(image_files[0], str) else [f.name for f in image_files]
    
    def replace_placeholder(match):
        n = int(match.group(1)) - 1
        idx = min(n, len(paths) - 1)
        # Gradio 6 phục vụ file ở /gradio_api/file=...; Windows: đổi '\\' thành '/' và mã hóa dấu cách/tiếng Việt
        src = "/gradio_api/file=" + quote(Path(paths[idx]).as_posix(), safe="/:")
        return (
            f'<figure style="text-align:center;margin:20px 0;">'
            f'<img src="{src}" style="max-width:100%;height:auto;border-radius:4px;" />'
            f'</figure>'
        )
    
    return re.sub(r'\[IMAGE_PLACEHOLDER_(\d+)\]', replace_placeholder, html_content)
