from datetime import datetime, timedelta, timezone

from bbv2.score import compute_score


def _iso(hours_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


def test_recency_decays():
    fresh = compute_score({"published_at": _iso(0)})
    recent = compute_score({"published_at": _iso(48)})
    ancient = compute_score({"published_at": _iso(1000)})
    assert fresh > recent > ancient


def test_source_weight_scales():
    base = compute_score({"published_at": _iso(0)}, source_weight=1.0)
    heavy = compute_score({"published_at": _iso(0)}, source_weight=2.0)
    assert heavy > base


def test_missing_timestamp_is_nonnegative():
    assert compute_score({}) >= 0.0
