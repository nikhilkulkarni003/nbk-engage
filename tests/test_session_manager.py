"""Tests for the session state machine transition rules in
services/session_manager.py. These test _require_transition directly
(pure logic, no DB) -- the full create/start/close/reveal DB-backed
flow is covered by tests/test_integration_db.py."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import inspect

import pytest

from services import session_manager
from services.session_manager import InvalidTransitionError, VALID_TRANSITIONS, _require_transition


def test_full_happy_path_sequence_is_valid():
    sequence = [
        "WAITING", "QUESTION_ACTIVE", "VOTING_CLOSED",
        "RESULTS_REVEALED", "LEADERBOARD", "QUESTION_ACTIVE",
    ]
    for current, target in zip(sequence, sequence[1:]):
        _require_transition(current, target)  # should not raise


def test_leaderboard_can_end_session():
    _require_transition("LEADERBOARD", "SESSION_ENDED")


def test_cannot_skip_from_waiting_to_voting_closed():
    with pytest.raises(InvalidTransitionError):
        _require_transition("WAITING", "VOTING_CLOSED")


def test_cannot_go_backwards():
    with pytest.raises(InvalidTransitionError):
        _require_transition("RESULTS_REVEALED", "QUESTION_ACTIVE")


def test_cannot_transition_out_of_ended_session():
    with pytest.raises(InvalidTransitionError):
        _require_transition("SESSION_ENDED", "WAITING")


def test_waiting_can_start_self_paced():
    _require_transition("WAITING", "SELF_PACED_ACTIVE")  # should not raise


def test_self_paced_active_can_close_to_leaderboard():
    _require_transition("SELF_PACED_ACTIVE", "LEADERBOARD")  # should not raise


def test_self_paced_active_cannot_skip_straight_to_session_ended_via_question_active():
    with pytest.raises(InvalidTransitionError):
        _require_transition("SELF_PACED_ACTIVE", "QUESTION_ACTIVE")


def test_end_session_bypasses_the_transition_table():
    # end_session() is intentionally unconditional -- the host's "End
    # Session" control must work from any screen (WAITING included),
    # so it does not call _require_transition at all. Guard against a
    # future refactor accidentally routing it through the transition
    # table (which would make WAITING -> SESSION_ENDED start failing,
    # since VALID_TRANSITIONS["WAITING"] only allows QUESTION_ACTIVE).
    source = inspect.getsource(session_manager.end_session)
    assert "_require_transition" not in source
