"""
Participant experience: join -> wait -> question -> answer -> result
-> next question ... -> final leaderboard.

No login. Identity for a browser tab is just (participant_id,
session_id) held in st.session_state -- purely local UI state that
tells this tab *which* database rows to read. The actual session
state, question and results always come fresh from the database, so a
page refresh never loses shared state (only the "which session am I
in" pointer, which is why we re-validate everything against the DB
below). Host-paced sessions have no timer -- voting stays open until
the host explicitly closes it.

Rendering is deliberately split two ways so the auto-refresh needed
for live polling doesn't grey out the question/answer UI while a
participant is reading or about to tap an option:
  - _poll_for_changes: a tiny @st.fragment(run_every=...) that renders
    nothing, just detects whether shared state changed and triggers a
    full st.rerun() when it has.
  - _render_session_body: a plain function (not a fragment) that does
    the actual rendering, invoked on load and on real transitions only.
"""

from __future__ import annotations

import os
import time

import streamlit as st

from components import progress as progress_component
from components import question_card
from components.review import render_full_review
from services import database as db, diagnostics, quiz_engine, session_manager

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

    session_id = st.session_state["p_session_id"]
    participant_id = st.session_state["p_participant_id"]

    session = db.get_session(session_id)
    if not session:
        st.warning("This session no longer exists.")
        _render_leave_button()
        return

    participant = db.get_participant(participant_id)
    if not participant:
        st.warning("We couldn't find your participant record (maybe the session was reset).")
        _render_leave_button()
        return

    # Lightweight background poll (~3 queries, renders nothing itself)
    # that only triggers a full-page st.rerun() when shared session
    # state has actually changed -- see _poll_for_changes. The actual
    # question/answer UI (_render_session_body) is a plain function,
    # NOT an auto-refreshing fragment, so it is never greyed out by
    # Streamlit's per-fragment refresh while a participant is reading
    # the question or about to tap an option; it only re-renders when
    # a real transition happens (or on initial load / a user action).
    _poll_for_changes(session_id, participant_id)

    _render_session_body(session, participant)


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
def _poll_for_changes(session_id: str, participant_id: str) -> None:
    """The ONLY thing that auto-refreshes every POLL_SECONDS. Renders
    nothing -- it just checks whether shared session state has changed
    since this browser tab last rendered (question advanced, voting
    closed, results revealed, someone else joined, etc.) via a cheap
    ~3-query fingerprint, and calls st.rerun() (a full page rerun) only
    when it has. Because it renders no UI, there is nothing for
    Streamlit's per-fragment refresh dimming to grey out -- the actual
    question/answer widgets live in _render_session_body, a plain
    function outside any fragment, so they stay static and tappable
    between real transitions instead of flashing on every tick."""
    diagnostics.start_poll("PARTICIPANT_POLL")
    diagnostics.mark("fragment_start")
    try:
        session = db.get_session(session_id)
        diagnostics.mark("get_session_done")
        if not session:
            return

        sq_id = session.get("current_session_question_id")
        my_response = db.get_response(sq_id, participant_id) if sq_id else None
        diagnostics.mark("get_response_done")

        participant_count = db.count_participants(session_id)
        diagnostics.mark("count_participants_done")

        fingerprint = (
            session["status"],
            session["current_question_index"],
            sq_id,
            my_response["id"] if my_response else None,
            session.get("group_summary_revealed_at"),
            participant_count,
        )
        fp_key = f"nbk_p_fingerprint_{session_id}_{participant_id}"
        if st.session_state.get(fp_key) != fingerprint:
            st.session_state[fp_key] = fingerprint
            diagnostics.mark("change_detected_triggering_rerun")
            st.rerun()
        else:
            diagnostics.mark("no_change_detected")
    finally:
        diagnostics.end_poll(pool_stats=db.get_pool_stats(), label="PARTICIPANT_POLL")


