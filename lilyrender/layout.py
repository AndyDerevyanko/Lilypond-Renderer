"""Engraving: resolved Score -> positioned primitives.

Coordinates are in staff spaces, y grows DOWNWARD.  Within a system, y=0 is
the top line of the first staff; x=0 is the system's left edge.  A staff is
4 spaces tall.  "Staff position" = diatonic steps above the bottom line
(bottom line 0, top line 8); y = staff_top + (8 - pos) / 2.

Output:
    LayoutResult
      .systems : [System]  (one per line of music; scroll mode -> exactly 1)
      .header  : dict
    System
      .items      : [Glyph|Line|Beam|Text|Curve]
      .width/.height, .staff_tops, .time_map [(time, x)], .start/.end time
"""

from dataclasses import dataclass, field
from fractions import Fraction
from typing import List, Optional, Tuple

from . import smufl
from .model import (Score, StaffData, TimedEvent, Duration,
                    clef_middle_c_position, TempoNode)

WHOLE = Fraction(1)


# ---------------------------------------------------------------------------
# primitives
# ---------------------------------------------------------------------------

@dataclass
class Glyph:
    name: str
    x: float
    y: float
    size: float = 1.0            # 1.0 == normal staff-size glyph
    color: Optional[tuple] = None
    staff: int = 0
    text: Optional[str] = None   # if set, draw this literal string with the
                                  # music font instead of looking up `name` as
                                  # a single glyph (dynamics: "mf"/"sfz"/...
                                  # rely on the font's own built-in kerning)

@dataclass
class Line:
    x1: float; y1: float; x2: float; y2: float
    thickness: float = 0.13
    color: Optional[tuple] = None
    staff: int = 0

@dataclass
class Beam:                       # filled quad with vertical ends
    x1: float; y1: float; x2: float; y2: float
    thickness: float = 0.5
    staff: int = 0

@dataclass
class Text:
    text: str
    x: float; y: float
    size: float = 1.0             # multiples of staff space for font sizing
    style: str = "plain"          # 'title','composer','lyric','tuplet','tempo','text','fingering'
    anchor: str = "left"          # left|center|right
    italic: bool = False
    bold: bool = False
    staff: int = 0

@dataclass
class Curve:                      # cubic bezier (tie/slur)
    x1: float; y1: float
    cx1: float; cy1: float
    cx2: float; cy2: float
    x2: float; y2: float
    thickness: float = 0.15
    staff: int = 0


@dataclass
class System:
    items: list = field(default_factory=list)
    width: float = 0.0
    height: float = 0.0
    top: float = 0.0              # extent above y=0 (title space not incl.)
    staff_tops: List[float] = field(default_factory=list)
    time_map: List[Tuple[Fraction, float]] = field(default_factory=list)
    start_time: Fraction = Fraction(0)
    end_time: Fraction = Fraction(0)
    # [(x_start, x_end, flexible)] spanning the whole system, in draw order;
    # flexible spans are spring-dominated note gaps (real justification only
    # stretches these); rigid spans are clefs/keys/timesigs/barline gaps/
    # glyph-width-bound chord columns, which keep their natural width
    segments: list = field(default_factory=list)


@dataclass
class LayoutResult:
    systems: List[System] = field(default_factory=list)
    header: dict = field(default_factory=dict)
    groups: list = field(default_factory=list)
    paper: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# music helpers
# ---------------------------------------------------------------------------

_FIFTHS_OF_STEP = {0: 0, 1: 2, 2: 4, 3: -1, 4: 1, 5: 3, 6: 5}  # c d e f g a b
_SHARP_ORDER = [3, 0, 4, 1, 5, 2, 6]   # F C G D A E B (step indices)
_FLAT_ORDER = [6, 2, 5, 1, 4, 0, 3]    # B E A D G C F

# staff positions of sharps/flats in treble clef, by order index
_SHARP_POS_TREBLE = [8, 5, 9, 6, 3, 7, 4]
_FLAT_POS_TREBLE = [4, 7, 3, 6, 2, 5, 1]

# Step-to-step deltas within that zigzag (same shape in every clef -- only
# the starting position moves). Verified against real LilyPond 2.24.4
# output for treble/bass; see key_sig_positions().
_FLAT_STEPS = [3, -4, 3, -4, 3, -4]
_SHARP_STEPS = [-3, 4, -3, -3, 4, -3]


def key_sig_positions(order_positions, steps, shift):
    """Full 7-accidental staff-position list for one clef.

    Naively adding a clef's position `shift` to each of the treble-clef
    reference positions and reducing every one independently into a
    plausible-looking range (as this used to do) gets the wrong octave for
    several accidentals -- e.g. bass-clef Bb landed a 7th too high. Real
    engraving instead: (1) reduces only the FIRST accidental into the
    staff's [0, 8] band, then (2) walks the rest of the zigzag from there
    with the clef-independent step pattern above, letting the pattern's own
    "overshoot" entries (like sharp #3) land outside that band exactly as
    they do in treble."""
    base = order_positions[0] + shift
    while base > 8:
        base -= 7
    while base < 0:
        base += 7
    out = [base]
    for d in steps:
        out.append(out[-1] + d)
    return out


def key_fifths(tonic, mode):
    f = _FIFTHS_OF_STEP[tonic.step] + 7 * tonic.alter
    if mode == "minor":
        f -= 3
    return f


def key_alter_map(fifths):
    """step -> alter for the key signature."""
    m = {}
    if fifths > 0:
        for s in _SHARP_ORDER[:fifths]:
            m[s] = 1
    elif fifths < 0:
        for s in _FLAT_ORDER[:-fifths]:
            m[s] = -1
    return m


def clef_pos_shift(clef_name):
    """Shift of key-signature positions relative to treble."""
    glyph, line = smufl.CLEF_GLYPHS.get(clef_name, ("gClef", 1))
    mc = clef_middle_c_position(clef_name)
    return mc - (-2)   # treble middle c pos is -2


class _ClefState:
    def __init__(self, name="treble"):
        self.set(name)

    def set(self, name):
        self.name = name
        g = smufl.CLEF_GLYPHS.get(name)
        if g is None:
            g = ("gClef", 1)
        self.glyph, self.line = g
        self.middle_c = clef_middle_c_position(name if name in smufl.CLEF_GLYPHS
                                               else "treble")

    def pos_of(self, pitch):
        # staff position of pitch: middle c pos + diatonic distance from c'
        return self.middle_c + pitch.diatonic


# ---------------------------------------------------------------------------
# engraving config
# ---------------------------------------------------------------------------

class Config:
    staff_gap = 9.0            # spaces between staff top lines
    group_gap = 8.0            # gap between staves in same group
    system_gap = 3.5
    line_width = 110.0         # spaces (page mode); None = endless (scroll)
    stem_len = 3.5
    stem_thickness = smufl.engraving("stemThickness", 0.12) if True else 0.12
    staff_line = 0.13
    thin_bar = 0.16
    thick_bar = 0.5
    beam_thick = 0.5
    beam_gap = 0.25
    ledger_ext = 0.4
    acc_gap = 0.25             # accidental to head
    dot_gap = 0.4
    col_pad = 0.35             # min padding between columns
    space_base = 0.9           # spring constants
    space_log = 0.45
    first_col_x = 0.8          # after prefix
    lyric_gap = 2.2            # below staff bottom line


# LilyPond's default staff size (pt) and page dimensions/margins for the two
# common paper sizes it supports; used to translate a score's #(paper)
# hints into staff-space page geometry (see page_geometry()).
DEFAULT_STAFF_SIZE_PT = 20.0
_PAPER_SIZES_PT = {
    "a4": (595.28, 841.89),
    "letter": (612.0, 792.0),
}
DEFAULT_MARGIN_MM = 10.0
_PT_PER_MM = 2.8346


def page_geometry(paper: dict = None):
    """Physical page size/margins (LilyPond defaults, overridden by any
    #(set-global-staff-size ..)/#(set-default-paper-size ..) hints picked up
    while parsing) translated into staff-space units, since layout.py's
    coordinate system is staff spaces and 1 space shrinks/grows with the
    staff size while the physical page does not.

    Returns dict(line_width, page_w, page_h, margin, staff_size) all in
    staff spaces except staff_size (points)."""
    paper = paper or {}
    staff_size_pt = paper.get("staff_size") or DEFAULT_STAFF_SIZE_PT
    paper_size = paper.get("paper_size") or "a4"
    page_w_pt, page_h_pt = _PAPER_SIZES_PT.get(paper_size, _PAPER_SIZES_PT["a4"])
    margin_pt = DEFAULT_MARGIN_MM * _PT_PER_MM
    space_pt = staff_size_pt / 4.0
    return {
        "line_width": (page_w_pt - 2 * margin_pt) / space_pt,
        "page_w": page_w_pt / space_pt,
        "page_h": page_h_pt / space_pt,
        "margin": margin_pt / space_pt,
        "staff_size": staff_size_pt,
    }


# ---------------------------------------------------------------------------


def duration_log(d: Duration):
    return d.log


def notehead_for(d: Duration):
    if d.log <= -1:
        return smufl.NOTEHEAD_BREVE
    return smufl.NOTEHEAD_FOR_LOG.get(d.log, smufl.NOTEHEAD_BLACK)


def measure_bounds(score: Score):
    """[(start, end, (num,den))] covering the whole piece."""
    # gather time signature + partial events from all staves (first wins)
    changes = {}
    partial = None
    for st in score.staves:
        for a in st.attributes:
            if a.kind == "time" and a.time not in changes:
                changes[a.time] = a.value
            elif a.kind == "partial" and a.time == 0:
                partial = a.value
    end = max((st.end_time for st in score.staves), default=Fraction(0))
    if end == 0:
        return [(Fraction(0), Fraction(1), (4, 4))]
    sig_times = sorted(changes)
    cur_sig = changes.get(Fraction(0), (4, 4))
    mlen = Fraction(cur_sig[0], cur_sig[1])
    t = Fraction(0)
    out = []
    if partial:
        out.append((t, t + partial, cur_sig))
        t += partial
    while t < end:
        # time signature change exactly at t?
        for ct in sig_times:
            if ct == t:
                cur_sig = changes[ct]
                mlen = Fraction(cur_sig[0], cur_sig[1])
        nxt = t + mlen
        # clip to next change
        for ct in sig_times:
            if t < ct < nxt:
                nxt = ct
        out.append((t, min(nxt, end) if nxt > end else nxt, cur_sig))
        t = nxt
    return out


# ---------------------------------------------------------------------------
# per-staff walking state
# ---------------------------------------------------------------------------

