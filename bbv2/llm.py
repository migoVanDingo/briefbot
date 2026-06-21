"""Anthropic (Claude Haiku) text generation for bbv2.

Adapted from the original briefbot's `llm.py`, trimmed to Anthropic-only and
wired to bbv2 config (Haiku by default — cost). The network call is isolated
here so brief-building stays testable with an injected generator.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable

import requests

from . import config
from .httpclient import request_with_backoff

# Called with (usage_dict, model) after a successful call, when provided. The
# usage_dict is Anthropic's `usage` block (input_tokens/output_tokens). Lets
# callers meter token spend per user without this module knowing about the DB.
UsageHook = Callable[[dict[str, Any], str], None]

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
GROK_URL = "https://api.x.ai/v1/chat/completions"


class LLMError(RuntimeError):
    pass


def _request(do_request: Callable[[], requests.Response]) -> requests.Response:
    """Run a request through backoff, converting an exhausted connection error
    into LLMError so callers only ever have to catch LLMError (a raw
    RequestException would otherwise escape into the agent/SSE path as a 500)."""
    try:
        return request_with_backoff(do_request)
    except requests.RequestException as exc:
        raise LLMError(f"LLM request failed: {exc}") from exc


def grok_text(
    prompt: str,
    *,
    max_tokens: int = 900,
    temperature: float = 0.2,
    model: str | None = None,
    timeout: int = 60,
    on_usage: UsageHook | None = None,
) -> str:
    """Single-turn completion via xAI Grok (OpenAI-compatible Chat Completions).

    Usage is normalized to Anthropic's shape (`input_tokens`/`output_tokens`) so
    metering is provider-agnostic."""
    api_key = config.grok_api_key()
    if not api_key:
        raise LLMError("GROK_API_KEY not set")
    model = model or config.grok_model()
    resp = _request(
        lambda: requests.post(
            GROK_URL,
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {api_key}",
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": [{"role": "user", "content": prompt}],
            },
        )
    )
    if resp.status_code >= 400:
        raise LLMError(f"Grok HTTP {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    choices = data.get("choices") or []
    text = (choices[0].get("message", {}).get("content", "") if choices else "").strip()
    if not text:
        raise LLMError("Grok returned empty content")
    if on_usage and isinstance(data.get("usage"), dict):
        u = data["usage"]
        on_usage(
            {
                "input_tokens": u.get("prompt_tokens", 0),
                "output_tokens": u.get("completion_tokens", 0),
            },
            model,
        )
    return text


def generate_text(
    prompt: str,
    *,
    max_tokens: int = 900,
    temperature: float = 0.2,
    model: str | None = None,
    timeout: int = 60,
    on_usage: UsageHook | None = None,
) -> str:
    """Single-turn completion via the Anthropic Messages API (Haiku by default)."""
    api_key = config.anthropic_api_key()
    if not api_key:
        raise LLMError("ANTHROPIC_API_KEY not set")
    model = model or config.anthropic_model()
    resp = _request(
        lambda: requests.post(
            ANTHROPIC_URL,
            timeout=timeout,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": [{"role": "user", "content": prompt}],
            },
        )
    )
    if resp.status_code >= 400:
        raise LLMError(f"Anthropic HTTP {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    if on_usage and isinstance(data.get("usage"), dict):
        on_usage(data["usage"], model)
    parts = [c.get("text", "") for c in (data.get("content") or []) if isinstance(c, dict)]
    text = "\n".join(p for p in parts if p).strip()
    if not text:
        raise LLMError("Anthropic returned empty content")
    return text


def anthropic_messages(
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None = None,
    system: str | None = None,
    max_tokens: int = 1500,
    temperature: float = 0.3,
    model: str | None = None,
    timeout: int = 60,
) -> dict[str, Any]:
    """Multi-turn Messages call (with optional tools). Returns the raw content
    blocks + stop_reason so the agent loop can drive tool use."""
    api_key = config.anthropic_api_key()
    if not api_key:
        raise LLMError("ANTHROPIC_API_KEY not set")
    payload: dict[str, Any] = {
        "model": model or config.anthropic_model(),
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": messages,
    }
    if system:
        payload["system"] = system
    if tools:
        payload["tools"] = tools
    resp = _request(
        lambda: requests.post(
            ANTHROPIC_URL,
            timeout=timeout,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=payload,
        )
    )
    if resp.status_code >= 400:
        raise LLMError(f"Anthropic HTTP {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    return {
        "content": data.get("content") or [],
        "stop_reason": data.get("stop_reason"),
        "usage": data.get("usage") if isinstance(data.get("usage"), dict) else None,
        "model": payload["model"],
    }


def extract_json(text: str) -> dict[str, Any]:
    """Tolerant JSON extraction from an LLM response (handles ``` fences)."""
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        match = re.search(r"\{.*\}", raw, re.S)
        if not match:
            return {}
        try:
            data = json.loads(match.group(0))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
