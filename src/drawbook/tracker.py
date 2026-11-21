"""Missing and late documents, per fund and LP, for the ledger's Documents sheet.

Expected quarterly documents: capital account statements for every fund that has sent one, or the kinds
listed for a fund in an optional expected.toml:

    due_days = 60                      # default lag after quarter end

    [funds."Example Fund III LP"]
    kinds = ["capital_account_statement"]
    due_days = 45

A statement's period is the latest quarter end on or before its date (a 15 May statement covers Q1).
Statuses: received; late (dated after the due date); missing (due date passed, nothing received).
A capital call whose due date has passed with no later document from that fund is also flagged late.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from .checks import fund_key
from .schema import Notice, NoticeKind

DEFAULT_DUE_DAYS = 60
DOC_COLS = ["fund", "lp", "period", "expected_kind", "status", "due", "file"]


def load_expected(path: Path) -> dict:
    try:
        import tomllib
    except ModuleNotFoundError:  # Python 3.10
        import tomli as tomllib
    return tomllib.loads(Path(path).read_text())


def _quarter_end(y: int, q: int) -> date:
    return date(y, 3 * q, 31 if q in (1, 4) else 30)


def period_of(d: date) -> date:
    """Latest quarter end on or before d."""
    for q in (4, 3, 2, 1):
        if _quarter_end(d.year, q) <= d:
            return _quarter_end(d.year, q)
    return _quarter_end(d.year - 1, 4)


def _next_quarter(qe: date) -> date:
    return period_of(qe + timedelta(days=95))


def _label(qe: date) -> str:
    return f"{qe.year}-Q{qe.month // 3}"


def documents(notices: list[Notice], expected: dict | None = None, today: date | None = None) -> list[dict]:
    today = today or date.today()
    expected = expected or {}
    default_days = expected.get("due_days", DEFAULT_DUE_DAYS)
    by_name = {" ".join(k.lower().split()): v for k, v in expected.get("funds", {}).items()}
    groups: dict[tuple, list[Notice]] = defaultdict(list)
    for n in notices:
        groups[fund_key(n)].append(n)
    rows = []
    for fk, seq in groups.items():
        dated = sorted((n for n in seq if n.notice_date), key=lambda n: n.notice_date)
        if not dated:
            continue
        fund, lp = dated[-1].fund_name, dated[-1].lp_id or dated[-1].lp_name
        cfg = by_name.get(fk[0], {})
        lag = timedelta(days=cfg.get("due_days", default_days))
        kinds = cfg.get("kinds") or ([NoticeKind.CAPITAL_ACCOUNT_STATEMENT.value]
                                     if any(n.kind == NoticeKind.CAPITAL_ACCOUNT_STATEMENT for n in dated) else [])
        for kind in kinds:
            got: dict[date, list[Notice]] = defaultdict(list)
            for n in dated:
                if n.kind.value == kind:
                    got[period_of(n.notice_date)].append(n)
            qe = min(got) if got else period_of(dated[0].notice_date)
            last = max([*got, qe])
            while qe <= last or qe + lag < today:
                due = qe + lag
                if got.get(qe):
                    for n in got[qe]:
                        rows.append({"fund": fund, "lp": lp, "period": _label(qe), "expected_kind": kind,
                                     "status": "late" if n.notice_date > due else "received", "due": due,
                                     "file": n.source_file})
                else:
                    rows.append({"fund": fund, "lp": lp, "period": _label(qe), "expected_kind": kind,
                                 "status": "missing", "due": due, "file": None})
                qe = _next_quarter(qe)
        for n in dated:
            if n.kind in (NoticeKind.CAPITAL_CALL, NoticeKind.COMBINED) and n.due_date and n.due_date < today \
                    and not any(m.notice_date > n.due_date for m in dated):
                rows.append({"fund": fund, "lp": lp, "period": n.due_date.isoformat(),
                             "expected_kind": "document after capital call", "status": "late", "due": n.due_date,
                             "file": n.source_file})
    return rows
