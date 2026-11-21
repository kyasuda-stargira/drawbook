"""Client for the Drawbook relay: GPs send sealed notices to the LPs who invited them.

The relay stores ciphertext only. Notices are encrypted on the GP's machine to every device
of the LP's account (libsodium sealed boxes) and signed with the GP's Ed25519 key, so the
relay can neither read a notice nor change one without the LP's Drawbook noticing.
"""
from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request

ENV_RELAY = "DRAWBOOK_RELAY"
DEFAULT_RELAY = "https://drawbook-relay.kyasuda-183.workers.dev"  # Stargira's relay (Cloudflare Worker, deployed 2026-11-21)


class RelayError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(f"relay said {status}: {message}")
        self.status = status


class Relay:
    def __init__(self, base: str | None = None, token: str | None = None, timeout: float = 60):
        base = base or os.environ.get(ENV_RELAY) or DEFAULT_RELAY
        self.base, self.token, self.timeout = base.rstrip("/"), token, timeout

    def call(self, method: str, path: str, body: dict | None = None, raw: bytes | None = None,
             headers: dict | None = None) -> dict | bytes:
        h = {"user-agent": "drawbook-lp (+https://github.com/kyasuda-stargira/drawbook)", **(headers or {})}
        data = None
        if body is not None:
            data, h["content-type"] = json.dumps(body).encode(), "application/json"
        elif raw is not None:
            data, h["content-type"] = raw, "application/octet-stream"
        if self.token:
            h["authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                out = r.read()
                return json.loads(out) if r.headers.get("content-type", "").startswith("application/json") else out
        except urllib.error.HTTPError as e:
            try:
                msg = json.loads(e.read()).get("error", "")
            except Exception:  # noqa: BLE001
                msg = e.reason
            raise RelayError(e.code, msg) from None


def b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def unb64(s: str) -> bytes:
    return base64.b64decode(s)
