"""
tests/test_searcher.py
Unit tests for core/searcher.py:
- URL unwrapping (_unwrap_url)
- SerpAPI search with timeout and graceful error handling (_search_via_serpapi)
- Concurrent search, fallback to DuckDuckGo, and extra_urls handling (search_articles)
"""
from __future__ import annotations
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure project root is in sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.searcher import (
    _unwrap_url,
    _search_via_serpapi,
    _search_via_duckduckgo,
    search_articles,
    BLOCKED_DOMAINS,
)
from config import settings


# ==============================================================================
# 1. Tests for _unwrap_url
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

    def test_google_redirect_with_url_param(self):
        wrapped = "https://www.google.com/url?url=https%3A%2F%2Fcellphones.com.vn%2Fiphone"
        expected = "https://cellphones.com.vn/iphone"
        assert _unwrap_url(wrapped) == expected

    def test_empty_or_no_target_param(self):
        assert _unwrap_url("") == ""
        assert _unwrap_url("https://translate.google.com/") == "https://translate.google.com/"


# ==============================================================================
# 2. Tests for _search_via_serpapi
# ==============================================================================
class TestSearchViaSerpapi:
    @patch("serpapi.GoogleSearch")
    def test_sets_timeout_and_extracts_results(self, mock_google_search_cls, monkeypatch):
        monkeypatch.setattr(settings, "SERP_API_KEY", "dummy_key")
        monkeypatch.setattr(settings, "SERP_TIMEOUT", 5)

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
                    "link": "https://translate.google.com/translate?u=https%3A%2F%2Fmediamart.vn%2Fmay-giat",
                },
            ]
        }

        results = _search_via_serpapi("Máy giặt Panasonic", limit=5)

        # Check timeout setting
        assert mock_search_instance.timeout == 5
        # Check unwrapping and source assignment
        assert len(results) == 2
        assert results[0]["url"] == "https://dienmayxanh.com/may-giat-panasonic"
        assert results[0]["source"] == "google"
        assert results[1]["url"] == "https://mediamart.vn/may-giat"
        assert results[1]["source"] == "google"

    @patch("serpapi.GoogleSearch")
    def test_filters_blocked_and_translate_domains(self, mock_google_search_cls, monkeypatch):
        monkeypatch.setattr(settings, "SERP_API_KEY", "dummy_key")
        mock_search_instance = MagicMock()
        mock_google_search_cls.return_value = mock_search_instance
        mock_search_instance.get_dict.return_value = {
            "organic_results": [
                {
                    "title": "Facebook Group",
                    "link": "https://facebook.com/group/123",
                },
                {
                    "title": "Pure Translate Domain",
                    "link": "https://translate.google.com/m?sl=auto",
                },
                {
                    "title": "Good Site",
                    "link": "https://websosanh.vn/may-giat.htm",
                },
            ]
        }

        results = _search_via_serpapi("Máy giặt", limit=5)
        assert len(results) == 1
        assert results[0]["url"] == "https://websosanh.vn/may-giat.htm"

    @patch("serpapi.GoogleSearch")
    def test_handles_timeout_exception_gracefully(self, mock_google_search_cls, monkeypatch):
        monkeypatch.setattr(settings, "SERP_API_KEY", "dummy_key")
        mock_search_instance = MagicMock()
        mock_google_search_cls.return_value = mock_search_instance
        # Simulate timeout error
        mock_search_instance.get_dict.side_effect = TimeoutError("Request timed out after 5.0 seconds")

        results = _search_via_serpapi("Máy giặt Panasonic", limit=5, timeout=5)
        # Should gracefully return empty list, not crash
        assert results == []

    @patch("serpapi.GoogleSearch")
    def test_custom_timeout_override(self, mock_google_search_cls, monkeypatch):
        monkeypatch.setattr(settings, "SERP_API_KEY", "dummy_key")
        mock_search_instance = MagicMock()
        mock_google_search_cls.return_value = mock_search_instance
        mock_search_instance.get_dict.return_value = {"organic_results": []}

        _search_via_serpapi("Test", limit=2, timeout=10)
        assert mock_search_instance.timeout == 10


