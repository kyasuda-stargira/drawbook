"""Shared scenario generator for the Drawbook test set.

A *scenario* is one fund seen by one LP: a sequence of notices whose balances tie from one notice to
the next. Each layout family renders the same kind of scenario in its own GP style.

Rules every family must follow:
- `make_fund(seed, ...)` gives the fund; `make_sequence(fund, ...)` gives a list of `Notice` answer keys
  with `pages` empty and `source_file` unset.
- The family's renderer prints every filled figure in the key on some page and records that page in
  `notice.pages[field]` (and `Transaction.page`). Figures may be formatted any way the family likes.
- `verify_pdf(pdf, key)` must pass for every document: the PDF opens, the key validates, and every
  figure appears (as a number, in any common format) on the page the key cites.
"""
from __future__ import annotations

import json
import random
import re
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from drawbook.schema import (  # noqa: E402
    BankDetails, InsideOutside, Notice, NoticeKind, Transaction, TransactionType as T, UnfundedImpact,
)

CENT = Decimal("0.01")


def q(x) -> Decimal:
    return Decimal(x).quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass
class Fund:
    fund_name: str
    gp_name: str
    currency: str
    fund_size: Decimal
    gp_commitment: Decimal
    lp_name: str
    lp_id: str
    lp_commitment: Decimal
    bank: BankDetails
    start: date

    @property
    def lp_pct(self) -> Decimal:
        return (self.lp_commitment / self.fund_size).quantize(Decimal("0.000001"))


GP_WORDS = ["Harbour", "Larch", "Meridian", "Kestrel", "Ashgrove", "Pellinor", "Corvid", "Tamsin", "Orrery",
            "Halcyon", "Wrenfield", "Basalt", "Stonechat", "Arden", "Quillon", "Vantor", "Marlow", "Elsworth"]
LP_NAMES = ["Northfield County Pension Scheme", "St Aldric College Endowment", "Brightwater Family Office",
            "Teesdale Local Government Pension Fund", "Ocarina Insurance plc", "Kildare Foundation",
            "Pinecrest Retirement System", "Hollins Charitable Trust", "Marchmont Mutual Assurance"]
BANKS = [("Private Equity Bank", "PEBKUS33"), ("Albion Commercial Bank plc", "ALBCGB2L"),
         ("Banque du Rhin SA", "BRHNLULL"), ("Nordic Merchant Bank AB", "NMBKSESS"),
         ("Harbourside Trust Company", "HTCOUS44")]


def make_fund(seed: int, currency: str = "USD") -> Fund:
    r = random.Random(seed)
    w = r.sample(GP_WORDS, 2)
    roman = r.choice(["II", "III", "IV", "V", "VI"])
    gp = f"{w[0]} {r.choice(['Capital', 'Partners', 'Equity', 'Investment Management'])}"
    form = r.choice(["L.P.", "SCSp", "LP", "Fund L.P."])
    fund_name = f"{w[0]} {w[1]} Fund {roman} {form}"
    size = Decimal(r.choice([350, 500, 750, 1000, 1500, 2000])) * Decimal(1_000_000)
    lp_commit = Decimal(r.choice([5, 10, 15, 20, 25, 40, 50])) * Decimal(1_000_000)
    bank_name, swift = r.choice(BANKS)
    if currency == "USD":
        acct = str(r.randrange(10**8, 10**9))
        sort = f"{r.randrange(10**8, 10**9)}"  # ABA routing
    elif currency == "GBP":
        acct = str(r.randrange(10**7, 10**8))
        sort = f"{r.randrange(10, 99)}-{r.randrange(10, 99)}-{r.randrange(10, 99)}"
    else:
        acct = f"LU{r.randrange(10, 99)} {r.randrange(1000, 9999)} {r.randrange(1000, 9999)} {r.randrange(1000, 9999)} {r.randrange(1000, 9999)}"
        sort = None
    bank = BankDetails(bank_name=bank_name, account_name=fund_name, account_number=acct, sort_code=sort,
                       swift_bic=swift, reference=None)
    return Fund(fund_name=fund_name, gp_name=gp, currency=currency, fund_size=size,
                gp_commitment=q(size * Decimal("0.02")), lp_name=r.choice(LP_NAMES),
                lp_id=f"LP-{r.randrange(100, 999)}", lp_commitment=lp_commit, bank=bank,
                start=date(r.choice([2018, 2019, 2020, 2021]), r.choice([1, 4, 7, 10]), 15))


