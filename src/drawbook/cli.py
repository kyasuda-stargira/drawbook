"""drawbook <folder>: read every PDF (and ILPA template .xlsx) in a folder into lp-ledger.xlsx + lp-ledger.csv."""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import sys
from pathlib import Path

from . import checks, ledger, xlsx_import
from .extract import extract
from .providers import LocalProvider, OutsideProvider


def _confirm_factory(assume_yes: bool):
    def confirm(msg: str) -> bool:
        print(f"\nWARNING: {msg}", file=sys.stderr)
        if assume_yes:
            print("(--yes given: sending)", file=sys.stderr)
            return True
        return input("Send? [y/N] ").strip().lower() == "y"
    return confirm


def main(argv: list[str] | None = None) -> int:
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
    a = ap.parse_args(argv)

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
    files = sorted(p for p in folder.iterdir() if p.suffix.lower() in (".pdf", ".xlsx"))
    for p in files:
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
    xlsx, csv_path = ledger.write(notices, warns, out)
    (out / "notices.json").write_text(json.dumps([json.loads(n.model_dump_json()) for n in notices], indent=1))
    print(f"{len(notices)} documents read, {len(warns)} warnings -> {xlsx}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
