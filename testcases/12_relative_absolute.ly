\version "2.26.0"
% Relative vs absolute octave entry (Learning Manual 2.1 / 4.3)
\score {
  <<
    \new Staff \relative c'' {
      c4 d e f |
      g a b c |
      c,, d e f |
      g,4 c' e, g |
      c,1 |
    }
    \new Staff {
      c'4 d' e' f' |
      g' a' b' c'' |
      c'4 d' e' f' |
      g4 c' e g |
      c'1 |
    }
  >>
}
