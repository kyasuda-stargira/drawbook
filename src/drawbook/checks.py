"""Tie-out and bank-change checks across a fund's notices."""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import date
from decimal import Decimal

from .schema import InsideOutside, Notice

TOL = Decimal("1.00")  # allow rounding to whole units on printed notices


def _ne(a, b) -> bool:
    return a is not None and b is not None and abs(a - b) > TOL


def fund_key(n: Notice) -> tuple:
    return (" ".join(n.fund_name.lower().split()), (n.lp_id or n.lp_name or "").lower())


def _norm_bank(v: str | None) -> str:
    return re.sub(r"[^0-9a-z]", "", (v or "").lower())


def within(n: Notice) -> list[str]:
    out = []
    parts = [n.lp_unfunded_prior, n.lp_unfunded_impact_current, n.lp_expired_released, n.lp_other_unfunded_adjustment]
    if n.lp_unfunded_prior is not None and n.lp_unfunded_impact_current is not None and n.lp_unfunded_incl is not None:
        s = sum((p for p in parts if p is not None), Decimal(0))
        if _ne(s, n.lp_unfunded_incl):
            out.append(f"unfunded does not tie: {n.lp_unfunded_prior} + changes = {s}, notice says {n.lp_unfunded_incl}")
    for label, prior, cur, incl in [
        ("contributions", n.lp_cum_contributions_prior, n.lp_contributions_current, n.lp_cum_contributions_incl),
        ("distributions", n.lp_cum_distributions_prior, n.lp_distributions_current, n.lp_cum_distributions_incl)]:
        if prior is not None and incl is not None:
            if _ne(prior + (cur or 0), incl):
                out.append(f"cumulative {label} do not tie: {prior} + {cur or 0} != {incl}")
    if n.transactions and n.lp_contributions_current is not None:
        inside = sum((t.lp_amount for t in n.transactions if t.transaction_type.value.startswith("Capital Call")
                      and t.inside_outside == InsideOutside.INSIDE), Decimal(0))
        if _ne(inside, n.lp_contributions_current):
            out.append(f"line items ({inside}) do not add up to the amount called ({n.lp_contributions_current})")
    return out


def run(notices: list[Notice]) -> list[dict]:
    """Return warnings: [{file, field, warning}]."""
    warns = []
    for n in notices:
        for msg in within(n):
            warns.append({"file": n.source_file, "field": "balances", "warning": msg})
    groups: dict[tuple, list[Notice]] = defaultdict(list)
    for n in notices:
        groups[fund_key(n)].append(n)
    for seq in groups.values():
        seq.sort(key=lambda n: (n.notice_date or date.min, n.source_file))
        for a, b in zip(seq, seq[1:]):
            for label, x, y in [("unfunded commitment", a.lp_unfunded_incl, b.lp_unfunded_prior),
                                ("contributions to date", a.lp_cum_contributions_incl, b.lp_cum_contributions_prior),
                                ("distributions to date", a.lp_cum_distributions_incl, b.lp_cum_distributions_prior)]:
                if _ne(x, y):
                    warns.append({"file": b.source_file, "field": "balances",
                                  "warning": f"{label} before this notice ({y}) does not match {a.source_file} after it ({x})"})
            if a.bank and b.bank:
                for f in ("account_number", "sort_code", "swift_bic", "bank_name"):
                    va, vb = getattr(a.bank, f), getattr(b.bank, f)
                    if va and vb and _norm_bank(va) != _norm_bank(vb):
                        warns.append({"file": b.source_file, "field": f"bank.{f}",
                                      "warning": f"PAYMENT DETAILS CHANGED: {f} was {va!r} in {a.source_file}, "
                                                 f"now {vb!r}. Confirm with the GP by phone before paying."})
    return warns
