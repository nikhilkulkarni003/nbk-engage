"""Tests for utils/excel_import.py: template generation and row validation."""

import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import pytest

from utils.excel_import import (
    ExcelImportError,
    REQUIRED_COLUMNS,
    generate_template_bytes,
    parse_and_validate,
)


def _build_excel_bytes(rows: list[dict]) -> bytes:
    df = pd.DataFrame(rows, columns=REQUIRED_COLUMNS)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Questions")
    return buf.getvalue()


GOOD_ROW = {
    "question": "What is EBITDA?", "type": "MCQ",
    "option_a": "Earnings before interest, tax, depreciation, amortization",
    "option_b": "Net profit", "option_c": "Gross revenue", "option_d": "Total assets",
    "correct_answer": "A", "explanation": "It's a profitability proxy.",
    "timer_seconds": 30, "category": "Finance", "difficulty": "Easy",
}

BAD_ROW = {
    "question": "", "type": "MCQ",  # missing question text
    "option_a": "A", "option_b": "", "option_c": "", "option_d": "",
    "correct_answer": "Z", "explanation": "",
    "timer_seconds": 30, "category": "Finance", "difficulty": "Easy",
}


def test_template_generates_valid_workbook():
    data = generate_template_bytes()
    assert len(data) > 0
    df = pd.read_excel(io.BytesIO(data))
    assert list(df.columns) == REQUIRED_COLUMNS
    assert len(df) >= 1


def test_all_valid_rows_pass():
    data = _build_excel_bytes([GOOD_ROW, GOOD_ROW])
    valid_rows, errors = parse_and_validate(data)
    assert len(valid_rows) == 2
    assert errors == []


def test_mixed_rows_separates_valid_and_invalid():
    data = _build_excel_bytes([GOOD_ROW, BAD_ROW])
    valid_rows, errors = parse_and_validate(data)
    assert len(valid_rows) == 1
    assert len(errors) >= 1
    assert "Row 3" in errors[0]  # header + 1 good row -> bad row is row 3


def test_missing_required_column_raises():
    df = pd.DataFrame([{"question": "x"}])
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False)
    with pytest.raises(ExcelImportError):
        parse_and_validate(buf.getvalue())


def test_empty_file_raises():
    df = pd.DataFrame(columns=REQUIRED_COLUMNS)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False)
    with pytest.raises(ExcelImportError):
        parse_and_validate(buf.getvalue())


def test_valid_row_normalizes_correct_answer_case():
    row = dict(GOOD_ROW)
    row["correct_answer"] = "a"
    data = _build_excel_bytes([row])
    valid_rows, errors = parse_and_validate(data)
    assert errors == []
    assert valid_rows[0]["correct_answer"] == "A"


def test_points_is_not_an_importable_column():
    # "points" is deliberately absent from REQUIRED_COLUMNS/the
    # template -- every imported question is fixed at 1 point,
    # regardless of what a user might put in an extra "points" column
    # in their own spreadsheet (which is just ignored, not read).
    assert "points" not in REQUIRED_COLUMNS
    data = _build_excel_bytes([GOOD_ROW, GOOD_ROW])
    valid_rows, errors = parse_and_validate(data)
    assert errors == []
    assert all(r["points"] == 1 for r in valid_rows)
