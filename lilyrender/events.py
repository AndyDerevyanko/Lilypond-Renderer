"""Flatten an interpreted Score into a performable stream of note events.

This is the bridge between the notation pipeline and anything that wants to
*perform* the music rather than draw it (piano apps, audio synths, and a
future MIDI exporter): each NoteEvent is an absolute onset + duration +
MIDI pitch on the timeline measured in whole notes.

Ties are merged into single sustained events; grace notes are given a small
nominal duration stolen from just before their host beat.
"""

from dataclasses import dataclass
from fractions import Fraction
from typing import List, Optional, Tuple

MIDDLE_C_MIDI = 60                 # model Pitch.semitones() is relative to c'
GRACE_LEN = Fraction(1, 32)        # nominal length of one grace note


@dataclass(frozen=True)
class NoteEvent:
    time: Fraction                 # onset in whole notes from the start
    duration: Fraction             # sounding length (ties merged)
    midi: int                      # MIDI note number (c' == 60)
    staff: int                     # index into Score.staves
    voice: int = 0


def extract_notes(score) -> List[NoteEvent]:
    """All sounding notes of `score`, sorted by (time, midi).

    Chords contribute one event per pitch.  A note carrying a tie is merged
    with the following event of the same staff/voice/pitch that starts where
    it ends (chains of ties collapse into one long event).
    """
    raw = []   # [onset, dur, midi, staff, voice, tied]
    for si, staff in enumerate(score.staves):
        for ev in staff.events:
            node = ev.node
            if not node.pitches or node.is_rest or node.is_skip:
                continue
            tied = any(p.kind == "tie" for p in node.post)
            if ev.grace_index:
                onset = ev.time - GRACE_LEN * ev.grace_index
                if onset < 0:
                    onset = Fraction(0)
                dur = GRACE_LEN
            else:
                onset, dur = ev.time, ev.duration
            if dur <= 0:
                continue
            for p in node.pitches:
                raw.append([onset, dur, MIDDLE_C_MIDI + p.semitones(),
                            si, ev.voice, tied])

    raw.sort(key=lambda r: (r[0], r[3], r[4], r[2]))
    by_key = {}
    for i, r in enumerate(raw):
        by_key.setdefault((r[3], r[4], r[2], r[0]), i)

    consumed = set()
    out = []
    for i, r in enumerate(raw):
        if i in consumed:
            continue
        onset, dur, midi, staff, voice, tied = r
        while tied:
            j = by_key.get((staff, voice, midi, onset + dur))
            if j is None or j in consumed:
                break
            consumed.add(j)
            dur += raw[j][1]
            tied = raw[j][5]
        out.append(NoteEvent(onset, dur, midi, staff, voice))

    out.sort(key=lambda e: (e.time, e.midi))
    return out


def find_tempo(score) -> Optional[Tuple[Fraction, int]]:
    """First \\tempo with a metronome mark, as (beat length, bpm)."""
    for st in score.staves:
        for a in st.attributes:
            if a.kind == "tempo" and a.value.bpm and a.value.unit:
                return (a.value.unit.length(), a.value.bpm)
    return None


def wholes_per_second(score, default_bpm=100) -> float:
    """Playback rate in whole notes per second (quarter = default_bpm
    when the score has no metronome mark)."""
    t = find_tempo(score)
    if t is None:
        return 0.25 * default_bpm / 60.0
    unit_len, bpm = t
    return float(unit_len) * bpm / 60.0


def total_length(score) -> Fraction:
    """End time of the last staff to finish, in whole notes."""
    end = Fraction(0)
    for st in score.staves:
        end = max(end, st.end_time)
    return end
