"""Layout family A: table-style capital call / distribution notices in three GP house styles.

Style 1 (fund 1, USD): navy letterhead bar, Helvetica, horizontal rules only, "14 January 2025",
    "$" on every amount, prior / this notice / after columns. One page.
Style 2 (fund 2, USD): letter style in Times, full grid, "01/14/2025", USD code in column headers,
    amount-first transaction rows, whole-dollar fund totals; balances on page 2 ("Schedule A").
Style 3 (fund 3, GBP): administrator statement in Courier, shaded headers, ISO dates,
    "£" amounts with brackets for negatives, "Undrawn" wording. One page.

Run: .venv/bin/python testset/gen/family_a.py  -> testset/build/family_a/<name>.pdf + .json
"""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, NoticeKind, fmt, make_fund, make_sequence, verify_pdf, write_key  # noqa: E402
from common import T  # noqa: E402

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4, LETTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

OUT = ROOT / "testset" / "build" / "family_a"
ZERO = Decimal("0.00")
SKIP = ("source_file", "kind", "transactions", "bank", "pages")


def z(v):
    return v if v is not None else ZERO


def pct(v: Decimal) -> str:
    return f"{v * 100:.4f}%"


def is_dist(n) -> bool:
    return n.kind == NoticeKind.DISTRIBUTION


def gross_dist(n) -> Decimal:
    return sum((t.lp_amount for t in n.transactions if t.transaction_type.value.startswith("Distribution")
                and t.transaction_type != T.D_TAX_WITHHELD), ZERO)


def is_tax(t) -> bool:
    return t.transaction_type == T.D_TAX_WITHHELD


def is_outside(t) -> bool:
    return t.inside_outside.value == "Outside"


def ps(name, font, size, **kw):
    return ParagraphStyle(name, fontName=font, fontSize=size, leading=size * 1.25, **kw)


def bank_rows(n, routing_label):
    b = n.bank
    rows = [("Bank", b.bank_name), ("Account name", b.account_name), ("Account number", b.account_number)]
    if b.sort_code:
        rows.append((routing_label, b.sort_code))
    if b.swift_bic:
        rows.append(("SWIFT / BIC", b.swift_bic))
    return rows


