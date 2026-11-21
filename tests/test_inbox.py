"""Inbox watcher: filters, dedupe, safe names, .emlx parsing, and IMAP with a fake server (no network)."""
from __future__ import annotations

import json
from datetime import date
from email.message import EmailMessage

import pytest

from drawbook.collect import inbox

PDF = b"%PDF-1.4 fake call notice"


def make_msg(sender="ir@acme-gp.com", subject="Capital Call Notice No. 3", date_hdr="Mon, 02 Nov 2026 09:00:00 +0000",
             attachments=(("call.pdf", PDF),), msgid="<m1@acme-gp.com>") -> bytes:
    m = EmailMessage()
    m["From"], m["To"], m["Subject"], m["Date"], m["Message-ID"] = sender, "lp@example.org", subject, date_hdr, msgid
    m.set_content("Please see attached.")
    for name, data in attachments:
        main, sub = ("application", "pdf") if name.lower().endswith(".pdf") else ("application", "octet-stream")
        m.add_attachment(data, maintype=main, subtype=sub, filename=name)
    return m.as_bytes()


def write_emlx(path, raw: bytes):
    plist = b'<?xml version="1.0" encoding="UTF-8"?>\n<plist version="1.0"><dict><key>flags</key><integer>0</integer></dict></plist>\n'
    path.write_bytes(f"{len(raw)}\n".encode() + raw + plist)


def test_filters_sender_subject_and_type(tmp_path):
    src, dest = tmp_path / "mail", tmp_path / "out"
    src.mkdir()
    (src / "a.eml").write_bytes(make_msg(attachments=(("call.pdf", PDF), ("logo.png", b"png"), ("t.xlsx", b"xl"))))
    (src / "b.eml").write_bytes(make_msg(sender="spam@other.com", attachments=(("x.pdf", b"other"),), msgid="<b>"))
    (src / "c.eml").write_bytes(make_msg(subject="Lunch?", attachments=(("y.pdf", b"lunch"),), msgid="<c>"))
    (src / "d.eml").write_bytes(make_msg(sender="ops@eu.acme-gp.com", subject="DISTRIBUTION notice",
                                         attachments=(("dist.pdf", b"dist"),), msgid="<d>"))
    docs = inbox.collect_folder(src, dest, senders=["acme-gp.com"])
    assert sorted(d.saved_name for d in docs) == ["call.pdf", "dist.pdf", "t.xlsx"]
    assert not (dest / "logo.png").exists()
    d = next(d for d in docs if d.saved_name == "call.pdf")
    assert (d.sender, d.subject, d.date, d.message_id, d.source) == (
        "ir@acme-gp.com", "Capital Call Notice No. 3", "2026-11-02", "<m1@acme-gp.com>", "folder")
    # exact-address allowlist
    assert inbox._sender_ok("ir@acme-gp.com", ["IR@acme-gp.com"]) and not inbox._sender_ok("x@acme-gp.com", ["ir@acme-gp.com"])
    assert not inbox._sender_ok("x@notacme-gp.com", ["acme-gp.com"])


def test_since_filter(tmp_path):
    src = tmp_path / "mail"
    src.mkdir()
    (src / "old.eml").write_bytes(make_msg(date_hdr="Thu, 01 Jan 2026 09:00:00 +0000", attachments=(("old.pdf", b"o"),)))
    (src / "new.eml").write_bytes(make_msg(attachments=(("new.pdf", b"n"),)))
    docs = inbox.collect_folder(src, tmp_path / "out", since=date(2026, 6, 1))
    assert [d.saved_name for d in docs] == ["new.pdf"]


def test_dedupe_on_second_run_and_state_file(tmp_path):
    src, dest = tmp_path / "mail", tmp_path / "out"
    src.mkdir()
    (src / "a.eml").write_bytes(make_msg())
    (src / "a-copy.eml").write_bytes(make_msg(msgid="<dup>"))  # same PDF bytes in a second message
    first = inbox.collect_folder(src, dest)
    assert len(first) == 1
    assert inbox.collect_folder(src, dest) == []
    state = json.loads((dest / inbox.STATE_FILE).read_text())
    assert list(state["docs"]) == [first[0].sha256]
    assert state["docs"][first[0].sha256]["saved_name"] == "call.pdf"


