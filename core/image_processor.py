"""
core/image_processor.py
Module xử lý và tối ưu hóa hình ảnh sản phẩm tự động cho WordPress Agent:
- Chuẩn hóa kích thước (Resize max 1200px)
- Nén ảnh sang chuẩn WebP chất lượng cao (giảm 60-80% dung lượng)
- Đóng dấu Watermark / Logo website (tùy chỉnh vị trí, opacity, scale)
- Tách nền sản phẩm (Xóa phông) bằng rembg (local, opt-in)
"""
from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import Any

from PIL import Image, ImageEnhance, ImageOps

logger = logging.getLogger(__name__)

# Thư mục mặc định lưu ảnh đã xử lý
DEFAULT_PROCESSED_DIR = Path("data") / "processed_images"
DEFAULT_PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

# Vị trí watermark được hỗ trợ
WATERMARK_POSITIONS = {
    "bottom-right": "Góc dưới phải",
    "bottom-left": "Góc dưới trái",
    "top-right": "Góc trên phải",
    "top-left": "Góc trên trái",
    "center": "Chính giữa",
}

# Kiểm tra rembg đã cài đặt chưa
_REMBG_AVAILABLE: bool | None = None


def is_rembg_available() -> bool:
    """Kiểm tra môi trường hiện tại có hỗ trợ tách nền bằng rembg hay không."""
    global _REMBG_AVAILABLE
    if _REMBG_AVAILABLE is None:
        try:
            import rembg  # noqa: F401
            _REMBG_AVAILABLE = True
            logger.info("rembg đã sẵn sàng cho tính năng tách nền.")
        except ImportError:
            _REMBG_AVAILABLE = False
            logger.info("rembg chưa được cài đặt trong môi trường. Tính năng tách nền sẽ ở trạng thái chờ.")
    return _REMBG_AVAILABLE


def optimize_and_resize(
    img: Image.Image,
    max_width: int = 1200,
    max_height: int = 1200,
) -> Image.Image:
    """
    Chuẩn hóa kích thước hình ảnh:
    - Xoay ảnh đúng chiều theo metadata EXIF (tránh bị lộn ngược khi chụp từ điện thoại)
    - Resize nếu kích thước vượt quá max_width hoặc max_height, giữ nguyên tỷ lệ khung hình.
    """
    # Xử lý xoay theo EXIF
    try:
        img = ImageOps.exif_transpose(img)
    except Exception as e:
        logger.debug(f"Không thể đọc EXIF orientation: {e}")

    orig_w, orig_h = img.size

    # Chỉ resize nếu vượt quá ngưỡng quy định
    if orig_w > max_width or orig_h > max_height:
        ratio = min(max_width / orig_w, max_height / orig_h)
        new_w = max(1, int(orig_w * ratio))
        new_h = max(1, int(orig_h * ratio))
        logger.info(f"Resize ảnh: {orig_w}x{orig_h} -> {new_w}x{new_h}")
        img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

    return img


def remove_background(img: Image.Image) -> tuple[Image.Image, bool]:
    """
    Tách nền sản phẩm bằng thư viện rembg chạy local.
    Trả về: (img_đã_xóa_nền, success_boolean)
    """
    if not is_rembg_available():
        logger.warning("Thư viện rembg chưa được cài đặt. Giữ nguyên nền gốc.")
        return img, False

    try:
        import rembg
        logger.info("Bắt đầu tách nền bằng rembg...")
        # Đảm bảo ảnh ở định dạng RGBA trước khi tách nền
        rgba_img = img.convert("RGBA") if img.mode != "RGBA" else img
        no_bg_img = rembg.remove(rgba_img)
        logger.info("Tách nền thành công.")
        return no_bg_img, True
    except Exception as e:
        logger.warning(f"Lỗi khi tách nền bằng rembg: {e}. Giữ nguyên ảnh gốc.")
        return img, False


