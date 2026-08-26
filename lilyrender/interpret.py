"""AST -> resolved Score: per-staff timelines of TimedEvents + attributes.

Handles \\relative octave resolution, duration inheritance, tuplet time
scaling, grace-note slots, << >> synchronisation, \\\\ voice separation,
staff/group contexts and \\addlyrics attachment.
"""

import copy
import itertools
from fractions import Fraction

from . import model as M
from .model import (Pitch, Duration, NoteNode, ClefNode, KeyNode, TimeNode,
                    TempoNode, BarNode, PartialNode, SequentialNode,
                    SimultaneousNode, RelativeNode, TupletNode, GraceNode,
                    ContextNode, AddLyricsNode, ScoreNode, OverrideNode,
                    UnsupportedNode, MarkupNode, LyricsNode, BreakNode,
                    ChangeStaffNode, OttavaNode, StemNode, ScaleDurationsNode,
                    TagNode, KeepTagNode, PostMarkNode, HideNode,
                    TimedEvent, AttributeEvent, StaffData, StaffGroup, Score)
from .parser import _FixedWrapper

STAFF_CONTEXTS = {"Staff", "RhythmicStaff", "TabStaff", "DrumStaff", "Voice"}
GROUP_CONTEXTS = {"PianoStaff", "GrandStaff", "StaffGroup", "ChoirStaff"}

_tuplet_ids = itertools.count(1)
_event_seq = itertools.count(1)

# LilyPond: \relative with no reference pitch defaults to f (below middle C),
# which makes an unmarked first note read as written in absolute octaves.
_DEFAULT_RELATIVE_REF = Pitch(3, 0, -1)


class _VoiceState:
    """Mutable interpretation state for one voice stream."""
    def __init__(self, time=Fraction(0)):
        self.time = time
        self.last_duration = Duration(2)      # lilypond default: quarter
        self.relative_ref = None              # Pitch or None (absolute mode)
        self.tuplet_factor = Fraction(1)
        self.tuplet_info = None               # (num, den, group_id)
        self.grace_pending = 0                # grace notes queued before next beat
        self.measure_len = Fraction(1)        # from \time, default 4/4
        self.fixed_ref = None
        self._chord_prev = None
        self.last_chord = None                # resolved pitches for q
        self.stem_dir = 0                     # \stemUp/\voiceOne... state
        self.ottava = 0                       # \ottava state
        self.staff_idx = None                 # \change Staff override
        self.hidden = False                   # \hideNotes/\unHideNotes state