def test_safe_names_no_overwrite(tmp_path):
    src, dest = tmp_path / "mail", tmp_path / "out"
    src.mkdir()
    dest.mkdir()
    (dest / "call.pdf").write_bytes(b"existing")
    (src / "a.eml").write_bytes(make_msg(attachments=(("../../etc/evil.pdf", b"e"), ("call.pdf", b"new"),
                                                      ("C:\\x\\win.pdf", b"w"), ("a:b?.pdf", b"q"))))
    names = sorted(d.saved_name for d in inbox.collect_folder(src, dest))
    assert names == ["a_b_.pdf", "call-1.pdf", "evil.pdf", "win.pdf"]
    assert (dest / "call.pdf").read_bytes() == b"existing"
    assert all(p.parent == dest for p in dest.iterdir())


def test_emlx_parsing(tmp_path):
    src = tmp_path / "Mail" / "V10" / "INBOX.mbox" / "Messages"
    src.mkdir(parents=True)
    raw = make_msg(attachments=(("acct.pdf", b"capital account"),), subject="Q3 Capital Account Statement")
    write_emlx(src / "123.emlx", raw)
    assert inbox.read_emlx(src / "123.emlx") == raw
    docs = inbox.collect_folder(tmp_path / "Mail", tmp_path / "out")
    assert [d.saved_name for d in docs] == ["acct.pdf"]
    assert (tmp_path / "out" / "acct.pdf").read_bytes() == b"capital account"


class FakeIMAP:
    instances: list = []

    def __init__(self, host, port):
        self.host, self.port, self.calls = host, port, []
        self.msgs = {b"1": make_msg(), b"2": make_msg(subject="Newsletter", attachments=(("n.pdf", b"n"),))}
        FakeIMAP.instances.append(self)

    def login(self, user, pw):
        self.calls.append(("login", user, pw))

    def select(self, mailbox, readonly=False):
        self.calls.append(("select", mailbox, readonly))
        return "OK", [b"2"]

    def search(self, charset, *crit):
        self.calls.append(("search", crit))
        return "OK", [b"1 2"]

    def fetch(self, num, spec):
        assert "PEEK" in spec
        return "OK", [(num + b" (BODY[] {n}", self.msgs[num]), b")"]

    def logout(self):
        self.calls.append(("logout",))


def test_collect_imap_with_fake_server(tmp_path, monkeypatch):
    FakeIMAP.instances.clear()
    monkeypatch.setattr(inbox.imaplib, "IMAP4_SSL", FakeIMAP)
    docs = inbox.collect_imap("imap.example.org", 993, "lp", "secret", "INBOX", tmp_path / "out",
                              since=date(2026, 11, 1))
    assert [d.saved_name for d in docs] == ["call.pdf"]
    assert docs[0].source == "imap:imap.example.org/INBOX"
    calls = FakeIMAP.instances[0].calls
    assert ("select", "INBOX", True) in calls and ("search", ("SINCE", "01-Nov-2026")) in calls
    assert calls[-1] == ("logout",)
    assert "secret" not in (tmp_path / "out" / inbox.STATE_FILE).read_text()


def test_password_keychain_then_env(monkeypatch):
    class R:
        returncode, stdout = 44, ""
    monkeypatch.setattr(inbox.subprocess, "run", lambda *a, **k: R())
    monkeypatch.delenv(inbox.ENV_PASSWORD, raising=False)
    with pytest.raises(RuntimeError):
        inbox.password_from_keychain("drawbook", "lp")
    monkeypatch.setenv(inbox.ENV_PASSWORD, "envpw")
    assert inbox.password_from_keychain("drawbook", "lp") == "envpw"
    R.returncode, R.stdout = 0, "kcpw\n"
    assert inbox.password_from_keychain("drawbook", "lp") == "kcpw"
