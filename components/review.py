"""
Full results review: every question in a session, shown together
with its results. Used by DEFERRED reveal_mode, where nothing is
revealed question-by-question -- everything becomes visible at once
after the last question closes.
"""

from __future__ import annotations

import streamlit as st

from components import question_card
from components.results import render_question_results
from services import database as db, quiz_engine


def render_full_review(session_id: str, participant_id: str | None = None,
                        chart_type: str = "bar") -> None:
    """
    Host calls this with participant_id=None (sees group results only).
    A participant screen passes its own participant_id so each
    question also shows what THAT participant answered.
    """
    questions = quiz_engine.get_ordered_questions(session_id)
    if not questions:
        st.info("No questions in this session.")
        return

    for idx, sq in enumerate(questions):
        response = db.get_response(sq["id"], participant_id) if participant_id else None

        # Badge shown right on the collapsed row, so a participant can
        # scan pass/fail at a glance and only open the ones they got
        # wrong -- no need to expand every question just to check.
        badge = ""
        if participant_id:
            if sq["type"] == "MCQ":
                if response is None:
                    badge = " · ⬜ Not answered"
                elif response["is_correct"]:
                    badge = " · ✅ Correct"
                else:
                    badge = " · ❌ Incorrect"
            elif response is not None:
                badge = " · ✔️ Answered"
            else:
                badge = " · ⬜ Not answered"

        with st.expander(f"Question {idx + 1}: {sq['question_text']}{badge}", expanded=False):
            question_card.render_question_prompt(sq)

            if participant_id:
                if response and sq["type"] == "MCQ":
                    if response["is_correct"]:
                        st.success(
                            f"You answered **{response['answer_text']}** -- correct! "
                            f"+{response['points_awarded']} pts"
                        )
                    else:
                        st.error(f"You answered **{response['answer_text']}** -- incorrect.")
                elif response:
                    st.caption(f"Your answer: {response['answer_text']}")
                else:
                    st.caption("You didn't answer this question.")

            if sq["type"] == "MCQ" and sq.get("correct_answer"):
                st.markdown(f"✅ **Correct answer: {sq['correct_answer']}**")
            if sq["type"] == "MCQ" and sq.get("explanation"):
                st.info(f"💡 {sq['explanation']}")

            render_question_results(sq, chart_type=chart_type)
