\version "2.26.0"
% Piano staff with brace (Learning Manual 3.2.3)
\score {
  \new PianoStaff <<
    \new Staff = "upper" {
      \clef treble
      \time 4/4
      e''4 d''8 c''8 d''4 e''4 |
      g'2 a'2 |
      c''1 |
    }
    \new Staff = "lower" {
      \clef bass
      \time 4/4
      <c e g>2 <b, d g>2 |
      <a, c e>2 <f a c'>2 |
      <c e g>1 |
    }
  >>
}
