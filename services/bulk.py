"""
services/bulk.py — tạo/đăng bài hàng loạt từ file CSV/Excel.

Gồm: đọc file danh sách sản phẩm, tạo bài và lưu nháp, hoặc tạo và đăng ngay từng sản phẩm.
Một sản phẩm lỗi không làm dừng cả lô.
"""
from __future__ import annotations

import csv
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from services import generation
from services import publishing
from services import sites as site_service
from services.errors import ServiceError

logger = logging.getLogger(__name__)

Progress = Callable[[float, str], None]

# Tên cột chấp nhận (đã hạ chữ thường) cho từng trường, theo thứ tự ưu tiên
_COLUMN_ALIASES = {
    "product_name": ["product_name", "ten_san_pham", "tên sản phẩm", "name", "san_pham", "sản phẩm", "tên"],
    "ref_urls": ["ref_urls", "url", "link", "url tham khảo"],
    "notes": ["notes", "ghi_chu", "ghi chú", "ghi chú ai", "note"],
    "regular_price": ["regular_price", "gia_goc", "giá gốc", "giá", "price"],
    "sale_price": ["sale_price", "gia_khuyen_mai", "giá khuyến mại", "giá km", "sale"],
}


@dataclass(frozen=True)
class BulkRow:
    """Một dòng kết quả của lô đăng: kind = 'create_failed' | 'published' | 'publish_failed'."""
    kind: str
    product_name: str
    site_name: str = "-"
    url: str = "-"
    detail: str = ""
    wp_status: str = "draft"


def _pick(row: dict, field: str) -> str:
    for key in _COLUMN_ALIASES[field]:
        val = row.get(key)
        if val:
            return "" if val.lower() == "nan" else val
    return ""


def parse_product_file(file_path: str) -> tuple[list[dict], str]:
    """
    Đọc CSV hoặc Excel. Trả (danh_sách_sản_phẩm, loại_file 'CSV'|'Excel').
    Mỗi sản phẩm: {product_name, ref_urls, notes, regular_price, sale_price}. Raise ServiceError nếu file không dùng được.
    """
    ext = Path(file_path).suffix.lower()
    try:
        if ext in (".xlsx", ".xls"):
            rows = pd.read_excel(file_path, dtype=str).fillna("").to_dict(orient="records")
        else:
            try:
                with open(file_path, "r", encoding="utf-8-sig") as f:
                    reader = csv.DictReader(f)
                    if not reader.fieldnames:
                        raise ServiceError("File rỗng hoặc không đúng định dạng.")
                    rows = list(reader)
            except UnicodeDecodeError:
                with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                    reader = csv.DictReader(f)
                    if not reader.fieldnames:
                        raise ServiceError("File rỗng hoặc không đúng định dạng.")
                    rows = list(reader)
    except ServiceError:
        raise
    except Exception as e:
        logger.exception("Lỗi khi đọc file CSV / Excel")
        raise ServiceError(f"Lỗi đọc file: {e}")

    products: list[dict] = []
    for row in rows:
        cleaned = {
            str(k).strip().lower(): (str(v).strip() if v is not None and not (isinstance(v, float) and pd.isna(v)) else "")
            for k, v in row.items()
            if k is not None
        }
        name = _pick(cleaned, "product_name")
        if not name:
            continue
        products.append({field: (name if field == "product_name" else _pick(cleaned, field)) for field in _COLUMN_ALIASES})

    if not products:
        raise ServiceError("Không tìm thấy dòng dữ liệu hợp lệ nào (cần cột 'product_name' hoặc 'tên sản phẩm').")
    return products, ("Excel" if ext in (".xlsx", ".xls") else "CSV")


def split_reference_urls(raw: str) -> list[str]:
    """Tách URL tham khảo bằng ; , hoặc xuống dòng; chỉ giữ chuỗi bắt đầu bằng http."""
    return [u.strip() for u in re.split(r"[;\n,]+", raw or "") if u.strip().startswith("http")]


