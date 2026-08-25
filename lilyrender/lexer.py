"""Tokenizer for the LilyPond subset.

Tokens carry a `glued` flag (True when there was no whitespace before the
token) because LilyPond syntax is whitespace-sensitive in places:
`c'4.` is one note while `c ' 4 .` is not valid input.

Scheme expressions introduced by `#` are captured as a single SCHEME token
containing the raw datum text (balanced-delimiter scan); evaluation happens
in the parser via pyscheme.
"""

from dataclasses import dataclass


class LexError(Exception):
    pass


# kinds: WORD NUMBER STRING COMMAND SCHEME PUNCT EOF
@dataclass
class Token:
    kind: str
    text: str
    pos: int
    line: int
    glued: bool

    def __repr__(self):
        return f"{self.kind}({self.text!r})"


PUNCT_2 = ("<<", ">>", "\\\\", "\\(", "\\)", "\\<", "\\>", "\\!", "--", "__")
PUNCT_1 = "{}<>|~()[]-_^=.,'*/:!?+"


def tokenize(src: str):
    toks = []
    i = 0
    n = len(src)
    line = 1
    glued = False

    def add(kind, text, pos):
        toks.append(Token(kind, text, pos, line, glued))

    while i < n:
        c = src[i]
        # -- whitespace ------------------------------------------------
        if c in " \t\r\n":
            if c == "\n":
                line += 1
            i += 1
            glued = False
            continue
        # -- comments --------------------------------------------------
        if c == "%":
            if i + 1 < n and src[i + 1] == "{":
                depth = 1
                j = i + 2
                while j < n and depth:
                    if src.startswith("%{", j):
                        depth += 1; j += 2
                    elif src.startswith("%}", j):
                        depth -= 1; j += 2
                    else:
                        if src[j] == "\n":
                            line += 1
                        j += 1
                i = j
            else:
                while i < n and src[i] != "\n":
                    i += 1
            glued = False
            continue
        # -- strings ---------------------------------------------------
        if c == '"':
            j = i + 1
            out = []
            while j < n and src[j] != '"':
                if src[j] == "\\" and j + 1 < n:
                    out.append(src[j + 1]); j += 2
                else:
                    if src[j] == "\n":
                        line += 1
                    out.append(src[j]); j += 1
            if j >= n:
                raise LexError(f"line {line}: unterminated string")
            add("STRING", "".join(out), i)
            i = j + 1
            glued = True
            continue
        # -- scheme ----------------------------------------------------
        if c == "#":
            j = _scan_scheme_datum(src, i + 1, line)
            add("SCHEME", src[i + 1:j], i)
            i = j
            glued = True
            continue
        # -- commands --------------------------------------------------
        if c == "\\":
            two = src[i:i + 2]
            if two in ("\\\\", "\\(", "\\)", "\\<", "\\>", "\\!", "\\="):
                add("PUNCT", two, i)
                i += 2
                glued = True
                continue
            j = i + 1
            while j < n and (src[j].isalpha() or src[j] in "-"):
                j += 1
            if j == i + 1:
                raise LexError(f"line {line}: stray backslash")
            add("COMMAND", src[i:j], i)
            i = j
            glued = True
            continue
        # -- numbers ---------------------------------------------------
        if c.isdigit():
            j = i
            while j < n and src[j].isdigit():
                j += 1
            # decimal only when a digit follows the dot ('4.' is a dotted
            # duration, '0.5' is a property value)
            if j + 1 < n and src[j] == "." and src[j + 1].isdigit():
                j += 1
                while j < n and src[j].isdigit():
                    j += 1
            add("NUMBER", src[i:j], i)
            i = j
            glued = True
            continue
        # -- words (note names, identifiers) ---------------------------
        if c.isalpha():
            j = i
            while j < n and (src[j].isalpha() or
                             (src[j] == "_" and j + 1 < n and src[j + 1].isalnum()) or
                             (src[j].isdigit() and j > i and src[j - 1] == "_") or
                             (src[j] == "-" and j + 1 < n and src[j + 1].isalpha())):
                j += 1
            # identifiers like treble_8 include digits after underscore;
            # property names like X-offset include internal hyphens
            add("WORD", src[i:j], i)
            i = j
            glued = True
            continue
        # -- multi-char punct (non-backslash) ---------------------------
        two = src[i:i + 2]
        if two in ("<<", ">>", "--", "__"):
            add("PUNCT", two, i)
            i += 2
            glued = True
            continue
        if c in PUNCT_1:
            add("PUNCT", c, i)
            i += 1
            glued = True
            continue
        raise LexError(f"line {line}: unexpected character {c!r}")

    toks.append(Token("EOF", "", n, line, False))
    return toks


def _scan_scheme_datum(src, i, line):
    """Return end index of one scheme datum starting at src[i]."""
    n = len(src)
    # prefixes: ' ` , ,@ # (for #t #f #x.. vectors #( )
    while i < n and src[i] in "'`,@#":
        i += 1
    if i >= n:
        raise LexError(f"line {line}: truncated scheme expression")
    c = src[i]
    if c == "(":
        depth = 0
        while i < n:
            ch = src[i]
            if ch == '"':
                i += 1
                while i < n and src[i] != '"':
                    i += 2 if src[i] == "\\" else 1
            elif ch == ";":
                while i < n and src[i] != "\n":
                    i += 1
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    return i + 1
            i += 1
        raise LexError(f"line {line}: unbalanced scheme parens")
    if c == '"':
        i += 1
        while i < n and src[i] != '"':
            i += 2 if src[i] == "\\" else 1
        return i + 1
    # atom: read to whitespace or a lilypond delimiter
    j = i
    while j < n and src[j] not in " \t\r\n(){}":
        j += 1
    return j
