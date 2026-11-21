"""Read a filled ILPA Capital Call & Distribution Template (v2.0) workbook directly, without AI.

Cells are found by their labels, so a GP that inserts rows still reads correctly. Values the template
computes with formulas are recomputed here, because a workbook saved by a script has no cached results.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import openpyxl

from .extract import impact_for
from .schema import InsideOutside, Notice, NoticeKind, Transaction, TransactionType

SHEET = "Call & Distribution Template"


def _n(s) -> str:
    return " ".join(str(s).split()).lower() if s is not None else ""


def _dec(v) -> Decimal | None:
    if v is None or v == "" or (isinstance(v, str) and (v.startswith("=") or v.strip() in ("---",))):
        return None
    try:
        return Decimal(str(v).replace(",", ""))
    except Exception:  # noqa: BLE001
        return None


def _date(v) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10]) if v else None
    except ValueError:
        return None


def is_ilpa_template(path: Path) -> bool:
    try:
        return SHEET in openpyxl.load_workbook(path, read_only=True).sheetnames
    except Exception:  # noqa: BLE001
        return False


def read(path: Path) -> Notice:
    path = Path(path)
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb[SHEET]
    labels: dict[str, tuple[int, int]] = {}
    for row in ws.iter_rows():
        for c in row:
            if isinstance(c.value, str) and _n(c.value) not in labels:
                labels[_n(c.value)] = (c.row, c.column)

    def right(label: str, offset: int = 1):
        pos = labels.get(_n(label))
        return ws.cell(pos[0], pos[1] + offset).value if pos else None

    def grid(row_label: str, col: int):  # F=0, G=1 next to a row label in column E
        pos = labels.get(_n(row_label))
        return ws.cell(pos[0], pos[1] + 1 + col).value if pos else None

    hdr = labels.get(_n("Transaction Description"))
    txs = []
    if hdr:
        r = hdr[0] + 1
        cols = {_n(ws.cell(hdr[0], c).value).split(" (")[0]: c for c in range(1, ws.max_column + 1) if ws.cell(hdr[0], c).value}
        while r <= ws.max_row and not _n(ws.cell(r, 2).value).startswith("supplemental"):
            ttype = ws.cell(r, cols.get("transaction type", 5)).value
            amt = _dec(ws.cell(r, cols.get("lp amount", 8)).value)
            if ttype and amt is not None:
                tt = TransactionType(" ".join(str(ttype).split()))
                io = InsideOutside(str(ws.cell(r, cols.get("inside / outside fund", 12)).value or "Inside").strip())
                imp = ws.cell(r, cols.get("impact on unfunded commitment", 9)).value
                t = Transaction(description=str(ws.cell(r, 2).value or tt.value), transaction_type=tt, lp_amount=abs(amt),
                                impact_on_unfunded=impact_for(tt, io, None), inside_outside=io, page=1)
                if imp:
                    t.impact_on_unfunded = type(t.impact_on_unfunded)(str(imp).strip())
                txs.append(t)
            r += 1

    inside_calls = sum((t.lp_amount for t in txs if t.transaction_type.value.startswith("Capital Call")
                        and t.inside_outside == InsideOutside.INSIDE), Decimal(0))
    outside_calls = sum((t.lp_amount for t in txs if t.inside_outside == InsideOutside.OUTSIDE
                         and t.transaction_type.value.startswith("Capital Call")), Decimal(0))
    outside_in = sum((t.lp_amount for t in txs if t.inside_outside == InsideOutside.OUTSIDE
                      and not t.transaction_type.value.startswith("Capital Call")), Decimal(0))
    tax = sum((t.lp_amount for t in txs if t.transaction_type == TransactionType.D_TAX_WITHHELD), Decimal(0))
    dists = sum((t.lp_amount for t in txs if t.transaction_type.value.startswith(("Distribution", "Negative Contribution"))
                 and t.transaction_type != TransactionType.D_TAX_WITHHELD
                 and t.inside_outside == InsideOutside.INSIDE), Decimal(0)) - tax
    impact = sum(({"Decrease": -1, "Increase": 1}.get(t.impact_on_unfunded.value, 0) * t.lp_amount for t in txs), Decimal(0))

    size, lp_commit = _dec(right("Fund Size")), _dec(right("LP Commitment"))
    unf_prior = _dec(right("LP Unfunded Balance (Prior to Current Notice)"))
    expired = _dec(right("Expired/Released Commitments (Input negative value)"))
    other = _dec(right("Other Unfunded Adjustment"))
    cum_c_prior = _dec(grid("Cumulative LP Amount (Prior to Current Notice)", 0))
    cum_d_prior = _dec(grid("Cumulative LP Amount (Prior to Current Notice)", 1))
    has_call, has_dist = inside_calls > 0 or outside_calls > 0, dists != 0
    kind = NoticeKind.COMBINED if has_call and has_dist else NoticeKind.DISTRIBUTION if has_dist else NoticeKind.CAPITAL_CALL
    fund_c, fund_d = _dec(grid("Fund Amount (Current Notice)", 0)), _dec(grid("Fund Amount (Current Notice)", 1))
    return Notice(
        source_file=path.name, kind=kind, notice_date=_date(right("Notice Date")), due_date=_date(right("Due Date")),
        fund_name=str(right("Fund Name") or "(unknown fund)"), fund_currency=str(right("Fund Currency") or "USD")[:3],
        fund_size=size, gp_commitment=_dec(right("GP Commitment Amount")),
        fund_contributions_current=fund_c or None, fund_distributions_current=abs(fund_d) if fund_d else None,
        lp_id=str(right("LP / ID Number")) if right("LP / ID Number") else None, lp_commitment=lp_commit,
        lp_pct_of_fund=(lp_commit / size).quantize(Decimal("0.000001")) if size and lp_commit else None,
        lp_pct_of_unfunded=_dec(right("LP % of Unfunded (% of Total Fund Unfunded) - Optional")),
        lp_contributions_current=inside_calls or None, lp_distributions_current=dists or None,
        lp_cum_contributions_prior=cum_c_prior, lp_cum_distributions_prior=cum_d_prior,
        lp_cum_contributions_incl=cum_c_prior + inside_calls if cum_c_prior is not None else None,
        lp_cum_distributions_incl=cum_d_prior + dists if cum_d_prior is not None else None,
        lp_unfunded_prior=unf_prior, lp_unfunded_impact_current=impact, lp_expired_released=expired,
        lp_other_unfunded_adjustment=other,
        lp_unfunded_incl=unf_prior + impact + (expired or 0) + (other or 0) if unf_prior is not None else None,
        lp_outside_outflow_current=outside_calls or None, lp_outside_inflow_current=outside_in or None,
        lp_net_called_distributed=inside_calls + outside_calls - dists - outside_in,
        transactions=txs, pages={},
    )
