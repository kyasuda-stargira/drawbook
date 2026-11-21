"""Reviewer decisions: saved per file + sha256 + field, applied on re-run, noted in Warnings."""
import json
from datetime import date
from decimal import Decimal

from openpyxl import load_workbook

from drawbook import ledger, review
from drawbook.schema import Notice


def _run(tmp_path):
    src = tmp_path / "src"; out = tmp_path / "out"
    src.mkdir(); out.mkdir()
    (src / "call1.pdf").write_bytes(b"%PDF fake call 1")
    n = Notice(source_file="call1.pdf", kind="capital_call", notice_date=date(2026, 3, 1), fund_name="Alpha Fund",
               fund_currency="USD", lp_commitment=Decimal("1000000"), lp_contributions_current=Decimal("25000"),
               pages={"lp_commitment": 1, "lp_contributions_current": 1})
    (out / "notices.json").write_text(json.dumps([json.loads(n.model_dump_json())]))
    warns = [{"file": "call1.pdf", "field": "lp_contributions_current", "warning": "figure looks odd"},
             {"file": "call1.pdf", "field": "lp_commitment", "warning": "check commitment"},
             {"file": "call1.pdf", "field": "balances", "warning": "cumulative contributions do not tie"}]
    ledger.write([n], warns, out)  # review reads the Warnings sheet when no warnings.json exists
    return src, out, n


def _answers(*xs):
    it = iter(xs)
    return lambda prompt: next(it)


def test_review_saves_decisions_and_shows_snippet(tmp_path):
    src, out, _ = _run(tmp_path)
    said = []
    # first warning: correct with a bad then a good value; second: accept; third: 'c' not offered -> asked GP
    review.review(out, src, ask=_answers("c", "not a number", "26000", "a", "c", "g"), say=said.append,
                  page_text=lambda path, page: "Header text. Your share of this call: 25000 USD due 15 March.")
    saved = json.loads((out / "corrections.json").read_text())
    assert [c["action"] for c in saved] == ["correct", "accept", "asked_gp"]
    assert saved[0]["value"] == "26000" and saved[0]["was"] == "25000"
    assert saved[0]["sha256"] == review.sha256(src / "call1.pdf")
    assert any("Your share of this call: 25000" in s for s in said)
    assert any("not a valid" in s for s in said)
    # a second session has nothing left to review
    said.clear()
    review.review(out, src, ask=_answers(), say=said.append, page_text=lambda p, n: "")
    assert said[0] == "0 warnings to review"


def test_quit_keeps_earlier_decisions(tmp_path):
    src, out, _ = _run(tmp_path)
    review.review(out, src, ask=_answers("a", "q"), say=lambda s: None, page_text=lambda p, n: "")
    assert len(json.loads((out / "corrections.json").read_text())) == 1


def test_apply_corrections_and_ledger_note(tmp_path):
    src, out, n = _run(tmp_path)
    corr = [{"source_file": "call1.pdf", "sha256": review.sha256(src / "call1.pdf"),
             "field": "lp_contributions_current", "action": "correct", "value": "26000"},
            {"source_file": "call1.pdf", "sha256": review.sha256(src / "call1.pdf"),
             "field": "lp_commitment", "action": "asked_gp", "value": None}]
    warns = []
    fixed = review.apply_corrections([n], corr, src_folder=src, warnings=warns)
    assert fixed[0].lp_contributions_current == Decimal("26000")
    assert n.lp_contributions_current == Decimal("25000")  # input left alone
    assert any("corrected by reviewer: was 25000, now 26000" in w["warning"] for w in warns)
    assert any("asked GP" in w["warning"] for w in warns)
    ledger.write(fixed, warns, out)
    ws = load_workbook(out / "lp-ledger.xlsx")["Balances"]
    head = [c.value for c in ws[1]]
    assert ws[2][head.index("lp_contributions_current")].value == 26000
    notes = [r[2] for r in load_workbook(out / "lp-ledger.xlsx")["Warnings"].iter_rows(min_row=2, values_only=True)]
    assert any("corrected by reviewer" in x for x in notes)


def test_changed_file_is_not_corrected(tmp_path):
    src, out, n = _run(tmp_path)
    corr = [{"source_file": "call1.pdf", "sha256": "0" * 64, "field": "lp_contributions_current",
             "action": "correct", "value": "26000"}]
    warns = []
    fixed = review.apply_corrections([n], corr, src_folder=src, warnings=warns)
    assert fixed[0].lp_contributions_current == Decimal("25000")
    assert "file changed since review" in warns[0]["warning"]


def test_snippet_finds_formatted_figure():
    s = review.snippet("a" * 300 + " Amount due 1,250,000.00 now " + "b" * 300, Decimal("1250000"))
    assert "1,250,000.00" in s and len(s) < 250
