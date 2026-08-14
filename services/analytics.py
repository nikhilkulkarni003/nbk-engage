"""
Read-only aggregation logic: poll/MCQ result bars, word-cloud
frequency tables, rating distributions, open-ended response lists,
and the full session summary used for Excel export.

All aggregation reads from the `responses` table (the single write
path for every question type -- see database/schema.sql for why
there is no separate wordcloud_responses table).
"""

from __future__ import annotations

import re
import string
from collections import Counter
from typing import Optional

from wordcloud import STOPWORDS

from services import database as db

OPTION_LETTERS = ["A", "B", "C", "D", "E", "F", "G", "H"]

# A few generic filler words beyond the wordcloud library's default
# English stopword list, common in classroom/training word-cloud answers.
EXTRA_STOPWORDS = {"im", "dont", "youre", "thats", "theyre", "will", "one", "also", "etc"}


def get_question_options(session_question: dict) -> list[tuple[str, str]]:
    """Returns [(letter, option_text), ...] for MCQ/POLL, in order."""
    options = []
    for letter, col in zip("ABCD", ["option_a", "option_b", "option_c", "option_d"]):
        text = session_question.get(col)
        if text:
            options.append((letter, text))
    extra = (session_question.get("config") or {}).get("extra_options") or []
    for i, text in enumerate(extra):
        if text:
            options.append((OPTION_LETTERS[4 + i], text))
    return options


def get_option_results(session_question: dict, responses: Optional[list[dict]] = None) -> list[dict]:
    """Live results for MCQ / POLL questions: option, count, pct.

    `responses`, if provided, must already be this question's response
    rows (e.g. a session-wide fetch grouped in Python by the caller --
    see get_session_report) so this doesn't issue its own
    get_option_counts query. Falls back to querying when not supplied,
    which is exactly right for the single current-question case (host/
    participant QUESTION_ACTIVE and RESULTS_REVEALED screens)."""
    # A skipped question (SELF_PACED pacing_mode) has answer_text=None
    # -- it must not count toward the option percentages/total, or
    # every question's percentages would be diluted by however many
    # people skipped it.
    if responses is not None:
        counts_by_letter: dict[str, int] = Counter(
            r["answer_text"] for r in responses if not r.get("is_skipped") and r.get("answer_text")
        )
    else:
        counts_by_letter = {
            row["answer_text"]: row["response_count"]
            for row in db.get_option_counts(session_question["id"])
            if row["answer_text"]
        }
    options = get_question_options(session_question)
    total = sum(counts_by_letter.values())
    results = []
    for letter, text in options:
        count = counts_by_letter.get(letter, 0)
        pct = round((count / total) * 100, 1) if total else 0.0
        results.append({
            "letter": letter,
            "option_text": text,
            "count": count,
            "pct": pct,
            "is_correct": (letter == session_question.get("correct_answer")),
        })
    return results


def get_rating_summary(session_question_id: str, responses: Optional[list[dict]] = None) -> dict:
    responses = responses if responses is not None else db.list_responses(session_question_id)
    values = []
    for r in responses:
        try:
            values.append(int(r["answer_text"]))
        except (TypeError, ValueError):
            continue
    distribution = {i: 0 for i in range(1, 6)}
    for v in values:
        if v in distribution:
            distribution[v] += 1
    average = round(sum(values) / len(values), 2) if values else 0.0
    return {"average": average, "distribution": distribution, "total": len(values)}


def get_open_ended_responses(session_question_id: str, responses: Optional[list[dict]] = None) -> list[dict]:
    responses = responses if responses is not None else db.list_responses(session_question_id)
    return [
        {"participant_name": r["participant_name"], "answer_text": r["answer_text"],
         "submitted_at": r["submitted_at"]}
        for r in responses
        if not r.get("is_skipped")  # a skip has no text worth listing
    ]


_WORD_RE = re.compile(r"[a-zA-Z']+")


def get_word_frequencies(session_question_id: str, min_length: int = 2, top_n: int = 100,
                          responses: Optional[list[dict]] = None) -> list[dict]:
    """Tokenizes all free-text answers for a WORDCLOUD question,
    normalizes case, strips punctuation, drops stopwords/short words,
    and returns [{"word": ..., "count": ...}, ...] sorted by frequency."""
    responses = responses if responses is not None else db.list_responses(session_question_id)
    stopwords = STOPWORDS | EXTRA_STOPWORDS
    counter: Counter[str] = Counter()
    for r in responses:
        raw = (r.get("answer_text") or "").lower()
        words = _WORD_RE.findall(raw)
        for w in words:
            w = w.strip(string.punctuation + "'")
            if len(w) < min_length:
                continue
            if w in stopwords:
                continue
            counter[w] += 1
    return [{"word": w, "count": c} for w, c in counter.most_common(top_n)]


