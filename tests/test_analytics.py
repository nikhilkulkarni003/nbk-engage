"""
Tests for services/analytics.py aggregation logic (poll/MCQ result
bars, word-cloud frequency counting, rating summaries).

These monkeypatch services.database's read functions instead of
hitting a real Postgres/Supabase instance, so the aggregation MATH
(percentages, stopword filtering, normalization) can be verified
without any live database -- see tests/test_integration_db.py for
the end-to-end DB-backed tests.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import analytics, database as db


def test_get_option_results_percentages(monkeypatch):
    monkeypatch.setattr(
        db, "get_option_counts",
        lambda sqid: [{"answer_text": "A", "response_count": 8}, {"answer_text": "C", "response_count": 12}],
    )
    sq = {
        "id": "sq1", "option_a": "Yes", "option_b": "No", "option_c": "Maybe", "option_d": None,
        "correct_answer": "A", "config": {},
    }
    results = analytics.get_option_results(sq)
    by_letter = {r["letter"]: r for r in results}
    assert by_letter["A"]["count"] == 8
    assert by_letter["A"]["pct"] == 40.0
    assert by_letter["C"]["count"] == 12
    assert by_letter["C"]["pct"] == 60.0
    assert by_letter["B"]["count"] == 0
    assert by_letter["A"]["is_correct"] is True
    assert by_letter["B"]["is_correct"] is False


def test_get_option_results_no_responses_yet(monkeypatch):
    monkeypatch.setattr(db, "get_option_counts", lambda sqid: [])
    sq = {"id": "sq1", "option_a": "Yes", "option_b": "No", "option_c": None, "option_d": None,
          "correct_answer": None, "config": {}}
    results = analytics.get_option_results(sq)
    assert all(r["count"] == 0 and r["pct"] == 0.0 for r in results)


def test_get_option_results_includes_poll_extra_options(monkeypatch):
    monkeypatch.setattr(
        db, "get_option_counts",
        lambda sqid: [{"answer_text": "E", "response_count": 3}],
    )
    sq = {
        "id": "sq1", "option_a": "A1", "option_b": "A2", "option_c": "A3", "option_d": "A4",
        "correct_answer": None, "config": {"extra_options": ["A5"]},
    }
    results = analytics.get_option_results(sq)
    letters = [r["letter"] for r in results]
    assert letters == ["A", "B", "C", "D", "E"]
    assert next(r for r in results if r["letter"] == "E")["count"] == 3


def test_word_frequencies_normalizes_case_and_strips_punctuation(monkeypatch):
    monkeypatch.setattr(
        db, "list_responses",
        lambda sqid: [
            {"answer_text": "Cash Flow!"},
            {"answer_text": "cash flow"},
            {"answer_text": "CASH."},
        ],
    )
    freq = analytics.get_word_frequencies("sq1", min_length=2)
    words = {item["word"]: item["count"] for item in freq}
    assert words["cash"] == 3
    assert words["flow"] == 2


def test_word_frequencies_removes_stopwords_and_short_words(monkeypatch):
    monkeypatch.setattr(
        db, "list_responses",
        lambda sqid: [{"answer_text": "the a of it is working capital"}],
    )
    freq = analytics.get_word_frequencies("sq1", min_length=2)
    words = {item["word"] for item in freq}
    assert "the" not in words
    assert "of" not in words
    assert "a" not in words  # below min_length AND a stopword
    assert "working" in words
    assert "capital" in words


def test_word_frequencies_empty_when_no_responses(monkeypatch):
    monkeypatch.setattr(db, "list_responses", lambda sqid: [])
    freq = analytics.get_word_frequencies("sq1")
    assert freq == []


def test_rating_summary_average_and_distribution(monkeypatch):
    monkeypatch.setattr(
        db, "list_responses",
        lambda sqid: [{"answer_text": "5"}, {"answer_text": "3"}, {"answer_text": "5"}, {"answer_text": "not-a-number"}],
    )
    summary = analytics.get_rating_summary("sq1")
    assert summary["total"] == 3
    assert summary["distribution"][5] == 2
    assert summary["distribution"][3] == 1
    assert summary["average"] == round((5 + 3 + 5) / 3, 2)


def test_rating_summary_handles_no_responses(monkeypatch):
    monkeypatch.setattr(db, "list_responses", lambda sqid: [])
    summary = analytics.get_rating_summary("sq1")
    assert summary["total"] == 0
    assert summary["average"] == 0.0


def test_session_report_computes_overall_accuracy_and_avg_time(monkeypatch):
    sqs = [
        {"id": "sq1", "order_index": 0, "question_text": "2+2=?", "type": "MCQ"},
        {"id": "sq2", "order_index": 1, "question_text": "Pick a color", "type": "POLL"},
    ]
    responses_by_sq = {
        "sq1": [
            {"is_correct": True, "response_time_ms": 2000},
            {"is_correct": False, "response_time_ms": 4000},
            {"is_correct": True, "response_time_ms": 3000},
        ],
        "sq2": [
            {"is_correct": None, "response_time_ms": 1000},
        ],
    }
    monkeypatch.setattr(db, "list_session_questions", lambda sid: sqs)
    monkeypatch.setattr(db, "list_participants", lambda sid: [{"id": "p1"}, {"id": "p2"}])
    monkeypatch.setattr(db, "list_responses", lambda sqid: responses_by_sq[sqid])
    monkeypatch.setattr(db, "get_leaderboard", lambda sid: [
        {"participant_id": "p1", "total_score": 2}, {"participant_id": "p2", "total_score": 0},
    ])

    report = analytics.get_session_report("session1")

    assert report["total_participants"] == 2
    assert report["total_questions"] == 2
    assert report["total_correct"] == 2
    assert report["total_incorrect"] == 1
    assert report["overall_accuracy_pct"] == round(2 / 3 * 100, 1)
    # avg of all 4 response times (2000+4000+3000+1000)/4 = 2500ms = 2.5s
    assert report["overall_avg_time_sec"] == 2.5
    # avg score across the two leaderboard rows (2+0)/2 = 1.0
    assert report["avg_score_per_participant"] == 1.0

    mcq_row = next(r for r in report["per_question"] if r["type"] == "MCQ")
    assert mcq_row["correct_count"] == 2
    assert mcq_row["incorrect_count"] == 1
    assert mcq_row["accuracy_pct"] == round(2 / 3 * 100, 1)

    poll_row = next(r for r in report["per_question"] if r["type"] == "POLL")
    assert poll_row["correct_count"] is None
    assert poll_row["accuracy_pct"] is None
    assert poll_row["response_count"] == 1


def test_session_report_handles_no_responses_at_all(monkeypatch):
    monkeypatch.setattr(db, "list_session_questions", lambda sid: [])
    monkeypatch.setattr(db, "list_participants", lambda sid: [])
    monkeypatch.setattr(db, "get_leaderboard", lambda sid: [])
    report = analytics.get_session_report("session1")
    assert report["total_questions"] == 0
    assert report["overall_accuracy_pct"] == 0.0
    assert report["avg_score_per_participant"] == 0.0
    assert report["per_question"] == []
