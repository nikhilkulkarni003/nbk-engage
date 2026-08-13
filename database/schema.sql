-- =============================================================
-- NBK Engage - Database Schema
-- Target: Supabase / PostgreSQL 14+
--
-- Run this file once against your Supabase project's Postgres
-- database (SQL editor in the Supabase dashboard, or `psql`).
-- It is idempotent-ish (uses IF NOT EXISTS) so it is safe to
-- re-run during development.
--
-- Design notes / deliberate deviations from a literal 1:1 table
-- list, made to avoid duplicated/derivable state (the same
-- principle the app applies by keeping Streamlit session_state
-- out of the source-of-truth path):
--
--  * "leaderboard" is NOT a stored table. A participant's score
--    is always the SUM of responses.points_awarded for a session.
--    Storing that sum separately would create a second source of
--    truth that can drift. Instead we expose a SQL VIEW
--    (session_leaderboard) that computes it live from `responses`.
--
--  * "wordcloud_responses" is NOT a separate table. A word-cloud
--    prompt is just a question of type WORDCLOUD, and a
--    participant's submitted phrase is stored in responses.answer_text
--    like every other answer type. Word-cloud aggregation
--    (stop-word removal, frequency counting) is done in
--    services/analytics.py by reading `responses` for that question.
--    This keeps one write path and one dedupe/validation path for
--    all participant answers, instead of two divergent ones.
--
--  * "session_questions" links a question bank entry to a live
--    session (its position/order in the session's running order and
--    its per-session timer). The live "what is happening right now"
--    pointer lives on `sessions` (status, current_session_question_id)
--    so there is exactly one place the app reads to know session state.
-- =============================================================

create extension if not exists pgcrypto;

-- ---------------------------------------------------------------
-- users  (trainers / hosts)
-- MVP auth is a simple shared admin password (see .env
-- ADMIN_PASSWORD); this table exists so sessions/question_sets
-- have a stable owner reference and so real per-host accounts can
-- be added later without a schema change.
-- ---------------------------------------------------------------
create table if not exists users (
    id              uuid primary key default gen_random_uuid(),
    name            text not null,
    email           text unique,
    role            text not null default 'host' check (role in ('host', 'admin')),
    created_at      timestamptz not null default now()
);

-- ---------------------------------------------------------------
-- question_sets  (reusable quizzes / "decks" the host can start)
-- ---------------------------------------------------------------
create table if not exists question_sets (
    id              uuid primary key default gen_random_uuid(),
    title           text not null,
    description     text,
    category        text,
    created_by      uuid references users(id) on delete set null,
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now()
);

-- ---------------------------------------------------------------
-- questions  (global question bank)
-- Columns option_a..option_d mirror the Excel import/export
-- format exactly. `config` (jsonb) carries type-specific extras
-- that don't need to be first-class Excel columns:
--   WORDCLOUD  -> { "min_response_length": 2 }
--   RATING     -> { "min": 1, "max": 5, "min_label": "Poor", "max_label": "Excellent" }
--   POLL       -> { "extra_options": ["Option E", "Option F", ...] }  (options 5-8)
--   MCQ        -> { "time_bonus_enabled": true, "negative_marking_enabled": false }
-- ---------------------------------------------------------------
create table if not exists questions (
    id              uuid primary key default gen_random_uuid(),
    question        text not null,
    type            text not null check (type in ('MCQ', 'POLL', 'WORDCLOUD', 'RATING', 'OPEN_ENDED')),
    option_a        text,
    option_b        text,
    option_c        text,
    option_d        text,
    correct_answer  text,                     -- 'A' | 'B' | 'C' | 'D' for MCQ, null otherwise
    explanation     text,
    points          integer not null default 1,
    timer_seconds   integer not null default 30,
    category        text not null default 'General',
    difficulty      text not null default 'Medium' check (difficulty in ('Easy', 'Medium', 'Hard')),
    image_url       text,
    config          jsonb not null default '{}'::jsonb,
    created_by      uuid references users(id) on delete set null,
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now()
);

