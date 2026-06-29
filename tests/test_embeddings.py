"""Topic embedding index — math, store, generation, routing (0030). Offline."""

from bbv2 import embeddings as emb
from bbv2 import topic_index
from bbv2.embeddings import EmbedResult
from bbv2.store import Store
from bbv2.usage import estimate_cost

# Deterministic bag-of-words "embedder" so cosine ranking is predictable offline.
_VOCAB = ["ai", "model", "gun", "firearm", "education", "learning", "student"]


def fake_embedder(texts):
    vecs = []
    for t in texts:
        tl = (t or "").lower()
        v = [float(tl.count(w)) for w in _VOCAB]
        if not any(v):
            v[0] = 1.0  # avoid a degenerate zero vector
        vecs.append(v)
    return EmbedResult(vecs, tokens=len(texts), model="fake-embed")


# ---- vector math ----

def test_cosine_and_centroid():
    assert emb.cosine([1, 0, 0], [1, 0, 0]) == 1.0
    assert emb.cosine([1, 0, 0], [0, 1, 0]) == 0.0
    assert emb.cosine([], [1]) == 0.0
    assert emb.centroid([[2, 0], [0, 2]]) == [1.0, 1.0]
    assert emb.centroid([]) is None


def test_pack_unpack_roundtrip():
    v = [0.1, -0.5, 1.25, 0.0]
    out = emb.unpack_vector(emb.pack_vector(v))
    assert all(abs(a - b) < 1e-6 for a, b in zip(v, out))
    assert len(out) == len(v)


def test_estimate_cost_embedding_branch(monkeypatch):
    monkeypatch.setenv("OPENAI_EMBED_PRICE", "0.02")
    # 1M embedding tokens → $0.02, NOT the ~$1 a haiku-family mistake would give.
    assert abs(estimate_cost("text-embedding-3-small", 1_000_000, 0) - 0.02) < 1e-9


# ---- store + generation ----

def _seed(store):
    tid_ai = store.add_topic("ai", "AI", "ai and model research")
    tid_gun = store.add_topic("firearms", "Firearms", "gun and firearm news")
    tid_edu = store.add_topic("edu", "Educational Research", "learning and student education")
    return tid_ai, tid_gun, tid_edu


def test_meta_floor_and_missing_queries():
    store = Store(":memory:")
    _seed(store)
    assert len(store.topics_missing_meta_embedding()) == 3
    n = topic_index.ensure_meta_embeddings(store, embedder=fake_embedder)
    assert n == 3
    assert store.topics_missing_meta_embedding() == []  # all have a meta vector now
    assert store.topic_meta_vector(1) is not None


def test_embed_pending_briefs_then_centroid_uses_briefs():
    store = Store(":memory:")
    tid_ai, _, _ = _seed(store)
    topic_index.ensure_meta_embeddings(store, embedder=fake_embedder)
    # a brief for AI emphasizing 'model' — centroid should now lean on the brief
    store.upsert_brief({
        "id": "BRF1", "topic_id": tid_ai, "date": "2030-06-01", "title": "t",
        "summary": "model model model architecture", "trending": [], "sources": [],
        "model": "x",
    })
    assert len(store.briefs_missing_embedding("2000-01-01")) == 1
    done = topic_index.embed_pending_briefs(store, days=36500, embedder=fake_embedder)
    assert done == 1
    assert store.briefs_missing_embedding("2000-01-01") == []  # idempotent now
    c = store.topic_centroid(tid_ai, days=36500)
    assert c is not None


def test_rank_topics_routes_by_cosine(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")  # enable routing; fake avoids network
    store = Store(":memory:")
    _seed(store)
    topic_index.ensure_meta_embeddings(store, embedder=fake_embedder)
    ranked = topic_index.rank_topics(
        store, "multimodal learning for K-12 students education", embedder=fake_embedder
    )
    assert ranked, "expected ranked topics"
    assert ranked[0]["slug"] == "edu"  # the education query routes to Educational Research
    # firearms should rank dead last (no overlap)
    assert ranked[-1]["slug"] == "firearms"
    assert ranked[0]["score"] > ranked[-1]["score"]


def test_rank_topics_disabled_without_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    store = Store(":memory:")
    _seed(store)
    assert topic_index.rank_topics(store, "anything", embedder=fake_embedder) == []
