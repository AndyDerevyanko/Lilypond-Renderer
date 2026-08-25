"""Recursive-descent parser for the LilyPond subset -> model.py AST.

Covers the Learning Manual 'common notation' feature set:
notes/durations/dots, rests/skips, chords < >, ties, slurs, phrasing slurs,
manual beams, articulations/fingerings/dynamics/hairpins, \\clef \\key \\time
\\tempo \\bar \\partial, \\tuplet & \\times, grace commands, \\relative,
<< >> simultaneous music & \\\\ polyphony, \\new/\\context, \\addlyrics,
variables, \\header, \\score, \\repeat volta (rendered once with repeat
barlines), and #scheme via the bundled pyscheme interpreter.

Unknown commands parse to UnsupportedNode so imperfect input still renders.
"""

import copy
import os
import re
import sys
from fractions import Fraction

from .lexer import tokenize, Token
from . import model as M
from .model import (Pitch, Duration, PostEvent, NoteNode, ClefNode, KeyNode,
                    TimeNode, TempoNode, BarNode, PartialNode, SequentialNode,
                    SimultaneousNode, RelativeNode, TupletNode, GraceNode,
                    ContextNode, LyricsNode, AddLyricsNode, ScoreNode,
                    MarkupNode, OverrideNode, UnsupportedNode, BreakNode,
                    ChangeStaffNode, OttavaNode, StemNode, ScaleDurationsNode,
                    TagNode, KeepTagNode, PostMarkNode, HideNode)
from . import smufl

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCHEME_DIR = os.path.join(_ROOT, "Scheme-Interpreter")
_DEBUG_DROPS = bool(os.environ.get("LILYRENDER_DEBUG_DROPS"))


class ParseError(Exception):
    pass


# ---------------------------------------------------------------------------
# Scheme bridge
# ---------------------------------------------------------------------------

_scheme_interp = None

def _get_scheme():
    global _scheme_interp
    if _scheme_interp is None:
        if _SCHEME_DIR not in sys.path:
            sys.path.insert(0, _SCHEME_DIR)
        from pyscheme import Interpreter
        _scheme_interp = Interpreter()
        # a few guile/lilypond globals that show up in ordinary scores
        for name, val in {
            "red": (1.0, 0.0, 0.0), "green": (0.0, 1.0, 0.0),
            "blue": (0.0, 0.0, 1.0), "black": (0.0, 0.0, 0.0),
            "white": (1.0, 1.0, 1.0), "grey": (0.5, 0.5, 0.5),
            "UP": 1, "DOWN": -1, "LEFT": -1, "RIGHT": 1, "CENTER": 0,
        }.items():
            try:
                _scheme_interp.define(name, val)
            except Exception:
                pass
    return _scheme_interp


def eval_scheme(text):
    """Evaluate a scheme datum from a # expression; fall back to raw text."""
    text = text.strip()
    if text in ("t", "#t"):
        return True
    if text in ("f", "#f"):
        return False
    try:
        return _get_scheme().eval_string(text)
    except Exception:
        # numbers still need to come out as numbers even without a working
        # scheme interpreter (override values like Y-offset = #-1)
        try:
            return int(text.lstrip("#"))
        except ValueError:
            pass
        try:
            return float(text.lstrip("#"))
        except ValueError:
            pass
        return text


class MText(str):
    """A markup's plain-text content, plus rich segments for layout.

    Behaves as a plain str everywhere (headers, tempo text...), while
    `segments` carries per-run styling: dicts with one content key
    (text/hspace/musicglyph) plus bold/italic/dynamic/size/dy, and `align`
    the whole markup's alignment at its anchor point."""
    def __new__(cls, plain, segments=None, align="left"):
        o = super().__new__(cls, plain)
        o.segments = segments if segments is not None else []
        o.align = align
        return o


_STAFF_SIZE_RE = re.compile(r"set-global-staff-size\s+([\d.]+)")
_PAPER_SIZE_RE = re.compile(r"set-default-paper-size\s+\"(\w+)\"")


def _scan_paper_scheme(text):
    """Pull page-geometry hints (staff-size, paper size) out of a top-level
    #(...) form; these live outside the (unparsed) \\paper block so they
    need to be recognized before the generic Scheme evaluator discards
    them."""
    out = {}
    m = _STAFF_SIZE_RE.search(text)
    if m:
        out["staff_size"] = float(m.group(1))
    m = _PAPER_SIZE_RE.search(text)
    if m:
        out["paper_size"] = m.group(1).lower()
    return out


# ---------------------------------------------------------------------------

NOTE_STEPS = {c: i for i, c in enumerate("cdefgab")}

_DUTCH_ALTERS = {"": 0, "is": 1, "isis": 2, "es": -1, "eses": -2,
                 "s": -1, "ses": -2}   # as, es, ases, eses
_ENGLISH_ALTERS = {"": 0, "s": 1, "ss": 2, "x": 2, "sharp": 1,
                   "f": -1, "ff": -2, "flat": -1,
                   "-sharp": 1, "-flat": -1,
                   "-sharpsharp": 2, "-flatflat": -2}


def parse_note_name(word, language="nederlands"):
    """'cis'/'cs' -> (step, alter) or None if not a note name."""
    if not word or word[0] not in NOTE_STEPS:
        return None
    step = NOTE_STEPS[word[0]]
    rest = word[1:]
    if language == "english":
        alter = _ENGLISH_ALTERS.get(rest)
        return None if alter is None else (step, alter)
    # dutch (default)
    if rest in _DUTCH_ALTERS:
        # 's' only valid after a/e (as, es)
        if rest in ("s", "ses") and word[0] not in "ae":
            return None
        return (step, _DUTCH_ALTERS[rest])
    return None


DYNAMICS = set(smufl.DYNAMIC_GLYPHS)
ARTICULATIONS = set(smufl.ARTICULATION_GLYPHS)

