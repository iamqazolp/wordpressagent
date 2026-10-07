"""
tests/test_searcher.py
Unit tests for core/searcher.py:
- Intelligent query construction (_build_search_query)
- Relevance filtering (_is_relevant)
- URL unwrapping (_unwrap_url)
- SerpAPI search with timeout and graceful error handling (_search_via_serpapi)
- Concurrent search, fallback to DuckDuckGo, and extra_urls handling (search_articles)
"""
from __future__ import annotations
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.searcher import (
    _build_search_query,
    _is_relevant,
    _unwrap_url,
    _search_via_serpapi,
    _search_via_duckduckgo,
    search_articles,
    BLOCKED_DOMAINS,
)
from config import settings


# ==============================================================================
# 1. Tests for _build_search_query
# ==============================================================================
class TestBuildSearchQuery:
    def test_technical_products_add_specs_suffix(self):
        assert _build_search_query("Máy khoan pin Bosch GSB") == "Máy khoan pin Bosch GSB thông số kỹ thuật"
        assert _build_search_query("Điện thoại iPhone 15 Pro") == "Điện thoại iPhone 15 Pro thông số kỹ thuật"
        assert _build_search_query("Máy bơm nước Wilo") == "Máy bơm nước Wilo thông số kỹ thuật"

    def test_non_technical_products_keep_original_name(self):
        assert _build_search_query("BÚN CHẢ") == "BÚN CHẢ"
        assert _build_search_query("thịt trâu") == "thịt trâu"
        assert _build_search_query("Áo sơ mi nam") == "Áo sơ mi nam"
        assert _build_search_query("Cà phê Robusta Đắk Lắk") == "Cà phê Robusta Đắk Lắk"

    def test_already_has_specs_not_duplicated(self):
        assert _build_search_query("Máy khoan Bosch thông số kỹ thuật") == "Máy khoan Bosch thông số kỹ thuật"


# ==============================================================================
# 2. Tests for _is_relevant
# ==============================================================================
class TestIsRelevant:
    def test_rejects_unrelated_items(self):
        # Bún Chả vs Bàn chải
        assert not _is_relevant("BÚN CHẢ", "Bàn chải điện thông minh RST-15CW", "https://rapido.vn/ban-chai")
        assert not _is_relevant("BÚN CHẢ", "Bàn chải nhà tắm Kirei", "https://inochi.vn/ban-chai")
        assert not _is_relevant("BÚN CHẢ", "Bàn chải kỹ thuật cán gỗ", "https://prostech.vn/tech-brush")

    def test_accepts_matching_items(self):
        assert _is_relevant("BÚN CHẢ", "Cách làm bún chả Hà Nội ngon chuẩn vị", "https://bunchasinhtu.vn/bun-cha")
        assert _is_relevant("Máy khoan pin", "Máy khoan pin Bosch GSB 18V chính hãng", "https://boschvn.com/may-khoan-pin")
        assert _is_relevant("Optimus Prime", "Mô hình Blokees Transformers CC09 Optimus Prime", "https://hacom.vn/optimus-prime")


# ==============================================================================
# 3. Tests for _unwrap_url
# ==============================================================================
class TestUnwrapUrl:
    def test_normal_url_remains_unchanged(self):
        url = "https://dienmayxanh.com/may-giat-panasonic-na-f90a9brv"
        assert _unwrap_url(url) == url

    def test_translate_google_with_u_param(self):
        wrapped = (
            "https://translate.google.com/translate?"
            "sl=en&tl=vi&u=https%3A%2F%2Fdienmayxanh.com%2Fmay-giat-panasonic"
        )
        expected = "https://dienmayxanh.com/may-giat-panasonic"
        assert _unwrap_url(wrapped) == expected

    def test_translate_google_with_url_param(self):
        wrapped = "https://translate.google.com/translate?url=https%3A%2F%2Ffptshop.com.vn%2Fsan-pham"
        expected = "https://fptshop.com.vn/san-pham"
        assert _unwrap_url(wrapped) == expected

    def test_google_redirect_with_q_param(self):
        wrapped = "https://www.google.com/url?q=https%3A%2F%2Fthegioididong.com%2Fdtdd&sa=U"
        expected = "https://thegioididong.com/dtdd"
        assert _unwrap_url(wrapped) == expected


