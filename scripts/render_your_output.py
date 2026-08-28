"""Render a .ly file with lilyrender to a PDF, then split it into page images.

Usage:
    py -3 scripts/render_your_output.py [score.ly] [--pdf path.pdf]
                                        [--format jpg|png] [--dpi 150]

Defaults: renders real_test/chopin-op23-ballade-1.ly to
real_test/your_output.pdf, then extracts every page with
scripts/pdf_to_images.py into real_test/your_output/ (stale page images from
a previous, longer run are deleted first so the folder always matches the
current PDF exactly).

Runs headless (offscreen Qt platform); mirrors the UI's "Export PDF" action
(lilyrender.ui.export_pdf_dialog) so the output is identical to a GUI export.
"""
import argparse
import glob
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# the offscreen platform has no system font database; point it at Windows fonts
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

from PyQt5.QtGui import QGuiApplication

from lilyrender import parser, interpret, layout
from lilyrender.render_qt import export_pdf
from pdf_to_images import convert_pdf_to_images

DEFAULT_LY = os.path.join(ROOT, "real_test", "chopin-op23-ballade-1.ly")
DEFAULT_PDF = os.path.join(ROOT, "real_test", "your_output.pdf")


def render_pdf(ly_path, pdf_path):
    """Parse + engrave ly_path and write the page-mode PDF, like the UI does."""
    with open(ly_path, encoding="utf-8") as f:
        scores = parser.parse(f.read(), ly_path)
    if not scores:
        raise ValueError(f"no music found in {ly_path}")
    score = interpret.build_score(scores[0])
    geo = layout.page_geometry(score.paper)
    result = layout.engrave(score, line_width=geo["line_width"])
    staff_space_mm = geo["staff_size"] / 4.0 * 0.352778   # pt -> mm
    export_pdf(result, pdf_path, staff_space_mm=staff_space_mm,
               page_w=geo["page_w"], page_h=geo["page_h"],
               margin=geo["margin"])
    return len(result.systems)


def clear_stale_pages(pdf_path):
    """Remove old page images so a shorter render leaves no leftovers."""
    base_dir = os.path.dirname(os.path.abspath(pdf_path))
    stem = os.path.splitext(os.path.basename(pdf_path))[0]
    out_dir = os.path.join(base_dir, stem)
    removed = 0
    for old in glob.glob(os.path.join(out_dir, f"{stem}_page-*.*")):
        os.remove(old)
        removed += 1
    return removed


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("ly_path", nargs="?", default=DEFAULT_LY,
                    help="input LilyPond file")
    ap.add_argument("--pdf", default=DEFAULT_PDF, help="output PDF path")
    ap.add_argument("--format", choices=["jpg", "png"], default="jpg",
                    help="page image format")
    ap.add_argument("--dpi", type=int, default=150, help="page image dpi")
    args = ap.parse_args()

    app = QGuiApplication([])   # noqa: F841 - Qt font db needs a live app

    n_systems = render_pdf(args.ly_path, args.pdf)
    print(f"rendered {args.ly_path} ({n_systems} systems) -> {args.pdf}")

    clear_stale_pages(args.pdf)
    out_dir, out_paths = convert_pdf_to_images(
        args.pdf, fmt=args.format, dpi=args.dpi)
    print(f"wrote {len(out_paths)} page image(s) to {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