GROUP_CONTEXTS = {"PianoStaff", "GrandStaff", "StaffGroup", "ChoirStaff"}

SKIP_BLOCK_COMMANDS = {"\\layout", "\\midi", "\\paper", "\\with"}


def _num(text):
    """NUMBER token text -> int when possible, else float."""
    try:
        return int(text)
    except ValueError:
        return float(text)


class Parser:
    def __init__(self, src, path=None):
        self.toks = tokenize(src)
        self.i = 0
        self.variables = {}
        self.header = {}
        self.scores = []
        self.language = "nederlands"
        self.dir = os.path.dirname(os.path.abspath(path)) if path else None
        self._included = set()
        self.paper_settings = {}

    def note_name(self, word):
        return parse_note_name(word, self.language)

    def _splice_include(self):
        """Consume  \\include "file"  and splice the file's tokens in."""
        self.next()                       # \include
        fname = self.expect("STRING").text
        path = os.path.join(self.dir, fname) if self.dir else fname
        key = os.path.normcase(os.path.abspath(path))
        if not os.path.isfile(path) or key in self._included:
            if not os.path.isfile(path):
                print(f"lilyrender: skipping missing include {fname!r}",
                      file=sys.stderr)
            return
        self._included.add(key)
        with open(path, encoding="utf-8") as f:
            toks = tokenize(f.read())
        self.toks[self.i:self.i] = toks[:-1]   # drop the EOF token

    # -- token helpers ------------------------------------------------
    def peek(self, ahead=0):
        j = min(self.i + ahead, len(self.toks) - 1)
        return self.toks[j]

    def next(self):
        t = self.toks[self.i]
        if t.kind != "EOF":
            self.i += 1
        return t

    def at(self, kind, text=None):
        t = self.peek()
        return t.kind == kind and (text is None or t.text == text)

    def expect(self, kind, text=None):
        t = self.peek()
        if not self.at(kind, text):
            raise ParseError(f"line {t.line}: expected {text or kind}, got {t.text!r}")
        return self.next()

    def error(self, msg):
        t = self.peek()
        raise ParseError(f"line {t.line}: {msg} (at {t.text!r})")

    # -- entry point ----------------------------------------------------
    def parse_file(self):
        toplevel_music = []
        while not self.at("EOF"):
            t = self.peek()
            if t.kind == "SCHEME":
                self.paper_settings.update(_scan_paper_scheme(t.text))
                self.next()
                continue
            if t.kind == "COMMAND":
                if t.text == "\\version":
                    self.next(); self.expect("STRING")
                    continue
                if t.text == "\\include":
                    self._splice_include()
                    continue
                if t.text == "\\language":
                    self.next()
                    self.language = self.expect("STRING").text
                    continue
                if t.text == "\\header":
                    self.next()
                    self.header.update(self.parse_header_block())
                    continue
                if t.text == "\\score":
                    self.next()
                    self.scores.append(self.parse_score())
                    continue
                if t.text == "\\paper":
                    self.next()
                    self.paper_settings.update(self.parse_paper_block())
                    continue
                if t.text in SKIP_BLOCK_COMMANDS:
                    self.next(); self.skip_balanced_block()
                    continue
            # variable assignment:  name = <value>
            if t.kind == "WORD" and self.peek(1).kind == "PUNCT" and self.peek(1).text == "=":
                name = self.next().text
                self.next()  # =
                self.variables[name] = self.parse_assignment_value()
                continue
            # otherwise: toplevel music
            toplevel_music.append(self.parse_music())
        toplevel_music = [m for m in toplevel_music if _is_meaningful(m)]
        if toplevel_music:
            body = toplevel_music[0] if len(toplevel_music) == 1 \
                else SequentialNode(toplevel_music)
            self.scores.append(ScoreNode(body))
        for sc in self.scores:
            merged = dict(self.header)
            merged.update(sc.header)
            sc.header = merged
            sc.paper = dict(self.paper_settings)
        return self.scores

    def parse_assignment_value(self):
        t = self.peek()
        if t.kind == "STRING":
            return self.next().text
        if t.kind == "SCHEME":
            return eval_scheme(self.next().text)
        if t.kind == "NUMBER":
            return _num(self.next().text)
        if t.kind == "COMMAND" and t.text == "\\markup":
            return self.parse_markup()
        if t.kind == "PUNCT" and t.text in ("-", "^", "_", "--"):
            # post-event variable:  ten = -\tenuto
            dummy = NoteNode([], None)
            self.parse_post_events(dummy)
            if dummy.post:
                return PostMarkNode(dummy.post[0])
            self.next()
            return UnsupportedNode(t.text)
        return self.parse_music()

    def parse_header_block(self):
        self.expect("PUNCT", "{")
        d = {}
        while not self.at("PUNCT", "}") and not self.at("EOF"):
            if self.at("WORD") and self.peek(1).text == "=":
                key = self.next().text
                self.next()
                t = self.peek()
                if t.kind == "STRING":
                    d[key] = self.next().text
                elif t.kind == "NUMBER":
                    d[key] = int(self.next().text)
                elif t.kind == "COMMAND" and t.text == "\\markup":
                    d[key] = self.parse_markup().text
                elif t.kind == "SCHEME":
                    d[key] = eval_scheme(self.next().text)
                else:
                    self.next()
            else:
                self.next()
        self.expect("PUNCT", "}")
        return d

    def parse_markup(self):
        self.expect("COMMAND", "\\markup")
        return MarkupNode(self._markup_expr())

    _MK_STYLE = {"bold": False, "italic": False, "dynamic": False,
                 "size": 1.0, "dy": 0.0}
    _MK_SIZES = {"\\huge": 1.26, "\\large": 1.12, "\\larger": 1.12,
                 "\\bigger": 1.12, "\\smaller": 0.89, "\\small": 0.89,
                 "\\tiny": 0.79, "\\teeny": 0.71}

    def _markup_expr(self):
        """One markup expression -> MText (a str carrying rich segments)."""
        segs, align = self._markup_rich(dict(self._MK_STYLE), sep=True)
        plain = "".join(s.get("text", "") for s in segs).strip()
        return MText(plain, segs, align)

    def _mk_number(self):
        """Numeric argument of a markup command (#1.5, plain number, -n)."""
        if self.at("SCHEME"):
            txt = self.next().text.lstrip("#").strip("'")
            try:
                return float(txt)
            except ValueError:
                return None
        if self.at("NUMBER"):
            return float(self.next().text)
        if self.at("PUNCT", "-"):
            self.next()
            if self.at("NUMBER"):
                return -float(self.next().text)
        return None

    def _markup_rich(self, style, sep):
        """One markup expression -> (segments, align). A segment is a dict
        holding one of text/hspace/musicglyph plus the bold/italic/dynamic/
        size/dy styling in effect where it appeared."""
        t = self.peek()
        if t.kind == "PUNCT" and t.text == "{":
            self.next()
            segs, align = [], "left"
            while not self.at("PUNCT", "}") and not self.at("EOF"):
                before = self.i
                s2, a2 = self._markup_rich(dict(style), sep)
                if s2:
                    if segs and sep and "text" in s2[0]:
                        segs.append({**style, "text": " "})
                    segs.extend(s2)
                    if a2 != "left":
                        align = a2
                if self.i == before:
                    self.next()      # unhandled punctuation: skip it
            if self.at("PUNCT", "}"):
                self.next()
            return segs, align
        if t.kind in ("WORD", "STRING", "NUMBER"):
            self.next()
            return [{**style, "text": t.text}], "left"
        if t.kind == "SCHEME":
            self.next()
            return [], "left"
        if t.kind == "COMMAND":
            cmd = t.text
            self.next()
            if cmd in ("\\hspace", "\\vspace"):
                n = self._mk_number() or 0.0
                return ([{"hspace": n}] if cmd == "\\hspace" else []), "left"
            if cmd in ("\\raise", "\\lower"):
                n = self._mk_number() or 0.0
                s = dict(style)
                s["dy"] += n if cmd == "\\raise" else -n
                return self._markup_rich(s, sep)
            if cmd in ("\\fontsize", "\\magnify", "\\abs-fontsize"):
                n = self._mk_number()
                s = dict(style)
                if n is not None:
                    if cmd == "\\fontsize":
                        s["size"] *= 2.0 ** (n / 6.0)
                    elif cmd == "\\magnify":
                        s["size"] *= n
                    else:
                        s["size"] = n / 11.0
                return self._markup_rich(s, sep)
            if cmd in ("\\pad-markup", "\\translate", "\\halign"):
                self._mk_number()
                return self._markup_rich(style, sep)
            if cmd in self._MK_SIZES:
                s = dict(style)
                s["size"] *= self._MK_SIZES[cmd]
                return self._markup_rich(s, sep)
            if cmd == "\\normalsize":
                s = dict(style)
                s["size"] = 1.0
                return self._markup_rich(s, sep)
            if cmd == "\\bold":
                return self._markup_rich({**style, "bold": True}, sep)
            if cmd in ("\\italic", "\\oblique"):
                return self._markup_rich({**style, "italic": True}, sep)
            if cmd in ("\\upright", "\\normal-text"):
                return self._markup_rich({**style, "italic": False}, sep)
            if cmd == "\\dynamic":
                return self._markup_rich({**style, "dynamic": True}, sep)
            if cmd == "\\concat":
                return self._markup_rich(style, sep=False)
            if cmd in ("\\center-align", "\\center-column"):
                segs, _ = self._markup_rich(style, sep)
                return segs, "center"
            if cmd in ("\\right-align", "\\right-column"):
                segs, _ = self._markup_rich(style, sep)
                return segs, "right"
            if cmd == "\\left-align":
                segs, _ = self._markup_rich(style, sep)
                return segs, "left"
            if cmd == "\\musicglyph":
                name = None
                if self.at("STRING") or self.at("WORD"):
                    name = self.next().text.strip('"')
                elif self.at("SCHEME"):
                    name = self.next().text.lstrip("#").strip('"')
                if name:
                    return [{**style, "musicglyph": name}], "left"
                return [], "left"
            if cmd == "\\char":
                if self.at("STRING") or self.at("NUMBER") or self.at("SCHEME"):
                    self.next()
                return [], "left"
            if cmd == "\\score":
                # \markup \score { music \layout {} } embeds engraved music
                # (e.g. a little chord illustration) inside text; rendering
                # that is out of scope, but it must still be *consumed* as a
                # block, not fed token-by-token into the generic command
                # branch below (which would stringify e.g. \with { \remove
                # "Clef_engraver" ... } context tweaks as literal text)
                self.skip_balanced_block()
                return [], "left"
            # ordinary one-markup-argument command (\whiteout, \column,
            # \line, \sans, \with-color, \with-url, \override...): consume
            # any scheme/url arguments, then recurse into its markup body
            while self.peek().kind == "SCHEME":
                self.next()
            nt = self.peek()
            if nt.kind in ("WORD", "STRING", "NUMBER", "COMMAND", "SCHEME") \
                    or (nt.kind == "PUNCT" and nt.text == "{"):
                return self._markup_rich(style, sep)
            return [], "left"
        # anything else ends the markup expression
        return [], "left"

    def parse_score(self):
        self.expect("PUNCT", "{")
        body = None
        header = {}
        while not self.at("PUNCT", "}") and not self.at("EOF"):
            t = self.peek()
            if t.kind == "COMMAND" and t.text == "\\header":
                self.next()
                header.update(self.parse_header_block())
            elif t.kind == "COMMAND" and t.text == "\\paper":
                self.next()
                self.paper_settings.update(self.parse_paper_block())
            elif t.kind == "COMMAND" and t.text in SKIP_BLOCK_COMMANDS:
                self.next(); self.skip_balanced_block()
            else:
                m = self.parse_music()
                body = m if body is None else SequentialNode(
                    body.elements + [m] if isinstance(body, SequentialNode) else [body, m])
        self.expect("PUNCT", "}")
        return ScoreNode(body if body is not None else SequentialNode([]), header)

    # properties inside \paper we actually act on (LilyPond identifier -> our key)
    _PAPER_NUMERIC_PROPS = {
        "min-systems-per-page": "min_systems_per_page",
        "max-systems-per-page": "max_systems_per_page",
        "system-count": "system_count",
    }

    def parse_paper_block(self):
        """\\paper { ... } is otherwise unparsed (see skip_balanced_block);
        pull out the handful of numeric page-breaking hints we act on
        (e.g. min-systems-per-page, used by heavily hand-tuned scores to
        force a fixed system count per page) while skipping the rest."""
        out = {}
        self.expect("PUNCT", "{")
        depth = 1
        while depth > 0 and not self.at("EOF"):
            t = self.next()
            if t.kind == "PUNCT" and t.text == "{":
                depth += 1
            elif t.kind == "PUNCT" and t.text == "}":
                depth -= 1
            elif t.kind == "WORD" and t.text in self._PAPER_NUMERIC_PROPS \
                    and self.at("PUNCT", "=") and self.peek(1).kind == "NUMBER":
                self.next()   # =
                out[self._PAPER_NUMERIC_PROPS[t.text]] = _num(self.next().text)
        return out

    def skip_balanced_block(self):
        """Skip an optional identifier then a { ... } block."""
        while not self.at("PUNCT", "{") and not self.at("EOF"):
            self.next()
        depth = 0
        while not self.at("EOF"):
            t = self.next()
            if t.kind == "PUNCT" and t.text == "{":
                depth += 1
            elif t.kind == "PUNCT" and t.text == "}":
                depth -= 1
                if depth == 0:
                    return

    # -- music expressions ---------------------------------------------
    def parse_music(self):
        t = self.peek()
        if t.kind == "PUNCT" and t.text == "{":
            return self.parse_sequential()
        if t.kind == "PUNCT" and t.text == "<<":
            return self.parse_simultaneous()
        if t.kind == "COMMAND":
            return self.parse_command_music()
        if t.kind == "WORD" or (t.kind == "PUNCT" and t.text == "<"):
            return self.parse_note_or_chord()
        if t.kind == "PUNCT" and t.text == "|":
            self.next()
            return UnsupportedNode("|")
        if t.kind == "PUNCT" and t.text in _STRAY_MARKS:
            self.next()
            return UnsupportedNode(t.text)
        if t.kind == "SCHEME":
            return M.SchemeNode(eval_scheme(self.next().text))
        # stray leftovers of unsupported constructs: consume and ignore
        if t.kind in ("NUMBER", "STRING", "PUNCT"):
            self.next()
            return UnsupportedNode(t.text)
        self.error("expected music")

    def parse_sequential(self):
        self.expect("PUNCT", "{")
        elems = []
        while not self.at("PUNCT", "}") and not self.at("EOF"):
            elems.append(self.parse_music())
        self.expect("PUNCT", "}")
        elems = _attach_stray_marks(elems)
        return SequentialNode([e for e in elems if not _is_noise(e)])

    def parse_simultaneous(self):
        self.expect("PUNCT", "<<")
        groups = [[]]
        while not self.at("PUNCT", ">>") and not self.at("EOF"):
            if self.at("PUNCT", "\\\\"):
                self.next()
                groups.append([])
                continue
            groups[-1].append(self.parse_music())
        self.expect("PUNCT", ">>")
        voice_sep = len(groups) > 1
        elems = []
        for g in groups:
            g = [e for e in g if not _is_noise(e)]
            if voice_sep:
                elems.append(g[0] if len(g) == 1 else SequentialNode(g))
            else:
                elems.extend(g)
        return SimultaneousNode(elems, voice_separated=voice_sep)

    def parse_command_music(self):
        t = self.next()
        cmd = t.text

        if cmd == "\\relative":
            ref = None
            if self.at("WORD") and self.note_name(self.peek().text) is not None \
                    and not self._word_is_music_keyword():
                ref = self.parse_pitch()
            return RelativeNode(ref, self.parse_music())

        if cmd in ("\\new", "\\context"):
            ctype = self.expect("WORD").text
            name = None
            if self.at("PUNCT", "="):
                self.next()
                nt = self.next()
                name = nt.text
            if self.at("COMMAND", "\\with"):
                self.next(); self.skip_balanced_block()
            body = self.parse_music()
            return ContextNode(ctype, name, body, is_new=(cmd == "\\new"))

        if cmd in ("\\tuplet", "\\times"):
            num = int(self.expect("NUMBER").text)
            self.expect("PUNCT", "/")
            den = int(self.expect("NUMBER").text)
            if cmd == "\\times":
                num, den = den, num   # \times 2/3 == \tuplet 3/2
            # optional span duration (ignored for layout grouping)
            if self.at("NUMBER"):
                self.next()
                while self.at("PUNCT", "."):
                    self.next()
            return TupletNode((num, den), self.parse_music())

        if cmd in ("\\grace", "\\acciaccatura", "\\appoggiatura", "\\slashedGrace"):
            return GraceNode(self.parse_music(), kind=cmd[1:])

        if cmd == "\\clef":
            if self.at("STRING"):
                return ClefNode(self.next().text)
            return ClefNode(self.expect("WORD").text)

        if cmd == "\\key":
            tonic = self.parse_pitch()
            mode = "major"
            if self.at("COMMAND"):
                mode = self.next().text[1:]
            return KeyNode(tonic, mode)

        if cmd == "\\time":
            num = int(self.expect("NUMBER").text)
            self.expect("PUNCT", "/")
            den = int(self.expect("NUMBER").text)
            return TimeNode(num, den)

        if cmd == "\\tempo":
            node = TempoNode()
            if self.at("STRING"):
                node.text = self.next().text
            if self.at("NUMBER"):
                node.unit = self.parse_duration()
                self.expect("PUNCT", "=")
                if self.at("NUMBER"):
                    node.bpm = int(self.next().text)
                elif self.at("SCHEME"):
                    v = eval_scheme(self.next().text)
                    node.bpm = int(v) if isinstance(v, (int, float)) else None
            return node

        if cmd == "\\bar":
            return BarNode(self.expect("STRING").text)

        if cmd == "\\partial":
            return PartialNode(self.parse_duration())

        if cmd == "\\repeat":
            kind = self.expect("WORD").text
            count = 1
            if self.at("NUMBER"):
                count = int(self.next().text)
            body = self.parse_music()
            if self.at("COMMAND", "\\alternative"):
                self.next()
                self.parse_music()   # parsed, not yet rendered
            if kind == "volta":
                return SequentialNode([BarNode(".|:"), body, BarNode(":|.")])
            if kind == "unfold" and count > 1:
                # unfolding happens in the interpreter: lilypond resolves
                # \relative over the body once and copies the result
                return M.RepeatNode(count, body)
            return body

        if cmd == "\\addlyrics":
            return AddLyricsNode(self.parse_lyrics_block())

        if cmd in ("\\override", "\\revert", "\\set", "\\unset", "\\once"):
            return self.parse_property_command(cmd)

        if cmd in ("\\break", "\\noBreak", "\\pageBreak"):
            kind = {"\\break": "line", "\\noBreak": "noBreak",
                    "\\pageBreak": "page"}[cmd]
            return BreakNode(kind)

        if cmd == "\\markup":
            self.i -= 1
            return self.parse_markup()

        if cmd == "\\fixed":
            ref = self.parse_pitch()
            body = self.parse_music()
            return RelativeNode(None, _FixedWrapper(ref, body))  # handled in interpret

        if cmd in ("\\autoBeamOff", "\\autoBeamOn"):
            return UnsupportedNode(cmd)

        if cmd in ("\\stemUp", "\\stemDown", "\\stemNeutral", "\\voiceOne",
                   "\\voiceTwo", "\\voiceThree", "\\voiceFour", "\\oneVoice"):
            d = {"\\stemUp": 1, "\\stemDown": -1, "\\voiceOne": 1,
                 "\\voiceTwo": -1, "\\voiceThree": 1, "\\voiceFour": -1}
            return StemNode(d.get(cmd, 0))

        if cmd in ("\\hideNotes", "\\unHideNotes"):
            return HideNode(cmd == "\\hideNotes")

        if cmd == "\\change":
            # \change Staff = "name"
            if self.at("WORD"):
                self.next()
            if self.at("PUNCT", "="):
                self.next()
            return ChangeStaffNode(self.next().text)

        if cmd == "\\ottava":
            return OttavaNode(int(self._parse_signed_number()))

        if cmd == "\\scaleDurations":
            return ScaleDurationsNode(self._parse_fraction_or_scheme(),
                                      self.parse_music())

        if cmd == "\\magnifyMusic":
            if self.at("NUMBER") or self.at("SCHEME"):
                self.next()
            return self.parse_music()

        if cmd == "\\tag":
            return TagNode(self._parse_tags(), self.parse_music())

        if cmd in ("\\keepWithTag", "\\removeWithTag"):
            tags = self._parse_tags()
            return KeepTagNode(tags, self.parse_music(),
                               keep=(cmd == "\\keepWithTag"))

        if cmd == "\\barNumberCheck":
            if self.at("NUMBER") or self.at("SCHEME"):
                self.next()
            return UnsupportedNode(cmd)

        if cmd == "\\tweak":
            self._consume_tweak_args()
            t2 = self.peek()
            if t2.kind == "EOF" \
                    or (t2.kind == "PUNCT" and t2.text in ("}", ">>")) \
                    or (t2.kind == "COMMAND" and t2.text == "\\etc"):
                return UnsupportedNode(cmd)
            return self.parse_music()

        if cmd == "\\shape":
            # \shape #'((dx.dy)(dx.dy)(dx.dy)(dx.dy)) ItemName : hand-tuned
            # bezier control-point offsets for the next Slur/PhrasingSlur/Tie.
            # The bundled scheme interpreter (Scheme-Interpreter/) is an
            # empty, unresolved git submodule in this checkout, so parse the
            # handful of dotted-pair numbers directly instead of round-
            # tripping through eval_scheme (which would just silently fail
            # and fall back to the raw '(...)' string).
            pairs = []
            if self.at("SCHEME"):
                text = self.next().text
                pairs = [(float(a), float(b)) for a, b in
                        re.findall(r"\(\s*(-?[\d.]+)\s*\.\s*(-?[\d.]+)\s*\)", text)][:4]
            grob = self.next().text if self.at("WORD") else "Slur"
            if len(pairs) == 4:
                return OverrideNode("shape:" + grob, pairs)
            return UnsupportedNode(cmd)

        if cmd in ("\\offset", "\\alterBroken"):
            # \offset prop value Item / \alterBroken prop #'(..) Item
            while self.at("WORD"):
                self.next()
                if self.at("PUNCT", "."):
                    self.next()
                else:
                    break
            self._parse_value()
            if self.at("WORD") and self.peek().text[:1].isupper():
                self.next()
            return UnsupportedNode(cmd)

        if cmd == "\\afterGrace":
            if self.at("NUMBER"):           # optional fraction argument
                self.next()
                if self.at("PUNCT", "/"):
                    self.next()
                    self.expect("NUMBER")
            main = self.parse_music()
            grace = self.parse_music()
            return SequentialNode([main, GraceNode(grace, kind="grace")])

        if cmd == "\\after":
            # \after duration event main-music
            if self.at("NUMBER"):
                self.parse_duration()
            ev = self.parse_music()
            main = self.parse_music()
            return SequentialNode([main, ev])

        if cmd in ("\\sustainOn", "\\sostenutoOn"):
            return PostMarkNode(PostEvent("pedal", "sustain_on"))
        if cmd in ("\\sustainOff", "\\sostenutoOff"):
            return PostMarkNode(PostEvent("pedal", "sustain_off"))
        if cmd == "\\arpeggio":
            return PostMarkNode(PostEvent("arpeggio"))

        if cmd == "\\parenthesize":
            return self.parse_music()

        if cmd == "\\language":
            self.language = self.expect("STRING").text
            return UnsupportedNode(cmd)

        if cmd == "\\include":
            self.i -= 1
            self._splice_include()
            return UnsupportedNode(cmd)

        # variable reference
        vname = cmd[1:]
        if vname in self.variables:
            val = self.variables[vname]
            if not hasattr(val, "__dict__") and not isinstance(val, list):
                return UnsupportedNode(cmd)   # scheme string/number value
            return copy.deepcopy(val)

        # unknown command: skip an attached block if present, else just the token
        if self.at("PUNCT", "{"):
            self.skip_balanced_block()
        return UnsupportedNode(cmd)

    def _word_is_music_keyword(self):
        return False

    # -- small argument helpers -------------------------------------------
    def _parse_signed_number(self):
        sign = 1
        if self.at("PUNCT", "-"):
            self.next()
            sign = -1
        t = self.peek()
        if t.kind == "NUMBER":
            return sign * _num(self.next().text)
        if t.kind == "SCHEME":
            v = eval_scheme(self.next().text)
            return sign * v if isinstance(v, (int, float)) else 0
        return 0

    def _parse_fraction_or_scheme(self):
        if self.at("NUMBER"):
            a = int(self.next().text)
            if self.at("PUNCT", "/"):
                self.next()
                return Fraction(a, int(self.expect("NUMBER").text))
            return Fraction(a)
        if self.at("SCHEME"):
            v = eval_scheme(self.next().text)
            if isinstance(v, (int, float)):
                return Fraction(v).limit_denominator(64)
        return Fraction(1)

    def _parse_tags(self):
        """Tag argument: bare word, or scheme symbol/list (#'a, #'(a b))."""
        t = self.peek()
        if t.kind == "SCHEME":
            import re
            return frozenset(re.findall(r"[A-Za-z][\w-]*", self.next().text))
        if t.kind == "WORD":
            return frozenset([self.next().text])
        return frozenset()

    def _consume_tweak_args(self):
        """After \\tweak: [Grob.]property value."""
        while self.at("WORD"):
            self.next()
            if self.at("PUNCT", "."):
                self.next()
            else:
                break
        self._parse_value()

    def _parse_value(self):
        """A property value: scheme, (signed/fractional) number, string,
        markup or bare word."""
        t = self.peek()
        if t.kind == "SCHEME":
            return eval_scheme(self.next().text)
        if t.kind == "PUNCT" and t.text == "-":
            self.next()
            if self.at("NUMBER"):
                return -_num(self.next().text)
            return None
        if t.kind == "NUMBER":
            v = _num(self.next().text)
            if isinstance(v, int) and self.at("PUNCT", "/"):
                self.next()
                return Fraction(v, int(self.expect("NUMBER").text))
            return v
        if t.kind == "STRING":
            return self.next().text
        if t.kind == "COMMAND" and t.text == "\\markup":
            return self.parse_markup().text
        if t.kind == "WORD":
            return self.next().text
        return None

    def parse_property_command(self, cmd):
        # \override Path.To.Prop = value   /   \revert Path.To.Prop
        path = []
        while self.at("WORD"):
            path.append(self.next().text)
            if self.at("PUNCT", "."):
                self.next()
            else:
                break
        value = None
        if self.at("PUNCT", "="):
            self.next()
            value = self._parse_value()
        if cmd in ("\\override", "\\set"):
            return OverrideNode(".".join(path), value)
        return UnsupportedNode(f"{cmd} {'.'.join(path)}")

    def parse_lyrics_block(self):
        self.expect("PUNCT", "{")
        syls = []
        pending = None    # syllable text being built with -- continuation
        while not self.at("PUNCT", "}") and not self.at("EOF"):
            t = self.next()
            if t.kind in ("WORD", "STRING", "NUMBER"):
                syls.append([t.text, ""])
            elif t.kind == "PUNCT" and t.text == "--":
                if syls:
                    syls[-1][1] = "-"
            elif t.kind == "PUNCT" and t.text == "__":
                if syls:
                    syls[-1][1] = "_"
            elif t.kind == "PUNCT" and t.text == "_":
                syls.append(["", ""])
            # everything else in lyrics mode is ignored
        self.expect("PUNCT", "}")
        return LyricsNode([tuple(s) for s in syls])

    # -- pitches, durations, notes ---------------------------------------
    def parse_pitch(self):
        t = self.expect("WORD")
        sa = self.note_name(t.text)
        if sa is None:
            raise ParseError(f"line {t.line}: not a note name: {t.text!r}")
        step, alter = sa
        octave = -1   # lilypond bare 'c' is the octave below middle C
        while self.at("PUNCT") and self.peek().text in ("'", ",") and self.peek().glued:
            octave += 1 if self.next().text == "'" else -1
        # forced (!) / cautionary (?) accidental marks
        while self.at("PUNCT") and self.peek().text in ("!", "?") and self.peek().glued:
            self.next()
        return Pitch(step, alter, octave)

    def parse_duration(self):
        t = self.expect("NUMBER")
        num = int(t.text)
        log = {1: 0, 2: 1, 4: 2, 8: 3, 16: 4, 32: 5, 64: 6, 128: 7,
               256: 8, 512: 9, 1024: 10}.get(num)
        if log is None:
            raise ParseError(f"line {t.line}: bad duration {num}")
        dots = 0
        while self.at("PUNCT", ".") and self.peek().glued:
            self.next()
            dots += 1
        dur = Duration(log, dots)
        # multiplier  *N or *N/M (lilypond allows whitespace: "s1 * 7")
        if self.at("PUNCT", "*"):
            self.next()
            a = int(self.expect("NUMBER").text)
            if self.at("PUNCT", "/"):
                self.next()
                b = int(self.expect("NUMBER").text)
                dur = dur.with_factor(Fraction(a, b))
            else:
                dur = dur.with_factor(Fraction(a))
        return dur

    def try_parse_duration(self):
        if self.at("NUMBER") and self.peek().glued:
            return self.parse_duration()
        return None

    def parse_note_or_chord(self):
        t = self.peek()
        if t.kind == "PUNCT" and t.text == "<":
            self.next()
            pitches = []
            while not self.at("PUNCT", ">") and not self.at("EOF"):
                pt = self.peek()
                if pt.kind == "COMMAND":
                    self.next()
                    if pt.text == "\\tweak":
                        self._consume_tweak_args()
                    continue          # \parenthesize etc: keep the note only
                if pt.kind == "WORD" and self.note_name(pt.text) is not None:
                    pitches.append(self.parse_pitch())
                    continue
                if pt.kind == "WORD" and _DEBUG_DROPS:
                    import sys
                    print(f"lilyrender: chord drops WORD {pt.text!r} line {pt.line}",
                          file=sys.stderr)
                self.next()           # per-note ties/accidental hints: skip
            self.expect("PUNCT", ">")
            dur = self.try_parse_duration()
            node = NoteNode(pitches, dur)
            self.parse_post_events(node)
            return node

        word = t.text
        if word == "r":
            self.next()
            node = NoteNode([], self.try_parse_duration(), is_rest=True)
            self.parse_post_events(node)
            return node
        if word == "s":
            self.next()
            node = NoteNode([], self.try_parse_duration(), is_rest=True, is_skip=True)
            self.parse_post_events(node)
            return node
        if word == "R":
            self.next()
            node = NoteNode([], self.try_parse_duration(), is_rest=True,
                            is_full_measure_rest=True)
            if node.duration and node.duration.factor != 1:
                node.multiplier = int(node.duration.factor)
                node.duration = Duration(node.duration.log, node.duration.dots)
            return node
        if word == "q":
            self.next()
            node = NoteNode([], self.try_parse_duration(),
                            is_chord_repeat=True)
            self.parse_post_events(node)
            return node

        if self.note_name(word) is not None:
            pitch = self.parse_pitch()
            # octave check  c'=''  : consume and ignore
            if self.at("PUNCT", "=") and self.peek().glued:
                self.next()
                while self.at("PUNCT") and self.peek().text in ("'", ","):
                    self.next()
            dur = self.try_parse_duration()
            node = NoteNode([pitch], dur)
            self.parse_post_events(node)
            return node

        # not a note: variable-ish word used as music? skip it.
        if _DEBUG_DROPS:
            import sys
            print(f"lilyrender: music drops WORD {word!r} line {t.line}",
                  file=sys.stderr)
        self.next()
        return UnsupportedNode(word)

    def parse_post_events(self, node):
        while True:
            t = self.peek()
            if t.kind == "PUNCT":
                if t.text == "~":
                    self.next(); node.post.append(PostEvent("tie")); continue
                if t.text == "(":
                    self.next(); node.post.append(PostEvent("slur_open")); continue
                if t.text == ")":
                    self.next(); node.post.append(PostEvent("slur_close")); continue
                if t.text == "\\(":
                    self.next(); node.post.append(PostEvent("phrasing_open")); continue
                if t.text == "\\)":
                    self.next(); node.post.append(PostEvent("phrasing_close")); continue
                if t.text == "[":
                    self.next(); node.post.append(PostEvent("beam_open")); continue
                if t.text == "]":
                    self.next(); node.post.append(PostEvent("beam_close")); continue
                if t.text == "\\<":
                    self.next(); node.post.append(PostEvent("cresc")); continue
                if t.text == "\\>":
                    self.next(); node.post.append(PostEvent("decresc")); continue
                if t.text == "\\!":
                    self.next(); node.post.append(PostEvent("end_hairpin")); continue
                if t.text == "\\=":      # spanner id  c\=1( : id is ignored
                    self.next()
                    if self.peek().glued and self.peek().kind in ("NUMBER", "WORD", "STRING"):
                        self.next()
                    continue
                if t.text == "--":   # lexed as one token: tenuto shorthand
                    self.next(); node.post.append(PostEvent("articulation", "tenuto"))
                    continue
                if t.text in ("-", "^", "_"):
                    if self._parse_directed_post(node):
                        continue
                    return
                return
            if t.kind == "COMMAND":
                name = t.text[1:]
                if name in DYNAMICS:
                    self.next()
                    node.post.append(PostEvent("dynamic", name)); continue
                if name in ARTICULATIONS:
                    self.next()
                    node.post.append(PostEvent("articulation", name)); continue
                if name in ("cresc", "decresc", "dim", "decr"):
                    self.next()
                    node.post.append(PostEvent("cresc" if name == "cresc" else "decresc"))
                    continue
                if name in ("sustainOn", "sostenutoOn"):
                    self.next()
                    node.post.append(PostEvent("pedal", "sustain_on")); continue
                if name in ("sustainOff", "sostenutoOff"):
                    self.next()
                    node.post.append(PostEvent("pedal", "sustain_off")); continue
                if name == "arpeggio":
                    self.next()
                    node.post.append(PostEvent("arpeggio")); continue
                if name == "rest":       # c4\rest : positioned rest
                    self.next()
                    node.is_rest = True
                    continue
                if name == "tweak":
                    self.next()
                    self._consume_tweak_args()
                    continue
                if name in ("noBeam", "glissando", "laissezVibrer",
                            "repeatTie", "startTextSpan", "stopTextSpan",
                            "startTrillSpan", "stopTrillSpan", "espressivo",
                            "downbow", "upbow", "harmonic"):
                    self.next()
                    continue
                var = self.variables.get(name)
                if isinstance(var, PostMarkNode):
                    self.next()
                    node.post.append(copy.deepcopy(var.event))
                    continue
                if isinstance(var, MarkupNode):
                    self.next()
                    node.post.append(PostEvent("text", var.text))
                    continue
                return
            return

    def _parse_directed_post(self, node):
        """Handle -X ^X _X where X is shorthand artic, digit, command or text."""
        d = self.next().text
        direction = {"-": 0, "^": 1, "_": -1}[d]
        t = self.peek()
        if t.kind == "PUNCT" and t.text == "~":
            self.next()
            node.post.append(PostEvent("tie", direction=direction))
            return True
        if t.kind == "PUNCT" and t.text in smufl.ARTICULATION_SHORTHAND:
            self.next()
            node.post.append(PostEvent(
                "articulation", smufl.ARTICULATION_SHORTHAND[t.text], direction))
            return True
        if t.kind == "PUNCT" and t.text in ("-", "^", "_") and d == "-":
            # '--' split by lexer? ('--' is PUNCT_2) fallthrough safety
            self.next()
            node.post.append(PostEvent("articulation", "tenuto", direction))
            return True
        if t.kind == "NUMBER":
            self.next()
            node.post.append(PostEvent("fingering", int(t.text), direction))
            return True
        if t.kind == "STRING":
            self.next()
            node.post.append(PostEvent("text", t.text, direction))
            return True
        if t.kind == "COMMAND":
            name = t.text[1:]
            self.next()
            while name == "tweak":       # -\tweak prop val \target
                self._consume_tweak_args()
                if self.peek().kind != "COMMAND":
                    return True
                name = self.next().text[1:]
            if name in ARTICULATIONS:
                node.post.append(PostEvent("articulation", name, direction))
            elif name in DYNAMICS:
                node.post.append(PostEvent("dynamic", name, direction))
            elif name == "markup":
                self.i -= 1
                mk = self.parse_markup()
                node.post.append(PostEvent("text", mk.text, direction))
            else:
                var = self.variables.get(name)
                if isinstance(var, MarkupNode):
                    node.post.append(PostEvent("text", var.text, direction))
                elif isinstance(var, PostMarkNode):
                    ev = copy.deepcopy(var.event)
                    ev.direction = direction
                    node.post.append(ev)
            return True
        # '--' tenuto handled by lexer as PUNCT_2:
        if t.kind == "PUNCT" and t.text == "--":
            self.next()
            node.post.append(PostEvent("articulation", "tenuto", direction))
            return True
        self.i -= 1   # not a post event: give the direction char back
        return False


