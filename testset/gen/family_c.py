"""Layout family C (held-out): multi-currency, recallable distributions, subsequent-close (equalisation)
interest, capital account statements.

Three house styles, none of them a plain admin table:
- Luxembourg SCSp administrator (EUR): landscape, bilingual FR/EN, two-column label/value grid,
  amounts 1.234.567,89, dates 14.01.2025.
- US (USD): cover letter plus a dense "Investor Allocation Schedule" with fund totals and LP share side by
  side, negatives in parentheses, dates January 14, 2025.
- UK (GBP): prose cover letter with annexes, amounts £1,234,567.89, dates 14th January 2025.

Plus a hand-made key for ILPA's own sample description letter (page 10 of the 2025 PDF).

Number layout note: verify_pdf's number reader treats "1,000.00 2,000.00" (two numbers split only by a
space) as one token, so every amount in a table cell carries a currency code or symbol in front.

Run: .venv/bin/python testset/gen/family_c.py
"""
from __future__ import annotations

import shutil
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

from reportlab.lib.pagesizes import A4, LETTER, landscape
from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen import canvas

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (  # noqa: E402
    ROOT, BankDetails, InsideOutside, Notice, NoticeKind, T, fmt, make_fund, make_sequence, q, verify_pdf,
    write_key,
)

OUT = ROOT / "testset" / "build" / "family_c"
K = NoticeKind
RECALL_SHARE = Decimal("0.5")
CLAUSE = "clause 4.6"

CONFIG = [  # (fund seed, currency, sequence seed, kinds, style)
    (121, "EUR", 221, [K.CAPITAL_CALL, K.DISTRIBUTION, K.CAPITAL_ACCOUNT_STATEMENT], "lux"),
    (122, "USD", 222, [K.DISTRIBUTION, K.CAPITAL_CALL, K.CAPITAL_CALL], "us"),
    (123, "GBP", 223, [K.CAPITAL_CALL, K.CAPITAL_ACCOUNT_STATEMENT, K.DISTRIBUTION], "uk"),
]


# ---------------------------------------------------------------- page writer
class Doc:
    """Thin canvas wrapper that knows the current page and records where each key field is printed."""

    def __init__(self, path: Path, size, key: Notice, font="Helvetica"):
        self.c = canvas.Canvas(str(path), pagesize=size)
        self.c.setTitle(key.fund_name)
        self.w, self.h = size
        self.key = key
        self.page = 1
        self.font = font

    def rec(self, *fields):
        for f in fields:
            if getattr(self.key, f) is not None:
                self.key.pages.setdefault(f, self.page)

    def t(self, x, y, s, size=9, bold=False, right=False, fields=()):
        self.c.setFont(self.font + ("-Bold" if bold else ""), size)
        (self.c.drawRightString if right else self.c.drawString)(x, y, s)
        self.rec(*fields)

    def para(self, x, y, s, width, size=10, lead=14, fields=()):
        self.c.setFont(self.font, size)
        lines = simpleSplit(s, self.font, size, width)
        for ln in lines:
            self.c.drawString(x, y, ln)
            y -= lead
        self.rec(*fields)
        return y - 4

    def rule(self, x0, y, x1, width=0.5):
        self.c.setLineWidth(width)
        self.c.line(x0, y, x1, y)

    def new_page(self):
        self.c.showPage()
        self.page += 1

    def save(self):
        self.c.save()


def tx_page(doc: Doc, tx):
    tx.page = doc.page


def bank_page(doc: Doc):
    doc.key.bank.page = doc.page


def cat(t) -> str:
    return t.transaction_type.value.split(": ", 1)[1].split(" (")[0]


def recallable_amt(key: Notice) -> Decimal:
    return sum((q(t.lp_amount * RECALL_SHARE) for t in key.transactions if t.recallable), Decimal(0))


def roc_amt(key: Notice) -> Decimal:
    return sum((t.lp_amount for t in key.transactions if t.recallable), Decimal(0))


def has_sci(key: Notice) -> bool:
    return any(t.transaction_type == T.CC_SUBSEQ_INTEREST for t in key.transactions)


def fund_shares(key: Notice, total: Decimal | None, kinds_prefix: str) -> dict[int, Decimal]:
    """Fund-level amount for each inside-commitment line, adjusted so the lines add to the key's fund total."""
    idx = [i for i, t in enumerate(key.transactions)
           if t.inside_outside == InsideOutside.INSIDE and t.transaction_type.value.startswith(kinds_prefix)]
    out = {i: q(key.transactions[i].lp_amount / key.lp_pct_of_fund) for i in idx}
    if total is not None and idx:
        sign = {i: (-1 if key.transactions[i].transaction_type == T.D_TAX_WITHHELD else 1) for i in idx}
        diff = total - sum(out[i] * sign[i] for i in idx)
        out[idx[0]] += diff * sign[idx[0]]
    return out


# ---------------------------------------------------------------- style (i): Luxembourg SCSp, EUR
def eur(x: Decimal) -> str:
    return f"EUR {fmt(x, 'eu')}"


def d_lux(d: date) -> str:
    return d.strftime("%d.%m.%Y")


ADMIN_LU = "Rhin Fund Services S.à r.l."


def lux_header(doc: Doc, title_fr: str, title_en: str, number: int):
    k = doc.key
    doc.c.setFillGray(0.92)
    doc.c.rect(0, doc.h - 62, doc.w, 62, fill=1, stroke=0)
    doc.c.setFillGray(0)
    doc.t(36, doc.h - 28, ADMIN_LU, 11, bold=True)
    doc.t(36, doc.h - 42, "Administrateur central / Central administration agent  -  6, rue Eugène Ruppert, "
          "L-2453 Luxembourg", 7.5)
    doc.t(doc.w - 36, doc.h - 28, f"{title_fr} / {title_en}", 11, bold=True, right=True)
    doc.t(doc.w - 36, doc.h - 42, f"Réf. {k.lp_id}-{number:02d}  -  page {doc.page}", 7.5, right=True)


