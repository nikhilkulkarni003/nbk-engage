"""
In-browser group results: overall accuracy + per-question
correct/incorrect breakdown, viewable directly on screen (not just
as an Excel download). This is fully anonymous by construction --
option-level counts/percentages only, never a name against an
answer. Shown on the host's final "Group Results" screen (both
reveal modes converge there), on "Session Ended", from Admin ->
Sessions & Results for any past session, and pushed to participants
via the host's "Reveal to Participants" action.
"""

from __future__ import annotations

import html

import streamlit as st

from components.results import render_question_results
from services import analytics


def _donut(pct: float) -> str:
    pct = max(0.0, min(100.0, pct))
    return f"""
    <div style="display:flex; align-items:center; gap:10px;">
      <div style="position:relative; width:150px; height:150px;">
        <div style="width:150px; height:150px; border-radius:50%;
                    background: conic-gradient(#26890C 0% {pct}%, #E21B3C {pct}% 100%);"></div>
        <div style="position:absolute; inset:18px; border-radius:50%; background:white;
                    display:flex; flex-direction:column; align-items:center; justify-content:center;">
          <div style="font-size:1.6rem; font-weight:800;">{pct:.0f}%</div>
          <div style="font-size:0.75rem; color:#6b6b7a;">Correct</div>
        </div>
      </div>
    </div>
    """


def render_session_report(session_id: str, chart_type: str = "bar",
                           show_sort: bool = True) -> None:
    report = analytics.get_session_report(session_id)

    st.markdown("#### 📊 Group Results")

    top_l, top_r = st.columns([1, 2])
    with top_l:
        st.markdown(_donut(report["overall_accuracy_pct"]), unsafe_allow_html=True)
    with top_r:
        m1, m2 = st.columns(2)
        with m1:
            st.metric("👥 Participants", report["total_participants"])
            st.metric("❓ Total Questions", report["total_questions"])
        with m2:
            st.metric("🎯 Group Accuracy", f'{report["overall_accuracy_pct"]}%')
            st.metric("⭐ Average Score", report["avg_score_per_participant"])

    if not report["per_question"]:
        return

    st.markdown("##### Question breakdown")

    if show_sort:
        sort_choice = st.radio(
            "Sort by", options=["Question #", "Incorrect %"], horizontal=True,
            key=f"report_sort_{session_id}", label_visibility="collapsed",
        )
    else:
        sort_choice = "Question #"

    rows = list(report["per_question"])
    if sort_choice == "Incorrect %":
        rows.sort(key=lambda r: (r["accuracy_pct"] if r["accuracy_pct"] is not None else -1))
    else:
        rows.sort(key=lambda r: r["order_index"])

    for row in rows:
        q_num = row["order_index"] + 1
        title = html.escape(row["question_text"])
        if row["accuracy_pct"] is not None:
            answered = row["correct_count"] + row["incorrect_count"]
            badge = f'{row["correct_count"]} of {answered} answered correctly ({row["accuracy_pct"]}%)'
        else:
            badge = f'{row["response_count"]} response(s)'
        with st.expander(f"Q{q_num}: {title}  —  {badge}"):
            sq = row["session_question"]
            if sq["type"] == "MCQ" and sq.get("explanation"):
                st.info(f"💡 {sq['explanation']}")
            render_question_results(sq, chart_type=chart_type, responses=row.get("responses"))
