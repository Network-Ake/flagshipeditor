"""The song-level plan the edit is built against, and the roles footage plays.

A timeline assembled cut by cut has no memory. Every slot is filled with
whatever scored highest at that instant, which is why the shipped engine
produces a rotation: with a no-repeat window of four and a least-recently-used
tie-break, twenty-four clips come back in almost perfect round-robin. Measured
on a 3:30 track, five clips were each used exactly fifty-two times.

This module supplies the memory. Before a single clip is chosen it builds:

* a :class:`NarrativePlan` — an ordered set of stages across the track, each
  with a time span, an intent, and the footage roles that serve it;
* a role for every clip, with confidence, so "this is the establishing shot"
  is a claim about measured descriptors rather than a label;
* a :class:`MotifLedger` that separates a *callback* — a deliberate return to
  an image the song has already used, justified by structure or a repeated
  lyric — from an accidental repeat.

Nothing here is a neural model and nothing pretends to be. The plan is derived
from measured tension, section structure and, when it is trustworthy enough,
lyric evidence. Where the evidence does not support a stage, the stage is
omitted rather than invented, and :attr:`NarrativePlan.confidence` says how much
of the plan rests on measurement.
"""

from __future__ import annotations

from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

import numpy as np

# The roles footage can play. These are editorial functions, not genres: the
# same clip can be an establishing shot early and an environment beat later,
# and the classifier reports every role it can support rather than forcing one.
ROLES = (
    "establishing",     # where we are
    "performance",      # the artist delivering
    "character",        # who this is, introduced
    "action",           # something happening
    "reaction",         # someone responding
    "environment",      # texture of the world
    "detail",           # a close object or gesture
    "bridge",           # a shot that carries us between two places
    "emotional",        # a face held long enough to read
    "symbolic",         # an image that stands for something
    "escalation",       # movement or energy that raises the stakes
    "climax",           # the biggest image available
    "resolution",       # the image that lets the song land
    "neutral",          # honest coverage with no strong claim
)

# The stages a music video can pass through. Not all appear in every song —
# a two-minute loosie has an opening image, a hook identity and a final image
# and nothing else, and forcing the rest would be fabrication.
STAGES = (
    "opening_image",
    "establish",
    "introduce",
    "theme",
    "setup",
    "escalate",
    "turn",
    "hook_identity",
    "climax",
    "release",
    "resolution",
    "final_image",
)

# What each stage wants on screen, best first. Consumed as a ranked preference
# by the selector, never as a hard filter — a library that has no symbolic
# footage still fills its turn, it just scores lower and says so.
STAGE_ROLE_PREFERENCE: Dict[str, Tuple[str, ...]] = {
    "opening_image": ("establishing", "environment", "symbolic", "detail"),
    "establish": ("establishing", "environment", "bridge", "detail"),
    "introduce": ("character", "performance", "emotional", "detail"),
    "theme": ("performance", "symbolic", "emotional", "environment"),
    "setup": ("action", "environment", "performance", "detail"),
    "escalate": ("escalation", "action", "performance", "detail"),
    "turn": ("emotional", "reaction", "symbolic", "detail"),
    "hook_identity": ("performance", "character", "climax", "emotional"),
    "climax": ("climax", "escalation", "performance", "action"),
    "release": ("reaction", "emotional", "environment", "detail"),
    "resolution": ("resolution", "emotional", "environment", "symbolic"),
    "final_image": ("resolution", "symbolic", "environment", "establishing"),
}

# How much a stage tolerates seeing the same thing again. A hook is *supposed*
# to bring back the image the viewer associates with it; an escalation that
# repeats itself is just running out of footage.
STAGE_MOTIF_TOLERANCE: Dict[str, float] = {
    "opening_image": 0.0,
    "establish": 0.15,
    "introduce": 0.1,
    "theme": 0.45,
    "setup": 0.2,
    "escalate": 0.1,
    "turn": 0.2,
    "hook_identity": 0.75,
    "climax": 0.4,
    "release": 0.3,
    "resolution": 0.5,
    "final_image": 0.85,
}

# Section labels that behave like a hook when the arrangement supports it.
HOOK_LIKE_SECTIONS = frozenset({"chorus", "drop"})

# Below this the plan is reported but should not be allowed to override the
# selector's other evidence. It exists so a track with unusable segmentation
# degrades to "no strong narrative claim" instead of to a confident wrong one.
MIN_PLAN_CONFIDENCE = 0.3


class NarrativeStage(NamedTuple):
    """One stage of the plan, with the evidence that placed it."""

    name: str
    start: float
    end: float
    roles: Tuple[str, ...]
    motif_tolerance: float
    intensity: float
    confidence: float
    evidence: Tuple[str, ...]

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


