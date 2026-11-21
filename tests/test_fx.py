"""Reporting currency: rate on or before the notice date from the user's CSV; missing rate -> Warning."""
import csv
from datetime import date
from decimal import Decimal

from openpyxl import load_workbook

from drawbook import fx, ledger
from drawbook.ledger import TX_COLS
from drawbook.schema import Notice, Transaction


def N(f, ccy, d, amt="1000"):
    t = Transaction(description="Investments", transaction_type="Capital Call: Investments", lp_amount=Decimal(amt),
                    impact_on_unfunded="Decrease", inside_outside="Inside", page=1)
    return Notice(source_file=f, kind="capital_call", notice_date=d, fund_name=f"Fund {ccy}", fund_currency=ccy,
                  transactions=[t])


def _rates(tmp_path):
    p = tmp_path / "rates.csv"
    p.write_text("date,from,to,rate\n2026-01-31,USD,GBP,0.80\n2026-02-28,USD,GBP,0.75\n2026-03-31,USD,GBP,0.70\n"
                 "2026-02-01,GBP,EUR,1.25\n")
    return fx.load_rates(p)


def test_rate_on_or_before(tmp_path):
    r = _rates(tmp_path)
    assert fx.rate_on(r, date(2026, 3, 15), "USD", "GBP") == (Decimal("0.75"), date(2026, 2, 28))
    assert fx.rate_on(r, date(2026, 1, 1), "USD", "GBP") is None
    assert fx.rate_on(r, date(2026, 3, 1), "EUR", "GBP") == (Decimal(1) / Decimal("1.25"), date(2026, 2, 1))
    assert fx.rate_on(r, date(2026, 3, 1), "GBP", "GBP") == (Decimal(1), None)


def test_ledger_reporting_columns_and_warning(tmp_path):
    ns = [N("usd.pdf", "USD", date(2026, 3, 15)), N("gbp.pdf", "GBP", date(2026, 3, 15), "500"),
          N("jpy.pdf", "JPY", date(2026, 3, 15)), N("usd_early.pdf", "USD", date(2026, 1, 1))]
    ledger.write(ns, [], tmp_path, reporting_currency="gbp", rates=_rates(tmp_path))
    wb = load_workbook(tmp_path / "lp-ledger.xlsx")
    ws = wb["Transactions"]
    head = [c.value for c in ws[1]]
    assert head == TX_COLS + fx.FX_COLS  # existing columns unchanged, new ones appended
    rows = {r[head.index("source_file")]: dict(zip(head, r)) for r in ws.iter_rows(min_row=2, values_only=True)}
    assert rows["usd.pdf"]["lp_amount_reporting"] == 750
    assert rows["gbp.pdf"]["lp_amount_reporting"] == 500
    assert rows["jpy.pdf"]["lp_amount_reporting"] is None
    assert rows["usd_early.pdf"]["fx_rate"] is None
    warns = {(r[0], r[1]) for r in wb["Warnings"].iter_rows(min_row=2, values_only=True)}
    assert warns == {("jpy.pdf", "fx_rate"), ("usd_early.pdf", "fx_rate")}
    with (tmp_path / "lp-ledger.csv").open() as f:
        assert csv.DictReader(f).fieldnames == TX_COLS + fx.FX_COLS


def test_ledger_unchanged_without_reporting_currency(tmp_path):
    ledger.write([N("usd.pdf", "USD", date(2026, 3, 15))], [], tmp_path)
    wb = load_workbook(tmp_path / "lp-ledger.xlsx")
    assert wb.sheetnames == ["Fund", "Transactions", "Balances", "Warnings"]
    assert [c.value for c in wb["Transactions"][1]] == TX_COLS
