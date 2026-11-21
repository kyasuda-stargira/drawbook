"""Step 5 fixtures: image-only 'scanned' copies of 5 test documents (slight skew, blur, grey noise, no text layer).

usage: make_scans.py <out_dir> <pdf> [<pdf> ...]
Each copy is <stem>_scan.pdf and is scored against the original's answer key.
"""
import random
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageFilter


def scan(pdf: Path, out: Path, seed: int) -> Path:
    r = random.Random(seed)
    with tempfile.TemporaryDirectory() as d:
        subprocess.run(["pdftoppm", "-r", "200", "-gray", "-png", str(pdf), f"{d}/p"], check=True)
        imgs = []
        for png in sorted(Path(d).glob("p*.png")):
            im = Image.open(png).convert("L")
            im = im.rotate(r.uniform(-0.8, 0.8), expand=False, fillcolor=255, resample=Image.BICUBIC)
            im = im.filter(ImageFilter.GaussianBlur(0.6))
            px = im.load()
            w, h = im.size
            for _ in range(w * h // 400):
                x, y = r.randrange(w), r.randrange(h)
                px[x, y] = r.randrange(120, 230)
            imgs.append(im.convert("RGB"))
        dst = out / f"{pdf.stem}_scan.pdf"
        imgs[0].save(dst, save_all=True, append_images=imgs[1:], resolution=200)
    return dst


if __name__ == "__main__":
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    for i, p in enumerate(sys.argv[2:]):
        print(scan(Path(p), out, i))
