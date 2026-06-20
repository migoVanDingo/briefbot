"""Anthropic (Claude Haiku) text generation for bbv2.

Adapted from the original briefbot's `llm.py`, trimmed to Anthropic-only and
wired to bbv2 config (Haiku by default — cost). The network call is isolated
here so brief-building stays testable with an injected generator.
"""

from __future__ import annotations

import json
import re
from typing import Any

import requests

from . import config

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"


class LLMError(RuntimeError):
    pass


def generate_text(
    prompt: str,
    *,
    max_tokens: int = 900,
    temperature: float = 0.2,
    model: str | None = None,
    timeout: int = 60,
) -> str:
    """Single-turn completion via the Anthropic Messages API (Haiku by default)."""
    api_key = config.anthropic_api_key()
    if not api_key:
        raise LLMError("ANTHROPIC_API_KEY not set")
    model = model or config.anthropic_model()
    resp = requests.post(
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
    if resp.status_code >= 400:
        raise LLMError(f"Anthropic HTTP {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
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
    resp = requests.post(
        ANTHROPIC_URL,
        timeout=timeout,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json=payload,
    )
    if resp.status_code >= 400:
        raise LLMError(f"Anthropic HTTP {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    return {"content": data.get("content") or [], "stop_reason": data.get("stop_reason")}


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