def lux_grid(doc: Doc, x, y, rows, label_w=190, col_w=360, lead=17):
    for lab, val, fields in rows:
        doc.t(x, y, lab, 8)
        doc.t(x + label_w, y, val, 9, bold=True, fields=fields)
        doc.c.setStrokeGray(0.8)
        doc.rule(x, y - 5, x + col_w - 15)
        doc.c.setStrokeGray(0)
        y -= lead
    return y


def lux_identity_rows(k: Notice, date_label: str):
    rows = [("Fonds / Fund", k.fund_name, ("fund_name",)),
            ("Associé commandité / General Partner", k.gp_name, ("gp_name",)),
            ("Investisseur / Investor", k.lp_name, ("lp_name",)),
            ("N° investisseur / Investor number", k.lp_id, ("lp_id",)),
            (date_label, d_lux(k.notice_date), ("notice_date",))]
    if k.due_date:
        rows.append(("Date de valeur / Value date", d_lux(k.due_date), ("due_date",)))
    rows.append(("Devise / Currency", k.fund_currency, ("fund_currency",)))
    return rows


def lux_bank(doc: Doc, x, y, heading):
    b = doc.key.bank
    doc.t(x, y, heading, 10, bold=True)
    y -= 20
    rows = [("Banque / Bank", b.bank_name), ("Bénéficiaire / Beneficiary", b.account_name),
            ("IBAN", b.account_number), ("BIC / SWIFT", b.swift_bic)]
    if b.sort_code:
        rows.append(("Code banque / Bank code", b.sort_code))
    rows.append(("Communication", f"{doc.key.lp_id} {doc.key.fund_name}"))
    y = lux_grid(doc, x, y, [(a, v, ()) for a, v in rows])
    bank_page(doc)
    return y


def lux_reconciliation(doc: Doc, x, y, after=True):
    k = doc.key
    doc.t(x, y, "Situation de l'engagement / Commitment position", 10, bold=True)
    y -= 20
    rows = [("Apports cumulés avant / Contributions before", eur(k.lp_cum_contributions_prior),
             ("lp_cum_contributions_prior",)),
            ("Distributions cumulées avant / Distributions before", eur(k.lp_cum_distributions_prior),
             ("lp_cum_distributions_prior",)),
            ("Non appelé avant / Unfunded before", eur(k.lp_unfunded_prior), ("lp_unfunded_prior",)),
            ("Variation du non appelé / Change in unfunded", eur(k.lp_unfunded_impact_current),
             ("lp_unfunded_impact_current",)),
            ("Non appelé après / Unfunded after", eur(k.lp_unfunded_incl), ("lp_unfunded_incl",)),
            ("Apports cumulés après / Contributions after", eur(k.lp_cum_contributions_incl),
             ("lp_cum_contributions_incl",)),
            ("Distributions cumulées après / Distributions after", eur(k.lp_cum_distributions_incl),
             ("lp_cum_distributions_incl",))]
    if k.lp_recallable_balance is not None:
        rows.append(("Solde rappelable / Recallable balance", eur(k.lp_recallable_balance),
                     ("lp_recallable_balance",)))
    return lux_grid(doc, x, y, rows, label_w=230, col_w=380)


def lux_breakdown(doc: Doc, x, y):
    k = doc.key
    doc.t(x, y, "Annexe 1 - Ventilation / Breakdown", 10, bold=True)
    y -= 18
    cols = [x, x + 300, x + 470, x + 560, x + 760]
    heads = ["Description", "Catégorie / Category", "Engagement", "Non appelé / Unfunded", "Montant / Amount"]
    for i, hd in enumerate(heads):
        doc.t(cols[i], y, hd, 7.5, bold=True, right=(i == 4))
    doc.rule(x, y - 4, x + 760)
    y -= 16
    for t in k.transactions:
        io = "dans / inside" if t.inside_outside == InsideOutside.INSIDE else "hors / outside"
        doc.t(cols[0], y, t.description, 8)
        doc.t(cols[1], y, cat(t), 8)
        doc.t(cols[2], y, io, 8)
        doc.t(cols[3], y, t.impact_on_unfunded.value, 8)
        doc.t(cols[4], y, eur(-t.lp_amount if t.transaction_type == T.D_TAX_WITHHELD else t.lp_amount), 8,
              right=True)
        tx_page(doc, t)
        y -= 14
    doc.rule(x, y + 8, x + 760)
    return y - 6


