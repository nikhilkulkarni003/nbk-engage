-- =============================================================
-- Migration 001: reveal mode, anonymous leaderboard, default scoring
--
-- For anyone who already ran the original database/schema.sql
-- before these features existed. Safe to re-run (uses IF NOT
-- EXISTS / idempotent ALTERs). New installs get all of this from
-- schema.sql directly and do not need to run this file.
-- =============================================================

-- Host-selectable reveal timing: reveal each question immediately
-- (INSTANT, the original/default behavior) or hold everything back
-- until all questions are answered (DEFERRED).
alter table sessions
    add column if not exists reveal_mode text not null default 'INSTANT'
        check (reveal_mode in ('INSTANT', 'DEFERRED'));

-- Hide real names from other participants on the leaderboard (host
-- and Excel export are unaffected -- they always see real names).
alter table sessions
    add column if not exists anonymous_leaderboard boolean not null default false;

-- New sessions now default to simple 1-point-per-correct-answer
-- scoring with no time bonus, instead of the earlier
-- 1000-points-plus-speed-bonus default.
alter table sessions
    alter column scoring_config set default
        '{"base_points": 1, "time_bonus_enabled": false, "negative_marking_enabled": false, "negative_points": 0}'::jsonb;

alter table questions alter column points set default 1;
alter table session_questions alter column points set default 1;

-- Re-point any already-seeded questions that were created under the
-- old 1000-point default back down to the new 1-point default.
-- Only touches rows still sitting at the old default (1000) so any
-- points a trainer has deliberately customized are left alone.
update questions set points = 1 where points = 1000;
