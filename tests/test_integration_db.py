"""
End-to-end tests against a real Postgres/Supabase database: session
creation, participant joining, question activation, answer
submission, duplicate-answer prevention, and leaderboard ranking.

These require DATABASE_URL to point at a real database with
database/schema.sql already applied. They are automatically SKIPPED
(not failed) when no database is reachable, e.g. in an environment
that only has the unit tests set up -- see README.md "Testing" for
how to run these locally against your Supabase project.

Every row created here is cleaned up in a fixture teardown so
repeated runs don't pollute your question bank.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from dotenv import load_dotenv

load_dotenv()

from services import database as db
from services import quiz_engine, session_manager

_ok, _msg = db.check_connection()
pytestmark = pytest.mark.skipif(
    not _ok, reason=f"No reachable database configured for integration tests ({_msg})"
)


@pytest.fixture()
def sample_set():
    q1 = db.create_question(
        question="2 + 2 = ?", type="MCQ",
        option_a="3", option_b="4", option_c="5", option_d="6",
        correct_answer="B", explanation="Basic arithmetic.",
        points=1000, timer_seconds=30, category="General", difficulty="Easy",
    )
    q2 = db.create_question(
        question="Pick a color", type="POLL",
        option_a="Red", option_b="Blue", option_c="Green", option_d=None,
        points=0, timer_seconds=20, category="General", difficulty="Easy",
    )
    qs = db.create_question_set(title="__test_set__", description="", category="General")
    db.set_question_set_items(qs["id"], [q1["id"], q2["id"]])

    yield qs, [q1, q2]

    db.delete_question_set(qs["id"])
    db.delete_question(q1["id"])
    db.delete_question(q2["id"])


@pytest.fixture()
def sample_session(sample_set):
    qs, questions = sample_set
    session = session_manager.create_session(
        title="__test_session__", question_set_id=qs["id"], host_name="Test Host",
    )
    yield session, questions
    db.execute("delete from sessions where id = :id", {"id": session["id"]})


def test_session_creation_generates_six_digit_code(sample_session):
    session, _ = sample_session
    assert len(session["session_code"]) == 6
    assert session["session_code"].isdigit()
    assert session["status"] == "WAITING"


def test_session_questions_are_snapshotted_in_order(sample_session):
    session, questions = sample_session
    sqs = quiz_engine.get_ordered_questions(session["id"])
    assert len(sqs) == 2
    assert sqs[0]["question_text"] == "2 + 2 = ?"
    assert sqs[1]["question_text"] == "Pick a color"


def test_participant_can_join_session(sample_session):
    session, _ = sample_session
    participant = db.join_session(session["id"], "Rahul")
    assert participant["name"] == "Rahul"
    assert db.count_participants(session["id"]) == 1


def test_duplicate_participant_name_rejected(sample_session):
    session, _ = sample_session
    db.join_session(session["id"], "Priya")
    with pytest.raises(db.DuplicateNameError):
        db.join_session(session["id"], "priya")  # case-insensitive collision


def test_participant_refresh_reconnects_to_same_identity(sample_session):
    # This is what pages/participant.py relies on: a page refresh loses
    # st.session_state, so rejoining with the same name (case-insensitive)
    # must resolve back to the SAME participant row -- not a new one and
    # not a DuplicateNameError -- or the participant would lose their score.
    session, _ = sample_session
    first_join = db.join_session(session["id"], "Kiran")
    reconnected = db.find_participant_by_name(session["id"], "kiran")
    assert reconnected is not None
    assert reconnected["id"] == first_join["id"]
    assert db.count_participants(session["id"]) == 1


def test_starting_session_activates_first_question(sample_session):
    session, questions = sample_session
    started = session_manager.start_session(session["id"])
    assert started["status"] == "QUESTION_ACTIVE"
    assert started["current_question_index"] == 0
    sq = db.get_session_question(started["current_session_question_id"])
    assert sq["question_id"] == questions[0]["id"]
    assert sq["started_at"] is not None


def test_answer_submission_scores_correct_mcq(sample_session):
    session, questions = sample_session
    started = session_manager.start_session(session["id"])
    participant = db.join_session(session["id"], "Amit")
    response = session_manager.submit_answer(
        session["id"], started["current_session_question_id"], participant["id"], "B"
    )
    assert response["is_correct"] is True
    assert response["points_awarded"] >= 1000


def test_answer_submission_scores_incorrect_mcq_as_zero(sample_session):
    session, questions = sample_session
    started = session_manager.start_session(session["id"])
    participant = db.join_session(session["id"], "Neha")
    response = session_manager.submit_answer(
        session["id"], started["current_session_question_id"], participant["id"], "A"
    )
    assert response["is_correct"] is False
    assert response["points_awarded"] == 0


def test_duplicate_answer_is_rejected(sample_session):
    session, questions = sample_session
    started = session_manager.start_session(session["id"])
    participant = db.join_session(session["id"], "Vikram")
    session_manager.submit_answer(
        session["id"], started["current_session_question_id"], participant["id"], "B"
    )
    with pytest.raises(db.DuplicateAnswerError):
        session_manager.submit_answer(
            session["id"], started["current_session_question_id"], participant["id"], "A"
        )


def test_answer_rejected_after_voting_closed(sample_session):
    session, questions = sample_session
    started = session_manager.start_session(session["id"])
    participant = db.join_session(session["id"], "Sana")
    session_manager.close_voting(session["id"])
    with pytest.raises(session_manager.VotingClosedError):
        session_manager.submit_answer(
            session["id"], started["current_session_question_id"], participant["id"], "B"
        )


def test_leaderboard_ranks_by_score_descending(sample_session):
    session, questions = sample_session
    started = session_manager.start_session(session["id"])
    sq_id = started["current_session_question_id"]

    winner = db.join_session(session["id"], "Winner")
    loser = db.join_session(session["id"], "Loser")
    session_manager.submit_answer(session["id"], sq_id, winner["id"], "B")   # correct
    session_manager.submit_answer(session["id"], sq_id, loser["id"], "A")    # incorrect

    leaderboard = db.get_leaderboard(session["id"])
    assert leaderboard[0]["participant_name"] == "Winner"
    assert leaderboard[0]["rank"] == 1
    assert leaderboard[0]["total_score"] > leaderboard[1]["total_score"]


def test_poll_question_is_never_scored(sample_session):
    session, questions = sample_session
    session_manager.start_session(session["id"])
    session_manager.close_voting(session["id"])
    session_manager.reveal_answer(session["id"])
    session_manager.show_leaderboard(session["id"])
    advanced = session_manager.next_question(session["id"])  # now on the POLL question

    participant = db.join_session(session["id"], "PollVoter")
    response = session_manager.submit_answer(
        session["id"], advanced["current_session_question_id"], participant["id"], "A"
    )
    assert response["is_correct"] is None
    assert response["points_awarded"] == 0


def test_session_ends_when_no_more_questions(sample_session):
    session, questions = sample_session
    session_manager.start_session(session["id"])
    session_manager.close_voting(session["id"])
    session_manager.reveal_answer(session["id"])
    session_manager.show_leaderboard(session["id"])
    session_manager.next_question(session["id"])  # -> question 2 (poll)
    session_manager.close_voting(session["id"])
    session_manager.reveal_answer(session["id"])
    session_manager.show_leaderboard(session["id"])
    ended = session_manager.next_question(session["id"])  # no question 3 left
    assert ended["status"] == "SESSION_ENDED"


# ---------------------------------------------------------------
# DEFERRED reveal_mode: nothing is revealed question-by-question --
# results only become visible after the last question, all at once.
# ---------------------------------------------------------------
@pytest.fixture()
def deferred_session(sample_set):
    qs, questions = sample_set
    session = session_manager.create_session(
        title="__test_deferred_session__", question_set_id=qs["id"], host_name="Test Host",
        reveal_mode="DEFERRED",
    )
    yield session, questions
    db.execute("delete from sessions where id = :id", {"id": session["id"]})


def test_deferred_session_is_created_with_reveal_mode(deferred_session):
    session, _ = deferred_session
    assert session["reveal_mode"] == "DEFERRED"


def test_deferred_mode_voting_closed_can_advance_directly_to_next_question(deferred_session):
    # No reveal/leaderboard step in between -- this is what lets the
    # host skip straight to the next question without showing results.
    session, questions = deferred_session
    session_manager.start_session(session["id"])
    session_manager.close_voting(session["id"])
    advanced = session_manager.next_question(session["id"])
    assert advanced["status"] == "QUESTION_ACTIVE"
    assert advanced["current_question_index"] == 1


def test_deferred_mode_reveals_all_questions_at_once_on_last_question(deferred_session):
    session, questions = deferred_session
    session_manager.start_session(session["id"])
    session_manager.close_voting(session["id"])
    session_manager.next_question(session["id"])  # -> question 2 (last one)
    session_manager.close_voting(session["id"])

    # Before the reveal-all action, neither question should show as revealed.
    sqs_before = quiz_engine.get_ordered_questions(session["id"])
    assert all(sq["revealed_at"] is None for sq in sqs_before)

    result = session_manager.reveal_all_and_show_leaderboard(session["id"])
    assert result["status"] == "LEADERBOARD"

    sqs_after = quiz_engine.get_ordered_questions(session["id"])
    assert all(sq["revealed_at"] is not None for sq in sqs_after)


def test_deferred_mode_cannot_reveal_all_before_voting_closes(deferred_session):
    session, questions = deferred_session
    session_manager.start_session(session["id"])
    with pytest.raises(session_manager.InvalidTransitionError):
        session_manager.reveal_all_and_show_leaderboard(session["id"])


def test_anonymous_leaderboard_flag_is_stored(sample_set):
    qs, _ = sample_set
    session = session_manager.create_session(
        title="__test_anon_session__", question_set_id=qs["id"], host_name="Test Host",
        anonymous_leaderboard=True,
    )
    try:
        fetched = db.get_session(session["id"])
        assert fetched["anonymous_leaderboard"] is True
    finally:
        db.execute("delete from sessions where id = :id", {"id": session["id"]})


# ---------------------------------------------------------------
# DEFERRED auto-advance: no host click needed between questions --
# voting closes and the session moves on by itself once everyone has
# answered (or the timer expires), all the way to the final
# leaderboard, where the host's "Reveal to Participants" click takes over.
# ---------------------------------------------------------------
def test_auto_advance_deferred_is_noop_for_instant_mode(sample_session):
    session, _ = sample_session
    session_manager.start_session(session["id"])
    result = session_manager.auto_advance_deferred(session["id"])
    assert result is None
    unchanged = db.get_session(session["id"])
    assert unchanged["status"] == "QUESTION_ACTIVE"


def test_auto_advance_deferred_waits_if_not_everyone_answered(deferred_session):
    session, questions = deferred_session
    db.join_session(session["id"], "Alice")
    db.join_session(session["id"], "Bob")
    session_manager.start_session(session["id"])
    # Nobody has answered yet, and the timer (30s) hasn't expired.
    result = session_manager.auto_advance_deferred(session["id"])
    assert result is None
    still_active = db.get_session(session["id"])
    assert still_active["status"] == "QUESTION_ACTIVE"
    assert still_active["current_question_index"] == 0


def test_auto_advance_deferred_advances_once_everyone_has_answered(deferred_session):
    session, questions = deferred_session
    p1 = db.join_session(session["id"], "Alice")
    started = session_manager.start_session(session["id"])
    session_manager.submit_answer(session["id"], started["current_session_question_id"], p1["id"], "B")

    advanced = session_manager.auto_advance_deferred(session["id"])
    assert advanced["status"] == "QUESTION_ACTIVE"
    assert advanced["current_question_index"] == 1


def test_auto_advance_deferred_reaches_leaderboard_after_last_question(deferred_session):
    session, questions = deferred_session
    p1 = db.join_session(session["id"], "Alice")
    started = session_manager.start_session(session["id"])
    session_manager.submit_answer(session["id"], started["current_session_question_id"], p1["id"], "B")
    advanced = session_manager.auto_advance_deferred(session["id"])  # -> question 2 (last)

    session_manager.submit_answer(session["id"], advanced["current_session_question_id"], p1["id"], "A")
    final = session_manager.auto_advance_deferred(session["id"])

    assert final["status"] == "LEADERBOARD"
    assert final["group_summary_revealed_at"] is None  # host still has to broadcast it
    sqs = quiz_engine.get_ordered_questions(session["id"])
    assert all(sq["revealed_at"] is not None for sq in sqs)


def test_reveal_group_summary_to_participants_sets_timestamp(sample_session):
    session, _ = sample_session
    before = db.get_session(session["id"])
    assert before["group_summary_revealed_at"] is None

    revealed = session_manager.reveal_group_summary_to_participants(session["id"])
    assert revealed["group_summary_revealed_at"] is not None

    # Idempotent -- calling it again doesn't error and stays revealed.
    revealed_again = session_manager.reveal_group_summary_to_participants(session["id"])
    assert revealed_again["group_summary_revealed_at"] is not None
