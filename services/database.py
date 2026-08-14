"""
Low-level database access layer for NBK Engage.

This is the ONLY module that talks SQL. Every other service
(session_manager, quiz_engine, scoring, analytics) calls into
functions here rather than building queries itself. Streamlit
session_state is never used as a source of truth for shared data --
this module reads from and writes to Postgres (Supabase) directly,
so every browser tab (host or participant) sees the same state.
"""

from __future__ import annotations

import os
import random
import sys
import time
import uuid
from contextlib import contextmanager
from typing import Any, Optional

import streamlit as st
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError, OperationalError

from services import diagnostics

# TEMPORARY diagnostics: counts physical DBAPI connections the pool has
# ever created (via the SQLAlchemy "connect" event, wired up on the
# engine in get_engine() below), so a query can tell whether its
# connection checkout reused an idle pooled connection or forced the
# pool to open a brand-new one. See services/diagnostics.py.
_new_connection_count = 0


# ---------------------------------------------------------------
# Errors
# ---------------------------------------------------------------
class DatabaseConfigError(RuntimeError):
    """Raised when DATABASE_URL is missing or the DB is unreachable."""


class DuplicateNameError(ValueError):
    """Raised when a participant name is already taken in a session."""


class InvalidSessionCodeError(ValueError):
    """Raised when a session code does not match any session."""


class DuplicateAnswerError(ValueError):
    """Raised when a participant tries to answer the same question twice."""


class SessionEndedError(ValueError):
    """Raised when an action is attempted on an ended session."""


# ---------------------------------------------------------------
# Engine / connection
# ---------------------------------------------------------------
@st.cache_resource(show_spinner=False)
def get_engine() -> Engine:
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        raise DatabaseConfigError(
            "DATABASE_URL is not set. Copy .env.example to .env and fill in "
            "your Supabase Postgres connection string."
        )
    engine = create_engine(
        database_url,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=10,
        pool_recycle=3600,
        pool_timeout=30,
    )

    # TEMPORARY diagnostics: fires only when the pool actually opens a
    # new physical connection (not when it hands out an already-open,
    # idle pooled one). Never touches connection parameters/secrets.
    @event.listens_for(engine, "connect")
    def _nbk_diag_on_new_connection(dbapi_connection, connection_record):  # noqa: ANN001
        global _new_connection_count
        _new_connection_count += 1

    return engine


def get_pool_stats() -> dict:
    """TEMPORARY diagnostics: read-only snapshot of the SQLAlchemy
    pool's current occupancy. Safe to call anytime."""
    try:
        pool = get_engine().pool
        return {
            "size": pool.size(),
            "checked_in": pool.checkedin(),
            "checked_out": pool.checkedout(),
            "overflow": pool.overflow(),
        }
    except Exception:  # noqa: BLE001 - diagnostics must never break the app
        return {}


def _caller_op_name() -> str:
    """TEMPORARY diagnostics: the name of the database.py function that
    called fetch_one/fetch_all/execute (e.g. "get_session"), used to
    label each query in the diagnostic log without threading a name
    through every one of this module's ~40 call sites."""
    try:
        return sys._getframe(2).f_code.co_name  # noqa: SLF001
    except Exception:  # noqa: BLE001
        return "unknown"


def check_connection() -> tuple[bool, str]:
    """Returns (ok, message). Never raises -- safe to call from any page."""
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("select 1"))
        return True, "Connected"
    except DatabaseConfigError as exc:
        return False, str(exc)
    except OperationalError as exc:
        return False, f"Could not reach the database: {exc.orig}"
    except Exception as exc:  # noqa: BLE001 - surfaced to a friendly banner
        return False, f"Database error: {exc}"


@contextmanager
def get_conn():
    engine = get_engine()
    with engine.begin() as conn:
        yield conn


def fetch_all(query: str, params: Optional[dict] = None) -> list[dict]:
    op = _caller_op_name()
    global _new_connection_count
    conns_before = _new_connection_count
    t0 = time.perf_counter()
    with get_conn() as conn:
        t1 = time.perf_counter()  # (A) time spent acquiring a pool connection + BEGIN
        rows = conn.execute(text(query), params or {}).mappings().all()
        t2 = time.perf_counter()  # (B) time spent executing the SQL itself
        result = [dict(r) for r in rows]
    diagnostics.record_query(op, (t1 - t0) * 1000, (t2 - t1) * 1000,
                              _new_connection_count > conns_before)
    return result