class _StaffState:
    def __init__(self, staff: StaffData, idx: int):
        self.data = staff
        self.idx = idx
        self.clef = _ClefState("treble")
        self.key_fifths = 0
        self.key_map = {}
        self.acc_state = {}       # (step, octave) -> alter, reset each measure
        self.color = None
        self.pending_clef = None
        self.clef_glyph_override = None   # \once \override Staff.Clef.glyph-name
        self.clef_y_override = None       # \once \override Staff.Clef.Y-offset
        self.timesig_markup = None        # \once \override Staff.TimeSignature.text
        self.pending_shape = {}   # grob name -> [(dx,dy)x4] from \shape, once
        self.cur_ottava = 0       # displayed ottava state (for bracket marks)
        # attribute cursors
        self.attrs = sorted(staff.attributes, key=lambda a: (a.time, _attr_rank(a.kind)))
        self.ai = 0
        self.tied_pitches = set() # pitches tied into the next note
        self.events_by_time = {}
        for e in staff.events:
            self.events_by_time.setdefault(e.time, []).append(e)
        self.sorted_times = sorted(self.events_by_time)

    def times_in(self, t0, t1):
        """Event onset times in [t0, t1) via binary search."""
        import bisect
        i = bisect.bisect_left(self.sorted_times, t0)
        j = bisect.bisect_left(self.sorted_times, t1)
        return self.sorted_times[i:j]

    def attrs_until(self, t):
        out = []
        while self.ai < len(self.attrs) and self.attrs[self.ai].time <= t:
            out.append(self.attrs[self.ai])
            self.ai += 1
        return out


def _attr_rank(kind):
    return {"clef": 0, "key": 1, "time": 2, "partial": 3,
            "tempo": 4, "bar": 5, "override": 6}.get(kind, 9)


# ---------------------------------------------------------------------------
# main engraver
# ---------------------------------------------------------------------------

