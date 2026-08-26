"""Music font access: glyph codepoints, bounding boxes, anchors, engraving
defaults.  Uses a private-use-area-patched copy of real LilyPond's own
Emmentaler font (see tools/build_emmentaler_font.py) rather than Bravura/
SMuFL, so glyph shapes match real LilyPond output exactly.  All geometry is
in staff spaces (SMuFL convention carried over: 1 em == 4 staff spaces,
metadata units are staff spaces, y up-positive) -- verified true for
Emmentaler too (unitsPerEm/4 == 1 staff space).

The rest of the program uses y DOWN-positive (screen convention), so callers
must negate metadata y values where relevant; helpers here return raw values
and document the convention.
"""

import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)

BRAVURA_OTF = os.path.join(_ROOT, "Emmentaler.otf")
BRAVURA_TEXT_OTF = os.path.join(_ROOT, "BravuraText.otf")

_symbols = None       # name -> codepoint int
_metadata = None      # full emmentaler_metadata.json


def _load():
    global _symbols, _metadata
    if _symbols is None:
        with open(os.path.join(_ROOT, "emmentaler_symbols.json"), encoding="utf-8") as f:
            raw = json.load(f)
        _symbols = {name: int(info["codepoint"][2:], 16) for name, info in raw.items()}
        with open(os.path.join(_ROOT, "emmentaler_metadata.json"), encoding="utf-8") as f:
            _metadata = json.load(f)


def char(name):
    """Unicode character for a SMuFL glyph name, e.g. 'noteheadBlack'."""
    _load()
    return chr(_symbols[name])


def has_glyph(name):
    _load()
    return name in _symbols


def bbox(name):
    """(west, south, east, north) in staff spaces, SMuFL y-up."""
    _load()
    bb = _metadata["glyphBBoxes"].get(name)
    if bb is None:
        return (0.0, -0.5, 1.0, 0.5)
    (e, n), (w, s) = bb["bBoxNE"], bb["bBoxSW"]
    return (w, s, e, n)


def width(name):
    w, _s, e, _n = bbox(name)
    return e - w


def anchor(name, key, default=None):
    """SMuFL anchor point [x, y] in staff spaces (y-up), e.g. stemUpSE."""
    _load()
    g = _metadata["glyphsWithAnchors"].get(name)
    if g is None or key not in g:
        return default
    return g[key]


def engraving(key, default=None):
    """Engraving default in staff spaces, e.g. 'stemThickness'."""
    _load()
    return _metadata["engravingDefaults"].get(key, default)


# ---------------------------------------------------------------------------
# Common lookup tables used by the layout engine.
# ---------------------------------------------------------------------------

NOTEHEAD_FOR_LOG = {
    # duration log: 0=whole 1=half 2=quarter(and shorter use black)
    0: "noteheadWhole",
    1: "noteheadHalf",
}
NOTEHEAD_BLACK = "noteheadBlack"
NOTEHEAD_BREVE = "noteheadDoubleWhole"

REST_FOR_LOG = {
    -1: "restDoubleWhole",
    0: "restWhole",
    1: "restHalf",
    2: "restQuarter",
    3: "rest8th",
    4: "rest16th",
    5: "rest32nd",
    6: "rest64th",
    7: "rest128th",
    8: "rest256th",
    9: "rest512th",
    10: "rest1024th",
}

FLAG_UP_FOR_LOG = {
    3: "flag8thUp",
    4: "flag16thUp",
    5: "flag32ndUp",
    6: "flag64thUp",
    7: "flag128thUp",
    8: "flag256thUp",
    9: "flag512thUp",
    10: "flag1024thUp",
}
FLAG_DOWN_FOR_LOG = {
    3: "flag8thDown",
    4: "flag16thDown",
    5: "flag32ndDown",
    6: "flag64thDown",
    7: "flag128thDown",
    8: "flag256thDown",
    9: "flag512thDown",
    10: "flag1024thDown",
}

CLEF_GLYPHS = {
    # name -> (glyph, staff line the clef sits on [0=bottom line], octave shift glyph pos)
    "treble":   ("gClef", 1),
    "violin":   ("gClef", 1),
    "G":        ("gClef", 1),
    "bass":     ("fClef", 3),
    "F":        ("fClef", 3),
    "alto":     ("cClef", 2),
    "C":        ("cClef", 2),
    "tenor":    ("cClef", 3),
    "soprano":  ("cClef", 0),
    "mezzosoprano": ("cClef", 1),
    "baritone": ("cClef", 4),
    "treble_8": ("gClef8vb", 1),
    "treble^8": ("gClef8va", 1),
    "bass_8":   ("fClef8vb", 3),
    "bass^8":   ("fClef8va", 3),
    "percussion": ("unpitchedPercussionClef1", 2),
}

