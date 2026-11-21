"""Reader rules that run in code, tested with a fake model answer (no model needed)."""
import json
from pathlib import Path

from drawbook.extract import extract
from drawbook.providers import MockProvider

PDF = Path(__file__).resolve().parents[1] / "testset" / "locked" / "family_a" / "a_fund1_n1.pdf"

IDENTITY = {
    "kind": "capital_call",
    "fields": {"fund_name": "Corvid Basalt Fund V SCSp", "fund_currency": "USD", "lp_name": "Investor Teesdale Local Government Pension Fund",
               "notice_date": "16 March 2023", "lp_commitment": {"value": "$10,000,000.00", "page": 2}},
    "transactions": [
        {"description": "Investment", "type": "Capital Call: Investments", "amount": "$2,803,479.57", "inside_outside": "Inside", "page": 1},
        {"description": "Fee", "type": "Capital Call: Management Fees", "amount": "$11,651.11", "inside_outside": "Inside", "page": 1},
        {"description": "Within commitment", "type": "Capital Call: Total Amount - Inside Fund", "amount": "$2,815,130.68", "inside_outside": "Inside", "page": 1},
        {"description": "Investment", "type": "Capital Call: Investments", "amount": "$2,803,479.57", "inside_outside": "Inside", "page": 1},
    ],
    "bank": {"bank_name": "Bank Banque du Rhin SA", "account_number": "621262534", "page": 1},
}
BALANCES = {"fields": {"lp_unfunded_prior": "$6,000,000.00", "lp_unfunded_incl": "$3,184,869.32",
                       "lp_unfunded_impact_current": "$2,815,130.68", "lp_expired_released": "0.00",
                       "lp_pct_of_unfunded": "0.6667%", "lp_recallable_balance": "$200,000.00",
                       "lp_cum_contributions_prior": "$9,999,999.99"}}


def fake(system, user):
    return json.dumps(BALANCES if "THIS LP's figures" in user else IDENTITY)


def run():
    return extract(PDF, MockProvider(fake))


def test_figures_not_on_any_page_are_dropped():
    r = run()
    assert r.notice.lp_cum_contributions_prior is None
    assert any("not found on any page" in w["warning"] for w in r.warnings)


def test_page_corrected_to_where_the_figure_is():
    r = run()
    assert r.notice.pages["lp_commitment"] == 1


def test_sign_of_unfunded_change_follows_prior_and_after():
    assert str(run().notice.lp_unfunded_impact_current) == "-2815130.68"


def test_zero_adjustment_and_unprinted_shares_and_recallable_dropped():
    n = run().notice
    assert n.lp_expired_released is None
    assert n.lp_pct_of_unfunded is None  # page never links "unfunded" to a percentage
    assert n.lp_recallable_balance is None  # page never says "recallable"


def test_subtotals_and_duplicates_removed():
    types = [t.transaction_type.name for t in run().notice.transactions]
    assert types == ["CC_INVESTMENTS", "CC_MGMT_FEES"]


def test_labels_stripped_and_us_date_read():
    n = run().notice
    assert n.lp_name == "Teesdale Local Government Pension Fund"
    assert n.bank.bank_name == "Banque du Rhin SA"
    assert str(n.notice_date) == "2023-03-16"


def test_salvage_cut_off_repeating_answer():
    from drawbook.extract import _json
    t = '{\n "kind": "capital_account_statement",\n "fields": {\n  "fund_name": "X Fund",\n  "lp_commitment": "50",\n  "lp_commitment": "50",\n  "fund_si'
    d = _json(t)
    assert d["kind"] == "capital_account_statement" and d["fields"]["fund_name"] == "X Fund"
