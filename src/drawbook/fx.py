"""Reporting-currency amounts from a user-supplied FX rates CSV (columns: date, from, to, rate). No fetching.

Each amount uses the latest rate on or before its notice date. A rate given the other way round is inverted.
No rate found -> a warning and blank reporting columns, never a guess.
"""
from __future__ import annotations

import csv
from datetime import date
from decimal import Decimal
from pathlib import Path

from .schema import Notice

FX_COLS = ["reporting_currency", "fx_rate", "fx_rate_date", "lp_amount_reporting", "net_called_distributed_reporting"]
CENT = Decimal("0.01")


def load_rates(path: Path) -> list[tuple[date, str, str, Decimal]]:
    with Path(path).open(newline="") as f:
        return [(date.fromisoformat(r["date"].strip()), r["from"].strip().upper(), r["to"].strip().upper(),
                 Decimal(r["rate"].strip())) for r in csv.DictReader(f)]


def rate_on(rates, d: date, frm: str, to: str) -> tuple[Decimal, date | None] | None:
    """(rate, rate date) for frm->to on or before d, or None."""
    if frm == to:
        return Decimal(1), None
    best = None
    for rd, a, b, r in rates:
        if rd > d:
            continue
        if (a, b) == (frm, to):
            cand = (rd, r)
        elif (a, b) == (to, frm) and r:
            cand = (rd, 1 / r)
        else:
            continue
        if best is None or cand[0] > best[0]:
            best = cand
    return (best[1], best[0]) if best else None


def add_reporting(rows: list[dict], notices: list[Notice], rates, currency: str) -> list[dict]:
    """Add FX_COLS to each transaction row (from ledger.tx_rows). Returns warnings for rows with no rate."""
    currency = currency.upper()
    ccy = {n.source_file: n.fund_currency.upper() for n in notices}
    warns, seen = [], set()
    for r in rows:
        frm = ccy.get(r["source_file"], "")
        found = rate_on(rates, r["notice_date"], frm, currency) if r["notice_date"] else None
        r["reporting_currency"] = currency
        if found is None:
            r.update(fx_rate=None, fx_rate_date=None, lp_amount_reporting=None, net_called_distributed_reporting=None)
            k = (r["source_file"], frm)
            if k not in seen:
                seen.add(k)
                when = f"on or before {r['notice_date']}" if r["notice_date"] else "(notice has no date)"
                warns.append({"file": r["source_file"], "field": "fx_rate",
                              "warning": f"no {frm}->{currency} rate {when}; reporting amount left blank"})
            continue
        rate, rd = found
        r.update(fx_rate=rate, fx_rate_date=rd, lp_amount_reporting=(r["lp_amount"] * rate).quantize(CENT),
                 net_called_distributed_reporting=(r["net_called_distributed"] * rate).quantize(CENT))
    return warns
