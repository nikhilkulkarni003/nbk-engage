"""
Excel import for the question bank: parses an uploaded .xlsx file,
validates every row, and returns clean records ready for
services.database.bulk_insert_questions -- plus a downloadable
template so the host knows the expected format.
"""

from __future__ import annotations

import io

import pandas as pd

from utils.validation import validate_question_dict

REQUIRED_COLUMNS = [
    "question", "type", "option_a", "option_b", "option_c", "option_d",
    "correct_answer", "explanation", "points", "timer_seconds",
    "category", "difficulty",
]

SAMPLE_ROWS = [
    {
        "question": "What does EBITDA stand for?",
        "type": "MCQ",
        "option_a": "Earnings Before Interest, Tax, Depreciation and Amortization",
        "option_b": "Earnings Before Income and Tax Deduction Adjustments",
        "option_c": "Equity Based Income Tax Deferred Asset",
        "option_d": "Estimated Business Income Tax and Duty Allowance",
        "correct_answer": "A",
        "explanation": "EBITDA is a proxy for operating cash profitability, excluding financing and non-cash items.",
        "points": 1000,
        "timer_seconds": 30,
        "category": "Finance",
        "difficulty": "Easy",
    },
    {
        "question": "Which training topic are you most excited about today?",
        "type": "POLL",
        "option_a": "Financial Statements",
        "option_b": "Working Capital",
        "option_c": "Ratio Analysis",
        "option_d": "FinTech Trends",
        "correct_answer": "",
        "explanation": "",
        "points": 0,
        "timer_seconds": 20,
        "category": "General",
        "difficulty": "Easy",
    },
]


class ExcelImportError(ValueError):
    pass


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
    return df


def parse_and_validate(file_bytes: bytes) -> tuple[list[dict], list[str]]:
    """Returns (valid_rows, error_messages). Raises ExcelImportError if
    the file itself can't be read or is missing required columns."""
    try:
        df = pd.read_excel(io.BytesIO(file_bytes), engine="openpyxl")
    except Exception as exc:  # noqa: BLE001
        raise ExcelImportError(f"Could not read the Excel file: {exc}") from exc

    if df.empty:
        raise ExcelImportError("The uploaded file has no rows.")

    df = _normalize_columns(df)
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ExcelImportError(
            f"Missing required column(s): {', '.join(missing)}. "
            f"Download the template for the exact expected format."
        )

    valid_rows: list[dict] = []
    errors: list[str] = []

    for idx, raw_row in df.iterrows():
        row_label = f"Row {idx + 2}"  # +2: 1-indexed + header row
        row = {c: (None if pd.isna(raw_row[c]) else raw_row[c]) for c in REQUIRED_COLUMNS}

        row_errors = validate_question_dict(row, row_label=row_label)
        if row_errors:
            errors.extend(row_errors)
            continue

        clean = {
            "question": str(row["question"]).strip(),
            "type": str(row["type"]).strip().upper(),
            "option_a": _clean_str(row.get("option_a")),
            "option_b": _clean_str(row.get("option_b")),
            "option_c": _clean_str(row.get("option_c")),
            "option_d": _clean_str(row.get("option_d")),
            "correct_answer": _clean_str(row.get("correct_answer")),
            "explanation": _clean_str(row.get("explanation")),
            "points": int(row["points"]) if row.get("points") not in (None, "") else 1000,
            "timer_seconds": int(row["timer_seconds"]) if row.get("timer_seconds") not in (None, "") else 30,
            "category": _clean_str(row.get("category")) or "General",
            "difficulty": (_clean_str(row.get("difficulty")) or "Medium").title(),
        }
        if clean["correct_answer"]:
            clean["correct_answer"] = clean["correct_answer"].upper()
        valid_rows.append(clean)

    return valid_rows, errors


def _clean_str(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def generate_template_bytes() -> bytes:
    df = pd.DataFrame(SAMPLE_ROWS, columns=REQUIRED_COLUMNS)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Questions")
    return buf.getvalue()
