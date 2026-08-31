"""Smoke test: engrave every testcase in page + scroll mode; sanity checks."""
import glob
import os
import sys
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from lilyrender import parser, interpret, layout


def check(res, name, mode):
    assert res.systems, f"{name} {mode}: no systems"
    for i, s in enumerate(res.systems):
        assert s.items, f"{name} {mode}: system {i} empty"
        assert s.width > 0, f"{name} {mode}: system {i} width {s.width}"
        assert s.height > 0, f"{name} {mode}: system {i} height {s.height}"
        for it in s.items:
            for attr in ("x", "x1"):
                v = getattr(it, attr, None)
                if v is not None:
                    assert -10 < v < s.width + 30, \
                        f"{name} {mode}: sys{i} {type(it).__name__} {attr}={v:.1f} width={s.width:.1f}"
        # time_map monotone
        tm = s.time_map
        for a, b in zip(tm, tm[1:]):
            assert a[0] <= b[0] and a[1] <= b[1] + 1e-9, \
                f"{name} {mode}: time_map not monotone {a} -> {b}"


def main():
    ok = fail = 0
    for path in sorted(glob.glob(os.path.join(ROOT, "testcases", "*.ly"))):
        name = os.path.basename(path)
        try:
            with open(path, encoding="utf-8") as f:
                scores = parser.parse(f.read())
            sc = interpret.build_score(scores[0])
            page = layout.engrave(sc, line_width=110.0)
            check(page, name, "page")
            scroll = layout.engrave(sc, scroll=True)
            check(scroll, name, "scroll")
            assert len(scroll.systems) == 1, f"{name}: scroll made >1 system"
            nitems = sum(len(s.items) for s in page.systems)
            print(f"OK   {name:34s} systems={len(page.systems)} "
                  f"items={nitems} width0={page.systems[0].width:.1f}")
            ok += 1
        except Exception:
            print(f"FAIL {name}")
            traceback.print_exc(limit=6)
            fail += 1
    print(f"\n{ok} ok, {fail} failed")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
