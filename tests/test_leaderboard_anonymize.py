"""
Tests the pseudonym-generation logic backing the anonymous
leaderboard (components/leaderboard.py). Only the pure hashing
function is tested here -- rendering itself needs a live Streamlit
script run context, so it's covered by the manual/browser
verification described in README.md.
"""

import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from components.leaderboard import _pseudonym


def test_pseudonym_is_stable_for_the_same_participant():
    pid = "11111111-1111-1111-1111-111111111111"
    assert _pseudonym(pid) == _pseudonym(pid)


def test_pseudonym_differs_across_participants():
    p1 = _pseudonym("11111111-1111-1111-1111-111111111111")
    p2 = _pseudonym("22222222-2222-2222-2222-222222222222")
    assert p1 != p2


def test_pseudonym_never_contains_the_raw_id():
    pid = "33333333-3333-3333-3333-333333333333"
    assert pid not in _pseudonym(pid)


def test_pseudonym_has_expected_format():
    pseudonym = _pseudonym("44444444-4444-4444-4444-444444444444")
    assert pseudonym.startswith("Participant ")
    number = int(pseudonym.split(" ")[1])
    assert 100 <= number <= 999


def test_pseudonym_accepts_uuid_object_not_just_str():
    # Regression test: psycopg2 returns uuid.UUID objects (not str)
    # for uuid columns, and session_leaderboard.participant_id is one
    # of those -- an earlier version of _pseudonym called .encode()
    # directly on the id and crashed with AttributeError as soon as a
    # real UUID object (rather than a plain string) reached it.
    pid_str = "55555555-5555-5555-5555-555555555555"
    pid_uuid = uuid.UUID(pid_str)
    assert _pseudonym(pid_uuid) == _pseudonym(pid_str)
