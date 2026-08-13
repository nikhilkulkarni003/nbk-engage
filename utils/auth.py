"""
Minimal trainer/host authentication for the MVP.

Participants never authenticate (by design). The host and admin
areas are gated by a single shared password (ADMIN_PASSWORD in
.env) -- this is intentionally simple for a single-trainer MVP; the
`users` table in the schema leaves room for real per-host accounts
later without breaking this interface.
"""

from __future__ import annotations

import os

import streamlit as st

AUTH_KEY = "nbk_host_authenticated"


def is_authenticated() -> bool:
    return bool(st.session_state.get(AUTH_KEY, False))


def log_out() -> None:
    st.session_state[AUTH_KEY] = False


def render_login_gate(subtitle: str = "Enter the trainer password to continue.") -> bool:
    """Renders a password form if not authenticated. Returns True once
    authenticated (so callers can `if not render_login_gate(): return`)."""
    if is_authenticated():
        return True

    st.markdown("## 🔐 Trainer Login")
    st.caption(subtitle)
    configured_password = os.environ.get("ADMIN_PASSWORD", "")

    with st.form("host_login_form"):
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Log In", use_container_width=True)

    if submitted:
        if not configured_password:
            st.error(
                "ADMIN_PASSWORD is not set on the server. Set it in your .env file to enable host/admin login."
            )
        elif password == configured_password:
            st.session_state[AUTH_KEY] = True
            st.rerun()
        else:
            st.error("Incorrect password.")

    return False
