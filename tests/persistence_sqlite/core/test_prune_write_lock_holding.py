"""A bulk prune must not run as ONE write transaction.

On a multi-GB store the single ``BEGIN IMMEDIATE`` that covered every chunk
held the WAL write lock for minutes. Every other opener waited behind it: the
Desktop's backend could not open ``state.db``, so its gateway-ticket mint and
API calls timed out while the sweep ran. The sweep is now one transaction per
chunk, so the lock is released between chunks.
"""

import pytest

from persistence.sqlite._holder import StoreHolder
from persistence.sqlite.conversation._store.sessions import create_session, end_session, get_session
from persistence.sqlite.housekeeping import maintenance


@pytest.fixture
def store(backend, scope_a):
    return backend.open(scope_a)


@pytest.fixture
def db(store):
    """The store's StoreHolder, shared with its repositories."""
    return store.holder()


@pytest.fixture
def media_root(tmp_path):
    return str(tmp_path / "media")


@pytest.fixture
def small_chunks(monkeypatch):
    """Two ids per chunk: the sweep's shape is what matters, not its size."""
    monkeypatch.setattr(
        maintenance, "_id_chunks",
        lambda ids: [list(ids)[i:i + 2] for i in range(0, len(list(ids)), 2)],
    )


def _seed_ended_sessions(db, count):
    ids = []
    for index in range(count):
        session_id = f"prune-bulk-{index:04d}"
        create_session(db, session_id, source="cron")
        end_session(db, session_id, end_reason="completed")
        ids.append(session_id)
    return ids


def test_prune_deletes_every_candidate_session(db, store, media_root, small_chunks):
    ids = _seed_ended_sessions(db, 5)

    result = store.maintenance.prune_sessions(older_than_days=0, source="cron", media_root=media_root)

    assert result.count == 5
    for session_id in ids:
        assert get_session(db, session_id) is None


def test_prune_splits_the_sweep_into_several_write_transactions(db, store, media_root, small_chunks, monkeypatch):
    """One transaction per chunk, not one for the whole sweep: the lock must
    come back to other writers between chunks."""
    _seed_ended_sessions(db, 5)

    transactions = []
    original = StoreHolder._execute_write

    def _counting_write(self, fn, patience_s=None):
        transactions.append(fn)
        return original(self, fn, patience_s)

    monkeypatch.setattr(StoreHolder, "_execute_write", _counting_write)
    store.maintenance.prune_sessions(older_than_days=0, source="cron", media_root=media_root)

    # The selection sweep, one transaction per chunk, and the cleanup pass: the
    # delete work is spread over several BEGIN IMMEDIATE windows.
    assert len(transactions) >= 4


def test_prune_skips_a_session_a_turn_started_mid_sweep(db, store, media_root, small_chunks, monkeypatch):
    """The write guard is re-checked per chunk now that the lock is not held
    across the sweep: a session that gained a live turn mid-sweep survives."""
    ids = _seed_ended_sessions(db, 5)
    target = "prune-bulk-0000"

    guard_calls = {"n": 0}

    def _guard_after_selection(holder, conn, candidates):
        # The selection sweep asks once; the per-chunk re-check asks again. Guard
        # only from the second ask on, so the session is selected and then spared
        # by the chunk-time re-check.
        guard_calls["n"] += 1
        return {target} if guard_calls["n"] > 1 else set()

    monkeypatch.setattr(maintenance, "_guarded_ids", _guard_after_selection)
    store.maintenance.prune_sessions(
        older_than_days=0, source="cron", exclude_active_write_guards=True, media_root=media_root,
    )

    assert get_session(db, target) is not None
    for session_id in ids:
        if session_id != target:
            assert get_session(db, session_id) is None
