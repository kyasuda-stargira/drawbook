"""Tiny local GP investor portal for tests: login form, two-step code page, session cookie,
a 2-page document list and PDF downloads. Runs on 127.0.0.1 on a random port in a thread."""
from __future__ import annotations

import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

USER, PASSWORD, CODE = "lp@example.com", "correct-horse", "246810"
DOCS = {  # page -> [(file, title, date)]
    1: [("call-001.pdf", "Fund III Capital Call #1", "2026-01-15"),
        ("dist-001.pdf", "Fund III Distribution #1", "2026-03-31")],
    2: [("cas-q1.pdf", "Fund III Capital Account Statement Q1", "2026-04-30")],
}


def pdf_bytes(name: str) -> bytes:
    return (b"%PDF-1.4\n% mock " + name.encode() + b"\n%%EOF\n")


class _Handler(BaseHTTPRequestHandler):
    server: "MockPortal"

    def log_message(self, *a):  # quiet
        pass

    def _send(self, code=200, body=b"", ctype="text/html", headers=()):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        for k, v in headers:
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _page(self, html: str, headers=()):
        self._send(body=f"<!doctype html><html><body>{html}</body></html>".encode(), headers=headers)

    def _redirect(self, where: str, headers=()):
        self._send(302, headers=[("Location", where), *headers])

    def _session(self) -> str | None:
        for part in self.headers.get("Cookie", "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == "sid":
                return v
        return None

    def _login_form(self, error=""):
        err = f'<p class="error">{error}</p>' if error else ""
        self._page(f'{err}<form method="post" action="/login"><input id="user" name="user">'
                   f'<input id="pw" name="pw" type="password"><button id="go">Sign in</button></form>')

    def _form(self) -> dict:
        n = int(self.headers.get("Content-Length", 0))
        return {k: v[0] for k, v in parse_qs(self.rfile.read(n).decode()).items()}

    def do_GET(self):
        u = urlparse(self.path)
        sid = self._session()
        if u.path in ("/", "/login"):
            return self._login_form()
        if u.path == "/code" and sid in self.server.pending:
            return self._page('<form method="post" action="/code"><input id="otp" name="otp">'
                              '<button id="verify">Verify</button></form>')
        if sid not in self.server.sessions:
            return self._redirect("/login")
        if u.path == "/documents":
            page = int(parse_qs(u.query).get("page", ["1"])[0])
            rows = "".join(f'<tr class="doc"><td class="date">{d}</td><td class="title">{t}</td>'
                           f'<td><a class="dl" href="/files/{f}">Download</a></td></tr>' for f, t, d in DOCS.get(page, []))
            nxt = f'<a id="next" href="/documents?page={page + 1}">Next</a>' if page + 1 in DOCS else ""
            return self._page(f"<table>{rows}</table>{nxt}")
        if u.path.startswith("/files/"):
            name = u.path.rsplit("/", 1)[-1]
            if any(name == f for docs in DOCS.values() for f, _, _ in docs):
                self.server.downloads.append(name)
                return self._send(body=pdf_bytes(name), ctype="application/pdf",
                                  headers=[("Content-Disposition", f'attachment; filename="{name}"')])
        self._send(404, b"not found", "text/plain")

    def do_POST(self):
        f = self._form()
        if self.path == "/login":
            if f.get("user") != USER or f.get("pw") != PASSWORD:
                return self._login_form("Invalid username or password")
            sid = secrets.token_hex(8)
            self.server.pending.add(sid)
            return self._redirect("/code", [("Set-Cookie", f"sid={sid}; Path=/; HttpOnly")])
        if self.path == "/code":
            sid = self._session()
            if sid not in self.server.pending or f.get("otp") != CODE:
                return self._page('<p class="error">Wrong code</p>')
            self.server.pending.discard(sid)
            self.server.sessions.add(sid)
            return self._redirect("/documents")
        self._send(404, b"not found", "text/plain")


class MockPortal(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self):
        super().__init__(("127.0.0.1", 0), _Handler)
        self.pending: set[str] = set()
        self.sessions: set[str] = set()
        self.downloads: list[str] = []
        self.thread = threading.Thread(target=self.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.shutdown()
        self.server_close()
