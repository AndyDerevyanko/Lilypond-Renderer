"""PyQt5 application: page view + scrolling "music app" view.

Page mode reproduces the LilyPond PDF look (white pages, systems broken to
a fixed line width).  Scroll mode shows one endless system with a fixed
playhead; the score scrolls right-to-left while playing.

Zoom model: one percentage (25..400) shared by both views; each view has
its own base scale.  Zooming keeps the point under the cursor (Ctrl+wheel)
or the viewport centre (slider / shortcuts) anchored.
"""

import bisect
import sys
from fractions import Fraction

from PyQt5.QtCore import Qt, QEvent, QTimer, QRectF, QPointF, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPen, QBrush
from PyQt5.QtWidgets import (QAction, QActionGroup, QApplication, QFileDialog,
                             QMainWindow, QMessageBox, QScrollArea,
                             QStackedWidget, QWidget, QToolBar, QLabel,
                             QSlider, QToolButton)

from . import interpret, layout, parser
from .render_qt import (DarkTheme, PageLayout, Theme, paint_system,
                        export_pdf)

ZOOM_MIN = 25
ZOOM_MAX = 400
PAGE_BASE_SCALE = 7.0     # px per staff space at 100 %
SCROLL_BASE_SCALE = 9.0


# ---------------------------------------------------------------------------
# page mode
# ---------------------------------------------------------------------------

