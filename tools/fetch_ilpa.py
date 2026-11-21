"""Download ILPA's public Capital Call & Distribution Template files into sources/.

ILPA's files are copyright ILPA and are not included in this repository. This script fetches them
from ilpa.org on your own machine. They are needed only for the field-map check, the Excel import
test and the ILPA sample-letter test document; Drawbook itself runs without them.
"""
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = {
    "ILPA-Capital-Call-Distribution-Template-v2.0.xlsx":
        "https://ilpa.org/wp-content/uploads/2025/09/ILPA-Capital-Call-Distribution-Template-v.-2.0.xlsx",
    "ILPA-Suggested-Guidance-2025-Final.pdf":
        "https://ilpa.org/wp-content/uploads/2025/09/ILPA-Suggested-Guidance-2025-Final.pdf",
    "ILPA-Sample-Cover-Description-Letter-2025.pdf":
        "https://ilpa.org/wp-content/uploads/2025/10/ILPA-Sample-Cover-Description-Letter-2025.pdf",
}


def main() -> int:
    out = ROOT / "sources"
    out.mkdir(exist_ok=True)
    for name, url in FILES.items():
        dst = out / name
        if dst.exists():
            print(f"have {name}")
            continue
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (drawbook fetch_ilpa)"})
        with urllib.request.urlopen(req, timeout=60) as r:
            dst.write_bytes(r.read())
        print(f"fetched {name} ({dst.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
