"""Per-task model routing.

bbv2 uses Anthropic Haiku for user-facing prose (chat, briefs, rundowns) but
routes the **highest-volume, lowest-stakes** call — story relevance classification
— to a **cheaper model (xAI Grok)** when configured, to keep the bill down. Grok
work falls back to Haiku on any error so collection never breaks.

`relevance_generate` returns a `generate(prompt, **kw) -> str` drop-in that
`relevance.classify_batch` / `review.quickscan_topic` already accept.
"""

from __future__ import annotations

from typing import Any, Callable

from . import config
from .llm import LLMError, UsageHook, generate_text, grok_text


def relevance_generate(on_usage: UsageHook | None = None) -> Callable[..., str]:
    """Relevance classifier: cheap Grok when configured, Haiku fallback on error."""
    provider = config.relevance_provider()

    def _generate(prompt: str, **kwargs: Any) -> str:
        if provider == "grok" and config.grok_api_key():
            try:
                return grok_text(prompt, on_usage=on_usage, **kwargs)
            except LLMError:
                pass  # fall back to Haiku below — collection must not break
        return generate_text(prompt, on_usage=on_usage, **kwargs)

    return _generate