def render_lux(key: Notice, path: Path, number: int):
    doc = Doc(path, landscape(A4), key)
    k = key
    if k.kind == K.CAPITAL_ACCOUNT_STATEMENT:
        lux_header(doc, "Relevé de compte de capital", "Capital Account Statement", number)
        doc.t(36, doc.h - 90, f"Relevé trimestriel au {d_lux(k.notice_date)} / Quarterly statement as at "
              f"{d_lux(k.notice_date)}", 12, bold=True, fields=("notice_date",))
        y = lux_grid(doc, 36, doc.h - 120, lux_identity_rows(k, "Date de clôture / Period end"))
        right = [("Taille du fonds / Fund size", eur(k.fund_size), ("fund_size",)),
                 ("Engagement du commandité / GP commitment", eur(k.gp_commitment), ("gp_commitment",)),
                 ("Engagement / Commitment", eur(k.lp_commitment), ("lp_commitment",)),
                 ("Quote-part / Share of fund", f"{k.lp_pct_of_fund * 100:.4f}%", ("lp_pct_of_fund",))]
        lux_grid(doc, 430, doc.h - 120, right, label_w=210, col_w=380)
        y = min(y, doc.h - 200) - 20
        doc.t(36, y, "Compte de capital de l'associé / Partner capital account", 10, bold=True)
        y -= 18
        cols = [36, 380, 540, 700]
        for i, hd in enumerate(["", "Ouverture / Opening", "Période / Period", "Clôture / Closing"]):
            doc.t(cols[i] + (120 if i else 0), y, hd, 8, bold=True, right=bool(i))
        doc.rule(36, y - 4, 820)
        y -= 16
        z = Decimal("0.00")
        lines = [("Apports / Contributions", k.lp_cum_contributions_prior, z, k.lp_cum_contributions_incl,
                  ("lp_cum_contributions_prior", "lp_cum_contributions_incl")),
                 ("Distributions", k.lp_cum_distributions_prior, z, k.lp_cum_distributions_incl,
                  ("lp_cum_distributions_prior", "lp_cum_distributions_incl")),
                 ("Engagement non appelé / Unfunded commitment", k.lp_unfunded_prior,
                  k.lp_unfunded_impact_current, k.lp_unfunded_incl,
                  ("lp_unfunded_prior", "lp_unfunded_impact_current", "lp_unfunded_incl"))]
        for lab, a, b, c, fields in lines:
            doc.t(cols[0], y, lab, 8.5)
            doc.t(cols[1] + 120, y, eur(a), 8.5, right=True)
            doc.t(cols[2] + 120, y, eur(b), 8.5, right=True)
            doc.t(cols[3] + 120, y, eur(c), 8.5, right=True, fields=fields)
            y -= 15
        doc.rule(36, y + 9, 820)
        y -= 8
        doc.t(36, y, "Mouvement net de trésorerie de la période / Net cash movement in period", 8.5)
        doc.t(820, y, eur(k.lp_net_called_distributed), 8.5, right=True, fields=("lp_net_called_distributed",))
        y -= 15
        if k.lp_recallable_balance is not None:
            doc.t(36, y, f"Solde rappelable / Recallable balance under {CLAUSE} of the LPA", 8.5)
            doc.t(820, y, eur(k.lp_recallable_balance), 8.5, right=True, fields=("lp_recallable_balance",))
        doc.new_page()
        lux_header(doc, "Relevé de compte de capital", "Capital Account Statement", number)
        y = doc.para(36, doc.h - 95, "Ce relevé est établi sur la base des livres non audités du fonds. Les "
                     "montants rappelables restent disponibles pour un nouvel appel conformément au contrat de "
                     "société. / This statement is prepared from the unaudited books of the fund. Recallable "
                     "amounts remain available to be drawn again under the limited partnership agreement.", 760)
        lux_bank(doc, 36, y - 10, "Compte du fonds / Fund account")
        doc.save()
        return

    is_call = k.kind == K.CAPITAL_CALL
    title = ("Avis d'appel de fonds", "Drawdown Notice") if is_call else ("Avis de distribution",
                                                                          "Distribution Notice")
    lux_header(doc, *title, number)
    doc.t(36, doc.h - 90, f"{title[1]} No. {number}", 12, bold=True)
    y = lux_grid(doc, 36, doc.h - 120, lux_identity_rows(k, "Date de l'avis / Notice date"))
    right = [("Taille du fonds / Fund size", eur(k.fund_size), ("fund_size",)),
             ("Engagement du commandité / GP commitment", eur(k.gp_commitment), ("gp_commitment",)),
             ("Engagement / Commitment", eur(k.lp_commitment), ("lp_commitment",)),
             ("Quote-part / Share of fund", f"{k.lp_pct_of_fund * 100:.4f}%", ("lp_pct_of_fund",))]
    if is_call:
        right += [("Appel total du fonds / Total fund drawdown", eur(k.fund_contributions_current),
                   ("fund_contributions_current",)),
                  ("Votre quote-part / Your share", eur(k.lp_contributions_current),
                   ("lp_contributions_current",))]
        if k.lp_outside_outflow_current:
            right.append(("Hors engagement / Outside commitment", eur(k.lp_outside_outflow_current),
                          ("lp_outside_outflow_current",)))
        right.append(("Montant à verser / Amount payable", eur(k.lp_net_called_distributed),
                      ("lp_net_called_distributed",)))
    else:
        right += [("Distribution totale / Total fund distribution", eur(k.fund_distributions_current),
                   ("fund_distributions_current",)),
                  ("Votre quote-part nette / Your net share", eur(k.lp_distributions_current),
                   ("lp_distributions_current",)),
                  ("Mouvement net / Net movement", eur(k.lp_net_called_distributed),
                   ("lp_net_called_distributed",))]
    lux_grid(doc, 430, doc.h - 120, right, label_w=210, col_w=380)
    y = min(y, doc.h - 270) - 15
    if is_call:
        txt = (f"Conformément au contrat de société en commandite spéciale, le commandité appelle la somme de "
               f"{eur(k.lp_net_called_distributed)} à verser au plus tard le {d_lux(k.due_date)}. / Under the "
               f"special limited partnership agreement, the General Partner calls "
               f"{eur(k.lp_net_called_distributed)}, payable by {d_lux(k.due_date)}.")
        if has_sci(k):
            txt += (" Ce montant comprend des intérêts d'égalisation (closing ultérieur) payés hors engagement. / "
                    "It includes subsequent-close equalisation interest paid outside commitment.")
    else:
        txt = (f"Le commandité distribue {eur(k.lp_distributions_current)} net, versés le {d_lux(k.due_date)} sur "
               f"votre compte enregistré. Le remboursement de capital s'élève à {eur(roc_amt(k))}, dont "
               f"{eur(recallable_amt(k))} est rappelable selon la {CLAUSE} du contrat. / The return of capital is "
               f"{eur(roc_amt(k))}, of which {eur(recallable_amt(k))} is recallable under {CLAUSE} of the LPA and "
               f"is added back to your unfunded commitment.")
    doc.para(36, y, txt, 770, size=9, lead=12)

    doc.new_page()
    lux_header(doc, *title, number)
    y = lux_breakdown(doc, 36, doc.h - 95)
    lux_reconciliation(doc, 36, y - 10)

    doc.new_page()
    lux_header(doc, *title, number)
    if is_call:
        y = doc.para(36, doc.h - 95, f"Instructions de paiement / Payment instructions. Veuillez virer "
                     f"{eur(k.lp_net_called_distributed)} en date de valeur {d_lux(k.due_date)} sur le compte "
                     "suivant, sans frais pour le bénéficiaire.", 760)
        lux_bank(doc, 36, y - 10, "Compte de réception / Receiving account")
    else:
        y = doc.para(36, doc.h - 95, "Le produit sera versé sur votre compte enregistré / Proceeds will be paid "
                     "to your account on file. Tout rappel ultérieur des montants rappelables sera à verser sur le "
                     "compte du fonds ci-dessous.", 760)
        lux_bank(doc, 36, y - 10, "Compte du fonds / Fund account")
    doc.save()


