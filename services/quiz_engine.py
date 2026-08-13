"""
Quiz flow / question-sequencing logic.

Responsible for turning a reusable question_set into the ordered,
immutable list of session_questions that a specific live session
runs through, and for answering "what's the current / next
question" during that run. State-machine transitions (WAITING ->
QUESTION_ACTIVE -> ...) live in session_manager.py, which calls
into this module for sequencing decisions.
"""

from __future__ import annotations

from typing import Optional

from services import database as db


def build_session_questions(session_id: str, question_set_id: str) -> list[dict]:
    bank_questions = db.get_question_set_items(question_set_id)
    if not bank_questions:
        raise ValueError("This question set has no questions. Add questions before starting a session.")
    return db.create_session_questions(session_id, bank_questions)


def get_ordered_questions(session_id: str) -> list[dict]:
    return db.list_session_questions(session_id)


def get_question_at_index(session_id: str, index: int) -> Optional[dict]:
    questions = get_ordered_questions(session_id)
    if 0 <= index < len(questions):
        return questions[index]
    return None


def total_questions(session_id: str) -> int:
    return len(db.list_session_questions(session_id))


def has_next_question(session_id: str, current_index: int) -> bool:
    return current_index + 1 < total_questions(session_id)
