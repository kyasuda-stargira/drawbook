"""GP side of the relay: sign up, describe funds (optionally listed in Conduit), accept LP invites,
send signed and sealed notices. Usable as a library (GPClient) or as the `drawbook-gp` command.

State lives in DRAWBOOK_GP_HOME (default ~/.drawbook-gp): gp.json (relay, gp id, API key,
signing key; mode 600). Fund administrators can call the same HTTP API from any language
with libsodium: see docs/gp-api.md.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from nacl.signing import SigningKey

from . import Relay, b64, unb64
from .crypto import fingerprint, new_sign_key, seal

KINDS = ("capital_call", "distribution", "combined", "capital_account_statement", "other")


def home() -> Path:
    return Path(os.environ.get("DRAWBOOK_GP_HOME") or Path.home() / ".drawbook-gp")


class GPClient:
    def __init__(self, state: dict):
        self.state = state
        self.relay = Relay(state["relay"], state.get("api_key"))
        self.signer = SigningKey(unb64(state["sign_sk"]))

    # --- set-up ---
    @staticmethod
    def signup(relay_url: str | None, firm_name: str, email: str, website: str) -> dict:
        """Step 1: the relay emails a 6-digit code to an address at the firm's website domain."""
        out = Relay(relay_url).call("POST", "/v1/gp/signup", {"firm_name": firm_name, "email": email, "website": website})
        out["relay"] = Relay(relay_url).base
        return out

    @classmethod
    def verify(cls, relay_url: str | None, signup_id: str, code: str, profile: dict | None = None,
               conduit_consent: bool = False, save: bool = True) -> "GPClient":
        """Step 2: prove the code; creates the firm, its API key and its signing key."""
        sign = new_sign_key()
        r = Relay(relay_url)
        out = r.call("POST", "/v1/gp/verify", {"signup_id": signup_id, "code": code, "sign_pk": b64(bytes(sign.verify_key)),
                                               "profile": profile or {}, "conduit_consent": conduit_consent})
        state = {"relay": r.base, "gp_id": out["gp_id"], "api_key": out["api_key"], "sign_sk": b64(bytes(sign))}
        if save:
            cls.save(state)
        return cls(state)

    @staticmethod
    def save(state: dict) -> None:
        home().mkdir(parents=True, exist_ok=True, mode=0o700)
        p = home() / "gp.json"
        if p.exists() and json.loads(p.read_text()).get("gp_id") != state["gp_id"]:
            raise RuntimeError(f"{p} already holds another firm's keys; set DRAWBOOK_GP_HOME to another folder")
        p.write_text(json.dumps(state, indent=1))
        p.chmod(0o600)

    @classmethod
    def load(cls) -> "GPClient":
        p = home() / "gp.json"
        if not p.exists():
            raise RuntimeError("not signed up: run `drawbook-gp signup` then `drawbook-gp verify`")
        return cls(json.loads(p.read_text()))

    def fingerprint(self) -> str:
        return fingerprint(b64(bytes(self.signer.verify_key)))

    # --- profile (shared with Conduit only with consent) ---
    def update_profile(self, profile: dict | None = None, conduit_consent: bool | None = None) -> dict:
        body = {}
        if profile is not None:
            body["profile"] = profile
        if conduit_consent is not None:
            body["conduit_consent"] = conduit_consent
        return self.relay.call("PATCH", "/v1/gp/me", body)

    def add_fund(self, name: str, profile: dict | None = None, conduit_consent: bool = False,
                 fund_id: str | None = None) -> str:
        body = {"name": name, "profile": profile or {}, "conduit_consent": conduit_consent}
        if fund_id:
            return self.relay.call("PUT", f"/v1/gp/funds/{fund_id}", body)["fund_id"]
        return self.relay.call("POST", "/v1/gp/funds", body)["fund_id"]

    def funds(self) -> list[dict]:
        return self.relay.call("GET", "/v1/gp/funds")["funds"]

    def demand(self) -> list[dict]:
        return self.relay.call("GET", "/v1/gp/demand")["funds"]

    # --- investors ---
    def view_invite(self, code: str) -> dict:
        return self.relay.call("GET", f"/v1/gp/invites/{code}")

    def accept_invite(self, code: str, fund_id: str, gp_lp_ref: str | None = None) -> str:
        return self.relay.call("POST", f"/v1/gp/invites/{code}/accept", {"fund_id": fund_id, "gp_lp_ref": gp_lp_ref})["link_id"]

    def links(self) -> list[dict]:
        return self.relay.call("GET", "/v1/gp/links")["links"]

    def rotate_key(self) -> str:
        """New signing key. Every linked LP must re-confirm the new fingerprint before notices open."""
        sign = new_sign_key()
        out = self.relay.call("POST", "/v1/gp/keys", {"sign_pk": b64(bytes(sign.verify_key))})
        self.state.update(api_key=out["api_key"], sign_sk=b64(bytes(sign)))
        self.save(self.state)
        self.relay.token, self.signer = out["api_key"], sign
        return self.fingerprint()

    # --- send ---
    def send(self, link_id: str, files: list[Path], kind: str = "capital_call") -> str:
        """Seal files (PDF, ILPA template .xlsx and/or a .drawbook.json notice) to every device of the LP."""
        if kind not in KINDS:
            raise ValueError(f"kind must be one of {KINDS}")
        link = next((l for l in self.links() if l["link_id"] == link_id), None)
        if not link:
            raise ValueError(f"no open link {link_id}")
        entries = []
        for f in map(Path, files):
            data = f.read_bytes()
            entries.append({"name": f.name, "sha256": hashlib.sha256(data).hexdigest(), "data": b64(data)})
        manifest = {"v": 1, "link_id": link_id, "gp_id": self.state["gp_id"], "fund_id": link["fund_id"], "kind": kind,
                    "created_at": datetime.now(timezone.utc).isoformat(), "files": entries}
        ct, keys = seal(manifest, self.signer, {m["member_id"]: m["box_pk"] for m in link["members"]})
        out = self.relay.call("POST", "/v1/gp/notices", raw=ct, headers={
            "x-drawbook-link": link_id, "x-drawbook-kind": kind, "x-drawbook-keys": b64(json.dumps(keys).encode())})
        return out["notice_id"]


