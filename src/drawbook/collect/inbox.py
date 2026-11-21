"""Collect notice attachments (PDF / ILPA .xlsx) from email into a folder Drawbook then reads.

Runs on the LP's own machine: IMAP (stdlib imaplib) or a folder of .eml / Apple Mail .emlx files.
Passwords are read from the macOS keychain or an environment variable, never stored.
"""
from __future__ import annotations

import hashlib
import imaplib
import json
import os
import re
import subprocess
from dataclasses import asdict, dataclass
from datetime import date
from email import message_from_bytes, policy
from email.message import Message
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path
from typing import Iterable

DEFAULT_SUBJECT_WORDS = ["capital call", "distribution", "capital account", "drawdown", "notice"]
KEEP_SUFFIXES = (".pdf", ".xlsx")
STATE_FILE = ".drawbook-collected.json"
ENV_PASSWORD = "DRAWBOOK_IMAP_PASSWORD"
_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


@dataclass
class CollectedDoc:
    sha256: str
    saved_name: str
    sender: str
    subject: str
    date: str
    message_id: str
    source: str


def password_from_keychain(service: str, account: str) -> str:
    """Password from the macOS keychain (`security find-generic-password -w`), else $DRAWBOOK_IMAP_PASSWORD."""
    try:
        r = subprocess.run(["security", "find-generic-password", "-s", service, "-a", account, "-w"],
                           capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.rstrip("\n")
    except FileNotFoundError:
        pass
    pw = os.environ.get(ENV_PASSWORD)
    if pw:
        return pw
    raise RuntimeError(f"no keychain item for service={service!r} account={account!r} and {ENV_PASSWORD} not set")


def safe_name(name: str | None, dest: Path) -> str:
    """File name with path parts and odd characters removed, made unique in dest (never overwrites)."""
    base = (name or "").replace("\\", "/").split("/")[-1]
    base = re.sub(r"[^\w.\- ()]", "_", base).strip(" .") or "attachment"
    stem, dot, ext = base.rpartition(".")
    if not dot:
        stem, ext = base, ""
    cand, i = base, 1
    while (dest / cand).exists():
        cand = f"{stem}-{i}.{ext}" if ext else f"{stem}-{i}"
        i += 1
    return cand


def _sender_ok(addr: str, senders: list[str] | None) -> bool:
    if not senders:
        return True
    addr = addr.lower()
    for s in senders:
        s = s.strip().lower().lstrip("@")
        if "@" in s:
            if addr == s:
                return True
        elif addr.endswith("@" + s) or addr.endswith("." + s):
            return True
    return False


def _subject_ok(subject: str, words: list[str] | None) -> bool:
    words = DEFAULT_SUBJECT_WORDS if words is None else words
    if not words:
        return True
    s = subject.lower()
    return any(w.lower() in s for w in words)


def _msg_date(msg: Message) -> date | None:
    try:
        return parsedate_to_datetime(msg["Date"]).date()
    except (TypeError, ValueError):
        return None


def _load_state(dest: Path) -> dict:
    p = dest / STATE_FILE
    return json.loads(p.read_text()) if p.exists() else {"docs": {}}


def _collect(raws: Iterable[bytes], dest: Path, source: str, since: date | None,
             senders: list[str] | None, subject_words: list[str] | None) -> list[CollectedDoc]:
    dest.mkdir(parents=True, exist_ok=True)
    state = _load_state(dest)
    out: list[CollectedDoc] = []
    for raw in raws:
        msg = message_from_bytes(raw, policy=policy.default)
        sender = parseaddr(str(msg.get("From", "")))[1]
        subject = str(msg.get("Subject", ""))
        d = _msg_date(msg)
        if not _sender_ok(sender, senders) or not _subject_ok(subject, subject_words):
            continue
        if since and d and d < since:
            continue
        for part in msg.walk():
            fname = part.get_filename()
            if part.is_multipart() or not fname or not fname.lower().endswith(KEEP_SUFFIXES):
                continue
            data = part.get_payload(decode=True) or b""
            sha = hashlib.sha256(data).hexdigest()
            if not data or sha in state["docs"]:
                continue
            name = safe_name(fname, dest)
            (dest / name).write_bytes(data)
            doc = CollectedDoc(sha, name, sender, subject, d.isoformat() if d else str(msg.get("Date", "")),
                               str(msg.get("Message-ID", "")), source)
            state["docs"][sha] = asdict(doc)
            out.append(doc)
    (dest / STATE_FILE).write_text(json.dumps(state, indent=2))
    return out


def read_emlx(path: Path) -> bytes:
    """RFC822 bytes from an Apple Mail .emlx file (byte-count line, message, then an XML plist)."""
    data = path.read_bytes()
    first, rest = data.split(b"\n", 1)
    return rest[:int(first.strip())]


def collect_folder(src: Path, dest: Path, since: date | None = None, senders: list[str] | None = None,
                   subject_words: list[str] | None = None) -> list[CollectedDoc]:
    """Collect attachments from every .eml / .emlx file under src. subject_words=[] turns the subject filter off."""
    def raws():
        for p in sorted(src.rglob("*")):
            if p.is_file() and p.suffix.lower() == ".eml":
                yield p.read_bytes()
            elif p.is_file() and p.suffix.lower() == ".emlx":
                yield read_emlx(p)
    return _collect(raws(), dest, "folder", since, senders, subject_words)


def collect_imap(host: str, port: int, user: str, password: str, mailbox: str, dest: Path,
                 since: date | None = None, senders: list[str] | None = None,
                 subject_words: list[str] | None = None, ssl: bool = True) -> list[CollectedDoc]:
    """Collect attachments from an IMAP mailbox (opened read-only; messages are not marked read)."""
    conn = (imaplib.IMAP4_SSL if ssl else imaplib.IMAP4)(host, port)
    try:
        conn.login(user, password)
        conn.select(mailbox, readonly=True)
        crit = ["SINCE", f"{since.day:02d}-{_MONTHS[since.month - 1]}-{since.year}"] if since else ["ALL"]
        _, data = conn.search(None, *crit)
        raws = []
        for num in (data[0] or b"").split():
            _, parts = conn.fetch(num, "(BODY.PEEK[])")
            raws += [p[1] for p in parts if isinstance(p, tuple)]
    finally:
        try:
            conn.logout()
        except Exception:  # noqa: BLE001
            pass
    return _collect(raws, dest, f"imap:{host}/{mailbox}", since, senders, subject_words)
