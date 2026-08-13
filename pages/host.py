"""
Host / trainer experience: create a session, run it question-by-
question from a presentation-friendly control room, and export
results. Optimized for laptop + projector use.

Like the participant page, the "which session is this browser tab
controlling" pointer (host_session_id) lives in st.session_state,
but every value shown on screen is re-read from the database each
poll tick -- so a host-side page refresh never loses the live
session (they just land back in the same control room).
"""

from __future__ import annotations

import os

import streamlit as st

from components import leaderboard as leaderboard_component
from components import progress as progress_component
from components import question_card
from components import results as results_component
from components import session_report as session_report_component
from components import timer as timer_component
from services import analytics, database as db, quiz_engine, session_manager
from utils import auth, qr_code
from utils.excel_export import build_session_results_workbook

POLL_SECONDS = float(os.environ.get("POLL_INTERVAL_SECONDS", "2"))

REVEAL_LABELS = {
    "MCQ": "✅ Reveal Answer",
    "POLL": "📊 Reveal Results",
    "WORDCLOUD": "☁️ Reveal Word Cloud",
    "RATING": "⭐ Reveal Ratings",
    "OPEN_ENDED": "💬 Reveal Responses",
}


def render(on_switch_role) -> None:
    if not auth.render_login_gate("Enter the trainer password to host a session."):
        return

    ok, msg = db.check_connection()
    if not ok:
        st.error(f"⚠️ Can't reach the database right now.\n\n({msg})")
        return

    top_l, top_r1, top_r2 = st.columns([4, 1, 1])
    with top_l:
        st.caption("NBK Engage · Trainer Console")
    with top_r1:
        if st.button("📚 Admin", use_container_width=True):
            on_switch_role("admin")
    with top_r2:
        if st.button("🚪 Log Out", use_container_width=True):
            auth.log_out()
            st.session_state.pop("host_session_id", None)
            on_switch_role("participant")

    host_session_id = st.session_state.get("host_session_id")
    session = db.get_session(host_session_id) if host_session_id else None

    if not session:
        st.session_state.pop("host_session_id", None)
        _render_create_session_form()
        return

    _render_control_room(session["id"])


# ---------------------------------------------------------------
# Create session
# ---------------------------------------------------------------
def _render_create_session_form() -> None:
    st.markdown('<div class="nbk-hero-title">🎯 Start a New Session</div>', unsafe_allow_html=True)

    existing_sessions = db.list_sessions(limit=10)
    live_sessions = [s for s in existing_sessions if s["status"] != "SESSION_ENDED"]
    if live_sessions:
        st.info("You have a session already in progress:")
        for s in live_sessions:
            c1, c2 = st.columns([3, 1])
            with c1:
                st.write(f"**{s['title']}** · Code `{s['session_code']}` · {s['participant_count']} joined")
            with c2:
                if st.button("Resume →", key=f"resume_{s['id']}", use_container_width=True):
                    st.session_state["host_session_id"] = s["id"]
                    st.rerun()
        st.divider()

    question_sets = db.list_question_sets()

    with st.form("create_session_form"):
        title = st.text_input("Session Title", placeholder="e.g. Finance for Non-Finance Managers - Batch 3")
        host_name = st.text_input("Trainer Name", value=st.session_state.get("nbk_host_name", "Trainer"))

        if not question_sets:
            st.warning(
                "No question sets yet. Go to **Admin → Question Bank** to add questions "
                "and build a set before starting a session."
            )
            set_options = {}
        else:
            set_options = {
                f"{qs['title']} ({qs['question_count']} questions)": qs["id"] for qs in question_sets
            }
        set_label = st.selectbox("Question Set", options=list(set_options.keys()) if set_options else ["—"])

        st.markdown("**When should results be revealed?**")
        reveal_choice = st.radio(
            "Reveal mode", label_visibility="collapsed",
            options=["Per question (reveal after each one closes)", "All at once (reveal everything at the end)"],
        )
        reveal_mode = "INSTANT" if reveal_choice.startswith("Per question") else "DEFERRED"

        anonymous_leaderboard = st.checkbox(
            "Hide participant names from each other on the leaderboard "
            "(you still see real names; export still has real names)",
            value=False,
        )

        with st.expander("⚙️ Scoring settings (optional)"):
            st.caption("Default: 1 point for a correct answer, 0 for incorrect, no time bonus.")
            base_points = st.number_input("Points for a correct MCQ answer", min_value=0,
                                           value=1, step=1)
            time_bonus = st.checkbox("Award bonus points for faster answers (Kahoot-style, up to +50%)",
                                      value=False)
            negative_marking = st.checkbox("Enable negative marking for wrong answers", value=False)
            negative_points = st.number_input("Points deducted for a wrong answer", min_value=0,
                                               value=0, step=1, disabled=not negative_marking)

        submitted = st.form_submit_button("🚀 Create Session", use_container_width=True)

    if submitted:
        if not title.strip():
            st.error("Please enter a session title.")
            return
        if not set_options:
            st.error("Please create a question set first (Admin → Question Bank).")
            return
        scoring_config = {
            "base_points": int(base_points),
            "time_bonus_enabled": bool(time_bonus),
            "negative_marking_enabled": bool(negative_marking),
            "negative_points": int(negative_points),
        }
        try:
            session = session_manager.create_session(
                title=title.strip(),
                question_set_id=set_options[set_label],
                host_name=host_name.strip() or "Trainer",
                scoring_config=scoring_config,
                reveal_mode=reveal_mode,
                anonymous_leaderboard=anonymous_leaderboard,
            )
        except ValueError as exc:
            st.error(str(exc))
            return
        st.session_state["host_session_id"] = session["id"]
        st.session_state["nbk_host_name"] = host_name
        st.rerun()


