"""drawbook <folder>: read every PDF (and ILPA template .xlsx) in a folder into lp-ledger.xlsx + lp-ledger.csv.

Other commands: drawbook connect ... (receive notices from GPs through the relay),
drawbook fetch <folder>, drawbook collect inbox|portal ..., drawbook review <folder>.
Run any of them with --help."""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import sys
from pathlib import Path

from . import checks, filing, fx, ledger, review, tracker, xlsx_import
from .extract import extract
from .providers import LocalProvider, OutsideProvider
from .schema import Notice


def _confirm_factory(assume_yes: bool):
    def confirm(msg: str) -> bool:
        print(f"\nWARNING: {msg}", file=sys.stderr)
        if assume_yes:
            print("(--yes given: sending)", file=sys.stderr)
            return True
        return input("Send? [y/N] ").strip().lower() == "y"
    return confirm


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] in COMMANDS:
        return COMMANDS[argv[0]](argv[1:])
    ap = argparse.ArgumentParser(prog="drawbook", description=__doc__)
    ap.add_argument("folder", type=Path)
    ap.add_argument("--out", type=Path, default=None, help="output folder (default: <folder>/drawbook-out)")
    ap.add_argument("--local-url", default=None, help="OpenAI-compatible server on this machine (default http://127.0.0.1:8080/v1)")
    ap.add_argument("--local-model", default=None)
    ap.add_argument("--no-ocr", action="store_true", help="skip OCR for scanned pages")
    g = ap.add_argument_group("outside AI (opt-in; documents leave this machine)")
    g.add_argument("--outside", choices=["anthropic", "openai-compatible"], help="use your own AI provider")
    g.add_argument("--outside-model", help="model name at that provider")
    g.add_argument("--outside-url", help="base URL (openai-compatible only)")
    g.add_argument("--outside-for", action="append", default=[],
                   help="file name pattern to send outside (repeatable). Without it, the whole folder is sent.")
    g.add_argument("--redact-figures", action="store_true", help="also replace figures with [FIGURE] before sending")
    g.add_argument("--yes", action="store_true", help="skip the per-document confirmation")
    g = ap.add_argument_group("ledger extras")
    g.add_argument("--expected", type=Path, help="expected.toml listing documents each fund should send "
                   "(default: <folder>/expected.toml if present)")
    g.add_argument("--reporting-currency", help="add amounts converted to this currency (needs --fx-rates)")
    g.add_argument("--fx-rates", type=Path, help="CSV of date,from,to,rate (your own rates; nothing is fetched)")
    g.add_argument("--file-to", type=Path, help="copy each document read to <dir>/<fund>/<date>-<kind>.pdf")
    g.add_argument("--review", action="store_true", help="after reading, go through the warnings one by one")
    g.add_argument("--feed", type=Path, action="append", default=[],
                   help="also export the ledger with this feed mapping file (repeatable; see docs/feeds.md)")
    a = ap.parse_args(argv)
    if a.reporting_currency and not a.fx_rates:
        ap.error("--reporting-currency needs --fx-rates")

    folder = a.folder
    out = a.out or folder / "drawbook-out"
    local = LocalProvider(a.local_url, a.local_model)
    outside = None
    if a.outside:
        key = os.environ.get("DRAWBOOK_OUTSIDE_KEY", "")
        if not key or not a.outside_model:
            ap.error("--outside needs --outside-model and the DRAWBOOK_OUTSIDE_KEY environment variable")
        outside = OutsideProvider(a.outside, key, a.outside_model, base_url=a.outside_url,
                                  log_path=out / "outside-send-log.jsonl", confirm=_confirm_factory(a.yes),
                                  redact_names=[], redact_figures=a.redact_figures)

    notices, warns = [], []
    files = sorted(p for p in folder.iterdir() if p.suffix.lower() in (".pdf", ".xlsx") or p.name.endswith(".drawbook.json"))
    for p in files:
        if p.name.endswith(".drawbook.json"):  # structured notice a GP sent through the relay, signature already checked
            try:
                n = Notice.model_validate_json(p.read_text())
                notices.append(n.model_copy(update={"source_file": p.name}))
            except Exception as e:  # noqa: BLE001
                warns.append({"file": p.name, "field": "*", "warning": f"could not read GP data file: {e}"})
            continue
        if p.suffix.lower() == ".xlsx":
            if xlsx_import.is_ilpa_template(p):
                notices.append(xlsx_import.read(p))
            continue
        use_outside = outside and (not a.outside_for or any(fnmatch.fnmatch(p.name, pat) for pat in a.outside_for))
        prov = outside if use_outside else local
        print(f"reading {p.name} with {prov.name}", file=sys.stderr)
        try:
            from .pdftext import read_pages
            pages = read_pages(p, ocr=not a.no_ocr)
            if use_outside:
                # local pass first finds the LP's name so it can be redacted before anything is sent
                first = extract(p, local, pages)
                outside.redact_names = [x for x in (first.notice.lp_name, first.notice.lp_id) if first.notice and x] \
                    if first.notice else []
            r = extract(p, prov, pages)
        except PermissionError:
            warns.append({"file": p.name, "field": "*", "warning": "not sent outside (declined); not read"})
            continue
        except Exception as e:  # noqa: BLE001
            warns.append({"file": p.name, "field": "*", "warning": f"could not read: {e}"})
            continue
        warns += r.warnings
        if r.notice:
            notices.append(r.notice)
    warns = checks.run(notices) + warns
    corr = review.load_corrections(out)
    if corr:
        notices = review.apply_corrections(notices, corr, src_folder=folder, warnings=warns)
    exp = a.expected or (folder / "expected.toml")
    docs = tracker.documents(notices, tracker.load_expected(exp) if exp.exists() else None)
    rates = fx.load_rates(a.fx_rates) if a.fx_rates else None
    xlsx, csv_path = ledger.write(notices, warns, out, documents_rows=docs,
                                  reporting_currency=a.reporting_currency, rates=rates)
    (out / "notices.json").write_text(json.dumps([json.loads(n.model_dump_json()) for n in notices], indent=1))
    (out / "warnings.json").write_text(json.dumps(warns, indent=1))
    from . import feeds
    feeds.write_json(notices, out / "ledger.json")
    for m in a.feed:
        print(f"feed {m.name} -> {feeds.export(notices, m, out / (m.stem + '.csv'))}", file=sys.stderr)
    if a.file_to:
        for old, new in filing.file_documents(notices, folder, a.file_to).items():
            print(f"filed {old} -> {new}", file=sys.stderr)
    late = sum(1 for d in docs if d["status"] != "received")
    print(f"{len(notices)} documents read, {len(warns)} warnings, {late} missing or late documents -> {xlsx}", file=sys.stderr)
    if a.review and not a.yes:
        review.review(out, folder)
        print("Re-run drawbook on the folder to apply your review decisions.", file=sys.stderr)
    return 0