def fetch_one(query: str, params: Optional[dict] = None) -> Optional[dict]:
    op = _caller_op_name()
    global _new_connection_count
    conns_before = _new_connection_count
    t0 = time.perf_counter()
    with get_conn() as conn:
        t1 = time.perf_counter()
        row = conn.execute(text(query), params or {}).mappings().first()
        t2 = time.perf_counter()
        result = dict(row) if row else None
    diagnostics.record_query(op, (t1 - t0) * 1000, (t2 - t1) * 1000,
                              _new_connection_count > conns_before)
    return result


def execute(query: str, params: Optional[dict] = None) -> int:
    op = _caller_op_name()
    global _new_connection_count
    conns_before = _new_connection_count
    t0 = time.perf_counter()
    with get_conn() as conn:
        t1 = time.perf_counter()
        result = conn.execute(text(query), params or {})
        t2 = time.perf_counter()
        rowcount = result.rowcount
    diagnostics.record_query(op, (t1 - t0) * 1000, (t2 - t1) * 1000,
                              _new_connection_count > conns_before)
    return rowcount


# =================================================================
# USERS
# =================================================================
def get_or_create_user(name: str, email: Optional[str] = None, role: str = "host") -> dict:
    if email:
        existing = fetch_one("select * from users where email = :email", {"email": email})
        if existing:
            return existing
    return fetch_one(
        """
        insert into users (name, email, role)
        values (:name, :email, :role)
        returning *
        """,
        {"name": name, "email": email, "role": role},
    )


# =================================================================
# QUESTION SETS
# =================================================================
def create_question_set(title: str, description: str = "", category: str = "General",
                         created_by: Optional[str] = None) -> dict:
    return fetch_one(
        """
        insert into question_sets (title, description, category, created_by)
        values (:title, :description, :category, :created_by)
        returning *
        """,
        {"title": title, "description": description, "category": category, "created_by": created_by},
    )


def list_question_sets() -> list[dict]:
    return fetch_all(
        """
        select qs.*, count(qsi.id) as question_count
        from question_sets qs
        left join question_set_items qsi on qsi.question_set_id = qs.id
        group by qs.id
        order by qs.created_at desc
        """
    )


def get_question_set(question_set_id: str) -> Optional[dict]:
    return fetch_one("select * from question_sets where id = :id", {"id": question_set_id})


def delete_question_set(question_set_id: str) -> None:
    execute("delete from question_sets where id = :id", {"id": question_set_id})


def delete_question_set_and_questions(question_set_id: str) -> dict:
    """Deletes the set AND attempts to delete every question that was
    in it -- not just the set/its links (which is all delete_question_set
    does). A question also used in a past session is kept in the bank
    (see delete_question_safe) rather than force-deleted; everything
    else is removed. A question that's ALSO in another set gets
    removed from that set too (questions.id cascades into
    question_set_items), which is expected for "delete this set and
    its questions", not just "delete this set"."""
    items = get_question_set_items(question_set_id)
    delete_question_set(question_set_id)

    deleted = 0
    kept = 0
    for item in items:
        if delete_question_safe(item["id"]):
            deleted += 1
        else:
            kept += 1
    return {"deleted_questions": deleted, "kept_questions": kept}


def set_question_set_items(question_set_id: str, question_ids: list[str]) -> None:
    """Replaces the full ordered list of questions in a set."""
    with get_conn() as conn:
        conn.execute(
            text("delete from question_set_items where question_set_id = :sid"),
            {"sid": question_set_id},
        )
        for idx, qid in enumerate(question_ids):
            conn.execute(
                text(
                    """
                    insert into question_set_items (question_set_id, question_id, order_index)
                    values (:sid, :qid, :idx)
                    """
                ),
                {"sid": question_set_id, "qid": qid, "idx": idx},
            )


def get_question_set_items(question_set_id: str) -> list[dict]:
    return fetch_all(
        """
        select q.*, qsi.order_index
        from question_set_items qsi
        join questions q on q.id = qsi.question_id
        where qsi.question_set_id = :sid
        order by qsi.order_index asc
        """,
        {"sid": question_set_id},
    )