# ---------------------------------------------------------------
# Control room
# ---------------------------------------------------------------
@st.fragment(run_every=POLL_SECONDS)
def _render_control_room(session_id: str) -> None:
    # Session questions are fixed for a session's whole lifetime (never
    # added to or removed from once it starts), so the count is cached
    # per-tab after the first tick instead of being re-queried via
    # list_session_questions on every single 2-second poll.
    total_q_key = f"nbk_total_q_{session_id}"
    state = session_manager.get_full_state(session_id, st.session_state.get(total_q_key))
    if not state:
        st.warning("Session not found.")
        return
    st.session_state.setdefault(total_q_key, state["total_questions"])
    session = state["session"]
    cq = state["current_question"]

    if session["reveal_mode"] == "DEFERRED" and session["status"] in ("QUESTION_ACTIVE", "VOTING_CLOSED"):
        # All-at-once mode is fully hands-off: voting closes and the
        # session advances to the next question automatically (timer
        # expiry or everyone-answered) all the way up to the last
        # question's results -- no host click needed until the final
        # "Reveal to Participants". Pass this tick's already-fetched
        # state in so auto_advance_deferred doesn't re-query it, and
        # only re-fetch full state if a transition actually happened.
        transitioned = session_manager.auto_advance_deferred(
            session_id,
            session=state["session"],
            sq=state["current_question"],
            participant_count=state["participant_count"],
            response_count=state["response_count"],
        )
        if transitioned is not None:
            state = session_manager.get_full_state(session_id, st.session_state.get(total_q_key))
        session = state["session"]
        cq = state["current_question"]
    elif session["status"] == "QUESTION_ACTIVE":
        # Pass in what this tick already fetched instead of
        # re-querying it inside force_close_voting_if_timer_expired,
        # and use its return value directly instead of unconditionally
        # re-reading the session "just in case" afterwards -- when
        # nothing closed, the already-fetched `session` is still correct.
        updated = session_manager.force_close_voting_if_timer_expired(
            session_id, session=state["session"], sq=state["current_question"]
        )
        if updated is not None:
            session = updated

    _render_header(session, state)

    status = session["status"]
    if status == "WAITING":
        _render_waiting(session)
    elif status == "QUESTION_ACTIVE":
        _render_question_active(session, cq)
    elif status == "VOTING_CLOSED":
        _render_voting_closed(session, cq)
    elif status == "RESULTS_REVEALED":
        _render_results_revealed(session, cq)
    elif status == "LEADERBOARD":
        _render_leaderboard(session, state["total_questions"])
    elif status == "SESSION_ENDED":
        _render_session_ended(session)

    # The terminal group-summary screen (shown by _render_leaderboard
    # once there's no next question, and always by _render_session_ended)
    # already has its own Download/End Session controls -- skip the
    # generic footer there to avoid duplicate buttons.
    is_final_screen = status == "SESSION_ENDED" or (
        status == "LEADERBOARD"
        and not quiz_engine.has_next_question(session["id"], session["current_question_index"], state["total_questions"])
    )
    if not is_final_screen:
        _render_footer_controls(session)


