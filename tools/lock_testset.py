"""Step 2e: freeze the test set. Copies testset/build -> testset/locked, adds 5 scanned copies of
held-out documents, writes MANIFEST.sha256. Refuses to overwrite an existing lock."""
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD, LOCK = ROOT / "testset" / "build", ROOT / "testset" / "locked"
SCAN_FROM = ["c_fund1_n1", "c_fund1_n3", "c_fund2_n2", "c_fund3_n1", "c_fund3_n3"]


def manifest(folder: Path) -> str:
    lines = []
    for p in sorted(folder.rglob("*")):
        if p.is_file() and p.name != "MANIFEST.sha256":
            lines.append(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(folder)}")
    return "\n".join(lines) + "\n"


def main():
    if LOCK.exists():
        sys.exit("testset/locked already exists; the test set is frozen")
    shutil.copytree(BUILD, LOCK)
    scans = LOCK / "scans"
    scans.mkdir()
    subprocess.run([sys.executable, str(ROOT / "tools" / "make_scans.py"), str(scans)] +
                   [str(LOCK / "family_c" / f"{s}.pdf") for s in SCAN_FROM], check=True)
    for s in SCAN_FROM:
        shutil.copy(LOCK / "family_c" / f"{s}.json", scans / f"{s}.json")
    (LOCK / "MANIFEST.sha256").write_text(manifest(LOCK))
    print(f"locked {sum(1 for _ in LOCK.rglob('*.pdf'))} PDFs")


if __name__ == "__main__":
    main()