class Engraver:
    def __init__(self, score: Score, cfg: Config = None, scroll=False):
        self.score = score
        self.cfg = cfg or Config()
        self.scroll = scroll
        self.staves = [_StaffState(s, i) for i, s in enumerate(score.staves)]
        self.systems = []
        self.cur = None            # current System being filled
        self.x = 0.0
        self.pending_ties = {}     # (staff, pitch semitones, voice) -> (x, y, dir)
        self.pending_slurs = {}    # (staff, voice, kind) -> [(x, y, dir)]
        self.pending_hairpin = {}  # staff -> (kind, x, time)
        self.cross_system_curves = []
        self.tempo_hidden = False  # \set Score.tempoHideNote = ##t

    # -- vertical helpers -------------------------------------------------
    def staff_top(self, staff_idx):
        return self.cur.staff_tops[staff_idx]

    def y_of_pos(self, staff_idx, pos):
        return self.staff_top(staff_idx) + (8 - pos) / 2.0

    # -- system management -------------------------------------------------
    def new_system(self, start_time, measure_no=None):
        cfg = self.cfg
        sys_ = System()
        tops = []
        y = 0.0
        for i, st in enumerate(self.staves):
            tops.append(y)
            gap = cfg.staff_gap
            if self._staff_has_lyrics(i):
                gap += 2.5
            y += gap
        sys_.staff_tops = tops
        sys_.height = tops[-1] + 4.0 if tops else 4.0
        sys_.start_time = start_time
        self.systems.append(sys_)
        self.cur = sys_
        self.x = 0.0
        self._draw_system_start(start_time)
        # lilypond convention: every system after the first is labelled
        # with its first measure's number, above the staff at the left edge
        if measure_no is not None and measure_no > 1:
            self.cur.items.append(Text(str(measure_no), 0.0,
                                       self.staff_top(0) - 2.0,
                                       size=1.0, style="measure_number"))

    def _staff_has_lyrics(self, i):
        return bool(self.staves[i].data.lyrics)

    def _draw_system_start(self, t):
        cfg = self.cfg
        # initial systemic barline across all staves
        if len(self.staves) > 1:
            y1 = self.staff_top(0)
            y2 = self.staff_top(len(self.staves) - 1) + 4
            self.cur.items.append(Line(0, y1, 0, y2, cfg.thin_bar))
        # group braces / brackets
        for grp in self.score.groups:
            if not grp.staves:
                continue
            y1 = self.staff_top(grp.staves[0])
            y2 = self.staff_top(grp.staves[-1]) + 4
            if grp.kind in ("PianoStaff", "GrandStaff"):
                name, actual_h = smufl.brace_for_height(y2 - y1)
                if name:
                    self.cur.items.append(
                        Glyph(name, -0.8, (y1 + y2) / 2.0, size=1.0))
            else:
                self.cur.items.append(Line(-0.8, y1 - 0.5, -0.8, y2 + 0.5, 0.5))
        x = self.cfg.first_col_x
        # clefs + key signatures (current state) per staff
        xmax = x
        for st in self.staves:
            xs = x
            xs = self._draw_clef(st, xs, small=False)
            xs = self._draw_keysig(st, xs, st.key_fifths)
            xmax = max(xmax, xs)
        self.x = xmax + 0.5

    _CLEF_CHANGE = {"gClef": "gClefChange", "fClef": "fClefChange",
                    "cClef": "cClefChange"}

    def _draw_clef(self, st: _StaffState, x, small):
        g = st.clef_glyph_override or st.clef.glyph
        st.clef_glyph_override = None   # \once: applies to this clef only
        size = 1.0
        if small:
            # mid-piece clef changes use the font's dedicated smaller
            # change-clef glyphs (like real LilyPond), not a scaled-down copy
            cg = self._CLEF_CHANGE.get(g)
            if cg and smufl.has_glyph(cg):
                g = cg
            else:
                size = 0.8
        y = self.y_of_pos(st.idx, st.clef.line * 2)
        if st.clef_y_override is not None:
            # Y-offset override: staff spaces up from the middle line
            y = self.y_of_pos(st.idx, 4) - st.clef_y_override
            st.clef_y_override = None
        self.cur.items.append(Glyph(g, x, y, size, staff=st.idx))
        return x + smufl.width(g) * size + 0.6

    def _draw_keysig(self, st: _StaffState, x, fifths, cancel=0):
        shift = clef_pos_shift(st.clef.name)
        def draw(order_positions, steps, glyph, n):
            nonlocal x
            positions = key_sig_positions(order_positions, steps, shift)
            for k in range(n):
                y = self.y_of_pos(st.idx, positions[k])
                self.cur.items.append(Glyph(glyph, x, y, staff=st.idx))
                # pack tight like real key signatures (the font's ink bbox
                # overstates the advance for accidentals)
                x += min(smufl.width(glyph), 1.0) + 0.05
        if fifths > 0:
            draw(_SHARP_POS_TREBLE, _SHARP_STEPS, "accidentalSharp", fifths)
        elif fifths < 0:
            draw(_FLAT_POS_TREBLE, _FLAT_STEPS, "accidentalFlat", -fifths)
        if fifths:
            x += 0.4
        return x

    def _draw_timesig(self, st: _StaffState, x, num, den):
        # lilypond's default style: C for 4/4, cut-C for 2/2
        symbol = {(4, 4): "timeSigCommon", (2, 2): "timeSigCutCommon"}.get((num, den))
        if symbol:
            self.cur.items.append(Glyph(symbol, x + 0.2,
                                        self.y_of_pos(st.idx, 4),
                                        staff=st.idx))
            end = x + 2.2
        else:
            # centered digits: numerator at pos 6, denominator at pos 2
            for value, pos in ((num, 6), (den, 2)):
                s = str(value)
                w = sum(smufl.width(smufl.TIMESIG_DIGITS[c]) for c in s)
                xx = x + (1.8 - w) / 2
                for c in s:
                    gname = smufl.TIMESIG_DIGITS[c]
                    self.cur.items.append(Glyph(gname, xx,
                                                self.y_of_pos(st.idx, pos),
                                                staff=st.idx))
                    xx += smufl.width(gname)
            end = x + 2.2
        markup = st.timesig_markup
        st.timesig_markup = None
        if markup is not None:
            # TimeSignature.text: markup appended right of the signature
            # (fake-clef trick: \hspace, \raise, \musicglyph "clefs.F_change")
            xx = end - 0.4
            for seg in getattr(markup, "segments", []):
                if "hspace" in seg:
                    xx += seg["hspace"]
                elif "musicglyph" in seg:
                    g = smufl.RAW_CLEF_GLYPH.get(seg["musicglyph"])
                    size = 1.0
                    if g and not smufl.has_glyph(g):
                        base = {"gClefChange": "gClef", "fClefChange": "fClef",
                                "cClefChange": "cClef"}.get(g)
                        if base:
                            g, size = base, 0.8
                    if g and smufl.has_glyph(g):
                        y = self.y_of_pos(st.idx, 4) - seg.get("dy", 0.0)
                        self.cur.items.append(Glyph(g, xx, y, size,
                                                    staff=st.idx))
                        xx += smufl.width(g) * size
            end = max(end, xx + 0.4)
        return end

    # -- barlines ----------------------------------------------------------
    def draw_barline(self, x, style="|"):
        cfg = self.cfg
        spans = self._barline_spans()
        for (i1, i2) in spans:
            y1 = self.staff_top(i1)
            y2 = self.staff_top(i2) + 4
            if style in ("|", ""):
                self.cur.items.append(Line(x, y1, x, y2, cfg.thin_bar))
            elif style == "||":
                self.cur.items.append(Line(x - 0.6, y1, x - 0.6, y2, cfg.thin_bar))
                self.cur.items.append(Line(x, y1, x, y2, cfg.thin_bar))
            elif style == "|.":
                self.cur.items.append(Line(x - 0.9, y1, x - 0.9, y2, cfg.thin_bar))
                self.cur.items.append(Line(x - 0.25, y1, x - 0.25, y2, cfg.thick_bar))
            elif style == ".|:":
                self.cur.items.append(Line(x + 0.25, y1, x + 0.25, y2, cfg.thick_bar))
                self.cur.items.append(Line(x + 0.9, y1, x + 0.9, y2, cfg.thin_bar))
                self._repeat_dots(x + 1.4, i1, i2)
            elif style == ":|.":
                self._repeat_dots(x - 1.9, i1, i2)
                self.cur.items.append(Line(x - 0.9, y1, x - 0.9, y2, cfg.thin_bar))
                self.cur.items.append(Line(x - 0.25, y1, x - 0.25, y2, cfg.thick_bar))
            elif style == ".|":
                self.cur.items.append(Line(x, y1, x, y2, cfg.thick_bar))
            else:
                self.cur.items.append(Line(x, y1, x, y2, cfg.thin_bar))

    def _repeat_dots(self, x, i1, i2):
        for si in range(i1, i2 + 1):
            for pos in (3, 5):
                self.cur.items.append(Glyph("repeatDot", x,
                                            self.y_of_pos(si, pos), staff=si))

    def _barline_spans(self):
        """Group staves whose barlines join (staff groups), else single."""
        used = set()
        spans = []
        for grp in self.score.groups:
            if grp.staves:
                spans.append((grp.staves[0], grp.staves[-1]))
                used.update(grp.staves)
        for i in range(len(self.staves)):
            if i not in used:
                spans.append((i, i))
        return sorted(spans)

    # -- note engraving ------------------------------------------------------

    def engrave(self):
        cfg = self.cfg
        measures = measure_bounds(self.score)
        prev_sig = None
        first = True
        # a hand-engraved score (like this Mutopia Chopin file) often places
        # explicit \break/\noBreak at every measure boundary via a dedicated
        # skip-note voice; when that's present, follow it exactly instead of
        # the natural-width greedy fit (which can't reproduce hand-placed
        # breaks, and the score's own \noBreak points forbid breaking early)
        forced_breaks = self.score.breaks

        for measure_no, (m_start, m_end, sig) in enumerate(measures, start=1):
            # plan before drawing the first system, so initial \clef/\key
            # attributes are already applied to staff state
            plan = self._plan_measure(m_start, m_end, sig, prev_sig,
                                      system_start=first)
            if first:
                self.new_system(m_start)
                first = False
            else:
                if not self.scroll and forced_breaks:
                    need_break = forced_breaks.get(m_start) in ("line", "page")
                else:
                    need_break = (not self.scroll and cfg.line_width
                                  and self.x + plan["width"] > cfg.line_width
                                  and self.x > cfg.first_col_x + 8)
                if need_break:
                    self._finish_system()
                    self.new_system(m_start, measure_no)
                    replan = self._plan_measure(m_start, m_end, sig, prev_sig,
                                                system_start=True)
                    # first plan consumed the measure-start attrs; keep them
                    replan["show_time"] = plan["show_time"]
                    replan["prefix"]["tempo"] = plan["prefix"]["tempo"]
                    replan["prefix"]["bar_before"] = plan["prefix"]["bar_before"]
                    plan = replan
            self._emit_measure(plan)
            prev_sig = sig

        # final barline if none explicit
        self._finish_system(final=True)
        self._flush_cross_system()
        res = LayoutResult(self.systems, dict(self.score.header),
                           self.score.groups, dict(self.score.paper))
        for s in self.systems:
            self._respace_staves(s)
            self._measure_system_bounds(s)
        if not self.scroll:
            self._justify()
        return res

    def _respace_staves(self, sys_):
        """Expand the gap between adjacent staves so notes/ledger lines
        reaching between them don't collide — real LilyPond's skyline-based
        staff-staff spacing (our fixed staff_gap is only the minimum). Items
        carry a `staff` index, so shifting a staff means shifting its items
        and every staff below it."""
        n = len(self.staves)
        if n < 2 or not sys_.staff_tops:
            return
        # boundaries between staff bands (midpoint of each gap), used both to
        # classify which staff a y belongs to and to skip items that span two
        # staves (barlines, braces) when measuring per-staff ink extent
        bounds = [(sys_.staff_tops[i - 1] + 4 + sys_.staff_tops[i]) / 2
                  for i in range(1, n)]

        def band(y):
            b = 0
            while b < len(bounds) and y >= bounds[b]:
                b += 1
            return b

        # ink extent per staff, relative to that staff's own top line;
        # only notation glyphs (noteheads/accidentals/rests/dots) drive the
        # spacing — stems/ledgers/barlines are excluded so a normal
        # down-stem doesn't force the staves apart
        low = [None] * n   # lowest ink (max y) rel to staff top
        high = [None] * n  # highest ink (min y) rel to staff top

        def note(si, y):
            nonlocal low, high
            v = y - sys_.staff_tops[si]
            if low[si] is None or v > low[si]:
                low[si] = v
            if high[si] is None or v < high[si]:
                high[si] = v

        for it in sys_.items:
            if isinstance(it, Glyph):
                if it.name and str(it.name).startswith("brace"):
                    continue
                note(band(it.y), it.y)
            elif isinstance(it, (Line, Beam)):
                # stems, ledger lines, beams reach into the gap and real
                # LilyPond spaces for them; barlines/brackets span two bands
                # and are excluded
                if band(it.y1) == band(it.y2):
                    note(band(it.y1), it.y1); note(band(it.y2), it.y2)
            elif isinstance(it, Curve):
                if band(it.y1) == band(it.y2) == band(it.cy1) == band(it.cy2):
                    note(band(it.y1), it.y1); note(band(it.y2), it.y2)
        # walk pairs top->down, accumulating downward shifts
        shift = 0.0
        cum = [0.0] * n
        for i in range(1, n):
            upper_bottom = low[i - 1] if low[i - 1] is not None else 4.0
            lower_top = high[i] if high[i] is not None else 0.0
            # required distance between the two staff top lines:
            # upper's lowest notehead + clearance - lower's highest notehead
            # (negative when it pokes above its own top line)
            clearance = 1.8
            need = max(upper_bottom, 4.0) + clearance - min(lower_top, 0.0)
            cur_gap = sys_.staff_tops[i] - sys_.staff_tops[i - 1]
            if need > cur_gap:
                shift += need - cur_gap
            cum[i] = shift
        if shift == 0.0:
            return

        def dy(y):
            band = 0
            while band < len(bounds) and y >= bounds[band]:
                band += 1
            return cum[band]

        for it in sys_.items:
            if isinstance(it, (Glyph, Text)):
                it.y += dy(it.y)
            elif isinstance(it, (Line, Beam)):
                it.y1 += dy(it.y1); it.y2 += dy(it.y2)
            elif isinstance(it, Curve):
                it.y1 += dy(it.y1); it.cy1 += dy(it.cy1)
                it.cy2 += dy(it.cy2); it.y2 += dy(it.y2)
        for i in range(n):
            sys_.staff_tops[i] += cum[i]

    # -- measure planning ---------------------------------------------------

    def _plan_measure(self, m_start, m_end, sig, prev_sig, system_start=False):
        """Collect columns and compute natural width (no emission yet)."""
        cfg = self.cfg
        # attribute events at measure start (clef/key/time changes)
        prefix = {"clef": [], "key": [], "time": None, "tempo": None,
                  "bar_before": None}
        for st in self.staves:
            for a in list(st.attrs_until(m_start)):
                if a.kind == "clef":
                    st.clef.set(a.value)
                    prefix["clef"].append(st.idx)
                elif a.kind == "key":
                    f = key_fifths(a.value.tonic, a.value.mode)
                    st.key_fifths = f
                    st.key_map = key_alter_map(f)
                    prefix["key"].append(st.idx)
                elif a.kind == "time":
                    prefix["time"] = a.value
                elif a.kind == "tempo":
                    prefix["tempo"] = a.value
                elif a.kind == "bar":
                    prefix["bar_before"] = a.value  # e.g. ".|:" written before music
                elif a.kind == "override":
                    self._apply_override(st, a.value)
            # reset measure accidental state
            st.acc_state = {}

        if system_start:
            prefix["clef"] = []
            prefix["key"] = []

        # time signature display: at start or when changed
        show_time = prefix["time"] if (prefix["time"] and
                                       (prev_sig is None or prefix["time"] != prev_sig
                                        or m_start == 0)) else None
        if m_start == 0 and prefix["time"] is None and sig != (4, 4):
            show_time = sig
        if m_start == 0 and prefix["time"] is None and sig == (4, 4):
            show_time = sig   # lilypond prints 4/4 by default too

        # columns: all onsets in [m_start, m_end)
        times = set()
        for st in self.staves:
            times.update(st.times_in(m_start, m_end))
        times = sorted(times)

        cols = []
        for t in times:
            cells = {}
            graces = {}
            for st in self.staves:
                evs = [e for e in st.events_by_time.get(t, ())]
                main = [e for e in evs if e.grace_index == 0]
                gr = sorted([e for e in evs if e.grace_index > 0],
                            key=lambda e: -e.grace_index)
                if main:
                    cells[st.idx] = main
                if gr:
                    graces[st.idx] = gr
            cols.append({"time": t, "cells": cells, "graces": graces})

        # measure natural width
        w = 0.0
        if prefix["clef"] and not system_start:
            w += 2.8
        if prefix["key"] and not system_start:
            w += 5.0
        if show_time:
            w += 2.6
        beamed_ids = self._measure_beam_ids(cols, sig, m_start)
        for i, col in enumerate(cols):
            cw = self._column_glyph_width(col, beamed_ids)
            nt = cols[i + 1]["time"] if i + 1 < len(cols) else m_end
            dur = nt - col["time"]
            spring = self._spring(dur)
            n_gr = max((len(g) for g in col["graces"].values()), default=0)
            col["_grace_w"] = n_gr * 1.5
            col["_glyph_w"] = cw
            col["_spring"] = spring
            w += col["_grace_w"] + max(cw + cfg.col_pad, spring)
        w += 1.2   # room before barline
        # width of mid-measure clef/key changes (peek, don't consume)
        for st in self.staves:
            for a in st.attrs[st.ai:]:
                if a.time >= m_end:
                    break
                if a.kind == "clef":
                    w += 2.0
                elif a.kind == "key":
                    w += 3.0
        return {"start": m_start, "end": m_end, "sig": sig, "cols": cols,
                "prefix": prefix, "show_time": show_time, "width": w,
                "system_start": system_start}

    def _measure_beam_ids(self, cols, sig, m_start):
        """id() set of note events that end up in a real (>=2 note) beam
        group. Mirrors _beam_groups, which normally only runs during
        emission (after widths are already needed): _column_glyph_width
        must know ahead of time whether a short note gets an unbeamed
        flag (extra width) or sits under a beam (no flag, no extra width)."""
        by_voice = {}
        for col in cols:
            for sidx, evs in col["cells"].items():
                for e in evs:
                    if e.hidden or not e.node.pitches or e.node.is_rest:
                        continue
                    node = e.node
                    by_voice.setdefault((sidx, e.voice), []).append({
                        "id": id(e), "log": node.duration.log, "time": e.time,
                        "duration": e.duration,
                        "beam_open": any(p.kind == "beam_open" for p in node.post),
                        "beam_close": any(p.kind == "beam_close" for p in node.post),
                    })
        beamed = set()
        for recs in by_voice.values():
            for g in self._beam_groups(recs, sig, m_start):
                if len(g) >= 2:
                    beamed.update(r["id"] for r in g)
        return beamed

    def _spring(self, dur):
        if dur <= 0:
            return self.cfg.col_pad
        import math
        f = float(dur)
        return max(1.0, self.cfg.space_base +
                   self.cfg.space_log * math.log2(f / 0.0625))

    def _column_glyph_width(self, col, beamed_ids):
        """Width needed by the widest cell: accidentals + head + dots.

        \\hideNotes events contribute ~nothing here: their NoteHead/Stem/
        Accidental stencils are empty in real LilyPond, so they still
        occupy their duration's spring but reserve no extra glyph room."""
        wmax = 1.5
        for sidx, evs in col["cells"].items():
            st = self.staves[sidx]
            visible = [e for e in evs if not e.hidden]
            # only voices that actually place a notehead can need shift
            # clearance; a rest/hidden voice sharing the column doesn't
            # displace anything (mirrors _voice_shifts, which the real
            # emission pass uses)
            nvoices = len({e.voice for e in visible
                          if e.node.pitches and not e.node.is_rest})
            shifts = self._voice_shifts(st, visible)
            # shared accidental column width (dry: don't consume acc state)
            accs = []
            for e in visible:
                if e.node.pitches and not e.node.is_rest:
                    for (p, a) in self._accidentals_needed(st, e.node,
                                                           dry=True):
                        accs.append((st.clef.pos_of(p) - 7 * e.ottava, a))
            acc_w = 0.0
            if accs:
                placed, ncols = self._acc_columns(accs)
                colw = max(smufl.width(smufl.ACCIDENTAL_GLYPHS[a])
                           for (_p, a, _c) in placed) + 0.12
                acc_w = ncols * colw + self.cfg.acc_gap
            for e in visible:
                w = acc_w
                node = e.node
                if node.pitches and not node.is_rest:
                    w += shifts.get(e.voice, 0.0)
                    head_w = smufl.width(notehead_for(node.duration))
                    w += head_w
                    # chord seconds: one notehead displaced a full head-width
                    # to the other side of the stem (mirrors _emit_event)
                    positions = sorted(st.clef.pos_of(p) - 7 * e.ottava
                                       for p in node.pitches)
                    if e.stem_dir:
                        stem_up = e.stem_dir > 0
                    elif nvoices > 1:
                        stem_up = (e.voice % 2 == 0)
                    else:
                        stem_up = (sum(positions) / len(positions)) < 4
                    if any(self._chord_offsets(positions, stem_up)):
                        w += head_w
                    if node.duration.dots:
                        w += node.duration.dots * (self.cfg.dot_gap + 0.4)
                    # unbeamed flag needs right room
                    if node.duration.log >= 3 and id(e) not in beamed_ids:
                        w += 0.8
                else:
                    w += 1.5
                wmax = max(wmax, w)
        return wmax

    def _accidentals_needed(self, st: _StaffState, node, dry=False):
        """[(pitch, alter_glyph_key)] accidentals to print for this note/chord."""
        out = []
        for p in node.pitches:
            key = (p.step, p.octave)
            cur = st.acc_state.get(key, st.key_map.get(p.step, 0))
            if p.alter != cur:
                if (st.idx, p.semitones()) in getattr(self, "_tied_in", set()) \
                        and not dry:
                    pass
                out.append((p, p.alter))
                if not dry:
                    st.acc_state[key] = p.alter
        return out

    def _apply_override(self, st, pv):
        path, value = pv
        tail = path.split(".")[-2:] if "." in path else [path]
        if path.endswith("NoteHead.color") or path == "NoteHead.color":
            if isinstance(value, (tuple, list)) and len(value) >= 3:
                st.color = tuple(value[:3])
            elif value is None:
                st.color = None
            elif isinstance(value, str):
                named = {"red": (1, 0, 0), "green": (0, 0.8, 0), "blue": (0, 0, 1)}
                st.color = named.get(value)
        elif path == "Staff.Clef.glyph-name":
            v = value.strip('"') if isinstance(value, str) else value
            st.clef_glyph_override = smufl.RAW_CLEF_GLYPH.get(v)
        elif path == "Staff.Clef.Y-offset":
            # absolute position of the clef glyph's reference point,
            # in staff spaces up from the staff's middle line (used by the
            # fake-clef trick: \clef bass shown with a G glyph at Y-offset -1
            # sits exactly where a true treble clef would)
            try:
                st.clef_y_override = float(str(value).lstrip("#"))
            except (TypeError, ValueError):
                pass
        elif path == "Staff.TimeSignature.text":
            # markup appended to the time signature (fake-clef trick appends
            # a small change-clef glyph after the C)
            st.timesig_markup = value
        elif path == "Score.tempoHideNote":
            # \set Score.tempoHideNote = ##t: suppress the printed tempo
            # mark entirely (it's still used for MIDI playback, which this
            # renderer doesn't model, so there's nothing else to preserve)
            self.tempo_hidden = bool(value)
        elif path.startswith("shape:"):
            # \shape #'((dx.dy)x4) Slur|PhrasingSlur|Tie: hand-tuned bezier
            # control-point offsets for the very next such curve on this
            # staff (consumed once in _handle_post, like a \once override)
            st.pending_shape[path[len("shape:"):]] = value

    # -- measure emission -----------------------------------------------------

    def _emit_measure(self, plan):
        cfg = self.cfg
        st_list = self.staves
        x = self.x
        prefix = plan["prefix"]

        # a clef change falling exactly on the barline prints BEFORE the
        # barline (real LilyPond's clef-then-bar convention)
        if prefix["clef"] and not plan["system_start"]:
            for sidx in prefix["clef"]:
                self._draw_clef(st_list[sidx], x, small=True)
            x += 2.8

        if prefix["bar_before"] and x > cfg.first_col_x + 4:
            self.draw_barline(x, prefix["bar_before"])
            x += 1.6
        if prefix["key"] and not plan["system_start"]:
            xk = x
            for sidx in prefix["key"]:
                xk = max(xk, self._draw_keysig(st_list[sidx], x,
                                               st_list[sidx].key_fifths))
            x = xk + 0.3
        if plan["show_time"]:
            num, den = plan["show_time"]
            xt = x + 2.6
            for st in st_list:
                xt = max(xt, self._draw_timesig(st, x, num, den) + 0.4)
            x = xt
        if prefix["tempo"] and not self.tempo_hidden:
            self._draw_tempo(prefix["tempo"], x)

        # -- emit columns; collect per-voice note records for beaming --------
        beam_records = {}    # (staff, voice) -> list of noterec
        for col in plan["cols"]:
            x = self._apply_mid_attrs(col["time"], x, plan)
            x += col["_grace_w"]
            if col["_grace_w"]:
                self._emit_graces(col, x)
            rod = col["_glyph_w"] + cfg.col_pad
            spring = col["_spring"]
            width_here = max(rod, spring)
            self._emit_column(col, x, beam_records)
            self.cur.time_map.append((col["time"], x))
            # spring-dominated columns are where real justification adds
            # extra stretch; glyph-width-bound ones (dense chords/
            # accidentals) are already at their physical minimum and stay put
            self.cur.segments.append((x, x + width_here, spring >= rod, spring))
            x += width_here

        # beams + flags + stems finalisation
        for key, recs in beam_records.items():
            self._beam_voice(key, recs, plan)

        # tuplet brackets
        self._draw_tuplets(beam_records)

        x += 0.9
        end_bar = "|"
        # explicit \bar / clef changes between last column and the barline
        for st in st_list:
            for a in st.attrs_until(plan["end"] - Fraction(1, 10 ** 9)):
                if a.kind == "bar":
                    end_bar = a.value
                elif a.kind == "clef":
                    # courtesy clef at end of measure (lilypond convention)
                    st.clef.set(a.value)
                    self._draw_clef(st, x - 0.4, small=True)
                    x += 2.0
                elif a.kind == "override":
                    self._apply_override(st, a.value)
        self.draw_barline(x, end_bar)
        self.cur.end_time = plan["end"]
        self.x = x + 0.15

    def _draw_tempo(self, node: TempoNode, x):
        y = self.staff_top(0) - 3.0
        parts = []
        if node.text:
            parts.append(node.text)
        if node.bpm and node.unit:
            unit_glyph = {0: "metNoteWhole", 1: "metNoteHalfUp",
                          2: "metNoteQuarterUp", 3: "metNote8thUp",
                          4: "metNote16thUp"}.get(node.unit.log,
                                                  "metNoteQuarterUp")
            self.cur.items.append(Glyph(unit_glyph, x, y, size=0.75))
            for k in range(node.unit.dots):
                self.cur.items.append(Glyph("metAugmentationDot",
                                            x + 0.9 + k * 0.5, y, size=0.75))
            dot_w = node.unit.dots * 0.5
            self.cur.items.append(Text(" = %d" % node.bpm, x + 1.2 + dot_w, y,
                                       size=1.0, style="tempo"))
            if parts:
                self.cur.items.append(Text(parts[0], x + 5.5 + dot_w, y,
                                           style="tempo"))
        elif parts:
            self.cur.items.append(Text(parts[0], x, y, style="tempo"))

    def _apply_mid_attrs(self, t, x, plan):
        """Apply attribute changes (clef, key, tempo...) that fall inside the
        measure, right before the column at time t."""
        for st in self.staves:
            for a in st.attrs_until(t):
                if a.kind == "clef":
                    st.clef.set(a.value)
                    self._draw_clef(st, x, small=True)
                    x += 2.0
                elif a.kind == "key":
                    f = key_fifths(a.value.tonic, a.value.mode)
                    st.key_fifths = f
                    st.key_map = key_alter_map(f)
                    x = self._draw_keysig(st, x, f) + 0.3
                elif a.kind == "tempo":
                    self._draw_tempo(a.value, x)
                elif a.kind == "bar":
                    self.draw_barline(x - 0.4, a.value)
                elif a.kind == "override":
                    self._apply_override(st, a.value)
        return x

    # ---- column emission ----------------------------------------------------

    def _emit_column(self, col, x, beam_records):
        for sidx, evs in col["cells"].items():
            st = self.staves[sidx]
            voices_here = sorted({e.voice for e in evs})
            nvoices = len(voices_here)
            shifts = self._voice_shifts(st, evs) if nvoices > 1 else {}
            # shared accidental column: all voices' accidentals stack to the
            # left of every notehead in this staff column (lilypond style)
            accs = []
            for e in evs:
                if e.node.pitches and not e.node.is_skip and not e.node.is_rest:
                    for (p, a) in self._accidentals_needed(st, e.node):
                        accs.append((st.clef.pos_of(p) - 7 * e.ottava, a))
            acc_w = self._draw_acc_column(sidx, accs, x)
            for e in evs:
                self._emit_event(st, e, x, nvoices, beam_records,
                                 acc_w=acc_w,
                                 shift=shifts.get(e.voice, 0.0))

    @staticmethod
    def _acc_columns(accs):
        """Assign accidentals to vertical sub-columns (0 = nearest to the
        heads); returns ([(pos, glyph, col)], ncols).  Accidentals closer
        than 6 staff positions overlap vertically and go one column left."""
        seen = set()
        uniq = []
        for (pos, a) in accs:
            if (pos, a) not in seen:
                seen.add((pos, a))
                uniq.append((pos, a))
        placed = []      # (pos, glyph, col)
        cols = []        # positions per column
        for (pos, a) in sorted(uniq, key=lambda t: -t[0]):
            for ci in range(len(cols)):
                if all(abs(pos - p) >= 6 for p in cols[ci]):
                    cols[ci].append(pos)
                    placed.append((pos, a, ci))
                    break
            else:
                cols.append([pos])
                placed.append((pos, a, len(cols) - 1))
        return placed, len(cols)

    def _draw_acc_column(self, sidx, accs, x):
        """Draw the stacked accidentals; return their total width."""
        if not accs:
            return 0.0
        placed, ncols = self._acc_columns(accs)
        colw = max(smufl.width(smufl.ACCIDENTAL_GLYPHS[a])
                   for (_p, a, _c) in placed) + 0.12
        for (pos, a, ci) in placed:
            gx = x + (ncols - 1 - ci) * colw
            gy = self.y_of_pos(sidx, pos)
            self.cur.items.append(Glyph(smufl.ACCIDENTAL_GLYPHS[a], gx, gy,
                                        staff=sidx))
        return ncols * colw + self.cfg.acc_gap

    def _voice_shifts(self, st, evs):
        """Shift down-stem voices right when they collide with an up-stem
        voice at the same column (unisons/seconds/crossings)."""
        by_voice = {}
        for e in evs:
            if not e.node.pitches or e.node.is_rest:
                continue
            pos = [st.clef.pos_of(p) - 7 * e.ottava for p in e.node.pitches]
            if e.stem_dir:
                up = e.stem_dir > 0
            else:
                up = (e.voice % 2 == 0)
            by_voice.setdefault(e.voice, [up, []])[1].extend(pos)
        shifts = {}
        ups = [v for v, (up, _) in by_voice.items() if up]
        downs = [v for v, (up, _) in by_voice.items() if not up]
        for dv in downs:
            dpos = by_voice[dv][1]
            for uv in ups:
                upos = by_voice[uv][1]
                if any(abs(a - b) <= 1 for a in dpos for b in upos) \
                        or (upos and dpos and max(dpos) > min(upos)):
                    shifts[dv] = 1.3
                    break
        return shifts

    def _emit_event(self, st, e, x, nvoices, beam_records,
                    acc_w=0.0, shift=0.0):
        cfg = self.cfg
        node = e.node
        sidx = st.idx
        vkey = (sidx, e.voice)

        if node.is_skip:
            self._emit_detached_post(st, e, x)
            return
        if not node.pitches or node.is_rest:
            # a positioned rest (`c4\rest`) keeps its written pitch only to
            # set the rest glyph's staff position, never a real notehead
            self._emit_rest(st, e, x + shift, nvoices)
            self._emit_detached_post(st, e, x)
            return

        dur = node.duration
        head = notehead_for(dur)
        # \ottava: notes are written shifted, with the 8va/8vb sign added
        positions = sorted(st.clef.pos_of(p) - 7 * e.ottava
                           for p in node.pitches)
        self._ottava_mark(st, e, x, positions)

        # stem direction
        if e.stem_dir:
            stem_up = e.stem_dir > 0
        elif nvoices > 1:
            stem_up = (e.voice % 2 == 0)
        else:
            avg = sum(positions) / len(positions)
            stem_up = avg < 4
        # chord second-offsets
        offsets = self._chord_offsets(positions, stem_up)

        head_w = smufl.width(head)
        # accidentals were drawn by _emit_column's shared column
        hx = x + acc_w + shift

        color = st.color
        ys = []
        for pos, off in zip(positions, offsets):
            y = self.y_of_pos(sidx, pos)
            ys.append(y)
            if e.hidden:
                continue
            gx = hx + (head_w if off else 0)
            self.cur.items.append(Glyph(head, gx, y, color=color, staff=sidx))
            # dots
            if dur.dots:
                dot_pos = pos if pos % 2 == 1 else pos + 1
                dy = self.y_of_pos(sidx, dot_pos)
                dx = hx + head_w + cfg.dot_gap + (head_w if any(offsets) else 0)
                for k in range(dur.dots):
                    self.cur.items.append(Glyph("augmentationDot",
                                                dx + k * 0.7, dy,
                                                color=color, staff=sidx))
        # ledger lines (\hideNotes hides these too, real LilyPond stencil ##f)
        if not e.hidden:
            self._ledger_lines(sidx, positions, hx, head_w, bool(any(offsets)))

        # stem info recorded; actual stem drawn in beaming pass
        rec = {
            "event": e, "x": x, "hx": hx, "head_w": head_w,
            "positions": positions, "ys": ys, "stem_up": stem_up,
            "stem_dir": e.stem_dir,
            "staff": sidx, "log": dur.log, "dots": dur.dots,
            "beam_open": any(p.kind == "beam_open" for p in node.post),
            "beam_close": any(p.kind == "beam_close" for p in node.post),
            "time": e.time, "duration": e.duration, "color": color,
            "tuplet": e.tuplet, "grace": False, "hidden": e.hidden,
        }
        beam_records.setdefault(vkey, []).append(rec)

        # post events: ties/slurs/dynamics/articulations...
        self._handle_post(st, e, rec)

    def _chord_offsets(self, positions, stem_up):
        """True = head displaced to the other side of the stem (seconds)."""
        offsets = [False] * len(positions)
        if stem_up:
            i = 0
            while i < len(positions) - 1:
                if positions[i + 1] - positions[i] == 1 and not offsets[i]:
                    offsets[i + 1] = True
                    i += 2
                else:
                    i += 1
        else:
            i = len(positions) - 1
            while i > 0:
                if positions[i] - positions[i - 1] == 1 and not offsets[i]:
                    offsets[i - 1] = True
                    i -= 2
                else:
                    i -= 1
        return offsets

    def _ledger_lines(self, sidx, positions, hx, head_w, has_offset):
        cfg = self.cfg
        ext = cfg.ledger_ext
        w = head_w * (2 if has_offset else 1)
        lo = min(positions)
        hi = max(positions)
        for pos in range(-2, lo - 1, -2) if lo < 0 else []:
            pass
        p = -2
        while p >= lo:
            y = self.y_of_pos(sidx, p)
            self.cur.items.append(Line(hx - ext, y, hx + w + ext, y,
                                       smufl.engraving("legerLineThickness", 0.16),
                                       staff=sidx))
            p -= 2
        p = 10
        while p <= hi:
            y = self.y_of_pos(sidx, p)
            self.cur.items.append(Line(hx - ext, y, hx + w + ext, y,
                                       smufl.engraving("legerLineThickness", 0.16),
                                       staff=sidx))
            p += 2

    def _emit_rest(self, st, e, x, nvoices):
        node = e.node
        sidx = st.idx
        if e.hidden:
            return
        if node.is_full_measure_rest:
            glyph = "restWhole"
            y = self.y_of_pos(sidx, 6)
            self.cur.items.append(Glyph(glyph, x + 0.5, y, staff=sidx))
            if node.multiplier > 1:
                self.cur.items.append(Text(str(node.multiplier), x + 0.5,
                                           self.staff_top(sidx) - 1.5,
                                           style="tuplet", anchor="center"))
            return
        log = node.duration.log
        glyph = smufl.REST_FOR_LOG.get(log, "restQuarter")
        if node.pitches:
            # positioned rest (`c4\rest`): the written pitch fixes the
            # rest's staff position explicitly, overriding the usual
            # by-duration default and the multi-voice auto-nudge below
            y = self.y_of_pos(sidx, st.clef.pos_of(node.pitches[0]) - 7 * e.ottava)
        else:
            # whole rest hangs from line pos 6; half sits on middle line
            if log == 0:
                y = self.y_of_pos(sidx, 6)
            elif log == 1:
                y = self.y_of_pos(sidx, 4)
            else:
                y = self.y_of_pos(sidx, 4)
            if nvoices > 1:
                y += -1.0 if e.voice % 2 == 0 else 1.0
        self.cur.items.append(Glyph(glyph, x, y, staff=sidx))
        for k in range(node.duration.dots):
            self.cur.items.append(Glyph("augmentationDot",
                                        x + smufl.width(glyph) + 0.3 + k * 0.7,
                                        self.y_of_pos(sidx, 5), staff=sidx))

    # ---- post events ---------------------------------------------------------

    # dynamic-letter advances (music font at normal size), staff spaces
    _DYN_ADV = {"f": 1.10, "p": 1.25, "m": 1.70, "s": 0.95, "z": 0.95,
                "r": 0.95, "n": 1.0}

    def _markup_width(self, seg):
        if "hspace" in seg:
            return seg["hspace"]
        if "musicglyph" in seg:
            g = smufl.RAW_CLEF_GLYPH.get(seg["musicglyph"])
            return smufl.width(g) if g and smufl.has_glyph(g) else 2.0
        text = seg.get("text", "")
        if seg.get("dynamic"):
            return sum(self._DYN_ADV.get(c, 1.0) for c in text)
        return len(text) * 0.86 * seg.get("size", 1.0)

    def _emit_markup(self, sidx, x, y, value, italic=False):
        """Draw a (possibly rich) markup string at baseline y, styled per
        segment: \\dynamic runs use the music font's dynamic letters, text
        runs carry their own bold/italic/size, \\raise offsets the baseline."""
        segs = getattr(value, "segments", None)
        if not segs:
            self.cur.items.append(Text(str(value), x, y, style="text",
                                       italic=italic, staff=sidx))
            return
        align = getattr(value, "align", "left")
        total = sum(self._markup_width(s) for s in segs)
        xx = x - total if align == "right" else \
            x - total / 2 if align == "center" else x
        for seg in segs:
            w = self._markup_width(seg)
            yy = y - seg.get("dy", 0.0)
            if "hspace" in seg:
                pass
            elif "musicglyph" in seg:
                g = smufl.RAW_CLEF_GLYPH.get(seg["musicglyph"])
                if g and smufl.has_glyph(g):
                    self.cur.items.append(Glyph(g, xx, yy, staff=sidx))
            elif seg.get("dynamic"):
                self.cur.items.append(Glyph(None, xx, yy, staff=sidx,
                                            text=seg.get("text", "")))
            elif seg.get("text", ""):
                # rich segments carry their own italic; the caller's default
                # only applies to plain (segment-less) strings
                self.cur.items.append(Text(seg["text"], xx, yy,
                                           size=seg.get("size", 1.0),
                                           style="markup",
                                           italic=seg.get("italic", False),
                                           bold=seg.get("bold", False),
                                           staff=sidx))
            xx += w

    def _handle_post(self, st, e, rec):
        node = e.node
        sidx = st.idx
        x = rec["hx"]
        head_w = rec["head_w"]
        stem_up = rec["stem_up"]
        vkey = (sidx, e.voice)

        top_pos = max(rec["positions"])
        bot_pos = min(rec["positions"])
        y_top = self.y_of_pos(sidx, top_pos)
        y_bot = self.y_of_pos(sidx, bot_pos)

        # notes under a pending slur push its arc outward and vote on its
        # side (all stems up -> slur below, all down -> above, mixed -> above)
        for k, v in self.pending_slurs.items():
            if k[0] == vkey:
                v["ext_top"] = min(v["ext_top"], y_top - 0.7)
                v["ext_bot"] = max(v["ext_bot"], y_bot + 0.7)
                v["stems"].add(stem_up)

        for p in node.post:
            if p.kind == "tie":
                shape = st.pending_shape.pop("Tie", None)
                for pos, pitch in zip(rec["positions"],
                                      sorted(node.pitches, key=st.clef.pos_of)):
                    key = (sidx, pitch.semitones(), e.voice)
                    ydir = 1 if stem_up else -1   # notehead side, away from stem
                    self.pending_ties[key] = (x + head_w + 0.15,
                                              self.y_of_pos(sidx, pos),
                                              ydir, len(self.systems) - 1, shape)
            elif p.kind in ("slur_open", "phrasing_open"):
                k = (vkey, "phrasing" if p.kind.startswith("phras") else "slur")
                grob = "PhrasingSlur" if p.kind.startswith("phras") else "Slur"
                shape = st.pending_shape.pop(grob, None)
                # the side is decided at close time from every covered
                # note's stem; until then track both candidate endpoints
                self.pending_slurs[k] = {
                    "x": x + head_w / 2,
                    "top": y_top - 0.7, "bot": y_bot + 0.7,
                    "ext_top": y_top - 0.7, "ext_bot": y_bot + 0.7,
                    "sys": len(self.systems) - 1,
                    "stems": {stem_up}, "shape": shape}
            elif p.kind in ("slur_close", "phrasing_close"):
                k = (vkey, "phrasing" if p.kind.startswith("phras") else "slur")
                if k in self.pending_slurs:
                    v = self.pending_slurs.pop(k)
                    v["stems"].add(stem_up)
                    # all stems up -> slur below; all down or mixed -> above
                    ydir = 1 if v["stems"] == {True} else -1
                    sy = v["top"] if ydir < 0 else v["bot"]
                    ey = (y_top - 0.7) if ydir < 0 else (y_bot + 0.7)
                    ext = v["ext_top"] if ydir < 0 else v["ext_bot"]
                    self._draw_slur(v["x"], sy, x + head_w / 2, ey, ydir,
                                    v["sys"], sidx, ext, v["shape"])
            elif p.kind == "dynamic":
                if p.value in smufl.DYNAMIC_GLYPHS:
                    # \voiceOne (forced stems up) also flips dynamics above
                    # the staff, like real LilyPond's voice defaults
                    if e.stem_dir and e.stem_dir > 0:
                        y = self.staff_top(sidx) - 2.2
                    else:
                        y = self.staff_top(sidx) + 4 + 2.4
                    self.cur.items.append(
                        Glyph(None, x - 0.3, y, staff=sidx, text=p.value))
                    self._end_hairpin_at(sidx, x - 0.6)
            elif p.kind == "articulation":
                self._draw_articulation(st, rec, p)
            elif p.kind == "fingering":
                y = (self.y_of_pos(sidx, top_pos) - 1.6 if p.direction >= 0
                     else self.y_of_pos(sidx, bot_pos) + 1.6)
                if p.direction >= 0:
                    y = min(y, self.staff_top(sidx) - 1.0)
                else:
                    y = max(y, self.staff_top(sidx) + 5.0)
                self.cur.items.append(Text(str(p.value), x + head_w / 2, y,
                                           size=0.85, style="fingering",
                                           anchor="center", staff=sidx))
            elif p.kind == "text":
                if getattr(p, "direction", 0) > 0:
                    y = self.staff_top(sidx) - 1.5
                else:
                    # lilypond's TextScript default direction is below
                    y = self.staff_top(sidx) + 4 + 2.2
                self._emit_markup(sidx, x, y, p.value, italic=True)
            elif p.kind in ("cresc", "decresc"):
                if e.stem_dir and e.stem_dir > 0:
                    hy = self.staff_top(sidx) - 2.2
                else:
                    hy = self.staff_top(sidx) + 4 + 2.6
                self.pending_hairpin[sidx] = (p.kind, x, e.time,
                                              len(self.systems) - 1, hy)
            elif p.kind == "end_hairpin":
                self._end_hairpin_at(sidx, x)
            elif p.kind == "pedal":
                self._draw_pedal(sidx, x, p.value)
            elif p.kind == "arpeggio":
                self._draw_arpeggio(sidx, rec["x"] - 1.0, y_top, y_bot)

        # resolve arriving ties
        for pitch in node.pitches:
            key = (sidx, pitch.semitones(), e.voice)
            if key in self.pending_ties:
                sx, sy, ydir, sysi, shape = self.pending_ties.pop(key)
                ex = x - 0.15
                self._draw_tie(sx, sy, ex, ydir, sysi, sidx, shape)

    def _between_staves_y(self, sidx):
        """Baseline for a Dynamics lane: centered between this staff and the
        next (real LilyPond's Dynamics context in a PianoStaff), or just
        under the staff when it's the lowest one."""
        bottom = self.staff_top(sidx) + 4
        if sidx + 1 < len(self.staves):
            return (bottom + self.staff_top(sidx + 1)) / 2 + 0.6
        return bottom + 2.6

    def _emit_detached_post(self, st, e, x):
        """Dynamics/pedal/hairpins attached to skips and rests (typically a
        \\new Dynamics lane merged into this staff)."""
        sidx = st.idx
        for p in e.node.post:
            if p.kind == "dynamic":
                if p.value in smufl.DYNAMIC_GLYPHS:
                    y = self._between_staves_y(sidx)
                    self.cur.items.append(
                        Glyph(None, x - 0.3, y, staff=sidx, text=p.value))
                    self._end_hairpin_at(sidx, x - 0.6)
            elif p.kind in ("cresc", "decresc"):
                self.pending_hairpin[sidx] = (p.kind, x, e.time,
                                              len(self.systems) - 1,
                                              self._between_staves_y(sidx))
            elif p.kind == "end_hairpin":
                self._end_hairpin_at(sidx, x)
            elif p.kind == "pedal":
                self._draw_pedal(sidx, x, p.value)
            elif p.kind == "text":
                y = self._between_staves_y(sidx)
                self._emit_markup(sidx, x, y, p.value, italic=True)

    def _draw_pedal(self, sidx, x, which):
        g = smufl.PEDAL_GLYPHS.get(which)
        if g:
            y = self.staff_top(sidx) + 4 + 4.2
            self.cur.items.append(Glyph(g, x - 0.4, y, staff=sidx))

    def _draw_arpeggio(self, sidx, x, y_top, y_bot):
        seg = smufl.ARPEGGIO_GLYPH
        if not smufl.has_glyph(seg):
            seg = "wiggleArpeggiatoUp"
            if not smufl.has_glyph(seg):
                return
        w, s, e_, n = smufl.bbox(seg)
        h = max(n - s, 0.8)
        y = y_bot + 1.0
        while y > y_top - 0.5:
            self.cur.items.append(Glyph(seg, x, y, staff=sidx))
            y -= h

    def _ottava_mark(self, st, e, x, positions):
        """Print 8va/8vb (etc.) when the displayed ottava changes."""
        if e.ottava == st.cur_ottava:
            return
        sidx = st.idx
        if e.ottava != 0:
            g = smufl.OTTAVA_GLYPHS.get(e.ottava)
            if g:
                above = e.ottava > 0
                y = (self.staff_top(sidx) - 2.5 if above
                     else self.staff_top(sidx) + 4 + 3.0)
                if above and positions:
                    y = min(y, self.y_of_pos(sidx, max(positions)) - 2.0)
                self.cur.items.append(Glyph(g, x, y, size=0.8, staff=sidx))
        st.cur_ottava = e.ottava

    def _end_hairpin_at(self, sidx, x_end):
        if sidx not in self.pending_hairpin:
            return
        kind, x0, _t, sysi, y = self.pending_hairpin.pop(sidx)
        if sysi != len(self.systems) - 1:
            x0 = 1.0   # hairpin crossed a break: start at system left
        h = 0.55
        if kind == "cresc":
            self.cur.items.append(Line(x0, y, x_end, y - h, 0.16, staff=sidx))
            self.cur.items.append(Line(x0, y, x_end, y + h, 0.16, staff=sidx))
        else:
            self.cur.items.append(Line(x0, y - h, x_end, y, 0.16, staff=sidx))
            self.cur.items.append(Line(x0, y + h, x_end, y, 0.16, staff=sidx))

    def _draw_articulation(self, st, rec, p):
        sidx = st.idx
        name = p.value
        pair = smufl.ARTICULATION_GLYPHS.get(name)
        if not pair:
            return
        stem_up = rec["stem_up"]
        if name in ("fermata", "trill", "turn", "mordent", "prall"):
            above = p.direction >= 0
        else:
            above = (p.direction > 0) or (p.direction == 0 and not stem_up)
        glyph = pair[0] if above else pair[1]
        x = rec["hx"] + rec["head_w"] / 2 - smufl.width(glyph) / 2
        if above:
            # plain staccato/tenuto/accent etc. sit close to the notehead
            # (often between staff lines for a note mid-staff, not pinned
            # above the whole staff); only fermata/ornaments conventionally
            # float clear of the staff regardless of the note's position
            if name in ("fermata", "trill", "turn", "mordent", "prall"):
                y = self.staff_top(sidx) - 1.2
                stem_top = min(rec.get("stem_end_y", y), y)
                y = min(y, stem_top - 0.6) if rec.get("stem_end_y") else y
            else:
                y = self.y_of_pos(sidx, max(rec["positions"])) - 0.8
        else:
            if name in ("fermata", "trill", "turn", "mordent", "prall"):
                ref = max(self.y_of_pos(sidx, min(rec["positions"])),
                          self.staff_top(sidx) + 4)
                y = ref + 0.8
            else:
                y = self.y_of_pos(sidx, min(rec["positions"])) + 0.8
        self.cur.items.append(Glyph(glyph, x, y, staff=sidx))

    # ---- curves ---------------------------------------------------------------

    def _draw_tie(self, sx, sy, ex, ydir, start_sys, sidx, shape=None):
        if start_sys != len(self.systems) - 1:
            # split: draw ending part from system left edge
            osys = self.systems[start_sys]
            self._curve_into(osys, sx, sy, osys.width or sx + 3, sy, ydir)
            sx = 0.8
        self._curve_into(self.cur, sx, sy + 0.15 * ydir, ex, sy + 0.15 * ydir,
                         ydir, shape=shape)

    def _draw_slur(self, sx, sy, ex, ey, ydir, start_sys, sidx, ext=None,
                   shape=None):
        if start_sys != len(self.systems) - 1:
            osys = self.systems[start_sys]
            self._curve_into(osys, sx, sy, (osys.width or sx + 4), sy, ydir)
            sx, sy = 0.8, ey
        self._curve_into(self.cur, sx, sy, ex, ey, ydir, clear=ext, shape=shape)

    def _curve_into(self, sys_, x1, y1, x2, y2, ydir, clear=None, shape=None):
        span = max(x2 - x1, 0.5)
        h = min(0.8 + span * 0.12, 2.4)
        if clear is not None:
            # arc must clear the extreme notehead between the endpoints;
            # apex of this cubic is at midpoint y + 0.75 * h
            midy = (y1 + y2) / 2
            if ydir < 0:
                need = (midy - (clear - 0.4)) / 0.75
            else:
                need = ((clear + 0.4) - midy) / 0.75
            h = max(h, min(need, 6.0))
        h *= ydir
        cx1 = x1 + span * 0.25
        cx2 = x1 + span * 0.75
        cy1 = y1 + h
        cy2 = y2 + h
        if shape and len(shape) == 4:
            # \shape displacements: lilypond's y-axis points up, ours points
            # down, so dy is negated; dx matches our left-right x directly
            (dx1, dy1), (dcx1, dcy1), (dcx2, dcy2), (dx2, dy2) = shape
            x1, y1 = x1 + dx1, y1 - dy1
            cx1, cy1 = cx1 + dcx1, cy1 - dcy1
            cx2, cy2 = cx2 + dcx2, cy2 - dcy2
            x2, y2 = x2 + dx2, y2 - dy2
        sys_.items.append(Curve(x1, y1, cx1, cy1, cx2, cy2, x2, y2))

    def _flush_cross_system(self):
        # unresolved ties/slurs at end: draw short curve fading out
        for (sidx, _sem, _v), (sx, sy, ydir, sysi, _shape) in self.pending_ties.items():
            sys_ = self.systems[sysi]
            self._curve_into(sys_, sx, sy, sx + 2.5, sy, ydir)
        self.pending_ties.clear()

    # ---- grace notes -----------------------------------------------------------

    def _emit_graces(self, col, x_end):
        size = 0.62
        for sidx, gevents in col["graces"].items():
            st = self.staves[sidx]
            n = len(gevents)
            x = x_end - 1.5 * n
            for e in gevents:
                node = e.node
                if not node.pitches:
                    x += 1.5
                    continue
                head = notehead_for(node.duration)
                positions = [st.clef.pos_of(p) for p in node.pitches]
                for pos in positions:
                    y = self.y_of_pos(sidx, pos)
                    self.cur.items.append(Glyph(head, x, y, size=size, staff=sidx))
                # small stem up + flag
                pos = max(positions)
                y = self.y_of_pos(sidx, pos)
                sx = x + smufl.width(head) * size - 0.05
                stem_top = y - 2.4
                self.cur.items.append(Line(sx, y - 0.15, sx, stem_top,
                                           0.1, staff=sidx))
                if node.duration.log >= 3:
                    self.cur.items.append(Glyph("flag8thUp", sx, stem_top,
                                                size=size, staff=sidx))
                x += 1.5

    # ---- beaming / stems / flags -------------------------------------------------

    def _beam_voice(self, vkey, recs, plan):
        """Draw stems, flags and beams for one voice in one measure."""
        sidx, _voice = vkey
        sig = plan["sig"]
        recs = [r for r in recs if not r.get("hidden")]
        if not recs:
            return
        groups = self._beam_groups(recs, sig, plan["start"])
        beamed_ids = set()
        for g in groups:
            if len(g) >= 2:
                self._draw_beam_group(g)
                for r in g:
                    beamed_ids.add(id(r))
        for r in recs:
            if id(r) not in beamed_ids:
                self._draw_stem_flag(r)

    def _beam_groups(self, recs, sig, m_start):
        # manual beams first
        groups = []
        manual = None
        auto_break = self._beat_len(sig)
        cur = []
        for r in recs:
            beamable = r["log"] >= 3
            if manual is not None:
                if beamable:
                    manual.append(r)
                if r["beam_close"]:
                    groups.append(manual)
                    manual = None
                continue
            if r["beam_open"] and beamable:
                if len(cur) >= 2:
                    groups.append(cur)
                cur = []
                manual = [r]
                continue
            if not beamable:
                if len(cur) >= 2:
                    groups.append(cur)
                cur = []
                continue
            # auto grouping: break at beat boundaries
            if cur:
                prev = cur[-1]
                gap = r["time"] - (prev["time"] + prev["duration"])
                beat = auto_break
                # 16ths and shorter group per quarter in simple meters
                if (prev["log"] >= 4 or r["log"] >= 4) and sig[1] in (2, 4):
                    beat = min(beat, Fraction(1, 4))
                crosses = self._crosses_beat(prev, r, m_start, beat)
                if gap != 0 or crosses:
                    if len(cur) >= 2:
                        groups.append(cur)
                    cur = []
            cur.append(r)
        if manual and len(manual) >= 2:
            groups.append(manual)
        if len(cur) >= 2:
            groups.append(cur)
        return groups

    def _beat_len(self, sig):
        num, den = sig
        if den == 8 and num % 3 == 0:
            return Fraction(3, 8)
        if (num, den) in ((4, 4), (2, 2)):
            return Fraction(1, 2)
        if (num, den) == (3, 4):
            return Fraction(3, 4)
        return Fraction(1, den)

    def _crosses_beat(self, prev, r, m_start, beat):
        b0 = (prev["time"] - m_start) // beat
        b1 = (r["time"] - m_start) // beat
        return b0 != b1

    def _stem_x(self, r, up):
        if up:
            a = smufl.anchor(notehead_for_log(r["log"]), "stemUpSE",
                             [r["head_w"], 0])
            return r["hx"] + a[0] - 0.06
        a = smufl.anchor(notehead_for_log(r["log"]), "stemDownNW", [0, 0])
        return r["hx"] + a[0] + 0.06

    def _draw_stem_flag(self, r):
        cfg = self.cfg
        log = r["log"]
        if log <= 0:
            return   # whole notes: no stem
        up = r["stem_up"]
        sidx = r["staff"]
        x = self._stem_x(r, up)
        extra = max(0, log - 4) * 0.6
        stem_len = cfg.stem_len + extra
        if up:
            y_start = min(r["ys"]) - 0.15
            y_att = max(r["ys"])   # stem spans chord
            y_end = min(r["ys"]) - stem_len
            y_from = y_att - 0.15
        else:
            y_att = min(r["ys"])
            y_end = max(r["ys"]) + stem_len
            y_from = y_att + 0.15
        # notes far from staff: stem reaches middle line
        mid = self.staff_top(sidx) + 2
        if up and y_end > mid and min(r["ys"]) > mid + 3:
            y_end = mid
        if not up and y_end < mid and max(r["ys"]) < mid - 3:
            y_end = mid
        self.cur.items.append(Line(x, y_from, x, y_end,
                                   cfg.stem_thickness, color=r["color"],
                                   staff=sidx))
        r["stem_end_y"] = y_end
        if log >= 3:
            table = smufl.FLAG_UP_FOR_LOG if up else smufl.FLAG_DOWN_FOR_LOG
            g = table.get(log)
            if g:
                self.cur.items.append(Glyph(g, x - (cfg.stem_thickness / 2 if up else cfg.stem_thickness / 2), y_end,
                                            color=r["color"], staff=sidx))

    def _draw_beam_group(self, g):
        cfg = self.cfg
        sidx = g[0]["staff"]
        # direction: explicit \stemUp/\voiceOne wins, else majority position
        explicit = [r["stem_dir"] for r in g if r.get("stem_dir")]
        if explicit:
            up = explicit[0] > 0
        else:
            allpos = [p for r in g for p in r["positions"]]
            up = (sum(allpos) / len(allpos)) < 4
        for r in g:
            r["stem_up"] = up
        x0 = self._stem_x(g[0], up)
        x1 = self._stem_x(g[-1], up)
        # beam line through outer notes
        def head_y(r):
            return min(r["ys"]) if up else max(r["ys"])
        yh0, yh1 = head_y(g[0]), head_y(g[-1])
        # damped slant: follow the run's contour, capped by span length
        span = max(x1 - x0, 0.1)
        cap = min(1.0 + span * 0.2, 3.5)
        slant = max(-cap, min(cap, (yh1 - yh0) * 0.6))
        ideal = 3.1     # beamed stems run a bit shorter than lone stems
        b0 = (yh0 - ideal) if up else (yh0 + ideal)
        b1 = b0 + slant
        xs = [self._stem_x(r, up) for r in g]
        ts = [0 if x1 == x0 else (x - x0) / (x1 - x0) for x in xs]
        # balance the beam about the run: average stem length == ideal
        # (shortens stems toward beams over rising/falling runs instead of
        # only ever pushing the beam away from the heads)
        lens = [(head_y(r) - (b0 + (b1 - b0) * t)) if up
                else ((b0 + (b1 - b0) * t) - head_y(r))
                for r, t in zip(g, ts)]
        excess = sum(lens) / len(lens) - ideal
        if up:
            b0 += excess
            b1 += excess
        else:
            b0 -= excess
            b1 -= excess
        # then keep every stem at least 2.5 by pushing away only
        for r, t in zip(g, ts):
            line_y = b0 + (b1 - b0) * t
            if up and line_y > head_y(r) - 2.5:
                delta = line_y - (head_y(r) - 2.5)
                b0 -= delta
                b1 -= delta
            elif not up and line_y < head_y(r) + 2.5:
                delta = (head_y(r) + 2.5) - line_y
                b0 += delta
                b1 += delta
        # stems
        for r in g:
            x = self._stem_x(r, up)
            t = 0 if x1 == x0 else (x - x0) / (x1 - x0)
            y_end = b0 + (b1 - b0) * t
            if up:
                y_from = max(r["ys"]) - 0.15
            else:
                y_from = min(r["ys"]) + 0.15
            self.cur.items.append(Line(x, y_from, x, y_end, cfg.stem_thickness,
                                       color=r["color"], staff=sidx))
            r["stem_end_y"] = y_end
        # primary beam
        half = cfg.beam_thick / 2
        dirn = 1 if up else -1
        self.cur.items.append(Beam(x0, b0 + half * dirn, x1, b1 + half * dirn,
                                   cfg.beam_thick, staff=sidx))
        # secondary beams
        level = 1
        step = (cfg.beam_thick + cfg.beam_gap) * (1 if up else -1)
        while True:
            need_log = 3 + level
            if not any(r["log"] >= need_log for r in g):
                break
            segs = []
            i = 0
            while i < len(g):
                if g[i]["log"] >= need_log:
                    j = i
                    while j + 1 < len(g) and g[j + 1]["log"] >= need_log:
                        j += 1
                    segs.append((i, j))
                    i = j + 1
                else:
                    i += 1
            for (i, j) in segs:
                xa = self._stem_x(g[i], up)
                xb = self._stem_x(g[j], up)
                if i == j:
                    # stub: 1.0 space hook toward group inside
                    if i == 0:
                        xb = xa + 1.0
                    else:
                        xb = xa
                        xa = xb - 1.0
                ta = 0 if x1 == x0 else (xa - x0) / (x1 - x0)
                tb = 0 if x1 == x0 else (xb - x0) / (x1 - x0)
                ya = b0 + (b1 - b0) * ta + step * level + half * dirn
                yb = b0 + (b1 - b0) * tb + step * level + half * dirn
                self.cur.items.append(Beam(xa, ya, xb, yb, cfg.beam_thick,
                                           staff=sidx))
            level += 1

    # ---- tuplets -------------------------------------------------------------

    def _draw_tuplets(self, beam_records):
        by_group = {}
        for (sidx, _v), recs in beam_records.items():
            for r in recs:
                if r["tuplet"]:
                    by_group.setdefault((sidx, r["tuplet"][2]), []).append(r)
        for (sidx, _gid), recs in by_group.items():
            recs.sort(key=lambda r: r["x"])
            num = recs[0]["tuplet"][0]
            x0 = recs[0]["hx"] - 0.3
            x1 = recs[-1]["hx"] + recs[-1]["head_w"] + 0.5
            top = min(min(r["ys"]) for r in recs)
            top = min(top, min((r.get("stem_end_y", top) for r in recs)))
            y = min(top - 1.0, self.staff_top(sidx) - 1.2)
            xm = (x0 + x1) / 2
            # bracket
            self.cur.items.append(Line(x0, y + 0.6, x0, y, 0.13, staff=sidx))
            self.cur.items.append(Line(x0, y, xm - 0.8, y, 0.13, staff=sidx))
            self.cur.items.append(Line(xm + 0.8, y, x1, y, 0.13, staff=sidx))
            self.cur.items.append(Line(x1, y, x1, y + 0.6, 0.13, staff=sidx))
            self.cur.items.append(Text(str(num), xm, y + 0.45, size=0.9,
                                       style="tuplet", anchor="center",
                                       italic=True, staff=sidx))

    # ---- system finishing -------------------------------------------------------

    def _finish_system(self, final=False):
        cfg = self.cfg
        sys_ = self.cur
        if final and self.x > 0:
            pass
        sys_.width = self.x + (0.2 if not final else 0.6)
        # staff lines
        for i in range(len(self.staves)):
            top = sys_.staff_tops[i]
            for ln in range(5):
                y = top + ln
                sys_.items.insert(0, Line(0, y, sys_.width, y, cfg.staff_line,
                                          staff=i))
        self._settle_pedals(sys_)
        # lyrics
        for i, st in enumerate(self.staves):
            if not st.data.lyrics:
                continue
            base_y = sys_.staff_tops[i] + 4 + cfg.lyric_gap
            tm = dict(sys_.time_map)
            for (t, text) in st.data.lyrics:
                if sys_.start_time <= t and (final or t < sys_.end_time) \
                        and t in tm:
                    sys_.items.append(Text(text, tm[t] + 0.5, base_y,
                                           style="lyric", anchor="center",
                                           staff=i))

    def _settle_pedals(self, sys_):
        """Move pedal marks below noteheads/stems/beams that hang under the
        staff, so Ped./* never collide with low bass notes."""
        import bisect
        pedal_names = set(smufl.PEDAL_GLYPHS.values())
        for i in range(len(self.staves)):
            bottom = sys_.staff_tops[i] + 4
            peds = [it for it in sys_.items
                    if isinstance(it, Glyph) and it.staff == i
                    and it.name in pedal_names]
            if not peds:
                continue
            content = []
            for it in sys_.items:
                if getattr(it, "staff", 0) != i:
                    continue
                if isinstance(it, Glyph):
                    if it.name not in pedal_names and it.y > bottom:
                        content.append((it.x, it.y + 0.8))
                elif isinstance(it, Line):
                    if abs(it.x1 - it.x2) < 1e-6 and abs(it.y2 - it.y1) > 7:
                        continue      # barline
                    y = max(it.y1, it.y2)
                    if y > bottom:
                        content.append((min(it.x1, it.x2), y))
                        content.append((max(it.x1, it.x2), y))
                elif isinstance(it, Beam):
                    y = max(it.y1, it.y2)
                    if y > bottom:
                        content.append((min(it.x1, it.x2), y))
                        content.append((max(it.x1, it.x2), y))
            if not content:
                continue
            if self.scroll:
                # endless system: clear only nearby content
                content.sort()
                xs = [c[0] for c in content]
                for g in peds:
                    lo = bisect.bisect_left(xs, g.x - 2.5)
                    hi = bisect.bisect_right(xs, g.x + 2.5)
                    if lo < hi:
                        g.y = max(g.y, max(content[k][1]
                                           for k in range(lo, hi)) + 1.4)
            else:
                # one aligned pedal baseline per system (lilypond-like)
                base = max(c[1] for c in content) + 1.4
                for g in peds:
                    g.y = max(g.y, base)

    def _measure_system_bounds(self, s: System):
        min_y = -1.5
        max_y = s.height + 1.0
        for it in s.items:
            if isinstance(it, Glyph):
                if it.text is not None:
                    min_y = min(min_y, it.y - 1.2 * it.size)
                    max_y = max(max_y, it.y + 1.2 * it.size)
                elif smufl.has_glyph(it.name):
                    w, so, e, n = smufl.bbox(it.name)   # SMuFL y-up, staff spaces
                    min_y = min(min_y, it.y - n * it.size)
                    max_y = max(max_y, it.y - so * it.size)
                else:
                    min_y = min(min_y, it.y - 1.2 * it.size)
                    max_y = max(max_y, it.y + 1.2 * it.size)
            elif isinstance(it, Text):
                max_y = max(max_y, it.y + 1.5)
                min_y = min(min_y, it.y - 1.5)
            elif isinstance(it, Line):
                min_y = min(min_y, it.y1, it.y2)
                max_y = max(max_y, it.y1, it.y2)
            elif isinstance(it, Beam):
                min_y = min(min_y, it.y1, it.y2)
                max_y = max(max_y, it.y1, it.y2)
            elif isinstance(it, Curve):
                # a cubic bezier lies within the hull of its 4 control
                # points, so their min/max is a safe (if slightly loose)
                # bound; slurs/ties/hairpins routinely sweep well past the
                # staff in this piece's hand-shaped \shape overrides and
                # were previously invisible to system-height measurement,
                # undersizing the gap before the next system
                ys = (it.y1, it.cy1, it.cy2, it.y2)
                min_y = min(min_y, *ys)
                max_y = max(max_y, *ys)
        s.top = -min_y
        s.height = max_y

    def _justify(self):
        """Stretch each full system to line width (except the last).

        Real LilyPond's spring-and-rod model only stretches the flexible
        note-to-note "springs"; glyph-width-bound "rods" (dense chords,
        stacked accidentals) stay at their natural minimum. A single
        uniform scale factor (the old approach here) stretches both alike,
        which distorts the relative spacing within a system even when the
        total system width matches. `_emit_measure` now records each
        column's (x_start, x_end, flexible, spring) in `s.segments`; use
        that to distribute the needed extra width only into the flexible
        segments, proportional to their spring value."""
        import bisect
        cfg = self.cfg
        for k, s in enumerate(self.systems):
            if s.width <= 0:
                continue
            last = (k == len(self.systems) - 1)
            if last and s.width < cfg.line_width * 0.7:
                continue
            extra = cfg.line_width - s.width
            if abs(extra) <= 0.001:
                continue
            segs = sorted(s.segments, key=lambda sg: sg[0])
            total_spring = sum(sp for (_x0, _x1, flex, sp) in segs if flex)
            if not total_spring:
                # no flexible columns (e.g. an all-rod system): fall back to
                # the old uniform scale rather than leaving it unstretched
                f = cfg.line_width / s.width
                for it in s.items:
                    if isinstance(it, (Glyph, Text)):
                        it.x *= f
                    elif isinstance(it, Line):
                        it.x1 *= f; it.x2 *= f
                    elif isinstance(it, Beam):
                        it.x1 *= f; it.x2 *= f
                    elif isinstance(it, Curve):
                        it.x1 *= f; it.cx1 *= f; it.cx2 *= f; it.x2 *= f
                s.time_map = [(t, x * f) for (t, x) in s.time_map]
                s.width = cfg.line_width
                continue

            # breakpoints at both the start (pre-stretch offset) and end
            # (post-stretch offset) of every segment, so x's that fall in
            # the untracked gaps between columns (barlines, mid-measure
            # clef/key prefixes) still carry forward the right cumulative
            # offset instead of losing whatever this segment just added
            breakpoints = []
            cum = 0.0
            for (x0, x1, flex, sp) in segs:
                breakpoints.append((x0, cum))
                if flex and sp:
                    cum += extra * (sp / total_spring)
                breakpoints.append((x1, cum))
            xs = [b[0] for b in breakpoints]
            offs = [b[1] for b in breakpoints]

            def remap(x, xs=xs, offs=offs, tail=cum):
                if not xs or x < xs[0]:
                    return x
                i = bisect.bisect_right(xs, x) - 1
                return x + (offs[i] if i < len(offs) else tail)

            for it in s.items:
                if isinstance(it, (Glyph, Text)):
                    it.x = remap(it.x)
                elif isinstance(it, Line):
                    it.x1 = remap(it.x1)
                    it.x2 = remap(it.x2)
                elif isinstance(it, Beam):
                    it.x1 = remap(it.x1)
                    it.x2 = remap(it.x2)
                elif isinstance(it, Curve):
                    nx1, nx2 = remap(it.x1), remap(it.x2)
                    span_old = it.x2 - it.x1
                    f_local = (nx2 - nx1) / span_old if abs(span_old) > 1e-6 else 1.0
                    it.cx1 = nx1 + (it.cx1 - it.x1) * f_local
                    it.cx2 = nx1 + (it.cx2 - it.x1) * f_local
                    it.x1, it.x2 = nx1, nx2
            s.time_map = [(t, remap(x)) for (t, x) in s.time_map]
            s.width = cfg.line_width


def notehead_for_log(log):
    if log <= -1:
        return smufl.NOTEHEAD_BREVE
    return smufl.NOTEHEAD_FOR_LOG.get(log, smufl.NOTEHEAD_BLACK)


def engrave(score: Score, line_width=110.0, scroll=False) -> LayoutResult:
    cfg = Config()
    if scroll:
        cfg.line_width = None
    elif line_width:
        cfg.line_width = line_width
    return Engraver(score, cfg, scroll=scroll).engrave()