create index if not exists idx_questions_category on questions(category);
create index if not exists idx_questions_difficulty on questions(difficulty);
create index if not exists idx_questions_type on questions(type);

-- ---------------------------------------------------------------
-- question_set_items  (ordered many-to-many: set <-> question)
-- ---------------------------------------------------------------
create table if not exists question_set_items (
    id                  uuid primary key default gen_random_uuid(),
    question_set_id     uuid not null references question_sets(id) on delete cascade,
    question_id         uuid not null references questions(id) on delete cascade,
    order_index         integer not null,
    created_at          timestamptz not null default now(),
    unique (question_set_id, question_id)
);

create index if not exists idx_qsi_set on question_set_items(question_set_id, order_index);

-- ---------------------------------------------------------------
-- sessions  (one live/ended engagement session)
-- status is the single source of truth for the session state
-- machine: WAITING -> QUESTION_ACTIVE -> VOTING_CLOSED ->
--          RESULTS_REVEALED -> LEADERBOARD -> (next question loops
--          back to QUESTION_ACTIVE) -> ... -> SESSION_ENDED
--
-- reveal_mode controls WHEN results become visible to participants:
--   INSTANT  -> host reveals each question's results right after it
--               closes (classic Kahoot-style flow, the default)
--   DEFERRED -> nothing is revealed question-by-question; all
--               questions run back-to-back, then everything is
--               revealed together at the end (exam/survey-style)
--
-- anonymous_leaderboard, when true, hides real participant names on
-- the LEADERBOARD as seen by participants (host and Excel export
-- always show real names regardless of this flag).
-- ---------------------------------------------------------------
create table if not exists sessions (
    id                          uuid primary key default gen_random_uuid(),
    session_code                char(6) not null unique,
    title                       text not null,
    question_set_id             uuid references question_sets(id) on delete set null,
    host_id                     uuid references users(id) on delete set null,
    host_name                   text,
    status                      text not null default 'WAITING'
                                    check (status in (
                                        'WAITING', 'QUESTION_ACTIVE', 'VOTING_CLOSED',
                                        'RESULTS_REVEALED', 'LEADERBOARD', 'SESSION_ENDED'
                                    )),
    current_question_index     integer not null default -1,
    current_session_question_id uuid,  -- FK added below (circular w/ session_questions)
    reveal_mode                 text not null default 'INSTANT'
                                    check (reveal_mode in ('INSTANT', 'DEFERRED')),
    anonymous_leaderboard        boolean not null default false,
    -- Set once the host clicks "Reveal to Participants" on the final
    -- group results screen (both reveal modes converge there). Distinct
    -- from session_questions.revealed_at (host-side visibility) -- this
    -- is what gates the PARTICIPANT-facing group summary specifically.
    group_summary_revealed_at   timestamptz,
    scoring_config              jsonb not null default
        '{"base_points": 1, "time_bonus_enabled": false, "negative_marking_enabled": false, "negative_points": 0}'::jsonb,
    created_at                  timestamptz not null default now(),
    started_at                  timestamptz,
    ended_at                    timestamptz
);

create index if not exists idx_sessions_code on sessions(session_code);
create index if not exists idx_sessions_status on sessions(status);