# ---------------------------------------------------------------- style (ii): US allocation schedule, USD
def usd(x: Decimal) -> str:
    return fmt(x, "paren", "$")


def d_us(d: date) -> str:
    return f"{d:%B} {d.day}, {d.year}"


def us_letterhead(doc: Doc, title: str):
    k = doc.key
    doc.t(50, doc.h - 50, k.gp_name.upper(), 14, bold=True)
    doc.t(50, doc.h - 64, "General Partner  |  401 Park Avenue South, New York, NY 10016  |  investor.relations@"
          "example.com", 7.5)
    doc.rule(50, doc.h - 72, doc.w - 50, 1.2)
    doc.t(doc.w - 50, doc.h - 50, title, 11, bold=True, right=True)


def render_us(key: Notice, path: Path, number: int):
    doc = Doc(path, LETTER, key)
    k = key
    is_call = k.kind == K.CAPITAL_CALL
    title = f"{'CAPITAL CALL' if is_call else 'DISTRIBUTION'} NOTICE #{number}"
    us_letterhead(doc, title)
    y = doc.h - 100
    doc.t(50, y, d_us(k.notice_date), 10, fields=("notice_date",))
    y -= 22
    doc.t(50, y, "To:", 10, bold=True)
    doc.t(90, y, k.lp_name, 10, fields=("lp_name",))
    y -= 14
    doc.t(90, y, f"Investor ID {k.lp_id}", 10, fields=("lp_id",))
    y -= 14
    doc.t(50, y, "Re:", 10, bold=True)
    doc.t(90, y, k.fund_name, 10, bold=True, fields=("fund_name",))
    y -= 28
    if is_call:
        txt = (f"{k.gp_name}, as general partner of {k.fund_name} (the \"Fund\"), hereby calls capital from the "
               f"limited partners as set out in the attached Investor Allocation Schedule. Your share of the call "
               f"is {usd(k.lp_net_called_distributed)}, due on {d_us(k.due_date)}.")
        doc.rec("gp_name", "lp_net_called_distributed", "due_date")
        y = doc.para(50, y, txt, doc.w - 100)
        if has_sci(k):
            sci = sum(t.lp_amount for t in k.transactions if t.transaction_type == T.CC_SUBSEQ_INTEREST)
            y = doc.para(50, y, f"Because you were admitted at a subsequent closing, the amount due includes "
                         f"{usd(sci)} of subsequent close interest. This interest is paid outside your commitment "
                         "and does not reduce your unfunded commitment.", doc.w - 100)
        y = doc.para(50, y, "Please wire immediately available funds to the account below, quoting your "
                     "investor ID. Do not rely on wiring instructions received by e-mail without calling us to "
                     "confirm them.", doc.w - 100)
        heading = "WIRE INSTRUCTIONS"
    else:
        txt = (f"{k.gp_name}, as general partner of {k.fund_name} (the \"Fund\"), is pleased to make the "
               f"distribution set out in the attached Investor Allocation Schedule. Your net distribution of "
               f"{usd(k.lp_distributions_current)} will be paid to your account on file on {d_us(k.due_date)}.")
        doc.rec("gp_name", "lp_distributions_current", "due_date")
        y = doc.para(50, y, txt, doc.w - 100)
        y = doc.para(50, y, f"The distribution includes a return of capital of {usd(roc_amt(k))}, of which "
                     f"{usd(recallable_amt(k))} is recallable under {CLAUSE} of the Partnership Agreement and is "
                     "added back to your unfunded commitment.", doc.w - 100)
        heading = "FUND ACCOUNT (for any future recall of recallable capital)"
    y -= 6
    doc.t(50, y, heading, 9, bold=True)
    y -= 16
    b = k.bank
    rows = [("Bank", b.bank_name), ("ABA routing", b.sort_code), ("SWIFT", b.swift_bic),
            ("Account name", b.account_name), ("Account no.", b.account_number),
            ("Reference", f"{k.lp_id} / Notice #{number}")]
    for lab, val in rows:
        if val:
            doc.t(60, y, lab, 9)
            doc.t(170, y, val, 9, bold=True)
            y -= 13
    bank_page(doc)
    y -= 20
    doc.t(50, y, "Very truly yours,", 10)
    doc.t(50, y - 30, f"{k.gp_name}, General Partner", 10)
    doc.t(50, 40, f"Currency of the Fund: {k.fund_currency}. All amounts in US dollars.", 7.5,
          fields=("fund_currency",))

    doc.new_page()
    us_letterhead(doc, "INVESTOR ALLOCATION SCHEDULE")
    y = doc.h - 95
    doc.t(50, y, f"{k.fund_name}  |  {k.lp_name}  |  {k.lp_id}  |  Notice #{number}  |  {d_us(k.notice_date)}",
          7.5)
    y -= 20
    # dense line-item table: fund total and LP share side by side
    cols = [50, 70, 205, 300, 335, 470, 562]
    heads = ["Line", "Description", "Category", "In/Out", "Unfunded", "Total Fund", "Investor Share"]
    doc.c.setFillGray(0.9)
    doc.c.rect(48, y - 4, doc.w - 96, 13, fill=1, stroke=0)
    doc.c.setFillGray(0)
    for i, hd in enumerate(heads):
        doc.t(cols[i], y, hd, 7, bold=True, right=(i >= 5))
    y -= 14
    prefix = "Capital Call" if is_call else "Distribution"
    fund_line = fund_shares(k, k.fund_contributions_current if is_call else k.fund_distributions_current, prefix)
    for i, t in enumerate(k.transactions):
        # calls are cash from the LP (positive); distributions are cash to the LP (negative);
        # tax withheld reduces the distribution, so it shows as positive
        sign = 1 if is_call or t.transaction_type == T.D_TAX_WITHHELD else -1
        lp_v = t.lp_amount * sign
        doc.t(cols[0], y, f"{i + 1:02d}", 7)
        desc = t.description if len(t.description) <= 34 else t.description[:32] + "..."
        doc.t(cols[1], y, desc, 7)
        doc.t(cols[2], y, cat(t)[:26], 7)
        doc.t(cols[3], y, t.inside_outside.value, 7)
        doc.t(cols[4], y, t.impact_on_unfunded.value, 7)
        doc.t(cols[5], y, usd(fund_line[i] * sign) if i in fund_line else "n/a", 7, right=True)
        doc.t(cols[6], y, usd(lp_v), 7, right=True)
        tx_page(doc, t)
        y -= 11
    doc.rule(50, y + 7, cols[6])
    y -= 4
    if any(len(t.description) > 34 for t in k.transactions):
        y -= 2
        for i, t in enumerate(k.transactions):
            if len(t.description) > 34:
                doc.t(70, y, f"Line {i + 1:02d}: {t.description}", 6.5)
                y -= 9
    y -= 14
    doc.t(50, y, "SUMMARY", 8, bold=True)
    doc.t(cols[5], y, "Total Fund", 7, bold=True, right=True)
    doc.t(cols[6], y, "Investor Share", 7, bold=True, right=True)
    y -= 12

    def row(label, fund_v, lp_v, ffields=(), lfields=()):
        nonlocal y
        doc.t(50, y, label, 7.5)
        if fund_v is not None:
            doc.t(cols[5], y, fund_v, 7.5, right=True, fields=ffields)
        if lp_v is not None:
            doc.t(cols[6], y, lp_v, 7.5, right=True, fields=lfields)
        y -= 11

    row("Commitment", usd(k.fund_size), usd(k.lp_commitment), ("fund_size",), ("lp_commitment",))
    row("  of which General Partner commitment", usd(k.gp_commitment), None, ("gp_commitment",))
    row("Ownership percentage", "100.0000%", f"{k.lp_pct_of_fund * 100:.4f}%", (), ("lp_pct_of_fund",))
    if is_call:
        row("Contributions this notice (inside commitment)", usd(k.fund_contributions_current),
            usd(k.lp_contributions_current), ("fund_contributions_current",), ("lp_contributions_current",))
        if k.lp_outside_outflow_current:
            row("Amounts outside commitment this notice", None, usd(k.lp_outside_outflow_current), (),
                ("lp_outside_outflow_current",))
    else:
        row("Net distributions this notice", usd(-k.fund_distributions_current),
            usd(-k.lp_distributions_current), ("fund_distributions_current",), ("lp_distributions_current",))
    row("Net amount due from / (to) investor", None, usd(k.lp_net_called_distributed), (),
        ("lp_net_called_distributed",))
    y -= 10
    doc.t(50, y, "INVESTOR COMMITMENT ROLL-FORWARD", 8, bold=True)
    doc.t(cols[4] - 20, y, "Prior", 7, bold=True, right=True)
    doc.t(cols[5], y, "This Notice", 7, bold=True, right=True)
    doc.t(cols[6], y, "Including Notice", 7, bold=True, right=True)
    y -= 12
    for label, a, b_, c, fa, fc in [
        ("Cumulative contributions", k.lp_cum_contributions_prior, k.lp_contributions_current,
         k.lp_cum_contributions_incl, "lp_cum_contributions_prior", "lp_cum_contributions_incl"),
        ("Cumulative distributions", k.lp_cum_distributions_prior, k.lp_distributions_current,
         k.lp_cum_distributions_incl, "lp_cum_distributions_prior", "lp_cum_distributions_incl"),
        ("Unfunded commitment", k.lp_unfunded_prior, k.lp_unfunded_impact_current, k.lp_unfunded_incl,
         "lp_unfunded_prior", "lp_unfunded_incl")]:
        doc.t(50, y, label, 7.5)
        doc.t(cols[4] - 20, y, usd(a), 7.5, right=True, fields=(fa,))
        doc.t(cols[5], y, usd(b_) if b_ is not None else "-", 7.5, right=True,
              fields=("lp_unfunded_impact_current",) if label.startswith("Unfunded") else ())
        doc.t(cols[6], y, usd(c), 7.5, right=True, fields=(fc,))
        y -= 11
    if k.lp_recallable_balance is not None:
        doc.t(50, y, f"Recallable distributions available for recall ({CLAUSE})", 7.5)
        doc.t(cols[6], y, usd(k.lp_recallable_balance), 7.5, right=True, fields=("lp_recallable_balance",))
        y -= 11
    y -= 14
    doc.para(50, y, "Negative amounts are shown in parentheses. Distributions are shown as negative cash flows "
             "to the investor. Fund totals are allocated pro rata to commitments; amounts outside commitment "
             "(subsequent close interest, placement fees) are charged only to the investors concerned.",
             doc.w - 100, size=7, lead=9)
    doc.save()


