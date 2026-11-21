"""Layout family B: prose letters, multi-page, with fee/expense breakdowns.

Three funds, each rendered in its own GP house style:
  A  (USD) US law-firm letter after the ILPA sample description letter: Times, wire box on page 1, Schedule A.
  B  (EUR) Luxembourg AIFM drawdown notice: Helvetica, EU number format, annexes, IBAN on the last pages.
  C  (GBP) London private-equity house letter: Georgia, space-grouped numbers, wire box on page 1 or last page.

Run: .venv/bin/python testset/gen/family_b.py   (writes testset/build/family_b/*.pdf + *.json)
"""
from __future__ import annotations

import random
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (  # noqa: E402
    ROOT, InsideOutside, NoticeKind, T, fmt, make_fund, make_sequence, page_texts, verify_pdf, write_key,
)
from drawbook.schema import SCALAR_FIELDS, Notice  # noqa: E402

from reportlab.lib import colors  # noqa: E402
from reportlab.lib.enums import TA_JUSTIFY, TA_RIGHT, TA_CENTER  # noqa: E402
from reportlab.lib.pagesizes import A4, LETTER  # noqa: E402
from reportlab.lib.styles import ParagraphStyle  # noqa: E402
from reportlab.lib.units import mm  # noqa: E402
from reportlab.pdfbase import pdfmetrics  # noqa: E402
from reportlab.pdfbase.ttfonts import TTFont  # noqa: E402
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle  # noqa: E402

OUT = ROOT / "testset" / "build" / "family_b"

# ---------- fonts ----------
SERIF_C, SERIF_C_B = "Times-Roman", "Times-Bold"
_g = Path("/System/Library/Fonts/Supplemental")
if (_g / "Georgia.ttf").exists() and (_g / "Georgia Bold.ttf").exists():
    pdfmetrics.registerFont(TTFont("Georgia", str(_g / "Georgia.ttf")))
    pdfmetrics.registerFont(TTFont("Georgia-Bold", str(_g / "Georgia Bold.ttf")))
    SERIF_C, SERIF_C_B = "Georgia", "Georgia-Bold"


# ---------- helpers ----------
class Rec:
    """Records the cited page for each filled field."""

    def __init__(self, key: Notice):
        self.key = key

    def __call__(self, page: int, *fields: str) -> None:
        for f in fields:
            if getattr(self.key, f) is not None:
                self.key.pages[f] = page

    def check(self) -> None:
        missing = [f for f in SCALAR_FIELDS if f not in ("kind",) and getattr(self.key, f) is not None
                   and f not in self.key.pages]
        if missing:
            raise RuntimeError(f"{self.key.source_file}: no page recorded for {missing}")


def parts(k: Notice):
    calls_in = [t for t in k.transactions if t.transaction_type.value.startswith("Capital Call")
                and t.inside_outside == InsideOutside.INSIDE]
    calls_out = [t for t in k.transactions if t.inside_outside == InsideOutside.OUTSIDE]
    dists = [t for t in k.transactions if t.transaction_type.value.startswith("Distribution")
             and t.transaction_type != T.D_TAX_WITHHELD]
    tax = [t for t in k.transactions if t.transaction_type == T.D_TAX_WITHHELD]
    return calls_in, calls_out, dists, tax


FEE_TYPES = (T.CC_MGMT_FEES, T.CC_EXPENSES, T.CC_SUB_FACILITY, T.CC_WORKING_CAPITAL)


def ssum(ts) -> Decimal:
    return sum((t.lp_amount for t in ts), Decimal("0.00"))


def build(path: Path, pages: list[list], pagesize, margins, deco) -> None:
    lm, rm, tm, bm = margins
    doc = SimpleDocTemplate(str(path), pagesize=pagesize, leftMargin=lm, rightMargin=rm, topMargin=tm,
                            bottomMargin=bm, title=path.stem, author="Drawbook test set")
    story = []
    for i, p in enumerate(pages):
        story += p
        if i < len(pages) - 1:
            story.append(PageBreak())
    total = len(pages)
    doc.build(story, onFirstPage=lambda c, d: deco(c, d, total), onLaterPages=lambda c, d: deco(c, d, total))


def wire_payable(k: Notice) -> bool:
    return k.kind != NoticeKind.DISTRIBUTION and k.lp_net_called_distributed > 0


# =====================================================================
# Style A: US law-firm letter (USD)
# =====================================================================
MON_A = ["Jan.", "Feb.", "March", "April", "May", "June", "July", "Aug.", "Sept.", "Oct.", "Nov.", "Dec."]


def dA(d):
    return f"{MON_A[d.month - 1]} {d.day}, {d.year}"


def mA(x):
    return fmt(x, "paren", "$")


