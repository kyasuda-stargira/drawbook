"""Feeds: mapping CSV exporter, ledger.json, Addepar payload builder. No network (conftest blocks it)."""
import csv
import json
from datetime import date
from decimal import Decimal

import pytest

from drawbook import addepar, feeds
from drawbook.schema import (BankDetails, InsideOutside, Notice, NoticeKind, Transaction, TransactionType as T,
                             UnfundedImpact)


def tx(tt, amt, unf=UnfundedImpact.DECREASE, io=InsideOutside.INSIDE, recallable=None, page=1):
    return Transaction(description=tt.value.split(": ")[1], transaction_type=tt, lp_amount=Decimal(amt),
                       impact_on_unfunded=unf, inside_outside=io, recallable=recallable, page=page)


@pytest.fixture
def notices():
    call = Notice(source_file="call.pdf", kind=NoticeKind.CAPITAL_CALL, notice_date=date(2026, 3, 1),
                  due_date=date(2026, 3, 15), fund_name="Fund A", fund_currency="USD", lp_id="LP7",
                  lp_commitment=Decimal("1000000"),
                  bank=BankDetails(account_number="12345678"),
                  transactions=[tx(T.CC_INVESTMENTS, "100000.10"), tx(T.CC_MGMT_FEES, "2500.00", page=2),
                                tx(T.CC_PLACEMENT, "10.00", unf=UnfundedImpact.NO_IMPACT, io=InsideOutside.OUTSIDE)])
    dist = Notice(source_file="dist.pdf", kind=NoticeKind.DISTRIBUTION, notice_date=date(2026, 6, 30),
                  fund_name="Fund A", fund_currency="USD", lp_id="LP7",
                  transactions=[tx(T.D_ROC_CASH, "40000", unf=UnfundedImpact.NO_IMPACT),
                                tx(T.D_OTHER, "500", unf=UnfundedImpact.INCREASE, recallable=True),
                                tx(T.D_ROC_STOCK, "7", unf=UnfundedImpact.NO_IMPACT)])
    return [dist, call]  # out of order on purpose


def read(p):
    with open(p, newline="") as f:
        return list(csv.reader(f))


def test_template_mapping(notices, tmp_path):
    out = feeds.export(notices, feeds.MAPPINGS / "template.toml", tmp_path / "x.csv")
    r = read(out)
    assert r[0] == ["Date", "Fund", "Investor ID", "Type", "Amount", "Currency", "Description", "Source", "Page"]
    assert len(r) == 7
    assert r[1] == ["2026-03-15", "Fund A", "LP7", "CALL", "-100000.10", "USD", "Investments", "call.pdf", "1"]
    assert r[2][3:5] == ["CALL_FEE", "-2500.00"] and r[2][8] == "2"
    assert r[3][3] == "OTHER"  # placement fee not in lookup -> default
    assert r[4][0] == "2026-06-30" and r[4][3:5] == ["DIST_ROC", "40000"]  # no due date -> notice date; inflow kept positive


def test_json_mapping_transforms(notices, tmp_path):
    m = tmp_path / "m.json"
    m.write_text(json.dumps({"date_format": "%d/%m/%Y", "columns": [
        {"header": "D", "field": "notice_date"},
        {"header": "US", "field": "notice_date", "date_format": "%m/%d/%Y"},
        {"header": "Amt", "field": "net_called_distributed", "negate": "always"},
        {"header": "Commit", "field": "lp_commitment"},
        {"header": "Rec", "field": "recallable"},
        {"header": "K", "value": "drawbook"}]}))
    r = read(feeds.export(notices, m, tmp_path / "y.csv"))
    assert r[1] == ["01/03/2026", "03/01/2026", "-100000.10", "1000000", "", "drawbook"]
    assert r[5] == ["30/06/2026", "06/30/2026", "500", "", "true", "drawbook"]  # distribution: net -500, negated


