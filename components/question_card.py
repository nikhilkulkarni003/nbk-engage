"""Rendering for a question prompt and its answer controls.

Components only render UI and return the participant's chosen
action (e.g. the selected option letter) -- they never write to the
database themselves. The calling page decides what to do with the
result (submit_response, validation, rerun).
"""

from __future__ import annotations

from typing import Optional

import streamlit as st

from services.analytics import get_question_options

OPTION_EMOJIS = ["🔴", "🔵", "🟡", "🟢", "🟣", "🟠", "⚪", "🟤"]


def render_question_prompt(session_question: dict, badge: str = "") -> None:
    if badge:
        st.caption(badge)
    st.markdown(f"### {session_question['question_text']}")
    image_url = (session_question.get("config") or {}).get("image_url")
    if image_url:
        st.image(image_url, use_container_width=True)


def render_mcq_or_poll_buttons(session_question: dict, disabled: bool = False,
                                key_prefix: str = "opt") -> Optional[str]:
    options = get_question_options(session_question)
    if not options:
        st.warning("This question has no options configured.")
        return None
    clicked = None
    cols = st.columns(2)
    for i, (letter, text) in enumerate(options):
        col = cols[i % 2]
        emoji = OPTION_EMOJIS[i % len(OPTION_EMOJIS)]
        with col:
            if st.button(f"{emoji}  {text}", key=f"{key_prefix}_{letter}",
                         use_container_width=True, disabled=disabled):
                clicked = letter
    return clicked


def render_rating_buttons(session_question: dict, disabled: bool = False,
                           key_prefix: str = "rate") -> Optional[str]:
    cfg = session_question.get("config") or {}
    min_v, max_v = cfg.get("min", 1), cfg.get("max", 5)
    min_label, max_label = cfg.get("min_label", ""), cfg.get("max_label", "")
    labels_row = st.columns(2)
    with labels_row[0]:
        if min_label:
            st.caption(f"⬅ {min_label}")
    with labels_row[1]:
        if max_label:
            st.markdown(f"<div style='text-align:right'>{max_label} ➡</div>", unsafe_allow_html=True)

    clicked = None
    cols = st.columns(max_v - min_v + 1)
    for i, val in enumerate(range(min_v, max_v + 1)):
        with cols[i]:
            if st.button(f"⭐ {val}", key=f"{key_prefix}_{val}", use_container_width=True, disabled=disabled):
                clicked = str(val)
    return clicked


def render_free_text_answer(session_question: dict, disabled: bool = False,
                             key_prefix: str = "text") -> Optional[str]:
    max_len = 200
    placeholder = "Type one word or a short phrase..." if session_question["type"] == "WORDCLOUD" \
        else "Type your answer..."
    with st.form(key=f"{key_prefix}_form", clear_on_submit=True):
        text = st.text_input("Your answer", max_chars=max_len, placeholder=placeholder,
                              disabled=disabled, label_visibility="collapsed")
        submitted = st.form_submit_button("Submit", use_container_width=True, disabled=disabled)
    if submitted and text and text.strip():
        return text.strip()
    return None


def render_host_options_preview(session_question: dict) -> None:
    """Read-only options display for the host/projector screen while
    voting is open -- shows what participants are choosing between,
    without highlighting the correct answer (that stays hidden until
    the host reveals results)."""
    sq_type = session_question["type"]

    if sq_type in ("MCQ", "POLL"):
        options = get_question_options(session_question)
        if not options:
            return
        cols = st.columns(2)
        for i, (letter, text) in enumerate(options):
            emoji = OPTION_EMOJIS[i % len(OPTION_EMOJIS)]
            with cols[i % 2]:
                st.markdown(
                    f"""<div style="padding:0.9rem 1rem; margin-bottom:0.6rem; border-radius:14px;
                                background:#F1F2F9; font-size:1.1rem; font-weight:600;">
                        {emoji}&nbsp;&nbsp;{text}</div>""",
                    unsafe_allow_html=True,
                )
    elif sq_type == "RATING":
        cfg = session_question.get("config") or {}
        min_v, max_v = cfg.get("min", 1), cfg.get("max", 5)
        min_label, max_label = cfg.get("min_label", ""), cfg.get("max_label", "")
        scale = "  ".join(f"⭐{v}" for v in range(min_v, max_v + 1))
        st.markdown(f"**{scale}**")
        if min_label or max_label:
            st.caption(f"{min_label or ''}  ⟷  {max_label or ''}")
    elif sq_type in ("WORDCLOUD", "OPEN_ENDED"):
        st.caption("💬 Participants type a free-text response.")
