"""AI extraction into the fixed schema, then checks in code.

The model reads page-tagged text and returns JSON. Code then:
1. parses figures and dates, and maps transaction types onto the 27 ILPA types;
2. checks provenance: every figure must appear on the page the model cited (if it appears on another
   page, the page is corrected; if it appears nowhere, the figure is dropped and a warning raised);
3. fixes signs the template defines (call = unfunded goes down; distribution = net negative);
4. sets each transaction's unfunded impact from its type (template rules), and validates the Notice.
"""
from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .numbers import matches, numbers_in
from .pdftext import Page, read_pages
from .providers import Provider
from .schema import (BankDetails, InsideOutside, Notice, NoticeKind, Transaction, TransactionType,
                     UnfundedImpact)

FIELD_HELP = {
    "notice_date": "date of the notice / statement period end, as printed",
    "due_date": "date payment is due or distribution will be paid, as printed",
    "fund_name": "fund legal name exactly as printed",
    "gp_name": "general partner / manager / sponsor firm name as printed in letterhead or signature",
    "fund_currency": "3-letter currency code of the fund (USD, EUR, GBP...)",
    "fund_size": "total fund commitments / fund size",
    "gp_commitment": "GP commitment amount",
    "fund_contributions_current": "total amount called from ALL partners in this notice (fund level, inside commitment)",
    "fund_distributions_current": "total distributed to ALL partners in this notice (fund level, net)",
    "lp_id": "investor / LP ID number or code",
    "lp_name": "investor (LP) name the notice is addressed to",
    "lp_commitment": "this LP's commitment",
    "lp_pct_of_fund": "LP share of fund as printed (e.g. '1.0000%')",
    "lp_pct_of_unfunded": "LP share of total fund unfunded, if printed",
    "lp_contributions_current": "this LP's contribution called in this notice inside commitment",
    "lp_distributions_current": "this LP's net distribution in this notice",
    "lp_cum_contributions_prior": "LP contributions to date BEFORE this notice",
    "lp_cum_distributions_prior": "LP distributions to date BEFORE this notice",
    "lp_cum_contributions_incl": "LP contributions to date INCLUDING this notice",
    "lp_cum_distributions_incl": "LP distributions to date INCLUDING this notice",
    "lp_unfunded_prior": "LP unfunded / remaining / undrawn commitment BEFORE this notice",
    "lp_unfunded_impact_current": "change in LP unfunded commitment from this notice (negative when it goes down)",
    "lp_expired_released": "expired or released commitment",
    "lp_other_unfunded_adjustment": "other unfunded adjustment",
    "lp_unfunded_incl": "LP unfunded / remaining / undrawn commitment AFTER this notice",
    "lp_recallable_balance": "LP recallable capital balance (amount of distributions that may be recalled)",
    "lp_outside_outflow_current": "LP amount called OUTSIDE commitment this notice (e.g. subsequent close / equalisation interest, fees outside commitment)",
    "lp_outside_inflow_current": "LP amount received outside commitment this notice",
    "lp_net_called_distributed": "net amount the LP pays (positive) or receives (negative) for this notice",
}
DECIMAL_FIELDS = {k for k in FIELD_HELP if k not in ("notice_date", "due_date", "fund_name", "gp_name",
                                                       "fund_currency", "lp_id", "lp_name")}
DATE_FIELDS = {"notice_date", "due_date"}
PCT_FIELDS = {"lp_pct_of_fund", "lp_pct_of_unfunded"}

SYSTEM = ("You extract data from private fund capital call notices, distribution notices and capital account "
          "statements. Copy figures exactly as printed. Never calculate or guess a figure that is not printed. "
          "Answer with one JSON object only.")


BALANCE_FIELDS = [k for k in FIELD_HELP if k.startswith("lp_") and k not in ("lp_id", "lp_name", "lp_commitment",
                                                                           "lp_pct_of_fund", "lp_pct_of_unfunded")]