# ==============================================================================
# 4. Tests for _search_via_serpapi
# ==============================================================================
class TestSearchViaSerpapi:
    @patch("serpapi.GoogleSearch")
    def test_sets_timeout_and_extracts_results(self, mock_google_search_cls, monkeypatch):
        monkeypatch.setattr(settings, "SERP_API_KEY", "dummy_key")
        monkeypatch.setattr(settings, "SERP_TIMEOUT", 8)

        mock_search_instance = MagicMock()
        mock_google_search_cls.return_value = mock_search_instance
        mock_search_instance.get_dict.return_value = {
            "organic_results": [
                {
                    "title": "Máy Giặt Panasonic 9kg",
                    "link": "https://dienmayxanh.com/may-giat-panasonic",
                },
                {
                    "title": "Máy Giặt DMX Bản dịch",
                    "link": "https://translate.google.com/translate?u=https%3A%2F%2Fmediamart.vn%2Fmay-giat-panasonic",
                },
            ]
        }

        results = _search_via_serpapi("Máy giặt Panasonic", limit=5)

        assert mock_search_instance.timeout == 8
        assert len(results) == 2
        assert results[0]["url"] == "https://dienmayxanh.com/may-giat-panasonic"
        assert results[1]["url"] == "https://mediamart.vn/may-giat-panasonic"

    @patch("serpapi.GoogleSearch")
    def test_filters_irrelevant_and_blocked_domains(self, mock_google_search_cls, monkeypatch):
        monkeypatch.setattr(settings, "SERP_API_KEY", "dummy_key")
        mock_search_instance = MagicMock()
        mock_google_search_cls.return_value = mock_search_instance
        mock_search_instance.get_dict.return_value = {
            "organic_results": [
                {
                    "title": "Bàn chải đánh răng",
                    "link": "https://shop.com/ban-chai",
                },
                {
                    "title": "Bún chả Hà Nội ngon",
                    "link": "https://facebook.com/bun-cha-page",
                },
                {
                    "title": "Bún chả Sinh Từ gia truyền",
                    "link": "https://bunchasinhtu.vn/gioi-thieu",
                },
            ]
        }

        results = _search_via_serpapi("Bún chả", limit=5)
        # Bàn chải is irrelevant, Facebook is blocked -> only Sinh Từ kept
        assert len(results) == 1
        assert results[0]["url"] == "https://bunchasinhtu.vn/gioi-thieu"

    @patch("serpapi.GoogleSearch")
    def test_handles_timeout_gracefully(self, mock_google_search_cls, monkeypatch):
        monkeypatch.setattr(settings, "SERP_API_KEY", "dummy_key")
        mock_search_instance = MagicMock()
        mock_google_search_cls.return_value = mock_search_instance
        mock_search_instance.get_dict.side_effect = TimeoutError("Request timed out")

        results = _search_via_serpapi("Máy giặt Panasonic", limit=5, timeout=5)
        assert results == []