# ---------------------------------------------------------------- style (iii): UK prose letter + annexes, GBP
def gbp(x: Decimal) -> str:
    return fmt(x, "paren", "£")


def d_uk(d: date) -> str:
    suf = "th" if 11 <= d.day % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(d.day % 10, "th")
    return f"{d.day}{suf} {d:%B %Y}"


def uk_head(doc: Doc, annex: str | None = None):
    k = doc.key
    doc.c.setFont("Times-Bold", 13)
    doc.c.drawCentredString(doc.w / 2, doc.h - 50, k.gp_name)
    doc.c.setFont("Times-Roman", 8)
    doc.c.drawCentredString(doc.w / 2, doc.h - 63, "Authorised and regulated by the Financial Conduct Authority  "
                            "-  10 Grosvenor Street, London W1K 4QB")
    doc.rule(60, doc.h - 70, doc.w - 60)
    if annex:
        doc.t(60, doc.h - 95, annex, 12, bold=True)
    doc.c.setFont("Times-Italic", 8)
    doc.c.drawCentredString(doc.w / 2, 30, f"Private and confidential  -  page {doc.page}")


def uk_table(doc: Doc, y, header, rows, xs=(60, 330, 430, 535)):
    for i, hd in enumerate(header):
        doc.t(xs[i], y, hd, 9, bold=True, right=(i > 0))
    doc.rule(60, y - 4, 535)
    y -= 16
    for r in rows:
        label, vals, fields = r
        doc.t(xs[0], y, label, 9.5)
        for j, v in enumerate(vals):
            if v is not None:
                doc.t(xs[len(header) - len(vals) + j], y, v, 9.5, right=True)
        doc.rec(*fields)
        y -= 15
    doc.rule(60, y + 10, 535)
    return y - 10


