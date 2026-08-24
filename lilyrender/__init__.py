"""lilyrender - a LilyPond subset renderer using the Bravura SMuFL font and PyQt5.

Pipeline:
    .ly source
      -> lexer.tokenize        (tokens)
      -> parser.Parser         (AST, model.py nodes; #(...) evaluated by pyscheme)
      -> interpret.build_score (timed per-staff event streams, measures)
      -> layout.engrave        (positioned primitives in staff-space units)
      -> ui.render_qt          (QPainter drawing; page view / scroll view / PDF)
"""

__version__ = "0.1.0"
