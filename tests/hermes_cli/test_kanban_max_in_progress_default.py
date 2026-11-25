"""The derived ``kanban.max_in_progress`` default must never be unbounded.

macOS and Windows report no total memory to the Linux-only sampler, so the
memory-derived cap has no answer there. Returning "no cap" there made the
dispatcher fan out EVERY ready card at once: the owner's event loop
saturated, each worker's gateway WebSocket handshake then blew past its 10s
open timeout, every worker exited 1, and the cards tripped the failure
breaker instead of progressing.

These are behaviour contracts for the derived default, not source readers:
each pins what a host may and may not end up with.
"""

from hermes_cli import kanban_db_dispatch as _kbd


def test_unknown_memory_never_means_unbounded(monkeypatch):
    """The invariant: a host that reports no memory still gets a bounded cap."""
    monkeypatch.setattr(_kbd, "_system_memory_sample", dict, raising=False)
    monkeypatch.setattr(_kbd.os, "cpu_count", lambda: 16)

    cap = _kbd.derive_default_max_in_progress()

    assert cap is not None, "unknown memory must not disable the concurrency cap"
    assert _kbd.DERIVED_MAX_IN_PROGRESS_FLOOR <= cap <= _kbd.DERIVED_MAX_IN_PROGRESS_CEILING


def test_cpu_count_scales_the_cap_but_never_past_the_ceiling(monkeypatch):
    """More cores buy more workers — bounded by the ceiling, floored by the floor."""
    monkeypatch.setattr(_kbd, "_system_memory_sample", dict, raising=False)

    monkeypatch.setattr(_kbd.os, "cpu_count", lambda: 8)
    eight_cores = _kbd.derive_default_max_in_progress()

    monkeypatch.setattr(_kbd.os, "cpu_count", lambda: 64)
    sixty_four_cores = _kbd.derive_default_max_in_progress()

    assert eight_cores == max(
        _kbd.DERIVED_MAX_IN_PROGRESS_FLOOR,
        8 // _kbd.CPU_COUNT_MAX_IN_PROGRESS_DIVISOR,
    )
    assert sixty_four_cores == _kbd.DERIVED_MAX_IN_PROGRESS_CEILING


def test_known_memory_still_drives_the_cap(monkeypatch):
    """A host that does report memory keeps the memory-derived answer."""
    monkeypatch.setattr(_kbd.os, "cpu_count", lambda: 64)

    cap = _kbd.derive_default_max_in_progress({"mem_total_kib": 8 * 1024 * 1024})

    assert cap == _kbd.DERIVED_MAX_IN_PROGRESS_CEILING


def test_explicit_config_still_wins_over_both_derived_paths(monkeypatch):
    """``kanban.max_in_progress`` in config overrides every derived default."""
    monkeypatch.setattr(_kbd, "_system_memory_sample", dict, raising=False)
    monkeypatch.setattr(_kbd.os, "cpu_count", lambda: 64)

    assert _kbd.resolve_max_in_progress(3) == 3


def test_a_host_that_reports_neither_neither_dispatch_nor_caps(monkeypatch):
    """No memory AND no core count ⇒ no cap — but dispatch must not be bricked."""
    monkeypatch.setattr(_kbd, "_system_memory_sample", dict, raising=False)
    monkeypatch.setattr(_kbd.os, "cpu_count", lambda: 0)

    assert _kbd.derive_default_max_in_progress() is None
