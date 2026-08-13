"""QR code generation for the participant join link."""

from __future__ import annotations

import io
import os

import qrcode
import streamlit as st
from qrcode.image.pil import PilImage

from utils.network import get_lan_ip

_DEFAULT_PLACEHOLDER = "http://localhost:8501"


def build_join_url(session_code: str, base_url: str | None = None) -> str:
    """
    Resolution order:
      1. An explicit base_url argument.
      2. APP_BASE_URL from .env, IF it has been changed from the
         localhost placeholder (i.e. the trainer deliberately pointed
         it at a real deployed/public URL).
      3. Auto-detected LAN IP of this machine, e.g. http://192.168.1.23:8501
         -- this is what makes the QR code scannable from a phone on
         the same Wi-Fi with zero configuration.
    """
    configured = os.environ.get("APP_BASE_URL", "").strip().rstrip("/")
    port = os.environ.get("APP_PORT", "8501").strip()

    if base_url:
        resolved = base_url.rstrip("/")
    elif configured and configured != _DEFAULT_PLACEHOLDER:
        resolved = configured
    else:
        resolved = f"http://{get_lan_ip()}:{port}"

    return f"{resolved}/?join={session_code}"


@st.cache_data(show_spinner=False)
def generate_qr_code_png(url: str) -> bytes:
    """The join URL is constant for a session's whole lifetime, so the
    PNG only needs to be generated once per unique URL rather than on
    every 2-second host poll tick. Cached by url (the only argument),
    so different sessions/codes each get their own correct image."""
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=2,
    )
    qr.add_data(url)
    qr.make(fit=True)
    img: PilImage = qr.make_image(fill_color="#1A1B25", back_color="#FFFFFF")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