IDENTITY_FIELDS = [k for k in FIELD_HELP if k not in BALANCE_FIELDS]

TABLE_HELP = """How to read balance tables: a row such as "Contributions", "Distributions" or "Unfunded commitment" with
columns "prior / this notice / after" gives the *_prior, the current-notice and the *_incl fields for that row. The same
columns are also called "before / movement / after", "brought forward / this period / carried forward" or "opening /
period / closing". Unfunded commitment is also called undrawn, remaining or uncalled commitment. The "this
notice" column of the unfunded row is lp_unfunded_impact_current (negative when unfunded goes down). Fill every field the
document prints, including 0.00 values in a balances table. Use lp_recallable_balance only for a figure the document calls
recallable. lp_net_called_distributed is the single amount the LP pays or receives for the whole notice."""


RETRY_NOTE = """
Your last answer left out most of these fields. Go through the balances table row by row (contributions,
distributions, unfunded/undrawn commitment, recallable) and column by column (before, this notice, after), and give
every figure printed there, plus the net amount the LP pays or receives."""

# Standard wording on notices -> transaction type. Used only when the model's type contradicts the description.
KEYWORD_TYPES = [
    (r"management fee", TransactionType.CC_MGMT_FEES), (r"placement", TransactionType.CC_PLACEMENT),
    (r"subscription (credit )?(facility|line)|credit facility", TransactionType.CC_SUB_FACILITY),
    (r"subsequent clos|equali[sz]ation", TransactionType.CC_SUBSEQ_INTEREST),
    (r"partnership expense|fund expense|\bexpenses\b", TransactionType.CC_EXPENSES),
    (r"working capital", TransactionType.CC_WORKING_CAPITAL),
    (r"return of capital", TransactionType.D_ROC_CASH), (r"reali[sz]ed gain", TransactionType.D_GAIN_CASH),
    (r"dividend", TransactionType.D_DIVIDENDS), (r"interest income", TransactionType.D_INCOME),
    (r"withh?olding tax|tax withheld", TransactionType.D_TAX_WITHHELD), (r"carried interest|\bcarry\b", TransactionType.D_CARRY),
]


def type_from_words(desc: str, model_type: TransactionType) -> TransactionType:
    """Keep the model's type when the description supports it; otherwise use the first standard wording that matches."""
    d = desc.lower()
    hits = [t for pat, t in KEYWORD_TYPES if re.search(pat, d)]
    if not hits or model_type in hits:
        return model_type
    return hits[0]


def build_prompt(pages: list[Page], part: str = "identity") -> str:
    doc = "\n\n".join(f"=== PAGE {p.number} ===\n{p.text}" for p in pages)
    if part == "balances":
        fields = "\n".join(f'  "{k}": {FIELD_HELP[k]}' for k in BALANCE_FIELDS)
        return f"""Read the document below. Return JSON: {{"fields": {{"<field>": {{"value": "<exactly as printed>", "page": <n>}}, ...}}}}
These are THIS LP's figures (not the fund totals): when a table has a "Total Fund" column and an investor / "your share"
column, read the investor column. Leave a field out only if the document does not print it.
{fields}

{TABLE_HELP}

DOCUMENT:
{doc}
"""
    types = "\n".join(f"- {t.value}" for t in TransactionType)
    fields = "\n".join(f'  "{k}": {FIELD_HELP[k]}' for k in IDENTITY_FIELDS)
    return f"""Read the document below and return JSON with this shape:
{{
 "kind": "capital_call" | "distribution" | "combined" | "capital_account_statement",
 "fields": {{ "<field>": {{"value": "<exactly as printed>", "page": <page number>}} , ... }},
 "transactions": [ {{"description": "...", "type": "<one of the types below>", "amount": "<LP amount as printed, positive>",
                    "inside_outside": "Inside" | "Outside", "recallable": true | false | null, "page": <n>}} ],
 "bank": {{"bank_name": "", "account_name": "", "account_number": "", "sort_code": "<sort code or ABA routing>",
          "swift_bic": "", "reference": "", "page": <n>}} or null
}}

Fields (fill every one the document prints; leave a field out only if it is not printed):
{fields}
Copy dates exactly as printed. Copy names without labels in front ("Investor", "Bank", "To").
gp_name is the manager or general partner firm named in the letterhead, signature or footer, not the fund.
lp_commitment is this LP's own commitment ("Your commitment"), not the fund size. fund_size is the total commitments of
all partners. When a table shows a "Total Fund" column next to an "Investor" / "Your share" column, transactions and all
lp_* fields come from the investor column; fund_* fields come from the fund column.

Transactions are this LP's line items (investments, fees, expenses, return of capital, gains, income, tax withheld...),
not subtotal or total rows. "Outside" means outside commitment (does not reduce unfunded commitment).
A capital account statement has no transactions. Carry is only the GP's carried interest; a sale's proceeds are
return of capital and realised gain.
Transaction types:
{types}

DOCUMENT:
{doc}
"""