# (type, inside/outside, impact on unfunded)
CALL_PARTS = [(T.CC_INVESTMENTS, "Inside", "Decrease"), (T.CC_MGMT_FEES, "Inside", "Decrease"),
              (T.CC_EXPENSES, "Inside", "Decrease"), (T.CC_SUB_FACILITY, "Inside", "Decrease"),
              (T.CC_WORKING_CAPITAL, "Inside", "Decrease"), (T.CC_SUBSEQ_INTEREST, "Outside", "No Impact"),
              (T.CC_PLACEMENT, "Outside", "No Impact")]
DIST_PARTS = [(T.D_ROC_CASH, "Inside", "No Impact"), (T.D_GAIN_CASH, "Inside", "No Impact"),
              (T.D_INCOME, "Inside", "No Impact"), (T.D_DIVIDENDS, "Inside", "No Impact"),
              (T.D_TAX_WITHHELD, "Inside", "No Impact")]
COMPANIES = ["ABC Widgets Inc.", "Brennan Logistics Ltd", "Calder Software GmbH", "Dunmore Foods SA",
             "Eskdale Health Group", "Fennick Robotics AB", "Glenrock Dental Partners", "Hartwell Packaging"]


def _amount(r, lo, hi) -> Decimal:
    return q(Decimal(r.randrange(lo, hi)) * Decimal(r.choice([1, 1, 1, 0.25, 0.5])) + Decimal(r.randrange(0, 100)) / 100)


