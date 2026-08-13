"""Leaderboard rendering with medal styling and rank-change arrows.

Rank-change comparison uses a snapshot kept in st.session_state
purely for the animation/arrow display -- it is cosmetic UI state,
never the source of truth for scores (which always comes from the
`session_leaderboard` database view).

Anonymization (sessions.anonymous_leaderboard) is applied here, at
render time, never in the query: the database always returns real
names, and it is only the participant-facing render call that passes
anonymize=True. The host's own leaderboard view and the Excel export
always call this with anonymize=False, so the trainer never loses
visibility into who is who.
"""

from __future__ import annotations

import hashlib
import html

import streamlit as st

MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}


def _pseudonym(participant_id) -> str:
    """A stable, name-free label derived from the participant's id --
    same participant always gets the same pseudonym for the lifetime
    of the session, without revealing their real name. participant_id
    may arrive as a str or a uuid.UUID (psycopg2 returns UUID objects
    for uuid columns), so it's always normalized to str first."""
    digest = hashlib.md5(str(participant_id).encode()).hexdigest()
    return f"Participant {int(digest[:4], 16) % 900 + 100}"


def render_leaderboard(rows: list[dict], previous_ranks_key: str = "leaderboard_prev_ranks",
                        anonymize: bool = False) -> None:
    if not rows:
        st.info("No scores yet.")
        return

    previous_ranks: dict[str, int] = st.session_state.get(previous_ranks_key, {})

    for row in rows:
        rank = row["rank"]
        name = _pseudonym(row["participant_id"]) if anonymize else html.escape(row["participant_name"])
        score = row["total_score"]
        medal = MEDALS.get(rank, "")
        prev_rank = previous_ranks.get(row["participant_id"])
        arrow = ""
        if prev_rank is not None and prev_rank != rank:
            arrow = " ▲" if rank < prev_rank else " ▼"
        highlight = "background:#FFF7DC; border:2px solid #FFC531;" if rank <= 3 else "background:#F1F2F9;"

        st.markdown(
            f"""
            <div style="display:flex; justify-content:space-between; align-items:center;
                        padding:12px 18px; border-radius:12px; margin-bottom:8px; {highlight}">
              <div style="font-size:1.1rem; font-weight:700;">
                {medal} #{rank} &nbsp; {name}
              </div>
              <div style="font-size:1.15rem; font-weight:800; color:#5B5FEF;">
                {score:,} pts{arrow}
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.session_state[previous_ranks_key] = {r["participant_id"]: r["rank"] for r in rows}
