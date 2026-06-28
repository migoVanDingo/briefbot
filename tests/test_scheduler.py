"""The `bbv2 tick` engine — due-based discovery + collection + quickscan."""

from datetime import datetime, timezone

from bbv2.scheduler import tick
from bbv2.store import Store


def _seed(store: Store) -> tuple[int, int]:
    tid = store.add_topic("crypto", "Crypto")
    sid = store.add_source("rss", "https://x/feed", "X")
    store.link_topic_source(tid, sid)
    return tid, sid


def _stub_collect(touched_tid):
    def _collect_one(store, row, session, timeout, stats):
        stats["sources"] += 1
        stats["new"] += 1
        return {touched_tid}

    return _collect_one


def test_tick_runs_due_work_and_quickscans_touched(monkeypatch):
    store = Store(":memory:")
    tid, sid = _seed(store)
    discovered = []
    reviewed = []

    def fake_discover(store, slug):
        discovered.append(slug)

    monkeypatch.setattr(
        "bbv2.review.quickscan_topic",
        lambda store, slug, **kw: reviewed.append(slug) or {"reviewed": 0},
    )

    stats = tick(
        store,
        discover_fn=fake_discover,
        collect_one=_stub_collect(tid),
        relevance_generate=lambda *a, **k: "{}",
    )

    assert discovered == ["crypto"]  # never discovered → due
    assert stats["new"] == 1
    assert reviewed == ["crypto"]  # touched topic got quickscanned
    # checkpoints advanced
    src = store.sources_for_scheduler()[0]
    assert src["last_collected_at"] is not None


def test_tick_skips_when_not_due(monkeypatch):
    store = Store(":memory:")
    tid, sid = _seed(store)
    now = datetime(2026, 6, 20, 12, 0, tzinfo=timezone.utc)
    # Collected 10 min ago, daily interval → not due.
    store.set_source_cadence(sid, 1440)
    store.set_source_collected(sid, "2026-06-20T11:50:00+00:00")
    store.set_topic_cadence("crypto", discover_interval_min=10080)
    store.set_topic_discovered("crypto", "2026-06-20T11:50:00+00:00")

    called = []
    stats = tick(
        store,
        now=now,
        discover_fn=lambda s, slug: called.append(slug),
        collect_one=_stub_collect(tid),
        relevance_generate=lambda *a, **k: "{}",
    )
    assert called == []  # discovery not due
    assert stats["sources"] == 0  # collection not due


def test_daily_discovery_fires_once_in_window(monkeypatch):
    store = Store(":memory:")
    store.add_topic("tech", "Tech")
    # run every day @ 02:00 UTC, starting 2026-06-22 (15-min window)
    store.set_topic_schedule(
        "tech", discover_period="day", discover_start_date="2026-06-22", discover_at_min=120
    )
    monkeypatch.setattr(
        "bbv2.review.quickscan_topic", lambda store, slug, **kw: {"reviewed": 0}
    )
    runs = []
    kw = dict(
        collect_one=lambda s, r, sess, to, st: set(),
        relevance_generate=lambda *a, **k: "{}",
        discover_fn=lambda s, slug: runs.append(slug),
    )

    # 01:50 → before the slot, not due
    tick(store, now=datetime(2026, 6, 22, 1, 50, tzinfo=timezone.utc), **kw)
    assert runs == []
    # 02:05 → inside [120,135) slot → fires
    tick(store, now=datetime(2026, 6, 22, 2, 5, tzinfo=timezone.utc), **kw)
    assert runs == ["tech"]
    # 02:10 same day → already ran today → does not refire
    tick(store, now=datetime(2026, 6, 22, 2, 10, tzinfo=timezone.utc), **kw)
    assert runs == ["tech"]
    # next day in-slot → fires again
    tick(store, now=datetime(2026, 6, 23, 2, 5, tzinfo=timezone.utc), **kw)
    assert runs == ["tech", "tech"]


def test_per_topic_story_cap_resolves():
    store = Store(":memory:")
    tid = store.add_topic("crypto", "Crypto")
    sid = store.add_source("rss", "https://x/feed", "X")
    store.link_topic_source(tid, sid)
    # no cap set → None (caller uses env default)
    assert store.source_max_stories(sid) is None
    store.set_topic_schedule("crypto", max_stories_per_source=20)
    assert store.source_max_stories(sid) == 20
    # scheduler row exposes it precomputed
    assert store.sources_for_scheduler()[0]["eff_max_stories"] == 20


def test_weekly_discovery_anchors_to_start_weekday(monkeypatch):
    store = Store(":memory:")
    store.add_topic("tech", "Tech")
    # 2026-06-22 is a Monday → "every week" should run on Mondays.
    store.set_topic_schedule(
        "tech", discover_period="week", discover_start_date="2026-06-22", discover_at_min=120
    )
    monkeypatch.setattr("bbv2.review.quickscan_topic", lambda s, slug, **kw: {"reviewed": 0})
    runs = []
    kw = dict(
        collect_one=lambda s, r, sess, to, st: set(),
        relevance_generate=lambda *a, **k: "{}",
        discover_fn=lambda s, slug: runs.append(slug),
    )
    # Tuesday in-slot → not the anchored weekday → no run
    tick(store, now=datetime(2026, 6, 23, 2, 5, tzinfo=timezone.utc), **kw)
    assert runs == []
    # The following Monday in-slot → runs
    tick(store, now=datetime(2026, 6, 29, 2, 5, tzinfo=timezone.utc), **kw)
    assert runs == ["tech"]


def test_discovery_not_due_before_start_date(monkeypatch):
    store = Store(":memory:")
    store.add_topic("tech", "Tech")
    store.set_topic_schedule(
        "tech", discover_period="day", discover_start_date="2026-07-01", discover_at_min=0
    )
    monkeypatch.setattr("bbv2.review.quickscan_topic", lambda s, slug, **kw: {"reviewed": 0})
    runs = []
    tick(
        store,
        now=datetime(2026, 6, 25, 0, 5, tzinfo=timezone.utc),  # before start
        collect_one=lambda s, r, sess, to, st: set(),
        relevance_generate=lambda *a, **k: "{}",
        discover_fn=lambda s, slug: runs.append(slug),
    )
    assert runs == []