def list_site_names() -> list[str]:
    return site_service.list_site_names()


def generate_and_save(
    products: list[dict],
    site_names: list[str],
    template_name: str | None,
    randomize: bool,
    progress: Progress | None = None,
) -> list[dict]:
    """
    Tạo bài cho từng sản phẩm và lưu nháp vào Kho bài viết (status 'saved').
    Trả list[{product_name, articles, regular_price, sale_price, status: 'success'|'error', error?}].
    """
    if not products:
        raise ServiceError("Không có sản phẩm nào để xử lý. Vui lòng tải file CSV trước.")
    if not site_names:
        raise ServiceError("Vui lòng chọn ít nhất 1 website đăng bài.")

    total = len(products)
    results: list[dict] = []
    for i, prod in enumerate(products):
        name = prod.get("product_name", f"Sản phẩm {i + 1}")
        base = {"product_name": name, "regular_price": prod.get("regular_price", ""), "sale_price": prod.get("sale_price", "")}
        if progress:
            progress(i / total, f"🤖 [{i + 1}/{total}] Đang viết: {name[:30]}...")
        try:
            articles = generation.generate_for_sites(
                name,
                site_names,
                extra_urls=split_reference_urls(prod.get("ref_urls", "")),
                user_notes=prod.get("notes", ""),
                randomize=randomize,
                template_name=template_name,
            )
            saved = _save_as_drafts(articles, base["regular_price"], base["sale_price"])
            results.append({**base, "articles": articles, "status": "success", "saved": saved})
        except Exception as e:
            logger.exception(f"Lỗi khi tạo bài hàng loạt cho {name}")
            results.append({**base, "articles": {}, "status": "error", "error": str(e)})
    return results


def _save_as_drafts(articles: dict[str, dict], regular_price: str, sale_price: str) -> tuple[tuple[str, int], ...]:
    # Hàng loạt luôn lưu theo loại 'product' (hành vi cũ của tab này)
    return publishing.save_drafts(articles, [], "product", regular_price, sale_price).saved


def generate_and_publish(
    products: list[dict],
    site_names: list[str],
    template_name: str | None,
    randomize: bool,
    post_type: str,
    post_status: str,
    progress: Progress | None = None,
) -> list[BulkRow]:
    """Tạo rồi đăng ngay từng sản phẩm lên các website đã chọn; ghi lịch sử cho mọi kết quả."""
    if not products:
        raise ServiceError("Không có sản phẩm nào để xử lý. Vui lòng tải file CSV trước.")
    if not site_names:
        raise ServiceError("Vui lòng chọn ít nhất 1 website đăng bài.")

    total = len(products)
    rows: list[BulkRow] = []
    for i, prod in enumerate(products):
        name = prod.get("product_name", f"Sản phẩm {i + 1}")
        if progress:
            progress(i / total, f"🚀 [{i + 1}/{total}] Đang xử lý: {name[:30]}...")
        try:
            articles = generation.generate_for_sites(
                name,
                site_names,
                extra_urls=split_reference_urls(prod.get("ref_urls", "")),
                user_notes=prod.get("notes", ""),
                randomize=randomize,
                template_name=template_name,
            )
        except Exception as e:
            logger.exception(f"Lỗi tạo bài: {name}")
            rows.append(BulkRow("create_failed", name, detail=str(e)))
            continue

        try:
            results = publishing.publish_and_record(
                articles, [], post_type, post_status,
                regular_price=prod.get("regular_price", ""), sale_price=prod.get("sale_price", ""),
            )
        except Exception as e:
            logger.exception(f"Lỗi đăng bài cho {name}")
            rows.append(BulkRow("publish_failed", name, detail=str(e)))
            continue

        for res in results:
            site = res.get("site_name", "")
            if res.get("success"):
                rows.append(BulkRow("published", name, site, res.get("post_url", ""), wp_status=res.get("status", "draft")))
            else:
                rows.append(BulkRow("publish_failed", name, site, "-", res.get("error", "Lỗi không xác định")))
    return rows
