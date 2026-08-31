"""Headless render of every testcase to out/*.png (page + scroll modes).

Used for visual comparison against testcases/reference/*.png.
"""
import glob
import os
import sys
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# the offscreen platform has no system font database; point it at Windows fonts
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

from PyQt5.QtGui import QGuiApplication

from lilyrender import parser, interpret, layout
from lilyrender.render_qt import (PageLayout, render_page_image,
                                  render_scroll_image)

OUT = os.path.join(ROOT, "out")


def main():
    app = QGuiApplication(sys.argv)
    os.makedirs(OUT, exist_ok=True)
    ok = fail = 0
    for path in sorted(glob.glob(os.path.join(ROOT, "testcases", "*.ly"))):
        name = os.path.splitext(os.path.basename(path))[0]
        try:
            with open(path, encoding="utf-8") as f:
                scores = parser.parse(f.read())
            sc = interpret.build_score(scores[0])
            page = layout.engrave(sc, line_width=110.0)
            pl = PageLayout(page)
            img = render_page_image(pl, 0, scale=8.0)
            img.save(os.path.join(OUT, f"{name}.png"))
            scroll = layout.engrave(sc, scroll=True)
            simg = render_scroll_image(scroll, scale=8.0)
            simg.save(os.path.join(OUT, f"{name}_scroll.png"))
            print(f"OK   {name}")
            ok += 1
        except Exception:
            print(f"FAIL {name}")
            traceback.print_exc(limit=6)
            fail += 1
    print(f"\n{ok} ok, {fail} failed -> {OUT}")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