@dataclass
class Result:
    notice: Notice | None
    warnings: list[dict] = field(default_factory=list)
    raw: str = ""


def _json(text: str) -> dict:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    start = text.find("{")
    if start < 0:
        raise ValueError("model returned no JSON")
    return _salvage(text[start:])


def _salvage(t: str) -> dict:
    """The local model sometimes repeats lines until it runs out of length, so the JSON never closes.
    Cut back to the last complete line and close whatever is still open."""
    lines = t.splitlines()
    for end in range(len(lines), 0, -1):
        body = "\n".join(lines[:end]).rstrip().rstrip(",")
        stack = []
        in_str = esc = False
        for ch in body:
            if in_str:
                esc = (ch == "\\") and not esc
                if ch == '"' and not esc:
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch in "{[":
                stack.append("}" if ch == "{" else "]")
            elif ch in "}]" and stack:
                stack.pop()
        if in_str:
            continue
        try:
            return json.loads(body + "".join(reversed(stack)))
        except json.JSONDecodeError:
            continue
    raise ValueError("model returned no JSON")


def parse_decimal(v) -> Decimal | None:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return Decimal(str(v))
    s = str(v).strip()
    neg = (s.startswith("(") and s.endswith(")")) or "-" in s[:3]
    nums = [n for n in numbers_in(s) if n >= 0]
    if not nums:
        return None
    # prefer the reading that keeps the most digits (1.234.567,89 -> 1234567.89)
    best = max(nums, key=lambda n: (len(n.as_tuple().digits), n))
    return -best if neg else best


MONTHS = {m: i + 1 for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}


def parse_date(v, month_first: bool = False) -> date | None:
    """Read a date as printed. Numeric d/m vs m/d is settled by month_first (US funds) unless one part is > 12."""
    if not v:
        return None
    s = str(v).strip().lower()
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        pass
    m = re.search(r"(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]{3})[a-z]*\.?,?\s+(\d{4})", s)
    if m and m.group(2) in MONTHS:
        return date(int(m.group(3)), MONTHS[m.group(2)], int(m.group(1)))
    m = re.search(r"([a-z]{3})[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})", s)
    if m and m.group(1) in MONTHS:
        return date(int(m.group(3)), MONTHS[m.group(1)], int(m.group(2)))
    m = re.search(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})", s)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if a > 12:
            mo, d = b, a
        elif b > 12:
            mo, d = a, b
        else:
            mo, d = (a, b) if month_first and "." not in s else (b, a)
        try:
            return date(y, mo, d)
        except ValueError:
            return None
    return None