-- ---------------------------------------------------------------
-- session_questions  (a question's live instance within a session)
-- Snapshots points/timer at session-start time so later edits to
-- the master question bank never change an in-flight session.
-- ---------------------------------------------------------------
create table if not exists session_questions (
    id              uuid primary key default gen_random_uuid(),
    session_id      uuid not null references sessions(id) on delete cascade,
    question_id     uuid not null references questions(id) on delete restrict,
    order_index     integer not null,
    question_text   text not null,
    type            text not null check (type in ('MCQ', 'POLL', 'WORDCLOUD', 'RATING', 'OPEN_ENDED')),
    option_a        text,
    option_b        text,
    option_c        text,
    option_d        text,
    correct_answer  text,
    explanation     text,
    points          integer not null default 1,
    timer_seconds   integer not null default 30,
    config          jsonb not null default '{}'::jsonb,
    started_at      timestamptz,   -- set when host clicks START (used for time-bonus calc)
    closed_at       timestamptz,   -- set when host clicks CLOSE VOTING
    revealed_at     timestamptz,   -- set when host clicks REVEAL
    created_at      timestamptz not null default now(),
    unique (session_id, question_id)
);

create index if not exists idx_sq_session on session_questions(session_id, order_index);

-- Postgres has no "ADD CONSTRAINT IF NOT EXISTS", so this is guarded
-- manually -- otherwise re-running this file (safe/expected for every
-- other statement here) fails with "constraint already exists" the
-- second time.
do $$
begin
    if not exists (
        select 1 from pg_constraint where conname = 'fk_sessions_current_sq'
    ) then
        alter table sessions
            add constraint fk_sessions_current_sq
            foreign key (current_session_question_id) references session_questions(id) on delete set null;
    end if;
end $$;

-- ---------------------------------------------------------------
-- participants  (no login; identified by name within a session)
-- ---------------------------------------------------------------
create table if not exists participants (
    id              uuid primary key default gen_random_uuid(),
    session_id      uuid not null references sessions(id) on delete cascade,
    name            text not null,
    joined_at       timestamptz not null default now(),
    last_seen_at    timestamptz not null default now(),
    is_active       boolean not null default true
);

-- Case-insensitive uniqueness of participant name within a session,
-- so duplicate-name joins can be rejected/disambiguated server-side.
create unique index if not exists idx_participants_unique_name
    on participants (session_id, lower(name));

create index if not exists idx_participants_session on participants(session_id);

-- ---------------------------------------------------------------
-- responses  (every participant answer, for every question type)
-- Scoring (is_correct, points_awarded) is always computed and
-- written server-side (services/scoring.py) -- never trusted from
-- the client.
-- ---------------------------------------------------------------
create table if not exists responses (
    id                      uuid primary key default gen_random_uuid(),
    session_question_id     uuid not null references session_questions(id) on delete cascade,
    participant_id          uuid not null references participants(id) on delete cascade,
    answer_text             text not null,       -- 'A'/'B'/'C'/'D' (MCQ/POLL), free text (WORDCLOUD/OPEN_ENDED), '1'-'5' (RATING)
    is_correct              boolean,
    response_time_ms        integer,
    points_awarded          integer not null default 0,
    submitted_at            timestamptz not null default now(),
    unique (session_question_id, participant_id)
);

create index if not exists idx_responses_sq on responses(session_question_id);
create index if not exists idx_responses_participant on responses(participant_id);

-- ---------------------------------------------------------------
-- session_leaderboard  (derived view, not stored)
-- ---------------------------------------------------------------
create or replace view session_leaderboard as
select
    p.session_id,
    p.id            as participant_id,
    p.name          as participant_name,
    coalesce(sum(r.points_awarded), 0)                       as total_score,
    count(r.id) filter (where r.is_correct is true)           as correct_count,
    count(r.id)                                                as answered_count,
    rank() over (
        partition by p.session_id
        order by coalesce(sum(r.points_awarded), 0) desc
    ) as rank
from participants p
left join responses r on r.participant_id = p.id
group by p.session_id, p.id, p.name;

-- ---------------------------------------------------------------
-- session_question_results  (derived view: option counts/%)
-- ---------------------------------------------------------------
create or replace view session_question_results as
select
    sq.id               as session_question_id,
    sq.session_id,
    r.answer_text,
    count(*)            as response_count
from session_questions sq
join responses r on r.session_question_id = sq.id
group by sq.id, sq.session_id, r.answer_text;

-- ---------------------------------------------------------------
-- updated_at helper trigger
-- ---------------------------------------------------------------
create or replace function set_updated_at()
returns trigger as $$
begin
    new.updated_at = now();
    return new;
end;
$$ language plpgsql;

drop trigger if exists trg_questions_updated_at on questions;
create trigger trg_questions_updated_at
    before update on questions
    for each row execute function set_updated_at();

drop trigger if exists trg_question_sets_updated_at on question_sets;
create trigger trg_question_sets_updated_at
    before update on question_sets
    for each row execute function set_updated_at();