# ---------------------------------------------------------------- style 1
def style1(n, path: Path) -> dict[str, int]:
    navy = colors.HexColor("#1F3A5F")
    cur = "$"
    m = lambda v: fmt(v, "us", cur)  # noqa: E731
    d = lambda x: f"{x.day} {x:%B %Y}"  # noqa: E731
    title = "DISTRIBUTION NOTICE" if is_dist(n) else "CAPITAL CALL NOTICE"
    body = ps("b1", "Helvetica", 8.5)
    small = ps("s1", "Helvetica", 7.5, textColor=colors.HexColor("#444444"))
    h = ps("h1", "Helvetica-Bold", 9.5, textColor=navy, spaceBefore=6, spaceAfter=3)

    def letterhead(c, doc):
        w, ht = LETTER
        c.setFillColor(navy)
        c.rect(0, ht - 22 * mm, w, 22 * mm, fill=1, stroke=0)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 16)
        c.drawString(18 * mm, ht - 13 * mm, n.gp_name)
        c.setFont("Helvetica", 8)
        c.drawString(18 * mm, ht - 18 * mm, f"General Partner of {n.fund_name}")
        c.setFont("Helvetica-Bold", 11)
        c.drawRightString(w - 18 * mm, ht - 13 * mm, title)
        c.setFillColor(colors.HexColor("#666666"))
        c.setFont("Helvetica", 7)
        c.drawString(18 * mm, 10 * mm, f"{n.gp_name} | Confidential - prepared for the named Limited Partner only")

    rule = TableStyle([("FONT", (0, 0), (-1, -1), "Helvetica", 8.5), ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8.5),
                       ("LINEBELOW", (0, 0), (-1, 0), 0.8, navy), ("LINEBELOW", (0, -1), (-1, -1), 0.8, navy),
                       ("ALIGN", (1, 0), (-1, -1), "RIGHT"), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                       ("TOPPADDING", (0, 0), (-1, -1), 2)])
    s = []
    head = Table([["To:", f"{n.lp_name}", "Notice date:", d(n.notice_date)],
                  ["Investor ID:", n.lp_id, "Payment date:" if is_dist(n) else "Due date:", d(n.due_date)],
                  ["Fund:", n.fund_name, "Currency:", n.fund_currency]],
                 colWidths=[22 * mm, 85 * mm, 28 * mm, 40 * mm])
    head.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), "Helvetica", 8.5),
                              ("FONT", (0, 0), (0, -1), "Helvetica-Bold", 8.5),
                              ("FONT", (2, 0), (2, -1), "Helvetica-Bold", 8.5)]))
    s += [Spacer(1, 8 * mm), head, Spacer(1, 3 * mm)]
    if is_dist(n):
        s.append(Paragraph(f"{n.fund_name} (the \"Fund\") is making a distribution to its partners, mainly from the "
                           f"proceeds of a portfolio realisation. Your share is set out below and will be paid by wire "
                           f"on the payment date. All amounts are in {n.fund_currency}.", body))
    else:
        s.append(Paragraph(f"In accordance with the Limited Partnership Agreement, {n.gp_name} hereby calls capital "
                           f"from the partners of {n.fund_name}. Please remit your share by wire so that it is "
                           f"received by the due date. All amounts are in {n.fund_currency}.", body))
    s.append(Paragraph("Transactions in this notice", h))
    rows = [["Description", "Amount"]]
    for t in n.transactions:
        rows.append([t.description, m(-t.lp_amount) if is_tax(t) else m(t.lp_amount)])
    if is_dist(n):
        rows.append(["Net distribution to you", m(n.lp_distributions_current)])
    else:
        rows.append(["Within commitment (contributions)", m(n.lp_contributions_current)])
        if n.lp_outside_outflow_current:
            rows.append(["Outside commitment", m(n.lp_outside_outflow_current)])
    net = n.lp_net_called_distributed
    rows.append(["Amount due from you" if net > 0 else "Net amount payable to you (shown negative)", m(net)])
    t1 = Table(rows, colWidths=[125 * mm, 50 * mm])
    t1.setStyle(rule)
    t1.setStyle(TableStyle([("FONT", (0, -1), (-1, -1), "Helvetica-Bold", 8.5),
                            ("LINEABOVE", (0, -1), (-1, -1), 0.5, colors.grey)]))
    s.append(t1)

    s.append(Paragraph("Your capital account", h))
    bal = [["", "Prior to this notice", "This notice", "After this notice"],
           ["Contributions", m(n.lp_cum_contributions_prior), m(z(n.lp_contributions_current)),
            m(n.lp_cum_contributions_incl)],
           ["Distributions", m(n.lp_cum_distributions_prior), m(z(n.lp_distributions_current)),
            m(n.lp_cum_distributions_incl)],
           ["Unfunded commitment", m(n.lp_unfunded_prior), m(n.lp_unfunded_impact_current), m(n.lp_unfunded_incl)]]
    if n.lp_recallable_balance is not None:
        bal.append(["Recallable distributions", "", "", m(n.lp_recallable_balance)])
    t2 = Table(bal, colWidths=[50 * mm, 42 * mm, 41 * mm, 42 * mm])
    t2.setStyle(rule)
    s.append(t2)
    s.append(Spacer(1, 2 * mm))
    t3 = Table([["Your commitment", m(n.lp_commitment), "Your percentage of the Fund", pct(n.lp_pct_of_fund)]],
               colWidths=[35 * mm, 50 * mm, 50 * mm, 40 * mm])
    t3.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), "Helvetica", 8.5), ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                            ("ALIGN", (3, 0), (3, 0), "RIGHT")]))
    s.append(t3)

    s.append(Paragraph("Fund totals", h))
    fr = [["Total fund size", m(n.fund_size)], ["General Partner commitment", m(n.gp_commitment)]]
    if n.fund_contributions_current is not None:
        fr.append(["Total capital called from all partners, this notice", m(n.fund_contributions_current)])
    if n.fund_distributions_current is not None:
        fr.append(["Total distributed to all partners, this notice", m(n.fund_distributions_current)])
    t4 = Table([["Item", "Amount"]] + fr, colWidths=[125 * mm, 50 * mm])
    t4.setStyle(rule)
    s.append(t4)

    s.append(Paragraph("Paid from the Fund account" if is_dist(n) else "Wire instructions", h))
    t5 = Table(bank_rows(n, "ABA routing number"), colWidths=[40 * mm, 135 * mm])
    t5.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), "Helvetica", 8.5), ("FONT", (0, 0), (0, -1), "Helvetica-Bold", 8.5),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 1), ("TOPPADDING", (0, 0), (-1, -1), 1)]))
    s.append(t5)
    s.append(Spacer(1, 3 * mm))
    s.append(Paragraph(f"Questions: investor relations, {n.gp_name}. Please verify any change to payment "
                       "instructions by telephone before sending funds.", small))
    SimpleDocTemplate(str(path), pagesize=LETTER, topMargin=26 * mm, bottomMargin=16 * mm, leftMargin=18 * mm,
                      rightMargin=18 * mm, title=title).build(s, onFirstPage=letterhead, onLaterPages=letterhead)
    return {}  # everything on page 1