class NarrativePlan(NamedTuple):
    """The whole arc, plus how much of it is measurement rather than convention."""

    stages: Tuple[NarrativeStage, ...]
    confidence: float
    diagnostics: Dict[str, Any]

    def stage_at(self, time_value: float) -> Optional[NarrativeStage]:
        for stage in self.stages:
            if stage.start <= time_value < stage.end:
                return stage
        return self.stages[-1] if self.stages else None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "confidence": round(self.confidence, 4),
            "stages": [
                {
                    "name": stage.name,
                    "start": round(stage.start, 4),
                    "end": round(stage.end, 4),
                    "roles": list(stage.roles),
                    "motifTolerance": round(stage.motif_tolerance, 3),
                    "intensity": round(stage.intensity, 4),
                    "confidence": round(stage.confidence, 4),
                    "evidence": list(stage.evidence),
                }
                for stage in self.stages
            ],
            "diagnostics": self.diagnostics,
        }


def classify_clip_roles(clip: Dict[str, Any]) -> Dict[str, float]:
    """Return every narrative role this clip can support, with confidence 0..1.

    The evidence is what clip analysis already measures — whether a face is
    present and how consistently, the shot scale, the camera movement, motion
    intensity, brightness. Each role is scored independently because footage is
    genuinely multi-purpose: a wide static landscape is a strong establishing
    shot *and* a usable environment beat, and collapsing that to one label
    throws away the flexibility the selector needs on a small library.

    A role that the descriptors cannot support scores zero and is absent, which
    is what makes ``neutral`` the honest answer for coverage footage rather
    than a dumping ground.
    """
    def number(key: str, default: float = 0.0) -> float:
        try:
            value = float(clip.get(key, default) or default)
        except (TypeError, ValueError):
            return default
        return value if np.isfinite(value) else default

    scene = str(clip.get("scene_type", "unknown") or "unknown")
    shot = str(clip.get("shot_type", "unknown") or "unknown")
    movement = str(clip.get("camera_movement", "unknown") or "unknown")
    has_face = bool(clip.get("has_face"))
    face_consistency = max(0.0, min(1.0, number("face_consistency")))
    face_ratio = max(0.0, min(1.0, number("face_size_ratio")))
    motion = max(0.0, min(100.0, number("motion_intensity"))) / 100.0
    variance = max(0.0, min(100.0, number("motion_variance") * 10.0)) / 100.0
    stability = max(0.0, min(100.0, number("brightness_stability", 100.0))) / 100.0
    composition = max(0.0, min(100.0, number("composition_score", 50.0))) / 100.0

    wide = shot in ("extreme_long_shot", "long_shot", "medium_long_shot")
    tight = shot in ("close_up", "extreme_close_up", "medium_close_up")

    roles: Dict[str, float] = {}

    if wide:
        roles["establishing"] = min(1.0, 0.45 + composition * 0.35 + stability * 0.2)
        roles["environment"] = min(1.0, 0.4 + composition * 0.3 + (1.0 - motion) * 0.3)
    elif shot == "unknown" and not has_face and motion < 0.3:
        # Scale could not be measured. A still, faceless shot is *probably*
        # environment, and 0.35 is deliberately low so a measured wide always
        # outranks it.
        roles["environment"] = 0.35

    if scene in ("performance", "b_roll_with_face") or (has_face and face_consistency > 0.4):
        roles["performance"] = min(1.0, 0.4 + face_consistency * 0.45 + motion * 0.15)

    if has_face and tight and face_consistency > 0.5:
        roles["character"] = min(1.0, 0.35 + face_consistency * 0.4 + min(1.0, face_ratio * 4.0) * 0.25)
        roles["emotional"] = min(1.0, 0.3 + face_consistency * 0.45 + stability * 0.25)

    if has_face and face_consistency > 0.3 and motion < 0.45:
        roles["reaction"] = min(1.0, 0.3 + face_consistency * 0.35 + (1.0 - motion) * 0.2)

    if motion > 0.35 or scene == "b_roll_dynamic":
        roles["action"] = min(1.0, 0.3 + motion * 0.5 + variance * 0.2)
    if motion > 0.5 and variance > 0.25:
        roles["escalation"] = min(1.0, 0.25 + motion * 0.45 + variance * 0.3)
    if motion > 0.6 and composition > 0.5:
        roles["climax"] = min(1.0, 0.2 + motion * 0.45 + composition * 0.35)

    if tight and not has_face:
        roles["detail"] = min(1.0, 0.4 + composition * 0.35 + stability * 0.25)

    if movement in ("pan", "push_pull", "tracking") and motion > 0.2:
        roles["bridge"] = min(1.0, 0.3 + motion * 0.35 + composition * 0.2)

    if not has_face and motion < 0.25 and composition > 0.55:
        roles["symbolic"] = min(1.0, 0.25 + composition * 0.4 + stability * 0.2)
        roles["resolution"] = min(1.0, 0.25 + composition * 0.35 + stability * 0.3)

    # Every usable clip can always be honest coverage. Keeping this floor is
    # what lets a four-clip library fill a timeline without the selector
    # pretending the footage is something it is not.
    roles["neutral"] = 0.3

    return {name: round(value, 4) for name, value in roles.items() if value > 0.0}


