\version "2.26.0"
% Multiple staves and staff groups (Learning Manual 3.2.2 / 3.2.3)
\score {
  <<
    \new Staff {
      \clef treble
      \key d \major
      \time 3/4
      a'4 d''4 fis''4 |
      a''2. |
      g''4 fis''4 e''4 |
      d''2. |
    }
    \new Staff {
      \clef bass
      \key d \major
      \time 3/4
      d4 fis4 a4 |
      d'2. |
      e'4 a4 a,4 |
      d2. |
    }
  >>
}