def uk_capital_account(doc: Doc, y, heading="Annex B - Your capital account"):
    k = doc.key
    doc.t(60, y, heading, 12, bold=True)
    y -= 24
    z = Decimal("0.00")
    rows = [("Contributions", [gbp(k.lp_cum_contributions_prior), gbp(k.lp_contributions_current or z),
                               gbp(k.lp_cum_contributions_incl)],
             ("lp_cum_contributions_prior", "lp_cum_contributions_incl")),
            ("Distributions", [gbp(k.lp_cum_distributions_prior), gbp(k.lp_distributions_current or z),
                               gbp(k.lp_cum_distributions_incl)],
             ("lp_cum_distributions_prior", "lp_cum_distributions_incl")),
            ("Undrawn commitment", [gbp(k.lp_unfunded_prior), gbp(k.lp_unfunded_impact_current),
                                    gbp(k.lp_unfunded_incl)],
             ("lp_unfunded_prior", "lp_unfunded_impact_current", "lp_unfunded_incl"))]
    y = uk_table(doc, y, ["", "Brought forward", "Movement", "Carried forward"], rows, xs=(60, 330, 430, 535))
    if k.lp_recallable_balance is not None:
        doc.t(60, y, f"Recallable distributions (available to be drawn again under {CLAUSE})", 9.5)
        doc.t(535, y, gbp(k.lp_recallable_balance), 9.5, right=True, fields=("lp_recallable_balance",))
        y -= 15
    doc.t(60, y, "Commitment", 9.5)
    doc.t(535, y, gbp(k.lp_commitment), 9.5, right=True, fields=("lp_commitment",))
    y -= 15
    doc.t(60, y, "Partnership commitments (of which General Partner commitment)", 9.5)
    doc.t(535, y, f"{gbp(k.fund_size)} ({gbp(k.gp_commitment)})", 9.5, right=True,
          fields=("fund_size", "gp_commitment"))
    return y - 25


def uk_bank(doc: Doc, y, heading):
    b = doc.key.bank
    doc.t(60, y, heading, 11, bold=True)
    y -= 20
    for lab, val in [("Bank", b.bank_name), ("Account name", b.account_name), ("Sort code", b.sort_code),
                     ("Account number", b.account_number), ("SWIFT/BIC", b.swift_bic),
                     ("Payment reference", f"{doc.key.lp_id}")]:
        if val:
            doc.t(80, y, lab, 9.5)
            doc.t(220, y, val, 9.5, bold=True)
            y -= 14
    bank_page(doc)
    return y - 10