def primary_role(roles: Dict[str, float]) -> Tuple[str, float]:
    """The strongest role and its confidence, for display and provenance."""
    if not roles:
        return "neutral", 0.0
    name = max(roles.items(), key=lambda item: (item[1], item[0]))
    return name[0], name[1]


def _measured_section_rank(
    sections: Sequence[Dict[str, Any]],
    tension: Any,
) -> List[Tuple[int, float]]:
    """Rank sections by measured tension, strongest first.

    Section *names* are largely positional in the shipped analyser — verse and
    chorus alternate by index, not by measurement. Ranking by what the audio
    actually does recovers the ordering the names were supposed to carry, and
    is what lets the plan put the climax where the song peaks rather than where
    the label says "drop".
    """
    ranked: List[Tuple[int, float]] = []
    for index, section in enumerate(sections or []):
        try:
            start = float(section.get("start", 0.0))
            end = float(section.get("end", 0.0))
        except (TypeError, ValueError):
            continue
        if end <= start:
            continue
        ranked.append((index, float(tension.mean_between(start, end)) if tension else 0.5))
    ranked.sort(key=lambda item: (-item[1], item[0]))
    return ranked


def build_narrative_plan(
    sections: Sequence[Dict[str, Any]],
    duration: float,
    tension: Any = None,
    lyrics: Any = None,
    hook_window: Optional[Tuple[float, float]] = None,
) -> NarrativePlan:
    """Lay a narrative arc over the track from the evidence available.

    The arc is anchored on three things, in descending order of reliability:

    1. the measured tension curve, which says where the song actually peaks and
       where it empties out;
    2. the section map, which says where the arrangement turns over;
    3. lyric evidence, when its confidence clears
       :data:`lyric_analysis.MIN_INTERPRETATION_CONFIDENCE` — a shift in
       emotional valence between sections is a real narrative turn, and where
       the hook line recurs is where the song's identity lives.

    Each stage records which of those actually placed it. A plan built from
    sections alone is reported at low confidence rather than presented as if it
    understood the song.
    """
    duration = float(duration) if duration and np.isfinite(duration) else 0.0
    diagnostics: Dict[str, Any] = {"evidence": []}
    if duration <= 0:
        return NarrativePlan((), 0.0, {"verdict": "no_duration"})

    ordered = [
        dict(section)
        for section in (sections or [])
        if section and float(section.get("end", 0.0)) > float(section.get("start", 0.0))
    ]
    ordered.sort(key=lambda section: float(section["start"]))
    if not ordered:
        ordered = [{"type": "verse", "start": 0.0, "end": duration}]

    has_tension = tension is not None and getattr(tension, "values", np.asarray([])).size > 0
    if has_tension:
        diagnostics["evidence"].append("tension_curve")
    lyric_usable = bool(lyrics is not None and getattr(lyrics, "can_interpret", False))
    if lyric_usable:
        diagnostics["evidence"].append("lyrics")
    if len(ordered) > 1:
        diagnostics["evidence"].append("sections")

    ranked = _measured_section_rank(ordered, tension if has_tension else None)
    peak_index = ranked[0][0] if ranked else len(ordered) // 2
    peak_section = ordered[peak_index]

    # Where the hook lives. Preference order: an explicitly supplied window,
    # the strongest hook-labelled section, then the measured peak.
    if hook_window and hook_window[1] > hook_window[0]:
        hook_start, hook_end = float(hook_window[0]), float(hook_window[1])
        hook_evidence = "supplied_hook"
    else:
        hook_like = [
            index
            for index, _score in ranked
            if str(ordered[index].get("type", "")) in HOOK_LIKE_SECTIONS
        ]
        chosen = hook_like[0] if hook_like else peak_index
        hook_start = float(ordered[chosen]["start"])
        hook_end = float(ordered[chosen]["end"])
        hook_evidence = "hook_section" if hook_like else "measured_peak"
    diagnostics["hookEvidence"] = hook_evidence
    diagnostics["hookWindow"] = [round(hook_start, 3), round(hook_end, 3)]

    climax_start = float(peak_section["start"])
    climax_end = float(peak_section["end"])

    # A narrative turn is a place the song changes direction. With trustworthy
    # lyrics that is where emotional valence flips; without them it is the
    # largest downward step in measured tension before the climax.
    turn_time: Optional[float] = None
    turn_evidence = ""
    if lyric_usable:
        previous_valence: Optional[float] = None
        for line in getattr(lyrics, "lines", ()):
            if line.start is None or line.interpretation_confidence < 0.45:
                continue
            if previous_valence is not None and abs(line.valence - previous_valence) > 0.8:
                if line.start < climax_start:
                    turn_time = float(line.start)
                    turn_evidence = "lyric_valence_shift"
            previous_valence = line.valence
    if turn_time is None and has_tension and len(ordered) >= 3:
        drops: List[Tuple[float, float]] = []
        for index in range(1, len(ordered)):
            boundary = float(ordered[index]["start"])
            if boundary >= climax_start:
                break
            before = tension.mean_between(boundary - 6.0, boundary)
            after = tension.mean_between(boundary, boundary + 6.0)
            drops.append((before - after, boundary))
        if drops:
            best = max(drops, key=lambda item: item[0])
            if best[0] > 0.08:
                turn_time = best[1]
                turn_evidence = "tension_drop"

    stages: List[NarrativeStage] = []

    def add(
        name: str,
        start: float,
        end: float,
        confidence: float,
        evidence: Sequence[str],
    ) -> None:
        start = max(0.0, min(duration, float(start)))
        end = max(0.0, min(duration, float(end)))
        if end - start < 0.35:
            return
        intensity = float(tension.mean_between(start, end)) if has_tension else 0.5
        stages.append(
            NarrativeStage(
                name=name,
                start=start,
                end=end,
                roles=STAGE_ROLE_PREFERENCE.get(name, ("neutral",)),
                motif_tolerance=STAGE_MOTIF_TOLERANCE.get(name, 0.25),
                intensity=intensity,
                confidence=max(0.0, min(1.0, confidence)),
                evidence=tuple(evidence),
            )
        )

    first_end = float(ordered[0]["end"])
    opening_span = min(first_end, max(1.5, duration * 0.03))
    add("opening_image", 0.0, opening_span, 0.7, ("track_start",))
    add("establish", opening_span, first_end, 0.6, ("first_section",))

    body_start = first_end
    body_end = min(hook_start, climax_start)
    if body_end > body_start:
        span = body_end - body_start
        # Introduce → theme → setup → escalate, weighted so the run-up spends
        # most of its time on setup and escalation rather than on introduction.
        marks = [0.0, 0.22, 0.48, 0.76, 1.0]
        names = ("introduce", "theme", "setup", "escalate")
        for index, name in enumerate(names):
            add(
                name,
                body_start + span * marks[index],
                body_start + span * marks[index + 1],
                0.5 if not lyric_usable else 0.65,
                ("run_up",) + (("lyrics",) if lyric_usable else ()),
            )

    if turn_time is not None and body_start < turn_time < climax_start:
        # Re-cut the stage containing the turn so the turn gets its own beat.
        stages = [stage for stage in stages if not (stage.start <= turn_time < stage.end)]
        add("turn", turn_time, min(turn_time + max(2.0, duration * 0.04), climax_start), 0.6, (turn_evidence,))

    if hook_end > hook_start:
        add(
            "hook_identity",
            hook_start,
            hook_end,
            0.75 if hook_evidence != "measured_peak" else 0.55,
            (hook_evidence,),
        )

    if climax_end > climax_start and not (hook_start <= climax_start < hook_end):
        add("climax", climax_start, climax_end, 0.7 if has_tension else 0.4, ("measured_peak",))

    tail_start = max(climax_end, hook_end)
    if tail_start < duration:
        remaining = duration - tail_start
        add("release", tail_start, tail_start + remaining * 0.35, 0.5, ("post_peak",))
        add("resolution", tail_start + remaining * 0.35, tail_start + remaining * 0.8, 0.5, ("post_peak",))
        add("final_image", tail_start + remaining * 0.8, duration, 0.7, ("track_end",))

    stages.sort(key=lambda stage: stage.start)

    # Chain the stages so they tile the track: a gap means a cut lands in no
    # stage at all and silently loses its narrative role.
    chained: List[NarrativeStage] = []
    for index, stage in enumerate(stages):
        end = stages[index + 1].start if index + 1 < len(stages) else duration
        if end <= stage.start:
            continue
        chained.append(stage._replace(end=end))
    if chained:
        chained[0] = chained[0]._replace(start=0.0)
        chained[-1] = chained[-1]._replace(end=duration)

    evidence_score = 0.0
    if has_tension:
        evidence_score += 0.4
    if len(ordered) > 1:
        evidence_score += 0.25
    if lyric_usable:
        evidence_score += 0.25
    if hook_evidence != "measured_peak":
        evidence_score += 0.1
    diagnostics["stageCount"] = len(chained)
    diagnostics["turnEvidence"] = turn_evidence or "none"

    return NarrativePlan(tuple(chained), min(1.0, evidence_score), diagnostics)


