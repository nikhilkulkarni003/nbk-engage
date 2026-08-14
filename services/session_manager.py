"""
Session state machine.

sessions.status is the single source of truth for where a live
session is in its lifecycle. There are two paths through it,
selected per-session by sessions.reveal_mode:

  INSTANT (default, classic Kahoot-style):
    WAITING --start_session-->
    QUESTION_ACTIVE --close_voting-->
    VOTING_CLOSED --reveal_answer-->
    RESULTS_REVEALED --show_leaderboard-->
    LEADERBOARD --next_question--> QUESTION_ACTIVE (loops)
                --next_question (no more questions)--> SESSION_ENDED

  DEFERRED (exam/survey-style -- nothing is revealed until every
  question has been answered):
    WAITING --start_session-->
    QUESTION_ACTIVE --close_voting-->
    VOTING_CLOSED --next_question (not the last question)--> QUESTION_ACTIVE (loops)
    VOTING_CLOSED --reveal_all_and_show_leaderboard (last question)--> LEADERBOARD
    LEADERBOARD --next_question (no more questions)--> SESSION_ENDED

    (any state) --end_session--> SESSION_ENDED

  SELF_PACED (pacing_mode == 'SELF_PACED', orthogonal to reveal_mode --
  every participant answers/skips all questions independently instead
  of the host broadcasting one shared current question):
    WAITING --start_session_self_paced--> SELF_PACED_ACTIVE
    SELF_PACED_ACTIVE --close_and_reveal_self_paced (manual, or
        automatic via auto_close_self_paced_if_everyone_done)--> LEADERBOARD
    LEADERBOARD --(no next_question; host ends from the group-results screen)--> SESSION_ENDED

Every transition here re-reads the session row from the database
first and validates the current status before writing, so two
browser tabs (e.g. host double-clicking, or a stale page) can never
push the session into an invalid state. Which of the two paths above
is legal at a given moment is a host.py/UI concern (it only offers
the buttons that make sense for the session's reveal_mode) -- the
transition table itself just needs to allow both paths to exist.
"""

from __future__ import annotations

from datetime import datetime, timezone

from services import database as db
from services import diagnostics
from services import quiz_engine
from services import scoring

VALID_TRANSITIONS = {
    # SELF_PACED_ACTIVE: pacing_mode == "SELF_PACED" only -- every
    # participant answers/skips all questions independently (see
    # submit_answer_or_skip), no single shared "current question".
    "WAITING": {"QUESTION_ACTIVE", "SELF_PACED_ACTIVE"},
    "QUESTION_ACTIVE": {"VOTING_CLOSED", "SESSION_ENDED"},
    "VOTING_CLOSED": {"RESULTS_REVEALED", "QUESTION_ACTIVE", "LEADERBOARD", "SESSION_ENDED"},
    "RESULTS_REVEALED": {"LEADERBOARD", "SESSION_ENDED"},
    "LEADERBOARD": {"QUESTION_ACTIVE", "SESSION_ENDED"},
    "SELF_PACED_ACTIVE": {"LEADERBOARD", "SESSION_ENDED"},
    "SESSION_ENDED": set(),
}


class InvalidTransitionError(ValueError):
    pass


class VotingClosedError(ValueError):
    pass


class SessionEndedError(ValueError):
    pass


def _now():
    return datetime.now(timezone.utc)


def _require_transition(current_status: str, target_status: str) -> None:
    allowed = VALID_TRANSITIONS.get(current_status, set())
    if target_status not in allowed:
        raise InvalidTransitionError(
            f"Cannot move from {current_status} to {target_status}."
        )


def create_session(title: str, question_set_id: str, host_name: str,
                    scoring_config: dict | None = None,
                    reveal_mode: str = "INSTANT",
                    anonymous_leaderboard: bool = False,
                    pacing_mode: str = "HOST_PACED") -> dict:
    session = db.create_session(
        title, question_set_id, host_name, scoring_config,
        reveal_mode=reveal_mode, anonymous_leaderboard=anonymous_leaderboard,
        pacing_mode=pacing_mode,
    )
    quiz_engine.build_session_questions(session["id"], question_set_id)
    return session


def get_full_state(session_id: str, known_total_questions: int | None = None) -> dict:
    """Everything a host/participant screen needs for one poll cycle.

    known_total_questions lets a caller that has already cached the
    session's question count (it's fixed for the session's whole
    lifetime -- see quiz_engine.total_questions) skip the
    list_session_questions round trip entirely, on every tick, not
    just within one. Falls back to fetching it when not supplied."""
    session = db.get_session(session_id)
    if not session:
        return {}
    current_q = None
    if session.get("current_session_question_id"):
        diagnostics.mark("before_get_current_question")
        current_q = db.get_session_question(session["current_session_question_id"])
        diagnostics.mark("after_get_current_question")
    return {
        "session": session,
        "current_question": current_q,
        "participant_count": db.count_participants(session_id),
        "response_count": db.count_responses(current_q["id"]) if current_q else 0,
        "total_questions": quiz_engine.total_questions(session_id, known_total_questions),
    }


