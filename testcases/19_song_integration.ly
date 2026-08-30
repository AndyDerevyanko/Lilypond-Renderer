\version "2.26.0"
% Integration piece: melody + block chords, like a typical piano app tune
\header {
  title = "Little Song"
}
\score {
  \new PianoStaff <<
    \new Staff = "RH" \relative c'' {
      \clef treble
      \time 4/4
      a8. b16 c4 r4. e8 |
      e4 d8. c16 d4. e8 |
      c4 a8 c4. b8 a8 |
      a2 r2 |
    }
    \new Staff = "LH" {
      \clef bass
      r1 |
      <a, c e>2. <a, c e>4 |
      <f a c>2. <f a c>4 |
      <c e g>2. <c e g>4 |
    }
  >>
}
