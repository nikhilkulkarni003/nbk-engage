-- =============================================================
-- Migration 002: group_summary_revealed_at
--
-- Backs the "Reveal to Participants" action on the unified
-- end-of-session group results screen. Safe to re-run. New installs
-- get this from schema.sql directly.
-- =============================================================

alter table sessions
    add column if not exists group_summary_revealed_at timestamptz;