# =================================================================
# QUESTIONS (bank)
# =================================================================
QUESTION_FIELDS = [
    "question", "type", "option_a", "option_b", "option_c", "option_d",
    "correct_answer", "explanation", "points", "timer_seconds",
    "category", "difficulty", "image_url", "config",
]


def _question_params(fields: dict, cols: list[str]) -> dict:
    params = {c: fields.get(c) for c in cols}
    if "config" in params and isinstance(params["config"], dict):
        params["config"] = _to_jsonb_param(params["config"])
    return params


def create_question(**fields) -> dict:
    cols = [f for f in QUESTION_FIELDS if f in fields]
    placeholders = ", ".join(f":{c}" for c in cols)
    col_list = ", ".join(cols)
    return fetch_one(
        f"insert into questions ({col_list}) values ({placeholders}) returning *",
        _question_params(fields, cols),
    )


def update_question(question_id: str, **fields) -> dict:
    cols = [f for f in QUESTION_FIELDS if f in fields]
    set_clause = ", ".join(f"{c} = :{c}" for c in cols)
    params = _question_params(fields, cols)
    params["id"] = question_id
    return fetch_one(
        f"update questions set {set_clause} where id = :id returning *",
        params,
    )


def delete_question(question_id: str) -> None:
    execute("delete from questions where id = :id", {"id": question_id})


def delete_question_safe(question_id: str) -> bool:
    """Same as delete_question, but returns False instead of raising
    when the question can't be deleted because it's referenced by a
    past session's session_questions row (question_id there is
    ON DELETE RESTRICT, deliberately, so a real session's historical
    results/responses are never silently orphaned). Callers should
    tell the user it was kept, not crash the page."""
    try:
        delete_question(question_id)
        return True
    except IntegrityError:
        return False


def duplicate_question(question_id: str) -> dict:
    original = get_question(question_id)
    if not original:
        raise ValueError("Question not found")
    fields = {k: original[k] for k in QUESTION_FIELDS if k in original}
    fields["question"] = f"{fields['question']} (copy)"
    return create_question(**fields)


def get_question(question_id: str) -> Optional[dict]:
    return fetch_one("select * from questions where id = :id", {"id": question_id})


def list_questions(search: str = "", category: Optional[str] = None,
                    difficulty: Optional[str] = None, q_type: Optional[str] = None) -> list[dict]:
    clauses = []
    params: dict[str, Any] = {}
    if search:
        clauses.append("question ilike :search")
        params["search"] = f"%{search}%"
    if category and category != "All":
        clauses.append("category = :category")
        params["category"] = category
    if difficulty and difficulty != "All":
        clauses.append("difficulty = :difficulty")
        params["difficulty"] = difficulty
    if q_type and q_type != "All":
        clauses.append("type = :q_type")
        params["q_type"] = q_type
    where = f"where {' and '.join(clauses)}" if clauses else ""
    return fetch_all(f"select * from questions {where} order by created_at desc", params)


def import_questions_into_set(rows: list[dict], question_set_id: str) -> dict:
    """Excel import target: adds every row to `question_set_id`
    directly (no separate "question bank" step). A row whose question
    text + type already matches an existing question (case-
    insensitive) is NOT re-inserted as a duplicate -- the existing
    question is reused/linked into the set instead. Appends to
    whatever is already in the set rather than replacing it. Returns
    {"new_count", "duplicate_count", "total"} for the UI to report."""
    existing = {
        (row["question"].strip().lower(), row["type"]): row["id"]
        for row in fetch_all("select id, question, type from questions")
    }

    result_ids: list[str] = []
    new_count = 0
    duplicate_count = 0
    for row in rows:
        key = (row["question"].strip().lower(), row["type"])
        existing_id = existing.get(key)
        if existing_id:
            duplicate_count += 1
            result_ids.append(existing_id)
            continue
        cols = [f for f in QUESTION_FIELDS if f in row]
        placeholders = ", ".join(f":{c}" for c in cols)
        col_list = ", ".join(cols)
        created = fetch_one(
            f"insert into questions ({col_list}) values ({placeholders}) returning *",
            _question_params(row, cols),
        )
        existing[key] = created["id"]
        result_ids.append(created["id"])
        new_count += 1

    current_ids = [it["id"] for it in get_question_set_items(question_set_id)]
    combined = current_ids + [qid for qid in result_ids if qid not in current_ids]
    set_question_set_items(question_set_id, combined)

    return {"new_count": new_count, "duplicate_count": duplicate_count, "total": len(rows)}


