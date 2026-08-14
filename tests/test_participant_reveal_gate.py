"""
Tests for the reveal-to-participants gate in pages/participant.py.

This was a real bug: self-paced sessions never reached the leaderboard
render at all (participants stuck on "waiting for the host to start"),
while host-paced sessions leaked the ranked leaderboard/scores to
participants before the host clicked "Reveal to Participants". Both
came from the same file -- see pages/participant.py::_final_results_revealed
and the LEADERBOARD dispatch branch in _render_session_body.

_final_results_revealed is a pure function (no DB, no Streamlit), so
it's tested directly here without a UI harness.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pages.participant import _final_results_revealed


def test_not_revealed_before_host_clicks_reveal():
    session = {"group_summary_revealed_at": None}
    assert _final_results_revealed(session) is False


def test_revealed_after_host_clicks_reveal():
    session = {"group_summary_revealed_at": "2026-01-01T00:00:00+00:00"}
    assert _final_results_revealed(session) is True


def test_missing_key_is_treated_as_not_revealed():
    # A session dict that simply doesn't have the key yet (e.g. a
    # stale/partial fetch) must fail safe to "not revealed", not
    # accidentally leak results.
    assert _final_results_revealed({}) is False
