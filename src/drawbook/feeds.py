"""Downstream feeds: a mapping-driven CSV exporter and a plain ledger.json.

Mapping file (TOML or JSON) — one entry per output column, in order:

    date_format = "%Y-%m-%d"          # optional, the default for every date column

    [[columns]]
    header = "Trade Date"             # the target system's column name
    field = ["due_date", "notice_date"]   # a Drawbook field, or a list: first non-empty wins

    [[columns]]
    header = "Amount"
    field = "lp_amount"
    negate = "outflows"               # "always" | "outflows" | "inflows"

    [[columns]]
    header = "Type"
    field = "transaction_type"
    lookup = { "Capital Call: Investments" = "CALL" }   # Drawbook value -> target code
    default = "OTHER"                 # used when the value is empty or not in the lookup

    [[columns]]
    header = "Source"
    value = "Drawbook"                # a constant

Fields: any key of `ledger.tx_rows()` (one output row per transaction) or any `Notice` field
(fund_currency, lp_commitment, ...). Transaction fields win when both have the name.
Outflow = money the LP pays (transaction type starts "Capital Call"); everything else is an inflow.
A lookup miss with no `default` raises, so an unmapped type never slips through.
Values: dates use the date format, amounts are written exactly as read (no float rounding),
booleans as true/false, empty as "".
"""
from __future__ import annotations

import csv
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from .ledger import tx_rows
from .schema import Notice

MAPPINGS = Path(__file__).parent / "feeds"  # shipped mapping files
JSON_VERSION = 1


def load_mapping(path) -> dict:
    path = Path(path)
    text = path.read_text()
    if path.suffix == ".json":
        m = json.loads(text)
    else:
        import tomllib  # Python 3.11+; on 3.10 use a .json mapping
        m = tomllib.loads(text)
    for c in m.get("columns", []):
        if "header" not in c or ("field" in c) == ("value" in c):
            raise ValueError(f"{path}: each column needs a header and exactly one of field/value: {c}")
        if c.get("negate") not in (None, "always", "outflows", "inflows"):
            raise ValueError(f"{path}: negate must be always, outflows or inflows: {c}")
    return m


def _sorted(notices: list[Notice]) -> list[Notice]:
    return sorted(notices, key=lambda n: (n.fund_name, n.notice_date or date.min))


def _cell(col: dict, row: dict, date_format: str) -> str:
    if "value" in col:
        return str(col["value"])
    names = col["field"] if isinstance(col["field"], list) else [col["field"]]
    for name in names:
        if name not in row:
            raise KeyError(f"unknown Drawbook field {name!r} in column {col['header']!r}")
    v = next((row[n] for n in names if row[n] not in (None, "")), None)
    if hasattr(v, "value"):  # enums
        v = v.value
    if "lookup" in col and v is not None:
        if v in col["lookup"]:
            v = col["lookup"][v]
        elif "default" in col:
            v = col["default"]
        else:
            raise KeyError(f"column {col['header']!r}: no lookup entry for {v!r}")
    if v is None:
        v = col.get("default")
    neg = col.get("negate")
    if isinstance(v, Decimal) and neg:
        outflow = str(row.get("transaction_type", "")).startswith("Capital Call")
        if neg == "always" or (neg == "outflows") == outflow:
            v = -v
    if v is None:
        return ""
    if isinstance(v, date):
        return v.strftime(col.get("date_format", date_format))
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def rows(notices: list[Notice], mapping: dict) -> list[list[str]]:
    """Header row plus one row per transaction, per the mapping."""
    cols, fmt = mapping["columns"], mapping.get("date_format", "%Y-%m-%d")
    out = [[c["header"] for c in cols]]
    for n in _sorted(notices):
        base = {k: getattr(n, k) for k in Notice.model_fields if k != "transactions"}
        for t in tx_rows([n]):
            out.append([_cell(c, base | t, fmt) for c in cols])
    return out


def export(notices: list[Notice], mapping_path, out_path) -> Path:
    """Write a CSV in the column layout the mapping file describes."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="") as f:
        csv.writer(f).writerows(rows(notices, load_mapping(mapping_path)))
    return out_path


def ledger_json(notices: list[Notice]) -> dict:
    """Stable shape: {"drawbook_ledger_version": 1, "notices": [notice + "transactions": [...]]}.

    Each notice carries every Notice field except `bank` (payment details stay out of feeds).
    Each transaction adds `net_called_distributed` and `unfunded_impact_value` from ledger.tx_rows.
    Amounts are strings (exact decimals), dates ISO 8601, missing values null.
    """
    out = []
    for n in _sorted(notices):
        d = n.model_dump(mode="json", exclude={"bank"})
        for t, r in zip(d["transactions"], tx_rows([n])):
            t["net_called_distributed"] = str(r["net_called_distributed"])
            t["unfunded_impact_value"] = str(r["unfunded_impact_value"])
        out.append(d)
    return {"drawbook_ledger_version": JSON_VERSION, "notices": out}


def write_json(notices: list[Notice], out_path) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(ledger_json(notices), indent=2) + "\n")
    return out_path
