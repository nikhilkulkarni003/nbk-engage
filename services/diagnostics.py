"""
TEMPORARY diagnostic instrumentation for the live-polling latency
investigation (see the performance audit / optimization rounds this
session). Not part of the permanent architecture -- safe to delete
this file and its handful of call sites in services/database.py,
pages/host.py and pages/participant.py once the actual latency source
is identified.

Prints one line per DB call and one summary line per polling-fragment
execution to stdout, which Streamlit Community Cloud captures in its
deployment logs. Never logs DATABASE_URL, ADMIN_PASSWORD, or any other
secret -- only operation names (Python function names) and timings.

Usage (see pages/host.py, pages/participant.py, services/database.py):
    start_poll("HOST_POLL")          # once, at the very top of the fragment
    mark("some_checkpoint")          # as many times as useful, anywhere
    record_query(op, acquire_ms, exec_ms, new_connection)  # called from database.py
    end_poll(pool_stats=db.get_pool_stats(), label="HOST_POLL")  # once, in a finally block
"""

from __future__ import annotations

import time
from contextvars import ContextVar
from typing import Optional

_poll: ContextVar[Optional[dict]] = ContextVar("_nbk_diag_poll", default=None)


def start_poll(name: str) -> None:
    """Call once at the top of a polling fragment (host or participant)
    to begin accumulating per-query timings for this single fragment
    execution. Any record_query()/mark() calls before the matching
    end_poll() are attributed to this poll."""
    _poll.set({"name": name, "start": time.perf_counter(), "queries": []})


def record_query(op: str, acquire_ms: float, exec_ms: float, new_connection: bool) -> None:
    """Called by services/database.py after every fetch_one/fetch_all/
    execute call. A no-op outside an active start_poll(...)/end_poll()
    span (e.g. a button-click mutation like submit_answer, which runs
    outside the polling fragment) -- so this only ever logs what a
    poll tick actually did, not every DB call in the app."""
    m = _poll.get()
    if m is None:
        return
    m["queries"].append({
        "op": op,
        "acquire_ms": acquire_ms,
        "exec_ms": exec_ms,
        "new_connection": new_connection,
    })


def mark(label: str) -> None:
    """Prints a single checkpoint line with elapsed time since this
    poll started -- use this around specific steps that aren't a raw
    DB call (rendering, cache hits, or to bracket a specific call like
    "get the current question" with a before/after pair)."""
    m = _poll.get()
    if m is None:
        print(f"    [checkpoint] {label} (no active poll)")
        return
    elapsed_ms = (time.perf_counter() - m["start"]) * 1000
    print(f"    [checkpoint] {label} elapsed_since_poll_start={elapsed_ms:.1f}ms", flush=True)


def end_poll(pool_stats: Optional[dict] = None, label: Optional[str] = None) -> None:
    """Call once at the end of the same polling fragment (in a
    try/finally so it always fires, even on an early return or an
    exception). Prints the per-query breakdown followed by the single
    summary line, e.g.:

        PARTICIPANT_POLL total=812.3ms db=740.1ms pool_wait=620.4ms render=45.2ms queries=6 new_conns=2

    total    = whole fragment execution time (D)
    db       = sum of (pool_wait + sql exec) across every query (A+B)
    pool_wait= sum of time spent acquiring/waiting for a pool connection (A)
    render   = total - db, i.e. time spent in Python/Streamlit rendering (C)
    """
    m = _poll.get()
    if m is None:
        return
    total_ms = (time.perf_counter() - m["start"]) * 1000
    db_ms = sum(q["acquire_ms"] + q["exec_ms"] for q in m["queries"])
    pool_wait_ms = sum(q["acquire_ms"] for q in m["queries"])
    render_ms = max(0.0, total_ms - db_ms)
    new_conns = sum(1 for q in m["queries"] if q["new_connection"])
    tag = label or m["name"]

    for q in m["queries"]:
        print(
            f"  [{tag}] op={q['op']:<28} pool_wait={q['acquire_ms']:7.1f}ms "
            f"sql_exec={q['exec_ms']:7.1f}ms new_connection={q['new_connection']}",
            flush=True,
        )

    if pool_stats:
        print(
            f"  [{tag}] pool size={pool_stats.get('size')} "
            f"checked_in={pool_stats.get('checked_in')} "
            f"checked_out={pool_stats.get('checked_out')} "
            f"overflow={pool_stats.get('overflow')}",
            flush=True,
        )

    print(
        f"{tag} total={total_ms:.1f}ms db={db_ms:.1f}ms "
        f"pool_wait={pool_wait_ms:.1f}ms render={render_ms:.1f}ms "
        f"queries={len(m['queries'])} new_conns={new_conns}",
        flush=True,
    )
    _poll.set(None)
