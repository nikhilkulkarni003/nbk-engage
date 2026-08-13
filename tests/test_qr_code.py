"""
Tests for utils/qr_code.py's join-URL resolution -- this is what
determines whether the QR code a host projects is actually reachable
from a participant's phone. The historical bug this guards against:
baking "localhost" into the QR code, which only ever resolves to the
scanning phone itself, never the host's computer.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import qr_code


def test_explicit_base_url_argument_wins(monkeypatch):
    monkeypatch.delenv("APP_BASE_URL", raising=False)
    url = qr_code.build_join_url("123456", base_url="https://engage.example.com")
    assert url == "https://engage.example.com/?join=123456"


def test_configured_public_url_is_used_when_not_placeholder(monkeypatch):
    monkeypatch.setenv("APP_BASE_URL", "https://nbk-engage.streamlit.app")
    url = qr_code.build_join_url("654321")
    assert url == "https://nbk-engage.streamlit.app/?join=654321"


def test_default_placeholder_falls_back_to_lan_ip(monkeypatch):
    monkeypatch.setenv("APP_BASE_URL", "http://localhost:8501")
    monkeypatch.setattr(qr_code, "get_lan_ip", lambda: "192.168.1.50")
    url = qr_code.build_join_url("111111")
    assert url == "http://192.168.1.50:8501/?join=111111"
    assert "localhost" not in url


def test_unset_base_url_falls_back_to_lan_ip(monkeypatch):
    monkeypatch.delenv("APP_BASE_URL", raising=False)
    monkeypatch.setattr(qr_code, "get_lan_ip", lambda: "10.0.0.5")
    url = qr_code.build_join_url("222222")
    assert url == "http://10.0.0.5:8501/?join=222222"


def test_custom_port_is_respected(monkeypatch):
    monkeypatch.delenv("APP_BASE_URL", raising=False)
    monkeypatch.setenv("APP_PORT", "9000")
    monkeypatch.setattr(qr_code, "get_lan_ip", lambda: "192.168.1.50")
    url = qr_code.build_join_url("333333")
    assert url == "http://192.168.1.50:9000/?join=333333"