def get_leaderboard(session_id: str) -> list[dict]:
    return db.get_leaderboard(session_id)


def get_session_summary(session_id: str) -> dict:
    """Full data needed for Excel export: participants, per-question
    results, final scores, and raw responses."""
    session = db.get_session(session_id)
    participants = db.list_participants(session_id)
    session_questions = db.list_session_questions(session_id)
    leaderboard = db.get_leaderboard(session_id)

    question_results = []
    raw_responses = []
    for sq in session_questions:
        responses = db.list_responses(sq["id"])
        for r in responses:
            raw_responses.append({
                "question": sq["question_text"],
                "type": sq["type"],
                "participant_name": r["participant_name"],
                "answer_text": r["answer_text"],
                "is_correct": r["is_correct"],
                "response_time_ms": r["response_time_ms"],
                "points_awarded": r["points_awarded"],
                "submitted_at": r["submitted_at"],
            })
        if sq["type"] in ("MCQ", "POLL"):
            for opt in get_option_results(sq):
                question_results.append({
                    "question": sq["question_text"],
                    "type": sq["type"],
                    "option": f'{opt["letter"]}: {opt["option_text"]}',
                    "responses": opt["count"],
                    "pct": opt["pct"],
                    "is_correct_option": opt["is_correct"],
                })

    return {
        "session": session,
        "participants": participants,
        "leaderboard": leaderboard,
        "question_results": question_results,
        "raw_responses": raw_responses,
    }


def get_session_report(session_id: str) -> dict:
    """Overall accuracy + per-question correct/incorrect breakdown for
    the in-browser session report (components/session_report.py) --
    the on-screen equivalent of the Excel export's summary numbers.

    Previously issued one list_responses() query per session_question
    (an N+1 that, combined with the per-question result renderers each
    also querying independently, was driving the host's Group Results
    screen to ~36 queries every poll tick). Now fetches every
    response for the whole session in a single round trip and groups
    it in Python by session_question_id -- the per-question rows in
    "responses" are handed back so callers (session_report.py) can
    pass them straight into render_question_results(...) instead of
    it re-querying per question too."""
    session_questions = db.list_session_questions(session_id)
    participants = db.list_participants(session_id)
    all_responses = db.list_responses_for_session(session_id)

    responses_by_sq: dict[str, list[dict]] = {}
    for r in all_responses:
        responses_by_sq.setdefault(r["session_question_id"], []).append(r)

    total_correct = 0
    total_incorrect = 0
    all_response_times_ms: list[int] = []
    per_question = []

    for sq in session_questions:
        responses = responses_by_sq.get(sq["id"], [])
        correct_count = incorrect_count = None
        if sq["type"] == "MCQ":
            correct_count = sum(1 for r in responses if r["is_correct"] is True)
            incorrect_count = sum(1 for r in responses if r["is_correct"] is False)
            total_correct += correct_count
            total_incorrect += incorrect_count

        times = [r["response_time_ms"] for r in responses if r["response_time_ms"] is not None]
        all_response_times_ms.extend(times)
        avg_time_sec = round(sum(times) / len(times) / 1000, 1) if times else None

        answered = (correct_count or 0) + (incorrect_count or 0)
        per_question.append({
            "order_index": sq["order_index"],
            "question_text": sq["question_text"],
            "type": sq["type"],
            "response_count": len(responses),
            "correct_count": correct_count,
            "incorrect_count": incorrect_count,
            "accuracy_pct": round(correct_count / answered * 100, 1) if answered else None,
            "avg_time_sec": avg_time_sec,
            "session_question": sq,
            "responses": responses,
        })

    total_scored = total_correct + total_incorrect
    overall_accuracy_pct = round(total_correct / total_scored * 100, 1) if total_scored else 0.0
    overall_avg_time_sec = (
        round(sum(all_response_times_ms) / len(all_response_times_ms) / 1000, 1)
        if all_response_times_ms else 0.0
    )

    leaderboard = db.get_leaderboard(session_id)
    avg_score_per_participant = (
        round(sum(r["total_score"] for r in leaderboard) / len(leaderboard), 1)
        if leaderboard else 0.0
    )

    return {
        "total_participants": len(participants),
        "total_questions": len(session_questions),
        "total_correct": total_correct,
        "total_incorrect": total_incorrect,
        "overall_accuracy_pct": overall_accuracy_pct,
        "overall_avg_time_sec": overall_avg_time_sec,
        "avg_score_per_participant": avg_score_per_participant,
        "per_question": per_question,
    }
