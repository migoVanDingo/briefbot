"""Auto-drop dead/blocked feeds after a streak of droppable 4xx failures (0029)."""

import requests

from bbv2 import collect as collect_mod
from bbv2.fetch import FetchError
from bbv2.store import Store


def _seed(store: Store) -> int:
    tid = store.add_topic("crypto", "Crypto")
    sid = store.add_source("rss", "https://dead/feed", "Dead")
    store.link_topic_source(tid, sid)
    return sid


def _src(store: Store, sid: int):
    return store.conn.execute("SELECT * FROM sources WHERE id = ?", (sid,)).fetchone()


def _collect_once(store: Store, monkeypatch, *, status_code=None, ok=False):
    if ok:
        def fn(*a, **k):
            return [], "not_modified"
    else:
        def fn(*a, **k):
            raise FetchError(f"Feed HTTP {status_code}: x", status_code=status_code, url="x")
    monkeypatch.setattr(collect_mod, "fetch_rss_feed", fn)
    row = store.list_sources("crypto")[0]
    collect_mod.collect_source(store, row, requests.Session(), 10, collect_mod._empty_stats())


def test_disabled_after_three_consecutive_404s(monkeypatch):
    monkeypatch.setenv("BBV2_SOURCE_DROP_THRESHOLD", "3")  # pin (don't inherit .env)
    store = Store(":memory:")
    sid = _seed(store)
    for i in range(2):  # below threshold → still active, streak grows
        _collect_once(store, monkeypatch, status_code=404)
        assert _src(store, sid)["status"] == "active"
        assert _src(store, sid)["consecutive_failures"] == i + 1
    _collect_once(store, monkeypatch, status_code=404)  # 3rd → disabled
    assert _src(store, sid)["status"] == "disabled"
    assert _src(store, sid)["last_error"] == "HTTP 404"


def test_success_resets_the_streak(monkeypatch):
    monkeypatch.setenv("BBV2_SOURCE_DROP_THRESHOLD", "3")
    store = Store(":memory:")
    sid = _seed(store)
    _collect_once(store, monkeypatch, status_code=403)
    _collect_once(store, monkeypatch, status_code=403)
    assert _src(store, sid)["consecutive_failures"] == 2
    _collect_once(store, monkeypatch, ok=True)  # a good fetch clears it
    assert _src(store, sid)["consecutive_failures"] == 0
    assert _src(store, sid)["status"] == "active"
    assert _src(store, sid)["last_error"] is None


def test_410_gone_disables_immediately(monkeypatch):
    store = Store(":memory:")
    sid = _seed(store)
    _collect_once(store, monkeypatch, status_code=410)
    assert _src(store, sid)["status"] == "disabled"
    assert _src(store, sid)["last_error"] == "HTTP 410"


def test_429_and_5xx_never_drop(monkeypatch):
    store = Store(":memory:")
    sid = _seed(store)
    for _ in range(5):
        _collect_once(store, monkeypatch, status_code=429)  # rate-limit: transient
        _collect_once(store, monkeypatch, status_code=503)  # server error: transient
    assert _src(store, sid)["status"] == "active"
    assert _src(store, sid)["consecutive_failures"] == 0


def test_threshold_zero_disables_autodrop(monkeypatch):
    monkeypatch.setenv("BBV2_SOURCE_DROP_THRESHOLD", "0")
    store = Store(":memory:")
    sid = _seed(store)
    for _ in range(5):
        _collect_once(store, monkeypatch, status_code=404)
    assert _src(store, sid)["status"] == "active"  # auto-drop disabled


def test_enable_resets_failures(monkeypatch):
    """Re-enabling an auto-dropped source clears the streak (store-level)."""
    store = Store(":memory:")
    sid = _seed(store)
    store.bump_source_failure(sid, "HTTP 404")
    store.disable_source(sid, "HTTP 404")
    store.set_source_status(sid, "active")
    store.clear_source_failures(sid)
    assert _src(store, sid)["consecutive_failures"] == 0
    assert _src(store, sid)["last_error"] is None
