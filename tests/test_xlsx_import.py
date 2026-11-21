"""Step 6a: a filled ILPA template round-trips into the ledger with all fields equal."""
from datetime import datetime
from pathlib import Path

import openpyxl
import pytest

from common import make_fund, make_sequence
from drawbook import xlsx_import

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "sources" / "ILPA-Capital-Call-Distribution-Template-v2.0.xlsx"
COMPARE = ["kind", "notice_date", "due_date", "fund_name", "fund_currency", "fund_size", "gp_commitment",
           "fund_contributions_current", "lp_id", "lp_commitment", "lp_pct_of_fund", "lp_contributions_current",
           "lp_distributions_current", "lp_cum_contributions_prior", "lp_cum_contributions_incl",
           "lp_cum_distributions_prior", "lp_cum_distributions_incl", "lp_unfunded_prior",
           "lp_unfunded_impact_current", "lp_unfunded_incl", "lp_outside_outflow_current", "lp_net_called_distributed"]


def fill(key, path):
    wb = openpyxl.load_workbook(TEMPLATE)
    ws = wb["Call & Distribution Template"]
    ws["G1"], ws["G2"] = datetime.combine(key.notice_date, datetime.min.time()), datetime.combine(key.due_date, datetime.min.time())
    ws["C3"], ws["C4"], ws["C5"], ws["C6"] = key.fund_name, key.fund_currency, float(key.fund_size), float(key.gp_commitment)
    ws["F6"] = float(key.fund_contributions_current or 0)
    ws["G6"] = float(key.fund_distributions_current or 0)
    ws["C10"], ws["C11"] = key.lp_id, float(key.lp_commitment)
    ws["F12"], ws["G12"] = float(key.lp_cum_contributions_prior), float(key.lp_cum_distributions_prior)
    ws["C16"] = float(key.lp_unfunded_prior)
    for r in range(24, 54):
        for col in "BEHIL":
            ws[f"{col}{r}"] = None
    for i, t in enumerate(key.transactions):
        r = 24 + i
        ws[f"B{r}"], ws[f"E{r}"], ws[f"H{r}"] = t.description, t.transaction_type.value, float(t.lp_amount)
        ws[f"I{r}"], ws[f"L{r}"] = t.impact_on_unfunded.value, t.inside_outside.value
    wb.save(path)


@pytest.mark.skipif(not TEMPLATE.exists(), reason="ILPA template not downloaded: run python tools/fetch_ilpa.py")
def test_round_trip(tmp_path):
    keys = make_sequence(make_fund(301, "USD"), 401, n=3)
    keys += make_sequence(make_fund(302, "EUR"), 402, n=2, kinds=None)
    for i, key in enumerate(keys):
        p = tmp_path / f"t{i}.xlsx"
        fill(key, p)
        assert xlsx_import.is_ilpa_template(p)
        got = xlsx_import.read(p)
        for f in COMPARE:
            a, b = getattr(got, f), getattr(key, f)
            if f == "lp_pct_of_fund":
                assert abs(a - b) < 1e-6, f
            elif f == "kind":
                assert a == b, (i, f, a, b)
            else:
                assert a == b, (i, f, a, b)
        assert [(t.transaction_type, t.lp_amount, t.inside_outside, t.impact_on_unfunded) for t in got.transactions] == \
               [(t.transaction_type, t.lp_amount, t.inside_outside, t.impact_on_unfunded) for t in key.transactions]
