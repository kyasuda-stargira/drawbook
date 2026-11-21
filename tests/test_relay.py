"""End to end: GP sign-up, LP invite, sealed notice to two LP devices, tampering and key changes.

Runs the real relay (relay/src/index.js) under `wrangler dev --local` on 127.0.0.1. Skipped if npx is missing.
"""
import json
import os
import shutil
import socket
import subprocess
import time
import urllib.request

import pytest

from drawbook.relay import Relay, RelayError, b64
from drawbook.relay import lp
from drawbook.relay.crypto import new_sign_key
from drawbook.relay.gp import GPClient

from conftest import ROOT

RELAY_DIR = ROOT / "relay"


@pytest.fixture(scope="module")
def relay_url(tmp_path_factory):
    if not shutil.which("npx"):
        pytest.skip("npx not installed")
    persist = tmp_path_factory.mktemp("relaydb")
    env = {**os.environ, "WRANGLER_SEND_METRICS": "false"}
    subprocess.run(["npx", "wrangler", "d1", "migrations", "apply", "drawbook-relay", "--local", "--persist-to", str(persist)],
                   cwd=RELAY_DIR, env=env, check=True, capture_output=True)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    p = subprocess.Popen(["npx", "wrangler", "dev", "--local", "--ip", "127.0.0.1", "--port", str(port), "--persist-to", str(persist),
                          "--var", "DEV_RETURN_CODE:1", "--var", "ADMIN_TOKEN:test-admin"],
                         cwd=RELAY_DIR, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}"
    for _ in range(120):
        try:
            urllib.request.urlopen(url + "/v1/health", timeout=1)
            break
        except Exception:  # noqa: BLE001
            time.sleep(0.25)
    else:
        p.kill()
        pytest.fail("relay did not start")
    yield url
    p.terminate()
    p.wait(10)


def use_home(monkeypatch, path):
    monkeypatch.setenv("DRAWBOOK_HOME", str(path))


def test_full_flow(relay_url, tmp_path, monkeypatch):
    a_home, b_home, gp_home = tmp_path / "lp-a", tmp_path / "lp-b", tmp_path / "gp"
    monkeypatch.setenv("DRAWBOOK_GP_HOME", str(gp_home))

    # LP device A creates the account; device B joins as a team member.
    use_home(monkeypatch, a_home)
    lp.init(relay_url, "Example Pension Scheme")
    inv = lp.invite("Northbank Growth Fund III", gp_email="ir@northbank.example")
    assert inv["code"] in inv["url"] and "cannot read them" in inv["email_text"]
    lp.hold("Northbank Growth Fund III L.P.")
    use_home(monkeypatch, b_home)
    req = lp.join_request("analyst laptop")
    use_home(monkeypatch, a_home)
    grant = lp.approve(req)
    use_home(monkeypatch, b_home)
    lp.join(grant)

    # GP sign-up: personal mail and other domains are refused; the code is checked.
    with pytest.raises(RelayError, match="website domain"):
        GPClient.signup(relay_url, "Northbank", "partner@gmail.com", "northbank.example")
    with pytest.raises(RelayError, match="website domain"):
        GPClient.signup(relay_url, "Northbank", "ir@other.example", "https://www.northbank.example")
    s = GPClient.signup(relay_url, "Northbank Capital", "ir@northbank.example", "https://www.northbank.example")
    with pytest.raises(RelayError, match="wrong code"):
        GPClient.verify(relay_url, s["signup_id"], "000000" if s["dev_code"] != "000000" else "111111", save=False)
    gp = GPClient.verify(relay_url, s["signup_id"], s["dev_code"], {"hq_country": "GB", "ignored_field": "x"}, conduit_consent=True)
    fund = gp.add_fund("Northbank Growth Fund III", {"vintage": "2021", "currency": "USD", "strategy": "Growth equity"}, True)
    gp.add_fund("Northbank Private Side Fund", {"vintage": "2019"}, conduit_consent=False)
    d = {x["fund_id"]: x for x in gp.demand()}
    assert d[fund]["investors_asking"] == "fewer than 3" and d[fund]["investors_linked"] == 0

    # Invite: the GP sees only what the LP chose to show, then links it to its fund. An invite works once.
    assert gp.view_invite(inv["code"]) == {"fund_name": "Northbank Growth Fund III", "lp_label": "Example Pension Scheme",
                                           "expires_at": gp.view_invite(inv["code"])["expires_at"]}
    link = gp.accept_invite(inv["code"], fund, gp_lp_ref="LP-0042")
    with pytest.raises(RelayError, match="used or expired"):
        gp.accept_invite(inv["code"], fund)
    [l] = gp.links()
    assert l["link_id"] == link and len(l["members"]) == 2

    # Send a notice: both LP devices open it; the relay keeps ciphertext until both have fetched it.
    pdf = tmp_path / "Capital Call 7.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake call notice 7")
    nid = gp.send(link, [pdf], "capital_call")
    use_home(monkeypatch, a_home)
    saved, warns = lp.fetch(tmp_path / "inbox-a")
    assert [open(x["file"], "rb").read() for x in saved] == [pdf.read_bytes()]
    assert any("pinned its signing key" in w["warning"] for w in warns)
    assert lp.links()[0]["pin"] == "ok"
    use_home(monkeypatch, b_home)
    saved_b, _ = lp.fetch(tmp_path / "inbox-b")
    assert len(saved_b) == 1
    with pytest.raises(RelayError) as e:  # gone once every device has it
        Relay(relay_url, json.load(open(b_home / "config.json"))["token"]).call("GET", f"/v1/lp/notices/{nid}/content")
    assert e.value.status == 404

    # A notice signed with any key other than the pinned one is rejected (a forged or altered notice).
    real = gp.signer
    gp.signer = new_sign_key()
    gp.send(link, [pdf], "capital_call")
    gp.signer = real
    use_home(monkeypatch, a_home)
    saved, warns = lp.fetch(tmp_path / "inbox-a2")
    assert saved == [] and any("REJECTED" in w["warning"] for w in warns)

    # Key rotation: LP refuses to open until it pins the new key.
    gp.rotate_key()
    gp.send(link, [pdf], "capital_call")
    saved, warns = lp.fetch(tmp_path / "inbox-a3", ack=False)
    assert saved == [] and any("SIGNING KEY CHANGED" in w["warning"] for w in warns)
    [ll] = lp.links()
    assert ll["pin"] == "CHANGED"
    lp.pin(ll["gp_id"], ll["gp_sign_pk"])
    saved, _ = lp.fetch(tmp_path / "inbox-a3")
    assert len(saved) == 1

    # Sealing to a stale device list is refused, so no device silently misses a notice.
    with pytest.raises(RelayError) as e:
        gp.relay.call("POST", "/v1/gp/notices", raw=b"x", headers={
            "x-drawbook-link": link, "x-drawbook-keys": b64(json.dumps({l["members"][0]["member_id"]: "A" * 80}).encode())})
    assert e.value.status == 409

    # Conduit export: admin only; consenting firm and funds only; nothing about the LP beyond a count.
    with pytest.raises(RelayError):
        Relay(relay_url, "wrong").call("GET", "/v1/admin/conduit-export")
    ex = Relay(relay_url, "test-admin").call("GET", "/v1/admin/conduit-export")
    [firm] = ex["firms"]
    assert firm["profile"] == {"hq_country": "GB"}
    assert [f["name"] for f in firm["funds"]] == ["Northbank Growth Fund III"] and firm["funds"][0]["investors_linked"] == 1
    assert "Example Pension" not in json.dumps(ex)