def list_categories() -> list[str]:
    rows = fetch_all("select distinct category from questions order by category")
    return [r["category"] for r in rows]


# =================================================================
# SESSIONS
# =================================================================
def _generate_session_code() -> str:
    for _ in range(30):
        code = str(random.randint(100000, 999999))
        existing = fetch_one("select id from sessions where session_code = :code", {"code": code})
        if not existing:
            return code
    raise RuntimeError("Could not generate a unique session code, please retry.")


def create_session(title: str, question_set_id: str, host_name: str,
                    scoring_config: Optional[dict] = None,
                    reveal_mode: str = "INSTANT",
                    anonymous_leaderboard: bool = False,
                    pacing_mode: str = "HOST_PACED") -> dict:
    code = _generate_session_code()
    cols = ["session_code", "title", "question_set_id", "host_name",
            "reveal_mode", "anonymous_leaderboard", "pacing_mode"]
    params = {
        "code": code,
        "title": title,
        "question_set_id": question_set_id,
        "host_name": host_name,
        "reveal_mode": reveal_mode,
        "anonymous_leaderboard": anonymous_leaderboard,
        "pacing_mode": pacing_mode,
    }
    if scoring_config is not None:
        cols.append("scoring_config")
        params["scoring_config"] = _to_jsonb_param(scoring_config)

    col_list = ", ".join(cols)
    placeholders = ", ".join(f":{'code' if c == 'session_code' else c}" for c in cols)
    return fetch_one(
        f"insert into sessions ({col_list}) values ({placeholders}) returning *",
        params,
    )


def _to_jsonb_param(d: dict):
    import json
    return json.dumps(d)


def get_session(session_id: str) -> Optional[dict]:
    return fetch_one("select * from sessions where id = :id", {"id": session_id})


def get_session_by_code(code: str) -> Optional[dict]:
    code = (code or "").strip()
    return fetch_one("select * from sessions where session_code = :code", {"code": code})


def update_session(session_id: str, **fields) -> dict:
    allowed = {"status", "current_question_index", "current_session_question_id",
               "started_at", "ended_at"}
    cols = [f for f in fields if f in allowed]
    set_clause = ", ".join(f"{c} = :{c}" for c in cols)
    params = {c: fields[c] for c in cols}
    params["id"] = session_id
    return fetch_one(f"update sessions set {set_clause} where id = :id returning *", params)


def list_sessions(limit: int = 50) -> list[dict]:
    return fetch_all(
        """
        select s.*, count(distinct p.id) as participant_count
        from sessions s
        left join participants p on p.session_id = s.id
        group by s.id
        order by s.created_at desc
        limit :limit
        """,
        {"limit": limit},
    )


# =================================================================
# SESSION QUESTIONS
# =================================================================
SQ_FIELDS = ["question_text", "type", "option_a", "option_b", "option_c", "option_d",
             "correct_answer", "explanation", "points", "timer_seconds", "config"]


def create_session_questions(session_id: str, bank_questions: list[dict]) -> list[dict]:
    """Snapshot bank questions (already in desired order) into session_questions."""
    created = []
    with get_conn() as conn:
        for idx, q in enumerate(bank_questions):
            row = conn.execute(
                text(
                    """
                    insert into session_questions
                        (session_id, question_id, order_index, question_text, type,
                         option_a, option_b, option_c, option_d, correct_answer,
                         explanation, points, timer_seconds, config)
                    values
                        (:session_id, :question_id, :order_index, :question_text, :type,
                         :option_a, :option_b, :option_c, :option_d, :correct_answer,
                         :explanation, :points, :timer_seconds, :config)
                    returning *
                    """
                ),
                {
                    "session_id": session_id,
                    "question_id": q["id"],
                    "order_index": idx,
                    "question_text": q["question"],
                    "type": q["type"],
                    "option_a": q.get("option_a"),
                    "option_b": q.get("option_b"),
                    "option_c": q.get("option_c"),
                    "option_d": q.get("option_d"),
                    "correct_answer": q.get("correct_answer"),
                    "explanation": q.get("explanation"),
                    "points": q.get("points", 1),
                    "timer_seconds": q.get("timer_seconds", 30),
                    "config": _to_jsonb_param(q.get("config") or {}),
                },
            ).mappings().first()
            created.append(dict(row))
    return created