def apply_watermark(
    base_img: Image.Image,
    watermark_path: str | Path,
    position: str = "bottom-right",
    opacity: float = 0.7,
    scale: float = 0.18,
    margin: int = 24,
) -> tuple[Image.Image, bool]:
    """
    Đóng dấu logo watermark lên ảnh gốc:
    - base_img: Ảnh gốc (PIL Image)
    - watermark_path: Đường dẫn file logo (PNG, WebP...)
    - position: 'bottom-right' | 'bottom-left' | 'top-right' | 'top-left' | 'center'
    - opacity: Độ mờ trong suốt (0.1 -> 1.0)
    - scale: Tỷ lệ kích thước watermark so với chiều ngang của ảnh gốc (mặc định 18%)
    - margin: Khoảng cách cách mép (pixel)
    """
    wm_path = Path(watermark_path)
    if not wm_path.exists():
        logger.warning(f"Không tìm thấy file watermark: {watermark_path}")
        return base_img, False

    try:
        # Mở logo và chuyển sang RGBA để xử lý kênh alpha
        wm_raw = Image.open(wm_path).convert("RGBA")
        try:
            wm_raw = ImageOps.exif_transpose(wm_raw)
        except Exception:
            pass

        base_w, base_h = base_img.size

        # Tính toán kích thước mới của logo theo tỷ lệ scale của ảnh chính
        target_wm_w = max(40, int(base_w * scale))
        # Không để logo chiếm quá 50% ảnh chính
        target_wm_w = min(target_wm_w, int(base_w * 0.5))

        wm_ratio = target_wm_w / wm_raw.width
        target_wm_h = max(1, int(wm_raw.height * wm_ratio))

        wm_resized = wm_raw.resize((target_wm_w, target_wm_h), Image.Resampling.LANCZOS)

        # Điều chỉnh độ trong suốt (opacity)
        if opacity < 1.0:
            opacity = max(0.05, min(1.0, opacity))
            # Tách các kênh màu R, G, B, A
            r, g, b, a = wm_resized.split()
            # Giảm giá trị alpha theo opacity
            a = a.point(lambda p: int(p * opacity))
            wm_resized = Image.merge("RGBA", (r, g, b, a))

        # Xác định tọa độ đặt logo
        pos_key = position.lower().strip()
        wm_w, wm_h = wm_resized.size

        if pos_key == "bottom-left":
            x = margin
            y = base_h - wm_h - margin
        elif pos_key == "top-right":
            x = base_w - wm_w - margin
            y = margin
        elif pos_key == "top-left":
            x = margin
            y = margin
        elif pos_key == "center":
            x = (base_w - wm_w) // 2
            y = (base_h - wm_h) // 2
        else:  # Mặc định: bottom-right
            x = base_w - wm_w - margin
            y = base_h - wm_h - margin

        # Đảm bảo tọa độ không vượt ra ngoài khung ảnh
        x = max(0, min(x, base_w - wm_w))
        y = max(0, min(y, base_h - wm_h))

        # Đưa ảnh gốc sang RGBA để ghép lớp (alpha composite)
        canvas = base_img.convert("RGBA")
        overlay = Image.new("RGBA", canvas.size, (255, 255, 255, 0))
        overlay.paste(wm_resized, (x, y), wm_resized)

        composed = Image.alpha_composite(canvas, overlay)
        return composed, True

    except Exception as e:
        logger.exception(f"Lỗi khi đóng dấu watermark: {e}")
        return base_img, False


def crop_image_ratio(img: Image.Image, ratio: str = "1:1", offset_pct: float = 0.5) -> Image.Image:
    """
    Cắt ảnh theo các tỷ lệ tiêu chuẩn TMĐT (1:1, 4:3, 16:9, 3:4) với vị trí vùng cắt tùy biến:
    - ratio: "1:1", "4:3", "16:9", "3:4"
    - offset_pct: Vị trí dịch chuyển vùng cắt:
        0.0 = Cạnh Trái (nếu ảnh ngang) / Cạnh Trên (nếu ảnh dọc)
        0.5 = Chính giữa (mặc định)
        1.0 = Cạnh Phải (nếu ảnh ngang) / Cạnh Dưới (nếu ảnh dọc)
    """
    w, h = img.size
    ratio_parts = ratio.split(":")
    if len(ratio_parts) != 2:
        return img

    try:
        rw = float(ratio_parts[0])
        rh = float(ratio_parts[1])
        target_r = rw / rh
    except ValueError:
        return img

    curr_r = w / h
    if abs(curr_r - target_r) < 0.005:
        return img

    offset = max(0.0, min(1.0, float(offset_pct)))

    if curr_r > target_r:
        # Ảnh rộng hơn tỷ lệ mong muốn -> cắt bớt 2 bên (hoặc theo offset)
        new_w = max(1, int(h * target_r))
        slack = w - new_w
        left = int(slack * offset)
        return img.crop((left, 0, left + new_w, h))
    else:
        # Ảnh cao hơn tỷ lệ mong muốn -> cắt bớt trên dưới (hoặc theo offset)
        new_h = max(1, int(w / target_r))
        slack = h - new_h
        top = int(slack * offset)
        return img.crop((0, top, w, top + new_h))


