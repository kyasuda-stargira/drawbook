import json

import pytest

from drawbook.collect import portal
from mock_portal import CODE, PASSWORD, USER, MockPortal


def _browser_ok() -> bool:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            p.chromium.launch().close()
        return True
    except Exception:  # noqa: BLE001
        return False


needs_browser = pytest.mark.skipif(not _browser_ok(), reason="Playwright browser can't launch")


@pytest.fixture
def mock():
    with MockPortal() as m:
        yield m


@pytest.fixture
def cfg_file(tmp_path, mock, monkeypatch):
    monkeypatch.setenv(portal.ENV_PASSWORD, PASSWORD)
    p = tmp_path / "mockgp.toml"
    p.write_text(f'''
name = "Mock GP"
login_url = "{mock.url}/login"
username = "{USER}"
keychain_service = "drawbook-test-no-such-item"

[selectors]
username_selector = "#user"
password_selector = "#pw"
submit_selector = "#go"
code_selector = "#otp"
code_submit_selector = "#verify"
error_selector = ".error"
row_selector = "tr.doc"
link_selector = "a.dl"
title_selector = ".title"
date_selector = ".date"
next_selector = "#next"
''')
    return p


def test_config_loads_json_and_toml(tmp_path, cfg_file):
    c = portal.PortalConfig.load(cfg_file)
    assert c.code_selector == "#otp" and c.timeout_ms == 15000
    j = tmp_path / "c.json"
    j.write_text(json.dumps({**c.__dict__}))
    assert portal.PortalConfig.load(j) == c


@needs_browser
def test_full_run_then_nothing_new(tmp_path, cfg_file, mock, capsys):
    dest = tmp_path / "in"
    prompts = []

    def code(name):
        prompts.append(name)
        return CODE

    new = portal.collect(cfg_file, dest, code_prompt=code)
    assert prompts == ["Mock GP"]
    assert sorted(r["saved_name"] for r in new) == ["call-001.pdf", "cas-q1.pdf", "dist-001.pdf"]  # both pages
    assert {r["title"] for r in new} >= {"Fund III Capital Account Statement Q1"}
    assert all((dest / r["saved_name"]).read_bytes().startswith(b"%PDF") for r in new)
    state = json.loads((dest / ".drawbook-collected.json").read_text())
    assert len(state["docs"]) == 3
    rec = next(r for r in state["docs"].values() if r["saved_name"] == "call-001.pdf")
    assert rec["doc_date"] == "2026-01-15" and rec["source"] == "portal:Mock GP"
    err = capsys.readouterr().err
    assert "terms of use" in err and PASSWORD not in err

    assert portal.collect(cfg_file, dest, code_prompt=lambda n: CODE) == []
    assert sorted(p.name for p in dest.iterdir()) == [".drawbook-collected.json", "call-001.pdf",
                                                      "cas-q1.pdf", "dist-001.pdf"]


@needs_browser
def test_keeps_other_records(tmp_path, cfg_file):
    dest = tmp_path / "in"
    dest.mkdir()
    other = {"sha256": "abc", "saved_name": "email.pdf", "sender": "gp@x.com"}
    (dest / ".drawbook-collected.json").write_text(json.dumps({"docs": {"abc": other}, "extra": 1}))
    portal.collect(cfg_file, dest, code_prompt=lambda n: CODE)
    state = json.loads((dest / ".drawbook-collected.json").read_text())
    assert state["docs"]["abc"] == other and state["extra"] == 1 and len(state["docs"]) == 4


@needs_browser
def test_wrong_password(tmp_path, cfg_file, monkeypatch):
    monkeypatch.setenv(portal.ENV_PASSWORD, "wrong")
    with pytest.raises(portal.PortalError, match="Invalid username or password"):
        portal.collect(cfg_file, tmp_path / "in", code_prompt=lambda n: pytest.fail("code asked"))


@needs_browser
def test_wrong_code(tmp_path, cfg_file):
    with pytest.raises(portal.PortalError, match="Wrong code"):
        portal.collect(cfg_file, tmp_path / "in", code_prompt=lambda n: "000000")


def test_no_password_is_clear(tmp_path, cfg_file, monkeypatch):
    monkeypatch.delenv(portal.ENV_PASSWORD)
    with pytest.raises(portal.PortalError, match="DRAWBOOK_PORTAL_PASSWORD"):
        portal.collect(cfg_file, tmp_path / "in")
