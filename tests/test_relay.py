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
from datetime import datetime, timedelta, timezone

import pytest

from drawbook.relay import Relay, RelayError, b64
from drawbook.relay import lp
from drawbook.relay.crypto import new_sign_key
from drawbook.relay.gp import GPClient

from conftest import ROOT

RELAY_DIR = ROOT / "relay"
DB = {}  # persist folder of the local relay database, for tests that read or backdate rows


@pytest.fixture(scope="module")
def relay_url(tmp_path_factory):
    if not shutil.which("npx"):
        pytest.skip("npx not installed")
    persist = tmp_path_factory.mktemp("relaydb")
    DB["persist"] = persist
    env = {**os.environ, "WRANGLER_SEND_METRICS": "false"}
    subprocess.run(["npx", "wrangler", "d1", "migrations", "apply", "drawbook-relay", "--local", "--persist-to", str(persist)],
                   cwd=RELAY_DIR, env=env, check=True, capture_output=True)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    p = subprocess.Popen(["npx", "wrangler", "dev", "--local", "--ip", "127.0.0.1", "--port", str(port), "--persist-to", str(persist),
                          "--var", "DEV_RETURN_CODE:1", "--var", "ADMIN_TOKEN:test-admin", "--test-scheduled"],
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


def sql(command):
    out = subprocess.run(["npx", "wrangler", "d1", "execute", "drawbook-relay", "--local", "--persist-to", str(DB["persist"]),
                          "--command", command, "--json"], cwd=RELAY_DIR, check=True, capture_output=True, text=True,
                         env={**os.environ, "WRANGLER_SEND_METRICS": "false"})
    return json.loads(out.stdout)[0]["results"]


def test_idle_accounts_deleted(relay_url, tmp_path, monkeypatch):
    # Two GPs and two LPs, all linked with a notice waiting. One GP and one LP then go idle.
    monkeypatch.setenv("DRAWBOOK_GP_HOME", str(tmp_path / "gp"))
    gps = {}
    for name in ("Idlegp", "Busygp"):
        s = GPClient.signup(relay_url, name, f"ir@{name.lower()}.example", f"{name.lower()}.example")
        g = GPClient.verify(relay_url, s["signup_id"], s["dev_code"], save=False)
        gps[name] = (g, g.add_fund(f"{name} Fund I"))
    lps = {}
    for name in ("Idle LP", "Busy LP"):
        use_home(monkeypatch, tmp_path / name)
        lps[name] = lp.init(relay_url, name)["account_id"]
        lp.hold("Idlegp Fund I")
        for g, fund in gps.values():
            link = g.accept_invite(lp.invite(g.funds()[0]["name"])["code"], fund)
            pdf = tmp_path / "n.pdf"
            pdf.write_bytes(b"%PDF-1.4 notice")
            g.send(link, [pdf])
    gp_ids = {n: g.relay.call("GET", "/v1/gp/me")["gp_id"] for n, (g, _) in gps.items()}

    # Any signed-in request records activity.
    sql(f"UPDATE lp_accounts SET last_seen_at = '2000-01-01T00:00:00Z' WHERE id = '{lps['Busy LP']}'")
    use_home(monkeypatch, tmp_path / "Busy LP")
    lp.links()
    assert sql(f"SELECT last_seen_at FROM lp_accounts WHERE id = '{lps['Busy LP']}'")[0]["last_seen_at"] > "2026"

    # Idle for just over 24 months: deleted with everything attached. Just under: kept.
    old = (datetime.now(timezone.utc) - timedelta(days=731)).isoformat()
    recent = (datetime.now(timezone.utc) - timedelta(days=729)).isoformat()
    sql(f"UPDATE lp_accounts SET last_seen_at = '{old}' WHERE id = '{lps['Idle LP']}'")
    sql(f"UPDATE gp_firms SET last_seen_at = '{old}' WHERE id = '{gp_ids['Idlegp']}'")
    sql(f"UPDATE gp_firms SET last_seen_at = '{recent}' WHERE id = '{gp_ids['Busygp']}'")
    urllib.request.urlopen(relay_url + "/__scheduled?cron=17+3+*+*+*", timeout=30).read()

    ids = lambda t: {r["id"] for r in sql(f"SELECT id FROM {t}")}
    assert lps["Idle LP"] not in ids("lp_accounts") and lps["Busy LP"] in ids("lp_accounts")
    assert gp_ids["Idlegp"] not in ids("gp_firms") and gp_ids["Busygp"] in ids("gp_firms")
    for t, col in [("lp_members", "account_id"), ("links", "account_id"), ("invites", "account_id"), ("lp_holdings", "account_id")]:
        assert sql(f"SELECT COUNT(*) AS n FROM {t} WHERE {col} = '{lps['Idle LP']}'")[0]["n"] == 0
    assert sql(f"SELECT COUNT(*) AS n FROM links WHERE gp_id = '{gp_ids['Idlegp']}'")[0]["n"] == 0
    assert sql(f"SELECT COUNT(*) AS n FROM gp_funds WHERE gp_id = '{gp_ids['Idlegp']}'")[0]["n"] == 0
    # Only the busy pair's link and notice are left, and no orphaned notice content.
    assert len(sql("SELECT id FROM links")) >= 1
    assert sql("SELECT COUNT(*) AS n FROM notices WHERE link_id NOT IN (SELECT id FROM links)")[0]["n"] == 0
    assert sql("SELECT COUNT(*) AS n FROM notice_keys WHERE notice_id NOT IN (SELECT id FROM notices)")[0]["n"] == 0
    assert sql("SELECT COUNT(*) AS n FROM blob_chunks WHERE notice_id NOT IN (SELECT id FROM notices)")[0]["n"] == 0
    # The busy GP still works and sees only its link to the busy LP.
    assert [l["lp_label"] for l in gps["Busygp"][0].links()] == ["Busy LP"]


def test_lp_deletes_own_account(relay_url, tmp_path, monkeypatch):
    from drawbook.cli import cmd_connect
    monkeypatch.setenv("DRAWBOOK_GP_HOME", str(tmp_path / "gp"))
    s = GPClient.signup(relay_url, "Leaver Capital", "ir@leaver.example", "leaver.example")
    g = GPClient.verify(relay_url, s["signup_id"], s["dev_code"], save=False)
    fund = g.add_fund("Leaver Fund I")
    a_home, b_home = tmp_path / "a", tmp_path / "b"
    use_home(monkeypatch, a_home)
    acct = lp.init(relay_url, "Leaving LP")["account_id"]
    lp.hold("Leaver Fund I")
    link = g.accept_invite(lp.invite("Leaver Fund I")["code"], fund)
    lp.invite("Some Other Fund")  # an unused invite
    use_home(monkeypatch, b_home)
    req = lp.join_request("second laptop")
    use_home(monkeypatch, a_home)
    grant = lp.approve(req)
    use_home(monkeypatch, b_home)
    lp.join(grant)
    pdf = tmp_path / "n.pdf"
    pdf.write_bytes(b"%PDF-1.4 waiting notice")
    g.send(link, [pdf])
    b_token = json.load(open(b_home / "config.json"))["token"]

    # The relay refuses without the account id repeated; the command refuses without "delete" typed.
    with pytest.raises(RelayError) as e:
        lp.relay().call("DELETE", "/v1/lp/account", {"confirm": "wrong"})
    assert e.value.status == 400
    use_home(monkeypatch, a_home)
    monkeypatch.setattr("builtins.input", lambda _: "y")
    assert cmd_connect(["delete"]) == 1 and (a_home / "config.json").exists()

    monkeypatch.setattr("builtins.input", lambda _: "delete")
    assert cmd_connect(["delete"]) == 0
    assert not (a_home / "config.json").exists() and not (a_home / "keys.json").exists()
    for t in ("lp_accounts", "lp_members", "lp_holdings", "invites", "links"):
        col = "id" if t == "lp_accounts" else "account_id"
        assert sql(f"SELECT COUNT(*) AS n FROM {t} WHERE {col} = '{acct}'")[0]["n"] == 0
    assert sql(f"SELECT COUNT(*) AS n FROM notices WHERE link_id = '{link}'")[0]["n"] == 0
    assert sql("SELECT COUNT(*) AS n FROM blob_chunks WHERE notice_id NOT IN (SELECT id FROM notices)")[0]["n"] == 0
    # The team's other device is locked out, and the GP no longer sees the link.
    with pytest.raises(RelayError) as e:
        Relay(relay_url, b_token).call("GET", "/v1/lp/links")
    assert e.value.status == 401
    assert g.links() == []


def test_gp_deletes_own_account(relay_url, tmp_path, monkeypatch):
    from drawbook.relay.gp import main as gp_main
    gp_home = tmp_path / "gp"
    monkeypatch.setenv("DRAWBOOK_GP_HOME", str(gp_home))
    s = GPClient.signup(relay_url, "Exit Partners", "ir@exitpartners.example", "exitpartners.example")
    g = GPClient.verify(relay_url, s["signup_id"], s["dev_code"], conduit_consent=True)  # saved to gp.json
    gp_id = g.state["gp_id"]
    fund = g.add_fund("Exit Fund I", {"vintage": "2020"}, conduit_consent=True)
    use_home(monkeypatch, tmp_path / "lp")
    lp.init(relay_url, "Staying LP")
    link = g.accept_invite(lp.invite("Exit Fund I")["code"], fund)
    pdf = tmp_path / "n.pdf"
    pdf.write_bytes(b"%PDF-1.4 waiting notice")
    g.send(link, [pdf])
    assert "Exit Partners" in json.dumps(Relay(relay_url, "test-admin").call("GET", "/v1/admin/conduit-export"))

    with pytest.raises(RelayError) as e:
        g.relay.call("DELETE", "/v1/gp/me", {"confirm": "wrong"})
    assert e.value.status == 400
    monkeypatch.setattr("builtins.input", lambda _: "yes")
    assert gp_main(["delete"]) == 1 and (gp_home / "gp.json").exists()

    monkeypatch.setattr("builtins.input", lambda _: "delete")
    assert gp_main(["delete"]) == 0
    assert not (gp_home / "gp.json").exists()
    for t, col in [("gp_firms", "id"), ("gp_funds", "gp_id"), ("links", "gp_id")]:
        assert sql(f"SELECT COUNT(*) AS n FROM {t} WHERE {col} = '{gp_id}'")[0]["n"] == 0
    assert sql(f"SELECT COUNT(*) AS n FROM notices WHERE link_id = '{link}'")[0]["n"] == 0
    assert sql("SELECT COUNT(*) AS n FROM blob_chunks WHERE notice_id NOT IN (SELECT id FROM notices)")[0]["n"] == 0
    # The old API key no longer works, the firm leaves the Conduit export, and the investor keeps its account.
    with pytest.raises(RelayError) as e:
        g.relay.call("GET", "/v1/gp/me")
    assert e.value.status == 401
    assert "Exit Partners" not in json.dumps(Relay(relay_url, "test-admin").call("GET", "/v1/admin/conduit-export"))
    assert lp.links() == []