def get_session_question(session_question_id: str) -> Optional[dict]:
    return fetch_one("select * from session_questions where id = :id", {"id": session_question_id})


def list_session_questions(session_id: str) -> list[dict]:
    return fetch_all(
        "select * from session_questions where session_id = :sid order by order_index asc",
        {"sid": session_id},
    )


def mark_question_started(session_question_id: str) -> dict:
    return fetch_one(
        "update session_questions set started_at = now() where id = :id returning *",
        {"id": session_question_id},
    )


def mark_question_closed(session_question_id: str) -> dict:
    return fetch_one(
        "update session_questions set closed_at = now() where id = :id returning *",
        {"id": session_question_id},
    )


def mark_question_revealed(session_question_id: str) -> dict:
    return fetch_one(
        "update session_questions set revealed_at = now() where id = :id returning *",
        {"id": session_question_id},
    )


def mark_all_questions_revealed(session_id: str) -> None:
    """Used by DEFERRED reveal_mode: reveals every question in the
    session at once, instead of one at a time."""
    execute(
        """
        update session_questions
        set revealed_at = coalesce(revealed_at, now())
        where session_id = :sid
        """,
        {"sid": session_id},
    )


def mark_all_questions_started(session_id: str) -> None:
    """Used by SELF_PACED pacing_mode: every question becomes
    answerable at once (no single shared "current question"), so all
    of them get started_at set in one UPDATE when the host starts the
    session, instead of one at a time as the host/timer advances."""
    execute(
        """
        update session_questions
        set started_at = coalesce(started_at, now())
        where session_id = :sid
        """,
        {"sid": session_id},
    )


def reveal_group_summary(session_id: str) -> dict:
    """Pushes the group results summary to participant screens (see
    services/session_manager.py::reveal_group_summary_to_participants).
    Idempotent -- re-clicking doesn't reset the timestamp."""
    return fetch_one(
        """
        update sessions
        set group_summary_revealed_at = coalesce(group_summary_revealed_at, now())
        where id = :id
        returning *
        """,
        {"id": session_id},
    )


# =================================================================
# PARTICIPANTS
# =================================================================
def join_session(session_id: str, name: str) -> dict:
    name = name.strip()
    try:
        return fetch_one(
            """
            insert into participants (session_id, name)
            values (:session_id, :name)
            returning *
            """,
            {"session_id": session_id, "name": name},
        )
    except IntegrityError as exc:
        if "idx_participants_unique_name" in str(exc.orig) or "unique" in str(exc.orig).lower():
            raise DuplicateNameError(
                f'"{name}" is already taken in this session. Please choose a different name.'
            ) from exc
        raise


def get_participant(participant_id: str) -> Optional[dict]:
    return fetch_one("select * from participants where id = :id", {"id": participant_id})


def find_participant_by_name(session_id: str, name: str) -> Optional[dict]:
    return fetch_one(
        "select * from participants where session_id = :sid and lower(name) = lower(:name)",
        {"sid": session_id, "name": name.strip()},
    )


def list_participants(session_id: str) -> list[dict]:
    return fetch_all(
        "select * from participants where session_id = :sid order by joined_at asc",
        {"sid": session_id},
    )


def count_participants(session_id: str) -> int:
    row = fetch_one(
        "select count(*) as c from participants where session_id = :sid", {"sid": session_id}
    )
    return row["c"] if row else 0


def touch_participant(participant_id: str) -> None:
    execute(
        "update participants set last_seen_at = now() where id = :id", {"id": participant_id}
    )


# =================================================================
# RESPONSES
# =================================================================
def get_response(session_question_id: str, participant_id: str) -> Optional[dict]:
    return fetch_one(
        """
        select * from responses
        where session_question_id = :sqid and participant_id = :pid
        """,
        {"sqid": session_question_id, "pid": participant_id},
    )


