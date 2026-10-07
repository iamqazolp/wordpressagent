"""core/ai_writer: Gemini client có timeout, được dùng lại, và báo lỗi rõ khi không có nội dung."""
import types as pytypes

import pytest

from config import settings
from core import ai_writer


def test_client_has_timeout_and_is_reused(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "k-test", raising=False)
    monkeypatch.setattr(settings, "GEMINI_BASE_URL", "", raising=False)
    monkeypatch.setattr(ai_writer, "_clients", {})
    c = ai_writer._get_client()
    assert c._api_client._http_options.timeout == ai_writer.GEMINI_TIMEOUT_MS
    assert ai_writer._get_client() is c
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "k-other", raising=False)
    assert ai_writer._get_client() is not c                    # đổi key trong .env -> client mới


def test_empty_response_raises_clear_error():
    blocked = pytypes.SimpleNamespace(text=None, candidates=[pytypes.SimpleNamespace(finish_reason="SAFETY")])
    with pytest.raises(RuntimeError, match="SAFETY"):
        ai_writer._response_text(blocked)
    assert ai_writer._response_text(pytypes.SimpleNamespace(text="<p>x</p>")) == "<p>x</p>"


def test_fill_template_keeps_css_braces_and_does_not_double_values():
    tpl = "<style>p{color:red}</style> {product_name} @ {site_name} {{literal}} {unknown}\n{reference_articles}"
    out = ai_writer.fill_template(tpl, product_name="Quạt", site_name="shop", reference_articles="json {a: 1}")
    assert out == "<style>p{color:red}</style> Quạt @ shop {literal} {unknown}\njson {a: 1}"
