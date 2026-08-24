"""Music model: AST produced by the parser and semantic objects shared with
the interpreter/layout stages.

Time is exact: fractions.Fraction of a whole note.
Pitch: diatonic step 0..6 (c..b), alteration in semitones (-2..2), octave
(0 == the octave of middle C, i.e. lilypond c' ; lilypond "c" is octave -1).
Staff position: diatonic steps above the bottom staff line (computed later
from clef + pitch).
"""

from dataclasses import dataclass, field
from fractions import Fraction
from typing import List, Optional, Tuple


STEP_NAMES = "cdefgab"


@dataclass(frozen=True)
class Pitch:
    step: int          # 0=c .. 6=b
    alter: int         # semitones, -2..+2 (es/is suffixes; -1=flat 1=sharp)
    octave: int        # 0 == lilypond c' (the octave starting at middle C)

    @property
    def diatonic(self):
        """Absolute diatonic index used for staff positions & \\relative."""
        return self.octave * 7 + self.step

    def semitones(self):
        base = [0, 2, 4, 5, 7, 9, 11][self.step]
        return self.octave * 12 + base + self.alter

    def name(self):
        s = STEP_NAMES[self.step]
        s += {-2: "eses", -1: "es", 0: "", 1: "is", 2: "isis"}[self.alter]
        if self.octave >= 1:
            s += "'" * self.octave
        elif self.octave <= -1:
            s += "," * (-self.octave)
        return s


@dataclass(frozen=True)
class Duration:
    log: int           # 0=whole 1=half 2=quarter 3=eighth ... (-1=breve)
    dots: int = 0
    factor: Fraction = Fraction(1)   # tuplet scaling

    def length(self) -> Fraction:
        base = Fraction(1, 2 ** self.log) if self.log >= 0 else Fraction(2 ** -self.log)
        total = base
        add = base
        for _ in range(self.dots):
            add /= 2
            total += add
        return total * self.factor

    def with_factor(self, f: Fraction) -> "Duration":
        return Duration(self.log, self.dots, self.factor * f)


# ---------------------------------------------------------------------------
# AST nodes (parser output)
# ---------------------------------------------------------------------------

@dataclass
class PostEvent:
    """Attached to a note/chord/rest: articulations, dynamics, slur marks..."""
    kind: str          # 'articulation','dynamic','fingering','slur_open',
                       # 'slur_close','phrasing_open','phrasing_close',
                       # 'beam_open','beam_close','tie','text','cresc','decresc','end_hairpin'
    value: object = None
    direction: int = 0     # -1 below, +1 above, 0 default


@dataclass
class NoteNode:
    pitches: List[Pitch]              # 1 = note, >1 = chord
    duration: Optional[Duration]      # None = inherit previous
    post: List[PostEvent] = field(default_factory=list)
    is_rest: bool = False             # r
    is_skip: bool = False             # s
    is_full_measure_rest: bool = False  # R
    multiplier: int = 1               # R1*4
    is_chord_repeat: bool = False     # q


@dataclass
class ClefNode:
    name: str

@dataclass
class KeyNode:
    tonic: Pitch
    mode: str          # 'major' | 'minor'

@dataclass
class TimeNode:
    num: int
    den: int

@dataclass
class TempoNode:
    text: Optional[str] = None
    unit: Optional[Duration] = None
    bpm: Optional[int] = None

@dataclass
class BarNode:
    style: str         # "|." "||" ":|." ".|:" ...

@dataclass
class PartialNode:
    duration: Duration

@dataclass
class BreakNode:
    kind: str          # 'line', 'noBreak', 'page'

@dataclass
class SequentialNode:
    elements: list = field(default_factory=list)

@dataclass
class SimultaneousNode:
    elements: list = field(default_factory=list)
    voice_separated: bool = False     # << ... \\ ... >>

@dataclass
class RelativeNode:
    reference: Optional[Pitch]
    body: object

@dataclass
class TupletNode:
    ratio: Tuple[int, int]            # (3,2) for \tuplet 3/2
    body: object

@dataclass
class GraceNode:
    body: object
    kind: str = "grace"               # grace | acciaccatura | appoggiatura

@dataclass
class ContextNode:
    ctype: str                        # 'Staff','Voice','PianoStaff','GrandStaff',...
    name: Optional[str]
    body: object
    is_new: bool = True

@dataclass
class LyricsNode:
    syllables: list = field(default_factory=list)   # list of (text, extender:str)

@dataclass
class AddLyricsNode:
    lyrics: LyricsNode = None

@dataclass
class ScoreNode:
    body: object
    header: dict = field(default_factory=dict)
    paper: dict = field(default_factory=dict)

@dataclass
class BookNode:
    scores: list = field(default_factory=list)
    header: dict = field(default_factory=dict)

