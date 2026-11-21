"""Filing copies documents to <fund>/<date>-<kind>[-n].pdf, never overwriting or deleting."""
from datetime import date

from drawbook.filing import file_documents, safe_name
from drawbook.schema import Notice


def N(f, kind, d, fund="Alpha Fund III, L.P."):
    return Notice(source_file=f, kind=kind, notice_date=d, fund_name=fund, fund_currency="USD")


def test_file_documents(tmp_path):
    src, dest = tmp_path / "in", tmp_path / "filed"
    src.mkdir()
    for f in ("a.pdf", "b.pdf", "c.PDF", "d.pdf"):
        (src / f).write_bytes(f.encode())
    ns = [N("a.pdf", "capital_call", date(2026, 3, 1)), N("b.pdf", "capital_call", date(2026, 3, 1)),
          N("c.PDF", "capital_account_statement", None), N("d.pdf", "distribution", date(2026, 5, 2), fund="Beta/Fund")]
    m = file_documents(ns, src, dest)
    fund = dest / "Alpha Fund III_ L.P"
    assert m[str(src / "a.pdf")] == str(fund / "2026-03-01-capital-call.pdf")
    assert m[str(src / "b.pdf")] == str(fund / "2026-03-01-capital-call-2.pdf")
    assert m[str(src / "c.PDF")] == str(fund / "undated-capital-account-statement.pdf")
    assert m[str(src / "d.pdf")] == str(dest / "Beta_Fund" / "2026-05-02-distribution.pdf")
    assert (fund / "2026-03-01-capital-call-2.pdf").read_bytes() == b"b.pdf"
    assert all((src / f).exists() for f in ("a.pdf", "b.pdf", "c.PDF", "d.pdf"))  # originals kept
    # re-run: same files map to the same copies, nothing new
    assert file_documents(ns, src, dest) == m
    assert len(list(fund.iterdir())) == 3


def test_never_overwrites_other_file(tmp_path):
    src, dest = tmp_path / "in", tmp_path / "filed"
    src.mkdir()
    (src / "a.pdf").write_bytes(b"new")
    (dest / "Alpha").mkdir(parents=True)
    (dest / "Alpha" / "2026-03-01-capital-call.pdf").write_bytes(b"someone else's")
    m = file_documents([N("a.pdf", "capital_call", date(2026, 3, 1), fund="Alpha")], src, dest)
    assert m[str(src / "a.pdf")].endswith("2026-03-01-capital-call-2.pdf")
    assert (dest / "Alpha" / "2026-03-01-capital-call.pdf").read_bytes() == b"someone else's"


def test_plan_only_copies_nothing(tmp_path):
    src, dest = tmp_path / "in", tmp_path / "filed"
    src.mkdir()
    (src / "a.pdf").write_bytes(b"x")
    m = file_documents([N("a.pdf", "capital_call", date(2026, 3, 1))], src, dest, copy=False)
    assert len(m) == 1 and not dest.exists()


def test_safe_name():
    assert safe_name("../../etc") == "etc"
    assert safe_name("  ") == "unnamed"
