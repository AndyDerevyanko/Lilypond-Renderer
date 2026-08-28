"""Convert every page of a PDF into standalone image files.

Usage:
    python scripts/pdf_to_images.py path/to/x.pdf [--format jpg|png] [--dpi 150]

For an input `x.pdf`, writes `x_page-0001.jpg`, `x_page-0002.jpg`, ... into a
folder named `x/` created next to the PDF (same directory).
"""
import argparse
import os
import sys

import fitz  # PyMuPDF


def convert_pdf_to_images(pdf_path, fmt="jpg", dpi=150):
    pdf_path = os.path.abspath(pdf_path)
    if not os.path.isfile(pdf_path):
        raise FileNotFoundError(pdf_path)

    base_dir = os.path.dirname(pdf_path)
    stem = os.path.splitext(os.path.basename(pdf_path))[0]
    out_dir = os.path.join(base_dir, stem)
    os.makedirs(out_dir, exist_ok=True)

    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)

    doc = fitz.open(pdf_path)
    out_paths = []
    try:
        for page_index in range(doc.page_count):
            page = doc.load_page(page_index)
            pix = page.get_pixmap(matrix=matrix)
            out_path = os.path.join(
                out_dir, f"{stem}_page-{page_index + 1:04d}.{fmt}"
            )
            pix.save(out_path)
            out_paths.append(out_path)
    finally:
        doc.close()

    return out_dir, out_paths


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf_path", help="path to the input PDF")
    parser.add_argument(
        "--format", choices=["jpg", "png"], default="jpg", help="output image format"
    )
    parser.add_argument("--dpi", type=int, default=150, help="render resolution")
    args = parser.parse_args()

    out_dir, out_paths = convert_pdf_to_images(
        args.pdf_path, fmt=args.format, dpi=args.dpi
    )
    print(f"wrote {len(out_paths)} page(s) to {out_dir}")


if __name__ == "__main__":
    sys.exit(main())
