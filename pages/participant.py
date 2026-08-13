"""
Participant experience: join -> wait -> question -> answer -> result
-> next question ... -> final leaderboard.

No login. Identity for a browser tab is just (participant_id,
session_id) held in st.session_state -- purely local UI state that
tells this tab *which* database rows to read. The actual session
state, question, timer and results always come fresh from the
database on every poll tick, so a page refresh never loses shared
state (only the "which session am I in" pointer, which is why we
re-validate everything against the DB below).
"""

from __future__ import annotations

import os
import time

import streamlit as st

from components import progress as progress_component
from components import question_card, timer as timer_component
from components.leaderboard import render_leaderboard as render_lb
from components.results import render_rating_summary, render_results_bars
from components.review import render_full_review
from components.session_report import render_session_report
from services import analytics, database as db, diagnostics, quiz_engine, session_manager

POLL_SECONDS = float(os.environ.get("POLL_INTERVAL_SECONDS", "2"))

# last_seen_at is presence-telemetry only (not currently read/displayed
# anywhere in the app), so it doesn't need a DB write on every single
# poll tick -- throttling it to roughly every 4th tick cuts a chunk of
# per-participant write volume with no visible behavior change.
TOUCH_MIN_INTERVAL_SECONDS = 8.0


def render(on_switch_role) -> None:
    ok, msg = db.check_connection()
    if not ok:
        st.error(f"⚠️ Can't reach the database right now. Please try again shortly.\n\n({msg})")
        return

    if not st.session_state.get("p_participant_id"):
        _render_join_screen(on_switch_role)
        return

    session = db.get_session(st.session_state["p_session_id"])
    if not session:
        st.warning("This session no longer exists.")
        _render_leave_button()
        return

    participant = db.get_participant(st.session_state["p_participant_id"])
    if not participant:
        st.warning("We couldn't find your participant record (maybe the session was reset).")
        _render_leave_button()
        return

    _render_session_screen(session, participant)


def _render_join_screen(on_switch_role) -> None:
    st.markdown('<div class="nbk-hero-title">🎯 NBK Engage</div>', unsafe_allow_html=True)
    st.markdown('<div class="nbk-hero-subtitle">Join a live training session</div>', unsafe_allow_html=True)

    prefill_code = st.query_params.get("join", "")

    with st.form("join_form"):
        code = st.text_input("Session Code", value=prefill_code, max_chars=6,
                              placeholder="123456")
        name = st.text_input("Your Name", max_chars=40, placeholder="e.g. Rahul Sharma")
        submitted = st.form_submit_button("Join Session →", use_container_width=True)

    if submitted:
        _handle_join(code, name)

    st.markdown("<br>", unsafe_allow_html=True)
    with st.expander("Are you the trainer?"):
        if st.button("Trainer / Host Login", use_container_width=True):
            on_switch_role("host")


def _handle_join(code: str, name: str) -> None:
    from utils.validation import validate_participant_name, validate_session_code

    ok_code, code_or_err = validate_session_code(code)
    if not ok_code:
        st.error(code_or_err)
        return
    ok_name, name_or_err = validate_participant_name(name)
    if not ok_name:
        st.error(name_or_err)
        return

    session = db.get_session_by_code(code_or_err)
    if not session:
        st.error("We couldn't find a session with that code. Double-check with your trainer.")
        return

    # A name that already exists in this session is treated as the same
    # person reconnecting (e.g. after a page refresh or a dropped phone
    # connection) rather than a hard collision -- this is what makes
    # "participant refresh" recoverable without losing their score.
    # It also means someone can reconnect to see final results even
    # after the session has ended.
    existing = db.find_participant_by_name(session["id"], name_or_err)
    if existing:
        participant = existing
    elif session["status"] == "SESSION_ENDED":
        st.error("This session has already ended.")
        return
    else:
        try:
            participant = db.join_session(session["id"], name_or_err)
        except db.DuplicateNameError as exc:
            st.error(str(exc))
            return
        except Exception:  # noqa: BLE001
            st.error("Something went wrong while joining. Please try again.")
            return

    st.session_state["p_participant_id"] = participant["id"]
    st.session_state["p_session_id"] = session["id"]
    st.query_params.clear()
    st.rerun()


def _render_leave_button() -> None:
    if st.button("← Leave / Rejoin"):
        for key in ("p_participant_id", "p_session_id"):
            st.session_state.pop(key, None)
        st.rerun()


