"""Unit tests for lilyrender.events (note extraction for playback)."""
import os
import sys
from fractions import Fraction

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from lilyrender import events, interpret, parser


def build(src):
    return interpret.build_score(parser.parse(src)[0])


def test_midi_numbers():
    sc = build(r"\score { { c'4 d' e' } }")
    ns = events.extract_notes(sc)
    assert [n.midi for n in ns] == [60, 62, 64]
    assert [n.time for n in ns] == [Fraction(0), Fraction(1, 4), Fraction(1, 2)]
    assert all(n.duration == Fraction(1, 4) for n in ns)


def test_accidentals_and_octaves():
    sc = build(r"\score { { cis'4 bes4 a,,2 } }")
    ns = events.extract_notes(sc)
    assert [n.midi for n in ns] == [61, 58, 33]


def test_chord_expands():
    sc = build(r"\score { { <c' e' g'>2 } }")
    ns = events.extract_notes(sc)
    assert sorted(n.midi for n in ns) == [60, 64, 67]
    assert all(n.duration == Fraction(1, 2) for n in ns)


def test_rests_skipped():
    sc = build(r"\score { { c'4 r4 s4 d'4 } }")
    ns = events.extract_notes(sc)
    assert [n.midi for n in ns] == [60, 62]
    assert ns[1].time == Fraction(3, 4)


def test_tie_merges():
    sc = build(r"\score { { c'2~ c'4 d'4 } }")
    ns = events.extract_notes(sc)
    assert len(ns) == 2
    assert ns[0].midi == 60 and ns[0].duration == Fraction(3, 4)
    assert ns[1].midi == 62 and ns[1].time == Fraction(3, 4)


def test_tie_chain_merges():
    sc = build(r"\score { { c'1~ c'1~ c'2 } }")
    ns = events.extract_notes(sc)
    assert len(ns) == 1
    assert ns[0].duration == Fraction(5, 2)


def test_tied_chord():
    sc = build(r"\score { { <c' e'>2~ <c' e'>2 } }")
    ns = events.extract_notes(sc)
    assert sorted(n.midi for n in ns) == [60, 64]
    assert all(n.duration == Fraction(1) for n in ns)


def test_grace_notes_get_time():
    sc = build(r"\score { { \grace { d'8 } c'4 } }")
    ns = events.extract_notes(sc)
    assert len(ns) == 2
    g = [n for n in ns if n.midi == 62][0]
    assert g.duration == events.GRACE_LEN
    assert g.time == Fraction(0)          # clamped at score start


def test_two_staves():
    sc = build(r"""\score { \new PianoStaff <<
        \new Staff { c''4 }
        \new Staff { \clef bass c4 }
    >> }""")
    ns = events.extract_notes(sc)
    assert sorted(n.midi for n in ns) == [48, 72]
    assert sorted(n.staff for n in ns) == [0, 1]


def test_tempo_helpers():
    sc = build(r"\score { { \tempo 4 = 120 c'1 } }")
    assert events.find_tempo(sc) == (Fraction(1, 4), 120)
    assert abs(events.wholes_per_second(sc) - 0.5) < 1e-9
    assert events.total_length(sc) == Fraction(1)


def test_no_tempo_default():
    sc = build(r"\score { { c'4 } }")
    assert events.find_tempo(sc) is None
    assert abs(events.wholes_per_second(sc, default_bpm=120) - 0.5) < 1e-9


def main():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    fail = 0
    for fn in fns:
        try:
            fn()
            print(f"OK   {fn.__name__}")
        except Exception as e:
            import traceback
            print(f"FAIL {fn.__name__}: {e}")
            traceback.print_exc(limit=3)
            fail += 1
    print(f"\n{len(fns) - fail} ok, {fail} failed")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