def _profile(path: str | None) -> dict:
    return json.loads(Path(path).read_text()) if path else {}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="drawbook-gp", description="Send investor notices through Drawbook.")
    ap.add_argument("--relay", help="relay address (default: $DRAWBOOK_RELAY)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("signup", help="step 1: get a code by email")
    s.add_argument("--firm", required=True); s.add_argument("--email", required=True); s.add_argument("--website", required=True)
    s = sub.add_parser("verify", help="step 2: enter the code")
    s.add_argument("signup_id"); s.add_argument("code")
    s.add_argument("--profile", help="JSON file with firm facts (see docs/gp-api.md)")
    s.add_argument("--conduit", action="store_true", help="let Stargira list the firm profile in the Conduit directory")
    s = sub.add_parser("fund", help="add or update a fund")
    s.add_argument("name"); s.add_argument("--profile"); s.add_argument("--conduit", action="store_true"); s.add_argument("--fund-id")
    sub.add_parser("funds", help="list funds and how many investors ask for notices via Drawbook")
    s = sub.add_parser("accept", help="accept an investor's invite for one of your funds")
    s.add_argument("code"); s.add_argument("--fund-id", required=True); s.add_argument("--lp-ref", help="your own investor id")
    sub.add_parser("links", help="list linked investors")
    s = sub.add_parser("send", help="send a notice to one linked investor")
    s.add_argument("link_id"); s.add_argument("files", nargs="+", type=Path); s.add_argument("--kind", default="capital_call", choices=KINDS)
    sub.add_parser("rotate-key", help="replace your signing key (investors must re-confirm it)")
    sub.add_parser("whoami")
    a = ap.parse_args(argv)

    if a.cmd == "signup":
        out = GPClient.signup(a.relay, a.firm, a.email, a.website)
        print(f"Code sent to {out['sent_to']}. Next: drawbook-gp verify {out['signup_id']} <code>")
        if "dev_code" in out:
            print(f"(test relay) code: {out['dev_code']}")
        return 0
    if a.cmd == "verify":
        c = GPClient.verify(a.relay, a.signup_id, a.code, _profile(a.profile), a.conduit)
        print(f"Signed up as {c.state['gp_id']}. Your signing-key fingerprint: {c.fingerprint()}")
        print("Investors will be asked to confirm this fingerprint with you by phone.")
        return 0
    c = GPClient.load()
    if a.cmd == "fund":
        print(c.add_fund(a.name, _profile(a.profile), a.conduit, a.fund_id))
    elif a.cmd == "funds":
        d = {x["fund_id"]: x for x in c.demand()}
        for f in c.funds():
            x = d.get(f["fund_id"], {})
            print(f"{f['fund_id']}  {f['name']}  conduit={'yes' if f['conduit_consent'] else 'no'}  "
                  f"investors asking={x.get('investors_asking', '0')}  linked={x.get('investors_linked', 0)}")
    elif a.cmd == "accept":
        inv = c.view_invite(a.code)
        print(f"Invite from {inv['lp_label']} for {inv['fund_name']}")
        print(c.accept_invite(a.code, a.fund_id, a.lp_ref))
    elif a.cmd == "links":
        for l in c.links():
            print(f"{l['link_id']}  fund={l['fund_id']}  investor={l['lp_label']}  your ref={l['gp_lp_ref'] or '-'}  devices={len(l['members'])}")
    elif a.cmd == "send":
        print(c.send(a.link_id, a.files, a.kind))
    elif a.cmd == "rotate-key":
        print(f"New fingerprint: {c.rotate_key()}. Tell your investors before your next notice.")
    elif a.cmd == "whoami":
        print(f"{c.state['gp_id']}  fingerprint {c.fingerprint()}  relay {c.state['relay']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