def styleA(k: Notice, n: int, rec: Rec, r: random.Random) -> tuple[list[list], callable]:
    F, FB = "Times-Roman", "Times-Bold"
    body = ParagraphStyle("a", fontName=F, fontSize=10.5, leading=14, alignment=TA_JUSTIFY, spaceAfter=7)
    small = ParagraphStyle("as", parent=body, fontSize=8, leading=10)
    h = ParagraphStyle("ah", parent=body, fontName=FB, fontSize=12, alignment=TA_CENTER, spaceAfter=10)
    h2 = ParagraphStyle("ah2", parent=body, fontName=FB, fontSize=10.5, spaceBefore=6, spaceAfter=4)
    cell = ParagraphStyle("ac", fontName=F, fontSize=9.5, leading=11.5)
    cin, cout, dists, tax = parts(k)
    is_call = k.kind == NoticeKind.CAPITAL_CALL
    pct_paid = k.lp_cum_contributions_incl / k.lp_commitment * 100

    # ---- page 1: description letter ----
    p1 = []
    hdr = Table([
        ["To:", Paragraph(f"{k.lp_name} (Investor ID {k.lp_id}), Attn: Investment Operations", cell)],
        ["From:", Paragraph(f"Investor Relations, {k.gp_name}, +1 (212) 555-0142, ir@{k.gp_name.split()[0].lower()}.example.com", cell)],
        ["RE:", Paragraph(k.fund_name, cell)],
        ["Date of Notice:", dA(k.notice_date)],
        ["Date Notice is Due:" if is_call else "Distribution Date:", dA(k.due_date)],
    ], colWidths=[1.35 * 72, 5.1 * 72])
    hdr.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), F, 9.5), ("FONT", (0, 0), (0, -1), FB, 9.5),
                             ("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
    p1 += [hdr, Spacer(1, 10)]
    rec(1, "lp_name", "lp_id", "fund_name", "notice_date", "due_date")
    title = {NoticeKind.CAPITAL_CALL: r.choice(["CAPITAL CALL NOTICE", "NOTICE OF CAPITAL CALL"]),
             NoticeKind.DISTRIBUTION: "NOTICE OF DISTRIBUTION"}[k.kind]
    p1.append(Paragraph(f"{title} No. {n}", h))
    if is_call:
        what = ["an investment"] + (["management fees and partnership expenses"] if any(
            t.transaction_type in FEE_TYPES for t in cin) else [])
        p1.append(Paragraph(
            f"{k.fund_name} (the &ldquo;Fund&rdquo;) is calling {mA(k.fund_contributions_current)} from its limited "
            f"partners in aggregate for {' and '.join(what)}. Please refer to the attached Schedule A for a breakdown "
            f"of the components of the amount, and to the narrative on page 3 for a description of the components "
            f"referred to in this notice.", body))
        rec(1, "fund_contributions_current")
        extra = ""
        if cout:
            extra = (f" Of this amount, {mA(ssum(cout))} relates to amounts payable outside your commitment "
                     f"and does not reduce your unfunded commitment.")
        p1.append(Paragraph(
            f"Your portion of the call is {mA(k.lp_net_called_distributed)}.{extra} After this notice, you will have "
            f"contributed {pct_paid:.2f}% of your commitment of {mA(k.lp_commitment)}, and your unfunded commitment "
            f"will be {mA(k.lp_unfunded_incl)}. You have received {mA(k.lp_cum_distributions_incl)} in distributions "
            f"to date. Please refer to the Schedule for further details.", body))
        rec(1, "lp_net_called_distributed", "lp_unfunded_incl", "lp_cum_distributions_incl")
        b = k.bank
        b.reference = f"{k.lp_id} / Call {n}"
        wire = Table([
            ["Due Date", f"{k.due_date.month}/{k.due_date.day}/{k.due_date.year}"],
            ["Amount Due", mA(k.lp_net_called_distributed)],
            ["Bank Name", b.bank_name], ["ABA#", b.sort_code], ["SWIFT", b.swift_bic],
            ["Credit To", Paragraph(b.account_name, cell)], ["Account#", b.account_number],
            ["Reference", b.reference],
        ], colWidths=[1.6 * 72, 4.2 * 72])
        wire.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), F, 9.5), ("FONT", (0, 0), (0, -1), FB, 9.5),
                                  ("BOX", (0, 0), (-1, -1), 0.8, colors.black),
                                  ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")),
                                  ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
        p1 += [Paragraph("Please wire your funds to:", body), wire, Spacer(1, 8)]
        b.page = 1
    else:
        p1.append(Paragraph(
            f"{k.fund_name} (the &ldquo;Fund&rdquo;) is distributing {mA(k.fund_distributions_current)} to its "
            f"partners in aggregate, net of any withholding, following the realization described on page 3.", body))
        rec(1, "fund_distributions_current")
        p1.append(Paragraph(
            f"Your portion of the distribution is {mA(k.lp_distributions_current)}, which will be wired to the "
            f"account we hold on file for you on {dA(k.due_date)}. After this distribution, you will have received "
            f"{mA(k.lp_cum_distributions_incl)} in aggregate distributions. Your unfunded commitment is unchanged at "
            f"{mA(k.lp_unfunded_incl)}, and you have contributed {pct_paid:.2f}% of your commitment of "
            f"{mA(k.lp_commitment)}.", body))
        rec(1, "lp_distributions_current", "lp_cum_distributions_incl", "lp_unfunded_incl")
        p1.append(Paragraph("No payment is required from you in respect of this notice. If your wire instructions "
                            "have changed, please contact Investor Relations by telephone before the distribution "
                            "date; we will not act on changes received by e-mail alone.", body))
        k.bank = None
    p1.append(Paragraph(
        "Wire fraud warning: the Fund will never change its bank details by e-mail. Before sending funds, confirm "
        "these instructions by calling your Investor Relations contact on a number you already hold.", small))
    p1.append(Spacer(1, 6))
    p1.append(Paragraph(f"Very truly yours,<br/><br/>{k.gp_name}, as General Partner", body))

    # ---- page 2: Schedule A ----
    p2 = [Paragraph(f"SCHEDULE A &mdash; {'CAPITAL CALL' if is_call else 'DISTRIBUTION'} DETAIL", h),
          Paragraph(f"Notice No. {n} dated {dA(k.notice_date)}. All amounts in U.S. dollars (USD).", body)]
    finfo = Table([
        ["Fund", Paragraph(k.fund_name, cell)], ["General Partner", k.gp_name], ["Fund currency", k.fund_currency],
        ["Total fund commitments", mA(k.fund_size)], ["General Partner commitment", mA(k.gp_commitment)],
        ["Limited Partner", Paragraph(k.lp_name, cell)], ["Investor ID", k.lp_id],
        ["Your commitment", mA(k.lp_commitment)], ["Your percentage of the Fund", f"{k.lp_pct_of_fund * 100:.4f}%"],
    ], colWidths=[2.4 * 72, 4.0 * 72])
    finfo.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), F, 9.5), ("FONT", (0, 0), (0, -1), FB, 9.5),
                               ("GRID", (0, 0), (-1, -1), 0.3, colors.grey), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    p2 += [finfo, Spacer(1, 8)]
    rec(2, "gp_name", "fund_currency", "fund_size", "gp_commitment", "lp_commitment", "lp_pct_of_fund")
    rows = [["Component", "Your share"]]
    sect = []
    if is_call:
        inv = [t for t in cin if t.transaction_type == T.CC_INVESTMENTS]
        fees = [t for t in cin if t.transaction_type in FEE_TYPES]
        for label, ts in (("Investments", inv), ("Management fees and partnership expenses", fees),
                          ("Amounts outside commitment", cout)):
            if not ts:
                continue
            sect.append(len(rows))
            rows.append([label, ""])
            for t in ts:
                rows.append([Paragraph("&nbsp;&nbsp;&nbsp;" + t.description, cell), mA(t.lp_amount)])
                t.page = 2
            if label.startswith("Management") and len(ts) > 1:
                rows.append([Paragraph("&nbsp;&nbsp;&nbsp;Subtotal, fees and expenses", cell), mA(ssum(ts))])
        rows.append(["Total called from you", mA(k.lp_net_called_distributed)])
    else:
        sect.append(len(rows))
        rows.append(["Distribution components", ""])
        for t in dists:
            rows.append([Paragraph("&nbsp;&nbsp;&nbsp;" + t.description, cell), mA(t.lp_amount)])
            t.page = 2
        for t in tax:
            rows.append([Paragraph("&nbsp;&nbsp;&nbsp;Less: " + t.description, cell), mA(-t.lp_amount)])
            t.page = 2
        rows.append(["Net distribution to you", mA(k.lp_distributions_current)])
        rec(2, "lp_net_called_distributed")
    comp = Table(rows, colWidths=[4.6 * 72, 1.8 * 72])
    cs = [("FONT", (0, 0), (-1, -1), F, 9.5), ("FONT", (0, 0), (-1, 0), FB, 9.5), ("FONT", (0, -1), (-1, -1), FB, 9.5),
          ("ALIGN", (1, 0), (1, -1), "RIGHT"), ("LINEBELOW", (0, 0), (-1, 0), 0.8, colors.black),
          ("LINEABOVE", (0, -1), (-1, -1), 0.8, colors.black)]
    cs += [("FONT", (0, i), (0, i), FB, 9.5) for i in sect]
    comp.setStyle(TableStyle(cs))
    p2 += [comp, Spacer(1, 10)]
    dash = lambda v: mA(v) if v is not None else "—"  # noqa: E731
    bal = Table([
        ["Capital account", "Prior to notice", "This notice", "Including notice"],
        ["Contributions", mA(k.lp_cum_contributions_prior), dash(k.lp_contributions_current),
         mA(k.lp_cum_contributions_incl)],
        ["Distributions", mA(k.lp_cum_distributions_prior), dash(k.lp_distributions_current),
         mA(k.lp_cum_distributions_incl)],
        ["Unfunded commitment", mA(k.lp_unfunded_prior), mA(k.lp_unfunded_impact_current), mA(k.lp_unfunded_incl)],
    ], colWidths=[1.9 * 72, 1.5 * 72, 1.5 * 72, 1.5 * 72])
    bal.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), F, 9.5), ("FONT", (0, 0), (-1, 0), FB, 9.5),
                             ("ALIGN", (1, 0), (-1, -1), "RIGHT"), ("GRID", (0, 0), (-1, -1), 0.3, colors.grey)]))
    p2 += [bal]
    rec(2, "lp_cum_contributions_prior", "lp_contributions_current", "lp_cum_contributions_incl",
        "lp_cum_distributions_prior", "lp_unfunded_prior", "lp_unfunded_impact_current")
    if cout:
        p2.append(Paragraph(f"Amounts called outside commitment this notice: {mA(k.lp_outside_outflow_current)}.", body))
        rec(2, "lp_outside_outflow_current")
    if not is_call:
        p2.append(Paragraph(f"Aggregate distribution by the Fund: {mA(k.fund_distributions_current)}.", body))

    # ---- page 3: description of components + legal ----
    p3 = [Paragraph("DESCRIPTION OF COMPONENTS", h)]
    if is_call:
        inv = [t for t in cin if t.transaction_type == T.CC_INVESTMENTS][0]
        co = inv.description.replace("Investment in ", "")
        p3.append(Paragraph(
            f"<b>Investment.</b> The Fund is calling capital for its investment in {co}. The proceeds will fund the "
            f"Fund&rsquo;s share of the purchase price together with transaction costs. The investment is expected to "
            f"close shortly after the due date of this notice, and the Fund will receive preferred equity with a 1x "
            f"liquidation preference. Further detail will be provided in the next quarterly report.", body))
        p3.append(Paragraph(
            "<b>Management fees.</b> Management fees are charged quarterly in advance at the rate set out in Section 4.1 "
            "of the Limited Partnership Agreement (the &ldquo;LPA&rdquo;), calculated on commitments during the "
            "investment period and reduced by any fee offsets due to the limited partners.", body))
        if any(t.transaction_type == T.CC_EXPENSES for t in cin):
            p3.append(Paragraph(
                "<b>Partnership expenses.</b> Partnership expenses comprise legal, audit, fund administration and "
                "other organizational costs borne by the Fund under Section 4.3 of the LPA.", body))
        if any(t.transaction_type == T.CC_SUB_FACILITY for t in cin):
            p3.append(Paragraph(
                "<b>Subscription facility.</b> The Fund drew on its subscription credit facility pending this call; "
                "the interest shown on Schedule A is the portion attributable to you.", body))
    else:
        co = dists[0].description.split(" of ")[-1]
        p3.append(Paragraph(
            f"<b>Realization.</b> The Fund completed the sale of {co}. Proceeds are distributed in accordance with "
            f"the distribution waterfall in Section 6.2 of the LPA. The return of capital portion is not recallable.",
            body))
        if tax:
            p3.append(Paragraph("<b>Withholding.</b> Amounts withheld in respect of taxes are treated as distributed "
                                "to you for all purposes of the LPA. A statement will follow with your Schedule K-1.",
                                body))
    p3.append(Paragraph("IMPORTANT NOTICE", h2))
    for t in [
        "If a Limited Partner fails to pay any portion of its capital contribution when due, the General Partner may "
        "charge interest on the unpaid amount and exercise the remedies set out in Article 7 of the LPA, including "
        "forfeiture of a portion of the defaulting partner's interest.",
        "This notice is confidential and is furnished solely for the use of the addressee. It does not constitute an "
        "offer to sell or a solicitation of an offer to buy any security. Nothing in this notice is tax, legal or "
        "investment advice; each Limited Partner should consult its own advisers.",
        "In the event of any inconsistency between this notice and the LPA, the LPA shall govern.",
    ]:
        p3.append(Paragraph(t, small))

    def deco(c, d, total):
        w, hgt = LETTER
        c.saveState()
        c.setFont(FB, 15)
        c.drawString(72, hgt - 50, k.gp_name.upper())
        c.setFont(F, 8.5)
        c.drawString(72, hgt - 63, "1290 Avenue of the Americas, 31st Floor, New York, NY 10104   |   Tel +1 (212) 555-0142")
        c.setLineWidth(1.2)
        c.line(72, hgt - 70, w - 72, hgt - 70)
        c.setFont(F, 7.5)
        c.line(72, 50, w - 72, 50)
        c.drawString(72, 38, f"{k.fund_name} | Confidential")
        c.drawRightString(w - 72, 38, f"Page {d.page} of {total}")
        c.restoreState()

    return [p1, p2, p3], deco, LETTER, (72, 72, 90, 70)


