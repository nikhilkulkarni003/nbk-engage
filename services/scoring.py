"""
Pure scoring logic -- no database or Streamlit imports, so this
module is trivially unit-testable.

Scoring is always computed here (server-side) and never trusted
from the participant's browser. The client only ever sends
"which option / text did the participant pick" plus a client-measured
response time used purely for the bonus calculation; correctness and
points are derived from the session_question's own stored
correct_answer and scoring_config.
"""

from __future__ import annotations

DEFAULT_SCORING_CONFIG = {
    "base_points": 1,
    "time_bonus_enabled": False,
    "negative_marking_enabled": False,
    "negative_points": 0,
}


def calculate_mcq_score(
    is_correct: bool,
    response_time_ms: int | None,
    timer_seconds: int | None,
    base_points: int = 1,
    time_bonus_enabled: bool = False,
    negative_marking_enabled: bool = False,
    negative_points: int = 0,
) -> int:
    """
    Default mode: correct answer -> base_points (1 unless configured
    otherwise), incorrect -> 0. If the host opts into
    time_bonus_enabled, a correct answer instead gets up to +50%
    bonus scaled by remaining time (classic Kahoot-style scoring).
    No timer configured -> no time bonus regardless of the setting.
    """
    if not is_correct:
        return -abs(negative_points) if negative_marking_enabled else 0

    if not time_bonus_enabled or not timer_seconds or timer_seconds <= 0:
        return base_points

    timer_ms = timer_seconds * 1000
    elapsed = max(0, response_time_ms or 0)
    remaining = max(0, timer_ms - elapsed)
    time_fraction = min(1.0, remaining / timer_ms)
    bonus = round(base_points * 0.5 * time_fraction)
    return base_points + bonus


def is_mcq_answer_correct(answer_text: str, correct_answer: str | None) -> bool:
    if not correct_answer:
        return False
    return (answer_text or "").strip().upper() == correct_answer.strip().upper()


def score_response(question_type: str, answer_text: str, session_question: dict,
                    response_time_ms: int | None, scoring_config: dict | None) -> tuple[bool | None, int]:
    """
    Returns (is_correct, points_awarded) for any question type.
    Only MCQ carries a notion of correctness/points; every other
    type is unscored (is_correct=None, points=0) by design.
    """
    cfg = {**DEFAULT_SCORING_CONFIG, **(scoring_config or {})}

    if question_type == "MCQ":
        correct = is_mcq_answer_correct(answer_text, session_question.get("correct_answer"))
        points = calculate_mcq_score(
            is_correct=correct,
            response_time_ms=response_time_ms,
            timer_seconds=session_question.get("timer_seconds"),
            base_points=session_question.get("points") or cfg["base_points"],
            time_bonus_enabled=cfg["time_bonus_enabled"],
            negative_marking_enabled=cfg["negative_marking_enabled"],
            negative_points=cfg["negative_points"],
        )
        return correct, points

    # POLL, WORDCLOUD, RATING, OPEN_ENDED: participation only, no correctness.
    return None, 0