def map_type(s: str, description: str = "") -> TransactionType | None:
    """Match the model's type to one of the 27; short forms ("Income", "Management Fees") match the part after the colon."""
    vals = {t.value.lower(): t for t in TransactionType}
    got = difflib.get_close_matches(str(s).lower(), list(vals), n=1, cutoff=0.5)
    if got:
        return vals[got[0]]
    tails = {t.value.split(": ", 1)[1].lower(): t for t in TransactionType}
    got = difflib.get_close_matches(str(s).lower(), list(tails), n=1, cutoff=0.6)
    return tails[got[0]] if got else None


def impact_for(t: TransactionType, io: InsideOutside, recallable: bool | None) -> UnfundedImpact:
    """ILPA template convention: inside-commitment calls reduce unfunded; outside calls do not;
    recallable distributions and returns of excess capital add back to unfunded."""
    v = t.value
    if v.startswith("Capital Call"):
        return UnfundedImpact.DECREASE if io == InsideOutside.INSIDE else UnfundedImpact.NO_IMPACT
    if v.startswith("Negative Contribution"):
        return UnfundedImpact.INCREASE
    return UnfundedImpact.INCREASE if recallable else UnfundedImpact.NO_IMPACT


def _share_beside(amt: Decimal, pct: Decimal | None, pages: list[Page]) -> Decimal | None:
    """If the line printing amt also prints amt x the LP's share of the fund (within 1%), amt is the fund total."""
    if not pct or pct >= 1:
        return None
    target = amt * pct
    for p in pages:
        for line in p.text.splitlines():
            nums = [n for n in numbers_in(line) if n > 0]
            if amt in nums:
                for n in nums:
                    if n != amt and target and abs(n - target) <= abs(target) * Decimal("0.01"):
                        return n
    return None


def _lp_figure_beside(fund_amt: Decimal, commitment: Decimal, pages: list[Page]) -> Decimal | None:
    """On the text line that prints a fund-level amount, the last figure no larger than the LP's commitment."""
    for p in pages:
        for line in p.text.splitlines():
            nums = [n for n in numbers_in(line) if n > 0]
            if fund_amt in nums:
                after = line[line.find(f"{fund_amt:,.2f}".split(".")[0]):]
                cands = [n for n in (x for x in numbers_in(after) if x > 0) if n <= commitment and n != fund_amt and n >= 1]
                if cands:
                    return max(cands)  # the investor's share is the largest figure that fits the commitment
    return None


def _locate(value: Decimal, cited: int | None, pages: list[Page]) -> int | None:
    order = ([cited] if cited else []) + [p.number for p in pages if p.number != cited]
    for n in order:
        if 1 <= n <= len(pages) and matches(value, numbers_in(pages[n - 1].text)):
            return n
    return None


def _text_on(value: str, cited: int | None, pages: list[Page]) -> int | None:
    norm = lambda s: " ".join(s.split()).lower()
    order = ([cited] if cited else []) + [p.number for p in pages if p.number != cited]
    for n in order:
        if 1 <= n <= len(pages) and norm(value) in norm(pages[n - 1].text):
            return n
    return None


# a 0.00 in a "this notice" or adjustment column records no movement; the template leaves those cells empty
ZERO_MEANS_NONE = ["lp_contributions_current", "lp_distributions_current", "lp_outside_outflow_current",
                   "lp_outside_inflow_current", "lp_expired_released", "lp_other_unfunded_adjustment",
                   "fund_contributions_current", "fund_distributions_current", "lp_pct_of_unfunded"]
PLACEHOLDER = re.compile(r"(?i)(not (printed|stated|shown|given|available)|n/?a|none|unknown|-+|—|\[.*\]|to|from|re|date|dear)")
# the template records these as positive amounts; the sign lives in the column, not the number
POSITIVE_FIELDS = ["fund_size", "gp_commitment", "fund_contributions_current", "fund_distributions_current",
                   "lp_commitment", "lp_contributions_current", "lp_distributions_current", "lp_cum_contributions_prior",
                   "lp_cum_distributions_prior", "lp_cum_contributions_incl", "lp_cum_distributions_incl",
                   "lp_unfunded_prior", "lp_unfunded_incl", "lp_recallable_balance", "lp_outside_outflow_current",
                   "lp_outside_inflow_current"]
