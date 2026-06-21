"""Concurrent writes on a file-backed Store must not corrupt transactions.

Reproduces the production bug: a shared sqlite connection across threadpool
threads raised `OperationalError: cannot commit - no transaction is active` when
a long write stream (provision) overlapped with polling endpoints (which write via
the add_user upsert). Per-thread connections + WAL + busy_timeout fix it.
"""

import os
import tempfile
import threading

from bbv2.store import Store


def test_concurrent_writes_do_not_corrupt_transactions():
    path = os.path.join(tempfile.mkdtemp(), "concurrent.db")
    store = Store(path, check_same_thread=False)
    tid = store.add_topic("crypto", "Crypto")

    errors: list[str] = []

    def worker(n: int) -> None:
        try:
            for i in range(25):
                uid = store.add_user(f"u{n}-{i}", f"u{n}-{i}@x.com")  # upsert + commit
                store.record_usage(uid, "chat", "haiku", 10, 5)
                store.subscribe(uid, tid)
        except Exception as exc:  # noqa: BLE001
            errors.append(repr(exc))

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], errors
    # All writes landed.
    assert store.usage_window(2, "1970-01-01T00:00:00+00:00")["total_tokens"] >= 15
