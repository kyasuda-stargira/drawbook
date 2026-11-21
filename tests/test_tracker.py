"""Expected quarterly statements: received / late / missing; overdue capital calls flagged."""
from datetime import date

from openpyxl import load_workbook

from drawbook import ledger
from drawbook.schema import Notice
from drawbook.tracker import DOC_COLS, documents, load_expected, period_of


def N(f, kind, d, fund="Alpha Fund", due=None):
    return Notice(source_file=f, kind=kind, notice_date=d, due_date=due, fund_name=fund, fund_currency="USD", lp_id="LP1")


def test_period_of():
    assert period_of(date(2026, 3, 31)) == date(2026, 3, 31)
    assert period_of(date(2026, 5, 15)) == date(2026, 3, 31)
    assert period_of(date(2026, 1, 10)) == date(2025, 12, 31)


def test_statements_received_late_missing():
    ns = [N("q4.pdf", "capital_account_statement", date(2026, 2, 10)),   # Q4 2025, due 1 Mar: received
          N("q2.pdf", "capital_account_statement", date(2026, 9, 15))]   # Q2 2026, due 29 Aug: late
    rows = documents(ns, today=date(2026, 11, 21))
    got = {r["period"]: (r["status"], r["file"]) for r in rows}
    assert got == {"2025-Q4": ("received", "q4.pdf"), "2026-Q1": ("missing", None),
                   "2026-Q2": ("late", "q2.pdf")}  # Q3 is due 29 Nov, not yet counted
    assert documents(ns, today=date(2026, 12, 1))[-1]["period"] == "2026-Q3"


def test_expected_toml_and_lag(tmp_path):
    p = tmp_path / "expected.toml"
    p.write_text('due_days = 60\n[funds."alpha  FUND"]\nkinds = ["capital_account_statement"]\ndue_days = 30\n')
    ns = [N("c1.pdf", "capital_call", date(2026, 4, 1), due=date(2026, 4, 15)),
          N("d1.pdf", "distribution", date(2026, 6, 1))]
    rows = documents(ns, load_expected(p), today=date(2026, 8, 1))
    # no statement seen, but the file expects them from the first document's quarter (Q1), 30-day lag
    assert [(r["period"], r["status"]) for r in rows] == [("2026-Q1", "missing"), ("2026-Q2", "missing")]
    assert documents(ns, today=date(2026, 8, 1)) == []  # without the file, nothing is expected


def test_overdue_call_without_later_document():
    ns = [N("c1.pdf", "capital_call", date(2026, 1, 5), due=date(2026, 1, 20)),
          N("c2.pdf", "capital_call", date(2026, 6, 1), due=date(2026, 6, 15))]
    rows = documents(ns, today=date(2026, 7, 1))
    assert [(r["file"], r["status"], r["expected_kind"]) for r in rows] == \
        [("c2.pdf", "late", "document after capital call")]
    assert documents(ns, today=date(2026, 6, 10)) == []  # not yet due


def test_ledger_documents_sheet(tmp_path):
    ns = [N("q4.pdf", "capital_account_statement", date(2026, 2, 10))]
    ledger.write(ns, [], tmp_path, documents_rows=documents(ns, today=date(2026, 3, 5)))
    wb = load_workbook(tmp_path / "lp-ledger.xlsx")
    assert wb.sheetnames == ["Fund", "Transactions", "Balances", "Warnings", "Documents"]
    assert [c.value for c in wb["Documents"][1]] == DOC_COLS
    assert wb["Documents"][2][4].value == "received"
