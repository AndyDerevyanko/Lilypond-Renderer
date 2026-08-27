"""One-time asset builder: patch LilyPond's real Emmentaler music font with a
private-use-area cmap so it can be used exactly like Bravura/SMuFL was used
before (single codepoint -> single glyph, drawn via QPainter.drawText).

Emmentaler (the actual font real LilyPond uses to typeset noteheads, clefs,
flags, rests, accidentals, articulations...) ships with glyphs addressed by
*name* only (e.g. "noteheads.s2"), not by unicode codepoint, except for a
handful of ASCII letters/digits used to typeset dynamics text (f, p, m, r,
s, z) and numerals -- those already have normal cmap entries and are left
untouched, and are used for dynamics by drawing literal kerned text with
this font at render time.

Run with the real LilyPond install's font directory as the only argument,
or rely on the hardcoded default path below. Writes to the repo root:
  Emmentaler.otf, emmentaler_symbols.json, emmentaler_metadata.json
"""
import json
import os
import sys

from fontTools.ttLib import TTFont
from fontTools.pens.boundsPen import BoundsPen

_DEFAULT_SRC = (
    r"C:\Users\andyt\AppData\Local\Microsoft\WinGet\Packages"
    r"\LilyPond.LilyPond_Microsoft.Winget.Source_8wekyb3d8bbwe"
    r"\lilypond-2.24.4\share\lilypond\2.24.4\fonts\otf\emmentaler-20.otf"
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# semantic name (as already used throughout lilyrender) -> Emmentaler glyph name
DIRECT_MAP = {
    # noteheads
    "noteheadWhole": "noteheads.s0",
    "noteheadHalf": "noteheads.s1",
    "noteheadBlack": "noteheads.s2",
    "noteheadDoubleWhole": "noteheads.sM1",
    # rests
    "restDoubleWhole": "rests.M1",
    "restWhole": "rests.0",
    "restHalf": "rests.1",
    "restQuarter": "rests.2",
    "rest8th": "rests.3",
    "rest16th": "rests.4",
    "rest32nd": "rests.5",
    "rest64th": "rests.6",
    "rest128th": "rests.7",
    "rest256th": "rests.8",
    "rest512th": "rests.9",
    "rest1024th": "rests.10",
    # flags
    "flag8thUp": "flags.u3", "flag16thUp": "flags.u4", "flag32ndUp": "flags.u5",
    "flag64thUp": "flags.u6", "flag128thUp": "flags.u7", "flag256thUp": "flags.u8",
    "flag512thUp": "flags.u9", "flag1024thUp": "flags.u10",
    "flag8thDown": "flags.d3", "flag16thDown": "flags.d4", "flag32ndDown": "flags.d5",
    "flag64thDown": "flags.d6", "flag128thDown": "flags.d7", "flag256thDown": "flags.d8",
    "flag512thDown": "flags.d9", "flag1024thDown": "flags.d10",
    # clefs (plain; 8va/8vb variants are handled as clef+numeral composites in
    # layout, not here, since Emmentaler has no baked-in octave clef glyphs)
    "gClef": "clefs.G",
    "fClef": "clefs.F",
    "cClef": "clefs.C",
    "unpitchedPercussionClef1": "clefs.percussion",
    # accidentals
    "accidentalDoubleFlat": "accidentals.flatflat",
    "accidentalFlat": "accidentals.flat",
    "accidentalNatural": "accidentals.natural",
    "accidentalSharp": "accidentals.sharp",
    "accidentalDoubleSharp": "accidentals.doublesharp",
    # pedal
    "keyboardPedalPed": "pedal.Ped",
    "keyboardPedalUp": "pedal.*",
    # arpeggio (tiled segment)
    "arpeggiatoUp": "scripts.arpeggio",
    # articulations (above/below variants collapse to Emmentaler's single
    # direction-agnostic glyph where it doesn't provide both)
    "articStaccatoAbove": "scripts.staccato", "articStaccatoBelow": "scripts.staccato",
    "articAccentAbove": "scripts.sforzato", "articAccentBelow": "scripts.sforzato",
    "articTenutoAbove": "scripts.tenuto", "articTenutoBelow": "scripts.tenuto",
    "articMarcatoAbove": "scripts.umarcato", "articMarcatoBelow": "scripts.dmarcato",
    "articStaccatissimoAbove": "scripts.ustaccatissimo",
    "articStaccatissimoBelow": "scripts.dstaccatissimo",
    "articTenutoStaccatoAbove": "scripts.uportato",
    "articTenutoStaccatoBelow": "scripts.dportato",
    "pluckedLeftHandPizzicato": "scripts.snappizzicato",
    "fermataAbove": "scripts.ufermata", "fermataBelow": "scripts.dfermata",
    "ornamentTrill": "scripts.trill",
    "ornamentTurn": "scripts.turn",
    "ornamentMordent": "scripts.mordent",
    "ornamentShortTrill": "scripts.prall",
    # time signature digits + common/cut time
    "timeSig0": "zero", "timeSig1": "one", "timeSig2": "two", "timeSig3": "three",
    "timeSig4": "four", "timeSig5": "five", "timeSig6": "six", "timeSig7": "seven",
    "timeSig8": "eight", "timeSig9": "nine",
    "timeSigCommon": "timesig.C44", "timeSigCutCommon": "timesig.C22",
}

# Composite clef glyphs built by literally stacking two source glyphs into one
# outline (clef + small octave numeral), since Emmentaler has no gClef8vb-style
# precomposed glyph the way Bravura/SMuFL does.
COMPOSITE_CLEFS = {
    # semantic name: (base glyph, numeral glyph, dx, dy, numeral scale)
    "gClef8vb": ("clefs.G", "fixedwidth.eight", 0.0, -0.9, 0.66),
    "gClef8va": ("clefs.G", "fixedwidth.eight", 0.0, 1.55, 0.66),
    "fClef8vb": ("clefs.F", "fixedwidth.eight", 0.0, -0.65, 0.66),
    "fClef8va": ("clefs.F", "fixedwidth.eight", 0.0, 0.7, 0.66),
}

PUA_START = 0xF0000


def build(src_path):
    font = TTFont(src_path)
    upm = font["head"].unitsPerEm
    staff_space = upm / 4.0   # SMuFL-style convention; verified against clef/notehead sizes
    glyph_order = font.getGlyphOrder()
    name_to_gid = {n: i for i, n in enumerate(glyph_order)}
    glyph_set = font.getGlyphSet()

    cmap_additions = {}   # codepoint -> glyph name
    codepoint = PUA_START
    symbols = {}           # our semantic name -> codepoint

    for sem_name, emm_name in DIRECT_MAP.items():
        if emm_name not in name_to_gid:
            print("WARNING: missing source glyph", emm_name, "for", sem_name)
            continue
        cmap_additions[codepoint] = emm_name
        symbols[sem_name] = codepoint
        codepoint += 1

    # --- composite glyphs (clef + octave numeral) ---------------------------
    from fontTools.pens.t2CharStringPen import T2CharStringPen
    from fontTools.pens.transformPen import TransformPen

    cff = font["CFF "].cff
    top_dict = cff.topDictIndex[0]
    charstrings = top_dict.CharStrings

    new_widths = {}
    for sem_name, (base, numeral, dx, dy, nscale) in COMPOSITE_CLEFS.items():
        if base not in glyph_set or numeral not in glyph_set:
            print("WARNING: missing composite source for", sem_name)
            continue
        base_glyph = glyph_set[base]
        width = base_glyph.width
        pen = T2CharStringPen(width, glyph_set)
        base_glyph.draw(pen)
        num_glyph = glyph_set[numeral]
        # place numeral relative to the base glyph's right edge
        bpen = BoundsPen(glyph_set)
        base_glyph.draw(bpen)
        bx0, by0, bx1, by1 = bpen.bounds if bpen.bounds else (0, 0, width, 0)
        tx = bx1 * 1.0 + dx * staff_space
        ty = dy * staff_space
        tpen = TransformPen(pen, (nscale, 0, 0, nscale, tx, ty))
        num_glyph.draw(tpen)
        charstring = pen.getCharString()
        charstring.private = top_dict.Private
        charstring.globalSubrs = cff.GlobalSubrs
        new_name = "lr." + sem_name
        new_index = len(charstrings.charStringsIndex)
        charstrings.charStringsIndex.append(charstring)
        charstrings.charStrings[new_name] = new_index
        new_widths[new_name] = int(width)
        glyph_order.append(new_name)
        name_to_gid[new_name] = len(glyph_order) - 1
        cmap_additions[codepoint] = new_name
        symbols[sem_name] = codepoint
        codepoint += 1

    # --- brace glyphs, copied from the separate emmentaler-brace font ------
    # Real LilyPond's piano brace is not one scalable glyph but ~500 discrete
    # pre-drawn sizes (feta-brace); the renderer picks whichever one is
    # closest to the needed height instead of stretching a single outline.
    brace_src = os.path.join(os.path.dirname(src_path), "emmentaler-brace.otf")
    if os.path.exists(brace_src):
        brace_font = TTFont(brace_src)
        brace_glyphset = brace_font.getGlyphSet()
        brace_names = [n for n in brace_font.getGlyphOrder() if n.startswith("brace")]
        for bname in brace_names:
            src_glyph = brace_glyphset[bname]
            pen = T2CharStringPen(src_glyph.width, glyph_set)
            src_glyph.draw(pen)
            charstring = pen.getCharString()
            charstring.private = top_dict.Private
            charstring.globalSubrs = cff.GlobalSubrs
            new_name = "lr." + bname
            new_index = len(charstrings.charStringsIndex)
            charstrings.charStringsIndex.append(charstring)
            charstrings.charStrings[new_name] = new_index
            new_widths[new_name] = int(src_glyph.width)
            glyph_order.append(new_name)
            name_to_gid[new_name] = len(glyph_order) - 1
            cmap_additions[codepoint] = new_name
            symbols[bname] = codepoint
            codepoint += 1
        print("copied", len(brace_names), "brace glyphs from", brace_src)
    else:
        print("WARNING: no emmentaler-brace.otf next to source; brace unavailable")

    font.setGlyphOrder(glyph_order)
    try:
        top_dict.charset = glyph_order
    except Exception:
        pass
    for new_name, w in new_widths.items():
        font["hmtx"].metrics[new_name] = (w, 0)

    # --- extend cmap ----------------------------------------------------
    # our PUA codepoints (plane 15, 0xF0000+) don't fit in a format-4 (BMP
    # only) subtable -- only the format-12 (full 32-bit) subtable gets them.
    has_fmt12 = any(t.format == 12 for t in font["cmap"].tables)
    if not has_fmt12:
        from fontTools.ttLib.tables._c_m_a_p import CmapSubtable
        sub = CmapSubtable.newSubtableClass(12)()
        sub.format = 12
        sub.reserved = 0
        sub.length = 0
        sub.language = 0
        sub.nGroups = 0
        sub.platformID = 3
        sub.platEncID = 10
        sub.platformEncodingID = 10
        sub.cmap = {}
        for t in font["cmap"].tables:
            if t.isUnicode():
                sub.cmap.update(t.cmap)
        sub.cmap.update(cmap_additions)
        font["cmap"].tables.append(sub)
    else:
        for t in font["cmap"].tables:
            if t.format == 12:
                t.cmap.update(cmap_additions)

    out_font = os.path.join(REPO_ROOT, "Emmentaler.otf")
    font.save(out_font)
    print("wrote", out_font, "glyphs:", len(glyph_order), "cmap additions:", len(cmap_additions))

    # reload so getGlyphSet() sees the freshly-written composite glyphs too
    font2 = TTFont(out_font)
    glyph_set = font2.getGlyphSet()

    # --- metadata (bbox/width/anchors) in staff-space units --------------
    bboxes = {}
    anchors = {}
    for sem_name, codepoint_ in symbols.items():
        gname = cmap_additions[codepoint_]
        if gname not in glyph_set:
            continue
        g = glyph_set[gname]
        bp = BoundsPen(glyph_set)
        g.draw(bp)
        if bp.bounds is None:
            continue
        x0, y0, x1, y1 = bp.bounds
        bboxes[sem_name] = {
            "bBoxSW": [x0 / staff_space, y0 / staff_space],
            "bBoxNE": [x1 / staff_space, y1 / staff_space],
        }

    for sem_name in ("noteheadBlack", "noteheadHalf", "noteheadWhole", "noteheadDoubleWhole"):
        if sem_name not in bboxes:
            continue
        sw = bboxes[sem_name]["bBoxSW"]
        ne = bboxes[sem_name]["bBoxNE"]
        half_h = (ne[1] - sw[1]) / 2.0
        anchors[sem_name] = {
            "stemUpSE": [ne[0], half_h * 0.336],
            "stemDownNW": [sw[0], -half_h * 0.336],
        }

    metadata = {
        "glyphBBoxes": bboxes,
        "glyphsWithAnchors": anchors,
        "engravingDefaults": {},
    }
    with open(os.path.join(REPO_ROOT, "emmentaler_metadata.json"), "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=1)

    sym_out = {name: {"codepoint": "U+%05X" % cp} for name, cp in symbols.items()}
    with open(os.path.join(REPO_ROOT, "emmentaler_symbols.json"), "w", encoding="utf-8") as f:
        json.dump(sym_out, f, indent=1)
    print("wrote metadata + symbols json;", len(symbols), "semantic glyphs mapped")


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else _DEFAULT_SRC
    build(src)
