"""Per-task model routing — relevance uses Grok with a Haiku fallback."""

import bbv2.models as models
from bbv2.llm import LLMError


def test_relevance_uses_grok_when_configured(monkeypatch):
    monkeypatch.setattr(models.config, "relevance_provider", lambda: "grok")
    monkeypatch.setattr(models.config, "grok_api_key", lambda: "key")
    monkeypatch.setattr(models, "grok_text", lambda prompt, **kw: "grok-said")
    monkeypatch.setattr(models, "generate_text", lambda prompt, **kw: "haiku-said")

    gen = models.relevance_generate()
    assert gen("classify these", max_tokens=300) == "grok-said"


def test_relevance_falls_back_to_haiku_on_grok_error(monkeypatch):
    monkeypatch.setattr(models.config, "relevance_provider", lambda: "grok")
    monkeypatch.setattr(models.config, "grok_api_key", lambda: "key")

    def _boom(prompt, **kw):
        raise LLMError("Grok HTTP 503")

    monkeypatch.setattr(models, "grok_text", _boom)
    monkeypatch.setattr(models, "generate_text", lambda prompt, **kw: "haiku-said")

    gen = models.relevance_generate()
    assert gen("classify these") == "haiku-said"


def test_relevance_uses_anthropic_when_selected(monkeypatch):
    monkeypatch.setattr(models.config, "relevance_provider", lambda: "anthropic")
    monkeypatch.setattr(models, "grok_text", lambda *a, **k: "grok-said")
    monkeypatch.setattr(models, "generate_text", lambda prompt, **kw: "haiku-said")

    gen = models.relevance_generate()
    assert gen("classify these") == "haiku-said"