# ---------------------------------------------------------------- style 2
def style2(n, path: Path) -> dict[str, int]:
    d = lambda x: f"{x:%m/%d/%Y}"  # noqa: E731
    m = lambda v: fmt(v, "paren")  # noqa: E731
    m0 = lambda v: fmt(v, "us0")  # noqa: E731
    title = "Notice of Distribution" if is_dist(n) else "Notice of Capital Contribution"
    body = ps("b2", "Times-Roman", 10.5, spaceAfter=5)
    centre = ps("c2", "Times-Roman", 9, alignment=TA_CENTER)
    big = ps("g2", "Times-Bold", 17, alignment=TA_CENTER, spaceAfter=1)
    h = ps("h2", "Times-Bold", 11, spaceBefore=8, spaceAfter=4)
    grid = TableStyle([("FONT", (0, 0), (-1, -1), "Times-Roman", 10), ("FONT", (0, 0), (-1, 0), "Times-Bold", 10),
                       ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                       ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8E8E8"))])
    s = [Paragraph(n.gp_name.upper(), big),
         Paragraph(f"as general partner of {n.fund_name}", centre), Spacer(1, 6 * mm),
         Paragraph(f"<b>{title}</b>", ps("t2", "Times-Bold", 13, alignment=TA_CENTER)), Spacer(1, 4 * mm)]
    head = Table([["Date of notice", d(n.notice_date)],
                  ["Payment date" if is_dist(n) else "Funds due by", d(n.due_date)],
                  ["Limited Partner", n.lp_name], ["Partner number", n.lp_id],
                  ["Reporting currency", n.fund_currency]], colWidths=[45 * mm, 120 * mm])
    head.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), "Times-Roman", 10),
                              ("FONT", (0, 0), (0, -1), "Times-Bold", 10)]))
    s += [head, Spacer(1, 4 * mm), Paragraph("Dear Limited Partner,", body)]
    if is_dist(n):
        s.append(Paragraph(f"We are pleased to advise that {n.fund_name} will distribute proceeds received from "
                           f"the realisation of portfolio investments. Your share is shown below and will be paid "
                           f"to your account of record on {d(n.due_date)}.", body))
    else:
        s.append(Paragraph(f"Pursuant to the partnership agreement, the General Partner is calling capital for the "
                           f"purposes described below. Please wire your share in immediately available funds so that "
                           f"it is received no later than {d(n.due_date)}.", body))
    s.append(Paragraph("Your share of this notice", h))
    rows = [["Amount (USD)", "Description", "Category"]]
    for t in n.transactions:
        cat = ("Outside commitment" if is_outside(t) else
               "Tax" if is_tax(t) else
               "Distribution" if t.transaction_type.value.startswith("Distribution") else "Capital call")
        rows.append([m(-t.lp_amount) if is_tax(t) else m(t.lp_amount), t.description, cat])
    if is_dist(n):
        rows.append([m(n.lp_distributions_current), "Net distribution", ""])
        rows.append([m(n.lp_net_called_distributed), "Net amount (negative = payable to you)", ""])
    else:
        rows.append([m(n.lp_contributions_current), "Capital contribution (reduces commitment)", ""])
        if n.lp_outside_outflow_current:
            rows.append([m(n.lp_outside_outflow_current), "Payable in addition to commitment", ""])
        rows.append([m(n.lp_net_called_distributed), "Total amount due", ""])
    t1 = Table(rows, colWidths=[35 * mm, 95 * mm, 35 * mm])
    t1.setStyle(grid)
    t1.setStyle(TableStyle([("ALIGN", (0, 0), (0, -1), "RIGHT"), ("FONT", (0, -1), (-1, -1), "Times-Bold", 10)]))
    s.append(t1)

    s.append(Paragraph("Fund-level totals", h))
    fr = [["Amount (USD)", "Item"], [m0(n.fund_size), "Aggregate fund commitments"],
          [m0(n.gp_commitment), "General partner commitment"]]
    if n.fund_contributions_current is not None:
        fr.append([m0(n.fund_contributions_current), "Total fund capital call, this notice"])
    if n.fund_distributions_current is not None:
        fr.append([m0(n.fund_distributions_current), "Total fund distribution, this notice"])
    t2 = Table(fr, colWidths=[45 * mm, 120 * mm])
    t2.setStyle(grid)
    t2.setStyle(TableStyle([("ALIGN", (0, 0), (0, -1), "RIGHT")]))
    s.append(t2)

    s.append(Paragraph("Remittance account of the Fund" if is_dist(n) else "Payment instructions", h))
    t3 = Table(bank_rows(n, "ABA number"), colWidths=[45 * mm, 120 * mm])
    t3.setStyle(grid)
    s.append(t3)
    s.append(Spacer(1, 4 * mm))
    s.append(Paragraph("Your capital account summary appears in Schedule A on the following page.", body))
    s.append(Paragraph(f"Sincerely,<br/>{n.gp_name}", body))

    # page 2: balances
    s += [PageBreak(), Paragraph(f"Schedule A - Capital Account Summary - {n.lp_id}", h),
          Paragraph(f"{n.fund_name} | as at {d(n.notice_date)}", centre), Spacer(1, 4 * mm)]
    bal = [["Item", "Amount (USD)"],
           ["Capital commitment", m(n.lp_commitment)],
           ["Ownership percentage of fund", pct(n.lp_pct_of_fund)],
           ["Contributions before this notice", m(n.lp_cum_contributions_prior)],
           ["Contributions, this notice", m(z(n.lp_contributions_current))],
           ["Cumulative contributions", m(n.lp_cum_contributions_incl)],
           ["Distributions before this notice", m(n.lp_cum_distributions_prior)],
           ["Distributions, this notice", m(z(n.lp_distributions_current))],
           ["Cumulative distributions", m(n.lp_cum_distributions_incl)],
           ["Remaining commitment before this notice", m(n.lp_unfunded_prior)],
           ["Change in remaining commitment", m(n.lp_unfunded_impact_current)],
           ["Remaining commitment after this notice", m(n.lp_unfunded_incl)]]
    if n.lp_recallable_balance is not None:
        bal.append(["Recallable amount", m(n.lp_recallable_balance)])
    t4 = Table(bal, colWidths=[110 * mm, 55 * mm])
    t4.setStyle(grid)
    t4.setStyle(TableStyle([("ALIGN", (1, 0), (1, -1), "RIGHT")]))
    s.append(t4)

    def foot(c, doc):
        c.setFont("Times-Italic", 8)
        c.drawCentredString(LETTER[0] / 2, 12 * mm, f"Page {doc.page} of 2 - Confidential")

    SimpleDocTemplate(str(path), pagesize=LETTER, topMargin=18 * mm, bottomMargin=20 * mm, leftMargin=25 * mm,
                      rightMargin=25 * mm, title=title).build(s, onFirstPage=foot, onLaterPages=foot)
    p2 = ["lp_commitment", "lp_pct_of_fund", "lp_cum_contributions_prior", "lp_cum_contributions_incl",
          "lp_cum_distributions_prior", "lp_cum_distributions_incl", "lp_unfunded_prior",
          "lp_unfunded_impact_current", "lp_unfunded_incl", "lp_recallable_balance"]
    return {f: 2 for f in p2}


