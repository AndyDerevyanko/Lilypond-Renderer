"""Pixel-diff lilyrender's page images against the real LilyPond reference.

Usage:
    py -3 scripts/compare_pages.py [--real DIR] [--yours DIR]
        [--threshold N] [--regions N] [--diff-dir DIR]
        [--dump-coords DIR] [--json PATH]

Pairs pages by their `_page-NNNN` number (default dirs:
real_test/real_output vs real_test/your_output) and reports, per page and in
total, how many pixels are wrong and the percentage. A pixel is wrong when
the grayscale difference exceeds --threshold (default 40, which ignores JPEG
compression noise but catches real ink differences). Pages that differ
slightly in size are cropped to their common size first; a page present on
only one side counts as 100% wrong.

Finding WHERE the wrong pixels are:
  --regions N       print the N largest connected clusters of wrong pixels
                    per page as pixel bounding boxes (x0,y0)-(x1,y1)
  --diff-dir DIR    write one PNG per page: the reference faded to light
                    gray with every wrong pixel drawn in solid red
  --dump-coords DIR write every wrong pixel as an "x y" line, one text file
                    per page (exhaustive; files can be large)
  --json PATH       machine-readable per-page results for scripted iteration
"""
import argparse
import glob
import json
import os
import re
import sys

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_REAL = os.path.join(ROOT, "real_test", "real_output")
DEFAULT_YOURS = os.path.join(ROOT, "real_test", "your_output")

PAGE_RE = re.compile(r"_page-(\d+)\.(?:jpg|jpeg|png)$", re.IGNORECASE)


def index_pages(folder):
    """Map page number -> image path for every *_page-NNNN.* file in folder."""
    pages = {}
    for path in glob.glob(os.path.join(folder, "*")):
        m = PAGE_RE.search(os.path.basename(path))
        if m:
            pages[int(m.group(1))] = path
    return pages


def load_gray(path):
    return np.asarray(Image.open(path).convert("L"), dtype=np.int16)


def wrong_mask(real, yours, threshold):
    """Boolean mask of wrong pixels over the two pages' common size."""
    h = min(real.shape[0], yours.shape[0])
    w = min(real.shape[1], yours.shape[1])
    return np.abs(real[:h, :w] - yours[:h, :w]) > threshold


