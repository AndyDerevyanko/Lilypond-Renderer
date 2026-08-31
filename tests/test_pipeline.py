"""Smoke test: parse + interpret every testcase .ly; print staff/event stats."""
import glob
import os
import sys
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from lilyrender import parser, interpret


def main():
    ok = fail = 0
    for path in sorted(glob.glob(os.path.join(ROOT, "testcases", "*.ly"))):
        name = os.path.basename(path)
        try:
            with open(path, encoding="utf-8") as f:
                scores = parser.parse(f.read())
            assert scores, "no scores"
            sc = interpret.build_score(scores[0])
            nstaves = len(sc.staves)
            nev = sum(len(s.events) for s in sc.staves)
            nattr = sum(len(s.attributes) for s in sc.staves)
            nlyr = sum(len(s.lyrics) for s in sc.staves)
            end = max((s.end_time for s in sc.staves), default=0)
            print(f"OK   {name:34s} staves={nstaves} events={nev} "
                  f"attrs={nattr} lyrics={nlyr} end={end}")
            ok += 1
        except Exception:
            print(f"FAIL {name}")
            traceback.print_exc(limit=4)
            fail += 1
    print(f"\n{ok} ok, {fail} failed")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