# ---------------------------------------------------------------- style 3
def style3(n, path: Path) -> dict[str, int]:
    cur = "£"
    m = lambda v: fmt(v, "paren", cur)  # noqa: E731
    d = lambda x: x.isoformat()  # noqa: E731
    gold = colors.HexColor("#8A6D1F")
    shade = colors.HexColor("#EFEAD8")
    title = "DISTRIBUTION ADVICE" if is_dist(n) else "DRAWDOWN NOTICE"
    body = ps("b3", "Helvetica", 8.5, spaceAfter=3)
    h = ps("h3", "Helvetica-Bold", 8.5, textColor=gold, spaceBefore=7, spaceAfter=2)
    tab = TableStyle([("FONT", (0, 0), (-1, -1), "Courier", 8), ("FONT", (0, 0), (-1, 0), "Courier-Bold", 8),
                      ("BACKGROUND", (0, 0), (-1, 0), shade), ("LINEBELOW", (0, -1), (-1, -1), 0.4, gold),
                      ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5), ("TOPPADDING", (0, 0), (-1, -1), 1.5)])
    s = []
    lh = Table([[Paragraph(f"<b>{n.gp_name}</b>", ps("l3", "Helvetica-Bold", 15, textColor=gold)),
                 Paragraph(f"<b>{title}</b><br/>{n.fund_name}", ps("r3", "Helvetica", 9, alignment=TA_RIGHT))]],
               colWidths=[80 * mm, 94 * mm])
    lh.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, 0), 1.5, gold), ("VALIGN", (0, 0), (-1, -1), "BOTTOM")]))
    s += [lh, Spacer(1, 4 * mm)]
    ref = Table([["Investor", n.lp_name, "Issued", d(n.notice_date)],
                 ["Investor no.", n.lp_id, "Value date" if is_dist(n) else "Settle by", d(n.due_date)],
                 ["Fund", n.fund_name, "Ccy", n.fund_currency]],
                colWidths=[24 * mm, 90 * mm, 22 * mm, 38 * mm])
    ref.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), "Courier", 8), ("FONT", (0, 0), (0, -1), "Courier-Bold", 8),
                             ("FONT", (2, 0), (2, -1), "Courier-Bold", 8), ("BOX", (0, 0), (-1, -1), 0.4, gold)]))
    s.append(ref)
    s.append(Spacer(1, 3 * mm))
    if is_dist(n):
        s.append(Paragraph("The Fund has received proceeds from the sale of, and income from, portfolio companies "
                           "and is returning them to investors. Your share will be credited on the value date. "
                           f"Figures in {n.fund_currency}; amounts in brackets are credits to you.", body))
    else:
        s.append(Paragraph("The Manager gives notice of a drawdown of commitments. Please settle your share in "
                           f"cleared funds by the settle-by date. Figures in {n.fund_currency}.", body))
    s.append(Paragraph("1. YOUR SHARE", h))
    rows = [["Ref", "Category", "Description", "Your share"]]
    for i, t in enumerate(n.transactions, 1):
        cat = ("Excess" if is_outside(t) else "WHT" if is_tax(t) else
               "Distrib." if t.transaction_type.value.startswith("Distribution") else "Drawdown")
        rows.append([f"T{i:02d}", cat, t.description, m(t.lp_amount if is_tax(t) else
                                                         (-t.lp_amount if is_dist(n) else t.lp_amount))])
    if is_dist(n):
        rows.append(["", "", "Net distribution (after tax)", m(-n.lp_distributions_current)])
    else:
        rows.append(["", "", "Drawn against commitment", m(n.lp_contributions_current)])
        if n.lp_outside_outflow_current:
            rows.append(["", "", "Payable outside commitment", m(n.lp_outside_outflow_current)])
    rows.append(["", "", "NET AMOUNT (credit in brackets)" if is_dist(n) else "AMOUNT DUE",
                 m(n.lp_net_called_distributed)])
    t1 = Table(rows, colWidths=[12 * mm, 20 * mm, 102 * mm, 40 * mm])
    t1.setStyle(tab)
    t1.setStyle(TableStyle([("ALIGN", (3, 0), (3, -1), "RIGHT"), ("FONT", (0, -1), (-1, -1), "Courier-Bold", 8)]))
    s.append(t1)

    s.append(Paragraph("2. CAPITAL ACCOUNT", h))
    bal = [["", "Before notice", "Movement", "After notice"],
           ["Drawn", m(n.lp_cum_contributions_prior), m(z(n.lp_contributions_current)), m(n.lp_cum_contributions_incl)],
           ["Distributed", m(n.lp_cum_distributions_prior), m(z(n.lp_distributions_current)),
            m(n.lp_cum_distributions_incl)],
           ["Undrawn", m(n.lp_unfunded_prior), m(n.lp_unfunded_impact_current), m(n.lp_unfunded_incl)]]
    if n.lp_recallable_balance is not None:
        bal.append(["Recallable", "", "", m(n.lp_recallable_balance)])
    bal.append(["Commitment", "", "", m(n.lp_commitment)])
    bal.append(["Share of Fund", "", "", pct(n.lp_pct_of_fund)])
    t2 = Table(bal, colWidths=[34 * mm, 47 * mm, 46 * mm, 47 * mm])
    t2.setStyle(tab)
    t2.setStyle(TableStyle([("ALIGN", (1, 0), (-1, -1), "RIGHT")]))
    s.append(t2)

    s.append(Paragraph("3. FUND", h))
    fr = [["Item", "Total"], ["Total commitments", fmt(n.fund_size, "us0", cur)],
          ["Manager/GP commitment", fmt(n.gp_commitment, "us0", cur)]]
    if n.fund_contributions_current is not None:
        fr.append(["Drawdown, all investors", m(n.fund_contributions_current)])
    if n.fund_distributions_current is not None:
        fr.append(["Distribution, all investors", m(n.fund_distributions_current)])
    t3 = Table(fr, colWidths=[134 * mm, 40 * mm])
    t3.setStyle(tab)
    t3.setStyle(TableStyle([("ALIGN", (1, 0), (1, -1), "RIGHT")]))
    s.append(t3)

    s.append(Paragraph("4. FUND BANK ACCOUNT (PAYING)" if is_dist(n) else "4. SETTLEMENT ACCOUNT", h))
    t4 = Table([["Field", "Detail"]] + [list(r) for r in bank_rows(n, "Sort code")], colWidths=[40 * mm, 134 * mm])
    t4.setStyle(tab)
    s.append(t4)
    s.append(Spacer(1, 3 * mm))
    s.append(Paragraph(f"Issued by {n.gp_name} on behalf of the Fund. The Manager will never change bank details "
                       "by email.", ps("f3", "Helvetica-Oblique", 7, textColor=colors.grey)))
    SimpleDocTemplate(str(path), pagesize=A4, topMargin=15 * mm, bottomMargin=15 * mm, leftMargin=18 * mm,
                      rightMargin=18 * mm, title=title).build(s)
    return {}


