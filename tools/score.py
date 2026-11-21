"""Score extracted notices against answer keys.

A field counts when the answer key fills it. It is right when the value matches exactly
(figures to the cent, percentages to 1e-6, dates equal, text equal ignoring case and spacing).
Transactions: each key line counts as 4 fields (type, amount, inside/outside, impact); a predicted
line is matched by amount. Bank: account_number, sort_code, swift_bic, bank_name.
Also reports 'extra' figures the extractor filled that the key leaves empty (possible inventions).
"""
from __future__ import annotations

import re
from decimal import Decimal

from drawbook.schema import Notice

SKIP = {"source_file", "transactions", "bank", "pages"}


def _eq(a, b) -> bool:
    """Exact, except: a whole-unit figure counts as right when the key rounds to it, because some GPs
    print amounts without cents and the document then shows only the rounded figure."""
    if a is None or b is None:
        return False
    if isinstance(a, Decimal) or isinstance(b, Decimal):
        try:
            a, b = Decimal(a), Decimal(b)
            if abs(b) >= 1 and a == a.to_integral_value() and abs(a - b) <= Decimal("0.5"):
                return True
            return abs(a - b) <= (Decimal("0.000001") if abs(b) < 1 else Decimal("0.005"))
        except Exception:  # noqa: BLE001
            return False
    if isinstance(a, str) and isinstance(b, str):
        return " ".join(a.lower().split()) == " ".join(b.lower().split())
    return a == b


def _bank_norm(v):
    return re.sub(r"[^0-9a-z]", "", (v or "").lower()) or None


def score(pred: Notice | None, key: Notice) -> dict:
    right, total, misses, extra = 0, 0, [], []
    kd = key.model_dump()
    pd_ = pred.model_dump() if pred else {}
    for f, v in kd.items():
        if f in SKIP or v is None or (f == "kind"):
            continue
        total += 1
        if _eq(pd_.get(f), v):
            right += 1
        else:
            misses.append(f"{f}: want {v} got {pd_.get(f)}")
    if pred:
        for f, v in pd_.items():
            if f not in SKIP and v is not None and kd.get(f) is None and f != "kind":
                extra.append(f"{f}={v}")
    # kind
    total += 1
    if pred and pred.kind == key.kind:
        right += 1
    else:
        misses.append(f"kind: want {key.kind.value} got {pred.kind.value if pred else None}")
    # transactions
    pool = list(pred.transactions) if pred else []
    for t in key.transactions:
        total += 4
        m = next((p for p in pool if _eq(p.lp_amount, t.lp_amount)), None)
        if not m:
            misses.append(f"tx missing: {t.transaction_type.value} {t.lp_amount}")
            continue
        pool.remove(m)
        right += 1
        for attr in ("transaction_type", "inside_outside", "impact_on_unfunded"):
            if getattr(m, attr) == getattr(t, attr):
                right += 1
            else:
                misses.append(f"tx {t.lp_amount} {attr}: want {getattr(t, attr).value} got {getattr(m, attr).value}")
    extra += [f"tx extra: {p.transaction_type.value} {p.lp_amount}" for p in pool]
    if key.bank:
        for f in ("account_number", "sort_code", "swift_bic", "bank_name"):
            kv = getattr(key.bank, f)
            if not kv:
                continue
            total += 1
            pv = getattr(pred.bank, f) if pred and pred.bank else None
            if _bank_norm(pv) == _bank_norm(kv):
                right += 1
            else:
                misses.append(f"bank.{f}: want {kv} got {pv}")
    return {"right": right, "total": total, "misses": misses, "extra": extra}
