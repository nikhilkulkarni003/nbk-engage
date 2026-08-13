"""
Builds a multi-sheet Excel workbook of session results for the
host to download: participants, question-wise results, final
scores/leaderboard, and raw responses.
"""

from __future__ import annotations

import io
from datetime import datetime

import pandas as pd


def _naive(value):
    """Excel/openpyxl can't write timezone-aware datetimes; Postgres
    always returns tz-aware ones. Strip the tzinfo (values are UTC)."""
    if isinstance(value, datetime) and value.tzinfo is not None:
        return value.replace(tzinfo=None)
    return value


def _strip_tz_columns(df: pd.DataFrame) -> pd.DataFrame:
    for col in df.columns:
        if pd.api.types.is_datetime64tz_dtype(df[col]):
            df[col] = df[col].dt.tz_localize(None)
        elif df[col].dtype == object:
            df[col] = df[col].map(_naive)
    return df


def build_session_results_workbook(summary: dict) -> bytes:
    session = summary["session"]

    participants_df = pd.DataFrame(
        [{"Name": p["name"], "Joined At": p["joined_at"]} for p in summary["participants"]]
    ) if summary["participants"] else pd.DataFrame(columns=["Name", "Joined At"])

    leaderboard_df = pd.DataFrame(
        [
            {
                "Rank": row["rank"],
                "Participant": row["participant_name"],
                "Score": row["total_score"],
                "Correct Answers": row["correct_count"],
                "Questions Answered": row["answered_count"],
            }
            for row in summary["leaderboard"]
        ]
    ) if summary["leaderboard"] else pd.DataFrame(
        columns=["Rank", "Participant", "Score", "Correct Answers", "Questions Answered"]
    )

    question_results_df = pd.DataFrame(summary["question_results"]) if summary["question_results"] \
        else pd.DataFrame(columns=["question", "type", "option", "responses", "pct", "is_correct_option"])

    raw_responses_df = pd.DataFrame(summary["raw_responses"]) if summary["raw_responses"] \
        else pd.DataFrame(columns=[
            "question", "type", "participant_name", "answer_text",
            "is_correct", "response_time_ms", "points_awarded", "submitted_at",
        ])

    summary_df = pd.DataFrame([{
        "Session Title": session["title"],
        "Session Code": session["session_code"],
        "Status": session["status"],
        "Created At": _naive(session["created_at"]),
        "Started At": _naive(session.get("started_at")),
        "Ended At": _naive(session.get("ended_at")),
        "Participants": len(summary["participants"]),
    }])

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        _strip_tz_columns(summary_df).to_excel(writer, index=False, sheet_name="Session Summary")
        _strip_tz_columns(participants_df).to_excel(writer, index=False, sheet_name="Participants")
        _strip_tz_columns(leaderboard_df).to_excel(writer, index=False, sheet_name="Final Scores")
        _strip_tz_columns(question_results_df).to_excel(writer, index=False, sheet_name="Question Results")
        _strip_tz_columns(raw_responses_df).to_excel(writer, index=False, sheet_name="Raw Responses")

    return buf.getvalue()