def render_uk(key: Notice, path: Path, number: int):
    doc = Doc(path, A4, key, font="Times-Roman")
    doc.font = "Times"  # Times-Roman / Times-Bold
    k = key
    W = doc.w - 120

    def T_(x, y, s, size=10.5, bold=False, right=False, fields=()):
        doc.c.setFont("Times-Bold" if bold else "Times-Roman", size)
        (doc.c.drawRightString if right else doc.c.drawString)(x, y, s)
        doc.rec(*fields)

    doc.t = T_  # Times faces have different names from Helvetica's

    def P(y, s, fields=()):
        doc.c.setFont("Times-Roman", 10.5)
        for ln in simpleSplit(s, "Times-Roman", 10.5, W):
            doc.c.drawString(60, y, ln)
            y -= 14
        doc.rec(*fields)
        return y - 7

    uk_head(doc)
    y = doc.h - 100
    doc.t(doc.w - 60, y, d_uk(k.notice_date), right=True, fields=("notice_date",))
    doc.t(60, y, k.lp_name, bold=True, fields=("lp_name",))
    doc.t(60, y - 14, f"Investor reference: {k.lp_id}", fields=("lp_id",))
    y -= 44
    doc.t(60, y, "Dear Limited Partner,")
    y -= 22
    if k.kind == K.CAPITAL_ACCOUNT_STATEMENT:
        doc.t(60, y, f"{k.fund_name} - Quarterly capital account statement", bold=True, fields=("fund_name",))
        y -= 22
        y = P(y, f"We enclose your partner capital account statement for {k.fund_name} for the quarter ended "
              f"{d_uk(k.notice_date)}, prepared by {k.gp_name} as manager. No drawdown or distribution was made "
              f"in the quarter, so your net cash movement for the period was {gbp(k.lp_net_called_distributed)}.",
              ("gp_name", "lp_net_called_distributed"))
        y = P(y, f"At the quarter end your commitment of {gbp(k.lp_commitment)} represented a "
              f"{k.lp_pct_of_fund * 100:.4f}% interest in the Partnership, and your undrawn commitment stood at "
              f"{gbp(k.lp_unfunded_incl)}. Amounts are stated in pounds sterling ({k.fund_currency}).",
              ("lp_pct_of_fund", "fund_currency"))
        if k.lp_recallable_balance is not None:
            y = P(y, f"Of the distributions you have received, {gbp(k.lp_recallable_balance)} is recallable "
                  f"under {CLAUSE} of the Limited Partnership Agreement.")
        y = P(y, "The full statement is set out in the Annex. Please contact Investor Relations with any queries.")
        doc.t(60, y - 10, "Yours faithfully,")
        doc.t(60, y - 40, f"For and on behalf of {k.gp_name}", bold=True)
        doc.new_page()
        uk_head(doc, f"Annex - Partner capital account statement as at {d_uk(k.notice_date)}")
        y = uk_capital_account(doc, doc.h - 125, heading=f"{k.fund_name} - {k.lp_name}")
        doc.t(60, y, "Net cash movement in the quarter", 9.5)
        doc.t(535, y, gbp(k.lp_net_called_distributed), 9.5, right=True)
        y -= 25
        y = P(y, "Should the General Partner recall any recallable distributions, payment will be due to the "
              "Partnership's account below.")
        uk_bank(doc, y, "Partnership account")
        doc.save()
        return

    is_call = k.kind == K.CAPITAL_CALL
    subj = f"Drawdown Notice No. {number}" if is_call else f"Distribution Notice No. {number}"
    doc.t(60, y, f"{k.fund_name} (the \"Partnership\") - {subj}", bold=True, fields=("fund_name",))
    y -= 22
    if is_call:
        y = P(y, f"{k.gp_name}, as manager of the Partnership, gives notice under clause 4.2 of the Limited "
              f"Partnership Agreement that the Partnership requires {gbp(k.fund_contributions_current)} from its "
              f"partners in proportion to their commitments (the \"Drawdown\").",
              ("gp_name", "fund_contributions_current"))
        y = P(y, f"Your commitment of {gbp(k.lp_commitment)} represents a {k.lp_pct_of_fund * 100:.4f}% interest "
              f"in the Partnership. Your share of the Drawdown is {gbp(k.lp_contributions_current)}.",
              ("lp_commitment", "lp_pct_of_fund", "lp_contributions_current"))
        if k.lp_outside_outflow_current:
            sci = sum((t.lp_amount for t in k.transactions if t.transaction_type == T.CC_SUBSEQ_INTEREST),
                      Decimal(0))
            what = (f"equalisation interest of {gbp(sci)} payable because you were admitted at a subsequent "
                    f"closing") if sci else "placement fees"
            y = P(y, f"In addition, {gbp(k.lp_outside_outflow_current)} is payable outside your commitment "
                  f"({what}). This amount does not reduce your undrawn commitment.",
                  ("lp_outside_outflow_current",))
        y = P(y, f"The total amount payable by you is {gbp(k.lp_net_called_distributed)}, which must reach the "
              f"Partnership's account no later than {d_uk(k.due_date)}. Amounts are in pounds sterling "
              f"({k.fund_currency}).", ("lp_net_called_distributed", "due_date", "fund_currency"))
        y = P(y, f"After this Drawdown you will have contributed {gbp(k.lp_cum_contributions_incl)} in total and "
              f"your undrawn commitment will be {gbp(k.lp_unfunded_incl)}. A breakdown is set out in Annex A and "
              "your capital account in Annex B, together with payment instructions.")
    else:
        y = P(y, f"{k.gp_name}, as manager of the Partnership, is pleased to advise a distribution of "
              f"{gbp(k.fund_distributions_current)} to partners following realisations in the portfolio.",
              ("gp_name", "fund_distributions_current"))
        y = P(y, f"Your commitment of {gbp(k.lp_commitment)} represents a {k.lp_pct_of_fund * 100:.4f}% interest "
              f"in the Partnership. Your net share of the distribution is {gbp(k.lp_distributions_current)}, "
              f"which will be paid to your account on file on {d_uk(k.due_date)}. Amounts are in pounds sterling "
              f"({k.fund_currency}).",
              ("lp_commitment", "lp_pct_of_fund", "lp_distributions_current", "due_date", "fund_currency"))
        y = P(y, f"The distribution includes a return of capital of {gbp(roc_amt(k))}, of which "
              f"{gbp(recallable_amt(k))} is recallable under {CLAUSE} of the Limited Partnership Agreement. The "
              f"recallable amount is added back to your undrawn commitment, which will be "
              f"{gbp(k.lp_unfunded_incl)} after this distribution.")
        y = P(y, f"The net cash movement on your account for this notice is {gbp(k.lp_net_called_distributed)} "
              "(a negative figure is a payment to you). A breakdown is set out in Annex A and your capital "
              "account in Annex B.", ("lp_net_called_distributed",))
    doc.t(60, y - 10, "Yours faithfully,")
    doc.t(60, y - 40, f"For and on behalf of {k.gp_name}", bold=True)

    doc.new_page()
    uk_head(doc, f"Annex A - Breakdown of {'Drawdown' if is_call else 'distribution'} No. {number}")
    y = doc.h - 125
    rows = []
    for t in k.transactions:
        amt = -t.lp_amount if t.transaction_type == T.D_TAX_WITHHELD else t.lp_amount
        where = "within commitment" if t.inside_outside == InsideOutside.INSIDE else "outside commitment"
        rows.append((t.description, [f"{cat(t)}, {where}", gbp(amt)], ()))
    y = uk_table(doc, y, ["Item", "Nature", "Your share"], rows, xs=(60, 430, 535))
    for t in k.transactions:
        t.page = doc.page
    if is_call:
        doc.t(60, y, "Total within commitment", 9.5)
        doc.t(535, y, gbp(k.lp_contributions_current), 9.5, right=True)
        y -= 15
        if k.lp_outside_outflow_current:
            doc.t(60, y, "Total outside commitment", 9.5)
            doc.t(535, y, gbp(k.lp_outside_outflow_current), 9.5, right=True)
            y -= 15
    doc.t(60, y, "Total", 9.5, bold=True)
    doc.t(535, y, gbp(abs(k.lp_net_called_distributed)), 9.5, bold=True, right=True)

    doc.new_page()
    uk_head(doc)
    y = uk_capital_account(doc, doc.h - 100)
    if is_call:
        y = P(y, f"Please transfer {gbp(k.lp_net_called_distributed)} by CHAPS to the following account, quoting "
              f"your investor reference:")
        uk_bank(doc, y, "Payment instructions")
    else:
        y = P(y, "Your distribution will be paid to your account on file. Should the manager recall any "
              "recallable amount in future, payment will be due to the Partnership's receiving account:")
        uk_bank(doc, y, "Partnership receiving account")
    doc.save()


