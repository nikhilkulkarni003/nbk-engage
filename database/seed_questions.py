"""
Seeds the question bank with sample finance-training questions and
bundles them into a ready-to-run "Sample Finance Training Set".

Usage (after configuring .env and running schema.sql against your
Supabase database):

    python -m database.seed_questions

Safe to re-run: it always inserts fresh rows (question banks are
meant to be curated over time), so if you run it twice you'll get
two copies -- that's fine for trying things out, but for a real
deployment just run it once.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

SAMPLE_QUESTIONS = [
    {
        "question": "What does EBITDA stand for?",
        "type": "MCQ",
        "option_a": "Earnings Before Interest, Tax, Depreciation and Amortization",
        "option_b": "Earnings Before Income, Tax and Debt Allocation",
        "option_c": "Equity-Based Income, Tax and Depreciation Adjustment",
        "option_d": "Estimated Business Income and Tax Deduction Amount",
        "correct_answer": "A",
        "explanation": "EBITDA strips out financing and non-cash items to show core operating profitability.",
        "points": 1, "timer_seconds": 30, "category": "Accounting", "difficulty": "Easy",
    },
    {
        "question": "Under accrual accounting, revenue is recognized when...",
        "type": "MCQ",
        "option_a": "Cash is received from the customer",
        "option_b": "The invoice is printed",
        "option_c": "It is earned, regardless of when cash is received",
        "option_d": "The financial year ends",
        "correct_answer": "C",
        "explanation": "Accrual accounting matches revenue to the period it was earned, not to the cash movement.",
        "points": 1, "timer_seconds": 30, "category": "Accounting", "difficulty": "Medium",
    },
    {
        "question": "Which financial statement shows a company's financial position at a single point in time?",
        "type": "MCQ",
        "option_a": "Income Statement",
        "option_b": "Balance Sheet",
        "option_c": "Cash Flow Statement",
        "option_d": "Statement of Retained Earnings",
        "correct_answer": "B",
        "explanation": "The Balance Sheet is a snapshot of assets, liabilities and equity as of a specific date.",
        "points": 1, "timer_seconds": 30, "category": "Financial Statements", "difficulty": "Easy",
    },
    {
        "question": "A company reports strong net profit but has negative operating cash flow. This is most likely due to:",
        "type": "MCQ",
        "option_a": "A rise in receivables and inventory tying up cash",
        "option_b": "The company paying off all its debt",
        "option_c": "An accounting error that must be corrected",
        "option_d": "Depreciation being too low",
        "correct_answer": "A",
        "explanation": "Profit is an accounting measure; cash flow reflects actual cash movement. Growing "
                        "receivables/inventory consumes cash even while profit looks healthy.",
        "points": 1, "timer_seconds": 30, "category": "Profit vs Cash Flow", "difficulty": "Hard",
    },
    {
        "question": "Working capital is calculated as:",
        "type": "MCQ",
        "option_a": "Total Assets minus Total Liabilities",
        "option_b": "Current Assets minus Current Liabilities",
        "option_c": "Revenue minus Cost of Goods Sold",
        "option_d": "Net Income plus Depreciation",
        "correct_answer": "B",
        "explanation": "Working capital measures short-term liquidity: what's available to fund day-to-day operations.",
        "points": 1, "timer_seconds": 30, "category": "Working Capital", "difficulty": "Easy",
    },
    {
        "question": "Which ratio best measures a company's ability to meet short-term obligations?",
        "type": "MCQ",
        "option_a": "Debt-to-Equity Ratio",
        "option_b": "Current Ratio",
        "option_c": "Return on Equity",
        "option_d": "Gross Profit Margin",
        "correct_answer": "B",
        "explanation": "Current Ratio (Current Assets / Current Liabilities) is the classic short-term liquidity measure.",
        "points": 1, "timer_seconds": 30, "category": "Financial Ratios", "difficulty": "Medium",
    },
    {
        "question": "In BFSI, what does 'NPA' refer to?",
        "type": "MCQ",
        "option_a": "Net Payable Account",
        "option_b": "Non-Performing Asset",
        "option_c": "New Product Approval",
        "option_d": "Net Present Allocation",
        "correct_answer": "B",
        "explanation": "An NPA is a loan/advance where interest or principal has been overdue for a specified period.",
        "points": 1, "timer_seconds": 30, "category": "BFSI", "difficulty": "Easy",
    },
    {
        "question": "Which of these is a core use case of blockchain in FinTech?",
        "type": "MCQ",
        "option_a": "Faster spreadsheet formatting",
        "option_b": "Tamper-evident, decentralized transaction records",
        "option_c": "Replacing the need for financial statements",
        "option_d": "Eliminating all regulatory reporting",
        "correct_answer": "B",
        "explanation": "Blockchain's value in finance is a shared, tamper-evident ledger that reduces reconciliation friction.",
        "points": 1, "timer_seconds": 30, "category": "FinTech", "difficulty": "Medium",
    },
    {
        "question": "Which financial topic are you most keen to go deeper on today?",
        "type": "POLL",
        "option_a": "Reading a Balance Sheet",
        "option_b": "Cash Flow Analysis",
        "option_c": "Ratio Analysis",
        "option_d": "Budgeting & Forecasting",
        "correct_answer": None, "explanation": None,
        "points": 0, "timer_seconds": 30, "category": "General", "difficulty": "Easy",
    },
    {
        "question": "How confident do you feel reading a company's financial statements right now?",
        "type": "RATING",
        "option_a": None, "option_b": None, "option_c": None, "option_d": None,
        "correct_answer": None, "explanation": None,
        "points": 0, "timer_seconds": 30, "category": "Finance", "difficulty": "Easy",
        "config": {"min": 1, "max": 5, "min_label": "Not confident", "max_label": "Very confident"},
    },
    {
        "question": "In one or two words, what comes to mind when you hear 'Working Capital'?",
        "type": "WORDCLOUD",
        "option_a": None, "option_b": None, "option_c": None, "option_d": None,
        "correct_answer": None, "explanation": None,
        "points": 0, "timer_seconds": 30, "category": "Working Capital", "difficulty": "Easy",
        "config": {"min_response_length": 2},
    },
    {
        "question": "What is one financial decision your team makes that you wish you understood better?",
        "type": "OPEN_ENDED",
        "option_a": None, "option_b": None, "option_c": None, "option_d": None,
        "correct_answer": None, "explanation": None,
        "points": 0, "timer_seconds": 30, "category": "Leadership", "difficulty": "Easy",
    },
    {
        "question": "Return on Equity (ROE) measures:",
        "type": "MCQ",
        "option_a": "How efficiently a company uses shareholders' capital to generate profit",
        "option_b": "The total market value of a company",
        "option_c": "How much debt a company holds relative to equity",
        "option_d": "The dividend paid per share",
        "correct_answer": "A",
        "explanation": "ROE = Net Income / Shareholders' Equity -- a core profitability-on-capital metric.",
        "points": 1, "timer_seconds": 30, "category": "Financial Ratios", "difficulty": "Medium",
    },
    {
        "question": "Which communication skill matters most when presenting financial results to a non-finance audience?",
        "type": "MCQ",
        "option_a": "Using as much technical jargon as possible",
        "option_b": "Translating numbers into business impact and simple visuals",
        "option_c": "Reading every line item from the balance sheet aloud",
        "option_d": "Avoiding any mention of risks or bad news",
        "correct_answer": "B",
        "explanation": "Great financial communication connects numbers to decisions the audience actually needs to make.",
        "points": 1, "timer_seconds": 30, "category": "Communication", "difficulty": "Easy",
    },
]


def main() -> None:
    from services import database as db

    ok, msg = db.check_connection()
    if not ok:
        print(f"Cannot connect to the database: {msg}")
        print("Make sure DATABASE_URL is set in your .env and schema.sql has been applied.")
        sys.exit(1)

    created_ids = []
    for q in SAMPLE_QUESTIONS:
        row = dict(q)
        row.setdefault("config", {})
        created = db.create_question(**row)
        created_ids.append(created["id"])
        print(f"Added [{created['type']}] {created['question'][:60]}")

    question_set = db.create_question_set(
        title="Sample Finance Training Set",
        description="10+ sample questions covering Accounting, Financial Statements, Working Capital, "
                     "Profit vs Cash Flow, Ratios, FinTech and BFSI -- ready to run immediately.",
        category="Finance",
    )
    db.set_question_set_items(question_set["id"], created_ids)
    print(f"\nCreated question set '{question_set['title']}' with {len(created_ids)} questions.")
    print("You can now start a session from the Host screen using this set.")


if __name__ == "__main__":
    main()
