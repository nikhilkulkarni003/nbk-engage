"""Countdown timer, computed from the server-stored start time so
every browser (host and every participant) shows the same
remaining time regardless of local clock or page-load time."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import streamlit as st


def seconds_remaining(started_at: datetime | None, timer_seconds: int | None) -> Optional[int]:
    if not started_at or not timer_seconds:
        return None
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()
    remaining = max(0, int(timer_seconds - elapsed))
    return remaining


def render_timer(started_at: datetime | None, timer_seconds: int | None) -> Optional[int]:
    """Renders a progress bar + big countdown number. Returns the
    remaining seconds (or None if this question has no timer)."""
    remaining = seconds_remaining(started_at, timer_seconds)
    if remaining is None:
        st.caption("⏱ No time limit")
        return None
    fraction = remaining / timer_seconds if timer_seconds else 0
    color = "🟢" if remaining > timer_seconds * 0.5 else ("🟡" if remaining > timer_seconds * 0.2 else "🔴")
    st.progress(fraction, text=f"{color} {remaining}s remaining")
    return remaining