# =====================================================================
# Style B: Luxembourg AIFM drawdown notice (EUR)
# =====================================================================
def dB(d):
    return d.strftime("%d.%m.%Y")


def mB(x):
    return "EUR " + fmt(x, "eu")


def eB(x):
    return fmt(x, "eu", "€")


def styleB(k: Notice, n: int, rec: Rec, r: random.Random):
    F, FB = "Helvetica", "Helvetica-Bold"
    navy = colors.HexColor("#1f3a5f")
    body = ParagraphStyle("b", fontName=F, fontSize=9.5, leading=13.5, spaceAfter=7)
    small = ParagraphStyle("bs", parent=body, fontSize=7.5, leading=9.5, textColor=colors.HexColor("#444444"))
    h = ParagraphStyle("bh", parent=body, fontName=FB, fontSize=13, textColor=navy, spaceAfter=8)
    h2 = ParagraphStyle("bh2", parent=body, fontName=FB, fontSize=10, textColor=navy, spaceBefore=8, spaceAfter=4)
    cell = ParagraphStyle("bc", fontName=F, fontSize=8.5, leading=10.5)
    cin, cout, dists, tax = parts(k)
    kind = k.kind
    ref = f"{'DN' if kind != NoticeKind.DISTRIBUTION else 'DS'}-{k.lp_id}-{n:03d}"
    tstyle = [("FONT", (0, 0), (-1, -1), F, 8.5), ("FONT", (0, 0), (-1, 0), FB, 8.5),
              ("BACKGROUND", (0, 0), (-1, 0), navy), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
              ("LINEBELOW", (0, 1), (-1, -1), 0.25, colors.HexColor("#b8c4d4")), ("VALIGN", (0, 0), (-1, -1), "TOP")]
    n_pages = 4 if kind == NoticeKind.COMBINED or n == 3 else 3

    # ---- page 1: cover letter ----
    title = {NoticeKind.CAPITAL_CALL: r.choice(["Drawdown Notice", "Capital Contribution Request"]),
             NoticeKind.COMBINED: "Combined Drawdown and Distribution Notice",
             NoticeKind.DISTRIBUTION: "Notice of Distribution"}[kind]
    addr = Paragraph(f"<b>{k.lp_name}</b><br/>c/o Investment Operations<br/>By secure investor portal", body)
    refbox = Table([["Reference", ref], ["Investor", k.lp_id], ["Date", dB(k.notice_date)],
                    ["Value date" if kind != NoticeKind.DISTRIBUTION else "Payment date", dB(k.due_date)],
                    ["Currency", k.fund_currency]], colWidths=[28 * mm, 40 * mm])
    refbox.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), F, 8.5), ("FONT", (0, 0), (0, -1), FB, 8.5),
                                ("BOX", (0, 0), (-1, -1), 0.6, navy), ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#e8edf3"))]))
    top = Table([[addr, refbox]], colWidths=[98 * mm, 72 * mm])
    top.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    p1 = [top, Spacer(1, 10), Paragraph(f"{title} No. {n} &ndash; {k.fund_name}", h)]
    rec(1, "lp_name", "lp_id", "notice_date", "due_date", "fund_name", "fund_currency")
    p1.append(Paragraph("Dear Investor,", body))
    pct_paid = (k.lp_cum_contributions_incl / k.lp_commitment * 100).quantize(Decimal("0.01"))
    pct_s = f"{pct_paid}".replace(".", ",")
    if kind in (NoticeKind.CAPITAL_CALL, NoticeKind.COMBINED):
        p1.append(Paragraph(
            f"In accordance with clause 5.2 of the limited partnership agreement of {k.fund_name} (the "
            f"&ldquo;Partnership&rdquo;), {k.gp_name}, acting as general partner of the Partnership, hereby requests "
            f"capital contributions from the investors in an aggregate amount of {eB(k.fund_contributions_current)}. "
            f"The drawdown will finance the items set out in Annex 1, including management fees and partnership "
            f"expenses for the current period.", body))
        rec(1, "gp_name", "fund_contributions_current")
        own = ssum(cin) + ssum(cout)
        p1.append(Paragraph(
            f"Your share of this drawdown amounts to {eB(own)}. Following this drawdown, your aggregate contributions "
            f"to date will amount to {eB(k.lp_cum_contributions_incl)}, representing {pct_s} % of your commitment of "
            f"{eB(k.lp_commitment)}. Your remaining commitment will be {eB(k.lp_unfunded_incl)}.", body))
        rec(1, "lp_cum_contributions_incl", "lp_commitment", "lp_unfunded_incl")
    if kind in (NoticeKind.DISTRIBUTION, NoticeKind.COMBINED):
        p1.append(Paragraph(
            f"{'In addition, the' if kind == NoticeKind.COMBINED else 'The'} Partnership will make a distribution to "
            f"the investors in an aggregate amount of {eB(k.fund_distributions_current)}, arising from the "
            f"realisation described in Annex 1. Your share of the distribution, after any withholding, amounts to "
            f"{eB(k.lp_distributions_current)}. Aggregate distributions to you will then total "
            f"{eB(k.lp_cum_distributions_incl)}.", body))
        rec(1, "fund_distributions_current", "lp_distributions_current", "lp_cum_distributions_incl")
        if kind == NoticeKind.DISTRIBUTION:
            p1.append(Paragraph(
                f"The distribution will be paid to the bank account registered for you with the administrator, with "
                f"value date {dB(k.due_date)}. Your undrawn commitment of {eB(k.lp_unfunded_incl)} is not affected "
                f"by this notice.", body))
            rec(1, "lp_unfunded_incl")
    net = k.lp_net_called_distributed
    if kind == NoticeKind.COMBINED:
        who = "is payable by you" if net > 0 else "will be paid to you"
        p1.append(Paragraph(
            f"In accordance with clause 5.7 of the partnership agreement, the drawdown and the distribution are set "
            f"off against each other. <b>The net amount of {eB(abs(net))} {who}</b> with value date {dB(k.due_date)}.",
            body))
        rec(1, "lp_net_called_distributed")
    elif kind == NoticeKind.CAPITAL_CALL:
        p1.append(Paragraph(
            f"<b>The amount of {eB(net)} is payable by you</b> no later than {dB(k.due_date)} (value date), "
            f"using the payment instructions in Annex 2.", body))
        rec(1, "lp_net_called_distributed")
    p1.append(Paragraph(
        "Please quote the reference shown above with your payment. Contributions received after the value date bear "
        "default interest under clause 5.9 of the partnership agreement.", body))
    p1.append(Paragraph(f"Yours faithfully,<br/><br/>for and on behalf of {k.gp_name}<br/>General Partner", body))

    # ---- page 2: Annex 1 breakdown ----
    p2 = [Paragraph("Annex 1 &ndash; Breakdown of amounts", h)]
    finfo = Table([["Partnership information", ""], ["Partnership", Paragraph(k.fund_name, cell)],
                   ["General partner", k.gp_name], ["Total commitments", mB(k.fund_size)],
                   ["General partner commitment", mB(k.gp_commitment)],
                   ["Investor share of total commitments", f"{k.lp_pct_of_fund * 100:.4f}".replace(".", ",") + " %"]],
                  colWidths=[70 * mm, 100 * mm])
    finfo.setStyle(TableStyle(tstyle))
    p2 += [finfo, Spacer(1, 8)]
    rec(2, "fund_size", "gp_commitment", "lp_pct_of_fund", *(["gp_name"] if "gp_name" not in k.pages else []))
    rows = [["Item", "Classification", "Commitment", "Investor amount"]]
    if kind in (NoticeKind.CAPITAL_CALL, NoticeKind.COMBINED):
        rows.append([Paragraph("<b>Drawdown</b>", cell), "", "", ""])
        inv = [t for t in cin if t.transaction_type == T.CC_INVESTMENTS]
        fees = [t for t in cin if t.transaction_type in FEE_TYPES]
        for t in inv + fees + cout:
            cls = {T.CC_INVESTMENTS: "Investment", T.CC_MGMT_FEES: "Management fee",
                   T.CC_EXPENSES: "Partnership expense", T.CC_SUB_FACILITY: "Facility cost",
                   T.CC_WORKING_CAPITAL: "Working capital", T.CC_SUBSEQ_INTEREST: "Equalisation interest",
                   T.CC_PLACEMENT: "Placement fee"}[t.transaction_type]
            rows.append([Paragraph(t.description, cell), cls,
                         "inside" if t.inside_outside == InsideOutside.INSIDE else "outside", mB(t.lp_amount)])
            t.page = 2
        if fees:
            rows.append([Paragraph("thereof management fee and partnership expenses", cell), "", "", mB(ssum(fees))])
        rows.append([Paragraph("Total drawdown (investor)", cell), "", "", mB(ssum(cin) + ssum(cout))])
    if kind in (NoticeKind.DISTRIBUTION, NoticeKind.COMBINED):
        rows.append([Paragraph("<b>Distribution</b>", cell), "", "", ""])
        for t in dists:
            cls = {T.D_ROC_CASH: "Return of capital", T.D_GAIN_CASH: "Realised gain", T.D_INCOME: "Income",
                   T.D_DIVIDENDS: "Dividend"}[t.transaction_type]
            rows.append([Paragraph(t.description, cell), cls, "n/a", mB(t.lp_amount)])
            t.page = 2
        for t in tax:
            rows.append([Paragraph(t.description, cell), "Withholding tax", "n/a", "-" + mB(t.lp_amount)])
            t.page = 2
        rows.append([Paragraph("Net distribution (investor)", cell), "", "", mB(k.lp_distributions_current)])
    tb = Table(rows, colWidths=[72 * mm, 36 * mm, 24 * mm, 38 * mm])
    tb.setStyle(TableStyle(tstyle + [("ALIGN", (3, 0), (3, -1), "RIGHT")]))
    p2 += [tb, Spacer(1, 8)]
    fund_rows = [["Partnership totals (all investors)", ""]]
    if k.fund_contributions_current is not None:
        fund_rows.append(["Aggregate drawdown", mB(k.fund_contributions_current)])
    if k.fund_distributions_current is not None:
        fund_rows.append(["Aggregate distribution", mB(k.fund_distributions_current)])
    ft = Table(fund_rows, colWidths=[70 * mm, 100 * mm])
    ft.setStyle(TableStyle(tstyle))
    p2.append(ft)
    if cout:
        p2.append(Paragraph(f"Amounts payable outside commitment (not reducing your undrawn commitment): "
                            f"{mB(k.lp_outside_outflow_current)}.", body))
        rec(2, "lp_outside_outflow_current")
    if kind == NoticeKind.DISTRIBUTION:
        rec(2, "fund_distributions_current")

    # ---- page 3: Annex 2 capital account + payment ----
    p3 = [Paragraph("Annex 2 &ndash; Investor capital account and payment instructions", h)]
    dash = lambda v: mB(v) if v is not None else "–"  # noqa: E731
    acct = Table([
        ["Capital account (EUR)", "Amount"],
        ["Commitment", mB(k.lp_commitment)],
        ["Aggregate contributions before this notice", mB(k.lp_cum_contributions_prior)],
        ["Contribution under this notice (within commitment)", dash(k.lp_contributions_current)],
        ["Aggregate contributions to date", mB(k.lp_cum_contributions_incl)],
        ["Undrawn commitment before this notice", mB(k.lp_unfunded_prior)],
        ["Movement in undrawn commitment", mB(k.lp_unfunded_impact_current)],
        ["Undrawn commitment after this notice", mB(k.lp_unfunded_incl)],
        ["Aggregate distributions before this notice", mB(k.lp_cum_distributions_prior)],
        ["Distribution under this notice (net)", dash(k.lp_distributions_current)],
        ["Aggregate distributions to date", mB(k.lp_cum_distributions_incl)],
        ["Net amount payable / (receivable)", mB(net)],
    ], colWidths=[110 * mm, 60 * mm])
    acct.setStyle(TableStyle(tstyle + [("ALIGN", (1, 0), (1, -1), "RIGHT"), ("FONT", (0, -1), (-1, -1), FB, 8.5)]))
    p3 += [acct, Spacer(1, 10)]
    rec(3, "lp_cum_contributions_prior", "lp_contributions_current", "lp_unfunded_prior",
        "lp_unfunded_impact_current", "lp_cum_distributions_prior")
    rec(3, *[f for f in ("lp_net_called_distributed", "lp_commitment", "lp_cum_contributions_incl",
                         "lp_unfunded_incl", "lp_cum_distributions_incl") if f not in k.pages])
    if wire_payable(k):
        b = k.bank
        b.reference = ref
        pay = Table([["Payment instructions", ""], ["Beneficiary", Paragraph(b.account_name, cell)],
                     ["Bank", b.bank_name], ["IBAN", b.account_number], ["BIC", b.swift_bic],
                     ["Amount", mB(net)], ["Value date", dB(k.due_date)], ["Payment reference", b.reference]],
                    colWidths=[45 * mm, 125 * mm])
        pay.setStyle(TableStyle(tstyle + [("BOX", (0, 0), (-1, -1), 0.8, navy)]))
        p3.append(pay)
        b.page = 3
    else:
        p3.append(Paragraph("No payment is required from you. The net amount will be credited to your registered "
                            "bank account on the payment date. Changes to your bank details must be notified to the "
                            "administrator in writing, signed by authorised signatories.", body))
        k.bank = None
    legal = [
        "This notice is issued by the general partner of the Partnership, a Luxembourg special limited partnership "
        "(société en commandite spéciale) managed by an authorised alternative investment fund manager "
        "under the Luxembourg law of 12 July 2013. Capitalised terms not defined here have the meaning given in the "
        "partnership agreement.",
        "Personal data relating to investors is processed in accordance with Regulation (EU) 2016/679 (GDPR) and the "
        "privacy notice in the subscription documents. This notice is confidential and intended solely for its "
        "addressee.",
        "Figures are unaudited and may be adjusted in the next capital account statement. Nothing in this notice is "
        "tax advice; investors should consult their own advisers on the tax treatment of distributions.",
    ]
    pages = [p1, p2, p3]
    if n_pages == 4:
        p4 = [Paragraph("Important information", h)]
        p4 += [Paragraph(t, body) for t in legal]
        p4.append(Paragraph("Default and remedies", h2))
        p4.append(Paragraph(
            "If an investor fails to pay any drawdown amount by the value date, the general partner may, after a "
            "cure period of ten business days, apply the default provisions of the partnership agreement, including "
            "the suspension of distributions to the defaulting investor and the compulsory transfer of its interest.",
            body))
        pages.append(p4)
    else:
        p3.append(Spacer(1, 8))
        p3 += [Paragraph(t, small) for t in legal]

    def deco(c, d, total):
        w, hgt = A4
        c.saveState()
        c.setFillColor(navy)
        c.rect(0, hgt - 22 * mm, w, 22 * mm, stroke=0, fill=1)
        c.setFillColor(colors.white)
        c.setFont(FB, 12)
        c.drawString(20 * mm, hgt - 12 * mm, k.gp_name)
        c.setFont(F, 7.5)
        c.drawString(20 * mm, hgt - 17 * mm, "General Partner  |  15, boulevard Royal, L-2449 Luxembourg  |  R.C.S. Luxembourg B 241 117")
        c.setFillColor(colors.HexColor("#555555"))
        c.setFont(F, 7)
        c.drawString(20 * mm, 12 * mm, f"{ref}  ·  Strictly confidential")
        c.drawRightString(w - 20 * mm, 12 * mm, f"{d.page}/{total}")
        c.restoreState()

    return pages, deco, A4, (20 * mm, 20 * mm, 32 * mm, 22 * mm)


