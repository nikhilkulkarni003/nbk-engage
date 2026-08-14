"""
NBK Engage -- live audience engagement platform.

Single entry point: `streamlit run app.py`.

This file only does routing + global styling. All real logic lives
in services/ (business logic + DB), components/ (reusable UI),
utils/ (cross-cutting helpers) and pages/ (screen-level composition
for the host, participant and admin experiences).

Routing is driven by URL query params and a lightweight in-memory
"which screen" flag -- not by Streamlit's automatic pages/-folder
sidebar (which we deliberately suppress via st.navigation(...,
position="hidden") so participants never see host/admin links).
"""

from __future__ import annotations

import os

import streamlit as st
from dotenv import load_dotenv

load_dotenv()


def _peek_role() -> str:
    """Reads just enough (query params + session_state) to decide page
    layout before set_page_config runs. Must stay side-effect free.
    Mirrors _determine_role's "session_state wins once set" rule below
    so the pre-layout guess and the real routing decision never
    disagree about which role is active."""
    if "nbk_role" in st.session_state:
        return st.session_state["nbk_role"]
    query_params = st.query_params
    if query_params.get("mode") == "admin":
        return "admin"
    if query_params.get("mode") == "host":
        return "host"
    if "join" in query_params:
        return "participant"
    return "participant"


_early_role = _peek_role()

st.set_page_config(
    page_title=os.environ.get("APP_NAME", "NBK Engage"),
    page_icon="🎯",
    layout="wide" if _early_role in ("host", "admin") else "centered",
    initial_sidebar_state="collapsed",
)

GLOBAL_CSS = """
<style>
    #MainMenu, footer, header {visibility: hidden;}
    div[data-testid="stToolbar"] {visibility: hidden;}

    .block-container {
        padding-top: 2rem;
        padding-bottom: 2rem;
        max-width: 900px;
    }

    button[kind="secondary"], button[kind="primary"] {
        font-size: 1.15rem !important;
        font-weight: 600 !important;
        padding: 0.9rem 1rem !important;
        border-radius: 14px !important;
        min-height: 3.2rem;
    }

    div[data-testid="stMetricValue"] {
        font-size: 1.8rem;
    }

    .nbk-session-code {
        font-size: 3rem;
        font-weight: 800;
        letter-spacing: 0.35rem;
        color: #5B5FEF;
        text-align: center;
    }

    .nbk-hero-title {
        text-align: center;
        font-size: 2.4rem;
        font-weight: 800;
        margin-bottom: 0;
    }

    .nbk-hero-subtitle {
        text-align: center;
        color: #6b6b7a;
        margin-top: 0.2rem;
        margin-bottom: 1.5rem;
    }
</style>
"""
st.markdown(GLOBAL_CSS, unsafe_allow_html=True)

from pages import admin as admin_page  # noqa: E402
from pages import host as host_page  # noqa: E402
from pages import participant as participant_page  # noqa: E402


def _determine_role() -> str:
    query_params = st.query_params

    # Only let the URL's ?mode=/?join= set the INITIAL role -- once a
    # role is already recorded in session_state, it wins on every
    # subsequent rerun regardless of what's still in the URL.
    # st.rerun() does NOT change the URL, so without this guard a link
    # that still contains an old ?mode=host (e.g. the local desktop
    # launcher opens .../?mode=host) would silently force the role
    # back to "host" on every single rerun -- making it impossible to
    # ever switch to "admin" via the in-app button, since this
    # query-param branch kept re-winning over _switch_role's write.
    if "nbk_role" not in st.session_state:
        if query_params.get("mode") == "admin":
            st.session_state["nbk_role"] = "admin"
        elif query_params.get("mode") == "host":
            st.session_state["nbk_role"] = "host"
        elif "join" in query_params:
            st.session_state["nbk_role"] = "participant"

    return st.session_state.get("nbk_role", "participant")


def _switch_role(role: str) -> None:
    st.session_state["nbk_role"] = role
    st.query_params.clear()
    st.rerun()


def render_router() -> None:
    role = _determine_role()

    if role == "host":
        host_page.render(on_switch_role=_switch_role)
    elif role == "admin":
        admin_page.render(on_switch_role=_switch_role)
    else:
        participant_page.render(on_switch_role=_switch_role)


page = st.Page(render_router, title=os.environ.get("APP_NAME", "NBK Engage"), default=True)
st.navigation([page], position="hidden").run()
