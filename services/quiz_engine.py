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


def get_question_at_index(session_id: str, index: int,
                           questions: Optional[list[dict]] = None) -> Optional[dict]:
    """`questions`, if provided, must be this session's full ordered
    list (e.g. already fetched this tick) -- avoids a redundant
    list_session_questions round trip. Falls back to fetching it when
    not supplied, so existing callers are unaffected."""
    questions = questions if questions is not None else get_ordered_questions(session_id)
    if 0 <= index < len(questions):
        return questions[index]
    return None


def total_questions(session_id: str, known_total: Optional[int] = None) -> int:
    """`known_total`, if provided, is trusted as-is instead of
    re-querying. Session questions are created once at session-start
    and never added to or removed from afterwards (see
    build_session_questions), so this count is safe for a caller to
    fetch once and reuse for the rest of the session's lifetime --
    including across separate poll ticks, not just within one -- and
    is exactly what host.py/participant.py do (cached per session_id
    in st.session_state) to avoid a list_session_questions round trip
    on every 2-second tick."""
    if known_total is not None:
        return known_total
    return len(get_ordered_questions(session_id))


def has_next_question(session_id: str, current_index: int,
                       known_total: Optional[int] = None) -> bool:
    return current_index + 1 < total_questions(session_id, known_total)