# =====================================================================
# Style C: London private-equity letter (GBP)
# =====================================================================
def dC(d):
    return f"{d.day} {d:%B %Y}"


def mC(x):
    # non-breaking spaces so a space-grouped figure never wraps across lines
    return fmt(x, "space", "£").replace(" ", "\u00a0")


def styleC(k: Notice, n: int, rec: Rec, r: random.Random):
    F, FB = SERIF_C, SERIF_C_B
    green = colors.HexColor("#234d3a")
    body = ParagraphStyle("c", fontName=F, fontSize=9.8, leading=14, spaceAfter=7)
    small = ParagraphStyle("cs", parent=body, fontSize=7.5, leading=9.5)
    h = ParagraphStyle("ch", parent=body, fontName=FB, fontSize=11.5, textColor=green, spaceAfter=8)
    cell = ParagraphStyle("cc", fontName=F, fontSize=8.8, leading=11)
    cin, cout, dists, tax = parts(k)
    is_call = k.kind == NoticeKind.CAPITAL_CALL
    wire_first = is_call and n == 1
    wire_page = 1 if wire_first else 3
    net = k.lp_net_called_distributed

    p1 = [Paragraph("PRIVATE &amp; CONFIDENTIAL", ParagraphStyle("cpc", parent=small, fontName=FB)),
          Paragraph(f"{k.lp_name}<br/>Attention: Head of Private Markets", body),
          Paragraph(dC(k.notice_date), ParagraphStyle("cr", parent=body, alignment=TA_RIGHT)),
          Paragraph("Dear Limited Partner,", body)]
    rec(1, "lp_name", "notice_date")
    word = r.choice(["Drawdown Notice", "Capital Call Notice"]) if is_call else "Notice of Distribution"
    p1.append(Paragraph(f"{k.fund_name} &ndash; {word} (your reference {k.lp_id})", h))
    rec(1, "fund_name", "lp_id")
    if is_call:
        p1.append(Paragraph(
            f"We write as manager of {k.fund_name} (the &ldquo;Fund&rdquo;) to give notice of a drawdown of "
            f"{mC(k.fund_contributions_current)} across the Fund, to finance a new investment and to meet the "
            f"management fee and partnership expenses for the period. The schedule overleaf sets out the components.",
            body))
        p1.append(Paragraph(
            f"Your share is {mC(net)}, which we ask you to remit so that it is received by {dC(k.due_date)}. "
            f"Following this drawdown, your aggregate contributions to date will be {mC(k.lp_cum_contributions_incl)} "
            f"and your undrawn commitment will stand at {mC(k.lp_unfunded_incl)}, against a commitment of "
            f"{mC(k.lp_commitment)}.", body))
        rec(1, "due_date", "lp_net_called_distributed", "lp_cum_contributions_incl", "lp_unfunded_incl",
            "lp_commitment")
        if cout:
            p1.append(Paragraph(
                f"The amount above includes {mC(k.lp_outside_outflow_current)} of items called outside "
                f"commitment (see the Schedule), which is paid in addition to, and does not draw on, your commitment.",
                body))
            rec(1, "lp_outside_outflow_current")
    else:
        p1.append(Paragraph(
            f"We are pleased to tell you that the Fund will make a distribution of "
            f"{mC(k.fund_distributions_current)} in aggregate on {dC(k.due_date)}, following the realisation "
            f"described in the schedule overleaf.", body))
        p1.append(Paragraph(
            f"Your share, after any tax withheld, is {mC(k.lp_distributions_current)}. It will be paid to the account "
            f"we hold for you on file. Aggregate distributions to you will then be {mC(k.lp_cum_distributions_incl)}. "
            f"Your undrawn commitment of {mC(k.lp_unfunded_incl)}, out of a total commitment of "
            f"{mC(k.lp_commitment)}, is unchanged.", body))
        rec(1, "lp_commitment", "fund_distributions_current", "due_date", "lp_distributions_current", "lp_cum_distributions_incl",
            "lp_unfunded_incl")
    if wire_first:
        b = k.bank
        b.reference = f"{k.lp_id} DN{n}"
        box = Table([["Payment instructions", ""], ["Amount", mC(net)], ["Value date", dC(k.due_date)],
                     ["Bank", b.bank_name], ["Sort code", b.sort_code], ["Account number", b.account_number],
                     ["SWIFT / BIC", b.swift_bic], ["Account name", Paragraph(b.account_name, cell)],
                     ["Reference", b.reference]], colWidths=[40 * mm, 110 * mm])
        box.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), F, 8.8), ("FONT", (0, 0), (-1, 0), FB, 9),
                                 ("BOX", (0, 0), (-1, -1), 1, green), ("SPAN", (0, 0), (1, 0)),
                                 ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e6efe9")),
                                 ("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5)]))
        p1 += [box, Spacer(1, 8)]
        b.page = 1
    elif is_call:
        p1.append(Paragraph("Payment instructions are on the final page of this notice.", body))
    p1.append(Paragraph("Please call your usual contact before making payment if you receive any message "
                        "suggesting a change to our bank details.", body))
    p1.append(Paragraph(f"Yours faithfully,<br/><br/>For and on behalf of<br/>{k.gp_name}", body))
    rec(1, "gp_name")

    # ---- page 2: schedule ----
    p2 = [Paragraph(f"Schedule &ndash; {word}, {dC(k.notice_date)}", h),
          Paragraph(f"Fund currency: {k.fund_currency} (pounds sterling). Fund commitments total "
                    f"{mC(k.fund_size)}, of which the general partner and its affiliates have committed "
                    f"{mC(k.gp_commitment)}. Your commitment represents {k.lp_pct_of_fund * 100:.4f}% of the Fund.",
                    body)]
    rec(2, "fund_currency", "fund_size", "gp_commitment", "lp_pct_of_fund")
    rows = [["", "Your share"]]
    bold = [0]
    if is_call:
        inv = [t for t in cin if t.transaction_type == T.CC_INVESTMENTS]
        fees = [t for t in cin if t.transaction_type in FEE_TYPES]
        for t in inv:
            rows.append([Paragraph(t.description, cell), mC(t.lp_amount)])
            t.page = 2
        bold.append(len(rows))
        rows.append(["Fees and expenses", ""])
        for t in fees:
            rows.append([Paragraph(t.description, cell), mC(t.lp_amount)])
            t.page = 2
        rows.append([Paragraph("Total fees and expenses", cell), mC(ssum(fees))])
        for t in cout:
            rows.append([Paragraph(t.description, cell), mC(t.lp_amount)])
            t.page = 2
        bold.append(len(rows))
        rows.append(["Amount payable by you", mC(net)])
        rows.append([Paragraph("Drawdown across the Fund (all partners)", cell), mC(k.fund_contributions_current)])
        rec(2, "fund_contributions_current")
    else:
        for t in dists:
            rows.append([Paragraph(t.description, cell), mC(t.lp_amount)])
            t.page = 2
        for t in tax:
            rows.append([Paragraph(t.description, cell), mC(-t.lp_amount)])
            t.page = 2
        bold.append(len(rows))
        rows.append(["Net distribution to you", mC(k.lp_distributions_current)])
        rec(2, "lp_net_called_distributed")
    tb = Table(rows, colWidths=[120 * mm, 45 * mm])
    tb.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), F, 8.8), ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                            ("LINEBELOW", (0, 0), (-1, 0), 0.6, green)] +
                           [("FONT", (0, i), (-1, i), FB, 8.8) for i in bold]))
    p2 += [tb, Spacer(1, 10), Paragraph("Your commitment", h)]
    dash = lambda v: mC(v) if v is not None else "nil"  # noqa: E731
    bal = Table([
        ["", "Before this notice", "This notice", "After this notice"],
        ["Aggregate contributions", mC(k.lp_cum_contributions_prior), dash(k.lp_contributions_current),
         mC(k.lp_cum_contributions_incl)],
        ["Aggregate distributions", mC(k.lp_cum_distributions_prior), dash(k.lp_distributions_current),
         mC(k.lp_cum_distributions_incl)],
        ["Undrawn commitment", mC(k.lp_unfunded_prior), mC(k.lp_unfunded_impact_current), mC(k.lp_unfunded_incl)],
    ], colWidths=[50 * mm, 38 * mm, 38 * mm, 38 * mm])
    bal.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), F, 8.8), ("FONT", (0, 0), (-1, 0), FB, 8.8),
                             ("ALIGN", (1, 0), (-1, -1), "RIGHT"), ("LINEBELOW", (0, 0), (-1, 0), 0.6, green),
                             ("LINEBELOW", (0, -1), (-1, -1), 0.6, green)]))
    p2.append(bal)
    rec(2, "lp_cum_contributions_prior", "lp_contributions_current", "lp_cum_distributions_prior",
        "lp_unfunded_prior", "lp_unfunded_impact_current")
    rec(2, *[f for f in ("lp_cum_contributions_incl", "lp_cum_distributions_incl", "lp_unfunded_incl")
             if f not in k.pages])
    notes = [
        "Management fees are charged half-yearly in advance in accordance with clause 8 of the limited partnership "
        "agreement. Partnership expenses include audit, legal, administration and depositary costs.",
        "This notice is given under the limited partnership agreement of the Fund, an English limited partnership "
        "registered under the Limited Partnerships Act 1907. A limited partner that fails to pay a drawdown when due "
        "may become a defaulting partner and lose part of its interest.",
        "This document is confidential. It is not an offer of, or invitation to invest in, any security, and it is "
        "not tax advice. The manager is authorised and regulated by the Financial Conduct Authority.",
    ]
    pages = [p1, p2]
    if is_call and not wire_first:
        b = k.bank
        b.reference = f"{k.lp_id} DN{n}"
        p3 = [Paragraph("Payment instructions", h),
              Paragraph(f"Please remit {mC(net)} by telegraphic transfer, for value no later than "
                        f"{dC(k.due_date)}, to the account below. Quote the reference so that we can match your "
                        f"payment.", body)]
        pay = Table([["Bank", b.bank_name], ["Sort code", b.sort_code], ["Account number", b.account_number],
                     ["SWIFT / BIC", b.swift_bic], ["Account name", Paragraph(b.account_name, cell)],
                     ["Reference", b.reference]], colWidths=[40 * mm, 110 * mm])
        pay.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), F, 9), ("FONT", (0, 0), (0, -1), FB, 9),
                                 ("GRID", (0, 0), (-1, -1), 0.4, green)]))
        p3 += [pay, Spacer(1, 12), Paragraph("Notes", h)] + [Paragraph(t, body) for t in notes]
        pages.append(p3)
        b.page = wire_page
    else:
        p2.append(Spacer(1, 10))
        p2 += [Paragraph(t, small) for t in notes]
        if not is_call:
            k.bank = None

    def deco(c, d, total):
        w, hgt = A4
        c.saveState()
        c.setFillColor(green)
        c.setFont(FB, 14)
        c.drawCentredString(w / 2, hgt - 18 * mm, k.gp_name)
        c.setFont(F, 7.5)
        c.drawCentredString(w / 2, hgt - 23 * mm, "4 St James's Square, London SW1Y 4JU  ·  +44 (0)20 7946 0321")
        c.setStrokeColor(green)
        c.line(25 * mm, hgt - 26 * mm, w - 25 * mm, hgt - 26 * mm)
        c.setFillColor(colors.black)
        c.setFont(F, 6.8)
        c.drawString(25 * mm, 13 * mm, f"{k.gp_name} is authorised and regulated by the Financial Conduct "
                                       f"Authority. Registered in England and Wales.")
        c.drawRightString(w - 25 * mm, 13 * mm, f"{d.page} of {total}")
        c.restoreState()

    return pages, deco, A4, (25 * mm, 25 * mm, 34 * mm, 24 * mm)


