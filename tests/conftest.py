import socket
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "testset" / "gen"), str(ROOT / "tools")]


@pytest.fixture(autouse=True)
def no_outside_network(monkeypatch):
    """No paid API calls in tests: any connection to a non-local host fails the test."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("DRAWBOOK_OUTSIDE_KEY", raising=False)
    real = socket.socket.connect

    def guarded(self, addr):
        host = addr[0] if isinstance(addr, tuple) else addr
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise AssertionError(f"test tried to reach outside host {host}")
        return real(self, addr)

    monkeypatch.setattr(socket.socket, "connect", guarded)
    real_gai = socket.getaddrinfo

    def gai(host, *a, **k):
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise AssertionError(f"test tried to resolve outside host {host}")
        return real_gai(host, *a, **k)

    monkeypatch.setattr(socket, "getaddrinfo", gai)
