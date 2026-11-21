"""Collect new documents from a GP investor portal, logged in as the LP on the LP's own machine (Playwright).

The LP writes a small TOML/JSON config per portal (login page, CSS selectors). The password comes from the
macOS keychain or $DRAWBOOK_PORTAL_PASSWORD and is never logged, printed or stored. A two-step sign-in code
is always typed by the LP (code_prompt); the robot never reads or generates codes.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tomllib
from dataclasses import dataclass, fields
from email.message import Message
from pathlib import Path
from typing import Callable
from urllib.parse import unquote, urljoin, urlparse

from .inbox import STATE_FILE, safe_name

ENV_PASSWORD = "DRAWBOOK_PORTAL_PASSWORD"
TERMS_WARNING = ("WARNING: many GP portals' terms of use forbid automated logins. You run this at your own risk; "
                 "check the portal's terms first.")
MAX_PAGES = 100


class PortalError(RuntimeError):
    pass


@dataclass
class PortalConfig:
    name: str
    login_url: str
    username: str
    keychain_service: str
    username_selector: str
    password_selector: str
    submit_selector: str
    row_selector: str            # one element per document in the list
    link_selector: str           # inside a row: the <a href> that downloads the file
    title_selector: str | None = None   # inside a row; default: the link's text
    date_selector: str | None = None    # inside a row
    code_selector: str | None = None    # two-step code field, if the portal asks for one
    code_submit_selector: str | None = None
    error_selector: str | None = None   # where the portal shows "wrong password" etc.
    logged_in_selector: str | None = None  # something only shown after login (default: row_selector)
    documents_url: str | None = None    # open this after login if the list is not the landing page
    next_selector: str | None = None    # "next page" link/button on the list
    download_dir: str | None = None
    timeout_ms: int = 15000

    @classmethod
    def load(cls, path: Path | str) -> "PortalConfig":
        """Read a .toml or .json config. Selectors may sit at the top level or in a [selectors] table."""
        path = Path(path)
        raw = tomllib.loads(path.read_text()) if path.suffix.lower() == ".toml" else json.loads(path.read_text())
        sel = raw.pop("selectors", {})
        raw = {**raw, **sel}
        known = {f.name for f in fields(cls)}
        extra = set(raw) - known
        if extra:
            raise PortalError(f"{path.name}: unknown config keys {sorted(extra)}")
        return cls(**raw)


def portal_password(cfg: PortalConfig) -> str:
    """Password from the macOS keychain (service, username), else $DRAWBOOK_PORTAL_PASSWORD."""
    try:
        r = subprocess.run(["security", "find-generic-password", "-s", cfg.keychain_service, "-a", cfg.username, "-w"],
                           capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.rstrip("\n")
    except FileNotFoundError:
        pass
    pw = os.environ.get(ENV_PASSWORD)
    if pw:
        return pw
    raise PortalError(f"{cfg.name}: no keychain item for service={cfg.keychain_service!r} "
                      f"account={cfg.username!r} and {ENV_PASSWORD} not set")


def ask_code(portal: str) -> str:
    """Default code_prompt: the LP types the code they received (text, email or authenticator app)."""
    return input(f"{portal}: type the sign-in code you received: ").strip()


class Adapter:
    """One portal's login, document list and download. Subclass for portals the generic adapter can't drive."""

    def __init__(self, cfg: PortalConfig, page, code_prompt: Callable[[str], str] = ask_code):
        self.cfg, self.page, self.code_prompt = cfg, page, code_prompt

    def login(self, password: str) -> None:
        raise NotImplementedError

    def list_documents(self) -> list[dict]:
        """Each doc: {"url", "title", "doc_date"}."""
        raise NotImplementedError

    def download(self, doc: dict) -> tuple[bytes, str]:
        """(file bytes, suggested file name)."""
        raise NotImplementedError


class GenericAdapter(Adapter):
    """Driven entirely by the CSS selectors in PortalConfig."""

    def _wait_any(self, *selectors: str | None) -> str:
        sels = [s for s in selectors if s]
        try:
            self.page.wait_for_selector(", ".join(sels), timeout=self.cfg.timeout_ms)
        except Exception:  # noqa: BLE001  (Playwright TimeoutError)
            raise PortalError(f"{self.cfg.name}: login failed - none of {sels} appeared "
                              f"(check username, password and selectors)") from None
        for s in sels:
            if self.page.query_selector(s):
                return s
        return sels[-1]

    def _fail_if_error(self, hit: str) -> None:
        if hit == self.cfg.error_selector:
            msg = (self.page.inner_text(hit) or "").strip()
            raise PortalError(f"{self.cfg.name}: login failed - portal says: {msg or '(no message)'}")

    def login(self, password: str) -> None:
        c, p = self.cfg, self.page
        p.goto(c.login_url)
        p.fill(c.username_selector, c.username)
        p.fill(c.password_selector, password)
        p.click(c.submit_selector)
        ok = c.logged_in_selector or c.row_selector
        hit = self._wait_any(c.error_selector, c.code_selector, ok)
        self._fail_if_error(hit)
        if c.code_selector and hit == c.code_selector:
            p.fill(c.code_selector, self.code_prompt(c.name))
            p.click(c.code_submit_selector or c.submit_selector)
            self._fail_if_error(self._wait_any(c.error_selector, ok))
        if c.documents_url:
            p.goto(urljoin(p.url, c.documents_url))

    def list_documents(self) -> list[dict]:
        c, p = self.cfg, self.page
        docs, seen = [], set()
        for _ in range(MAX_PAGES):
            p.wait_for_selector(c.row_selector, timeout=c.timeout_ms)
            for row in p.query_selector_all(c.row_selector):
                link = row.query_selector(c.link_selector)
                href = link and link.get_attribute("href")
                if not href:
                    continue
                url = urljoin(p.url, href)
                if url in seen:
                    continue
                seen.add(url)
                t = row.query_selector(c.title_selector) if c.title_selector else link
                d = row.query_selector(c.date_selector) if c.date_selector else None
                docs.append({"url": url, "title": (t.inner_text() if t else "").strip(),
                             "doc_date": (d.inner_text() if d else "").strip()})
            nxt = c.next_selector and p.query_selector(c.next_selector)
            if not nxt:
                break
            before = p.url
            nxt.click()
            p.wait_for_load_state()
            if p.url == before:
                break
        return docs

    def download(self, doc: dict) -> tuple[bytes, str]:
        r = self.page.context.request.get(doc["url"], timeout=self.cfg.timeout_ms)  # same cookies as the page
        if not r.ok:
            raise PortalError(f"{self.cfg.name}: download failed ({r.status}) for {doc.get('title') or doc['url']}")
        m = Message()
        m["content-disposition"] = r.headers.get("content-disposition", "")
        name = m.get_filename() or unquote(Path(urlparse(doc["url"]).path).name) or "document.pdf"
        return r.body(), name


def _load_state(dest: Path) -> dict:
    """Shared with the inbox watcher: {"docs": {sha256: record}}. Other keys and records are kept as they are."""
    p = dest / STATE_FILE
    state = json.loads(p.read_text()) if p.exists() else {}
    if isinstance(state, list):  # tolerate a bare list of records
        state = {"docs": {r["sha256"]: r for r in state if "sha256" in r}}
    state.setdefault("docs", {})
    return state


def collect(config_path: Path | str, dest: Path | str | None = None, headed: bool = False,
            code_prompt: Callable[[str], str] = ask_code, adapter: type[Adapter] = GenericAdapter) -> list[dict]:
    """Log in to one portal, download every document not already collected into dest, return the new records."""
    print(TERMS_WARNING, file=sys.stderr)
    cfg = PortalConfig.load(config_path)
    dest = Path(dest or cfg.download_dir or ".").expanduser()
    password = portal_password(cfg)
    from playwright.sync_api import sync_playwright

    new: list[dict] = []
    dest.mkdir(parents=True, exist_ok=True)
    state = _load_state(dest)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not headed)
        try:
            page = browser.new_page()
            a = adapter(cfg, page, code_prompt)
            a.login(password)
            del password
            for doc in a.list_documents():
                data, name = a.download(doc)
                sha = hashlib.sha256(data).hexdigest()
                if not data or sha in state["docs"]:
                    continue
                saved = safe_name(name, dest)
                (dest / saved).write_bytes(data)
                rec = {"sha256": sha, "saved_name": saved, "source": f"portal:{cfg.name}",
                       "title": doc.get("title", ""), "doc_date": doc.get("doc_date", "")}
                state["docs"][sha] = rec
                new.append(rec)
                (dest / STATE_FILE).write_text(json.dumps(state, indent=2))
        finally:
            browser.close()
    return new