def find_regions(mask, cell=16):
    """Cluster wrong pixels into rectangles.

    Buckets the mask into cell x cell blocks, flood-fills 8-connected
    non-empty blocks, and returns [(count, x0, y0, x1, y1), ...] sorted by
    count descending. Cheap even on full pages, precise enough to say where
    to look.
    """
    h, w = mask.shape
    ch = -(-h // cell)
    cw = -(-w // cell)
    padded = np.zeros((ch * cell, cw * cell), dtype=bool)
    padded[:h, :w] = mask
    counts = padded.reshape(ch, cell, cw, cell).sum(axis=(1, 3))

    seen = np.zeros_like(counts, dtype=bool)
    regions = []
    for cy in range(ch):
        for cx in range(cw):
            if counts[cy, cx] == 0 or seen[cy, cx]:
                continue
            stack = [(cy, cx)]
            seen[cy, cx] = True
            total = 0
            y0 = x0 = 1 << 30
            y1 = x1 = -1
            while stack:
                y, x = stack.pop()
                total += int(counts[y, x])
                y0, x0 = min(y0, y), min(x0, x)
                y1, x1 = max(y1, y), max(x1, x)
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        ny, nx = y + dy, x + dx
                        if (0 <= ny < ch and 0 <= nx < cw
                                and counts[ny, nx] and not seen[ny, nx]):
                            seen[ny, nx] = True
                            stack.append((ny, nx))
            regions.append((total,
                            x0 * cell, y0 * cell,
                            min((x1 + 1) * cell, w) - 1,
                            min((y1 + 1) * cell, h) - 1))
    regions.sort(reverse=True)
    return regions


def write_diff_image(real, mask, out_path):
    """Reference faded to light gray, wrong pixels in solid red."""
    h, w = mask.shape
    base = 255 - (255 - real[:h, :w]) // 4        # faint copy of the reference
    rgb = np.dstack([base, base, base]).astype(np.uint8)
    rgb[mask] = (220, 0, 0)
    Image.fromarray(rgb).save(out_path)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--real", default=DEFAULT_REAL,
                    help="reference page image folder")
    ap.add_argument("--yours", default=DEFAULT_YOURS,
                    help="lilyrender page image folder")
    ap.add_argument("--threshold", type=int, default=40,
                    help="grayscale difference above this counts as wrong")
    ap.add_argument("--regions", type=int, default=0, metavar="N",
                    help="print the N largest wrong-pixel clusters per page")
    ap.add_argument("--diff-dir", default=None,
                    help="write per-page diff overlay PNGs here")
    ap.add_argument("--dump-coords", default=None,
                    help="write every wrong pixel's 'x y' to text files here")
    ap.add_argument("--json", default=None,
                    help="write per-page results to this JSON file")
    args = ap.parse_args()

    real_pages = index_pages(args.real)
    your_pages = index_pages(args.yours)
    if not real_pages:
        print(f"no page images found in {args.real}", file=sys.stderr)
        return 2
    if not your_pages:
        print(f"no page images found in {args.yours}", file=sys.stderr)
        return 2

    for d in (args.diff_dir, args.dump_coords):
        if d:
            os.makedirs(d, exist_ok=True)

    all_nums = sorted(set(real_pages) | set(your_pages))
    results = []
    total_wrong = total_px = 0

    for num in all_nums:
        rp = real_pages.get(num)
        yp = your_pages.get(num)
        if rp is None or yp is None:
            img = load_gray(yp if rp is None else rp)
            area = img.shape[0] * img.shape[1]
            side = "reference" if rp is None else "yours"
            print(f"page {num:2d}: 100.0000% wrong "
                  f"({area} px, page missing from {side})")
            results.append({"page": num, "wrong": area, "total": area,
                            "percent": 100.0, "missing_from": side})
            total_wrong += area
            total_px += area
            continue

        real = load_gray(rp)
        yours = load_gray(yp)
        mask = wrong_mask(real, yours, args.threshold)
        wrong = int(mask.sum())
        area = mask.size
        pct = 100.0 * wrong / area
        note = ""
        if real.shape != yours.shape:
            note = (f"  (size {yours.shape[1]}x{yours.shape[0]} vs "
                    f"{real.shape[1]}x{real.shape[0]}, cropped to common)")
        print(f"page {num:2d}: {pct:8.4f}% wrong ({wrong}/{area} px){note}")
        results.append({"page": num, "wrong": wrong, "total": area,
                        "percent": pct})
        total_wrong += wrong
        total_px += area

        if args.regions and wrong:
            for i, (cnt, x0, y0, x1, y1) in \
                    enumerate(find_regions(mask)[:args.regions]):
                print(f"    region {i + 1}: ({x0},{y0})-({x1},{y1})  "
                      f"{cnt} wrong px")
        if args.diff_dir:
            write_diff_image(real, mask,
                             os.path.join(args.diff_dir,
                                          f"diff_page-{num:04d}.png"))
        if args.dump_coords and wrong:
            ys, xs = np.nonzero(mask)
            out = os.path.join(args.dump_coords, f"page-{num:04d}.txt")
            with open(out, "w") as f:
                for x, y in zip(xs.tolist(), ys.tolist()):
                    f.write(f"{x} {y}\n")

    overall = 100.0 * total_wrong / total_px if total_px else 0.0
    print(f"\nTOTAL: {overall:.4f}% wrong "
          f"({total_wrong}/{total_px} px over {len(all_nums)} pages)")

    if args.json:
        with open(args.json, "w") as f:
            json.dump({"threshold": args.threshold, "pages": results,
                       "total_wrong": total_wrong, "total_px": total_px,
                       "percent": overall}, f, indent=2)
        print(f"wrote {args.json}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