def test_auth_boundaries(relay_url, tmp_path, monkeypatch):
    with pytest.raises(RelayError) as e:
        Relay(relay_url).call("GET", "/v1/lp/notices")
    assert e.value.status == 401
    with pytest.raises(RelayError) as e:
        Relay(relay_url, "dbg_nope").call("GET", "/v1/gp/links")
    assert e.value.status == 401
    # One GP cannot accept an invite into another GP's fund.
    monkeypatch.setenv("DRAWBOOK_GP_HOME", str(tmp_path / "gp1"))
    s1 = GPClient.signup(relay_url, "Alpha", "a@alpha.example", "alpha.example")
    g1 = GPClient.verify(relay_url, s1["signup_id"], s1["dev_code"], save=False)
    s2 = GPClient.signup(relay_url, "Beta", "b@beta.example", "beta.example")
    g2 = GPClient.verify(relay_url, s2["signup_id"], s2["dev_code"], save=False)
    f1 = g1.add_fund("Alpha I")
    use_home(monkeypatch, tmp_path / "lp")
    lp.init(relay_url, "Some LP")
    inv = lp.invite("Alpha I")
    with pytest.raises(RelayError) as e:
        g2.accept_invite(inv["code"], f1)
    assert e.value.status == 404


def test_large_notice_round_trip(relay_url, tmp_path, monkeypatch):
    """A notice bigger than one stored piece (1 MB) comes back byte for byte."""
    monkeypatch.setenv("DRAWBOOK_GP_HOME", str(tmp_path / "gp"))
    use_home(monkeypatch, tmp_path / "lp")
    lp.init(relay_url, "Big File LP")
    inv = lp.invite("Gamma II")
    s = GPClient.signup(relay_url, "Gamma", "ir@gamma.example", "gamma.example")
    g = GPClient.verify(relay_url, s["signup_id"], s["dev_code"], save=False)
    link = g.accept_invite(inv["code"], g.add_fund("Gamma II"))
    big = tmp_path / "statement.pdf"
    big.write_bytes(os.urandom(2_600_000))
    g.send(link, [big], "capital_account_statement")
    saved, _ = lp.fetch(tmp_path / "in")
    assert open(saved[0]["file"], "rb").read() == big.read_bytes()