# ---------------------------------------------------------------- ILPA sample letter (hand-made key)
ILPA_PDF = ROOT / "sources" / "ILPA-Sample-Cover-Description-Letter-2025.pdf"


def ilpa_key() -> Notice:
    pg = 10  # pdftotext -f 10 -l 10: the "Sample Description Letter" with the figures is PDF page 10
    fields = ["due_date", "fund_name", "fund_currency", "lp_commitment",
              "lp_unfunded_incl", "lp_cum_distributions_incl", "lp_recallable_balance", "lp_net_called_distributed"]
    return Notice(
        source_file="c_ilpa_sample.pdf", kind=K.CAPITAL_CALL, notice_date=None, due_date=date(2025, 1, 14),
        fund_name="Investment Fund II, L.P.", fund_currency="USD", lp_commitment=Decimal("50000000"),
        lp_unfunded_incl=Decimal("30000000"),
        lp_cum_distributions_incl=Decimal("10000000"), lp_recallable_balance=Decimal("5000000"),
        lp_net_called_distributed=Decimal("1750000"), transactions=[],
        bank=BankDetails(bank_name="Private Equity Bank", account_name="Investment Fund II, L.P.",
                         account_number="445632189", sort_code="023 334 023", page=pg),
        pages={f: pg for f in fields},
    )


# ---------------------------------------------------------------- main
RENDER = {"lux": render_lux, "us": render_us, "uk": render_uk}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    docs: list[tuple[Path, Notice]] = []
    for i, (fseed, cur, sseed, kinds, style) in enumerate(CONFIG, start=1):
        fund = make_fund(fseed, cur)
        seq = make_sequence(fund, sseed, n=3, kinds=kinds, recallable_share=float(RECALL_SHARE))
        for n, key in enumerate(seq, start=1):
            name = f"c_fund{i}_n{n}"
            key.source_file = f"{name}.pdf"
            if key.kind == K.CAPITAL_ACCOUNT_STATEMENT:
                key.due_date = None
            pdf = OUT / f"{name}.pdf"
            RENDER[style](key, pdf, n)
            write_key(key, OUT / f"{name}.json")
            docs.append((pdf, key))
    if not any(has_sci(k) for _, k in docs):
        print("no document shows subsequent close interest; change a sequence seed")
        return 1
    if ILPA_PDF.exists():  # ILPA's sample letter is not redistributed; fetch it with tools/fetch_ilpa.py
        shutil.copyfile(ILPA_PDF, OUT / "c_ilpa_sample.pdf")
        ik = ilpa_key()
        write_key(ik, OUT / "c_ilpa_sample.json")
        docs.append((OUT / "c_ilpa_sample.pdf", ik))

    bad = 0
    for pdf, key in docs:
        probs = verify_pdf(pdf, key)
        missing = [f for f, v in key.model_dump().items()
                   if v is not None and f not in ("source_file", "kind", "transactions", "bank", "pages")
                   and f not in key.pages]
        if key.bank is not None and key.bank.page is None:
            missing.append("bank.page")
        probs += [f"{m}: page not recorded" for m in missing if f"{m}: no page recorded" not in probs]
        status = "ok" if not probs else f"{len(probs)} problem(s)"
        print(f"{pdf.name:24s} {key.kind.value:27s} {status}")
        for p in probs:
            print(f"    {p}")
        bad += bool(probs)
    sci_docs = [p.name for p, k in docs if has_sci(k)]
    print(f"family C: {len(docs)} documents, {len(docs) - bad} pass, {bad} fail; "
          f"subsequent close interest in {', '.join(sci_docs)}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