def cmd_connect(argv: list[str]) -> int:
    from .relay import lp
    from .relay.crypto import fingerprint
    ap = argparse.ArgumentParser(prog="drawbook connect", description="Receive notices from your GPs through the "
                                 "Drawbook relay. Notices are encrypted to this device and signed by the GP.")
    ap.add_argument("--relay", help="relay address (default: $DRAWBOOK_RELAY)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("init", help="create your investor account with this device")
    s.add_argument("--label", required=True, help="the name your GPs will see, e.g. 'Example Pension Scheme'")
    s.add_argument("--device", default="first device")
    s = sub.add_parser("invite", help="make an invite to send to one GP for one fund")
    s.add_argument("fund"); s.add_argument("--gp-email"); s.add_argument("--as", dest="label", help="name shown to this GP")
    s = sub.add_parser("hold", help="opt in: tell GPs 'an investor wants this fund's notices via Drawbook' (name only)")
    s.add_argument("fund"); s.add_argument("--remove", action="store_true")
    sub.add_parser("links", help="list linked GPs and their key fingerprints")
    s = sub.add_parser("pin", help="accept a GP's new signing key after checking its fingerprint by phone")
    s.add_argument("gp_id")
    s = sub.add_parser("join", help="team: on a NEW device, make a join request (or store the grant with --grant)")
    s.add_argument("--label", default="team device"); s.add_argument("--grant")
    s = sub.add_parser("approve", help="team: on an EXISTING device, approve a join request")
    s.add_argument("request")
    a = ap.parse_args(argv)
    if a.cmd == "init":
        out = lp.init(a.relay, a.label, a.device)
        print(f"Account {out['account_id']} created. Next: drawbook connect invite \"<fund name>\"")
    elif a.cmd == "invite":
        out = lp.invite(a.fund, a.label, a.gp_email)
        print(out["email_text"])
    elif a.cmd == "hold":
        lp.hold(a.fund, a.remove)
        print("removed" if a.remove else "noted (fund name only)")
    elif a.cmd == "links":
        for l in lp.links():
            print(f"{l['gp_id']}  {l['firm_name']}  {l['fund_name']}  key {l['fingerprint']}  [{l['pin']}]")
    elif a.cmd == "pin":
        l = next((x for x in lp.links() if x["gp_id"] == a.gp_id), None)
        if not l:
            ap.error("no linked GP with that id")
        if input(f"Pin key {fingerprint(l['gp_sign_pk'])} for {l['firm_name']}? Did the GP confirm it by phone? [y/N] ").lower() != "y":
            return 1
        lp.pin(a.gp_id, l["gp_sign_pk"])
    elif a.cmd == "join":
        if a.grant:
            lp.join(a.grant)
            print("This device now receives your account's notices (new ones only).")
        else:
            print("On a device already connected, run:\n  drawbook connect approve " + lp.join_request(a.label))
    elif a.cmd == "approve":
        print("On the new device, run:\n  drawbook connect join --grant " + lp.approve(a.request))
    return 0


def cmd_fetch(argv: list[str]) -> int:
    from .relay import lp
    ap = argparse.ArgumentParser(prog="drawbook fetch", description="Download, decrypt and check notices GPs sent you.")
    ap.add_argument("folder", type=Path)
    ap.add_argument("--keep", action="store_true", help="leave them on the relay (another fetch gets them again)")
    a = ap.parse_args(argv)
    saved, warns = lp.fetch(a.folder, ack=not a.keep)
    for s in saved:
        print(f"saved {s['file']}  ({s['gp']}, {s['fund']}, signed {s['signed_by']})")
    for w in warns:
        print(f"WARNING: {w['warning']}", file=sys.stderr)
    print(f"{len(saved)} files saved. Next: drawbook {a.folder}", file=sys.stderr)
    return 0


def cmd_collect(argv: list[str]) -> int:
    from datetime import date
    from .collect import inbox
    ap = argparse.ArgumentParser(prog="drawbook collect", description="Collect notice documents into a folder.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("inbox", help="from email (IMAP, or a folder of .eml / Apple Mail .emlx files)")
    s.add_argument("dest", type=Path)
    s.add_argument("--imap-host"); s.add_argument("--imap-port", type=int, default=993); s.add_argument("--imap-user")
    s.add_argument("--mailbox", default="INBOX")
    s.add_argument("--keychain-service", help="macOS Keychain item holding the mail password "
                   "(otherwise $DRAWBOOK_IMAP_PASSWORD)")
    s.add_argument("--mail-folder", type=Path, help="read .eml/.emlx files here instead of IMAP")
    s.add_argument("--since", type=date.fromisoformat)
    s.add_argument("--sender", action="append", help="only from this address or domain (repeatable)")
    s.add_argument("--any-subject", action="store_true", help="don't filter on subject words")
    s = sub.add_parser("portal", help="log in to a GP portal with your own login and download new documents")
    s.add_argument("config", type=Path); s.add_argument("dest", type=Path); s.add_argument("--headed", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "portal":
        from .collect import portal
        got = portal.collect(a.config, a.dest, headed=a.headed)
        print(f"{len(got)} new documents -> {a.dest}", file=sys.stderr)
        return 0
    words = [] if a.any_subject else None
    if a.mail_folder:
        got = inbox.collect_folder(a.mail_folder, a.dest, a.since, a.sender, words)
    else:
        if not (a.imap_host and a.imap_user):
            ap.error("give --imap-host and --imap-user, or --mail-folder")
        pw = inbox.password_from_keychain(a.keychain_service or a.imap_host, a.imap_user)
        got = inbox.collect_imap(a.imap_host, a.imap_port, a.imap_user, pw, a.mailbox, a.dest, a.since, a.sender, words)
    for d in got:
        print(f"saved {d.saved_name}  ({d.sender}: {d.subject})")
    print(f"{len(got)} new documents -> {a.dest}", file=sys.stderr)
    return 0


def cmd_review(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="drawbook review", description="Go through a run's warnings: accept, correct or "
                                 "mark 'asked GP'. Decisions apply on the next run.")
    ap.add_argument("folder", type=Path); ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    review.review(a.out or a.folder / "drawbook-out", a.folder)
    return 0


def cmd_feed(argv: list[str]) -> int:
    from . import addepar
    ap = argparse.ArgumentParser(prog="drawbook feed", description="Build Addepar transactions from a finished run "
                                 "(POST /v1/transactions). Writes the request bodies to a file; sends only with --send.")
    ap.add_argument("target", choices=["addepar"])
    ap.add_argument("folder", type=Path, help="the notices folder you ran drawbook on")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--owner", required=True, help="Addepar entity ID of your portfolio or account")
    ap.add_argument("--funds", type=Path, required=True, help="JSON file {fund name as in the ledger: Addepar entity ID}")
    ap.add_argument("--send", metavar="BASE_URL", help="e.g. https://yourfirm.addepar.com/api; key from $ADDEPAR_TOKEN "
                    "(base64 of key:secret) and firm from $ADDEPAR_FIRM")
    a = ap.parse_args(argv)
    out = a.out or a.folder / "drawbook-out"
    notices = [Notice.model_validate(n) for n in json.loads((out / "notices.json").read_text())]
    payloads, skipped = addepar.build_payloads(notices, a.owner, json.loads(a.funds.read_text()))
    (out / "addepar-payloads.json").write_text(json.dumps(payloads, indent=1))
    n = sum(len(p["data"]) for p in payloads)
    for s in skipped:
        print(f"skipped {s['file']} p{s['page']} {s['type']}: {s['reason']}", file=sys.stderr)
    print(f"{n} transactions -> {out / 'addepar-payloads.json'}", file=sys.stderr)
    if a.send:
        tok, firm = os.environ.get("ADDEPAR_TOKEN"), os.environ.get("ADDEPAR_FIRM")
        if not (tok and firm):
            ap.error("--send needs $ADDEPAR_TOKEN and $ADDEPAR_FIRM")
        if input(f"Write {n} transactions to Addepar firm {firm} at {a.send}? Try one test transaction first. [y/N] ").lower() != "y":
            return 1
        addepar.send(payloads, a.send, tok, firm)
        print("sent", file=sys.stderr)
    return 0


COMMANDS = {"feed": cmd_feed, "connect": cmd_connect, "fetch": cmd_fetch, "collect": cmd_collect, "review": cmd_review}


if __name__ == "__main__":
    sys.exit(main())