def test_lookup_miss_raises(notices, tmp_path):
    m = tmp_path / "m.json"
    m.write_text(json.dumps({"columns": [{"header": "T", "field": "transaction_type", "lookup": {"x": "y"}}]}))
    with pytest.raises(KeyError, match="no lookup entry"):
        feeds.export(notices, m, tmp_path / "z.csv")


def test_bad_mapping_rejected(tmp_path):
    m = tmp_path / "m.json"
    m.write_text(json.dumps({"columns": [{"header": "T", "field": "fund_name", "value": "x"}]}))
    with pytest.raises(ValueError):
        feeds.load_mapping(m)
    m.write_text(json.dumps({"columns": [{"header": "T", "field": "no_such_field"}]}))
    with pytest.raises(KeyError, match="unknown Drawbook field"):
        feeds.rows([Notice(source_file="a", kind=NoticeKind.DISTRIBUTION, fund_name="F", fund_currency="USD",
                            transactions=[tx(T.D_OTHER, "1")])], feeds.load_mapping(m))


def test_ledger_json(notices, tmp_path):
    d = json.loads(feeds.write_json(notices, tmp_path / "ledger.json").read_text())
    assert d["drawbook_ledger_version"] == 1
    assert [n["source_file"] for n in d["notices"]] == ["call.pdf", "dist.pdf"]
    first = d["notices"][0]
    assert "bank" not in first
    assert first["due_date"] == "2026-03-15" and first["lp_commitment"] == "1000000"
    t = first["transactions"][0]
    assert t["lp_amount"] == "100000.10" and t["net_called_distributed"] == "100000.10"
    assert t["unfunded_impact_value"] == "-100000.10" and t["page"] == 1
    assert d["notices"][1]["transactions"][0]["net_called_distributed"] == "-40000"


def test_addepar_payloads(notices):
    payloads, skipped = addepar.build_payloads(notices, owner_id=183, owned_ids={"Fund A": "2260710"})
    assert len(payloads) == 1
    data = payloads[0]["data"]
    assert len(data) == 5
    a = data[0]["attributes"]
    assert a == {"type": "contribution", "currency": "USD", "trade_date": "2026-03-15", "amount": 100000.10,
                 "comment": "Investments (call.pdf p1)", "contribution_investment": 100000.10,
                 "affects_unfunded_commitment": True}
    assert data[0]["relationships"] == {"owner": {"data": {"type": "entities", "id": "183"}},
                                        "owned": {"data": {"type": "entities", "id": "2260710"}}}
    assert data[1]["attributes"]["contribution_management_fee"] == 2500.0
    assert data[2]["attributes"]["contribution_generic"] == 10.0
    assert data[2]["attributes"]["affects_unfunded_commitment"] is False  # outside-fund fee
    assert data[3]["attributes"]["type"] == "distribution" and data[3]["attributes"]["return_of_capital"] == 40000.0
    assert data[3]["attributes"]["trade_date"] == "2026-06-30"
    assert data[4]["attributes"]["recallable"] == 500.0
    assert [s["reason"] for s in skipped] == ["in-kind distribution: no cash type mapped"]


def test_addepar_missing_fund_and_batching(notices):
    _, skipped = addepar.build_payloads(notices, "1", {})
    assert len(skipped) == 6 and all("entity ID" in s["reason"] or "in-kind" in s["reason"] for s in skipped)
    many = [Notice(source_file=f"{i}.pdf", kind=NoticeKind.CAPITAL_CALL, notice_date=date(2026, 1, 1),
                   fund_name="F", fund_currency="EUR", transactions=[tx(T.CC_INVESTMENTS, "1")]) for i in range(501)]
    payloads, _ = addepar.build_payloads(many, "1", {"F": "2"})
    assert [len(p["data"]) for p in payloads] == [500, 1]


def test_addepar_send_needs_explicit_target():
    with pytest.raises(ValueError):
        addepar.send([{"data": []}], "", "", "")
