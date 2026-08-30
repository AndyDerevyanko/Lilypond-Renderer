\version "2.26.0"
% Variables and titles (Learning Manual 3.4)
\header {
  title = "Test Piece"
  composer = "Trad."
}

melody = \relative c'' {
  \time 4/4
  c4 d e f |
  g2 e2 |
  c1 |
}

bassline = {
  \clef bass
  c2 g,2 |
  c2 c2 |
  c1 |
}

\score {
  <<
    \new Staff \melody
    \new Staff \bassline
  >>
}
