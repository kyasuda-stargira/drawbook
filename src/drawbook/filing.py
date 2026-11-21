"""Rename and file read documents as <dest_root>/<Fund name>/<yyyy-mm-dd>-<kind>[-n].<ext>.

Originals are never moved or deleted, and an existing file is never overwritten.
"""
from __future__ import annotations

import hashlib
import re
import shutil
from pathlib import Path

from .schema import Notice


def safe_name(s: str, limit: int = 100) -> str:
    s = re.sub(r"[^A-Za-z0-9 ._&()-]+", "_", s)
    s = re.sub(r"\s+", " ", s).strip(" ._")
    return s[:limit] or "unnamed"


def _digest(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def file_documents(notices: list[Notice], src_folder: Path, dest_root: Path, copy: bool = True) -> dict[str, str]:
    """Copy each notice's source file to its filed name. Returns {old path: new path}.

    copy=False plans the names without copying anything. A file already filed with identical
    content maps to that copy instead of making another.
    """
    src_folder, dest_root = Path(src_folder), Path(dest_root)
    taken: set[Path] = set()
    out = {}
    for n in sorted(notices, key=lambda n: (n.fund_name, n.notice_date is None, n.notice_date, n.source_file)):
        src = src_folder / n.source_file
        if not src.is_file():
            continue
        folder = dest_root / safe_name(n.fund_name)
        stem = f"{n.notice_date.isoformat() if n.notice_date else 'undated'}-{n.kind.value.replace('_', '-')}"
        i = 1
        while True:
            dest = folder / f"{stem}{'' if i == 1 else f'-{i}'}{src.suffix.lower()}"
            if dest not in taken and dest.exists() and _digest(dest) == _digest(src):
                break  # already filed on an earlier run
            if dest not in taken and not dest.exists():
                if copy:
                    folder.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dest)
                break
            i += 1
        taken.add(dest)
        out[str(src)] = str(dest)
    return out