def _render_session_body(session: dict, participant: dict) -> None:
    """The actual question/answer UI. NOT an auto-refreshing fragment --
    runs once on initial load and again only when _poll_for_changes
    detects a real transition (or on any normal user interaction,
    e.g. clicking an answer button, same as any other Streamlit
    widget). See the module docstring and _poll_for_changes above."""
    diagnostics.start_poll("PARTICIPANT_RENDER")
    diagnostics.mark("render_start")
    try:
        session_id = session["id"]
        participant_id = participant["id"]

        touch_key = f"nbk_last_touch_{participant_id}"
        now = time.monotonic()
        if now - st.session_state.get(touch_key, 0.0) >= TOUCH_MIN_INTERVAL_SECONDS:
            db.touch_participant(participant_id)
            st.session_state[touch_key] = now

        st.markdown(f"**{session['title']}**  ·  👤 {participant['name']}")
        status = session["status"]
        # Session questions are fixed for the session's whole lifetime, so
        # the count is cached per-tab after the first tick instead of
        # being re-queried via list_session_questions on every render.
        total_q_key = f"nbk_total_q_{session_id}"
        cached_total = st.session_state.get(total_q_key)
        total_questions = quiz_engine.total_questions(session_id, cached_total)
        st.session_state.setdefault(total_q_key, total_questions)
        progress_component.render_progress(session["current_question_index"], total_questions, status)

        if status == "WAITING":
            _render_waiting(session)
        elif status == "SESSION_ENDED":
            _render_session_ended(session, participant)
        elif status == "SELF_PACED_ACTIVE":
            _render_self_paced_active(session, participant)
        elif status == "LEADERBOARD":
            # Handled at this level, NOT inside the "needs a current
            # question" branch below -- SELF_PACED sessions never set
            # current_session_question_id, so nesting this inside that
            # branch (as it used to be) meant self-paced sessions
            # reaching LEADERBOARD fell through to "waiting for the
            # host to start" instead of ever showing the leaderboard/
            # reveal. _render_leaderboard doesn't need sq at all.
            _render_leaderboard(session, participant)
        else:
            diagnostics.mark("before_get_current_question")
            sq = db.get_session_question(session["current_session_question_id"]) if session.get(
                "current_session_question_id") else None
            diagnostics.mark("after_get_current_question")
            if not sq:
                _render_waiting(session)
                return
            if status == "QUESTION_ACTIVE":
                _render_question_active(session, sq, participant)
            elif status == "VOTING_CLOSED":
                _render_voting_closed(sq, participant)
            elif status == "RESULTS_REVEALED":
                _render_results(sq, participant)

        st.markdown("---")
        _render_leave_button()
        diagnostics.mark("render_done")
    finally:
        diagnostics.end_poll(pool_stats=db.get_pool_stats(), label="PARTICIPANT_RENDER")


def _render_waiting(session: dict) -> None:
    st.info("⏳ Waiting for the host to start the session...")
    count = db.count_participants(session["id"])
    st.caption(f"{count} participant(s) have joined so far.")


def _render_question_active(session: dict, sq: dict, participant: dict) -> None:
    # Host-paced sessions have no timer -- voting stays open until the
    # host explicitly closes it (see pages/host.py::_render_question_active),
    # so this only needs to check whether this participant has already
    # answered, not any time-based cutoff.
    existing = db.get_response(sq["id"], participant["id"])
    diagnostics.mark("get_response_done")

    question_card.render_question_prompt(sq)
    diagnostics.mark("question_rendering_done")

    if existing:
        st.success("✅ Answer submitted! Waiting for the host...")
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


def _render_self_paced_active(session: dict, participant: dict) -> None:
    """SELF_PACED pacing_mode: there is no single shared current
    question, so each participant works out their own next one
    locally -- the full question list is fetched once and cached for
    the rest of the session (it's immutable), and "which one is next"
    is computed from this participant's own responses (answered or
    skipped) with no server round trip needed beyond those two reads.
    Submitting/skipping writes immediately (see submit_answer_or_skip)
    and reruns, so the very next script pass just recomputes the next
    question from the now-updated response list -- no polling needed
    to advance, it's entirely driven by the participant's own action."""
    session_id = session["id"]
    participant_id = participant["id"]

    q_cache_key = f"nbk_sp_questions_{session_id}"
    if q_cache_key not in st.session_state:
        st.session_state[q_cache_key] = quiz_engine.get_ordered_questions(session_id)
    questions = st.session_state[q_cache_key]

    if not questions:
        st.info("This session has no questions.")
        return

    my_responses = db.list_responses_for_participant(session_id, participant_id)
    diagnostics.mark("list_responses_for_participant_done")
    done_ids = {r["session_question_id"] for r in my_responses}
    remaining = [q for q in questions if q["id"] not in done_ids]
    total = len(questions)
    done_count = total - len(remaining)

    progress_component.render_progress(done_count, total, "QUESTION_ACTIVE")

    if not remaining:
        st.success("✅ You've answered every question!")
        st.info("⏳ Waiting for the host to close the session and share results...")
        return

    sq = remaining[0]
    question_card.render_question_prompt(sq)

    answer = None
    if sq["type"] in ("MCQ", "POLL"):
        answer = question_card.render_mcq_or_poll_buttons(sq, key_prefix=f"sp_ans_{sq['id']}")
    elif sq["type"] == "RATING":
        answer = question_card.render_rating_buttons(sq, key_prefix=f"sp_rate_{sq['id']}")
    elif sq["type"] in ("WORDCLOUD", "OPEN_ENDED"):
        answer = question_card.render_free_text_answer(sq, key_prefix=f"sp_text_{sq['id']}")

    if answer is not None:
        _submit_self_paced(session_id, sq["id"], participant_id, answer, is_skipped=False)

    if st.button("⏭️  Skip this question", use_container_width=True, key=f"sp_skip_{sq['id']}"):
        _submit_self_paced(session_id, sq["id"], participant_id, None, is_skipped=True)