def _chart_type_toggle(key: str) -> str:
    choice = st.radio("Chart style", options=["Bar", "Pie"], horizontal=True, key=key)
    return choice.lower()


def _render_header(session: dict, state: dict) -> None:
    total = state["total_questions"]
    mode_label = "🎁 All-at-once reveal" if session["reveal_mode"] == "DEFERRED" else "⚡ Per-question reveal"
    if session.get("anonymous_leaderboard"):
        mode_label += "  ·  🔒 Anonymous leaderboard ON"

    c1, c2, c3 = st.columns([3, 1, 1])
    with c1:
        st.markdown(f"### {session['title']}")
        st.caption(mode_label)
    with c2:
        st.metric("Participants", state["participant_count"])
    with c3:
        if state["current_question"]:
            st.metric("Responses", state["response_count"])

    progress_component.render_progress(session["current_question_index"], total, session["status"])

    with st.expander("📱 Join Info (Session Code / QR)", expanded=(session["status"] == "WAITING")):
        jc1, jc2 = st.columns([1, 1])
        with jc1:
            st.markdown(f'<div class="nbk-session-code">{session["session_code"]}</div>',
                         unsafe_allow_html=True)
            join_url = qr_code.build_join_url(session["session_code"])
            st.caption(join_url)
            st.caption(
                "Works for any device on the **same Wi-Fi/network** as this "
                "computer. If a phone can't connect, allow Python through "
                "Windows Defender Firewall, or see README.md for making the "
                "app reachable over the internet."
            )
        with jc2:
            png = qr_code.generate_qr_code_png(join_url)
            st.image(png, width=180)


def _render_waiting(session: dict) -> None:
    participants = db.list_participants(session["id"])
    st.markdown("#### Waiting for participants to join...")
    if participants:
        names = ", ".join(p["name"] for p in participants)
        st.write(names)
    else:
        st.caption("No one has joined yet. Share the code / QR code above.")
    if st.button("▶️  START SESSION", type="primary", use_container_width=True):
        try:
            session_manager.start_session(session["id"])
        except ValueError as exc:
            st.error(str(exc))
        st.rerun()


def _render_question_active(session: dict, sq: dict) -> None:
    question_card.render_question_prompt(sq)
    question_card.render_host_options_preview(sq)
    timer_component.render_timer(sq.get("started_at"), sq.get("timer_seconds"))
    st.caption("Participants are answering. Live results stay hidden until you close voting.")
    if session["reveal_mode"] == "INSTANT":
        if st.button("⏹️  CLOSE VOTING", type="primary", use_container_width=True):
            session_manager.close_voting(session["id"])
            st.rerun()
    else:
        st.caption("All-at-once mode: voting closes automatically (timer or everyone answered).")


def _render_voting_closed(session: dict, sq: dict) -> None:
    question_card.render_question_prompt(sq)
    st.success(f"🔒 Voting closed · {db.count_responses(sq['id'])} response(s) received")

    if session["reveal_mode"] == "INSTANT":
        label = REVEAL_LABELS.get(sq["type"], "Reveal Results")
        if st.button(label, type="primary", use_container_width=True):
            session_manager.reveal_answer(session["id"])
            st.rerun()
        return

    # DEFERRED: fully automatic -- the control room's poll loop already
    # advances past VOTING_CLOSED the moment it's reached (see
    # session_manager.auto_advance_deferred, called every tick in
    # _render_control_room). This screen only flashes briefly, if at
    # all, while that happens -- no host action needed here.
    st.caption("Results stay hidden -- advancing automatically, no action needed.")


def _render_results_revealed(session: dict, sq: dict) -> None:
    question_card.render_question_prompt(sq)
    if sq["type"] in ("MCQ", "POLL"):
        chart_type = _chart_type_toggle(key=f"chart_type_{sq['id']}")
    else:
        chart_type = "bar"
    results_component.render_question_results(sq, chart_type=chart_type)
    if sq["type"] == "MCQ" and sq.get("explanation"):
        st.info(f"💡 {sq['explanation']}")
    if st.button("🏆  SHOW LEADERBOARD", type="primary", use_container_width=True):
        session_manager.show_leaderboard(session["id"])
        st.rerun()