def start_session(session_id: str) -> dict:
    session = db.get_session(session_id)
    _require_transition(session["status"], "QUESTION_ACTIVE")
    first_q = quiz_engine.get_question_at_index(session_id, 0)
    if not first_q:
        raise ValueError("No questions available to start this session.")
    db.mark_question_started(first_q["id"])
    return db.update_session(
        session_id,
        status="QUESTION_ACTIVE",
        current_question_index=0,
        current_session_question_id=first_q["id"],
        started_at=_now(),
    )


def start_session_self_paced(session_id: str) -> dict:
    """pacing_mode == 'SELF_PACED' only: every question becomes
    answerable at once (see submit_answer_or_skip) instead of the
    host/timer stepping through them one at a time."""
    session = db.get_session(session_id)
    _require_transition(session["status"], "SELF_PACED_ACTIVE")
    db.mark_all_questions_started(session_id)
    return db.update_session(session_id, status="SELF_PACED_ACTIVE", started_at=_now())


def close_voting(session_id: str) -> dict:
    session = db.get_session(session_id)
    _require_transition(session["status"], "VOTING_CLOSED")
    if session.get("current_session_question_id"):
        db.mark_question_closed(session["current_session_question_id"])
    return db.update_session(session_id, status="VOTING_CLOSED")


def reveal_answer(session_id: str) -> dict:
    session = db.get_session(session_id)
    _require_transition(session["status"], "RESULTS_REVEALED")
    if session.get("current_session_question_id"):
        db.mark_question_revealed(session["current_session_question_id"])
    return db.update_session(session_id, status="RESULTS_REVEALED")


def show_leaderboard(session_id: str) -> dict:
    session = db.get_session(session_id)
    _require_transition(session["status"], "LEADERBOARD")
    return db.update_session(session_id, status="LEADERBOARD")


def reveal_all_and_show_leaderboard(session_id: str) -> dict:
    """DEFERRED reveal_mode only: called once, after the LAST
    question's voting has closed. Reveals every question in the
    session at once (rather than one at a time) and jumps straight
    to the leaderboard."""
    session = db.get_session(session_id)
    _require_transition(session["status"], "LEADERBOARD")
    db.mark_all_questions_revealed(session_id)
    return db.update_session(session_id, status="LEADERBOARD")


def next_question(session_id: str) -> dict:
    session = db.get_session(session_id)
    _require_transition(session["status"], "QUESTION_ACTIVE")
    next_index = session["current_question_index"] + 1
    next_q = quiz_engine.get_question_at_index(session_id, next_index)
    if not next_q:
        return end_session(session_id)
    db.mark_question_started(next_q["id"])
    return db.update_session(
        session_id,
        status="QUESTION_ACTIVE",
        current_question_index=next_index,
        current_session_question_id=next_q["id"],
    )


def end_session(session_id: str) -> dict:
    return db.update_session(session_id, status="SESSION_ENDED", ended_at=_now())


def submit_answer(session_id: str, session_question_id: str, participant_id: str,
                   answer_text: str) -> dict:
    """Validates that voting is actually open, computes response_time_ms
    from the server-stored question start time (never trusting a
    client-supplied timestamp), scores the answer server-side, and
    writes the response. Relies on the DB's unique constraint (via
    database.insert_response) to make duplicate-answer prevention
    atomic even under concurrent requests."""
    session = db.get_session(session_id)
    if not session or session["status"] == "SESSION_ENDED":
        raise SessionEndedError("This session has ended.")
    if session["status"] != "QUESTION_ACTIVE" or session["current_session_question_id"] != session_question_id:
        raise VotingClosedError("Voting is closed for this question.")

    sq = db.get_session_question(session_question_id)
    if not sq:
        raise ValueError("Question not found.")

    response_time_ms = None
    if sq.get("started_at"):
        started_at = sq["started_at"]
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)
        response_time_ms = max(0, int((_now() - started_at).total_seconds() * 1000))

    is_correct, points = scoring.score_response(
        question_type=sq["type"],
        answer_text=answer_text,
        session_question=sq,
        response_time_ms=response_time_ms,
        scoring_config=session.get("scoring_config"),
    )

    return db.insert_response(
        session_question_id=session_question_id,
        participant_id=participant_id,
        answer_text=answer_text,
        is_correct=is_correct,
        response_time_ms=response_time_ms,
        points_awarded=points,
    )