class Interpreter:
    def __init__(self):
        self.score = Score()
        self.staff_stack = []      # indices into score.staves
        self.current_group = None
        self.tag_filters = []      # (frozenset, keep) from \keepWithTag etc.
        self.last_opened_staff = None  # idx of the most recently opened
                                        # `\new Staff` sibling (for Dynamics
                                        # lanes); NOT updated by `\change
                                        # Staff`, which may pre-create a
                                        # later-named staff out of order.

    # -- staff helpers ---------------------------------------------------
    def new_staff(self, name=None):
        st = StaffData(name=name)
        self.score.staves.append(st)
        idx = len(self.score.staves) - 1
        if self.current_group is not None:
            self.current_group.staves.append(idx)
        return idx

    def staff_index_by_name(self, name):
        for i, s in enumerate(self.score.staves):
            if s.name == name:
                return i
        return None

    def ensure_staff(self, st=None):
        if st is not None and st.staff_idx is not None:
            return self.score.staves[st.staff_idx]
        if not self.staff_stack:
            self.staff_stack.append(self.new_staff())
        return self.score.staves[self.staff_stack[-1]]

    # -- main walk ---------------------------------------------------------
    def run(self, score_node: ScoreNode) -> Score:
        self.score.header = dict(score_node.header)
        self.score.paper = dict(score_node.paper)
        st = _VoiceState()
        self.walk(score_node.body, st, voice=0)
        for staff in self.score.staves:
            if staff.events:
                staff.end_time = max(staff.end_time,
                                     max(e.time + e.duration for e in staff.events))
        return self.score

    def walk(self, node, st: _VoiceState, voice: int) -> Fraction:
        """Interpret node starting at st.time; returns elapsed length."""
        if node is None:
            return Fraction(0)

        if isinstance(node, SequentialNode):
            t0 = st.time
            for el in node.elements:
                self.walk(el, st, voice)
            return st.time - t0

        if isinstance(node, SimultaneousNode):
            return self.walk_simultaneous(node, st, voice)

        if isinstance(node, ContextNode):
            return self.walk_context(node, st, voice)

        if isinstance(node, RelativeNode):
            body = node.body
            if isinstance(body, _FixedWrapper):
                saved = st.fixed_ref
                st.fixed_ref = body.ref
                n = self.walk(body.body, st, voice)
                st.fixed_ref = saved
                return n
            saved = st.relative_ref
            st.relative_ref = node.reference or _DEFAULT_RELATIVE_REF
            n = self.walk(body, st, voice)
            st.relative_ref = saved
            return n

        if isinstance(node, TupletNode):
            num, den = node.ratio
            gid = next(_tuplet_ids)
            saved_f, saved_i = st.tuplet_factor, st.tuplet_info
            st.tuplet_factor = st.tuplet_factor * Fraction(den, num)
            st.tuplet_info = (num, den, gid)
            n = self.walk(node.body, st, voice)
            st.tuplet_factor, st.tuplet_info = saved_f, saved_i
            return n

        if isinstance(node, ScaleDurationsNode):
            saved = st.tuplet_factor
            st.tuplet_factor = st.tuplet_factor * node.factor
            n = self.walk(node.body, st, voice)
            st.tuplet_factor = saved
            return n

        if isinstance(node, TagNode):
            for tags, keep in self.tag_filters:
                if keep and node.tags.isdisjoint(tags):
                    return Fraction(0)
                if not keep and node.tags & tags:
                    return Fraction(0)
            return self.walk(node.body, st, voice)

        if isinstance(node, KeepTagNode):
            self.tag_filters.append((node.tags, node.keep))
            n = self.walk(node.body, st, voice)
            self.tag_filters.pop()
            return n

        if isinstance(node, ChangeStaffNode):
            idx = self.staff_index_by_name(node.target)
            if idx is None:
                # staff not seen yet (e.g. \change to "lower" while walking
                # the upper staff): create it so events land in the right place
                idx = self.new_staff(node.target)
            st.staff_idx = idx
            # returning to the voice's own staff?
            if self.staff_stack and idx == self.staff_stack[-1]:
                st.staff_idx = None
            return Fraction(0)

        if isinstance(node, OttavaNode):
            st.ottava = node.octaves
            self.add_attr(st, "ottava", node.octaves)
            return Fraction(0)

        if isinstance(node, StemNode):
            st.stem_dir = node.direction
            return Fraction(0)

        if isinstance(node, HideNode):
            st.hidden = node.hidden
            return Fraction(0)

        if isinstance(node, M.RepeatNode):
            return self.walk_repeat(node, st, voice)

        if isinstance(node, PostMarkNode):
            staff = self.ensure_staff(st)
            target = None
            for e in reversed(staff.events):
                if e.voice == voice:
                    target = e
                    break
            if target is None and staff.events:
                target = staff.events[-1]
            if target is not None and node.event is not None:
                target.node.post.append(node.event)
            return Fraction(0)

        if isinstance(node, GraceNode):
            # collect grace notes: they occupy no timeline space
            events = _collect_notes(node.body)
            staff = self.ensure_staff(st)
            total = len(events)
            for i, nn in enumerate(events):
                dur = nn.duration or st.last_duration
                if nn.duration:
                    st.last_duration = nn.duration
                st._chord_prev = None
                pitches = [self.resolve_pitch(p, st, first_in_chord=(j == 0))
                           for j, p in enumerate(nn.pitches)]
                if pitches and st.relative_ref is not None:
                    st.relative_ref = pitches[0]
                nn2 = NoteNode(pitches, dur, nn.post, nn.is_rest, nn.is_skip)
                staff.events.append(TimedEvent(
                    st.time, Fraction(0), nn2, voice,
                    grace_index=total - i, stem_dir=st.stem_dir,
                    ottava=st.ottava, seq=next(_event_seq), hidden=st.hidden))
            return Fraction(0)

        if isinstance(node, NoteNode):
            return self.walk_note(node, st, voice)

        if isinstance(node, ClefNode):
            self.add_attr(st, "clef", node.name); return Fraction(0)
        if isinstance(node, KeyNode):
            self.add_attr(st, "key", node); return Fraction(0)
        if isinstance(node, TimeNode):
            st.measure_len = Fraction(node.num, node.den)
            self.add_attr(st, "time", (node.num, node.den)); return Fraction(0)
        if isinstance(node, TempoNode):
            self.add_attr(st, "tempo", node); return Fraction(0)
        if isinstance(node, BarNode):
            self.add_attr(st, "bar", node.style); return Fraction(0)
        if isinstance(node, PartialNode):
            self.add_attr(st, "partial", node.duration.length()); return Fraction(0)
        if isinstance(node, BreakNode):
            if node.kind in ("line", "page"):
                self.score.breaks[st.time] = node.kind
            return Fraction(0)
        if isinstance(node, OverrideNode):
            self.add_attr(st, "override", (node.path, node.value)); return Fraction(0)
        if isinstance(node, AddLyricsNode):
            self.attach_lyrics(node.lyrics); return Fraction(0)
        if isinstance(node, (UnsupportedNode, MarkupNode, M.SchemeNode, LyricsNode)):
            return Fraction(0)

        return Fraction(0)

    # -- simultaneous ------------------------------------------------------
    def walk_simultaneous(self, node, st, voice):
        t0 = st.time
        end_times = [t0]
        n_others = sum(1 for e in node.elements if not _creates_staff(e))
        multi = node.voice_separated or n_others > 1
        if n_others and multi:
            self.ensure_staff()
        saved_stack = list(self.staff_stack)

        # \relative threads the reference pitch sequentially through the
        # elements of << >> (verified against LilyPond 2.24 on the Chopin
        # ballades: the music following << >> continues from the reference
        # left after ALL elements).  Default durations thread lexically the
        # same way.
        ref = st.relative_ref
        last_dur = st.last_duration
        vidx = 0
        for el in node.elements:
            sub = _VoiceState(t0)
            sub.measure_len = st.measure_len
            sub.relative_ref = ref
            sub.last_duration = last_dur
            if _creates_staff(el):
                self.walk(el, sub, 0)
                self.staff_stack = list(saved_stack)
            else:
                sub.tuplet_factor = st.tuplet_factor
                sub.last_chord = st.last_chord
                sub.stem_dir = st.stem_dir
                sub.ottava = st.ottava
                sub.staff_idx = st.staff_idx
                self.walk(el, sub, vidx if multi else voice)
                vidx += 1
            end_times.append(sub.time)
            ref = sub.relative_ref
            last_dur = sub.last_duration

        st.time = max(end_times)
        if st.relative_ref is not None and ref is not None:
            st.relative_ref = ref
        st.last_duration = last_dur
        return st.time - t0

    def walk_repeat(self, node, st, voice):
        """\\repeat unfold: walk the body once (lilypond resolves \\relative
        once over the body), then replay the resolved events shifted in time."""
        t0 = st.time
        before = [(len(s.events), len(s.attributes))
                  for s in self.score.staves]
        delta = self.walk(node.body, st, voice)
        if node.count > 1 and delta > 0:
            slices = []
            for i, s in enumerate(self.score.staves):
                e0, a0 = before[i] if i < len(before) else (0, 0)
                slices.append((s, s.events[e0:], s.attributes[a0:]))
            for k in range(1, node.count):
                off = delta * k
                gid_map = {}
                for s, evs, attrs in slices:
                    for e in evs:
                        ne = copy.deepcopy(e)
                        ne.time = e.time + off
                        ne.seq = next(_event_seq)
                        ne.unfolded = True
                        if ne.tuplet:
                            num, den, gid = ne.tuplet
                            if gid not in gid_map:
                                gid_map[gid] = next(_tuplet_ids)
                            ne.tuplet = (num, den, gid_map[gid])
                        s.events.append(ne)
                    for a in attrs:
                        s.attributes.append(
                            AttributeEvent(a.time + off, a.kind, a.value))
            st.time = t0 + delta * node.count
        return st.time - t0

    def walk_context(self, node, st, voice):
        t0 = st.time
        if node.ctype in GROUP_CONTEXTS:
            saved_group = self.current_group
            grp = StaffGroup(node.ctype)
            self.score.groups.append(grp)
            self.current_group = grp
            sub = _VoiceState(t0)
            sub.measure_len = st.measure_len
            self.walk(node.body, sub, voice)
            self.current_group = saved_group
            st.time = max(st.time, sub.time)
            return st.time - t0

        if node.ctype == "Devnull":
            return Fraction(0)      # \forceBreaks etc: silenced entirely

        if node.ctype == "Dynamics":
            # dynamics/pedal lane: merge into the most recently *opened*
            # sibling Staff (not just the last-created one -- a `\change
            # Staff` earlier in another voice can pre-create a later-named
            # staff, so array length is not reliable here).
            if not self.score.staves:
                return Fraction(0)
            idx = self.last_opened_staff if self.last_opened_staff is not None \
                else len(self.score.staves) - 1
            self.staff_stack.append(idx)
            sub = _VoiceState(t0)
            sub.measure_len = st.measure_len
            self.walk(node.body, sub, voice)
            self.staff_stack.pop()
            st.time = max(st.time, sub.time)
            return st.time - t0

        if node.ctype in STAFF_CONTEXTS and node.ctype != "Voice":
            idx = None
            if node.name is not None:
                # a \change Staff may have created this staff already
                idx = self.staff_index_by_name(node.name)
                if idx is not None and self.score.staves[idx].events:
                    pass          # reuse it (events keep their times)
            if idx is None:
                idx = self.new_staff(node.name)
            self.last_opened_staff = idx
            self.staff_stack.append(idx)
            sub = _VoiceState(t0)
            sub.measure_len = st.measure_len
            self.walk(node.body, sub, voice)
            self.staff_stack.pop()
            st.time = max(st.time, sub.time)
            return st.time - t0

        # Voice / Lyrics / unknown context: interpret in current staff
        return self.walk(node.body, st, voice)

    # -- notes --------------------------------------------------------------
    def resolve_pitch(self, p, st, first_in_chord):
        if st.fixed_ref is not None:
            return Pitch(p.step, p.alter,
                         p.octave + st.fixed_ref.octave + 1)
        if st.relative_ref is None:
            return p
        ref = st.relative_ref if first_in_chord else st._chord_prev
        marks = p.octave + 1     # parser stores bare note as octave -1
        # choose octave so |interval| <= 3 diatonic steps
        prev_d = ref.diatonic
        base_oct = (prev_d - p.step) // 7
        best = None
        for o in (base_oct - 1, base_oct, base_oct + 1):
            d = o * 7 + p.step - prev_d
            if -3 <= d <= 3:
                best = o
                break
        if best is None:
            best = base_oct
        newp = Pitch(p.step, p.alter, best + marks)
        st._chord_prev = newp
        return newp

    def walk_note(self, node, st, voice):
        staff = self.ensure_staff(st)
        dur = node.duration or st.last_duration
        if node.duration is not None:
            st.last_duration = Duration(node.duration.log, node.duration.dots)

        if node.is_full_measure_rest:
            base = dur.length() if node.duration else st.measure_len
            length = st.measure_len * node.multiplier \
                if node.duration is None else base * node.multiplier
            ev = TimedEvent(st.time, length, node, voice, seq=next(_event_seq),
                            hidden=st.hidden)
            staff.events.append(ev)
            st.time += length
            return length

        length = dur.length() * st.tuplet_factor

        if node.is_chord_repeat:                     # q: repeat last chord
            pitches = list(st.last_chord or [])
            node = NoteNode(pitches, dur, node.post, is_rest=not pitches,
                            is_chord_repeat=True)
        elif node.pitches:
            st._chord_prev = None
            pitches = [self.resolve_pitch(p, st, first_in_chord=(i == 0))
                       for i, p in enumerate(node.pitches)]
            if st.relative_ref is not None:
                st.relative_ref = pitches[0]
            if len(pitches) > 1:
                st.last_chord = list(pitches)
            node = NoteNode(pitches, dur, node.post, node.is_rest,
                            node.is_skip, node.is_full_measure_rest,
                            node.multiplier)
        else:
            node = NoteNode([], dur, node.post, node.is_rest, node.is_skip,
                            node.is_full_measure_rest, node.multiplier)

        ev = TimedEvent(st.time, length, node, voice, tuplet=st.tuplet_info,
                        stem_dir=st.stem_dir, ottava=st.ottava,
                        seq=next(_event_seq), hidden=st.hidden)
        staff.events.append(ev)
        st.time += length
        return length

    # -- attributes / lyrics -------------------------------------------------
    def add_attr(self, st, kind, value):
        staff = self.ensure_staff(st)
        staff.attributes.append(AttributeEvent(st.time, kind, value))

    def attach_lyrics(self, lyr: LyricsNode):
        if not self.score.staves:
            return
        staff = self.score.staves[-1]
        notes = sorted([e for e in staff.events
                        if e.node.pitches and e.grace_index == 0 and e.voice == 0],
                       key=lambda e: e.time)
        # skip notes tied from a previous one
        onsets = []
        tied = False
        for e in notes:
            if not tied:
                onsets.append(e)
            tied = any(p.kind == "tie" for p in e.node.post)
        texts = []
        for i, (text, cont) in enumerate(lyr.syllables):
            if cont == "-":
                text = text + "-"
            texts.append(text)
        for e, text in zip(onsets, texts):
            if text:
                staff.lyrics.append((e.time, text))


def _creates_staff(node):
    if isinstance(node, ContextNode):
        return (node.ctype in STAFF_CONTEXTS.union(GROUP_CONTEXTS)
                and node.ctype != "Voice") \
            or node.ctype in ("Dynamics", "Devnull")
    if isinstance(node, (RelativeNode, TagNode, KeepTagNode, M.RepeatNode)):
        body = node.body
        if isinstance(body, _FixedWrapper):
            body = body.body
        return _creates_staff(body)
    return False


def _collect_notes(node):
    if isinstance(node, NoteNode):
        return [node]
    out = []
    if isinstance(node, (SequentialNode, SimultaneousNode)):
        for el in node.elements:
            out.extend(_collect_notes(el))
    elif isinstance(node, (RelativeNode, TupletNode, GraceNode, ContextNode,
                           ScaleDurationsNode, TagNode, KeepTagNode,
                           M.RepeatNode)):
        body = node.body if not isinstance(node.body, _FixedWrapper) else node.body.body
        out.extend(_collect_notes(body))
    return out


def build_score(score_node: ScoreNode) -> Score:
    return Interpreter().run(score_node)