@st.fragment(run_every=POLL_SECONDS)
def _render_session_screen(session_static: dict, participant_static: dict) -> None:
    # TEMPORARY diagnostics (see services/diagnostics.py) -- start_poll/
    # end_poll bracket the whole fragment execution; the try/finally
    # guarantees end_poll (and its summary line) always fires, even on
    # an early return or an unhandled exception.
    diagnostics.start_poll("PARTICIPANT_POLL")
    diagnostics.mark("fragment_start")
    try:
        session_id = session_static["id"]
        participant_id = participant_static["id"]

        session = db.get_session(session_id)
        diagnostics.mark("get_session_done")
        if not session:
            st.warning("This session no longer exists.")
            return
        participant = db.get_participant(participant_id)
        diagnostics.mark("get_participant_done")
        if not participant:
            st.warning("Your participant record was not found.")
            return

        touch_key = f"nbk_last_touch_{participant_id}"
        now = time.monotonic()
        if now - st.session_state.get(touch_key, 0.0) >= TOUCH_MIN_INTERVAL_SECONDS:
            db.touch_participant(participant_id)
            st.session_state[touch_key] = now
            diagnostics.mark("touch_participant_done(executed=True)")
        else:
            diagnostics.mark("touch_participant_done(executed=False, throttled)")

        st.markdown(f"**{session['title']}**  ·  👤 {participant['name']}")
        status = session["status"]
        # Session questions are fixed for the session's whole lifetime, so
        # the count is cached per-tab after the first tick instead of
        # being re-queried via list_session_questions on every poll tick.
        total_q_key = f"nbk_total_q_{session_id}"
        cached_total = st.session_state.get(total_q_key)
        total_questions = quiz_engine.total_questions(session_id, cached_total)
        st.session_state.setdefault(total_q_key, total_questions)
        diagnostics.mark(f"total_questions_done(cache_hit={cached_total is not None})")
        progress_component.render_progress(session["current_question_index"], total_questions, status)

        if status == "WAITING":
            _render_waiting(session)
        elif status == "SESSION_ENDED":
            _render_session_ended(session, participant)
        else:
            diagnostics.mark("before_get_session_question")
            sq = db.get_session_question(session["current_session_question_id"]) if session.get(
                "current_session_question_id") else None
            diagnostics.mark("after_get_session_question")
            if not sq:
                _render_waiting(session)
                return
            if status == "QUESTION_ACTIVE":
                _render_question_active(session, sq, participant)
            elif status == "VOTING_CLOSED":
                _render_voting_closed(sq, participant)
            elif status == "RESULTS_REVEALED":
                _render_results(sq, participant)
            elif status == "LEADERBOARD":
                _render_leaderboard(session, participant)

        st.markdown("---")
        diagnostics.mark("main_render_done")
    finally:
        diagnostics.end_poll(pool_stats=db.get_pool_stats(), label="PARTICIPANT_POLL")
    _render_leave_button()


def _render_waiting(session: dict) -> None:
    st.info("⏳ Waiting for the host to start the session...")
    count = db.count_participants(session["id"])
    st.caption(f"{count} participant(s) have joined so far.")


def _render_question_active(session: dict, sq: dict, participant: dict) -> None:
    existing = db.get_response(sq["id"], participant["id"])
    diagnostics.mark("get_response_done")

    question_card.render_question_prompt(sq)
    diagnostics.mark("question_rendering_done")
    remaining = timer_component.render_timer(sq.get("started_at"), sq.get("timer_seconds"))
    diagnostics.mark("timer_rendering_done")

    if existing:
        st.success("✅ Answer submitted! Waiting for the host...")
        return

    if remaining == 0:
        st.warning("⏰ Time's up! Waiting for the host to close voting.")
        return

    answer = None
    if sq["type"] in ("MCQ", "POLL"):
        answer = question_card.render_mcq_or_poll_buttons(sq, key_prefix=f"ans_{sq['id']}")
    elif sq["type"] == "RATING":
        answer = question_card.render_rating_buttons(sq, key_prefix=f"rate_{sq['id']}")
    elif sq["type"] in ("WORDCLOUD", "OPEN_ENDED"):
        answer = question_card.render_free_text_answer(sq, key_prefix=f"text_{sq['id']}")

    if answer is not None:
        _submit(session["id"], sq["id"], participant["id"], answer)