BIC = re.compile(r"[A-Z]{6}[A-Z0-9]{2}([A-Z0-9]{3})?")
TOTAL_TYPES = {TransactionType.CC_TOTAL_INSIDE, TransactionType.CC_TOTAL_OUTSIDE}


def _drop_subtotals(txs: list[Transaction]) -> list[Transaction]:
    """Drop repeated lines, and any line that equals the sum of two or more other lines
    (a subtotal or 'net to you' row the model read as a transaction)."""
    seen, uniq = set(), []
    for t in txs:
        k = (t.transaction_type, t.lp_amount)
        if k not in seen:
            seen.add(k)
            uniq.append(t)
    keep = []
    for t in uniq:
        others = [o for o in uniq if o is not t]
        call = t.transaction_type.value.startswith("Capital Call")
        peers = [o for o in others if o.transaction_type.value.startswith("Capital Call") == call]
        if len(peers) >= 2 and any(abs(sum(o.lp_amount for o in grp) - t.lp_amount) <= Decimal("1")
                                   for grp in _groups(peers, t)):
            continue
        if t.transaction_type in TOTAL_TYPES and any(abs(o.lp_amount - t.lp_amount) <= Decimal("0.01") for o in peers):
            continue
        keep.append(t)
    return keep


def _groups(peers: list[Transaction], t: Transaction):
    """Candidate sets a subtotal row might add up: all peers, and all peers on the same side of commitment."""
    yield peers
    side = [o for o in peers if o.inside_outside == t.inside_outside]
    if len(side) >= 2:
        yield side
    small = [o for o in peers if o.lp_amount < t.lp_amount]
    if len(small) >= 2:
        yield small


LABELS = ["limited partner", "investor name", "investor", "partner", "lp name", "bank name", "bank", "to", "dear",
          "account name", "fund name", "fund", "general partner", "manager", "re"]


def strip_label(s: str) -> str:
    low = s.lower()
    for lab in LABELS:
        if low.startswith(lab + " ") or low.startswith(lab + ": ") or low.startswith(lab + ":"):
            rest = s[len(lab):].lstrip(" :")
            if rest and lab not in ("fund",):
                return rest
    return s


def _clean_text(v: str | None, pages: list[Page], cited: int | None) -> str | None:
    """Keep a printed string; if the model added a label word in front, drop words until it is on a page."""
    if not v:
        return None
    s = strip_label(" ".join(str(v).split()))
    words = s.split()
    for i in range(len(words)):
        cand = " ".join(words[i:])
        if _text_on(cand, cited, pages) or _text_on(cand.replace(" ", ""), cited, pages):
            return cand
    return s


