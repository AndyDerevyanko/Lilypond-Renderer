\version "2.26.0"
% Basic embedded Scheme expressions
{
  \time 4/4
  c'4 d'4 e'4 f'4 |
  \override NoteHead.color = #red
  g'4 a'4
  \revert NoteHead.color
  b'4 c''4 |
  \tempo 4 = #(* 30 4)
  c''1 |
}
