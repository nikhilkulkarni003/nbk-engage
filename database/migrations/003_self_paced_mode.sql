-- =============================================================
-- Migration 003: self-paced answering mode + skip
--
-- Adds an opt-in alternative to the existing host-paced flow: each
-- participant works through every question at their own speed (with
-- a "Skip" option) instead of the host broadcasting one shared
-- current question. The host sees live per-participant progress and
-- can close & reveal manually, or it closes automatically once every
-- participant has answered/skipped every question.
--
-- Safe to re-run. New installs get all of this from schema.sql
-- directly and do not need to run this file.
-- =============================================================

-- A skipped question still needs a row in `responses` so progress
-- ("has this participant dealt with this question yet?") can be
-- derived the same way answered questions already are -- one write
-- path, no separate "skips" table. answer_text is meaningless for a
-- skip, hence it becomes nullable.
alter table responses
    add column if not exists is_skipped boolean not null default false;

alter table responses
    alter column answer_text drop not null;

-- Which pacing model a session uses. HOST_PACED is the existing
-- default/unchanged behavior (one shared current question, host or
-- timer controls advancing). SELF_PACED is the new mode.
alter table sessions
    add column if not exists pacing_mode text not null default 'HOST_PACED'
        check (pacing_mode in ('HOST_PACED', 'SELF_PACED'));

-- sessions.status needs one more value for the self-paced "everyone
-- is answering independently" phase. Postgres has no
-- "ALTER CONSTRAINT ... ADD VALUE" for a plain CHECK, so the
-- constraint is dropped and recreated with the extra value. The name
-- matches the auto-generated name Postgres gives an unnamed
-- column-level CHECK (<table>_<column>_check) on a fresh schema.sql
-- install.
alter table sessions drop constraint if exists sessions_status_check;
alter table sessions add constraint sessions_status_check check (status in (
    'WAITING', 'QUESTION_ACTIVE', 'VOTING_CLOSED',
    'RESULTS_REVEALED', 'LEADERBOARD', 'SESSION_ENDED', 'SELF_PACED_ACTIVE'
));
