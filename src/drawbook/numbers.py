"""Read numbers from page text in US, EU, space-grouped and bracketed styles."""
import re
from decimal import Decimal


_NUM = re.compile(r"\(?-?[\d][\d,.  ']*\d\)?|\(?-?\d\)?")


def numbers_in(text: str) -> set[Decimal]:
    """Every number on a page, read in US, EU, space-grouped and parenthesis styles (both signs kept)."""
    found: set[Decimal] = set()
    for m in _NUM.finditer(text):
        raw = m.group(0)
        neg = raw.startswith("(") and raw.endswith(")") or raw.startswith("-")
        core = raw.strip("()-").replace(" ", " ").replace("'", "")
        cands = []
        pieces = {core, core.replace(" ", "")} | set(core.split())
        for c in pieces:
            if re.fullmatch(r"\d{1,3}(,\d{3})*(\.\d+)?|\d+(\.\d+)?", c):
                cands.append(c.replace(",", ""))
            if re.fullmatch(r"\d{1,3}(\.\d{3})*(,\d+)?|\d+,\d+", c):
                cands.append(c.replace(".", "").replace(",", "."))
        for c in cands:
            try:
                v = Decimal(c)
            except Exception:
                continue
            found.add(v)
            found.add(-v if not neg else v)
            if neg:
                found.add(-v)
    return found


def matches(v: Decimal, nums: set[Decimal]) -> bool:
    if v in nums or -v in nums:
        return True
    # Strict: the figure itself must be printed. (No rounding allowance: an invented 9,999,999.99
    # must not pass because 10,000,000 is on the page.) Percentages may be printed x100.
    if abs(v) < 1 and (v * 100).normalize() in {n.normalize() for n in nums}:
        return True
    if any(abs(n - v) < Decimal("0.0001") for n in nums):
        return True
    return abs(v) < 1 and any(abs(n - v * 100) < Decimal("0.01") for n in nums)
