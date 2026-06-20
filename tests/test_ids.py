from bbv2 import ids
from bbv2.ids import new_id, ulid


def test_ulid_shape_and_charset():
    value = ulid()
    assert len(value) == 26
    assert set(value) <= set("0123456789ABCDEFGHJKMNPQRSTVWXYZ")  # Crockford, no I/L/O/U


def test_new_id_carries_prefix():
    assert new_id(ids.SOURCE).startswith("SRC")
    assert new_id(ids.TOPIC).startswith("TOP")
    assert new_id(ids.ITEM).startswith("ITM")
    assert len(new_id(ids.SOURCE)) == 3 + 26


def test_ids_are_unique():
    assert len({new_id(ids.ITEM) for _ in range(1000)}) == 1000


def test_ulids_sort_by_time():
    # The timestamp lives in the high-order chars, so a newer ms sorts after an
    # older one regardless of the random suffix.
    earlier = ulid(now_ms=1_000_000)
    later = ulid(now_ms=2_000_000)
    assert earlier < later
