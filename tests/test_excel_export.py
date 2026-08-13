"""Regression test: Postgres always returns timezone-aware
datetimes, but openpyxl/pandas cannot write tz-aware datetimes to
.xlsx (raises ValueError). build_session_results_workbook must
strip tzinfo before writing."""

import io
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from utils.excel_export import build_session_results_workbook

NOW = datetime.now(timezone.utc)

SUMMARY = {
    "session": {
        "title": "Test Session", "session_code": "123456", "status": "SESSION_ENDED",
        "created_at": NOW, "started_at": NOW, "ended_at": NOW,
    },
    "participants": [{"name": "Rahul", "joined_at": NOW}],
    "leaderboard": [
        {"rank": 1, "participant_name": "Rahul", "total_score": 1500,
         "correct_count": 1, "answered_count": 1},
    ],
    "question_results": [
        {"question": "2+2=?", "type": "MCQ", "option": "A: 3", "responses": 0,
         "pct": 0.0, "is_correct_option": False},
    ],
    "raw_responses": [
        {"question": "2+2=?", "type": "MCQ", "participant_name": "Rahul", "answer_text": "B",
         "is_correct": True, "response_time_ms": 1200, "points_awarded": 1200, "submitted_at": NOW},
    ],
}


def test_workbook_builds_without_error_with_tz_aware_timestamps():
    data = build_session_results_workbook(SUMMARY)
    assert len(data) > 0


def test_workbook_sheets_contain_expected_data():
    data = build_session_results_workbook(SUMMARY)
    sheets = pd.read_excel(io.BytesIO(data), sheet_name=None)
    assert set(sheets.keys()) == {
        "Session Summary", "Participants", "Final Scores", "Question Results", "Raw Responses",
    }
    assert sheets["Final Scores"].iloc[0]["Participant"] == "Rahul"
    assert sheets["Raw Responses"].iloc[0]["answer_text"] == "B"


def test_workbook_handles_empty_session():
    empty_summary = {
        "session": {
            "title": "Empty", "session_code": "000001", "status": "WAITING",
            "created_at": NOW, "started_at": None, "ended_at": None,
        },
        "participants": [], "leaderboard": [], "question_results": [], "raw_responses": [],
    }
    data = build_session_results_workbook(empty_summary)
    assert len(data) > 0