def make_sequence(fund: Fund, seed: int, n: int = 3, kinds: list[NoticeKind] | None = None,
                  recallable_share: float = 0.0) -> list[Notice]:
    """n notices that tie: each notice's 'prior' balances equal the previous notice's 'including' balances.

    kinds: optional list of NoticeKind per notice (default: mostly calls, one distribution).
    recallable_share: share of each Return of Capital distribution marked recallable (adds back to unfunded).
    """
    r = random.Random(seed)
    if kinds is None:
        kinds = [NoticeKind.CAPITAL_CALL] * n
        if n >= 3:
            kinds[r.randrange(1, n)] = NoticeKind.DISTRIBUTION
    paid = q(fund.lp_commitment * Decimal(r.choice(["0.10", "0.25", "0.40"])))
    dist = q(paid * Decimal(r.choice(["0", "0.05", "0.20"])))
    unfunded = q(fund.lp_commitment - paid)
    recallable = Decimal("0.00")
    d = fund.start + timedelta(days=365 * r.randrange(1, 4))
    out = []
    for kind in kinds:
        d = d + timedelta(days=r.randrange(60, 120))
        due = d + timedelta(days=r.choice([10, 14, 15]))
        tx: list[Transaction] = []
        if kind in (NoticeKind.CAPITAL_CALL, NoticeKind.COMBINED):
            parts = [CALL_PARTS[0], CALL_PARTS[1]] + r.sample(CALL_PARTS[2:], r.randrange(0, 3))
            for t, io, imp in parts:
                amt = _amount(r, 200_000, 3_000_000) if t == T.CC_INVESTMENTS else _amount(r, 5_000, 120_000)
                desc = {T.CC_INVESTMENTS: f"Investment in {r.choice(COMPANIES)}",
                        T.CC_MGMT_FEES: f"Management fee, Q{r.randrange(1, 5)} {d.year}",
                        T.CC_EXPENSES: "Partnership expenses (legal, audit, administration)",
                        T.CC_SUB_FACILITY: "Interest on subscription credit facility",
                        T.CC_WORKING_CAPITAL: "Working capital reserve",
                        T.CC_SUBSEQ_INTEREST: "Subsequent close interest (outside commitment)",
                        T.CC_PLACEMENT: "Placement agent fees (outside commitment)"}[t]
                tx.append(Transaction(description=desc, transaction_type=t, lp_amount=amt,
                                      impact_on_unfunded=UnfundedImpact(imp), inside_outside=InsideOutside(io),
                                      recallable=None, page=1))
        if kind in (NoticeKind.DISTRIBUTION, NoticeKind.COMBINED):
            co = r.choice(COMPANIES)
            parts = [DIST_PARTS[0]] + r.sample(DIST_PARTS[1:4], r.randrange(1, 3))
            if r.random() < 0.3:
                parts.append(DIST_PARTS[4])
            for t, io, imp in parts:
                amt = _amount(r, 100_000, 2_000_000) if t != T.D_TAX_WITHHELD else _amount(r, 2_000, 40_000)
                rec = None
                if t == T.D_ROC_CASH:
                    rec = recallable_share > 0
                desc = {T.D_ROC_CASH: f"Return of capital, sale of {co}",
                        T.D_GAIN_CASH: f"Realised gain, sale of {co}",
                        T.D_INCOME: "Interest income from portfolio loans",
                        T.D_DIVIDENDS: f"Dividend from {r.choice(COMPANIES)}",
                        T.D_TAX_WITHHELD: "Withholding tax deducted"}[t]
                imp_v = UnfundedImpact.INCREASE if rec else UnfundedImpact(imp)
                tx.append(Transaction(description=desc, transaction_type=t, lp_amount=amt,
                                      impact_on_unfunded=imp_v, inside_outside=InsideOutside(io),
                                      recallable=rec, page=1))
        inside_calls = sum((t.lp_amount for t in tx if t.transaction_type.value.startswith("Capital Call")
                            and t.inside_outside == InsideOutside.INSIDE), Decimal(0))
        outside_calls = sum((t.lp_amount for t in tx if t.inside_outside == InsideOutside.OUTSIDE), Decimal(0))
        tax = sum((t.lp_amount for t in tx if t.transaction_type == T.D_TAX_WITHHELD), Decimal(0))
        dists = sum((t.lp_amount for t in tx if t.transaction_type.value.startswith("Distribution")
                     and t.transaction_type != T.D_TAX_WITHHELD), Decimal(0)) - tax
        rec_add = sum((q(t.lp_amount * Decimal(str(recallable_share))) for t in tx if t.recallable), Decimal(0))
        unf_impact = q(-inside_calls + rec_add)
        n_ = Notice(
            source_file="", kind=kind, notice_date=d, due_date=due, fund_name=fund.fund_name,
            gp_name=fund.gp_name, fund_currency=fund.currency, fund_size=fund.fund_size,
            gp_commitment=fund.gp_commitment,
            fund_contributions_current=q(inside_calls / fund.lp_pct) if inside_calls else None,
            fund_distributions_current=q(dists / fund.lp_pct) if dists else None,
            lp_id=fund.lp_id, lp_name=fund.lp_name, lp_commitment=fund.lp_commitment,
            lp_pct_of_fund=fund.lp_pct,
            lp_contributions_current=q(inside_calls) if inside_calls else None,
            lp_distributions_current=q(dists) if dists else None,
            lp_cum_contributions_prior=paid, lp_cum_distributions_prior=dist,
            lp_cum_contributions_incl=q(paid + inside_calls), lp_cum_distributions_incl=q(dist + dists),
            lp_unfunded_prior=unfunded, lp_unfunded_impact_current=unf_impact,
            lp_unfunded_incl=q(unfunded + unf_impact),
            lp_recallable_balance=q(recallable + rec_add) if (recallable or rec_add) else None,
            lp_outside_outflow_current=q(outside_calls) if outside_calls else None,
            lp_net_called_distributed=q(inside_calls + outside_calls - dists),
            transactions=tx, bank=fund.bank.model_copy(),
        )
        paid, dist, unfunded = n_.lp_cum_contributions_incl, n_.lp_cum_distributions_incl, n_.lp_unfunded_incl
        recallable = n_.lp_recallable_balance or Decimal("0.00")
        out.append(n_)
    return out


# ---------- number formats renderers may use ----------
def fmt(x: Decimal, style: str = "us", cur: str = "") -> str:
    """us: 1,234,567.89 | us0: 1,234,568 | eu: 1.234.567,89 | space: 1 234 567.89 | paren: (1,234,567.89) for negatives."""
    neg = x < 0
    x = abs(x)
    if style == "us0":
        s = f"{x.quantize(Decimal(1), rounding=ROUND_HALF_UP):,}"
    else:
        s = f"{x:,.2f}"
    if style == "eu":
        s = s.replace(",", "X").replace(".", ",").replace("X", ".")
    elif style == "space":
        s = s.replace(",", " ")
    s = f"{cur}{s}"
    if neg:
        s = f"({s})" if style in ("paren", "us", "us0") else f"-{s}"
    return s


_NUM = re.compile(r"\(?-?[\d][\d,.  ']*\d\)?|\(?-?\d\)?")