# ---------------------------------------------------------------- driver
PLAN = [  # (fund seed, currency, sequence seed, n, style)
    (101, "USD", 201, 4, style1),
    (102, "USD", 202, 3, style2),
    (103, "GBP", 203, 3, style3),
]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    results = []
    for fi, (fseed, ccy, sseed, n, style) in enumerate(PLAN, 1):
        fund = make_fund(fseed, ccy)
        for ni, key in enumerate(make_sequence(fund, sseed, n), 1):
            name = f"a_fund{fi}_n{ni}"
            pdf = OUT / f"{name}.pdf"
            key.source_file = pdf.name
            overrides = style(key, pdf)
            for f, v in key.model_dump().items():
                if f not in SKIP and v is not None:
                    key.pages[f] = overrides.get(f, 1)
            for t in key.transactions:
                t.page = 1
            key.bank.page = 1
            write_key(key, OUT / f"{name}.json")
            results.append((name, style.__name__, key.kind.value, verify_pdf(pdf, key)))
    bad = 0
    for name, st, kind, probs in results:
        print(f"{name:14} {st:7} {kind:13} {'OK' if not probs else 'FAIL'}")
        for p in probs:
            print("    -", p)
        bad += bool(probs)
    print(f"{len(results)} documents, {len(results) - bad} pass, {bad} fail")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
