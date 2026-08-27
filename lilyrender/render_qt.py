"""Qt painting of layout primitives.

The layout engine emits geometry in staff spaces (y down).  Here we scale
by `scale` (pixels per staff space) and draw with QPainter.  Bravura is a
SMuFL font: 1 em == 4 staff spaces, so its pixel size is 4 * scale.
"""

import os
from bisect import bisect_left, bisect_right

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import (QColor, QFont, QFontDatabase, QImage, QPainter,
                         QPainterPath, QPen, QPolygonF)

from . import smufl
from .layout import Beam, Curve, Glyph, LayoutResult, Line, System, Text

_bravura_family = None
_text_family_registered = False

_TEXT_FONT_FILES = ["texgyreschola-regular.otf", "texgyreschola-bold.otf",
                    "texgyreschola-italic.otf", "texgyreschola-bolditalic.otf"]


def bravura_family():
    """Register the music font (real LilyPond's Emmentaler, PUA-patched)
    with Qt and return the family name."""
    global _bravura_family
    if _bravura_family is None:
        fid = QFontDatabase.addApplicationFont(smufl.BRAVURA_OTF)
        fams = QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
        _bravura_family = fams[0] if fams else "Bravura"
    return _bravura_family


def _ensure_text_family():
    """Register TeX Gyre Schola (real LilyPond's default text font, all
    four weight/style variants) with Qt so setBold()/setItalic() select the
    real drawn glyphs instead of a synthesized fake-bold/oblique."""
    global _text_family_registered
    if _text_family_registered:
        return
    _text_family_registered = True
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for fn in _TEXT_FONT_FILES:
        QFontDatabase.addApplicationFont(os.path.join(_root, "fonts", fn))


class Theme:
    fg = QColor(0, 0, 0)
    bg = QColor(255, 255, 255)
    text_family = "TeX Gyre Schola"

    @staticmethod
    def qcolor(rgb, default):
        if rgb is None:
            return default
        return QColor.fromRgbF(*(list(rgb[:3]) + [1.0]))


class DarkTheme(Theme):
    fg = QColor(238, 234, 248)
    bg = QColor(43, 26, 74)          # deep purple


_TEXT_SIZES = {   # staff spaces of font pixel size per style
    "title": 3.4, "composer": 1.7, "dedication": 1.4, "lyric": 1.65,
    "tempo": 1.6, "tuplet": 1.4, "fingering": 1.25, "text": 1.9, "plain": 1.5,
    "measure_number": 1.3, "markup": 1.9,
}


def _text_font(item: Text, scale, family):
    _ensure_text_family()
    f = QFont(family)
    f.setPixelSize(max(1, round(_TEXT_SIZES.get(item.style, 1.5)
                                * item.size * scale)))
    f.setItalic(item.italic or item.style in ("text", "tuplet", "dedication"))
    if getattr(item, "bold", False) or item.style in ("tempo", "title"):
        f.setBold(True)
    return f


_CULL_MAXSPAN = 60.0     # items wider than this always paint (staff lines...)


def _item_xspan(it):
    if isinstance(it, (Line, Beam, Curve)):
        return (min(it.x1, it.x2) - 1.0, max(it.x1, it.x2) + 1.0)
    if isinstance(it, Glyph):
        return (it.x - 2.0, it.x + 5.0)
    if isinstance(it, Text):
        return (it.x - 30.0, it.x + 30.0)
    return (-1e9, 1e9)


def _cull_index(sys_: System):
    """(sorted short items, always-painted long items); cached per system."""
    cache = getattr(sys_, "_cull_cache", None)
    if cache is not None and cache[0] is sys_.items:
        return cache[1], cache[2]
    short, long_ = [], []
    for idx, it in enumerate(sys_.items):
        x0, x1 = _item_xspan(it)
        (long_ if x1 - x0 > _CULL_MAXSPAN else short).append((x0, x1, idx, it))
    short.sort(key=lambda r: r[0])
    sys_._cull_cache = (sys_.items, short, long_)
    return short, long_


def visible_items(sys_: System, clip_x0: float, clip_x1: float):
    """Items intersecting [clip_x0, clip_x1] (system x, staff spaces),
    in original paint order."""
    short, long_ = _cull_index(sys_)
    mins = [r[0] for r in short]
    lo = bisect_left(mins, clip_x0 - _CULL_MAXSPAN)
    hi = bisect_right(mins, clip_x1)
    picked = [r for r in short[lo:hi] if r[1] >= clip_x0]
    picked.extend(long_)
    picked.sort(key=lambda r: r[2])
    return [r[3] for r in picked]


