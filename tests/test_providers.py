import json
import urllib.request

import pytest

from drawbook.providers import LocalProvider, MockProvider, OutsideProvider, redact


def test_local_refuses_remote_url():
    with pytest.raises(ValueError):
        LocalProvider("https://api.anthropic.com/v1")
    with pytest.raises(ValueError):
        LocalProvider("http://192.168.1.10:8080/v1")
    assert LocalProvider("http://127.0.0.1:8091/v1").base_url.startswith("http://127.0.0.1")


def test_network_guard_blocks_outside_hosts():
    with pytest.raises(AssertionError):
        urllib.request.urlopen("https://api.anthropic.com/v1/messages", timeout=2)


def _outside(tmp_path, confirm, sent, **kw):
    def transport(url, body, headers):
        sent.append((url, body, headers))
        return {"content": [{"type": "text", "text": "{}"}]}
    return OutsideProvider("anthropic", "test-key-not-real", "claude-x", log_path=tmp_path / "log.jsonl",
                           confirm=confirm, transport=transport, **kw)


def test_outside_needs_confirmation_and_sends_nothing_when_declined(tmp_path):
    sent, warnings = [], []
    p = _outside(tmp_path, lambda m: warnings.append(m) or False, sent)
    with pytest.raises(PermissionError):
        p.complete("sys", "Northfield County Pension Scheme owes 1,234.00", doc="a.pdf")
    assert sent == [] and not (tmp_path / "log.jsonl").exists()
    assert "outside this machine" in warnings[0] and "a.pdf" in warnings[0]


def test_outside_redacts_and_logs(tmp_path):
    sent = []
    p = _outside(tmp_path, lambda m: True, sent, redact_names=["Northfield County Pension Scheme", "LP-436"],
                 redact_figures=True)
    p.complete("sys", "Dear Northfield County Pension Scheme (LP-436), you owe $1,234,567.89", doc="a.pdf")
    body = sent[0][1]["messages"][0]["content"]
    assert "Northfield" not in body and "LP-436" not in body and "1,234,567.89" not in body
    assert "[LP]" in body and "[FIGURE]" in body
    log = [json.loads(x) for x in (tmp_path / "log.jsonl").read_text().splitlines()]
    assert log[0]["doc"] == "a.pdf" and log[0]["provider"] == "anthropic:claude-x" and log[0]["figures_redacted"]


def test_outside_requires_key(tmp_path):
    with pytest.raises(ValueError):
        OutsideProvider("anthropic", "", "m", log_path=tmp_path / "l", confirm=lambda m: True)


def test_redact_keeps_figures_by_default():
    assert redact("Acme LP pays 1,000.00", ["Acme LP"]) == "[LP] pays 1,000.00"


def test_mock_records_calls():
    m = MockProvider("{}")
    m.complete("s", "u")
    assert m.calls == [("s", "u")]
