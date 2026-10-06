"""Chọn/xoá/thêm ảnh của bài đã lưu: ngữ nghĩa None vs [] và lưu bền ảnh từ thư mục tạm."""
import json
from pathlib import Path

import pytest

from services import images as images_svc
from services import posts as svc
from ui.common import extract_gallery_paths, merge_image_selection
from ui import tab_history


@pytest.fixture
def img_dirs(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(images_svc, "DATA_DIR", data)
    monkeypatch.setattr(images_svc, "POST_IMAGES_DIR", data / "post_images")
    return tmp_path, data


def _img(d: Path, name: str, content=b"x") -> Path:
    p = d / name
    p.write_bytes(content)
    return p


def test_persist_copies_outside_files_and_keeps_inside(img_dirs):
    tmp, data = img_dirs
    a = _img(tmp, "Bơm dầu.jpg", b"AAA")
    inside = _img(data, "keep.jpg", b"BBB")
    out = images_svc.persist_images([str(a), str(inside), str(a), "/missing.jpg"])
    assert len(out) == 3                      # trùng bị bỏ
    assert out[0].startswith(str(data / "post_images")) and Path(out[0]).read_bytes() == b"AAA"
    assert Path(out[0]).name == "Bơm dầu.jpg"
    assert out[1] == str(inside) and out[2] == "/missing.jpg"
    a.unlink()
    assert Path(out[0]).exists()               # ảnh gốc tạm bị xoá vẫn còn bản lưu
    assert images_svc.persist_images([out[0]]) == [out[0]]   # idempotent


def test_extract_gallery_paths_and_merge():
    items = [("/a.jpg", None), ("/b.jpg", "cap"), {"path": "/c.jpg"}, "/a.jpg"]
    assert extract_gallery_paths(items) == ["/a.jpg", "/b.jpg", "/c.jpg"]
    assert extract_gallery_paths(None) == []
    assert merge_image_selection([("/a.jpg", None)], ["/n.jpg", "/a.jpg"]) == ["/a.jpg", "/n.jpg"]
    assert merge_image_selection(None, None) == []


def test_final_images_semantics():
    assert tab_history._final_images(tab_history._UNSET, None) is None
    assert tab_history._final_images(tab_history._UNSET, ["/n.jpg"]) == ["/n.jpg"]
    assert tab_history._final_images(None, None) is None
    assert tab_history._final_images([], None) == []          # xoá hết ảnh trong album
    assert tab_history._final_images([("/a.jpg", None)], ["/n.jpg"]) == ["/a.jpg", "/n.jpg"]

