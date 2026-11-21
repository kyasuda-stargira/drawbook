# Field map: ILPA Capital Call & Distribution Template v2.0 -> Drawbook schema

Built by `tools/field_map.py` from `sources/ILPA-Capital-Call-Distribution-Template-v2.0.xlsx`.

| Section | Template label | Drawbook field |
|---|---|---|
| Header | Notice Date | `notice_date` |
| Header | Due Date | `due_date` |
| Fund-level | Fund Name | `fund_name` |
| Fund-level | Fund Currency | `fund_currency` |
| Fund-level | Fund Size | `fund_size` |
| Fund-level | GP Commitment Amount | `gp_commitment` |
| Fund-level | Fund Amount (Current Notice) / Contributions | `fund_contributions_current` |
| Fund-level | Fund Amount (Current Notice) / Distributions | `fund_distributions_current` |
| Fund-level | Fund Amount (Current Notice) / Net Cash Flow | OUT: derived (contributions + distributions); computed in ledger |
| LP-level inside fund | LP / ID Number | `lp_id` |
| LP-level inside fund | LP Commitment | `lp_commitment` |
| LP-level inside fund | LP % of Fund (LP Commitment / Fund Size) | `lp_pct_of_fund` |
| LP-level inside fund | LP % of Unfunded (% of Total Fund Unfunded) - Optional | `lp_pct_of_unfunded` |
| LP-level inside fund | LP Amount (Current Notice) / Contributions | `lp_contributions_current` |
| LP-level inside fund | LP Amount (Current Notice) / Distributions | `lp_distributions_current` |
| LP-level inside fund | LP Amount (Current Notice) / Net Cash Flow | OUT: derived; computed in ledger |
| LP-level inside fund | As a % of Fund Amount | OUT: derived (LP amount / fund amount); computed in ledger |
| LP-level inside fund | Cumulative LP Amount (Prior to Current Notice) / Contributions | `lp_cum_contributions_prior` |
| LP-level inside fund | Cumulative LP Amount (Prior to Current Notice) / Distributions | `lp_cum_distributions_prior` |
| LP-level inside fund | Cumulative LP Amount (Including Current Notice) / Contributions | `lp_cum_contributions_incl` |
| LP-level inside fund | Cumulative LP Amount (Including Current Notice) / Distributions | `lp_cum_distributions_incl` |
| LP-level inside fund | LP Unfunded Balance (Prior to Current Notice) | `lp_unfunded_prior` |
| LP-level inside fund | Impact on LP Unfunded Balance (Current Notice) | `lp_unfunded_impact_current` |
| LP-level inside fund | Expired/Released Commitments (Input negative value) | `lp_expired_released` |
| LP-level inside fund | Other Unfunded Adjustment | `lp_other_unfunded_adjustment` |
| LP-level inside fund | LP Unfunded Balance (Including Current Notice) | `lp_unfunded_incl` |
| LP-level outside fund | LP Amount (Current Notice) / Outflow from LP | `lp_outside_outflow_current` |
| LP-level outside fund | LP Amount (Current Notice) / Inflow to LP | `lp_outside_inflow_current` |
| LP-level outside fund | LP Amount (Current Notice) / Net Cash Flow | OUT: derived; computed in ledger |
| LP-level outside fund | LP Total Net Amount Called / (Distributed) | `lp_net_called_distributed` |
| Transactions | Transaction Description | `transactions[].description` |
| Transactions | Transaction Type | `transactions[].transaction_type` |
| Transactions | LP Amount (Input Positive Values) | `transactions[].lp_amount` |
| Transactions | Impact on Unfunded Commitment (Increase/Decrease) | `transactions[].impact_on_unfunded` |
| Transactions | Impact on Unfunded Commitment (Value) | OUT: derived from amount + direction; computed in ledger |
| Transactions | Net Amount Called / (Distributed) (Value) | OUT: derived from amount + type; computed in ledger |
| Transactions | Inside / Outside Fund | `transactions[].inside_outside` |
| Supplemental | Management Fee Calculation (per Section X.X of LPA) | OUT: optional supplemental calculation; v0 reads cash flows and balances only |
| Supplemental | Time Period | OUT: optional supplemental calculation; v0 reads cash flows and balances only |
| Supplemental | Calculation Basis, per LPA | OUT: optional supplemental calculation; v0 reads cash flows and balances only |
| Supplemental | Gross Calculation | OUT: optional supplemental calculation; v0 reads cash flows and balances only |
| Supplemental | Waiver Amount | OUT: optional supplemental calculation; v0 reads cash flows and balances only |
| Supplemental | Fee Offset | OUT: optional supplemental calculation; v0 reads cash flows and balances only |
| Supplemental | Capital Call: Management Fees (Investor #X) | OUT: optional supplemental calculation; v0 reads cash flows and balances only |
| Supplemental | Management Fee Calculation - Key Dates (Optional) | OUT: optional supplemental calculation; v0 reads cash flows and balances only |
| Supplemental | Final Close Date | OUT: optional supplemental calculation; v0 reads cash flows and balances only |
| Supplemental | Investment Period End Date | OUT: optional supplemental calculation; v0 reads cash flows and balances only |
| Supplemental | Management Fee Step-Down Date | OUT: optional supplemental calculation; v0 reads cash flows and balances only |
| Supplemental | Fund Term Expiration Date | OUT: optional supplemental calculation; v0 reads cash flows and balances only |
| Supplemental | Waterfall/Carry Calculation (per Section X.X of LPA) | OUT: optional supplemental calculation; v0 reads cash flows and balances only |
| Supplemental | Distributable Cash | OUT: optional supplemental calculation; v0 reads cash flows and balances only |
| Supplemental | Return of Capital | OUT: optional supplemental calculation; v0 reads cash flows and balances only |
| Supplemental | G/L - pre LP/GP Split | OUT: optional supplemental calculation; v0 reads cash flows and balances only |
| Supplemental | G/L - after LP/GP Split | OUT: optional supplemental calculation; v0 reads cash flows and balances only |
| Supplemental | Carry Paid/(Received) | OUT: optional supplemental calculation; v0 reads cash flows and balances only |
| Supplemental | Carry Earned/(Realized Profits, Inclusive of Amt. Held in Escrow) | OUT: optional supplemental calculation; v0 reads cash flows and balances only |
| Supplemental | Clawback Questions | OUT: optional supplemental calculation; v0 reads cash flows and balances only |
| Supplemental | Is the Fund in a Clawback Situation (Yes/No) | OUT: optional supplemental calculation; v0 reads cash flows and balances only |
| Supplemental | If Yes: What is the Amount? | OUT: optional supplemental calculation; v0 reads cash flows and balances only |
| Supplemental | If Yes: What is the Proposed Remedy? | OUT: optional supplemental calculation; v0 reads cash flows and balances only |
| Supplemental | Disclosures/Footnotes | OUT: optional supplemental calculation; v0 reads cash flows and balances only |
| Supplemental | Cumulative Balance - Reconciliation to a Prior Period Notice | OUT as template fields; v0 computes this reconciliation itself (Balances sheet tie-out check) |
| Supplemental | Balance Name (e.g., LP Unfunded Balance) | OUT as template fields; v0 computes this reconciliation itself (Balances sheet tie-out check) |
| Supplemental | Ending Balance - Prior Period (As reported in a prior notice) | OUT as template fields; v0 computes this reconciliation itself (Balances sheet tie-out check) |
| Supplemental | Ending Balance - Current Period (As reported in the current notice) | OUT as template fields; v0 computes this reconciliation itself (Balances sheet tie-out check) |
| Supplemental | Variance | OUT as template fields; v0 computes this reconciliation itself (Balances sheet tie-out check) |
| Supplemental | Reason for Variance | OUT as template fields; v0 computes this reconciliation itself (Balances sheet tie-out check) |

## Fields Drawbook adds (not in the template)

- `kind`, `source_file`, `pages` (provenance), `gp_name`, `lp_name`, `lp_recallable_balance`,
  `transactions[].recallable`, `transactions[].page`, `bank` (payment instructions for the bank-change warning).

## Transaction types: 27 in template, 27 in schema

- Missing from schema: none
- Extra in schema: none

## Result

- Unmapped template labels: 0 
- Mapped targets missing from schema: 0 
