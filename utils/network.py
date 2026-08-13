"""
LAN IP detection for the participant join link / QR code.

Streamlit serves the app on whatever machine runs `streamlit run
app.py`. If the join link/QR code encodes "localhost", every phone
that scans it tries to reach *itself* on port 8501 -- not the host's
laptop -- which is why a QR code that "doesn't scan" almost always
means the URL baked into it was localhost instead of the host
machine's actual network address. This module finds that address
automatically so the join link works out of the box for any device
on the same Wi-Fi/LAN, with no manual configuration.
"""

from __future__ import annotations

import socket


def get_lan_ip() -> str:
    """Best-effort LAN IP of this machine, e.g. 192.168.1.23.

    Uses the venerable "connect a UDP socket to a public address"
    trick -- no packets are actually sent, it just asks the OS which
    local interface/IP would be used to route there, which reliably
    returns the real LAN-facing IP even on machines with multiple
    network adapters. Falls back to 127.0.0.1 if that fails for any
    reason (e.g. no network at all), so callers never crash on this.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()
