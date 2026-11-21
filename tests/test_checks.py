"""Step 4: seeded errors in 5 notices are all caught; clean sequences raise no alarm.

Uses answer keys from the tuning families (A, B) only; family C stays held out.
"""
from decimal import Decimal
from pathlib import Path

import pytest

from common import read_key
from drawbook import checks

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "testset" / "build"
if (ROOT / "testset" / "locked").exists():
    BUILD = ROOT / "testset" / "locked"


def seq(family, fund):
    return [read_key(p) for p in sorted((BUILD / family).glob(f"{family[-1]}_fund{fund}_n*.json"))]


@pytest.mark.parametrize("family,fund", [("family_a", 1), ("family_a", 2), ("family_a", 3),
                                         ("family_b", 1), ("family_b", 2), ("family_b", 3)])
def test_clean_sequences_raise_nothing(family, fund):
    s = seq(family, fund)
    assert len(s) >= 3
    assert checks.run(s) == []


def _caught(notices, file, word):
    return [w for w in checks.run(notices) if w["file"] == file and word in w["warning"]]


def test_seeded_errors_all_caught():
    seeds = []
    # 1 changed account number (fund A1, notice 3)
    s = seq("family_a", 1); n = s[2]; n.bank.account_number = "999999999"; seeds.append((s, n.source_file, "PAYMENT DETAILS CHANGED"))
    # 2 changed sort code / routing (fund B1, notice 2)
    s = seq("family_b", 1); n = s[1]; n.bank.sort_code = "111000025"; seeds.append((s, n.source_file, "PAYMENT DETAILS CHANGED"))
    # 3 unfunded before this notice does not match the previous notice (fund A2, notice 2)
    s = seq("family_a", 2); n = s[1]; n.lp_unfunded_prior += Decimal("50000"); n.lp_unfunded_incl += Decimal("50000")
    seeds.append((s, n.source_file, "does not match"))
    # 4 unfunded does not tie inside one notice (fund A3, notice 1)
    s = seq("family_a", 3); n = s[0]; n.lp_unfunded_incl -= Decimal("1250.00"); seeds.append((s, n.source_file, "unfunded does not tie"))
    # 5 line items do not add up to the amount called (fund B3, first call)
    s = seq("family_b", 3); n = next(x for x in s if x.transactions and x.lp_contributions_current)
    n.transactions[0].lp_amount += Decimal("10.00"); seeds.append((s, n.source_file, "do not add up"))
    caught = [bool(_caught(*x)) for x in seeds]
    assert caught == [True] * 5, caught


def test_bank_change_ignores_formatting():
    s = seq("family_a", 1)
    s[1].bank.account_number = " ".join(s[1].bank.account_number)  # same digits, spaced
    assert not [w for w in checks.run(s) if "PAYMENT" in w["warning"]]
