"""Text embeddings for the topic embedding index + evidence-based routing (0030).

OpenAI `text-embedding-3-small` over plain HTTP (no SDK), mirroring `llm.py`. The
network call is injectable so routing/placement stays testable offline with a fake
embedder. Vectors are stored in SQLite (packed float32) and compared with a
pure-Python cosine — no vector DB / numpy at this scale.
"""

from __future__ import annotations

import logging
import math
import struct
from typing import Callable

import requests

from . import config
from .httpclient import request_with_backoff
from .llm import LLMError

log = logging.getLogger("bbv2.embeddings")

# (vectors, total_tokens). Same injectable shape used everywhere a fake is needed.
Embedder = Callable[[list[str]], "EmbedResult"]


class EmbedResult:
    __slots__ = ("vectors", "tokens", "model")

    def __init__(self, vectors: list[list[float]], tokens: int, model: str) -> None:
        self.vectors = vectors
        self.tokens = tokens
        self.model = model


def embed_texts(
    texts: list[str], *, model: str | None = None, timeout: int = 30
) -> EmbedResult:
    """Embed a batch of texts via OpenAI. Returns vectors + token count + model.
    Raises LLMError on any failure (callers treat embeddings as best-effort)."""
    if not texts:
        return EmbedResult([], 0, model or config.openai_embed_model())
    api_key = config.openai_api_key()
    if not api_key:
        raise LLMError("OPENAI_API_KEY not set")
    model = model or config.openai_embed_model()
    # OpenAI rejects empty strings; coerce to a single space so indexes stay aligned.
    inputs = [t if (t or "").strip() else " " for t in texts]
    try:
        resp = request_with_backoff(
            lambda: requests.post(
                config.OPENAI_EMBED_URL,
                timeout=timeout,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "content-type": "application/json",
                },
                json={"model": model, "input": inputs},
            )
        )
    except requests.RequestException as exc:
        raise LLMError(f"OpenAI embeddings request failed: {exc}") from exc
    if resp.status_code >= 400:
        raise LLMError(f"OpenAI embeddings HTTP {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    rows = sorted(data.get("data") or [], key=lambda d: d.get("index", 0))
    vectors = [list(r.get("embedding") or []) for r in rows]
    tokens = int((data.get("usage") or {}).get("total_tokens") or 0)
    if len(vectors) != len(texts) or any(not v for v in vectors):
        raise LLMError("OpenAI embeddings returned an unexpected shape")
    log.debug("embedded %d text(s) model=%s tokens=%d", len(texts), model, tokens)
    return EmbedResult(vectors, tokens, model)


# ---- vector (de)serialization + math ----

def pack_vector(vec: list[float]) -> bytes:
    """Pack a vector as little-endian float32 bytes for compact BLOB storage."""
    return struct.pack(f"<{len(vec)}f", *vec)


def unpack_vector(blob: bytes) -> list[float]:
    return list(struct.unpack(f"<{len(blob) // 4}f", blob))


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity of two equal-length vectors; 0.0 if either is degenerate."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = math.fsum(x * y for x, y in zip(a, b))
    na = math.sqrt(math.fsum(x * x for x in a))
    nb = math.sqrt(math.fsum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def centroid(vectors: list[list[float]]) -> list[float] | None:
    """Mean vector of a non-empty list (all same length); None if empty."""
    vectors = [v for v in vectors if v]
    if not vectors:
        return None
    dim = len(vectors[0])
    out = [0.0] * dim
    for v in vectors:
        if len(v) != dim:
            continue
        for i, x in enumerate(v):
            out[i] += x
    n = float(len(vectors))
    return [x / n for x in out]


def default_embedder(on_usage: Callable[[int, str], None] | None = None) -> Embedder:
    """A real embedder bound to OpenAI; `on_usage(tokens, model)` meters spend."""

    def _embed(texts: list[str]) -> EmbedResult:
        res = embed_texts(texts)
        if on_usage and res.tokens:
            on_usage(res.tokens, res.model)
        return res

    return _embed
