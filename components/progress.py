"""
Session progress indicator: how many questions have been worked
through so far. Shown consistently on both the host and participant
screens (in every session state, not just while a question is live)
so everyone always knows how much of the session is left.
"""

from __future__ import annotations

import streamlit as st


def render_progress(current_question_index: int, total_questions: int, status: str) -> None:
    if total_questions <= 0:
        return

    if status == "WAITING":
        position = 0
        label = f"Not started yet · {total_questions} question(s) ready"
    elif status == "SESSION_ENDED":
        position = total_questions
        label = f"All {total_questions} question(s) complete"
    else:
        position = min(current_question_index + 1, total_questions)
        label = f"Question {position} of {total_questions}"

    st.progress(position / total_questions, text=label)