# ==============================================================================
# 3. Tests for search_articles
# ==============================================================================
class TestSearchArticles:
    @patch("core.searcher._search_via_duckduckgo")
    @patch("core.searcher._search_via_serpapi")
    def test_concurrent_search_uses_serp_first_and_fills_with_ddg(
        self, mock_serp, mock_ddg, monkeypatch
    ):
        monkeypatch.setattr(settings, "SERP_API_KEY", "test_key")
        monkeypatch.setattr(settings, "SEARCH_RESULT_COUNT", 4)

        mock_serp.return_value = [
            {"url": "https://serp1.com", "title": "Serp 1", "source": "google"},
            {"url": "https://serp2.com", "title": "Serp 2", "source": "google"},
        ]
        mock_ddg.return_value = [
            {"url": "https://serp1.com", "title": "Serp 1 Duplicate", "source": "duckduckgo"},
            {"url": "https://ddg1.com", "title": "DDG 1", "source": "duckduckgo"},
            {"url": "https://ddg2.com", "title": "DDG 2", "source": "duckduckgo"},
        ]

        results = search_articles("Máy bơm nước")

        # Limit is 4: serp1, serp2, ddg1, ddg2
        assert len(results) == 4
        urls = [r["url"] for r in results]
        assert urls == ["https://serp1.com", "https://serp2.com", "https://ddg1.com", "https://ddg2.com"]

    @patch("core.searcher._search_via_duckduckgo")
    @patch("core.searcher._search_via_serpapi")
    def test_fallback_to_duckduckgo_when_serpapi_times_out(
        self, mock_serp, mock_ddg, monkeypatch
    ):
        monkeypatch.setattr(settings, "SERP_API_KEY", "test_key")
        monkeypatch.setattr(settings, "SEARCH_RESULT_COUNT", 3)

        # SerpAPI times out and returns empty list
        mock_serp.return_value = []
        mock_ddg.return_value = [
            {"url": "https://ddg1.com", "title": "DDG 1", "source": "duckduckgo"},
            {"url": "https://ddg2.com", "title": "DDG 2", "source": "duckduckgo"},
        ]

        results = search_articles("Quạt trần")

        assert len(results) == 2
        assert results[0]["source"] == "duckduckgo"
        assert results[1]["source"] == "duckduckgo"

    @patch("core.searcher._search_via_duckduckgo")
    @patch("core.searcher._search_via_serpapi")
    def test_no_serp_key_calls_ddg_directly(self, mock_serp, mock_ddg, monkeypatch):
        monkeypatch.setattr(settings, "SERP_API_KEY", "")
        monkeypatch.setattr(settings, "SEARCH_RESULT_COUNT", 3)

        mock_ddg.return_value = [
            {"url": "https://ddg1.com", "title": "DDG 1", "source": "duckduckgo"}
        ]

        results = search_articles("Đèn led")

        mock_serp.assert_not_called()
        mock_ddg.assert_called_once()
        assert len(results) == 1
        assert results[0]["url"] == "https://ddg1.com"

    @patch("core.searcher._search_via_duckduckgo")
    @patch("core.searcher._search_via_serpapi")
    def test_manual_extra_urls_prioritized_and_deduplicated(
        self, mock_serp, mock_ddg, monkeypatch
    ):
        monkeypatch.setattr(settings, "SERP_API_KEY", "test_key")
        monkeypatch.setattr(settings, "SEARCH_RESULT_COUNT", 3)

        extra = ["https://manual-source.com/spec", "https://serp1.com"]
        mock_serp.return_value = [
            {"url": "https://serp1.com", "title": "Serp 1", "source": "google"},
            {"url": "https://serp2.com", "title": "Serp 2", "source": "google"},
        ]
        mock_ddg.return_value = []

        results = search_articles("Tủ lạnh", extra_urls=extra)

        # Extra URLs are prioritized first (manual)
        assert results[0]["url"] == "https://manual-source.com/spec"
        assert results[0]["source"] == "manual"
        assert results[1]["url"] == "https://serp1.com"
        assert results[1]["source"] == "manual"
        # Serp2 fills the remaining slot
        assert results[2]["url"] == "https://serp2.com"
        assert results[2]["source"] == "google"
        assert len(results) == 3
