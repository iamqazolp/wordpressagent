"""Tách nền: một phiên rembg dùng chung, ảnh giống nhau (nhiều website) chỉ tách nền một lần."""
import concurrent.futures
import sys
import types

from PIL import Image

from core import image_processor as ip


def test_rembg_session_shared_and_result_cached(tmp_path, monkeypatch):
    calls = {"session": 0, "remove": 0}

    def new_session(*a, **k):
        calls["session"] += 1
        return object()

    def remove(img, session=None):
        assert session is not None
        calls["remove"] += 1
        return img.copy()

    monkeypatch.setitem(sys.modules, "rembg", types.SimpleNamespace(new_session=new_session, remove=remove))
    monkeypatch.setattr(ip, "_REMBG_AVAILABLE", True)
    monkeypatch.setattr(ip, "_rembg_session", None)
    monkeypatch.setattr(ip, "_bg_cache", ip.OrderedDict())
    src = tmp_path / "sp.jpg"
    Image.new("RGB", (64, 48), "red").save(src)

    def run(i):
        out = tmp_path / f"site{i}"
        return ip.process_single_image(src, output_dir=out, options={"remove_bg": True})

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:   # 4 website đăng cùng ảnh song song
        results = list(ex.map(run, range(4)))
    assert all(r["success"] and r["bg_removed"] for r in results)
    assert calls == {"session": 1, "remove": 1}


def test_watermark_cached_reloaded_on_change_and_file_not_locked(tmp_path):
    import os
    logo = tmp_path / "logo.png"
    Image.new("RGBA", (20, 10), (255, 0, 0, 255)).save(logo)
    base = Image.new("RGB", (400, 300), "white")
    ip._wm_cache.clear()
    _, ok = ip.apply_watermark(base, logo)
    first = ip._load_watermark(logo)
    assert ok and ip._load_watermark(logo) is first             # lần sau dùng lại, không giải mã lại

    os.replace(tmp_path / "logo.png", tmp_path / "old.png")      # Windows: chỉ đổi tên được nếu file không bị giữ mở
    Image.new("RGBA", (40, 10), (0, 0, 255, 255)).save(logo)
    os.utime(logo, ns=(1, 2))
    assert ip._load_watermark(logo).size == (40, 10)            # đổi logo -> nạp lại
    assert len([k for k in ip._wm_cache if k[0] == str(logo)]) == 1


def test_large_jpeg_is_downscaled_correctly(tmp_path):
    src = tmp_path / "big.jpg"
    Image.new("RGB", (4000, 3000), "green").save(src, quality=80)
    r = ip.process_single_image(src, output_dir=tmp_path / "out", options={"max_width": 1200, "max_height": 1200})
    assert r["success"] and (r["width"], r["height"]) == (1200, 900)