def paint_system(p: QPainter, sys_: System, scale: float,
                 ox: float, oy: float, theme: Theme = Theme,
                 clip_x0: float = None, clip_x1: float = None):
    """Draw one system with its origin (x=0, y=0) at pixel (ox, oy).

    clip_x0/clip_x1 (staff spaces, system coordinates) restrict painting to
    the items that intersect the window — big win on endless scroll systems.
    """
    music = QFont(bravura_family())
    fg = theme.fg
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setRenderHint(QPainter.TextAntialiasing, True)

    def X(v): return ox + v * scale
    def Y(v): return oy + v * scale

    if clip_x0 is not None and clip_x1 is not None:
        items = visible_items(sys_, clip_x0, clip_x1)
    else:
        items = sys_.items

    for it in items:
        if isinstance(it, Line):
            color = Theme.qcolor(it.color, fg)
            pen = QPen(color)
            pen.setWidthF(max(1.0, it.thickness * scale))
            pen.setCapStyle(Qt.FlatCap)
            p.setPen(pen)
            p.drawLine(QPointF(X(it.x1), Y(it.y1)), QPointF(X(it.x2), Y(it.y2)))
        elif isinstance(it, Beam):
            half = it.thickness * scale / 2.0
            poly = QPolygonF([
                QPointF(X(it.x1), Y(it.y1) - half),
                QPointF(X(it.x2), Y(it.y2) - half),
                QPointF(X(it.x2), Y(it.y2) + half),
                QPointF(X(it.x1), Y(it.y1) + half),
            ])
            p.setPen(Qt.NoPen)
            p.setBrush(fg)
            p.drawPolygon(poly)
        elif isinstance(it, Glyph):
            if it.text is None and not smufl.has_glyph(it.name):
                continue
            color = Theme.qcolor(it.color, fg)
            music.setPixelSize(max(1, round(4 * scale * it.size)))
            p.setFont(music)
            p.setPen(color)
            # dynamics ("mf"/"sfz"/...) are drawn as literal multi-letter
            # text with the music font so the font's own GPOS kerning
            # between the individual letter glyphs applies, exactly like
            # real LilyPond's dynamic-mark typesetting.
            s = it.text if it.text is not None else smufl.char(it.name)
            p.drawText(QPointF(X(it.x), Y(it.y)), s)
        elif isinstance(it, Text):
            f = _text_font(it, scale, theme.text_family)
            p.setFont(f)
            p.setPen(fg)
            fm = p.fontMetrics()
            w = fm.horizontalAdvance(it.text)
            x = X(it.x)
            if it.anchor == "center":
                x -= w / 2
            elif it.anchor == "right":
                x -= w
            p.drawText(QPointF(x, Y(it.y)), it.text)
        elif isinstance(it, Curve):
            path = QPainterPath(QPointF(X(it.x1), Y(it.y1)))
            path.cubicTo(QPointF(X(it.cx1), Y(it.cy1)),
                         QPointF(X(it.cx2), Y(it.cy2)),
                         QPointF(X(it.x2), Y(it.y2)))
            # return path slightly offset -> filled lens (thicker middle)
            t = it.thickness * scale
            path.cubicTo(QPointF(X(it.cx2), Y(it.cy2) + t),
                         QPointF(X(it.cx1), Y(it.cy1) + t),
                         QPointF(X(it.x1), Y(it.y1)))
            p.setPen(QPen(fg, max(1.0, 0.06 * scale)))
            p.setBrush(fg)
            p.drawPath(path)


# ---------------------------------------------------------------------------
# page assembly
# ---------------------------------------------------------------------------

