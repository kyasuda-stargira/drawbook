"""Run the extractor over one test-set folder and score it.

usage: run_set.py <folder> <out.json> [--ocr-copies]
Refuses a held-out folder (named in DRAWBOOK_HELD_OUT, default "family_d") unless DRAWBOOK_SCORING=1.
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tools")]
os.environ.pop("ANTHROPIC_API_KEY", None)

from drawbook.extract import extract  # noqa: E402
from drawbook.providers import LocalProvider  # noqa: E402
from drawbook.schema import Notice  # noqa: E402
from score import score  # noqa: E402


def keep_server_alive():
    """Some local model servers stop when idle, judged by a file's time. Touch DRAWBOOK_KEEPALIVE_FILE if set."""
    f = os.environ.get("DRAWBOOK_KEEPALIVE_FILE")
    if f and Path(f).exists():
        os.utime(f, None)


def main():
    folder, out = Path(sys.argv[1]), Path(sys.argv[2])
    held = os.environ.get("DRAWBOOK_HELD_OUT", "family_d").split(",")
    if any(h and h in str(folder) for h in held) and os.environ.get("DRAWBOOK_SCORING") != "1":
        sys.exit(f"{folder} is a held-out set; score it only once per reader version (DRAWBOOK_SCORING=1)")
    prov = LocalProvider()
    rows, R, T, E = [], 0, 0, 0
    for pdf in sorted(folder.glob("*.pdf")):
        keyp = pdf.with_suffix(".json")
        if not keyp.exists():
            keyp = folder / (pdf.stem.replace("_scan", "") + ".json")
        key = Notice.model_validate_json(keyp.read_text())
        keep_server_alive()
        r = extract(pdf, prov)
        s = score(r.notice, key)
        R, T, E = R + s["right"], T + s["total"], E + len(s["extra"])
        rows.append({"file": pdf.name, **s, "warnings": r.warnings,
                     "notice": json.loads(r.notice.model_dump_json()) if r.notice else None})
        print(f"{pdf.name}: {s['right']}/{s['total']} extra={len(s['extra'])}", flush=True)
    summary = {"folder": str(folder), "right": R, "total": T, "pct": round(100 * R / T, 2) if T else 0, "extra": E}
    out.write_text(json.dumps({"summary": summary, "docs": rows}, indent=1, default=str))
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
