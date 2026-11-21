"""drawbook review: walk a run's Warnings in the terminal and record what the reviewer decided.

Each decision is saved to <out>/corrections.json, keyed by source file + sha256 of that file + field:
  accept   - the value stands as read
  correct  - the reviewer typed the right value; a re-run puts it in the ledger
  asked_gp - the question is with the GP
A correction is applied only while the source file is unchanged (same sha256).
"""
from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Callable

from .schema import SCALAR_FIELDS, Notice

ACTIONS = {"a": "accept", "c": "correct", "g": "asked_gp"}


def sha256(path: Path) -> str | None:
    path = Path(path)
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def key(d: dict) -> tuple:
    return (d["source_file"], d["sha256"], d["field"])


def load_notices(out_dir: Path) -> list[Notice]:
    return [Notice.model_validate(x) for x in json.loads((Path(out_dir) / "notices.json").read_text())]


def load_warnings(out_dir: Path) -> list[dict]:
    """warnings.json if the run wrote one, else the Warnings sheet of lp-ledger.xlsx."""
    out_dir = Path(out_dir)
    if (out_dir / "warnings.json").exists():
        return json.loads((out_dir / "warnings.json").read_text())
    from openpyxl import load_workbook
    ws = load_workbook(out_dir / "lp-ledger.xlsx", read_only=True)["Warnings"]
    rows = list(ws.iter_rows(min_row=2, values_only=True))
    return [{"file": f, "field": fld, "warning": w} for f, fld, w in rows if f is not None]


def load_corrections(out_dir: Path) -> list[dict]:
    p = Path(out_dir) / "corrections.json"
    return json.loads(p.read_text()) if p.exists() else []


def save_corrections(out_dir: Path, corrections: list[dict]) -> Path:
    p = Path(out_dir) / "corrections.json"
    p.write_text(json.dumps(corrections, indent=1, default=str))
    return p


def _set(n: Notice, field: str, value: str) -> Notice:
    """Return a copy of n with field set from the typed text; raises ValueError if the text does not fit the field."""
    data = n.model_dump()
    data[field] = value.strip() or None
    return Notice.model_validate(data)


def snippet(text: str, value, width: int = 160) -> str:
    """The page text around the printed value, or the start of the page if the value is not found."""
    text = " ".join((text or "").split())
    needles = [str(value)] if value is not None else []
    try:
        needles.append(f"{float(value):,.2f}")
    except (TypeError, ValueError):
        pass
    for s in needles:
        i = text.find(s)
        if s and i >= 0:
            a = max(0, i - width // 2)
            return ("..." if a else "") + text[a:i + len(s) + width // 2] + "..."
    return text[:width] + ("..." if len(text) > width else "")


def _default_page_text(path: Path, page: int) -> str:
    from .pdftext import read_pages
    if path.suffix.lower() != ".pdf" or not path.is_file():
        return ""
    pages = read_pages(path, ocr=False)
    return pages[page - 1].text if 0 < page <= len(pages) else ""


def review(out_dir: Path, src_folder: Path, ask: Callable[[str], str] = input, say: Callable[[str], None] = print,
           page_text: Callable[[Path, int], str] = _default_page_text) -> list[dict]:
    """Walk each warning not yet decided; save decisions after each one. Returns all decisions."""
    out_dir, src_folder = Path(out_dir), Path(src_folder)
    notices = {n.source_file: n for n in load_notices(out_dir)}
    corrections = load_corrections(out_dir)
    done = {key(c) for c in corrections}
    hashes: dict[str, str | None] = {}
    todo: dict[tuple, list[str]] = {}  # one decision per file + field, covering all its warnings
    for w in load_warnings(out_dir):
        if w["file"] not in hashes:
            hashes[w["file"]] = sha256(src_folder / w["file"])
        k = (w["file"], hashes[w["file"]], w["field"])
        if k not in done:
            todo.setdefault(k, []).append(w["warning"])
    say(f"{len(todo)} warnings to review")
    for i, ((file, digest, field), texts) in enumerate(todo.items(), start=1):
        n = notices.get(file)
        value = getattr(n, field, None) if n and field in SCALAR_FIELDS else None
        page = n.pages.get(field) if n else None
        say(f"\n[{i}/{len(todo)}] {file}  field: {field}" + (f"  page {page}" if page else ""))
        for t in texts:
            say(f"  warning: {t}")
        if n and field in SCALAR_FIELDS:
            say(f"  value:   {value}")
        if page:
            text = page_text(src_folder / file, page)
            if text:
                say(f"  page text: {snippet(text, value)}")
        can_correct = n is not None and field in SCALAR_FIELDS
        choices = "[a]ccept, " + ("[c]orrect, " if can_correct else "") + "asked [g]P, [s]kip, [q]uit"
        while True:
            ans = ask(f"  {choices}: ").strip().lower()[:1]
            if ans in ("s", "q") or ans in ACTIONS and (ans != "c" or can_correct):
                break
        if ans == "q":
            break
        if ans == "s":
            continue
        d = {"source_file": file, "sha256": digest, "field": field, "action": ACTIONS[ans], "value": None,
             "was": None if value is None else str(value), "warning": "; ".join(texts), "decided": date.today().isoformat()}
        if ans == "c":
            while True:
                typed = ask(f"  new value for {field}: ")
                try:
                    new = getattr(_set(n, field, typed), field)
                    break
                except ValueError as e:
                    say(f"  not a valid {field}: {str(e).splitlines()[-1]}")
            d["value"] = None if new is None else (new.value if hasattr(new, "value") else str(new))
        corrections.append(d)
        save_corrections(out_dir, corrections)
    return corrections


def apply_corrections(notices: list[Notice], corrections: list[dict], src_folder: Path | None = None,
                      warnings: list[dict] | None = None) -> list[Notice]:
    """Return notices with reviewer corrections applied (later decisions win).

    With src_folder, a decision whose file has changed since review (different sha256) is not applied.
    With warnings, a note per decision is appended to that list for the ledger's Warnings sheet.
    """
    latest = {key(c): c for c in corrections}
    by_file: dict[str, list[dict]] = {}
    for c in latest.values():
        by_file.setdefault(c["source_file"], []).append(c)
    out = []
    for n in notices:
        digest = sha256(Path(src_folder) / n.source_file) if src_folder is not None else None
        for c in by_file.get(n.source_file, []):
            if src_folder is not None and c["sha256"] != digest:
                if warnings is not None:
                    warnings.append({"file": n.source_file, "field": c["field"],
                                     "warning": "file changed since review; reviewer decision not applied"})
                continue
            if c["action"] == "correct":
                was = getattr(n, c["field"])
                n = _set(n, c["field"], "" if c["value"] is None else str(c["value"]))
                msg = f"corrected by reviewer: was {was}, now {getattr(n, c['field'])}"
            elif c["action"] == "accept":
                msg = "accepted by reviewer"
            else:
                msg = "asked GP; awaiting answer"
            if warnings is not None:
                warnings.append({"file": n.source_file, "field": c["field"], "warning": msg})
        out.append(n)
    return out
