"""Page text: the PDF text layer first, OCR (tesseract) for pages with no usable text."""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pdfplumber

MIN_CHARS = 40  # a page with less text than this is treated as scanned


@dataclass
class Page:
    number: int  # 1-based
    text: str
    ocr: bool


def ocr_page(pdf: Path, number: int, dpi: int = 300) -> str:
    if not shutil.which("tesseract") or not shutil.which("pdftoppm"):
        raise RuntimeError("scanned page found but tesseract/pdftoppm are not installed (brew install tesseract poppler)")
    with tempfile.TemporaryDirectory() as d:
        base = Path(d) / "p"
        subprocess.run(["pdftoppm", "-r", str(dpi), "-f", str(number), "-l", str(number), "-png", "-singlefile",
                        str(pdf), str(base)], check=True, capture_output=True)
        out = subprocess.run(["tesseract", f"{base}.png", "-", "--psm", "6"], check=True, capture_output=True, text=True)
        return out.stdout


def layout_text(pg) -> str:
    """Keep table columns: lay the text out by position, then mark wide gaps with ' | '."""
    raw = pg.extract_text(layout=True) or ""
    lines = []
    for ln in raw.splitlines():
        ln = re.sub(r" {3,}", " | ", ln.strip())
        if ln:
            lines.append(ln)
    return "\n".join(lines)


def read_pages(pdf: Path, ocr: bool = True) -> list[Page]:
    pages = []
    with pdfplumber.open(pdf) as doc:
        for i, pg in enumerate(doc.pages, start=1):
            text = layout_text(pg)
            if len(text.strip()) < MIN_CHARS and ocr:
                pages.append(Page(i, ocr_page(pdf, i), True))
            else:
                pages.append(Page(i, text, False))
    return pages