class _FixedWrapper:
    """Marker for \\fixed: octave marks are relative to `ref` but per-note."""
    def __init__(self, ref, body):
        self.ref = ref
        self.body = body


def _is_noise(node):
    return isinstance(node, UnsupportedNode) and node.text == "|"


def _is_meaningful(node):
    """True if `node` contains real notes/contexts.  Used to decide whether
    stray top-level music (leftovers of unsupported constructs) should form
    an implicit score."""
    if isinstance(node, NoteNode):
        return not node.is_skip
    if isinstance(node, (ContextNode, ScoreNode)):
        return True
    if isinstance(node, (SequentialNode, SimultaneousNode)):
        return any(_is_meaningful(e) for e in node.elements)
    if isinstance(node, (UnsupportedNode, MarkupNode, OverrideNode,
                         PostMarkNode, M.SchemeNode)):
        return False
    body = getattr(node, "body", None)
    if body is not None:
        return _is_meaningful(body)
    return False


# Post-event marks that may appear detached from a note ("\( g4" instead of
# "g4\("): openers attach to the next note, closers to the previous one.
_STRAY_MARKS = {
    "\\(": ("phrasing_open", "next"), "\\)": ("phrasing_close", "prev"),
    "(": ("slur_open", "next"), ")": ("slur_close", "prev"),
    "[": ("beam_open", "next"), "]": ("beam_close", "prev"),
    "~": ("tie", "prev"),
}


def _attach_stray_marks(elems):
    out = []
    pending_next = []
    for el in elems:
        if isinstance(el, UnsupportedNode) and el.text in _STRAY_MARKS:
            kind, where = _STRAY_MARKS[el.text]
            if where == "next":
                pending_next.append(kind)
            else:
                target = next((e for e in reversed(out)
                               if isinstance(e, NoteNode)), None)
                if target is not None:
                    target.post.append(PostEvent(kind))
            continue
        if pending_next and isinstance(el, NoteNode):
            for kind in pending_next:
                el.post.append(PostEvent(kind))
            pending_next = []
        out.append(el)
    return out


def parse(src, path=None):
    """Parse a .ly source string -> list of ScoreNode.

    `path` (the source file's location) enables \\include resolution."""
    return Parser(src, path).parse_file()
