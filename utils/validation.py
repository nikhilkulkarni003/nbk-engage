"""
Shared validation helpers used by the participant join flow, the
admin question editor, and the Excel importer. Pure functions --
no database or Streamlit imports -- so they're easy to unit test.
"""

from __future__ import annotations

import re

MAX_NAME_LENGTH = 40
MIN_NAME_LENGTH = 1
ALLOWED_TYPES = ["MCQ", "POLL", "WORDCLOUD", "RATING", "OPEN_ENDED"]
ALLOWED_DIFFICULTIES = ["Easy", "Medium", "Hard"]
SESSION_CODE_RE = re.compile(r"^\d{6}$")


def validate_session_code(code: str) -> tuple[bool, str]:
    code = (code or "").strip()
    if not code:
        return False, "Please enter a session code."
    if not SESSION_CODE_RE.match(code):
        return False, "Session code must be exactly 6 digits."
    return True, code


def validate_participant_name(name: str) -> tuple[bool, str]:
    name = (name or "").strip()
    if len(name) < MIN_NAME_LENGTH:
        return False, "Please enter your name."
    if len(name) > MAX_NAME_LENGTH:
        return False, f"Name must be {MAX_NAME_LENGTH} characters or fewer."
    if not re.search(r"[A-Za-z0-9]", name):
        return False, "Name must contain at least one letter or number."
    return True, name


def validate_free_text_answer(text: str, min_length: int = 1, max_length: int = 200) -> tuple[bool, str]:
    text = (text or "").strip()
    if len(text) < min_length:
        return False, f"Please enter at least {min_length} character(s)."
    if len(text) > max_length:
        return False, f"Response must be {max_length} characters or fewer."
    return True, text


def validate_question_dict(row: dict, row_label: str = "") -> list[str]:
    """Validates a single question record (from the admin form or an
    Excel row). Returns a list of human-readable error strings; an
    empty list means the row is valid."""
    errors: list[str] = []
    prefix = f"{row_label}: " if row_label else ""

    question_text = str(row.get("question") or "").strip()
    if not question_text:
        errors.append(f"{prefix}Question text is required.")

    q_type = str(row.get("type") or "").strip().upper()
    if q_type not in ALLOWED_TYPES:
        errors.append(f"{prefix}Type must be one of {', '.join(ALLOWED_TYPES)} (got '{row.get('type')}').")
        return errors  # further checks depend on a valid type

    options = [row.get("option_a"), row.get("option_b"), row.get("option_c"), row.get("option_d")]
    non_empty_options = [o for o in options if str(o or "").strip()]

    if q_type in ("MCQ", "POLL"):
        if len(non_empty_options) < 2:
            errors.append(f"{prefix}{q_type} needs at least 2 options.")

    if q_type == "MCQ":
        correct = str(row.get("correct_answer") or "").strip().upper()
        if correct not in ("A", "B", "C", "D", "E", "F", "G", "H"):
            errors.append(f"{prefix}MCQ requires a correct_answer (A, B, C or D).")
        else:
            option_letters = ["A", "B", "C", "D"][: len(options)]
            filled_letters = [l for l, o in zip(option_letters, options) if str(o or "").strip()]
            if correct not in filled_letters:
                errors.append(f"{prefix}correct_answer '{correct}' does not match a filled option.")

    points = row.get("points")
    if points not in (None, ""):
        try:
            if int(points) < 0:
                errors.append(f"{prefix}points must be zero or a positive number.")
        except (ValueError, TypeError):
            errors.append(f"{prefix}points must be a whole number.")

    timer = row.get("timer_seconds")
    if timer not in (None, ""):
        try:
            if int(timer) < 0:
                errors.append(f"{prefix}timer_seconds must be zero or a positive number.")
        except (ValueError, TypeError):
            errors.append(f"{prefix}timer_seconds must be a whole number.")

    difficulty = str(row.get("difficulty") or "Medium").strip().title()
    if difficulty not in ALLOWED_DIFFICULTIES:
        errors.append(f"{prefix}difficulty must be one of {', '.join(ALLOWED_DIFFICULTIES)}.")

    return errors