# ==============================================================================
# 5. Tests for search_articles
# ==============================================================================
class TestSearchArticles:
    @patch("core.searcher._search_via_duckduckgo")
    @patch("core.searcher._search_via_serpapi")
    def test_concurrent_search_merges_serp_and_ddg(
        self, mock_serp, mock_ddg, monkeypatch
    ):
        monkeypatch.setattr(settings, "SERP_API_KEY", "test_key")
        monkeypatch.setattr(settings, "SEARCH_RESULT_COUNT", 4)

        mock_serp.return_value = [
            {"url": "https://serp1.com", "title": "Bún chả 1", "source": "google"},
            {"url": "https://serp2.com", "title": "Bún chả 2", "source": "google"},
        ]
        mock_ddg.return_value = [
            {"url": "https://serp1.com", "title": "Bún chả 1 Dup", "source": "duckduckgo"},
            {"url": "https://ddg1.com", "title": "Bún chả DDG 1", "source": "duckduckgo"},
            {"url": "https://ddg2.com", "title": "Bún chả DDG 2", "source": "duckduckgo"},
        ]

        results = search_articles("Bún chả")

        assert len(results) == 4
        urls = [r["url"] for r in results]
        assert urls == ["https://serp1.com", "https://serp2.com", "https://ddg1.com", "https://ddg2.com"]

    @patch("core.searcher._search_via_duckduckgo")
    @patch("core.searcher._search_via_serpapi")
    def test_fallback_when_serpapi_fails(
        self, mock_serp, mock_ddg, monkeypatch
    ):
        monkeypatch.setattr(settings, "SERP_API_KEY", "test_key")
        monkeypatch.setattr(settings, "SEARCH_RESULT_COUNT", 2)

        mock_serp.return_value = []
        mock_ddg.return_value = [
            {"url": "https://ddg1.com", "title": "Bún chả 1", "source": "duckduckgo"},
            {"url": "https://ddg2.com", "title": "Bún chả 2", "source": "duckduckgo"},
        ]

        results = search_articles("Bún chả")
        assert len(results) == 2
        assert all(r["source"] == "duckduckgo" for r in results)

    @patch("core.searcher._search_via_duckduckgo")
    @patch("core.searcher._search_via_serpapi")
    def test_extra_urls_prioritized(
        self, mock_serp, mock_ddg, monkeypatch
    ):
        monkeypatch.setattr(settings, "SERP_API_KEY", "test_key")
        monkeypatch.setattr(settings, "SEARCH_RESULT_COUNT", 3)

        extra = ["https://my-recipe.vn/bun-cha"]
        mock_serp.return_value = [
            {"url": "https://serp1.com", "title": "Bún chả 1", "source": "google"}
        ]
        mock_ddg.return_value = []

        results = search_articles("Bún chả", extra_urls=extra)
        assert results[0]["url"] == "https://my-recipe.vn/bun-cha"
        assert results[0]["source"] == "manual"
        assert results[1]["url"] == "https://serp1.com"
        assert results[1]["source"] == "google"


def test_search_returns_without_waiting_for_slow_duckduckgo(monkeypatch):
    import time
    from core import searcher

    serp = [{"url": f"https://a{i}.vn", "title": "t", "source": "google"} for i in range(5)]
    monkeypatch.setattr(settings, "SERP_API_KEY", "k", raising=False)
    monkeypatch.setattr(settings, "SEARCH_RESULT_COUNT", 5, raising=False)
    monkeypatch.setattr(searcher, "_search_via_serpapi", lambda name, limit=5: serp)
    monkeypatch.setattr(searcher, "_search_via_duckduckgo", lambda name, limit=5: time.sleep(3) or [])
    t = time.monotonic()
    assert searcher.search_articles("Quạt") == serp
    assert time.monotonic() - t < 1.0


def test_search_keeps_late_duckduckgo_results_when_serpapi_empty(monkeypatch):
    import time
    from core import searcher

    ddg = [{"url": "https://d.vn", "title": "t", "source": "duckduckgo"}]
    monkeypatch.setattr(settings, "SERP_API_KEY", "k", raising=False)
    monkeypatch.setattr(settings, "SERP_TIMEOUT", 8, raising=False)
    monkeypatch.setattr(searcher, "_search_via_serpapi", lambda name, limit=5: [])
    monkeypatch.setattr(searcher, "_search_via_duckduckgo", lambda name, limit=5: time.sleep(2.6) or ddg)
    assert searcher.search_articles("Quạt") == ddg            # trước đây bị bỏ vì DuckDuckGo > 2.5s