# Middle-c staff position offset per clef: staff position of middle C
# measured in diatonic steps from the bottom staff line (line 0).
# treble: middle C sits on the first ledger line below the staff = -2.
MIDDLE_C_POSITION = {
    "gClef": -2, "gClef8vb": 5, "gClef8va": -9,
    "fClef": 10, "fClef8vb": 17, "fClef8va": 3,
    "cClef": 4,  # relative to the line the clef is centered on (line 2 for alto)
    "unpitchedPercussionClef1": 4,
}

ACCIDENTAL_GLYPHS = {
    -2: "accidentalDoubleFlat",
    -1: "accidentalFlat",
    0: "accidentalNatural",
    1: "accidentalSharp",
    2: "accidentalDoubleSharp",
}

DYNAMIC_GLYPHS = {
    "pppp": "dynamicPPPP", "ppp": "dynamicPPP", "pp": "dynamicPP",
    "p": "dynamicPiano", "mp": "dynamicMP", "mf": "dynamicMF",
    "f": "dynamicForte", "ff": "dynamicFF", "fff": "dynamicFFF",
    "ffff": "dynamicFFFF",
    "fp": "dynamicFortePiano", "sf": "dynamicSforzando1",
    "sff": "dynamicSforzatoFF", "sfp": "dynamicSforzatoPiano",
    "sfz": "dynamicSforzato", "fz": "dynamicForzando",
    "rf": "dynamicRinforzando1", "rfz": "dynamicRinforzando2",
    "sp": "dynamicSforzandoPiano", "spp": "dynamicSforzandoPianissimo",
}

PEDAL_GLYPHS = {
    "sustain_on": "keyboardPedalPed",
    "sustain_off": "keyboardPedalUp",
}

ARPEGGIO_GLYPH = "arpeggiatoUp"

OTTAVA_GLYPHS = {1: "ottavaAlta", -1: "ottavaBassaVb",
                 2: "quindicesimaAlta", -2: "quindicesimaBassaMb"}

ARTICULATION_GLYPHS = {
    # lilypond name -> (above glyph, below glyph)
    "staccato": ("articStaccatoAbove", "articStaccatoBelow"),
    "accent": ("articAccentAbove", "articAccentBelow"),
    "tenuto": ("articTenutoAbove", "articTenutoBelow"),
    "marcato": ("articMarcatoAbove", "articMarcatoBelow"),
    "staccatissimo": ("articStaccatissimoAbove", "articStaccatissimoBelow"),
    "portato": ("articTenutoStaccatoAbove", "articTenutoStaccatoBelow"),
    "stopped": ("pluckedLeftHandPizzicato", "pluckedLeftHandPizzicato"),
    "fermata": ("fermataAbove", "fermataBelow"),
    "trill": ("ornamentTrill", "ornamentTrill"),
    "turn": ("ornamentTurn", "ornamentTurn"),
    "mordent": ("ornamentMordent", "ornamentMordent"),
    "prall": ("ornamentShortTrill", "ornamentShortTrill"),
}

# Shorthand articulations: -. -> etc.
ARTICULATION_SHORTHAND = {
    ".": "staccato", ">": "accent", "-": "tenuto", "^": "marcato",
    "!": "staccatissimo", "_": "portato", "+": "stopped",
}

# raw Emmentaler glyph name -> our semantic name, for \override
# Staff.Clef.glyph-name = #"clefs.G"-style cosmetic clef-glyph swaps (the
# note-positioning clef and the *drawn* clef glyph are independent in
# LilyPond; this only affects which glyph gets drawn).
RAW_CLEF_GLYPH = {"clefs.G": "gClef", "clefs.F": "fClef", "clefs.C": "cClef",
                  "clefs.G_change": "gClefChange",
                  "clefs.F_change": "fClefChange",
                  "clefs.C_change": "cClefChange"}

TIMESIG_DIGITS = {str(d): "timeSig%d" % d for d in range(10)}

_brace_sizes = None   # [(height_in_staffspaces, glyph_name), ...] sorted


def brace_for_height(height):
    """Real LilyPond's piano brace is ~500 discrete pre-drawn sizes (not one
    stretchable glyph); pick whichever is closest to the needed height and
    return (glyph_name, actual_height)."""
    global _brace_sizes
    _load()
    if _brace_sizes is None:
        sizes = []
        for name in _symbols:
            if name.startswith("brace"):
                w, s, e, n = bbox(name)
                sizes.append((n - s, name))
        sizes.sort()
        _brace_sizes = sizes
    if not _brace_sizes:
        return None, height
    import bisect
    heights = [h for h, _ in _brace_sizes]
    i = bisect.bisect_left(heights, height)
    if i <= 0:
        return _brace_sizes[0][1], _brace_sizes[0][0]
    if i >= len(_brace_sizes):
        return _brace_sizes[-1][1], _brace_sizes[-1][0]
    lo = _brace_sizes[i - 1]
    hi = _brace_sizes[i]
    chosen = lo if (height - lo[0]) <= (hi[0] - height) else hi
    return chosen[1], chosen[0]