def extract(pdf: Path, provider: Provider, pages: list[Page] | None = None) -> Result:
    pdf = Path(pdf)
    pages = pages or read_pages(pdf)
    warns: list[dict] = []
    w = lambda fld, msg: warns.append({"file": pdf.name, "field": fld, "warning": msg})
    raw, data = "", None
    for attempt in range(2):  # an answer with no readable JSON is asked once more
        out = provider.complete(SYSTEM, build_prompt(pages, "identity"), doc=pdf.name)
        raw += out
        try:
            data = _json(out)
            break
        except Exception as e:  # noqa: BLE001
            err = e
    if data is None:
        w("*", f"could not read model output: {err}")
        return Result(None, warns, raw)
    bal, raw2 = {}, ""
    for attempt in range(2):  # a near-empty answer is asked once more
        prompt = build_prompt(pages, "balances") + (RETRY_NOTE if attempt else "")
        out = provider.complete(SYSTEM, prompt, doc=pdf.name)
        raw2 += "\n\n" + out
        try:
            got = _json(out).get("fields") or {}
        except Exception as e:  # noqa: BLE001
            w("*", f"could not read balances output: {e}")
            got = {}
        if len([k for k in got if k in BALANCE_FIELDS]) > len([k for k in bal if k in BALANCE_FIELDS]):
            bal = got
        if len([k for k in bal if k in BALANCE_FIELDS]) >= 4:
            break
    raw = raw + raw2
    data.setdefault("fields", {})
    for k in BALANCE_FIELDS:
        data["fields"].pop(k, None)
        if k in bal:
            data["fields"][k] = bal[k]

    vals: dict = {}
    pg: dict[str, int] = {}
    cur_cell = (data.get("fields") or {}).get("fund_currency")
    cur = str(cur_cell.get("value") if isinstance(cur_cell, dict) else cur_cell or "").upper()
    month_first = cur.startswith("USD") or "$" in cur
    for k, cell in (data.get("fields") or {}).items():
        if k not in FIELD_HELP:
            continue
        if isinstance(cell, dict):
            v, cited = cell.get("value"), cell.get("page")
        else:  # model gave the bare value; the page is found below
            v, cited = cell, None
        cited = int(cited) if str(cited).isdigit() else None
        if v in (None, "", "null") or PLACEHOLDER.fullmatch(str(v).strip()):
            continue
        if k in DATE_FIELDS:
            d = parse_date(v, month_first)
            if d:
                vals[k], pg[k] = d, cited or 1
            else:
                w(k, f"unreadable date {v!r}")
        elif k in DECIMAL_FIELDS:
            dv = parse_decimal(v)
            if dv is None:
                w(k, f"unreadable figure {v!r}")
                continue
            if k in PCT_FIELDS and (("%" in str(v)) or dv > 1):
                where = _locate(dv, cited, pages)
                dv = dv / 100
            else:
                where = _locate(dv, cited, pages)
            if where is None:
                w(k, f"figure {v!r} not found on any page; dropped")
                continue
            if k == "lp_recallable_balance" and "recall" not in " ".join(p.text.lower() for p in pages):
                w(k, "figure labelled recallable but the document never says recallable; dropped")
                continue
            if cited and where != cited:
                w(k, f"page corrected from {cited} to {where}")
            vals[k], pg[k] = dv, where
        else:
            s = " ".join(str(v).split())
            if k == "fund_currency":
                s = s.upper()[:3]
                vals[k], pg[k] = s, cited or 1
                continue
            s = strip_label(s)
            where = _text_on(s, cited, pages)
            if where is None:
                w(k, f"text {s!r} not found on any page; kept for review")
                where = cited or 1
            vals[k], pg[k] = s, where

    for k in ZERO_MEANS_NONE:
        if k in vals and vals[k] == 0:
            vals.pop(k)
            pg.pop(k, None)
    for k in POSITIVE_FIELDS:
        if k in vals and vals[k] < 0:
            vals[k] = -vals[k]
    if "fund_size" in vals and "lp_commitment" in vals and vals["fund_size"] <= vals["lp_commitment"]:
        w("fund_size", f"fund size {vals['fund_size']} is not larger than the LP's commitment; dropped")
        vals.pop("fund_size"); pg.pop("fund_size", None)
    if "lp_pct_of_unfunded" in vals and not any(
            re.search(r"unfunded[^\n|]{0,60}%|%[^\n|]{0,40}unfunded", p.text, re.I) for p in pages):
        w("lp_pct_of_unfunded", "no share of unfunded printed; dropped")
        vals.pop("lp_pct_of_unfunded"); pg.pop("lp_pct_of_unfunded", None)

    kind = data.get("kind") or "capital_call"
    try:
        kind = NoticeKind(kind)
    except ValueError:
        w("kind", f"unknown kind {kind!r}; assumed capital_call")
        kind = NoticeKind.CAPITAL_CALL

    # sign rules the template defines
    p, i, imp = vals.get("lp_unfunded_prior"), vals.get("lp_unfunded_incl"), vals.get("lp_unfunded_impact_current")
    if p is not None and i is not None and imp is not None and abs(imp) == abs(i - p):
        vals["lp_unfunded_impact_current"] = i - p
    net = vals.get("lp_net_called_distributed")
    if net is not None:
        if kind == NoticeKind.DISTRIBUTION and net > 0:
            vals["lp_net_called_distributed"] = -net
        elif kind == NoticeKind.CAPITAL_CALL and net < 0:
            vals["lp_net_called_distributed"] = -net

    txs = []
    for t in data.get("transactions") or []:
        tt = map_type(t.get("type", ""))
        amt = parse_decimal(t.get("amount"))
        if tt is not None:
            tt = type_from_words(str(t.get("description") or ""), tt)
        if tt is None or amt is None:
            w("transactions", f"skipped unreadable line {t!r}")
            continue
        amt = abs(amt)
        cited = t.get("page")
        cited = int(cited) if str(cited).isdigit() else None
        where = _locate(amt, cited, pages)
        if where is None:
            w("transactions", f"amount {t.get('amount')!r} not found on any page; dropped")
            continue
        share = _share_beside(amt, vals.get("lp_pct_of_fund"), pages)
        if share is not None:
            w("transactions", f"line {amt} is the fund total; used the investor share {share} printed beside it")
            amt, cited = share, None
        elif tt.value.startswith("Capital Call") and vals.get("lp_commitment") and amt > vals["lp_commitment"]:
            lp_amt = _lp_figure_beside(amt, vals["lp_commitment"], pages)
            if lp_amt is None:
                w("transactions", f"line {amt} is larger than the LP's commitment, so it is a fund-level figure; dropped")
                continue
            w("transactions", f"line {amt} is a fund-level figure; used the investor figure {lp_amt} printed beside it")
            amt, cited = lp_amt, None
        io = InsideOutside.OUTSIDE if str(t.get("inside_outside", "")).lower().startswith("out") else InsideOutside.INSIDE
        rec = t.get("recallable")
        rec = rec if isinstance(rec, bool) else None
        txs.append(Transaction(description=str(t.get("description") or tt.value)[:200], transaction_type=tt,
                               lp_amount=amt, impact_on_unfunded=impact_for(tt, io, rec), inside_outside=io,
                               recallable=rec, page=where))

    txs = _drop_subtotals(txs)

    bank = None
    b = data.get("bank")
    if isinstance(b, dict) and any(b.get(k) for k in ("account_number", "sort_code", "swift_bic", "bank_name")):
        bp = b.get("page")
        bp_ = int(bp) if str(bp).isdigit() else None
        bank = BankDetails(**{k: _clean_text(b.get(k), pages, bp_)
                              for k in ("bank_name", "account_name", "account_number", "sort_code", "swift_bic", "reference")},
                           page=int(bp) if str(bp).isdigit() else None)

    if bank and bank.sort_code and BIC.fullmatch(bank.sort_code.replace(" ", "")) and not bank.swift_bic:
        bank.swift_bic, bank.sort_code = bank.sort_code.replace(" ", ""), None
    if bank and vals.get("gp_name") and bank.bank_name and vals["gp_name"].lower() == bank.bank_name.lower():
        w("gp_name", "GP name was the bank's name; dropped")
        vals.pop("gp_name"); pg.pop("gp_name", None)
    if "fund_name" not in vals:
        w("fund_name", "no fund name found")
        vals["fund_name"] = "(unknown fund)"
    if "fund_currency" not in vals:
        w("fund_currency", "no currency found; assumed USD")
        vals["fund_currency"] = "USD"
    notice = Notice(source_file=pdf.name, kind=kind, transactions=txs, bank=bank, pages=pg, **vals)
    if any(pp.ocr for pp in pages):
        w("*", "read with OCR: check figures against the page")
    return Result(notice, warns, raw)