class PageWidget(QWidget):
    """All pages stacked vertically, white paper on grey backdrop."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pl = None
        self.scale = PAGE_BASE_SCALE
        self.page_gap_px = 24

    def set_result(self, result, geo=None):
        if result:
            geo = geo or {}
            self.pl = PageLayout(result, page_w=geo.get("page_w", 126.0),
                                 page_h=geo.get("page_h", 178.0),
                                 margin=geo.get("margin", 8.0))
        else:
            self.pl = None
        self._resize()

    def set_scale(self, s):
        if s == self.scale:
            return
        self.scale = s
        self._resize()

    def content_size(self):
        if not self.pl:
            return (400, 300)
        w = int(self.pl.page_w * self.scale) + 40
        h = int(len(self.pl.pages) *
                (self.pl.page_h * self.scale + self.page_gap_px)) + 40
        return (w, h)

    def _resize(self):
        w, h = self.content_size()
        self.setMinimumSize(w, h)
        self.resize(w, h)
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(70, 70, 74))
        if not self.pl:
            p.setPen(QColor(220, 220, 220))
            p.drawText(self.rect(), Qt.AlignCenter, "Open a .ly file")
            p.end()
            return
        pw = self.pl.page_w * self.scale
        ph = self.pl.page_h * self.scale
        ox = max(20, (self.width() - pw) / 2)
        oy = 20
        clip = ev.rect()
        for i in range(len(self.pl.pages)):
            if oy <= clip.bottom() and oy + ph + 3 >= clip.top():
                p.fillRect(QRectF(ox + 3, oy + 3, pw, ph), QColor(0, 0, 0, 90))
                p.fillRect(QRectF(ox, oy, pw, ph), Theme.bg)
                self.pl.paint_page(p, i, self.scale, ox, oy, Theme)
            oy += ph + self.page_gap_px
        p.end()


# ---------------------------------------------------------------------------
# scroll (music app) mode
# ---------------------------------------------------------------------------

class ScrollTheme(Theme):
    # plain LilyPond-PDF look: black ink on white paper
    fg = QColor(0, 0, 0)
    bg = QColor(255, 255, 255)
    playhead = QColor(0, 170, 200)
    played = QColor(0, 170, 200, 26)      # translucent wash left of playhead


class ScrollWidget(QWidget):
    """Endless system with fixed playhead; scrolls while playing.

    Interaction: Space play/pause, click seeks, drag pans, wheel pans,
    Ctrl+wheel zooms, Left/Right step by a quarter note.
    """

    PLAYHEAD_FRAC = 0.32     # playhead position as fraction of widget width
    DRAG_THRESHOLD = 4       # px before a press becomes a pan

    playing_changed = pyqtSignal(bool)
    zoom_step = pyqtSignal(int)          # +1 / -1 notches (Ctrl+wheel)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.result = None
        self.system = None
        self.scale = SCROLL_BASE_SCALE
        self.time = 0.0          # current position in whole notes
        self.playing = False
        self.wholes_per_sec = 0.5    # 120 bpm quarters
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._tick)
        self._tm_t = []          # time_map split for interpolation
        self._tm_x = []
        self._press_pos = None   # pixel pos of mouse press
        self._press_time = None  # playback time at mouse press
        self._dragging = False
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.PointingHandCursor)

    def set_result(self, result, tempo=None):
        self.result = result
        self.system = result.systems[0] if result and result.systems else None
        self.time = 0.0
        self.stop()
        if self.system:
            tm = list(self.system.time_map)
            tm.append((self.system.end_time, self.system.width - 2.0))
            self._tm_t = [float(t) for (t, _x) in tm]
            self._tm_x = [x for (_t, x) in tm]
        if tempo is not None:
            unit_len, bpm = tempo
            self.wholes_per_sec = float(unit_len) * bpm / 60.0
        self.update()

    def set_scale(self, s):
        if s != self.scale:
            self.scale = s
            self.update()

    # -- playback -----------------------------------------------------------
    def end_time(self):
        return float(self.system.end_time) if self.system else 0.0

    def play(self):
        if not self.system:
            return
        if self.time >= self.end_time():     # replay from the top
            self.time = 0.0
        self.playing = True
        self.timer.start()
        self.playing_changed.emit(True)
        self.update()

    def stop(self):
        was = self.playing
        self.playing = False
        self.timer.stop()
        if was:
            self.playing_changed.emit(False)
        self.update()

    def toggle(self):
        (self.stop if self.playing else self.play)()

    def rewind(self):
        self.time = 0.0
        self.update()

    def seek(self, t):
        self.time = max(0.0, min(self.end_time(), t))
        self.update()

    def _tick(self):
        self.time += self.wholes_per_sec * self.timer.interval() / 1000.0
        if self.system and self.time >= self.end_time():
            self.time = self.end_time()
            self.stop()
        self.update()

    # -- time <-> x mapping ---------------------------------------------------
    def x_of_time(self, t):
        """Interpolated x (staff spaces) for playback time t."""
        ts, xs = self._tm_t, self._tm_x
        if not ts:
            return 0.0
        i = bisect.bisect_right(ts, t) - 1
        if i < 0:
            return xs[0]
        if i >= len(ts) - 1:
            return xs[-1]
        t0, t1 = ts[i], ts[i + 1]
        f = 0.0 if t1 <= t0 else (t - t0) / (t1 - t0)
        return xs[i] + f * (xs[i + 1] - xs[i])

    def time_of_x(self, x):
        """Inverse of x_of_time: playback time for staff-space x."""
        ts, xs = self._tm_t, self._tm_x
        if not xs:
            return 0.0
        i = bisect.bisect_right(xs, x) - 1
        if i < 0:
            return ts[0]
        if i >= len(xs) - 1:
            return ts[-1]
        x0, x1 = xs[i], xs[i + 1]
        f = 0.0 if x1 <= x0 else (x - x0) / (x1 - x0)
        return ts[i] + f * (ts[i + 1] - ts[i])

    # -- interaction ----------------------------------------------------------
    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key_Right:
            self.seek(self.time + 0.25)
        elif ev.key() == Qt.Key_Left:
            self.seek(self.time - 0.25)
        else:
            super().keyPressEvent(ev)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton and self.system:
            self._press_pos = ev.pos()
            self._press_time = self.time
            self._dragging = False
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if self._press_pos is None or not self.system:
            return
        dx = ev.pos().x() - self._press_pos.x()
        if not self._dragging and abs(dx) < self.DRAG_THRESHOLD:
            return
        self._dragging = True
        # dragging the score right (dx>0) moves backward in time
        x0 = self.x_of_time(self._press_time)
        self.seek(self.time_of_x(x0 - dx / self.scale))

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.LeftButton and self._press_pos is not None:
            if not self._dragging and self.system:
                # click: seek to the music under the cursor
                playhead_px = self.width() * self.PLAYHEAD_FRAC
                ox = playhead_px - self.x_of_time(self.time) * self.scale
                self.seek(self.time_of_x((ev.pos().x() - ox) / self.scale))
            self._press_pos = None
            self._dragging = False
        super().mouseReleaseEvent(ev)

    def wheelEvent(self, ev):
        delta = ev.angleDelta().y() or ev.angleDelta().x()
        if not delta:
            return
        if ev.modifiers() & Qt.ControlModifier:
            self.zoom_step.emit(1 if delta > 0 else -1)
            return
        # wheel pans through the piece: one notch = one quarter note
        self.seek(self.time - (delta / 120.0) * 0.25)

    def paintEvent(self, ev):
        p = QPainter(self)
        th = ScrollTheme
        p.fillRect(self.rect(), th.bg)
        if not self.system:
            p.setPen(QColor(90, 90, 90))
            p.drawText(self.rect(), Qt.AlignCenter,
                       "Open a .ly file  |  Space = play/pause")
            p.end()
            return
        s = self.system
        scale = self.scale
        playhead_px = self.width() * self.PLAYHEAD_FRAC
        x_now = self.x_of_time(self.time) * scale
        ox = playhead_px - x_now
        # centre the full vertical extent (s.top above y=0, s.height below)
        oy = (self.height() - (s.top + s.height) * scale) / 2 + s.top * scale

        # played-region wash
        p.fillRect(QRectF(0, 0, playhead_px, self.height()),
                   QBrush(th.played))
        paint_system(p, s, scale, ox, oy, th,
                     clip_x0=(0 - ox) / scale,
                     clip_x1=(self.width() - ox) / scale)

        # playhead bar
        pen = QPen(th.playhead)
        pen.setWidthF(3.0)
        p.setPen(pen)
        p.drawLine(QPointF(playhead_px, 0), QPointF(playhead_px, self.height()))
        glow = QColor(th.playhead)
        glow.setAlpha(60)
        p.fillRect(QRectF(playhead_px - 6, 0, 12, self.height()), glow)
        p.end()


# ---------------------------------------------------------------------------
# main window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("lilyrender")
        self.resize(1280, 860)
        self.score = None
        self.path = None
        self.page_geo = None
        self.zoom_pct = 100

        self.page_widget = PageWidget()
        self.page_scroll = QScrollArea()
        self.page_scroll.setWidget(self.page_widget)
        self.page_scroll.setWidgetResizable(False)
        self.page_scroll.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.page_scroll.viewport().installEventFilter(self)
        self.scroll_widget = ScrollWidget()
        self.scroll_widget.playing_changed.connect(self._playing_changed)
        self.scroll_widget.zoom_step.connect(self._zoom_by_steps)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.page_scroll)
        self.stack.addWidget(self.scroll_widget)
        self.setCentralWidget(self.stack)

        tb = QToolBar("Main")
        tb.setMovable(False)
        self.addToolBar(tb)

        a_open = QAction("Open…", self)
        a_open.setShortcut("Ctrl+O")
        a_open.triggered.connect(self.open_dialog)
        tb.addAction(a_open)

        self.a_reload = QAction("Reload", self)
        self.a_reload.setShortcut("F5")
        self.a_reload.setEnabled(False)
        self.a_reload.triggered.connect(self.reload)
        tb.addAction(self.a_reload)

        tb.addSeparator()
        mode_group = QActionGroup(self)
        mode_group.setExclusive(True)
        self.a_page = QAction("Page view", self, checkable=True)
        self.a_page.setShortcut("Ctrl+1")
        self.a_page.setChecked(True)
        self.a_page.triggered.connect(lambda: self.set_mode(0))
        mode_group.addAction(self.a_page)
        tb.addAction(self.a_page)

        self.a_scroll = QAction("Scroll view", self, checkable=True)
        self.a_scroll.setShortcut("Ctrl+2")
        self.a_scroll.triggered.connect(lambda: self.set_mode(1))
        mode_group.addAction(self.a_scroll)
        tb.addAction(self.a_scroll)

        tb.addSeparator()
        self.a_play = QAction("Play", self, checkable=True)
        self.a_play.setShortcut(Qt.Key_Space)
        self.a_play.setEnabled(False)
        self.a_play.triggered.connect(self.toggle_play)
        tb.addAction(self.a_play)

        self.a_rew = QAction("Rewind", self)
        self.a_rew.setShortcut(Qt.Key_Home)
        self.a_rew.setEnabled(False)
        self.a_rew.triggered.connect(self.scroll_widget.rewind)
        tb.addAction(self.a_rew)

        tb.addSeparator()
        self.a_pdf = QAction("Export PDF…", self)
        self.a_pdf.setShortcut("Ctrl+E")
        self.a_pdf.setEnabled(False)
        self.a_pdf.triggered.connect(self.export_pdf_dialog)
        tb.addAction(self.a_pdf)

        tb.addSeparator()
        a_zout = QAction("−", self)
        a_zout.setShortcut("Ctrl+-")
        a_zout.triggered.connect(lambda: self._zoom_by_steps(-1))
        tb.addAction(a_zout)

        self.zoom = QSlider(Qt.Horizontal)
        self.zoom.setRange(ZOOM_MIN, ZOOM_MAX)
        self.zoom.setValue(self.zoom_pct)
        self.zoom.setFixedWidth(140)
        self.zoom.valueChanged.connect(self._slider_zoom)
        tb.addWidget(self.zoom)

        a_zin = QAction("+", self)
        a_zin.setShortcut("Ctrl+=")
        a_zin.triggered.connect(lambda: self._zoom_by_steps(1))
        tb.addAction(a_zin)

        a_zreset = QAction("100%", self)
        a_zreset.setShortcut("Ctrl+0")
        a_zreset.triggered.connect(lambda: self.set_zoom(100))
        tb.addAction(a_zreset)

        self.zoom_label = QLabel(" 100% ")
        self.zoom_label.setFixedWidth(48)
        tb.addWidget(self.zoom_label)

        self.status = self.statusBar()

    # -- mode / playback ------------------------------------------------------
    def set_mode(self, idx):
        self.stack.setCurrentIndex(idx)
        self.a_page.setChecked(idx == 0)
        self.a_scroll.setChecked(idx == 1)
        if idx == 1:
            self.scroll_widget.setFocus()

    def toggle_play(self):
        if not self.score:
            self.a_play.setChecked(False)
            return
        if self.stack.currentIndex() != 1:
            self.set_mode(1)          # playback lives in the scroll view
        self.scroll_widget.toggle()

    def _playing_changed(self, playing):
        self.a_play.setChecked(playing)
        self.a_play.setText("Pause" if playing else "Play")

    # -- zoom ------------------------------------------------------------------
    def set_zoom(self, pct, anchor=None):
        """Set zoom percentage; keep `anchor` (page-view viewport point,
        default centre) fixed while rescaling."""
        pct = max(ZOOM_MIN, min(ZOOM_MAX, int(round(pct))))
        if pct == self.zoom_pct:
            return
        old_scale = self.page_widget.scale
        self.zoom_pct = pct
        self.page_widget.set_scale(PAGE_BASE_SCALE * pct / 100.0)
        self.scroll_widget.set_scale(SCROLL_BASE_SCALE * pct / 100.0)
        # keep the anchor point stationary in the page view
        f = self.page_widget.scale / old_scale
        vp = self.page_scroll.viewport()
        ax = anchor.x() if anchor is not None else vp.width() / 2
        ay = anchor.y() if anchor is not None else vp.height() / 2
        for bar, a in ((self.page_scroll.horizontalScrollBar(), ax),
                       (self.page_scroll.verticalScrollBar(), ay)):
            bar.setValue(int(round((bar.value() + a) * f - a)))
        self.zoom.blockSignals(True)
        self.zoom.setValue(pct)
        self.zoom.blockSignals(False)
        self.zoom_label.setText(f" {pct}% ")

    def _slider_zoom(self, v):
        self.set_zoom(v)

    def _zoom_by_steps(self, steps, anchor=None):
        factor = 1.1 ** steps
        # ensure at least 1 % of movement so small percentages still change
        new = self.zoom_pct * factor
        if abs(new - self.zoom_pct) < 1:
            new = self.zoom_pct + (1 if steps > 0 else -1)
        self.set_zoom(new, anchor=anchor)

    def eventFilter(self, obj, ev):
        # Ctrl+wheel zoom in the page view, anchored at the cursor
        if obj is self.page_scroll.viewport() and ev.type() == QEvent.Wheel \
                and ev.modifiers() & Qt.ControlModifier:
            delta = ev.angleDelta().y() or ev.angleDelta().x()
            if delta:
                self._zoom_by_steps(1 if delta > 0 else -1, anchor=ev.pos())
            return True
        return super().eventFilter(obj, ev)

    # -- file actions -----------------------------------------------------------
    def open_dialog(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open LilyPond file", "", "LilyPond (*.ly);;All files (*)")
        if path:
            self.load(path)

    def reload(self):
        if self.path:
            self.load(self.path)

    def load(self, path):
        try:
            with open(path, encoding="utf-8") as f:
                scores = parser.parse(f.read(), path)
            if not scores:
                raise ValueError("no music found in file")
            score = interpret.build_score(scores[0])
        except Exception as e:
            QMessageBox.critical(self, "lilyrender", f"Cannot load {path}:\n{e}")
            return
        self.path = path
        self.score = score
        geo = layout.page_geometry(score.paper)
        page = layout.engrave(score, line_width=geo["line_width"])
        scroll = layout.engrave(score, scroll=True)
        self.page_geo = geo
        self.page_widget.set_result(page, geo=geo)
        self.scroll_widget.set_result(scroll, tempo=self._find_tempo(score))
        for a in (self.a_reload, self.a_play, self.a_rew, self.a_pdf):
            a.setEnabled(True)
        title = score.header.get("title") or path
        self.setWindowTitle(f"lilyrender — {title}")
        n = sum(len(s.events) for s in score.staves)
        self.status.showMessage(
            f"{path} — {len(score.staves)} staves, {n} events, "
            f"{len(page.systems)} systems")

    @staticmethod
    def _find_tempo(score):
        for st in score.staves:
            for a in st.attributes:
                if a.kind == "tempo" and a.value.bpm and a.value.unit:
                    return (a.value.unit.length(), a.value.bpm)
        return None

    def export_pdf_dialog(self):
        if not self.score:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export PDF", "", "PDF (*.pdf)")
        if not path:
            return
        geo = self.page_geo or layout.page_geometry(self.score.paper)
        result = layout.engrave(self.score, line_width=geo["line_width"])
        staff_space_mm = geo["staff_size"] / 4.0 * 0.352778   # pt -> mm
        export_pdf(result, path, staff_space_mm=staff_space_mm,
                  page_w=geo["page_w"], page_h=geo["page_h"],
                  margin=geo["margin"])
        self.status.showMessage(f"Exported {path}")


def run(argv=None):
    argv = argv if argv is not None else sys.argv
    app = QApplication(argv)
    win = MainWindow()
    win.show()
    for a in argv[1:]:
        if a.lower().endswith(".ly"):
            win.load(a)
            break
    return app.exec_()
