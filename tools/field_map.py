"""Step 1 check: every label in the ILPA template maps to a schema field or is listed out of scope.

Reads sources/ILPA-Capital-Call-Distribution-Template-v2.0.xlsx, writes docs/field-map.md,
exits 1 if any template label is unmapped or any mapped field is missing from the schema.
"""
import sys
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from drawbook.schema import Notice, Transaction, TransactionType  # noqa: E402

TEMPLATE = ROOT / "sources" / "ILPA-Capital-Call-Distribution-Template-v2.0.xlsx"
SHEET = "Call & Distribution Template"

# (section, template label) -> schema field, or "OUT: reason"
MAP = {
    ("Header", "Notice Date"): "notice_date",
    ("Header", "Due Date"): "due_date",
    ("Fund-level", "Fund Name"): "fund_name",
    ("Fund-level", "Fund Currency"): "fund_currency",
    ("Fund-level", "Fund Size"): "fund_size",
    ("Fund-level", "GP Commitment Amount"): "gp_commitment",
    ("Fund-level", "Fund Amount (Current Notice) / Contributions"): "fund_contributions_current",
    ("Fund-level", "Fund Amount (Current Notice) / Distributions"): "fund_distributions_current",
    ("Fund-level", "Fund Amount (Current Notice) / Net Cash Flow"): "OUT: derived (contributions + distributions); computed in ledger",
    ("LP-level inside fund", "LP / ID Number"): "lp_id",
    ("LP-level inside fund", "LP Commitment"): "lp_commitment",
    ("LP-level inside fund", "LP % of Fund (LP Commitment / Fund Size)"): "lp_pct_of_fund",
    ("LP-level inside fund", "LP % of Unfunded (% of Total Fund Unfunded) - Optional"): "lp_pct_of_unfunded",
    ("LP-level inside fund", "LP Amount (Current Notice) / Contributions"): "lp_contributions_current",
    ("LP-level inside fund", "LP Amount (Current Notice) / Distributions"): "lp_distributions_current",
    ("LP-level inside fund", "LP Amount (Current Notice) / Net Cash Flow"): "OUT: derived; computed in ledger",
    ("LP-level inside fund", "As a % of Fund Amount"): "OUT: derived (LP amount / fund amount); computed in ledger",
    ("LP-level inside fund", "Cumulative LP Amount (Prior to Current Notice) / Contributions"): "lp_cum_contributions_prior",
    ("LP-level inside fund", "Cumulative LP Amount (Prior to Current Notice) / Distributions"): "lp_cum_distributions_prior",
    ("LP-level inside fund", "Cumulative LP Amount (Including Current Notice) / Contributions"): "lp_cum_contributions_incl",
    ("LP-level inside fund", "Cumulative LP Amount (Including Current Notice) / Distributions"): "lp_cum_distributions_incl",
    ("LP-level inside fund", "LP Unfunded Balance (Prior to Current Notice)"): "lp_unfunded_prior",
    ("LP-level inside fund", "Impact on LP Unfunded Balance (Current Notice)"): "lp_unfunded_impact_current",
    ("LP-level inside fund", "Expired/Released Commitments (Input negative value)"): "lp_expired_released",
    ("LP-level inside fund", "Other Unfunded Adjustment"): "lp_other_unfunded_adjustment",
    ("LP-level inside fund", "LP Unfunded Balance (Including Current Notice)"): "lp_unfunded_incl",
    ("LP-level outside fund", "LP Amount (Current Notice) / Outflow from LP"): "lp_outside_outflow_current",
    ("LP-level outside fund", "LP Amount (Current Notice) / Inflow to LP"): "lp_outside_inflow_current",
    ("LP-level outside fund", "LP Amount (Current Notice) / Net Cash Flow"): "OUT: derived; computed in ledger",
    ("LP-level outside fund", "LP Total Net Amount Called / (Distributed)"): "lp_net_called_distributed",
    ("Transactions", "Transaction Description"): "transactions[].description",
    ("Transactions", "Transaction Type"): "transactions[].transaction_type",
    ("Transactions", "LP Amount (Input Positive Values)"): "transactions[].lp_amount",
    ("Transactions", "Impact on Unfunded Commitment (Increase/Decrease)"): "transactions[].impact_on_unfunded",
    ("Transactions", "Impact on Unfunded Commitment (Value)"): "OUT: derived from amount + direction; computed in ledger",
    ("Transactions", "Net Amount Called / (Distributed) (Value)"): "OUT: derived from amount + type; computed in ledger",
    ("Transactions", "Inside / Outside Fund"): "transactions[].inside_outside",
}
SUPPLEMENTAL_OUT = "OUT: optional supplemental calculation; v0 reads cash flows and balances only"
SUPPLEMENTAL_LABELS = [
    "Management Fee Calculation (per Section X.X of LPA)", "Time Period", "Calculation Basis, per LPA",
    "Gross Calculation", "Waiver Amount", "Fee Offset", "Capital Call: Management Fees (Investor #X)",
    "Management Fee Calculation - Key Dates (Optional)", "Final Close Date", "Investment Period End Date",
    "Management Fee Step-Down Date", "Fund Term Expiration Date",
    "Waterfall/Carry Calculation (per Section X.X of LPA)", "Distributable Cash", "Return of Capital",
    "G/L - pre LP/GP Split", "G/L - after LP/GP Split", "Carry Paid/(Received)",
    "Carry Earned/(Realized Profits, Inclusive of Amt. Held in Escrow)",
    "Clawback Questions", "Is the Fund in a Clawback Situation (Yes/No)", "If Yes: What is the Amount?",
    "If Yes: What is the Proposed Remedy?", "Disclosures/Footnotes",
]
for lab in SUPPLEMENTAL_LABELS:
    MAP[("Supplemental", lab)] = SUPPLEMENTAL_OUT
