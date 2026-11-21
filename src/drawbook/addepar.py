"""Addepar Transactions API payloads (POST /v1/transactions), built from Drawbook notices.

Source, fetched 2026-11-21:
  https://developers.addepar.com/docs/transactions.md          (attributes, buckets, example POST)
  https://developers.addepar.com/docs/transaction-types.md     (type names)
  https://developers.addepar.com/docs/basic-authentication.md  (headers)

`build_payloads` makes no network call. `send` is the only function that does, needs an explicit
base URL, credential and firm ID, and is never called in tests. Each Drawbook transaction becomes
one Addepar transaction, with its whole amount in one breakdown bucket (Addepar asks that the
buckets sum to the amount). In-kind (stock) distributions are not mapped and come back as skipped.
"""
from __future__ import annotations

import json
import urllib.request
from datetime import date

from .schema import Notice, TransactionType as T

BATCH = 500  # Addepar: "Batch operations accept up to 500 transactions per request."

# Drawbook type -> (Addepar type, breakdown attribute or None)
CONTRIBUTION_BUCKET = {T.CC_INVESTMENTS: "contribution_investment", T.CC_MGMT_FEES: "contribution_management_fee",
                       T.CC_EXPENSES: "contribution_expense"}
DISTRIBUTION_BUCKET = {T.D_ROC_CASH: "return_of_capital", T.D_DIVIDENDS: "dividend", T.D_GAIN_CASH: "cap_gain"}
OTHER = {T.NC_EXCESS: ("recalled_contribution", None), T.NC_EXCESS_INV: ("recalled_contribution", None),
         T.NC_EXCESS_FEES: ("recalled_contribution", None), T.D_TAX_WITHHELD: ("tax_withholding", None),
         T.D_TAX_REFUND: ("tax_withholding_refund", None)}
UNMAPPED = {T.D_ROC_STOCK, T.D_GAIN_STOCK}


def _addepar_type(t) -> tuple[str, str | None] | None:
    tt = t.transaction_type
    if tt in UNMAPPED:
        return None
    if tt in OTHER:
        return OTHER[tt]
    if tt.value.startswith("Capital Call"):
        return "contribution", CONTRIBUTION_BUCKET.get(tt, "contribution_generic")
    if t.recallable:
        return "distribution", "recallable"
    return "distribution", DISTRIBUTION_BUCKET.get(tt, "generic")


def build_payloads(notices: list[Notice], owner_id: str, owned_ids: dict[str, str]) -> tuple[list[dict], list[dict]]:
    """Return (payloads, skipped).

    owner_id: the Addepar entity ID of the LP's portfolio/account (the `owner` relationship).
    owned_ids: fund_name -> Addepar entity ID of the fund holding (the `owned` relationship).
    Trade date is the notice's due date, else its notice date.
    Each payload is one request body {"data": [...]} of at most 500 transactions.
    """
    items, skipped = [], []
    for n in sorted(notices, key=lambda n: (n.fund_name, n.notice_date or date.min)):
        when = n.due_date or n.notice_date
        for t in n.transactions:
            why = None
            kind = _addepar_type(t)
            if kind is None:
                why = "in-kind distribution: no cash type mapped"
            elif n.fund_name not in owned_ids:
                why = "no Addepar entity ID given for this fund"
            elif when is None:
                why = "notice has no due date or notice date"
            if why:
                skipped.append({"file": n.source_file, "page": t.page, "type": t.transaction_type.value, "reason": why})
                continue
            atype, bucket = kind
            attrs = {"type": atype, "currency": n.fund_currency, "trade_date": when.isoformat(),
                     "amount": float(t.lp_amount), "comment": f"{t.description} ({n.source_file} p{t.page})"}
            if bucket:
                attrs[bucket] = float(t.lp_amount)
            if atype == "contribution":
                attrs["affects_unfunded_commitment"] = t.impact_on_unfunded.value != "No Impact"
            items.append({"type": "transactions", "attributes": attrs,
                          "relationships": {"owner": {"data": {"type": "entities", "id": str(owner_id)}},
                                            "owned": {"data": {"type": "entities", "id": str(owned_ids[n.fund_name])}}}})
    return [{"data": items[i:i + BATCH]} for i in range(0, len(items), BATCH)], skipped


def send(payloads: list[dict], base_url: str, token: str, firm_id: str) -> list[dict]:
    """POST each payload to {base_url}/v1/transactions, e.g. base_url="https://yourfirm.addepar.com/api".

    token: base64 of "API_KEY:API_SECRET" (sent as "Authorization: Basic <token>").
    firm_id: your Addepar firm ID (sent as the Addepar-Firm header).
    Writes to a live Addepar firm. Never called by tests or by Drawbook on its own.
    """
    if not (base_url and token and firm_id):
        raise ValueError("send needs an explicit base_url, token and firm_id")
    out = []
    for p in payloads:
        req = urllib.request.Request(f"{base_url.rstrip('/')}/v1/transactions", data=json.dumps(p).encode(),
                                     method="POST", headers={"Authorization": f"Basic {token}",
                                                             "Addepar-Firm": str(firm_id),
                                                             "Content-Type": "application/vnd.api+json"})
        with urllib.request.urlopen(req) as r:
            out.append(json.loads(r.read() or b"{}"))
    return out
