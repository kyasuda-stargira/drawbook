"""Fixed schema for one notice, shaped on the ILPA Capital Call & Distribution Template v2.0 (Sept 2025).

Section names follow the template sheet "Call & Distribution Template":
header, fund-level, LP-level (inside fund), LP-level (outside fund), transactions.
`docs/field-map.md` maps every template label to a field here (built by tools/field_map.py).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class TransactionType(str, Enum):
    """The 27 transaction types on the template's 'Trans. Types & Definitions' sheet."""
    CC_DEEMED_GP = "Capital Call: Deemed GP Contribution from LPs"
    CC_TOTAL_INSIDE = "Capital Call: Total Amount - Inside Fund"
    CC_TOTAL_OUTSIDE = "Capital Call: Total Amount - Outside Fund"
    CC_INVESTMENTS = "Capital Call: Investments"
    CC_MGMT_FEES = "Capital Call: Management Fees"
    CC_EXPENSES = "Capital Call: Partnership Expenses"
    CC_PLACEMENT = "Capital Call: Placement Agent Fees"
    CC_SUBSEQ_INTEREST = "Capital Call: Subsequent Close Interest"
    CC_WORKING_CAPITAL = "Capital Call: Working Capital"
    CC_SUB_FACILITY = "Capital Call: Fund-level Subscription Facility Fees/Interest"
    CC_OTHER = "Capital Call: Other (Provide explanation in far-left column)"
    D_CARRY = "Distribution: Carry"
    D_CLAWBACK = "Distribution: Clawback"
    D_INCOME = "Distribution: Income"
    D_DIVIDENDS = "Distribution: Dividends"
    D_OTHER = "Distribution: Other (Provide explanation in far-left column)"
    D_GAIN_CASH = "Distribution: Realized Gain / (Loss) - Cash (input negative value for loss)"
    D_GAIN_STOCK = "Distribution: Realized Gain / (Loss) - Stock (input negative value for loss)"
    D_ROC_CASH = "Distribution: Return of Capital - Cash"
    D_ROC_STOCK = "Distribution: Return of Capital - Stock"
    D_NAV_FACILITY = "Distribution: From NAV-Based Facility"
    NC_EXCESS = "Negative Contribution: Return of Excess Capital Called"
    NC_EXCESS_INV = "Negative Contribution: Return of Excess Capital Called - Investments"
    NC_EXCESS_FEES = "Negative Contribution: Return of Excess Capital Called - Management Fees/Partnership Expenses"
    D_SUBSEQ_INTEREST = "Distribution: Subsequent Close Interest"
    D_TAX_WITHHELD = "Distribution: Tax Withheld"
    D_TAX_REFUND = "Distribution: Refund of Tax Withheld"


class UnfundedImpact(str, Enum):
    INCREASE = "Increase"
    DECREASE = "Decrease"
    NO_IMPACT = "No Impact"


class InsideOutside(str, Enum):
    INSIDE = "Inside"
    OUTSIDE = "Outside"


class NoticeKind(str, Enum):
    CAPITAL_CALL = "capital_call"
    DISTRIBUTION = "distribution"
    COMBINED = "combined"  # call and distribution netted in one notice
    CAPITAL_ACCOUNT_STATEMENT = "capital_account_statement"


class Transaction(BaseModel):
    """One row of the template's transaction table (B23:L53)."""
    description: str
    transaction_type: TransactionType
    lp_amount: Decimal = Field(description="Positive value, as the template asks ('Input Positive Values')")
    impact_on_unfunded: UnfundedImpact
    inside_outside: InsideOutside
    recallable: Optional[bool] = None  # not a template column; scope note asks for it
    page: int = Field(ge=1, description="1-based PDF page the amount was read from")


class BankDetails(BaseModel):
    """Payment instructions. Not part of the template; used for the bank-change warning."""
    bank_name: Optional[str] = None
    account_name: Optional[str] = None
    account_number: Optional[str] = None  # account number or IBAN, as printed
    sort_code: Optional[str] = None  # sort code / ABA routing
    swift_bic: Optional[str] = None
    reference: Optional[str] = None
    page: Optional[int] = Field(default=None, ge=1)


class Notice(BaseModel):
    """Everything Drawbook reads from one document."""
    # source
    source_file: str
    kind: NoticeKind
    # header
    notice_date: Optional[date] = None  # required on real notices; ILPA sample letter leaves it as "[Date]"
    due_date: Optional[date] = None
    # fund-level
    fund_name: str
    gp_name: Optional[str] = None  # not a template field; scope note asks for it
    fund_currency: str = Field(min_length=3, max_length=3)
    fund_size: Optional[Decimal] = None
    gp_commitment: Optional[Decimal] = None
    fund_contributions_current: Optional[Decimal] = None
    fund_distributions_current: Optional[Decimal] = None
    # LP-level, inside fund
    lp_id: Optional[str] = None
    lp_name: Optional[str] = None
    lp_commitment: Optional[Decimal] = None
    lp_pct_of_fund: Optional[Decimal] = None  # as a fraction, 0.01 = 1%
    lp_pct_of_unfunded: Optional[Decimal] = None
    lp_contributions_current: Optional[Decimal] = None
    lp_distributions_current: Optional[Decimal] = None
    lp_cum_contributions_prior: Optional[Decimal] = None
    lp_cum_distributions_prior: Optional[Decimal] = None
    lp_cum_contributions_incl: Optional[Decimal] = None
    lp_cum_distributions_incl: Optional[Decimal] = None
    lp_unfunded_prior: Optional[Decimal] = None
    lp_unfunded_impact_current: Optional[Decimal] = None
    lp_expired_released: Optional[Decimal] = None
    lp_other_unfunded_adjustment: Optional[Decimal] = None
    lp_unfunded_incl: Optional[Decimal] = None
    lp_recallable_balance: Optional[Decimal] = None  # not a template field; scope note asks for it
    # LP-level, outside fund
    lp_outside_outflow_current: Optional[Decimal] = None
    lp_outside_inflow_current: Optional[Decimal] = None
    lp_net_called_distributed: Optional[Decimal] = None  # positive = called, negative = distributed
    # transactions
    transactions: list[Transaction] = Field(default_factory=list)
    # payment
    bank: Optional[BankDetails] = None
    # provenance: field name -> 1-based page for every scalar figure above that is filled
    pages: dict[str, int] = Field(default_factory=dict)


# Scalar fields scored by the test harness (everything filled in an answer key is scored).
SCALAR_FIELDS = [n for n in Notice.model_fields if n not in ("source_file", "transactions", "bank", "pages")]