def insert_response(session_question_id: str, participant_id: str, answer_text: Optional[str],
                     is_correct: Optional[bool], response_time_ms: Optional[int],
                     points_awarded: int, is_skipped: bool = False) -> dict:
    """Atomic insert; relies on the unique(session_question_id, participant_id)
    constraint so a race between two rapid submits from the same participant
    can never produce two rows. A skip (SELF_PACED pacing_mode) is just a
    row with is_skipped=True and answer_text=None -- same write path,
    same duplicate-prevention guarantee as a real answer."""
    with get_conn() as conn:
        result = conn.execute(
            text(
                """
                insert into responses
                    (session_question_id, participant_id, answer_text, is_correct,
                     response_time_ms, points_awarded, is_skipped)
                values
                    (:sqid, :pid, :answer, :is_correct, :rt, :points, :is_skipped)
                on conflict (session_question_id, participant_id) do nothing
                returning *
                """
            ),
            {
                "sqid": session_question_id,
                "pid": participant_id,
                "answer": answer_text,
                "is_correct": is_correct,
                "rt": response_time_ms,
                "points": points_awarded,
                "is_skipped": is_skipped,
            },
        ).mappings().first()
    if result is None:
        raise DuplicateAnswerError("You have already answered this question.")
    return dict(result)


def list_responses_for_participant(session_id: str, participant_id: str) -> list[dict]:
    """Every response (answered or skipped) this one participant has
    made in this session, in ONE query. Used by SELF_PACED pacing_mode
    to work out "which question should this participant see next"
    locally -- there is no single shared current question to ask the
    server for, so each participant's own responses (not everyone
    else's, unlike list_responses_for_session) are all that's needed."""
    return fetch_all(
        """
        select r.*
        from responses r
        join session_questions sq on sq.id = r.session_question_id
        where sq.session_id = :sid and r.participant_id = :pid
        """,
        {"sid": session_id, "pid": participant_id},
    )


def list_responses(session_question_id: str) -> list[dict]:
    return fetch_all(
        """
        select r.*, p.name as participant_name
        from responses r
        join participants p on p.id = r.participant_id
        where r.session_question_id = :sqid
        order by r.submitted_at asc
        """,
        {"sqid": session_question_id},
    )


def count_responses(session_question_id: str) -> int:
    row = fetch_one(
        "select count(*) as c from responses where session_question_id = :sqid",
        {"sqid": session_question_id},
    )
    return row["c"] if row else 0


def list_responses_for_session(session_id: str) -> list[dict]:
    """Every response for every question in a session, in ONE round
    trip -- used to build the whole-session group report/breakdown
    (services/analytics.py::get_session_report and the per-question
    result renderers it feeds) without looping list_responses/
    get_option_counts once per question (an N+1 pattern that was
    driving the host's Group Results screen to ~36 queries per poll
    tick). Same row shape as list_responses(), just scoped by session
    instead of a single session_question, so callers can group the
    result by session_question_id in Python."""
    return fetch_all(
        """
        select r.*, p.name as participant_name
        from responses r
        join participants p on p.id = r.participant_id
        join session_questions sq on sq.id = r.session_question_id
        where sq.session_id = :sid
        order by r.submitted_at asc
        """,
        {"sid": session_id},
    )


def get_self_paced_progress(session_id: str) -> list[dict]:
    """One row per participant who has joined: how many of this
    session's questions they've dealt with so far (answered OR
    skipped -- both are rows in `responses`) and how many of those
    were skips. Used by the host's SELF_PACED_ACTIVE progress panel
    and by the auto-close check (has everyone finished every
    question?) -- a single aggregate query instead of looping per
    participant."""
    return fetch_all(
        """
        select
            p.id as participant_id,
            p.name as participant_name,
            count(r.id) as completed_count,
            count(r.id) filter (where r.is_skipped) as skipped_count
        from participants p
        left join responses r
            on r.participant_id = p.id
            and r.session_question_id in (
                select id from session_questions where session_id = :sid
            )
        where p.session_id = :sid
        group by p.id, p.name
        order by p.joined_at asc
        """,
        {"sid": session_id},
    )


def get_option_counts(session_question_id: str) -> list[dict]:
    return fetch_all(
        """
        select answer_text, count(*) as response_count
        from responses
        where session_question_id = :sqid
        group by answer_text
        """,
        {"sqid": session_question_id},
    )


def get_leaderboard(session_id: str) -> list[dict]:
    return fetch_all(
        """
        select * from session_leaderboard
        where session_id = :sid
        order by total_score desc, participant_name asc
        """,
        {"sid": session_id},
    )


def new_uuid() -> str:
    return str(uuid.uuid4())