RECON = "OUT as template fields; v0 computes this reconciliation itself (Balances sheet tie-out check)"
for lab in ["Cumulative Balance - Reconciliation to a Prior Period Notice", "Balance Name (e.g., LP Unfunded Balance)",
            "Ending Balance - Prior Period (As reported in a prior notice)",
            "Ending Balance - Current Period (As reported in the current notice)", "Variance", "Reason for Variance"]:
    MAP[("Supplemental", lab)] = RECON

# cells that are headings / column captions, not fields
IGNORE = {"ILPA Capital Call & Distribution Template", "Contributions", "Distributions", "Net Cash Flow",
          "Inside Fund", "Outside Fund", "Outflow from LP", "Inflow to LP", "Supplemental Calculations - Optional",
          "Investor X", "All LPs", "GP", "Total", "Fund Amount (Current Notice)", "LP Amount (Current Notice)",
          "Cumulative LP Amount (Prior to Current Notice)", "Cumulative LP Amount (Including Current Notice)"}


def norm(s: str) -> str:
    return " ".join(str(s).split())


def template_labels(ws):
    """Every text label on the sheet (string cells that are not data or formulas), with its row."""
    out = []
    for row in ws.iter_rows():
        for c in row:
            v = c.value
            if isinstance(v, str) and not v.startswith("=") and c.row != 24:  # row 24 is ILPA's example data
                if c.column_letter == "C" and c.row in (3, 4, 10):  # example values
                    continue
                out.append((c.row, norm(v)))
    return out


def main() -> int:
    if not TEMPLATE.exists():
        print("ILPA template not found. Download it first: python tools/fetch_ilpa.py")
        return 2
    wb = openpyxl.load_workbook(TEMPLATE)
    ws = wb[SHEET]
    mapped_labels = {norm(lab.split(" / ")[0]) for (_, lab) in MAP} | {norm(lab.split(" / ")[-1]) for (_, lab) in MAP} \
        | {norm(lab) for (_, lab) in MAP}
    unmapped = [(r, lab) for r, lab in template_labels(ws) if lab not in mapped_labels and lab not in IGNORE]

    fields = set(Notice.model_fields)
    tfields = set(Transaction.model_fields)
    bad = []
    for key, target in MAP.items():
        if target.startswith("OUT"):
            continue
        name = target.split("[].")[-1]
        ok = name in tfields if target.startswith("transactions[]") else name in fields
        if not ok:
            bad.append((key, target))

    types_ws = wb["Trans. Types & Definitions"]
    tpl_types = {norm(types_ws.cell(r, 1).value) for r in range(3, 30) if types_ws.cell(r, 1).value}
    enum_types = {norm(t.value) for t in TransactionType}
    missing_types = sorted(tpl_types - enum_types)
    extra_types = sorted(enum_types - tpl_types)

    lines = ["# Field map: ILPA Capital Call & Distribution Template v2.0 -> Drawbook schema", "",
             "Built by `tools/field_map.py` from `sources/ILPA-Capital-Call-Distribution-Template-v2.0.xlsx`.", "",
             "| Section | Template label | Drawbook field |", "|---|---|---|"]
    for (sec, lab), tgt in MAP.items():
        lines.append(f"| {sec} | {lab} | {tgt if tgt.startswith('OUT') else '`' + tgt + '`'} |")
    lines += ["", "## Fields Drawbook adds (not in the template)", "",
              "- `kind`, `source_file`, `pages` (provenance), `gp_name`, `lp_name`, `lp_recallable_balance`,",
              "  `transactions[].recallable`, `transactions[].page`, `bank` (payment instructions for the bank-change warning).", "",
              f"## Transaction types: {len(tpl_types)} in template, {len(enum_types)} in schema", "",
              f"- Missing from schema: {missing_types or 'none'}", f"- Extra in schema: {extra_types or 'none'}", "",
              f"## Result", "", f"- Unmapped template labels: {len(unmapped)} {unmapped or ''}",
              f"- Mapped targets missing from schema: {len(bad)} {bad or ''}"]
    (ROOT / "docs" / "field-map.md").write_text("\n".join(lines) + "\n")
    print(f"labels mapped={len(MAP)} unmapped={len(unmapped)} bad_targets={len(bad)} "
          f"types tpl={len(tpl_types)} schema={len(enum_types)} missing={missing_types} extra={extra_types}")
    for u in unmapped:
        print("UNMAPPED", u)
    return 1 if (unmapped or bad or missing_types or extra_types) else 0


if __name__ == "__main__":
    sys.exit(main())