def _render_leaderboard(session: dict, known_total_questions: int | None = None) -> None:
    has_next = quiz_engine.has_next_question(session["id"], session["current_question_index"], known_total_questions)

    if not has_next:
        # Both reveal modes converge here: the last question is done,
        # nothing left to advance to. Show the full group results
        # screen instead of just a bare leaderboard.
        _render_group_summary_screen(session)
        return

    # Mid-session leaderboard (INSTANT mode only -- DEFERRED never
    # stops here, it auto-advances straight through).
    rows = analytics.get_leaderboard(session["id"])
    st.markdown("#### 🏆 Leaderboard")
    leaderboard_component.render_leaderboard(
        rows, previous_ranks_key=f"host_lb_prev_{session['id']}", anonymize=False
    )
    if st.button("➡️  NEXT QUESTION", type="primary", use_container_width=True):
        session_manager.next_question(session["id"])
        st.rerun()


def _render_excel_export(session: dict, button_label: str) -> None:
    """Building the export (a full-session analytics query -- every
    question's responses/option breakdown -- plus the pandas/openpyxl
    workbook itself) is expensive. Doing it unconditionally on every
    2-second poll tick was the dominant source of both query volume
    and CPU time on the host side. Instead, only compute it when the
    trainer explicitly clicks to (re)generate it; the bytes are then
    cached in this browser tab's session_state so subsequent ticks
    just re-display them for free until the trainer asks again. This
    is host-local UI convenience state, not shared live-session state
    -- it doesn't affect what any other browser tab sees."""
    cache_key = f"xlsx_bytes_{session['id']}"
    prep_clicked = st.button(
        f"🔄 Prepare Excel Export", key=f"prep_{cache_key}", use_container_width=True
    )
    if prep_clicked:
        summary = analytics.get_session_summary(session["id"])
        st.session_state[cache_key] = build_session_results_workbook(summary)

    workbook_bytes = st.session_state.get(cache_key)
    if workbook_bytes:
        st.download_button(
            button_label,
            data=workbook_bytes,
            file_name=f"nbk_engage_results_{session['session_code']}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            key=f"dl_{cache_key}",
        )
    else:
        st.caption("Click “Prepare Excel Export” to generate the download.")


def _render_group_summary_screen(session: dict) -> None:
    """The screen both reveal modes end at: an anonymous, group-level
    summary of the whole session, plus the controls the host needs to
    wrap up -- show the ranked leaderboard, download Excel, push the
    same summary to participants, and end the session."""
    chart_type = _chart_type_toggle(key=f"chart_type_group_summary_{session['id']}")
    session_report_component.render_session_report(session["id"], chart_type=chart_type)
    st.divider()

    show_lb_key = f"host_show_leaderboard_{session['id']}"
    if st.button("🏆  Show Leaderboard", use_container_width=True):
        st.session_state[show_lb_key] = True
    if st.session_state.get(show_lb_key):
        rows = analytics.get_leaderboard(session["id"])
        leaderboard_component.render_leaderboard(
            rows, previous_ranks_key=f"host_lb_final_{session['id']}", anonymize=False
        )

    _render_excel_export(session, "⬇️  Download Results (Excel)")

    if session.get("group_summary_revealed_at"):
        st.success("✅ Revealed to participants")
    else:
        if st.button("🌐  Reveal to Participants", type="primary", use_container_width=True):
            session_manager.reveal_group_summary_to_participants(session["id"])
            st.rerun()

    if session["status"] != "SESSION_ENDED":
        if st.button("🏁  End Session", use_container_width=True):
            session_manager.end_session(session["id"])
            st.rerun()


def _render_session_ended(session: dict) -> None:
    st.markdown("#### 🏁 Session Ended")
    _render_group_summary_screen(session)
    if st.button("➕  Start New Session", use_container_width=True):
        st.session_state.pop("host_session_id", None)
        st.rerun()


def _render_footer_controls(session: dict) -> None:
    st.markdown("---")
    c1, c2 = st.columns(2)
    with c1:
        if session["status"] != "SESSION_ENDED":
            _render_excel_export(session, "⬇️  Download Results So Far")
    with c2:
        if session["status"] != "SESSION_ENDED":
            if st.button("⏹️  END SESSION", use_container_width=True):
                session_manager.end_session(session["id"])
                st.rerun()