def rotate_image(img: Image.Image, angle: int = 90) -> Image.Image:
    """Xoay ảnh theo góc 90 độ cùng chiều kim đồng hồ."""
    return img.rotate(-angle, expand=True)


def flip_image(img: Image.Image, horizontal: bool = True) -> Image.Image:
    """Lật ảnh (ngang hoặc dọc)."""
    if horizontal:
        return ImageOps.mirror(img)
    return ImageOps.flip(img)


def resize_dimensions(img: Image.Image, width: int, height: int, keep_aspect: bool = False) -> Image.Image:
    """Đổi kích thước ảnh theo độ phân giải mong muốn."""
    width = max(10, width)
    height = max(10, height)
    if keep_aspect:
        img_copy = img.copy()
        img_copy.thumbnail((width, height), Image.Resampling.LANCZOS)
        return img_copy
    return img.resize((width, height), Image.Resampling.LANCZOS)


def extract_image_from_editor(editor_data: Any) -> Image.Image | None:
    """Trích xuất ảnh PIL an toàn từ dữ liệu trình soạn ảnh (PIL / đường dẫn / dict có 'composite'|'background')."""
    if editor_data is None:
        return None
    if isinstance(editor_data, Image.Image):
        return editor_data
    if isinstance(editor_data, str) and Path(editor_data).exists():
        try:
            return Image.open(editor_data)
        except Exception:
            return None
    if isinstance(editor_data, dict):
        comp = editor_data.get("composite") or editor_data.get("background")
        if comp is not None:
            if isinstance(comp, Image.Image):
                return comp
            if isinstance(comp, str) and Path(comp).exists():
                try:
                    return Image.open(comp)
                except Exception:
                    pass
            try:
                import numpy as np
                if isinstance(comp, np.ndarray):
                    return Image.fromarray(comp)
            except Exception:
                pass
    return None