def _submit_self_paced(session_id: str, sq_id: str, participant_id: str,
                        answer: str | None, is_skipped: bool) -> None:
    if not is_skipped:
        from utils.validation import validate_free_text_answer

        if answer is None or len(answer) > 200:
            st.error("Response is too long.")
            return
        ok, _ = validate_free_text_answer(answer, min_length=1, max_length=200)
        if not ok:
            st.error("Please enter a valid response.")
            return
    try:
        session_manager.submit_answer_or_skip(
            session_id, sq_id, participant_id, answer, is_skipped=is_skipped
        )
        st.rerun()
    except session_manager.VotingClosedError:
        st.warning("This session isn't accepting answers right now.")
    except db.DuplicateAnswerError:
        # Already answered/skipped (e.g. a double-click) -- just
        # refresh, which will move on to the next question.
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
        st.info("You didn't answer before voting closed.")
    st.info("⏳ Waiting for the host to reveal results...")


def _render_results(sq: dict, participant: dict) -> None:
    """Per-question reveal: this participant's OWN answer/correctness
    only -- no group-level option breakdown (bar/pie chart) or rating
    distribution. That aggregate view is host/trainer-only, on the
    control room screen, per the same "individual results only" rule
    as the final summary (see _render_personal_summary)."""
    question_card.render_question_prompt(sq)
    existing = db.get_response(sq["id"], participant["id"])

    if sq["type"] == "MCQ":
        if existing:
            if existing["is_correct"]:
                st.success(f"🎉 Correct! You earned **{existing['points_awarded']}** points.")
            else:
                st.error(f"Not quite. You answered **{existing['answer_text']}**.")
        else:
            st.info("You didn't answer before voting closed.")
        correct = sq.get("correct_answer")
        if correct:
            st.markdown(f"✅ **Correct answer: {correct}**")
        if sq.get("explanation"):
            st.info(sq["explanation"])
    elif sq["type"] == "POLL":
        if existing:
            st.success(f"You answered: **{existing['answer_text']}**")
        else:
            st.info("You didn't answer before voting closed.")
    elif sq["type"] == "RATING":
        if existing:
            st.success(f"You rated: **{existing['answer_text']} / 5**")
        else:
            st.info("You didn't answer before voting closed.")
    else:
        st.success("🙌 Thanks! Your response has been recorded.")

    st.info("⏳ Waiting for the host...")


def _final_results_revealed(session: dict) -> bool:
    """The single gate both self-paced and host-paced converge on: once
    there's no next question, NOTHING on this screen -- not the group
    results/charts, not even the ranked leaderboard/scores -- is shown
    to a participant until the host explicitly clicks "Reveal to
    Participants" (sessions.group_summary_revealed_at). Pulled out as
    its own function so both _render_leaderboard and
    _render_session_ended check the exact same condition instead of
    each having their own (previously inconsistent) gating."""
    return bool(session.get("group_summary_revealed_at"))


def _render_personal_summary(session: dict, participant: dict) -> None:
    """The final screen a participant sees: THEIR OWN correct/incorrect
    count and accuracy percentage only. Group-level results (charts,
    everyone's names/scores, the ranked leaderboard) are host/trainer-
    only -- visible on the host's Group Results control-room screen,
    never here. Still gated behind the same reveal flag as before."""
    if not _final_results_revealed(session):
        st.info("⏳ Waiting for the host to share the results...")
        return

    my_responses = db.list_responses_for_participant(session["id"], participant["id"])
    scored = [r for r in my_responses if r["is_correct"] is not None]
    correct = sum(1 for r in scored if r["is_correct"])
    incorrect = len(scored) - correct
    accuracy_pct = round(correct / len(scored) * 100, 1) if scored else 0.0
    total_score = sum(r["points_awarded"] for r in my_responses)

    st.markdown("#### 🎯 Your Results")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("✅ Correct", correct)
    with c2:
        st.metric("❌ Incorrect", incorrect)
    with c3:
        st.metric("Accuracy", f"{accuracy_pct}%")
    with c4:
        st.metric("⭐ Your Score", total_score)

    with st.expander("📋 Your Answers", expanded=False):
        render_full_review(session["id"], participant_id=participant["id"])


def _render_leaderboard(session: dict, participant: dict) -> None:
    # SELF_PACED sessions never set current_question_index, so the
    # generic index-based has-next check doesn't apply here -- see the
    # matching guard in pages/host.py::_render_leaderboard.
    has_next = (
        session.get("pacing_mode") != "SELF_PACED"
        and quiz_engine.has_next_question(session["id"], session["current_question_index"])
    )

    if not has_next:
        # Both pacing modes converge here -- the final screen.
        _render_personal_summary(session, participant)
        return

    # Mid-session (INSTANT host-paced only, between questions): no
    # group leaderboard here either -- participants only ever see
    # their own results, never everyone else's names/scores/ranks.
    st.info("⏳ Waiting for the host to continue...")


def _render_session_ended(session: dict, participant: dict) -> None:
    st.markdown("## 🏁 Session Ended")
    _render_personal_summary(session, participant)
    if _final_results_revealed(session):
        st.balloons()
    st.markdown("Thanks for participating! 🎉")