# =====================================================================
def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    plan = [
        (1, make_fund(111, "USD"), dict(seed=211, n=3), styleA),
        (2, make_fund(112, "EUR"), dict(seed=212, n=4, kinds=[NoticeKind.CAPITAL_CALL, NoticeKind.COMBINED,
                                                             NoticeKind.CAPITAL_CALL, NoticeKind.DISTRIBUTION]), styleB),
        (3, make_fund(113, "GBP"), dict(seed=213, n=3), styleC),
    ]
    results = []
    for fi, fund, sargs, style in plan:
        for i, key in enumerate(make_sequence(fund, **sargs), start=1):
            name = f"b_fund{fi}_n{i}"
            key.source_file = f"{name}.pdf"
            rec = Rec(key)
            pages, deco, size, margins = style(key, i, rec, random.Random(fi * 100 + i))
            pdf = OUT / f"{name}.pdf"
            build(pdf, pages, size, margins, deco)
            rec.check()
            write_key(key, OUT / f"{name}.json")
            probs = verify_pdf(pdf, key)
            n_pg = len(page_texts(pdf))
            if n_pg != len(pages):
                probs.append(f"rendered {n_pg} pages, expected {len(pages)} (overflow)")
            results.append((name, key.kind.value, n_pg, probs))
    bad = 0
    for name, kind, n_pg, probs in results:
        print(f"{name:14s} {kind:14s} {n_pg} pages  {'OK' if not probs else 'FAIL'}")
        for p in probs:
            print(f"    - {p}")
        bad += bool(probs)
    print(f"{len(results)} documents, {bad} with problems -> {OUT}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
