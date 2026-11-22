"""LP side of the relay: keys, invites to GPs, opt-in holdings, fetching sealed notices.

State lives in DRAWBOOK_HOME (default ~/.drawbook): config.json (relay address, account,
device token), keys.json (this device's private keys, mode 600) and pins.json (each GP's
signing key, pinned the first time the LP sees it).
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from nacl.public import PrivateKey

from . import Relay, b64, unb64
from .crypto import BadNotice, fingerprint, new_box_key, new_sign_key, open_notice


def home() -> Path:
    return Path(os.environ.get("DRAWBOOK_HOME") or Path.home() / ".drawbook")


def _read(name: str, default=None):
    p = home() / name
    return json.loads(p.read_text()) if p.exists() else default


def _write(name: str, data, private: bool = False) -> None:
    home().mkdir(parents=True, exist_ok=True, mode=0o700)
    p = home() / name
    p.write_text(json.dumps(data, indent=1))
    if private:
        p.chmod(0o600)


def _keys() -> tuple[PrivateKey, dict]:
    k = _read("keys.json")
    if not k:
        raise RuntimeError("this device has no Drawbook keys: run `drawbook connect init` (or `join`) first")
    return PrivateKey(unb64(k["box_sk"])), k


def _new_keys() -> dict:
    if _read("keys.json"):
        raise RuntimeError(f"keys already exist in {home()}; refusing to overwrite them")
    box, sign = new_box_key(), new_sign_key()
    k = {"box_sk": b64(bytes(box)), "box_pk": b64(bytes(box.public_key)),
         "sign_sk": b64(bytes(sign)), "sign_pk": b64(bytes(sign.verify_key))}
    _write("keys.json", k, private=True)
    return k


def relay() -> Relay:
    c = _read("config.json")
    if not c:
        raise RuntimeError("not connected: run `drawbook connect init` first")
    return Relay(c["relay"], c["token"])


def init(relay_url: str | None, label: str, device: str = "first device") -> dict:
    """Create this investor's account on the relay with this device as its first member."""
    if _read("config.json"):
        raise RuntimeError(f"this device is already connected (see {home() / 'config.json'})")
    k = _read("keys.json") or _new_keys()  # keys kept from an earlier attempt that failed to register
    r = Relay(relay_url)
    out = r.call("POST", "/v1/lp/register", {"label": label, "member_label": device,
                                              "box_pk": k["box_pk"], "sign_pk": k["sign_pk"]})
    _write("config.json", {"relay": r.base, "account_id": out["account_id"], "member_id": out["member_id"],
                           "token": out["token"], "label": label}, private=True)
    return out


def join_request(label: str) -> str:
    """On a new team device: make keys and print a request for an existing device to approve."""
    k = _new_keys()
    return b64(json.dumps({"label": label, "box_pk": k["box_pk"], "sign_pk": k["sign_pk"]}).encode())


def approve(request: str) -> str:
    """On an existing device: add the new device to the account; returns the token to paste back."""
    req = json.loads(unb64(request))
    out = relay().call("POST", "/v1/lp/members", req)
    c = _read("config.json")
    return b64(json.dumps({"relay": c["relay"], "account_id": c["account_id"], "member_id": out["member_id"],
                           "token": out["token"], "label": c.get("label")}).encode())


def join(grant: str) -> None:
    """On the new device: store the grant from `approve`."""
    _keys()
    _write("config.json", json.loads(unb64(grant)), private=True)


def invite(fund_name: str, lp_label: str | None = None, gp_email: str | None = None) -> dict:
    """Make an invite for one GP and fund. The LP sends it to its GP contact itself."""
    c = _read("config.json") or {}
    out = relay().call("POST", "/v1/lp/invites", {"fund_name": fund_name, "lp_label": lp_label or c.get("label"),
                                                   "gp_email": gp_email})
    out["email_text"] = (
        f"Subject: Please send our {fund_name} notices through Drawbook\n\n"
        f"Hello,\n\nWe now read our capital call and distribution notices with Drawbook. "
        f"Could you send our notices for {fund_name} through it as well as by your usual route?\n\n"
        f"Set-up takes a few minutes and is free: {out['url']}\n"
        f"Notices are encrypted on your side to our keys and signed by you; Stargira, which runs the relay, "
        f"cannot read them.\nThe link works for {out['expires_in_days']} days and only once.\n\nThank you.")
    return out