class PageLayout:
    """Positions systems (and a title block) onto fixed-size pages.

    All geometry in staff spaces; one page is `page_w` x `page_h` spaces.
    """

    def __init__(self, result: LayoutResult, page_w=126.0, page_h=178.0,
                 margin=8.0, system_gap=None):
        if system_gap is None:
            from .layout import Config
            system_gap = Config.system_gap
        self.result = result
        self.page_w = page_w
        self.page_h = page_h
        self.margin = margin
        self.pages = []          # [[(system, x, y_of_origin)]]
        self.titles = []         # [(text, style, x, y, anchor)] on page 0

        y = margin
        header = result.header
        cx = page_w / 2
        if header.get("dedication"):
            y += 1.2
            self.titles.append((header["dedication"], "dedication",
                                margin, y, "left"))
        if header.get("title"):
            y += 4.0
            self.titles.append((header["title"], "title", cx, y, "center"))
            y += 1.3
        if header.get("subtitle"):
            y += 1.5
            self.titles.append((header["subtitle"], "composer", cx, y, "center"))
        if header.get("composer"):
            self.titles.append((header["composer"], "composer",
                                page_w - margin, y + 1.2, "right"))
        if header.get("poet"):
            self.titles.append((header["poet"], "composer",
                                margin, y + 1.2, "left"))
        if header.get("composer") or header.get("poet"):
            y += 1.6
        # markup-system-spacing: title block sits close above the first
        # system's skyline (real LilyPond packs these tightly)
        y += 0.4

        # a hand-tuned score's \paper block sometimes fixes the system
        # count per page directly (min-systems-per-page); when set, honor
        # it exactly instead of packing by vertical fit, since the score
        # was engraved (margins/spacing) assuming that fixed count
        min_per_page = result.paper.get("min_systems_per_page")

        page0_top = y                 # bbox-top of first system on page 0
        other_top = margin + 4.0      # top-system-spacing on later pages

        # ---- group systems into pages ----
        pages_raw = []
        page = []
        yfit = page0_top
        for s in result.systems:
            need = s.top + s.height
            page_full = min_per_page and len(page) >= min_per_page
            if page and (page_full or (not min_per_page
                                        and yfit + need > page_h - margin)):
                pages_raw.append(page)
                page = []
                yfit = other_top
            page.append(s)
            yfit += need + system_gap
        if page or not pages_raw:
            pages_raw.append(page)

        # ---- vertically justify each page (real LilyPond spreads systems
        # to fill the page rather than packing them against the top) ----
        bottom_reserve = margin + 6.0
        for pi, syslist in enumerate(pages_raw):
            top_anchor = page0_top if pi == 0 else other_top
            placed = []
            if not syslist:
                self.pages.append(placed)
                continue
            natural = sum(s.top + s.height for s in syslist) \
                + system_gap * (len(syslist) - 1)
            limit = page_h - bottom_reserve
            slack = (limit - top_anchor) - natural
            # only stretch full pages (the last, short page stays ragged,
            # like ragged-last-bottom); never compress below natural
            stretch = len(syslist) > 1 and (min_per_page is None
                                            or len(syslist) >= min_per_page)
            extra = max(0.0, slack) / (len(syslist) - 1) \
                if stretch and len(syslist) > 1 else 0.0
            yy = top_anchor
            for s in syslist:
                placed.append((s, margin, yy + s.top))
                yy += s.top + s.height + system_gap + extra
            self.pages.append(placed)

    def paint_page(self, p: QPainter, idx: int, scale: float,
                   ox=0.0, oy=0.0, theme: Theme = Theme):
        if idx == 0:
            for (text, style, x, ty, anchor) in self.titles:
                item = Text(text, x, ty, style=style, anchor=anchor)
                f = _text_font(item, scale, theme.text_family)
                p.setFont(f)
                p.setPen(theme.fg)
                w = p.fontMetrics().horizontalAdvance(text)
                px = ox + x * scale
                if anchor == "center":
                    px -= w / 2
                elif anchor == "right":
                    px -= w
                p.drawText(QPointF(px, oy + ty * scale), text)
        for (s, sx, sy) in self.pages[idx]:
            paint_system(p, s, scale, ox + sx * scale, oy + sy * scale, theme)


def render_page_image(pl: PageLayout, idx: int, scale=8.0,
                      theme: Theme = Theme) -> QImage:
    w = int(pl.page_w * scale)
    h = int(pl.page_h * scale)
    img = QImage(w, h, QImage.Format_RGB32)
    img.fill(theme.bg)
    p = QPainter(img)
    pl.paint_page(p, idx, scale, theme=theme)
    p.end()
    return img


def render_scroll_image(result: LayoutResult, scale=8.0,
                        theme: Theme = Theme, pad=6.0) -> QImage:
    """Render the single endless system (scroll mode) to one long image."""
    s = result.systems[0]
    w = int((s.width + 2 * pad) * scale)
    h = int((s.top + s.height + 2 * pad) * scale)
    img = QImage(w, h, QImage.Format_RGB32)
    img.fill(theme.bg)
    p = QPainter(img)
    paint_system(p, s, scale, pad * scale, (pad + s.top) * scale, theme)
    p.end()
    return img


def export_pdf(result: LayoutResult, path: str, staff_space_mm=1.75,
               page_w=126.0, page_h=178.0, margin=8.0):
    """Write the page-mode layout to a PDF (A4-ish proportions)."""
    from PyQt5.QtGui import QPdfWriter, QPageSize
    from PyQt5.QtCore import QSizeF

    pl = PageLayout(result, page_w=page_w, page_h=page_h, margin=margin)
    writer = QPdfWriter(path)
    writer.setResolution(300)
    writer.setPageSizeMM(QSizeF(pl.page_w * staff_space_mm,
                                pl.page_h * staff_space_mm))
    scale = staff_space_mm / 25.4 * 300          # px per staff space
    p = QPainter(writer)
    for i in range(len(pl.pages)):
        if i:
            writer.newPage()
        pl.paint_page(p, i, scale)
    p.end()
    return path
