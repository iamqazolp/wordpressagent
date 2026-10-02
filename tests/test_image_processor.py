"""
tests/test_image_processor.py
Unit tests cho core/image_processor.py
"""
import shutil
import tempfile
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageDraw

from core.image_processor import (
    optimize_and_resize,
    apply_watermark,
    remove_background,
    process_single_image,
    process_image_batch,
    format_processing_summary,
    WATERMARK_POSITIONS,
)


def _create_sample_image(path: Path, width: int = 1600, height: int = 1200, color: tuple = (200, 100, 50)):
    """Tạo một ảnh mẫu để test."""
    img = Image.new("RGB", (width, height), color)
    draw = ImageDraw.Draw(img)
    # Vẽ vài hình khối để có dung lượng thực tế
    draw.rectangle([100, 100, width - 100, height - 100], fill=(50, 150, 200))
    draw.ellipse([300, 300, 800, 800], fill=(255, 255, 0))
    img.save(path, format="JPEG", quality=95)
    return path


def _create_sample_watermark(path: Path, width: int = 300, height: int = 100):
    """Tạo một logo watermark RGBA trong suốt."""
    wm = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(wm)
    draw.rounded_rectangle([0, 0, width, height], radius=15, fill=(0, 120, 255, 200))
    draw.text((20, 35), "MY BRAND LOGO", fill=(255, 255, 255, 255))
    wm.save(path, format="PNG")
    return path


def test_optimize_and_resize():
    """Test tính năng resize giữ đúng tỷ lệ khung hình."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        img_file = tmp_path / "large.jpg"
        _create_sample_image(img_file, width=2400, height=1800)

        with Image.open(img_file) as img:
            resized = optimize_and_resize(img, max_width=1200, max_height=1200)
            assert resized.width == 1200
            assert resized.height == 900  # Giữ tỷ lệ 4:3


def test_watermark_positions():
    """Test tính năng đóng dấu watermark ở các vị trí khác nhau."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        img_file = tmp_path / "product.jpg"
        wm_file = tmp_path / "logo.png"

        _create_sample_image(img_file, width=1000, height=800)
        _create_sample_watermark(wm_file)

        with Image.open(img_file) as img:
            for pos in WATERMARK_POSITIONS.keys():
                watermarked, ok = apply_watermark(
                    img,
                    watermark_path=wm_file,
                    position=pos,
                    opacity=0.7,
                    scale=0.2,
                )
                assert ok is True
                assert watermarked.size == (1000, 800)
                assert watermarked.mode == "RGBA"


def test_watermark_missing_file_fallback():
    """Test nếu đường dẫn watermark không tồn tại thì không gây crash và giữ nguyên ảnh."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        img_file = tmp_path / "product.jpg"
        _create_sample_image(img_file, width=800, height=600)

        with Image.open(img_file) as img:
            res_img, ok = apply_watermark(img, watermark_path=tmp_path / "non_existent.png")
            assert ok is False
            assert res_img.size == (800, 600)


def test_process_single_image_to_webp():
    """Test quy trình xử lý trọn gói 1 ảnh ra định dạng WebP với nén dung lượng."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        img_file = tmp_path / "input.jpg"
        out_dir = tmp_path / "output"
        wm_file = tmp_path / "logo.png"

        _create_sample_image(img_file, width=2000, height=1500)
        _create_sample_watermark(wm_file)

        res = process_single_image(
            input_path=img_file,
            output_dir=out_dir,
            options={
                "max_width": 1200,
                "max_height": 1200,
                "format": "WEBP",
                "quality": 85,
                "watermark_path": wm_file,
                "watermark_position": "bottom-right",
                "watermark_opacity": 0.8,
            },
        )

        assert res["success"] is True
        assert res["output_path"] is not None
        assert Path(res["output_path"]).exists()
        assert Path(res["output_path"]).suffix == ".webp"
        assert res["width"] == 1200
        assert res["height"] == 900
        assert res["watermarked"] is True
        # Dung lượng WebP nén từ ảnh lớn 2000x1500 phải giảm đáng kể
        assert res["processed_size_bytes"] < res["original_size_bytes"]
        assert res["saved_percent"] > 0


def test_process_image_batch_and_summary():
    """Test xử lý danh sách ảnh và định dạng báo cáo markdown."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        img1 = tmp_path / "img1.jpg"
        img2 = tmp_path / "img2.jpg"
        out_dir = tmp_path / "output"

        _create_sample_image(img1, width=1500, height=1000)
        _create_sample_image(img2, width=1600, height=1200)

        results = process_image_batch(
            input_paths=[img1, img2],
            output_dir=out_dir,
            options={"max_width": 1000, "quality": 80},
        )

        assert len(results) == 2
        assert all(r["success"] for r in results)

        summary = format_processing_summary(results)
        assert "Báo Cáo Xử Lý" in summary
        assert "WebP" in summary
        assert "Giảm" in summary


def test_interactive_studio_tools():
    """Test các chức năng chỉnh sửa tương tác: crop ratio with offset_pct, rotate, flip, resize."""
    from core.image_processor import (
        crop_image_ratio,
        rotate_image,
        flip_image,
        resize_dimensions,
    )

    # 1. Test crop ratios with offset_pct
    base = Image.new("RGB", (1200, 600), color="blue")
    crop_1_1_center = crop_image_ratio(base, "1:1", offset_pct=0.5)
    assert crop_1_1_center.size == (600, 600)

    crop_1_1_left = crop_image_ratio(base, "1:1", offset_pct=0.0)
    assert crop_1_1_left.size == (600, 600)

    crop_1_1_right = crop_image_ratio(base, "1:1", offset_pct=1.0)
    assert crop_1_1_right.size == (600, 600)

    crop_4_3 = crop_image_ratio(base, "4:3", offset_pct=0.5)
    assert crop_4_3.size == (800, 600)

    crop_16_9 = crop_image_ratio(base, "16:9", offset_pct=0.5)
    assert crop_16_9.width == int(600 * 16 / 9)
    assert crop_16_9.height == 600

    # 2. Test rotate
    rot = rotate_image(base, 90)
    assert rot.size == (600, 1200)

    # 3. Test flip
    flipped = flip_image(base, horizontal=True)
    assert flipped.size == base.size

    # 4. Test resize_dimensions
    resized = resize_dimensions(base, 800, 800)
    assert resized.size == (800, 800)


if __name__ == "__main__":
    print("Running tests manually...")
    test_optimize_and_resize()
    print("✓ test_optimize_and_resize passed")
    test_watermark_positions()
    print("✓ test_watermark_positions passed")
    test_watermark_missing_file_fallback()
    print("✓ test_watermark_missing_file_fallback passed")
    test_process_single_image_to_webp()
    print("✓ test_process_single_image_to_webp passed")
    test_process_image_batch_and_summary()
    print("✓ test_process_image_batch_and_summary passed")
    test_interactive_studio_tools()
    print("✓ test_interactive_studio_tools passed")
    print("\n🎉 ALL TESTS PASSED!")