class MotifLedger:
    """Tracks which images the video has already used, and why a return is allowed.

    Repetition is not automatically a defect — a music video that never returns
    to its central image has no identity. What makes repetition a defect is
    being *unjustified*. The ledger therefore records every appearance with the
    stage it happened in, and answers one question: may this thing come back
    here, and on what grounds?

    Three grounds are accepted, and every accepted return stores which one it
    was so a reviewer can audit the choice:

    * ``hook_callback``  — the stage is the hook or the final image, where
      returning to an established image is the point;
    * ``lyric_callback`` — a repeated lyric line is sounding, so the image is
      answering a repeat in the song;
    * ``structural``     — the same section type has come round again and the
      library is too small to fill it with anything new.
    """

    def __init__(self) -> None:
        self.appearances: Dict[str, List[Dict[str, Any]]] = {}
        self.accepted: List[Dict[str, Any]] = []

    def record(self, key: str, time_value: float, stage: str, cut_index: int) -> None:
        self.appearances.setdefault(key, []).append(
            {"time": round(float(time_value), 4), "stage": stage, "cutIndex": int(cut_index)}
        )

    def count(self, key: str) -> int:
        return len(self.appearances.get(key, []))

    def last_time(self, key: str) -> Optional[float]:
        entries = self.appearances.get(key)
        return entries[-1]["time"] if entries else None

    def justify(
        self,
        key: str,
        stage: Optional[NarrativeStage],
        time_value: float,
        lyric_is_hook: bool = False,
        library_exhausted: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """Return the justification for repeating ``key`` here, or ``None``.

        ``None`` is the common answer and is what keeps accidental repeats out.
        A caller that gets ``None`` must choose something else or, if it truly
        cannot, record the repeat as unjustified so the review package shows it
        rather than hiding it.
        """
        if self.count(key) == 0:
            return None
        stage_name = stage.name if stage else "unknown"
        tolerance = stage.motif_tolerance if stage else 0.25

        if lyric_is_hook:
            reason = "lyric_callback"
        elif stage_name in ("hook_identity", "final_image", "resolution") and tolerance >= 0.45:
            reason = "hook_callback"
        elif library_exhausted:
            reason = "structural"
        else:
            return None

        previous = self.last_time(key)
        return {
            "reason": reason,
            "stage": stage_name,
            "priorAppearances": self.count(key),
            "previousTime": previous,
            "gapSeconds": round(float(time_value) - float(previous), 3) if previous is not None else None,
            "motifTolerance": round(tolerance, 3),
        }

    def accept(self, key: str, justification: Dict[str, Any]) -> None:
        self.accepted.append(dict(justification, key=key))

    def as_dict(self) -> Dict[str, Any]:
        return {
            "distinctImages": len(self.appearances),
            "acceptedMotifs": len(self.accepted),
            "motifs": self.accepted[:64],
        }


def role_affinity(stage: Optional[NarrativeStage], roles: Dict[str, float]) -> float:
    """Score 0..1 for how well a clip's roles serve a stage's needs.

    Ranked rather than binary: a stage asking for ``establishing`` is best
    served by an establishing shot, acceptably served by an environment beat,
    and poorly served by a tight reaction. Returning a graded number is what
    lets the selector trade role fit against everything else instead of
    filtering the library down to nothing.
    """
    if stage is None or not roles:
        return 0.5
    preferences = stage.roles or ("neutral",)
    best = 0.0
    for rank, role in enumerate(preferences):
        confidence = roles.get(role, 0.0)
        if confidence <= 0.0:
            continue
        positional = 1.0 - rank / max(1, len(preferences))
        best = max(best, confidence * (0.55 + 0.45 * positional))
    if best <= 0.0:
        # No preferred role at all. Neutral coverage is not a failure, it is
        # just uninformative, so it lands mid-scale rather than at zero.
        return 0.35 * roles.get("neutral", 0.0) / 0.3
    return float(min(1.0, best))
