"""Unit tests for utils/validation.py."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.validation import (
    validate_participant_name,
    validate_question_dict,
    validate_session_code,
)


def test_valid_session_code():
    ok, val = validate_session_code("123456")
    assert ok is True
    assert val == "123456"


def test_session_code_wrong_length():
    ok, msg = validate_session_code("12345")
    assert ok is False


def test_session_code_non_numeric():
    ok, msg = validate_session_code("12345A")
    assert ok is False


def test_session_code_empty():
    ok, msg = validate_session_code("")
    assert ok is False


def test_valid_participant_name():
    ok, val = validate_participant_name("  Rahul Sharma  ")
    assert ok is True
    assert val == "Rahul Sharma"


def test_participant_name_empty():
    ok, msg = validate_participant_name("   ")
    assert ok is False


def test_participant_name_too_long():
    ok, msg = validate_participant_name("x" * 41)
    assert ok is False


def test_participant_name_symbols_only():
    ok, msg = validate_participant_name("!!!")
    assert ok is False


def test_valid_mcq_question():
    row = {
        "question": "2+2=?", "type": "MCQ",
        "option_a": "3", "option_b": "4", "option_c": "5", "option_d": "6",
        "correct_answer": "B", "points": 1000, "timer_seconds": 30, "difficulty": "Easy",
    }
    assert validate_question_dict(row) == []


def test_mcq_missing_correct_answer():
    row = {
        "question": "2+2=?", "type": "MCQ",
        "option_a": "3", "option_b": "4", "option_c": "", "option_d": "",
        "correct_answer": "", "points": 1000, "timer_seconds": 30, "difficulty": "Easy",
    }
    errors = validate_question_dict(row)
    assert any("correct_answer" in e for e in errors)


def test_mcq_correct_answer_not_matching_filled_option():
    row = {
        "question": "2+2=?", "type": "MCQ",
        "option_a": "3", "option_b": "4", "option_c": "", "option_d": "",
        "correct_answer": "D", "points": 1000, "timer_seconds": 30, "difficulty": "Easy",
    }
    errors = validate_question_dict(row)
    assert any("does not match" in e for e in errors)


def test_poll_needs_at_least_two_options():
    row = {
        "question": "Pick one", "type": "POLL",
        "option_a": "Only one", "option_b": "", "option_c": "", "option_d": "",
        "correct_answer": "", "points": 0, "timer_seconds": 20, "difficulty": "Easy",
    }
    errors = validate_question_dict(row)
    assert any("at least 2 options" in e for e in errors)


def test_wordcloud_needs_no_options():
    row = {
        "question": "One word?", "type": "WORDCLOUD",
        "option_a": "", "option_b": "", "option_c": "", "option_d": "",
        "correct_answer": "", "points": 0, "timer_seconds": 30, "difficulty": "Easy",
    }
    assert validate_question_dict(row) == []


def test_invalid_type_rejected():
    row = {"question": "x", "type": "TRUEFALSE"}
    errors = validate_question_dict(row)
    assert any("Type must be one of" in e for e in errors)


def test_negative_points_rejected():
    row = {
        "question": "x", "type": "MCQ",
        "option_a": "a", "option_b": "b", "correct_answer": "A",
        "points": -50, "timer_seconds": 30, "difficulty": "Easy",
    }
    errors = validate_question_dict(row)
    assert any("points must be" in e for e in errors)


def test_invalid_difficulty_rejected():
    row = {
        "question": "x", "type": "MCQ",
        "option_a": "a", "option_b": "b", "correct_answer": "A",
        "points": 100, "timer_seconds": 30, "difficulty": "Impossible",
    }
    errors = validate_question_dict(row)
    assert any("difficulty" in e for e in errors)