def _submit(session_id: str, sq_id: str, participant_id: str, answer: str) -> None:
    from utils.validation import validate_free_text_answer

    if len(answer) > 200:
        st.error("Response is too long.")
        return
    ok, _ = validate_free_text_answer(answer, min_length=1, max_length=200)
    if not ok:
        st.error("Please enter a valid response.")
        return
    try:
        session_manager.submit_answer(session_id, sq_id, participant_id, answer)
        st.rerun()
    except session_manager.VotingClosedError:
        st.warning("Voting just closed -- your answer arrived a moment too late.")
    except db.DuplicateAnswerError:
        st.info("You've already answered this question.")
        st.rerun()
    except session_manager.SessionEndedError:
        st.warning("This session has ended.")
    except Exception:  # noqa: BLE001
        st.error("Couldn't submit your answer. Please try again.")


def _render_voting_closed(sq: dict, participant: dict) -> None:
    st.caption("🔒 Voting closed")
    question_card.render_question_prompt(sq)
    existing = db.get_response(sq["id"], participant["id"])
    if existing:
        st.success(f"You answered: **{existing['answer_text']}**")
    else:
        st.info("You didn't answer in time.")
    st.info("⏳ Waiting for the host to reveal results...")


def _render_results(sq: dict, participant: dict) -> None:
    question_card.render_question_prompt(sq)
    existing = db.get_response(sq["id"], participant["id"])

    if sq["type"] == "MCQ":
        if existing:
            if existing["is_correct"]:
                st.success(f"🎉 Correct! You earned **{existing['points_awarded']}** points.")
            else:
                st.error("Not quite.")
        else:
            st.info("You didn't answer in time.")
        correct = sq.get("correct_answer")
        if correct:
            st.markdown(f"✅ **Correct answer: {correct}**")
        if sq.get("explanation"):
            st.info(sq["explanation"])
        render_results_bars(analytics.get_option_results(sq), reveal_correct=True)
    elif sq["type"] == "POLL":
        render_results_bars(analytics.get_option_results(sq), reveal_correct=False)
    elif sq["type"] == "RATING":
        render_rating_summary(analytics.get_rating_summary(sq["id"]))
    else:
        st.success("🙌 Thanks! Your response has been added to the group results on the main screen.")

    st.info("⏳ Waiting for the host...")


def _render_leaderboard(session: dict, participant: dict) -> None:
    has_next = quiz_engine.has_next_question(session["id"], session["current_question_index"])

    if not has_next:
        # Both reveal modes converge here -- the final, anonymous group
        # results, gated behind the host's explicit "Reveal to
        # Participants" click.
        _render_group_results_for_participant(session, participant)
        st.divider()

    rows = analytics.get_leaderboard(session["id"])
    my_row = next((r for r in rows if r["participant_id"] == participant["id"]), None)
    if my_row:
        st.markdown(
            f"### Your rank: #{my_row['rank']} · {my_row['total_score']:,} pts"
        )
    st.markdown("#### 🏆 Leaderboard")
    render_lb(rows[:10], previous_ranks_key=f"p_lb_prev_{session['id']}",
              anonymize=session.get("anonymous_leaderboard", False))
    if has_next:
        st.info("⏳ Waiting for the host to continue...")


def _render_group_results_for_participant(session: dict, participant: dict) -> None:
    if not session.get("group_summary_revealed_at"):
        st.info("⏳ Waiting for the host to share the results...")
        return
    render_session_report(session["id"], chart_type="bar", show_sort=False)
    with st.expander("📋 Your Answers", expanded=False):
        render_full_review(session["id"], participant_id=participant["id"])


def _render_session_ended(session: dict, participant: dict) -> None:
    st.balloons()
    st.markdown("## 🏁 Session Ended")

    _render_group_results_for_participant(session, participant)
    st.divider()

    rows = analytics.get_leaderboard(session["id"])
    my_row = next((r for r in rows if r["participant_id"] == participant["id"]), None)
    if my_row:
        st.markdown(f"### Your final rank: #{my_row['rank']} · {my_row['total_score']:,} pts")
    st.markdown("#### Final Leaderboard")
    render_lb(rows[:10], previous_ranks_key=f"p_lb_final_{session['id']}",
              anonymize=session.get("anonymous_leaderboard", False))
    st.markdown("Thanks for participating! 🎉")