def process_single_image(
    input_path: str | Path,
    output_dir: str | Path | None = None,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Xử lý trọn gói 1 file ảnh theo pipeline:
    Resize -> Tách nền (nếu bật) -> Watermark (nếu có) -> Nén WebP.

    Returns dict kết quả chi tiết.
    """
    inp = Path(input_path)
    if not inp.exists():
        return {
            "success": False,
            "error": f"File không tồn tại: {input_path}",
            "original_path": str(input_path),
            "output_path": None,
        }

    opts = options or {}
    out_dir = Path(output_dir) if output_dir else DEFAULT_PROCESSED_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    max_w = opts.get("max_width", 1200)
    max_h = opts.get("max_height", 1200)
    quality = opts.get("quality", 85)
    do_remove_bg = opts.get("remove_bg", False)
    watermark_path = opts.get("watermark_path")
    wm_pos = opts.get("watermark_position", "bottom-right")
    wm_opacity = opts.get("watermark_opacity", 0.7)
    wm_scale = opts.get("watermark_scale", 0.18)
    out_format = opts.get("format", "WEBP").upper()
    prefix = opts.get("prefix", "")

    orig_size = inp.stat().st_size

    try:
        with Image.open(inp) as raw_img:
            # 1. Resize & Chuẩn hóa EXIF
            working_img = optimize_and_resize(raw_img, max_width=max_w, max_height=max_h)

            # 2. Tách nền (nếu người dùng bật)
            bg_removed = False
            if do_remove_bg:
                working_img, bg_removed = remove_background(working_img)

            # 3. Đóng dấu Watermark (nếu có đường dẫn file logo)
            watermarked = False
            if watermark_path:
                working_img, watermarked = apply_watermark(
                    working_img,
                    watermark_path=watermark_path,
                    position=wm_pos,
                    opacity=wm_opacity,
                    scale=wm_scale,
                )

            # 4. Lưu ảnh đã tối ưu ra file
            ext = ".webp" if out_format == "WEBP" else f".{out_format.lower()}"
            stem = inp.stem
            if prefix:
                stem = f"{prefix}_{stem}"
            out_filename = f"{stem}_optimized{ext}"
            out_path = out_dir / out_filename

            # Đảm bảo tương thích kênh màu khi lưu
            final_img = working_img
            if out_format == "JPEG":
                # JPEG không hỗ trợ kênh Alpha (trong suốt) -> chuyển sang RGB nền trắng
                if final_img.mode in ("RGBA", "LA", "P"):
                    bg = Image.new("RGB", final_img.size, (255, 255, 255))
                    alpha = final_img.split()[-1] if final_img.mode in ("RGBA", "LA") else None
                    bg.paste(final_img, mask=alpha)
                    final_img = bg
                else:
                    final_img = final_img.convert("RGB")
                final_img.save(out_path, format="JPEG", quality=quality, optimize=True)
            else:
                # Mặc định WEBP: hỗ trợ cả RGB và RGBA trong suốt
                if final_img.mode not in ("RGB", "RGBA"):
                    final_img = final_img.convert("RGBA" if "A" in final_img.mode else "RGB")
                final_img.save(out_path, format="WEBP", quality=quality, method=4)

        new_size = out_path.stat().st_size
        saved_bytes = max(0, orig_size - new_size)
        saved_percent = round((saved_bytes / orig_size) * 100, 1) if orig_size > 0 else 0.0

        return {
            "success": True,
            "error": None,
            "original_path": str(inp),
            "output_path": str(out_path),
            "original_size_bytes": orig_size,
            "processed_size_bytes": new_size,
            "original_size_kb": round(orig_size / 1024, 1),
            "processed_size_kb": round(new_size / 1024, 1),
            "saved_percent": saved_percent,
            "width": final_img.width,
            "height": final_img.height,
            "format": out_format,
            "watermarked": watermarked,
            "bg_removed": bg_removed,
        }

    except Exception as e:
        logger.exception(f"Lỗi khi xử lý ảnh {inp.name}: {e}")
        return {
            "success": False,
            "error": str(e),
            "original_path": str(inp),
            "output_path": None,
        }


def process_image_batch(
    input_paths: list[str | Path],
    output_dir: str | Path | None = None,
    options: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """
    Xử lý hàng loạt danh sách đường dẫn ảnh.
    Trả về danh sách kết quả chi tiết từng ảnh.
    """
    results = []
    for p in input_paths:
        res = process_single_image(p, output_dir=output_dir, options=options)
        results.append(res)
    return results


def format_processing_summary(results: list[dict[str, Any]]) -> str:
    """
    Định dạng báo cáo tổng hợp sau khi xử lý danh sách ảnh sang Markdown thân thiện.
    """
    if not results:
        return "*(Không có ảnh nào được xử lý)*"

    success_items = [r for r in results if r.get("success")]
    failed_items = [r for r in results if not r.get("success")]

    total_orig_kb = sum(r.get("original_size_kb", 0) for r in success_items)
    total_new_kb = sum(r.get("processed_size_kb", 0) for r in success_items)
    total_saved_percent = (
        round(((total_orig_kb - total_new_kb) / total_orig_kb) * 100, 1)
        if total_orig_kb > 0
        else 0.0
    )

    lines = [
        f"### 🖼️ Báo Cáo Xử Lý & Tối Ưu Ảnh ({len(success_items)}/{len(results)} thành công)",
        f"- **Dung lượng:** `{total_orig_kb:.1f} KB` ➜ `{total_new_kb:.1f} KB` (**Giảm {total_saved_percent}%**)",
        f"- **Định dạng đầu ra:** `WebP` (Chuẩn Google PageSpeed & SEO)",
    ]

    # Kiểm tra trạng thái watermark và tách nền
    wm_count = sum(1 for r in success_items if r.get("watermarked"))
    if wm_count > 0:
        lines.append(f"- **Watermark:** ✅ Đã đóng dấu logo ({wm_count} ảnh)")

    bg_count = sum(1 for r in success_items if r.get("bg_removed"))
    if bg_count > 0:
        lines.append(f"- **Tách nền:** ✅ Đã xóa phông sạch ({bg_count} ảnh)")

    if failed_items:
        lines.append("\n⚠️ **Lỗi khi xử lý một số ảnh:**")
        for f in failed_items:
            lines.append(f"- `{Path(f.get('original_path', '')).name}`: {f.get('error')}")

    return "\n".join(lines)