def submit_answer_or_skip(session_id: str, session_question_id: str, participant_id: str,
                           answer_text: str | None = None, is_skipped: bool = False) -> dict:
    """pacing_mode == 'SELF_PACED' only: each participant answers/skips
    every question independently, so unlike submit_answer there is no
    single shared "is this the current question" gate -- any question
    belonging to this session is fair game, in any order, exactly once
    per participant (the unique(session_question_id, participant_id)
    DB constraint that protects submit_answer protects this too). A
    skip is never scored (is_correct=None, points=0), same as any
    other non-MCQ/participation-only answer."""
    session = db.get_session(session_id)
    if not session or session["status"] == "SESSION_ENDED":
        raise SessionEndedError("This session has ended.")
    if session["status"] != "SELF_PACED_ACTIVE":
        raise VotingClosedError("This session is not accepting answers right now.")

    sq = db.get_session_question(session_question_id)
    if not sq or sq["session_id"] != session_id:
        raise ValueError("Question not found.")

    response_time_ms = None
    if not is_skipped and sq.get("started_at"):
        started_at = sq["started_at"]
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)
        response_time_ms = max(0, int((_now() - started_at).total_seconds() * 1000))

    if is_skipped:
        is_correct, points = None, 0
    else:
        is_correct, points = scoring.score_response(
            question_type=sq["type"],
            answer_text=answer_text,
            session_question=sq,
            response_time_ms=response_time_ms,
            scoring_config=session.get("scoring_config"),
        )

    return db.insert_response(
        session_question_id=session_question_id,
        participant_id=participant_id,
        answer_text=answer_text,
        is_correct=is_correct,
        response_time_ms=response_time_ms,
        points_awarded=points,
        is_skipped=is_skipped,
    )


def close_and_reveal_self_paced(session_id: str) -> dict:
    """pacing_mode == 'SELF_PACED' only: the host's manual "Close &
    Reveal Results" action (or the automatic equivalent -- see
    auto_close_self_paced_if_everyone_done). Reveals every question at
    once and jumps to the group-results screen, the same terminal
    convergence point DEFERRED reveal_mode's final step uses."""
    session = db.get_session(session_id)
    _require_transition(session["status"], "LEADERBOARD")
    db.mark_all_questions_revealed(session_id)
    return db.update_session(session_id, status="LEADERBOARD")


def auto_close_self_paced_if_everyone_done(session_id: str, session: dict | None = None,
                                            progress: list[dict] | None = None,
                                            total_questions: int | None = None) -> dict | None:
    """pacing_mode == 'SELF_PACED' only: called by the host poll loop.
    Once at least one participant has joined and every one of them has
    answered/skipped every question, closes & reveals automatically --
    no host click needed, mirroring auto_advance_deferred's hands-off
    behavior for DEFERRED reveal_mode.

    session/progress/total_questions let a caller that already fetched
    this tick's state pass it straight in instead of this function
    re-querying it."""
    session = session if session is not None else db.get_session(session_id)
    if not session or session["status"] != "SELF_PACED_ACTIVE":
        return None
    progress = progress if progress is not None else db.get_self_paced_progress(session_id)
    if not progress:
        return None
    total = total_questions if total_questions is not None else quiz_engine.total_questions(session_id)
    if total <= 0:
        return None
    if all(row["completed_count"] >= total for row in progress):
        return close_and_reveal_self_paced(session_id)
    return None


def auto_advance_deferred(session_id: str, session: dict | None = None,
                           sq: dict | None = None,
                           participant_count: int | None = None,
                           response_count: int | None = None) -> dict | None:
    """DEFERRED reveal_mode only: fully hands-off question flow. Host-
    paced sessions have no timer at all -- voting closes automatically
    once every joined participant has answered, and the session
    immediately moves to the next question with no host click needed.

    On the LAST question, it stops one step short of broadcasting to
    participants: it auto-advances the host into the terminal
    LEADERBOARD state (via reveal_all_and_show_leaderboard, so the
    host can already see the group results) but does NOT set
    group_summary_revealed_at -- that stays a deliberate host action
    ("Reveal to Participants"), identical to per-question mode's
    manual final reveal.

    session/sq/participant_count/response_count let a caller that has
    already fetched this same tick's state (e.g. host.py, right after
    calling get_full_state) pass it straight in instead of this
    function re-querying the same rows a second time. Each value is
    still fetched here if not supplied, so calling with just
    session_id (as before) behaves identically. Note this only affects
    the read-side decision of *whether* to transition -- the actual
    state-changing calls below (close_voting/next_question/etc.) each
    re-read fresh from the DB immediately before writing, so this
    never causes a stale write.
    """
    session = session if session is not None else db.get_session(session_id)
    if not session or session["reveal_mode"] != "DEFERRED":
        return None

    if session["status"] == "QUESTION_ACTIVE":
        sq = sq if sq is not None else db.get_session_question(session["current_session_question_id"])
        if not sq or not sq.get("started_at"):
            return None

        participant_count = participant_count if participant_count is not None else db.count_participants(session_id)
        response_count = response_count if response_count is not None else db.count_responses(sq["id"])
        everyone_answered = participant_count > 0 and response_count >= participant_count

        if not everyone_answered:
            return None
        session = close_voting(session_id)

    if session["status"] == "VOTING_CLOSED":
        if quiz_engine.has_next_question(session_id, session["current_question_index"]):
            return next_question(session_id)
        return reveal_all_and_show_leaderboard(session_id)

    return None


def reveal_group_summary_to_participants(session_id: str) -> dict:
    """The host's explicit 'Reveal to Participants' action on the
    final group results screen. Works identically for both reveal
    modes -- it's a flag, not a status transition, so it doesn't go
    through _require_transition."""
    return db.reveal_group_summary(session_id)