def numbers_in(text: str) -> set[Decimal]:
    """Every number on a page, read in US, EU, space-grouped and parenthesis styles (both signs kept)."""
    found: set[Decimal] = set()
    for m in _NUM.finditer(text):
        raw = m.group(0)
        neg = raw.startswith("(") and raw.endswith(")") or raw.startswith("-")
        core = raw.strip("()-").replace(" ", " ").replace("'", "")
        cands = []
        pieces = {core, core.replace(" ", "")} | set(core.split())
        for c in pieces:
            if re.fullmatch(r"\d{1,3}(,\d{3})*(\.\d+)?|\d+(\.\d+)?", c):
                cands.append(c.replace(",", ""))
            if re.fullmatch(r"\d{1,3}(\.\d{3})*(,\d+)?|\d+,\d+", c):
                cands.append(c.replace(".", "").replace(",", "."))
        for c in cands:
            try:
                v = Decimal(c)
            except Exception:
                continue
            found.add(v)
            found.add(-v if not neg else v)
            if neg:
                found.add(-v)
    return found


def page_texts(pdf: Path) -> list[str]:
    import pdfplumber
    with pdfplumber.open(pdf) as p:
        return [pg.extract_text() or "" for pg in p.pages]


def _matches(v: Decimal, nums: set[Decimal]) -> bool:
    if v in nums or -v in nums:
        return True
    # rounded presentations (whole units) and percentages
    if v.quantize(Decimal(1), rounding=ROUND_HALF_UP) in nums:
        return True
    if abs(v) < 1 and (v * 100).normalize() in {n.normalize() for n in nums}:
        return True
    if any(abs(n - v) < Decimal("0.0001") for n in nums):
        return True
    return abs(v) < 1 and any(abs(n - v * 100) < Decimal("0.01") for n in nums)


def _date_on(d: date, text: str) -> bool:
    t = " ".join(text.split()).lower()
    months = ["january", "february", "march", "april", "may", "june", "july", "august", "september",
              "october", "november", "december"]
    m = months[d.month - 1]
    suf = {1: "st", 2: "nd", 3: "rd", 21: "st", 22: "nd", 23: "rd", 31: "st"}.get(d.day, "th")
    forms = [d.isoformat(), f"{d.month:02d}/{d.day:02d}/{d.year}", f"{d.month}/{d.day}/{d.year}",
             f"{d.day:02d}.{d.month:02d}.{d.year}", f"{d.day:02d}/{d.month:02d}/{d.year}",
             f"{d.day} {m} {d.year}", f"{d.day}{suf} {m} {d.year}", f"{m} {d.day}, {d.year}",
             f"{m[:3]}. {d.day}, {d.year}", f"{m[:3]} {d.day}, {d.year}", f"{d.day} {m[:3]} {d.year}"]
    return any(x in t for x in forms)


def verify_pdf(pdf: Path, key: Notice) -> list[str]:
    """Return a list of problems (empty = pass)."""
    probs = []
    Notice.model_validate(key.model_dump())
    texts = page_texts(pdf)
    if not texts:
        return ["PDF has no pages"]
    data = key.model_dump()
    for f, v in data.items():
        if f in ("source_file", "transactions", "bank", "pages", "kind") or v is None:
            continue
        pg = key.pages.get(f)
        if pg is None:
            probs.append(f"{f}: no page recorded")
            continue
        if pg > len(texts):
            probs.append(f"{f}: page {pg} > {len(texts)}")
            continue
        if isinstance(v, Decimal):
            if not _matches(v, numbers_in(texts[pg - 1])):
                probs.append(f"{f}={v} not found on page {pg}")
        elif isinstance(v, date):
            if not _date_on(v, texts[pg - 1]):
                probs.append(f"{f}={v} not found on page {pg}")
        elif isinstance(v, str) and f not in ("fund_currency",):
            if " ".join(v.split()).lower() not in " ".join(texts[pg - 1].split()).lower():
                probs.append(f"{f}={v!r} not found on page {pg}")
    for i, t in enumerate(key.transactions):
        if t.page > len(texts) or not _matches(t.lp_amount, numbers_in(texts[t.page - 1])):
            probs.append(f"transactions[{i}].lp_amount={t.lp_amount} not on page {t.page}")
    return probs


def write_key(key: Notice, path: Path) -> None:
    path.write_text(json.dumps(json.loads(key.model_dump_json()), indent=2) + "\n")


def read_key(path: Path) -> Notice:
    return Notice.model_validate_json(path.read_text())
