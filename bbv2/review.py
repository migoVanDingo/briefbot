"""Post-collect relevance quickscan.

After collect, each topic has freshly-mapped items with `relevant IS NULL`. This
batches those pending items (~20 at a time) to Haiku, which decides — from title
+ blurb — whether each is genuinely about the topic, and writes the verdict back
to `item_topics.relevant` (1 keep / 0 drop). Display queries hide `relevant = 0`.

The generator is injectable so this is offline-testable.
"""

from __future__ import annotations

from typing import Callable

from .relevance import classify_batch
from .store import Store


def quickscan_topic(
    store: Store,
    topic_slug: str,
    *,
    generate: Callable[..., str] | None = None,
    batch_size: int = 20,
) -> dict[str, int]:
    topic = store.get_topic(topic_slug)
    if not topic:
        return {"reviewed": 0, "kept": 0, "dropped": 0}
    tid = int(topic["id"])
    pending = store.pending_relevance(topic_slug)
    reviewed = kept = dropped = 0
    for i in range(0, len(pending), batch_size):
        batch = pending[i : i + batch_size]
        items = [
            {"item_id": r["item_id"], "title": r["title"], "summary": r["summary"]}
            for r in batch
        ]
        verdicts = classify_batch(
            topic["name"], topic["description"] or "", items, generate
        )
        for r in batch:
            verdict = verdicts.get(str(r["item_id"]))
            if verdict is None:
                continue  # LLM skipped it → leave pending for next time
            store.set_item_relevance(r["item_id"], tid, 1 if verdict else 0)
            reviewed += 1
            if verdict:
                kept += 1
            else:
                dropped += 1
    return {"reviewed": reviewed, "kept": kept, "dropped": dropped}
