"""
Live/reviewed results rendering for every question type.

Per-question results (this module) are always anonymous by design --
they show option letters and percentages/counts, never who picked
what. Real participant names only ever appear on the leaderboard
(components/leaderboard.py) and in the host's Excel export, which is
a deliberate separation: participants can see how the group answered
without seeing who got what wrong.
"""

from __future__ import annotations

import html

import streamlit as st

BAR_COLOR = "#5B5FEF"
CORRECT_COLOR = "#26890C"
PIE_COLORS = ["#5B5FEF", "#26890C", "#D89E00", "#E21B3C",
              "#8B2FC9", "#0F9B8E", "#FF7A45", "#4A5568"]


def render_results_bars(results: list[dict], reveal_correct: bool = False) -> None:
    if not results:
        st.info("No responses yet.")
        return

    for opt in results:
        letter = opt["letter"]
        text = html.escape(opt["option_text"] or "")
        pct = opt["pct"]
        count = opt["count"]
        is_correct = opt.get("is_correct") and reveal_correct
        bar_color = CORRECT_COLOR if is_correct else BAR_COLOR
        check = " ✅" if is_correct else ""

        st.markdown(
            f"""
            <div style="margin-bottom:14px;">
              <div style="display:flex; justify-content:space-between; font-weight:600; margin-bottom:4px;">
                <span>{letter}. {text}{check}</span>
                <span>{pct}% ({count})</span>
              </div>
              <div style="background:#E9E9F5; border-radius:8px; height:22px; width:100%;">
                <div style="background:{bar_color}; width:{max(pct, 2)}%; height:22px; border-radius:8px;
                            transition: width 0.4s ease;"></div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_results_pie(results: list[dict], reveal_correct: bool = False) -> None:
    """A dependency-free donut chart built from a CSS conic-gradient,
    plus a legend -- an alternative to the bar view for the same
    anonymous option-level percentages."""
    if not results:
        st.info("No responses yet.")
        return

    total = sum(r["count"] for r in results)
    segments = []
    cursor = 0.0
    for i, opt in enumerate(results):
        color = PIE_COLORS[i % len(PIE_COLORS)]
        share = (opt["count"] / total * 100) if total else (100 / len(results))
        start, end = cursor, cursor + share
        segments.append(f"{color} {start:.2f}% {end:.2f}%")
        cursor = end
    gradient = ", ".join(segments) if total else "#E9E9F5 0% 100%"

    legend_rows = []
    for i, opt in enumerate(results):
        color = PIE_COLORS[i % len(PIE_COLORS)]
        text = html.escape(opt["option_text"] or "")
        check = " ✅" if (opt.get("is_correct") and reveal_correct) else ""
        legend_rows.append(
            f"""<div style="display:flex; align-items:center; gap:8px; margin-bottom:6px;">
                <span style="width:14px; height:14px; border-radius:4px; background:{color};
                             display:inline-block; flex-shrink:0;"></span>
                <span style="flex:1;">{opt['letter']}. {text}{check}</span>
                <span style="font-weight:600;">{opt['pct']}% ({opt['count']})</span>
            </div>"""
        )

    st.markdown(
        f"""
        <div style="display:flex; gap:28px; align-items:center; flex-wrap:wrap;">
          <div style="width:160px; height:160px; border-radius:50%; flex-shrink:0;
                      background: conic-gradient({gradient});"></div>
          <div style="flex:1; min-width:200px;">{''.join(legend_rows)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_option_results(results: list[dict], reveal_correct: bool = False,
                           chart_type: str = "bar") -> None:
    if chart_type == "pie":
        render_results_pie(results, reveal_correct=reveal_correct)
    else:
        render_results_bars(results, reveal_correct=reveal_correct)


def render_rating_summary(summary: dict) -> None:
    if summary["total"] == 0:
        st.info("No responses yet.")
        return
    st.metric("Average rating", f'{summary["average"]} / 5')
    for value in range(1, 6):
        count = summary["distribution"].get(value, 0)
        pct = round((count / summary["total"]) * 100, 1) if summary["total"] else 0
        st.markdown(
            f"""
            <div style="margin-bottom:10px;">
              <div style="display:flex; justify-content:space-between;">
                <span>{"⭐" * value}</span><span>{count} ({pct}%)</span>
              </div>
              <div style="background:#E9E9F5; border-radius:8px; height:16px; width:100%;">
                <div style="background:{BAR_COLOR}; width:{max(pct, 2)}%; height:16px; border-radius:8px;"></div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_open_ended_list(responses: list[dict]) -> None:
    if not responses:
        st.info("No responses yet.")
        return
    for r in responses:
        name = html.escape(r["participant_name"])
        text = html.escape(r["answer_text"])
        st.markdown(
            f"""<div style="padding:10px 14px; background:#F1F2F9; border-radius:10px; margin-bottom:8px;">
                <b>{name}:</b> {text}</div>""",
            unsafe_allow_html=True,
        )


def render_question_results(session_question: dict, chart_type: str = "bar",
                             responses: list[dict] | None = None) -> None:
    """Dispatches to the right renderer for a session_question's
    type. Shared by the host control room and the participant/host
    'review all questions' screen (DEFERRED reveal_mode), so both use
    identical rendering logic.

    `responses`, if provided, must already be this question's response
    rows (see services/analytics.py::get_session_report, which fetches
    the whole session's responses in one query and groups them by
    question) -- passing it through here avoids each question's
    expander on the Group Results screen re-querying independently.
    Falls back to querying per-question when not supplied, which is
    correct for the single-current-question call sites (live
    QUESTION_ACTIVE/RESULTS_REVEALED screens)."""
    from services import analytics, database as db
    from components.wordcloud import render_wordcloud

    sq_type = session_question["type"]
    if sq_type in ("MCQ", "POLL"):
        results = analytics.get_option_results(session_question, responses)
        render_option_results(results, reveal_correct=(sq_type == "MCQ"), chart_type=chart_type)
    elif sq_type == "RATING":
        render_rating_summary(analytics.get_rating_summary(session_question["id"], responses))
    elif sq_type == "WORDCLOUD":
        cfg = session_question.get("config") or {}
        min_len = cfg.get("min_response_length", 2)
        freq = analytics.get_word_frequencies(session_question["id"], min_length=min_len, responses=responses)
        count = len(responses) if responses is not None else db.count_responses(session_question["id"])
        render_wordcloud(freq, count)
    elif sq_type == "OPEN_ENDED":
        render_open_ended_list(analytics.get_open_ended_responses(session_question["id"], responses))
