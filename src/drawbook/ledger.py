"""Write lp-ledger.xlsx (Fund, Transactions, Balances, Warnings) and lp-ledger.csv (transactions)."""
from __future__ import annotations

import csv
from datetime import date
from decimal import Decimal
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font

from .schema import Notice

FUND_COLS = ["fund_name", "gp_name", "fund_currency", "fund_size", "gp_commitment", "lp_id", "lp_name",
             "lp_commitment", "lp_pct_of_fund"]
BAL_COLS = ["notice_date", "due_date", "kind", "lp_contributions_current", "lp_distributions_current",
            "lp_outside_outflow_current", "lp_outside_inflow_current", "lp_net_called_distributed",
            "lp_cum_contributions_prior", "lp_cum_contributions_incl", "lp_cum_distributions_prior",
            "lp_cum_distributions_incl", "lp_unfunded_prior", "lp_unfunded_impact_current", "lp_expired_released",
            "lp_other_unfunded_adjustment", "lp_unfunded_incl", "lp_recallable_balance",
            "fund_contributions_current", "fund_distributions_current"]
TX_COLS = ["fund_name", "lp_id", "notice_date", "due_date", "transaction_type", "description", "lp_amount",
           "impact_on_unfunded", "unfunded_impact_value", "net_called_distributed", "inside_outside", "recallable",
           "source_file", "page"]


def _v(x):
    if isinstance(x, Decimal):
        return float(x)
    if hasattr(x, "value"):
        return x.value
    return x


def tx_rows(notices: list[Notice]) -> list[dict]:
    rows = []
    for n in sorted(notices, key=lambda n: (n.fund_name, n.notice_date or date.min)):
        for t in n.transactions:
            sign_unf = {"Decrease": -1, "Increase": 1}.get(t.impact_on_unfunded.value, 0)
            is_dist = t.transaction_type.value.startswith(("Distribution", "Negative Contribution"))
            tax = t.transaction_type.value == "Distribution: Tax Withheld"
            rows.append({"fund_name": n.fund_name, "lp_id": n.lp_id, "notice_date": n.notice_date, "due_date": n.due_date,
                         "transaction_type": t.transaction_type.value, "description": t.description,
                         "lp_amount": t.lp_amount, "impact_on_unfunded": t.impact_on_unfunded.value,
                         "unfunded_impact_value": sign_unf * t.lp_amount,
                         "net_called_distributed": (t.lp_amount if tax else -t.lp_amount) if is_dist else t.lp_amount,
                         "inside_outside": t.inside_outside.value, "recallable": t.recallable,
                         "source_file": n.source_file, "page": t.page})
    return rows


def write(notices: list[Notice], warnings: list[dict], out_dir: Path) -> tuple[Path, Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    bold = Font(bold=True)

    def sheet(ws, header, rows):
        ws.append(header)
        for c in ws[1]:
            c.font = bold
        for r in rows:
            ws.append([_v(x) for x in r])
        ws.freeze_panes = "A2"

    funds, seen = [], set()
    for n in notices:
        k = (n.fund_name, n.lp_id)
        if k in seen:
            continue
        seen.add(k)
        latest = max((m for m in notices if (m.fund_name, m.lp_id) == k), key=lambda m: m.notice_date or date.min)
        funds.append([getattr(latest, c) for c in FUND_COLS] + [latest.source_file])
    ws = wb.active
    ws.title = "Fund"
    sheet(ws, FUND_COLS + ["from_file"], funds)

    trows = tx_rows(notices)
    sheet(wb.create_sheet("Transactions"), TX_COLS, [[r[c] for c in TX_COLS] for r in trows])

    brows = []
    for n in sorted(notices, key=lambda n: (n.fund_name, n.notice_date or date.min)):
        cells = [n.fund_name, n.lp_id] + [getattr(n, c) for c in BAL_COLS]
        cites = "; ".join(f"{c}: p{n.pages[c]}" for c in BAL_COLS if c in n.pages)
        brows.append(cells + [n.source_file, cites])
    sheet(wb.create_sheet("Balances"), ["fund_name", "lp_id"] + BAL_COLS + ["source_file", "pages"], brows)

    sheet(wb.create_sheet("Warnings"), ["file", "field", "warning"],
          [[w["file"], w["field"], w["warning"]] for w in warnings])

    xlsx = out_dir / "lp-ledger.xlsx"
    wb.save(xlsx)
    csv_path = out_dir / "lp-ledger.csv"
    with csv_path.open("w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=TX_COLS)
        wr.writeheader()
        for r in trows:
            wr.writerow({k: _v(v) for k, v in r.items()})
    return xlsx, csv_path