def hold(fund_name: str, remove: bool = False) -> dict:
    """Opt in (or out) to 'I hold this fund'. Only the fund's name is sent, never figures."""
    return relay().call("DELETE" if remove else "POST", "/v1/lp/holdings", {"fund_name": fund_name})


def links() -> list[dict]:
    out = relay().call("GET", "/v1/lp/links")["links"]
    pins = _read("pins.json", {})
    for l in out:
        pin = pins.get(l["gp_id"])
        l["fingerprint"] = fingerprint(l["gp_sign_pk"])
        l["pin"] = "new" if not pin else ("ok" if pin == l["gp_sign_pk"] else "CHANGED")
    return out


def pin(gp_id: str, sign_pk: str) -> None:
    """Accept a GP's (new) signing key, after checking its fingerprint with the GP."""
    pins = _read("pins.json", {})
    pins[gp_id] = sign_pk
    _write("pins.json", pins)


def delete_account() -> str:
    """Delete this investor's account on the relay, with every device, link, invite and waiting notice.
    Then remove this device's relay key and token. Documents already saved are not touched."""
    c = _read("config.json")
    relay().call("DELETE", "/v1/lp/account", {"confirm": c["account_id"]})
    for name in ("config.json", "keys.json"):
        (home() / name).unlink(missing_ok=True)
    return c["account_id"]


def _safe(name: str) -> str:
    base = os.path.basename(name.replace("\\", "/")) or "notice"
    return "".join(ch if ch.isalnum() or ch in "-_. " else "_" for ch in base).strip(". ") or "notice"


def fetch(dest: Path, ack: bool = True) -> tuple[list[dict], list[dict]]:
    """Download, decrypt and check every waiting notice into dest. Returns (saved, warnings)."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    box_sk, _ = _keys()
    r = relay()
    pins = _read("pins.json", {})
    gp_keys = {l["gp_id"]: l["gp_sign_pk"] for l in r.call("GET", "/v1/lp/links")["links"]}
    saved, warns = [], []
    for n in r.call("GET", "/v1/lp/notices")["notices"]:
        gp = n["gp_id"]
        if gp not in pins:  # trust on first use; the fingerprint is shown so the LP can check it by phone
            pins[gp] = gp_keys[gp]
            _write("pins.json", pins)
            warns.append({"file": n["id"], "field": "gp_key", "warning":
                          f"first notice from {n['firm_name']}: pinned its signing key {fingerprint(pins[gp])}. "
                          f"Confirm this fingerprint with the GP by phone."})
        elif gp_keys.get(gp) != pins[gp]:
            warns.append({"file": n["id"], "field": "gp_key", "warning":
                          f"GP SIGNING KEY CHANGED for {n['firm_name']}: notice not opened. Confirm the new key "
                          f"{fingerprint(gp_keys.get(gp) or '')} with the GP by phone, then run `drawbook connect pin`."})
            continue
        try:
            m = open_notice(r.call("GET", f"/v1/lp/notices/{n['id']}/content"), n["sealed_key"], box_sk, pins[gp])
            if m.get("link_id") != n["link_id"] or m.get("gp_id") != gp:
                raise BadNotice("notice was addressed to a different link")
        except BadNotice as e:
            warns.append({"file": n["id"], "field": "*", "warning": f"REJECTED notice from {n['firm_name']}: {e}"})
            continue
        stamp = (m.get("created_at") or n["created_at"])[:10]
        for f in m.get("files", []):
            data = unb64(f["data"])
            if hashlib.sha256(data).hexdigest() != f["sha256"]:
                warns.append({"file": f["name"], "field": "*", "warning": "file hash does not match the signed manifest; not saved"})
                continue
            p = dest / f"{stamp}-{_safe(f['name'])}"
            i = 1
            while p.exists() and hashlib.sha256(p.read_bytes()).hexdigest() != f["sha256"]:
                p = p.with_name(f"{p.stem}-{i}{p.suffix}")
                i += 1
            p.write_bytes(data)
            saved.append({"file": str(p), "notice_id": n["id"], "gp": n["firm_name"], "fund": n["fund_name"],
                          "kind": m.get("kind"), "signed_by": fingerprint(pins[gp]), "sha256": f["sha256"]})
        log = _read("received.json", [])
        log.append({"notice_id": n["id"], "at": datetime.now(timezone.utc).isoformat(), "gp_id": gp,
                    "fund": n["fund_name"], "files": [f["name"] for f in m.get("files", [])]})
        _write("received.json", log)
        if ack:
            r.call("POST", f"/v1/lp/notices/{n['id']}/ack", {})
    return saved, warns