@dataclass
class MarkupNode:
    text: str

@dataclass
class SchemeNode:
    value: object                     # already-evaluated pyscheme value

@dataclass
class OverrideNode:
    path: str                         # e.g. "NoteHead.color"
    value: object

@dataclass
class UnsupportedNode:
    """Recognised-but-ignored command; keeps the pipeline tolerant."""
    text: str


@dataclass
class ChangeStaffNode:
    """\\change Staff = "name": later notes print on another staff."""
    target: str


@dataclass
class OttavaNode:
    """\\ottava n: display shift of n octaves with an 8va/8vb mark."""
    octaves: int


@dataclass
class StemNode:
    """\\stemUp/\\stemDown/\\voiceOne...: preferred stem direction."""
    direction: int                    # +1 up, -1 down, 0 back to automatic


@dataclass
class HideNode:
    """\\hideNotes/\\unHideNotes: suppress noteheads/stems/accidentals
    (a standard LilyPond voice-leading trick) without removing them from
    the timeline; hidden notes still occupy their duration but contribute
    ~no glyph width, since their stencils are empty in real LilyPond."""
    hidden: bool


@dataclass
class ScaleDurationsNode:
    """\\scaleDurations f: durations scaled without a tuplet bracket."""
    factor: Fraction
    body: object = None


@dataclass
class TagNode:
    """\\tag names music: kept/dropped by \\keepWithTag/\\removeWithTag."""
    tags: frozenset
    body: object = None


@dataclass
class KeepTagNode:
    """\\keepWithTag (keep=True) or \\removeWithTag (keep=False)."""
    tags: frozenset
    body: object = None
    keep: bool = True


@dataclass
class RepeatNode:
    """\\repeat unfold n music: interpreted by replaying the resolved body."""
    count: int
    body: object = None


@dataclass
class PostMarkNode:
    """A post event written detached from its note (\\sustainOn etc.);
    the interpreter attaches it to the preceding event."""
    event: PostEvent = None


# ---------------------------------------------------------------------------
# Resolved (interpreted) structures consumed by layout
# ---------------------------------------------------------------------------

@dataclass
class TimedEvent:
    """A note/chord/rest placed on the timeline of one voice."""
    time: Fraction
    duration: Fraction                # actual length (tuplet-scaled)
    node: NoteNode
    voice: int = 0                    # 0 = single/first voice
    grace_index: int = 0              # >0: grace note n slots before `time`
    tuplet: Optional[tuple] = None    # (num,den,group_id) for bracket drawing
    stem_dir: int = 0                 # \stemUp/\voiceOne...: +1 up, -1 down
    ottava: int = 0                   # \ottava displayed-octave shift
    seq: int = 0                      # global walk order (debugging/tests)
    unfolded: bool = False            # replayed copy from \repeat unfold
    hidden: bool = False              # \hideNotes: no stencil, ~no glyph width


@dataclass
class AttributeEvent:
    time: Fraction
    kind: str                         # 'clef','key','time','tempo','bar','partial'
    value: object


@dataclass
class StaffData:
    name: Optional[str] = None
    events: List[TimedEvent] = field(default_factory=list)
    attributes: List[AttributeEvent] = field(default_factory=list)
    lyrics: List[Tuple[Fraction, str]] = field(default_factory=list)
    end_time: Fraction = Fraction(0)


@dataclass
class StaffGroup:
    kind: str                         # 'PianoStaff','GrandStaff','StaffGroup','ChoirStaff'
    staves: List[int] = field(default_factory=list)   # indices into Score.staves


@dataclass
class Score:
    staves: List[StaffData] = field(default_factory=list)
    groups: List[StaffGroup] = field(default_factory=list)
    header: dict = field(default_factory=dict)
    paper: dict = field(default_factory=dict)
    # time -> 'line'/'page', forced \break/\pageBreak points (explicit
    # hand-placed breaks used by heavily hand-tuned scores); \noBreak
    # points aren't stored since the absence of a forced break already
    # means "don't break here" once any forced break exists.
    breaks: dict = field(default_factory=dict)


def clef_middle_c_position(clef_name: str) -> int:
    """Staff position (diatonic steps above bottom line) of middle C."""
    from . import smufl
    glyph, line = smufl.CLEF_GLYPHS.get(clef_name, ("gClef", 1))
    if glyph.startswith("gClef"):
        pos = 2 * line - 4
    elif glyph.startswith("fClef"):
        pos = 2 * line + 4
    else:  # cClef family / percussion: middle C on the clef's line
        pos = 2 * line
    if glyph.endswith("8vb"):
        pos += 7
    elif glyph.endswith("8va"):
        pos -= 7
    return pos
