"""Unit tests for services/scoring.py -- pure functions, no DB needed."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.scoring import calculate_mcq_score, is_mcq_answer_correct, score_response


def test_correct_answer_letter_case_insensitive():
    assert is_mcq_answer_correct("a", "A") is True
    assert is_mcq_answer_correct(" B ", "b") is True


def test_incorrect_answer_letter():
    assert is_mcq_answer_correct("C", "A") is False


def test_no_correct_answer_configured():
    assert is_mcq_answer_correct("A", None) is False


def test_correct_answer_full_points_no_timer():
    points = calculate_mcq_score(
        is_correct=True, response_time_ms=5000, timer_seconds=None, base_points=1000,
    )
    assert points == 1000


def test_correct_answer_instant_gets_max_bonus():
    points = calculate_mcq_score(
        is_correct=True, response_time_ms=0, timer_seconds=30, base_points=1000,
        time_bonus_enabled=True,
    )
    # remaining fraction = 1.0 -> bonus = 50% of base
    assert points == 1500


def test_correct_answer_at_time_limit_gets_no_bonus():
    points = calculate_mcq_score(
        is_correct=True, response_time_ms=30000, timer_seconds=30, base_points=1000,
        time_bonus_enabled=True,
    )
    assert points == 1000


def test_correct_answer_halfway_gets_partial_bonus():
    points = calculate_mcq_score(
        is_correct=True, response_time_ms=15000, timer_seconds=30, base_points=1000,
        time_bonus_enabled=True,
    )
    assert points == 1250  # 1000 + 50% * 0.5 * 1000


def test_incorrect_answer_scores_zero_by_default():
    points = calculate_mcq_score(is_correct=False, response_time_ms=1000, timer_seconds=30)
    assert points == 0


def test_incorrect_answer_with_negative_marking():
    points = calculate_mcq_score(
        is_correct=False, response_time_ms=1000, timer_seconds=30,
        negative_marking_enabled=True, negative_points=250,
    )
    assert points == -250


def test_negative_marking_disabled_ignores_negative_points():
    points = calculate_mcq_score(
        is_correct=False, response_time_ms=1000, timer_seconds=30,
        negative_marking_enabled=False, negative_points=250,
    )
    assert points == 0


def test_late_answer_after_timer_expired_gets_zero_bonus():
    # response_time_ms greater than timer -> remaining clamps to 0
    points = calculate_mcq_score(
        is_correct=True, response_time_ms=45000, timer_seconds=30, base_points=1000,
    )
    assert points == 1000


def test_score_response_mcq_correct_uses_default_flat_scoring():
    # With no scoring_config override, the default is flat 1-point
    # scoring and no time bonus -- a correct answer scores exactly
    # the question's own points value, regardless of how fast it was.
    sq = {"correct_answer": "B", "timer_seconds": 30, "points": 1}
    is_correct, points = score_response(
        "MCQ", "B", sq, response_time_ms=3000, scoring_config=None
    )
    assert is_correct is True
    assert points == 1


def test_score_response_mcq_incorrect_scores_zero_by_default():
    sq = {"correct_answer": "B", "timer_seconds": 30, "points": 1}
    is_correct, points = score_response(
        "MCQ", "A", sq, response_time_ms=3000, scoring_config=None
    )
    assert is_correct is False
    assert points == 0


def test_score_response_mcq_time_bonus_only_when_explicitly_enabled():
    sq = {"correct_answer": "B", "timer_seconds": 30, "points": 1000}
    is_correct, points = score_response(
        "MCQ", "B", sq, response_time_ms=3000,
        scoring_config={"time_bonus_enabled": True},
    )
    assert is_correct is True
    assert points > 1000


def test_score_response_poll_is_never_scored():
    sq = {"correct_answer": None, "timer_seconds": 20, "points": 0}
    is_correct, points = score_response("POLL", "A", sq, response_time_ms=1000, scoring_config=None)
    assert is_correct is None
    assert points == 0


def test_score_response_wordcloud_is_never_scored():
    sq = {"timer_seconds": 30, "points": 0}
    is_correct, points = score_response(
        "WORDCLOUD", "growth", sq, response_time_ms=2000, scoring_config=None
    )
    assert is_correct is None
    assert points == 0
