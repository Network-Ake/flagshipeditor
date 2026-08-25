"""AI shot selection — plans the cut grid and picks the best clip for each cut.

Two responsibilities live here:

* ``plan_cuts`` turns the beat grid, the section map and the style's
  ``cut_strategy`` into concrete ``(start, end, section)`` slots that tile the
  whole track without gaps or overlaps.
* ``select_best_clips`` scores the analysed clips against every slot on six
  criteria, weighted by what the section calls for, and assigns one clip per
  cut under a hard no-repeat rule.

The planner is fully deterministic: the same beats, sections and clips always
produce the same edit. Musical intent lives in three places — section
boundaries are non-negotiable cut points, each section type has its own cut
rate in beats, and a drop follows the bass onsets rather than a metronome.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

# Weight profiles per section. A verse wants the artist on screen, a drop wants
# motion, an intro or bridge wants atmosphere.
SECTION_WEIGHTS: Dict[str, Dict[str, float]] = {
    "intro": {
        "composition": 0.30,
        "energy": 0.10,
        "variety": 0.20,
        "sharpness": 0.20,
        "stability": 0.15,
        "face_quality": 0.05,
    },
    "verse": {
        "composition": 0.20,
        "energy": 0.15,
        "variety": 0.15,
        "sharpness": 0.15,
        "stability": 0.10,
        "face_quality": 0.25,
    },
    "chorus": {
        "composition": 0.20,
        "energy": 0.30,
        "variety": 0.20,
        "sharpness": 0.15,
        "stability": 0.05,
        "face_quality": 0.10,
    },
    "drop": {
        "composition": 0.15,
        "energy": 0.35,
        "variety": 0.25,
        "sharpness": 0.15,
        "stability": 0.05,
        "face_quality": 0.05,
    },
    "bridge": {
        "composition": 0.30,
        "energy": 0.10,
        "variety": 0.20,
        "sharpness": 0.20,
        "stability": 0.15,
        "face_quality": 0.05,
    },
    "outro": {
        "composition": 0.30,
        "energy": 0.10,
        "variety": 0.20,
        "sharpness": 0.20,
        "stability": 0.15,
        "face_quality": 0.05,
    },
}

DEFAULT_WEIGHTS: Dict[str, float] = {
    "composition": 0.25,
    "energy": 0.20,
    "variety": 0.20,
    "sharpness": 0.15,
    "stability": 0.10,
    "face_quality": 0.10,
}

# Scene types a section prefers, best first. Used as a soft bonus rather than a
# hard filter so a short library still fills the timeline.
SECTION_SCENE_AFFINITY: Dict[str, Sequence[str]] = {
    "intro": ("b_roll_static", "b_roll_low_light", "b_roll"),
    "verse": ("performance", "close_up", "b_roll_with_face"),
    "chorus": ("close_up", "performance", "b_roll_with_face", "b_roll_dynamic"),
    "drop": ("b_roll_dynamic", "close_up", "performance"),
    "bridge": ("b_roll_static", "b_roll_low_light", "b_roll"),
    "outro": ("b_roll_static", "b_roll", "performance"),
}

AFFINITY_BONUS = 12.0
SHORT_CLIP_PENALTY = 15.0
OVERUSE_PENALTY = 3.0
REPEAT_WINDOW = 4  # A clip may not come back within this many consecutive cuts.
MIN_CUT_SECONDS = 0.15  # Below this a cut reads as a flash frame, not an edit.
MIN_SECTION_SECONDS = 1.0  # Shorter segments are merged into their neighbour.
MAX_CUTS = 20000
_DEDUPE_TOLERANCE = 0.012  # Two cut candidates this close are the same edit.

# How much a cut candidate is worth when two of them are too close together to
# both survive. A section change outranks everything; inside a drop a played
# bass hit outranks the metronome, so a syncopated 808 keeps its own edit
# instead of being crushed by the grid cut that happens to precede it.
_CUT_GRID = 0
_CUT_ONSET = 1
_CUT_BOUNDARY = 2

# Cut rate per section type, expressed in beats between cuts. A style preset can
# override any of these through ``cut_strategy``.
SECTION_CUT_BEATS: Dict[str, float] = {
    "intro": 4.0,  # let the opening breathe
    "verse": 4.0,  # downbeats only — one cut per bar
    "chorus": 1.0,  # every beat
    "drop": 1.0,  # baseline; the bass onsets drive the real pattern
    "bridge": 2.0,
    "outro": 4.0,
}

# Longest a single cut may run, in beats, before it is subdivided. Keeps a
# sparse beat grid or a long tail from parking one clip on screen forever.
SECTION_MAX_BEATS: Dict[str, float] = {
    "intro": 8.0,
    "verse": 8.0,
    "chorus": 2.0,
    "drop": 2.0,
    "bridge": 4.0,
    "outro": 8.0,
}

DEFAULT_CUT_BEATS = 1.0
DEFAULT_MAX_BEATS = 4.0


def bounded_score(value: Any, default: float = 50.0) -> float:
    """Coerce a score to the public 0..100 contract."""
    try:
        numeric = float(value)
        if not np.isfinite(numeric):
            return float(default)
        return max(0.0, min(100.0, numeric))
    except (TypeError, ValueError):
        return float(default)


def bounded_duration(value: Any) -> float:
    """Return a clip duration in seconds, or 0.0 when it is unknown."""
    try:
        duration = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not np.isfinite(duration) or duration <= 0:
        return 0.0
    return duration


def histogram_distance(first: Any, second: Any) -> float:
    """Return normalized histogram distance: 0 identical, 100 maximally different."""
    try:
        # ``np.array`` copies, so normalising below cannot mutate a caller's
        # cached histogram in place.
        left = np.array(first, dtype=np.float64).reshape(-1)
        right = np.array(second, dtype=np.float64).reshape(-1)
        if left.size == 0 or left.size != right.size:
            return 50.0
        left_total = float(left.sum())
        right_total = float(right.sum())
        if left_total <= 0 or right_total <= 0:
            return 50.0
        left /= left_total
        right /= right_total
        return max(0.0, min(100.0, float(np.abs(left - right).sum()) * 50.0))
    except (TypeError, ValueError):
        return 50.0


def face_quality_score(clip_info: Dict[str, Any]) -> float:
    """Score a detected face by how close it sits to a flattering framing."""
    try:
        face_ratio = float(clip_info.get("face_size_ratio", 0) or 0)
    except (TypeError, ValueError):
        face_ratio = 0.0
    if not np.isfinite(face_ratio):
        face_ratio = 0.0
    size_score = 100.0 - abs(face_ratio - 0.15) * 500.0
    return max(0.0, min(100.0, size_score))


def section_affinity(
    section_type: str,
    style_config: Optional[Dict[str, Any]] = None,
) -> Sequence[str]:
    """Return the scene types a section prefers, honouring a style override.

    A preset can carry ``"scene_affinity": {"chorus": ["close_up"]}`` to steer a
    look without touching the scoring weights.
    """
    overrides = (style_config or {}).get("scene_affinity") or {}
    override = overrides.get(section_type)
    if isinstance(override, (list, tuple)) and override:
        return tuple(str(entry) for entry in override)
    return SECTION_SCENE_AFFINITY.get(section_type, ())


def score_clip(
    clip_info: Dict[str, Any],
    prev_clip_info: Optional[Dict[str, Any]] = None,
    section_type: str = "",
    affinity: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Score a single clip on six criteria and return the weighted composite.

    ``energy`` blends average motion with motion variance, so a clip whose
    movement builds or breaks scores above one that pans at a constant rate.
    ``stability`` reads the brightness jitter measured during clip analysis, and
    ``face_quality`` rewards a face that is present in most frames rather than
    one that flashes through a single sample.
    """
    scores: Dict[str, float] = {}
    scores["composition"] = bounded_score(clip_info.get("composition_score"), 50)

    motion_intensity = bounded_score(clip_info.get("motion_intensity", 0), 0)
    motion_variance = bounded_score(clip_info.get("motion_variance", 0), 0)
    scores["energy"] = min(100.0, motion_intensity * 0.6 + motion_variance * 3.0)

    if prev_clip_info and clip_info.get("histogram") and prev_clip_info.get("histogram"):
        scores["variety"] = histogram_distance(clip_info["histogram"], prev_clip_info["histogram"])
    else:
        scores["variety"] = 80.0

    scores["sharpness"] = bounded_score(clip_info.get("sharpness_score"), 50)
    scores["stability"] = bounded_score(clip_info.get("brightness_stability", 100), 100)

    if clip_info.get("has_face"):
        face_consistency = bounded_score(clip_info.get("face_consistency", 0.0) * 100.0, 0.0)
        scores["face_quality"] = min(
            100.0, face_quality_score(clip_info) + face_consistency * 0.2
        )
    else:
        scores["face_quality"] = 50.0

    weights = SECTION_WEIGHTS.get(section_type, DEFAULT_WEIGHTS)
    composite = sum(scores[key] * weights.get(key, 0.0) for key in scores)

    preferred = list(affinity) if affinity is not None else list(section_affinity(section_type))
    scene_type = str(clip_info.get("scene_type", "unknown"))
    if scene_type in preferred:
        rank = preferred.index(scene_type)
        composite += AFFINITY_BONUS * (1.0 - rank / max(1, len(preferred)))

    return {
        "scores": scores,
        "composite": max(0.0, min(100.0, composite)),
        "clipPath": str(clip_info.get("path", "")),
        "clipName": str(clip_info.get("name", "")),
        "thumbnailId": str(clip_info.get("thumbnail_id", "")),
        "sceneType": scene_type,
    }


def _parse_cut_interval(raw: Any, default: Optional[float] = 1.0) -> Optional[float]:
    """Parse a ``cut_interval`` such as ``"0.25_beat"`` into a beat count."""
    if raw is None:
        return default
    text = str(raw).strip().lower()
    if text.endswith("_beat"):
        text = text[: -len("_beat")]
    elif text.endswith("_beats"):
        text = text[: -len("_beats")]
    try:
        value = float(text)
    except ValueError:
        return default
    if not np.isfinite(value) or value <= 0:
        return default
    return max(0.0625, min(64.0, value))


def _beat_position(beats: Sequence[float], index: float, fallback_period: float) -> float:
    """Return the time at a fractional beat index, interpolating between beats."""
    if not beats:
        return index * fallback_period
    if index <= 0:
        return float(beats[0]) + index * fallback_period
    last = len(beats) - 1
    if index >= last:
        return float(beats[last]) + (index - last) * fallback_period
    lower = int(np.floor(index))
    upper = min(lower + 1, last)
    ratio = index - lower
    return float(beats[lower]) + (float(beats[upper]) - float(beats[lower])) * ratio


def _median_beat_period(beats: Sequence[float], tempo: float) -> float:
    """Estimate one beat in seconds from the grid, falling back to the tempo."""
    if len(beats) >= 2:
        deltas = np.diff(np.asarray(beats, dtype=np.float64))
        deltas = deltas[deltas > 0]
        if deltas.size:
            return float(np.median(deltas))
    if tempo and tempo > 0:
        return 60.0 / float(tempo)
    return 0.5


def _clean_times(values: Optional[Sequence[Any]]) -> List[float]:
    """Coerce a time list to sorted finite floats, dropping anything unusable."""
    cleaned: List[float] = []
    for value in values or []:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if np.isfinite(number) and number >= 0.0:
            cleaned.append(number)
    cleaned.sort()
    return cleaned


def normalize_sections(
    sections: Sequence[Dict[str, Any]],
    duration: float,
) -> List[Dict[str, Any]]:
    """Return contiguous, ordered sections that cover ``[0, duration]`` exactly.

    Segmentation output is noisy: sections overlap, leave holes, run past the
    end of the track, or last a tenth of a second. Cutting against that produces
    holes in the timeline and one-frame "sections", so the grid is repaired
    before a single cut is planned. Every returned section starts where the
    previous one ends, which is what makes a boundary cut meaningful.
    """
    duration = float(duration)
    if duration <= 0:
        return []

    parsed: List[Dict[str, Any]] = []
    for section in sections or []:
        if not section:
            continue
        try:
            start = float(section.get("start", 0.0))
            end = float(section.get("end", 0.0))
        except (TypeError, ValueError):
            continue
        if not (np.isfinite(start) and np.isfinite(end)):
            continue
        start = max(0.0, min(duration, start))
        end = max(0.0, min(duration, end))
        if end <= start:
            continue
        parsed.append({"type": str(section.get("type", "verse")), "start": start, "end": end})

    if not parsed:
        return [{"type": "verse", "start": 0.0, "end": duration}]

    parsed.sort(key=lambda entry: (entry["start"], entry["end"]))

    # Chain the sections: each one ends where the next begins, so overlaps and
    # holes both disappear in a single pass.
    chained: List[Dict[str, Any]] = []
    for section in parsed:
        if chained and section["start"] < chained[-1]["end"]:
            section = dict(section, start=chained[-1]["end"])
            if section["end"] <= section["start"]:
                continue
        chained.append(dict(section))
    if not chained:
        return [{"type": "verse", "start": 0.0, "end": duration}]

    chained[0]["start"] = 0.0
    chained[-1]["end"] = duration
    for index in range(len(chained) - 1):
        chained[index]["end"] = chained[index + 1]["start"]

    # Absorb slivers that are too short to hold even one cut.
    merged: List[Dict[str, Any]] = []
    for section in chained:
        if section["end"] - section["start"] < MIN_SECTION_SECONDS and merged:
            merged[-1]["end"] = section["end"]
            continue
        merged.append(section)
    if not merged:
        return [{"type": "verse", "start": 0.0, "end": duration}]
    if len(merged) > 1 and merged[0]["end"] - merged[0]["start"] < MIN_SECTION_SECONDS:
        merged[1]["start"] = merged[0]["start"]
        merged.pop(0)
    merged[0]["start"] = 0.0
    merged[-1]["end"] = duration
    return merged


def get_section_boundary_times(sections: Sequence[Dict[str, Any]]) -> List[float]:
    """Extract the section start times where a cut MUST happen.

    A section transition (verse to chorus, chorus to drop) is the one edit the
    viewer feels whether or not it lands on a beat, so it is never optional.
    """
    boundaries = {
        round(float(section.get("start", 0.0)), 6)
        for section in (sections or [])
        if section is not None
    }
    return sorted(boundaries)


def get_cut_interval_for_section(
    section_type: str,
    style_config: Optional[Dict[str, Any]] = None,
) -> float:
    """Return how many beats pass between cuts in this section type.

    Defaults follow the arrangement: an intro or outro holds a shot for a full
    bar, a verse cuts on downbeats, a chorus cuts every beat, and a drop starts
    from every beat before the bass onsets subdivide it further. A style preset
    overrides any of them with ``cut_strategy.<section>.cut_interval``.
    """
    fallback = SECTION_CUT_BEATS.get(section_type, DEFAULT_CUT_BEATS)
    cut_strategy = (style_config or {}).get("cut_strategy") or {}
    strategy = cut_strategy.get(section_type) or {}
    if not isinstance(strategy, dict):
        return fallback
    interval = _parse_cut_interval(strategy.get("cut_interval"), None)
    return fallback if interval is None else interval


def _max_beats_for_section(
    section_type: str,
    interval_beats: float,
    style_config: Optional[Dict[str, Any]] = None,
) -> float:
    """Return the longest a cut may run in this section, in beats."""
    cut_strategy = (style_config or {}).get("cut_strategy") or {}
    strategy = cut_strategy.get(section_type) or {}
    if isinstance(strategy, dict):
        override = _parse_cut_interval(strategy.get("max_cut_interval"), None)
        if override is not None:
            return max(override, interval_beats)
    default = SECTION_MAX_BEATS.get(section_type, DEFAULT_MAX_BEATS)
    return max(default, interval_beats * 2.0)


def _snap_to_beat(time_value: float, beats: Sequence[float], tolerance: float) -> float:
    """Pull a time onto the beat grid when it is a near miss, else leave it.

    A bass onset detected 30 ms early is the same musical event as the beat; one
    that lands halfway between beats is a syncopation worth cutting on as-is.
    """
    if not beats or tolerance <= 0:
        return time_value
    array = np.asarray(beats, dtype=np.float64)
    index = int(np.searchsorted(array, time_value, side="left"))
    best = time_value
    best_delta = tolerance
    for candidate_index in (index - 1, index):
        if 0 <= candidate_index < array.size:
            delta = abs(float(array[candidate_index]) - time_value)
            if delta <= best_delta:
                best_delta = delta
                best = float(array[candidate_index])
    return best


def _section_beat_indices(beats: Sequence[float], start: float, end: float) -> Tuple[int, int]:
    """Return the half-open index range of beats inside ``[start, end)``."""
    if not beats:
        return 0, 0
    array = np.asarray(beats, dtype=np.float64)
    first = int(np.searchsorted(array, start, side="left"))
    last = int(np.searchsorted(array, end, side="left"))
    return first, last


def _section_cut_candidates(
    section: Dict[str, Any],
    beats: Sequence[float],
    onsets: Sequence[float],
    period: float,
    style_config: Dict[str, Any],
) -> List[Tuple[float, int]]:
    """Return ``(time, priority)`` cut candidates for one section.

    The section start is always emitted at ``_CUT_BOUNDARY``. What follows
    depends on the section type: a drop follows its bass onsets, everything else
    walks the beat grid at the section's cut interval.
    """
    section_type = str(section.get("type", "verse"))
    start = float(section["start"])
    end = float(section["end"])
    interval_beats = get_cut_interval_for_section(section_type, style_config)

    candidates: List[Tuple[float, int]] = [(start, _CUT_BOUNDARY)]

    first_index, last_index = _section_beat_indices(beats, start, end)
    section_beats = list(beats[first_index:last_index])

    if section_beats:
        # Anchor the bar count to the first beat of the section: a section
        # boundary is a downbeat, so "every 4th beat" means every bar here.
        position = 0.0
        limit = float(last_index - first_index)
        while position < limit:
            candidates.append((_beat_position(beats, first_index + position, period), _CUT_GRID))
            position += interval_beats
    else:
        # No beat landed in this section — fall back to a metronome from tempo.
        step = max(MIN_CUT_SECONDS, interval_beats * period)
        time_value = start + step
        while time_value < end:
            candidates.append((time_value, _CUT_GRID))
            time_value += step

    if section_type == "drop" and onsets:
        # A drop keeps the steady pulse above and adds a cut on every bass hit,
        # so a syncopated 808 lands on its own edit instead of being rounded
        # away. Near misses are quantised onto the beat; real syncopation is
        # kept where it was played.
        snap_tolerance = min(0.08, period * 0.25)
        strategy = ((style_config or {}).get("cut_strategy") or {}).get(section_type) or {}
        double_time = bool(isinstance(strategy, dict) and strategy.get("double_time_on_808"))
        half_step = interval_beats * period * 0.5
        for onset in onsets:
            if not (start <= onset < end):
                continue
            snapped = _snap_to_beat(onset, section_beats, snap_tolerance)
            candidates.append((snapped, _CUT_ONSET))
            if double_time and half_step >= MIN_CUT_SECONDS:
                offbeat = snapped + half_step
                if offbeat < end:
                    candidates.append((offbeat, _CUT_GRID))

    return [(time_value, priority) for time_value, priority in candidates if start <= time_value < end]


def _dedupe_times(candidates: List[Tuple[float, str, int]]) -> List[Tuple[float, str, int]]:
    """Collapse candidates that describe the same edit, keeping the strongest.

    A bass onset quantised onto the beat lands on a grid candidate that is
    already there; the two are one edit, and the survivor keeps the higher
    priority so the later spacing pass knows the 808 was played here.
    """
    ordered = sorted(candidates, key=lambda entry: (entry[0], -entry[2]))
    deduped: List[Tuple[float, str, int]] = []
    for time_value, section_type, priority in ordered:
        if deduped and time_value - deduped[-1][0] <= _DEDUPE_TOLERANCE:
            previous_time, previous_section, previous_priority = deduped[-1]
            if priority > previous_priority:
                deduped[-1] = (time_value, section_type, priority)
            continue
        deduped.append((time_value, section_type, priority))
    return deduped


def _enforce_min_spacing(
    candidates: List[Tuple[float, str, int]],
    min_gap: float,
) -> List[Tuple[float, str, int]]:
    """Drop cuts that would produce a sub-``min_gap`` slot, weakest first.

    Cuts are removed rather than shortened, so the surviving cut simply runs
    longer and the timeline stays gap-free. When two cuts crowd each other the
    higher-priority one wins: a section boundary evicts an ordinary cut, and a
    bass onset evicts the grid tick next to it. Evicting can uncover a third cut
    that is now too close, so the walk back continues until the spacing holds.
    """
    kept: List[Tuple[float, str, int]] = []
    for entry in candidates:
        time_value, _section_type, priority = entry
        while kept and time_value - kept[-1][0] < min_gap and priority > kept[-1][2]:
            kept.pop()
        if not kept:
            kept.append(entry)
            continue
        if time_value - kept[-1][0] >= min_gap:
            kept.append(entry)
        elif priority == _CUT_BOUNDARY and kept[-1][2] == _CUT_BOUNDARY:
            # Two boundaries this close cannot happen after normalize_sections,
            # but honour both rather than silently losing a section.
            kept.append(entry)
    return kept


def _subdivide_long_slots(
    candidates: List[Tuple[float, str, int]],
    end_time: float,
    beats: Sequence[float],
    period: float,
    style_config: Dict[str, Any],
) -> List[Tuple[float, str, int]]:
    """Split any slot that outruns its section's maximum cut length.

    Splitting beats truncating: a truncated slot leaves the timeline empty until
    the next cut, whereas an extra cut keeps the edit continuous.
    """
    if not candidates:
        return candidates
    expanded: List[Tuple[float, str, int]] = []
    for index, entry in enumerate(candidates):
        expanded.append(entry)
        time_value, section_type, _priority = entry
        slot_end = candidates[index + 1][0] if index + 1 < len(candidates) else end_time
        length = slot_end - time_value
        interval_beats = get_cut_interval_for_section(section_type, style_config)
        max_seconds = _max_beats_for_section(section_type, interval_beats, style_config) * period
        if max_seconds <= 0 or length <= max_seconds + 1e-6:
            continue
        pieces = int(np.ceil(length / max_seconds))
        if pieces < 2 or length / pieces < MIN_CUT_SECONDS:
            continue
        step = length / pieces
        snap_tolerance = min(step * 0.25, period * 0.25)
        previous = time_value
        for piece in range(1, pieces):
            split = _snap_to_beat(time_value + step * piece, beats, snap_tolerance)
            if split - previous < MIN_CUT_SECONDS or slot_end - split < MIN_CUT_SECONDS:
                continue
            expanded.append((split, section_type, _CUT_GRID))
            previous = split
    expanded.sort(key=lambda item: item[0])
    return expanded


def _absorb_runt_tails(
    candidates: List[Tuple[float, str, int]],
    end_time: float,
    period: float,
    style_config: Dict[str, Any],
) -> List[Tuple[float, str, int]]:
    """Remove a cut whose slot is a stub against the next section boundary.

    A section rarely divides evenly by its cut interval, which leaves a runt at
    the tail — a quarter-second flash right before the transition. Dropping that
    cut lets the previous shot ride into the boundary, which is what an editor
    does. Boundary cuts themselves are never removed.
    """
    if len(candidates) < 2:
        return candidates
    kept: List[Tuple[float, str, int]] = [candidates[0]]
    for index in range(1, len(candidates)):
        time_value, section_type, priority = candidates[index]
        if priority == _CUT_BOUNDARY:
            kept.append(candidates[index])
            continue
        slot_end = candidates[index + 1][0] if index + 1 < len(candidates) else end_time
        interval_seconds = get_cut_interval_for_section(section_type, style_config) * period
        if slot_end - time_value < interval_seconds * 0.5:
            continue
        kept.append(candidates[index])
    return kept


def plan_cuts(
    beats: Sequence[float],
    sections: Sequence[Dict[str, Any]],
    style_config: Dict[str, Any],
    duration: float,
    tempo: float = 0.0,
    bass_onsets: Optional[Sequence[float]] = None,
) -> List[Dict[str, Any]]:
    """Turn the beat grid and the style's cut strategy into timed cut slots.

    The rules, in the order they are applied:

    * every section boundary is a cut, whether or not a beat lands there;
    * a drop cuts on its bass onsets, quantised onto the beat when they are a
      near miss, so the edit follows the 808 rather than a metronome;
    * every other section walks the beat grid at its own interval — one cut per
      bar in a verse, one per beat in a chorus, one per bar in intro and outro;
    * no slot is shorter than ``MIN_CUT_SECONDS`` or longer than its section's
      maximum, and the slots tile ``[0, duration]`` with no gap or overlap.

    Every slot carries a start and an end, so After Effects can trim each clip.
    """
    duration = float(duration) if np.isfinite(duration) else 0.0
    if duration <= 0:
        return []

    beat_times = _clean_times(beats)
    period = _median_beat_period(beat_times, tempo)
    if not np.isfinite(period) or period <= 0:
        period = 0.5
    onsets = _clean_times(bass_onsets)
    style_config = style_config or {}

    ordered_sections = normalize_sections(sections, duration)
    if not ordered_sections:
        return []

    candidates: List[Tuple[float, str, int]] = []
    for section in ordered_sections:
        section_type = str(section.get("type", "verse"))
        for time_value, priority in _section_cut_candidates(
            section, beat_times, onsets, period, style_config
        ):
            candidates.append((time_value, section_type, priority))

    if not candidates:
        return []

    candidates = _dedupe_times(candidates)
    candidates = _enforce_min_spacing(candidates, MIN_CUT_SECONDS)
    candidates = _subdivide_long_slots(
        candidates, duration, beat_times, period, style_config
    )
    candidates = _dedupe_times(candidates)
    candidates = _enforce_min_spacing(candidates, MIN_CUT_SECONDS)
    candidates = _absorb_runt_tails(candidates, duration, period, style_config)

    if len(candidates) > MAX_CUTS:
        candidates = candidates[:MAX_CUTS]

    slots: List[Dict[str, Any]] = []
    for index, (time_value, section_type, _priority) in enumerate(candidates):
        slot_end = candidates[index + 1][0] if index + 1 < len(candidates) else duration
        if slot_end - time_value < MIN_CUT_SECONDS:
            continue
        slots.append(
            {
                "beatTime": round(float(time_value), 6),
                "endTime": round(float(slot_end), 6),
                "sectionType": section_type,
            }
        )
    return slots


def _has_onset_between(onsets: Sequence[float], start: float, end: float) -> bool:
    """Return True when a bass onset falls inside the half-open window."""
    if not onsets:
        return False
    index = int(np.searchsorted(np.asarray(onsets), start, side="left"))
    return index < len(onsets) and onsets[index] < end


def filter_clips_for_section(
    clips: Sequence[Dict[str, Any]],
    section_type: str,
    style_config: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Return the clips a section prefers, falling back to everything usable."""
    usable = [
        clip
        for clip in clips
        if clip.get("usable", True) and clip.get("scene_type") != "unknown"
    ]
    affinity = section_affinity(section_type, style_config) or ("performance", "b_roll_dynamic")
    preferred = [clip for clip in usable if clip.get("scene_type") in affinity]
    return preferred or usable


def best_moment_window(
    clip_info: Dict[str, Any],
    slot_length: float,
) -> Tuple[float, float]:
    """Return the ``(source_start, source_end)`` to lift out of a clip.

    Clip analysis records the frame range with the most visual interest. Rather
    than always starting a cut at the head of the file, the slot is centred a
    little ahead of that peak so the moment lands inside the cut instead of at
    its very first frame. The window is clamped to the clip's real extent.
    """
    clip_duration = bounded_duration(clip_info.get("duration"))
    slot_length = max(MIN_CUT_SECONDS, float(slot_length))
    best_moment = clip_info.get("best_moment") or {}
    best_time = 0.0
    if isinstance(best_moment, dict):
        try:
            candidate = float(best_moment.get("best_time", 0.0))
            if np.isfinite(candidate) and candidate >= 0.0:
                best_time = candidate
        except (TypeError, ValueError):
            best_time = 0.0

    if clip_duration <= 0:
        return 0.0, slot_length

    # Put the peak roughly a third of the way into the cut.
    source_start = best_time - slot_length * 0.35
    latest_start = max(0.0, clip_duration - slot_length)
    source_start = max(0.0, min(latest_start, source_start))
    source_end = min(clip_duration, source_start + slot_length)
    return round(source_start, 6), round(source_end, 6)


def _eligible_indices(
    scored: Sequence[Dict[str, Any]],
    recent: Sequence[str],
    preferred: set,
) -> List[int]:
    """Return candidate indices honouring the no-repeat rule as far as possible.

    A clip used in the last ``REPEAT_WINDOW`` cuts is excluded outright rather
    than merely penalised — a penalty still loses to a high enough score, which
    is how the same shot ends up back-to-back. When the library is smaller than
    the window the constraint is relaxed one cut at a time, so a three-clip
    project still alternates instead of failing.
    """
    for window in range(REPEAT_WINDOW, 0, -1):
        blocked = set(recent[-window:])
        allowed = [
            index for index, entry in enumerate(scored) if entry["clipPath"] not in blocked
        ]
        if not allowed:
            continue
        favoured = [index for index in allowed if scored[index]["clipPath"] in preferred]
        return favoured or allowed
    return list(range(len(scored)))


def select_best_clips(
    clips: Sequence[Dict[str, Any]],
    beats: Sequence[float],
    sections: Sequence[Dict[str, Any]],
    style_config: Optional[Dict[str, Any]] = None,
    duration: float = 0.0,
    tempo: float = 0.0,
    bass_onsets: Optional[Sequence[float]] = None,
    seed: int = 1,
) -> List[Dict[str, Any]]:
    """Plan the cut grid and choose the best clip for every slot.

    Selection is deterministic — no sampling, no exploration — so the same
    inputs always yield the same edit and a re-run never reshuffles an approved
    sequence. ``seed`` is accepted for API compatibility and deliberately
    unused.

    Three rules shape the sequence: a clip cannot return within
    ``REPEAT_WINDOW`` cuts, a clip that has already carried several cuts is
    progressively penalised so the library gets used, and ties are broken by
    least-recently-used then by path, which keeps the result stable.

    The result is ordered by time and uses the same camelCase field names the
    After Effects bridge consumes, so no translation layer can drift.
    """
    style_config = style_config or {}
    usable_clips = [clip for clip in clips if clip.get("usable", True)]
    if not usable_clips:
        return []

    if duration <= 0:
        duration = max(
            [float(section.get("end", 0.0)) for section in (sections or [])] or [0.0]
        )
    if duration <= 0 and beats:
        duration = float(max(beats))
    if duration <= 0:
        return []

    slots = plan_cuts(beats, sections, style_config, duration, tempo, bass_onsets)
    if not slots:
        return []

    selections: List[Dict[str, Any]] = []
    recent: List[str] = []
    prev_clip: Optional[Dict[str, Any]] = None
    clips_by_path = {str(clip.get("path", "")): clip for clip in usable_clips}
    preferred_by_section: Dict[str, set] = {}
    clip_usage_count: Dict[str, int] = {str(clip.get("path", "")): 0 for clip in usable_clips}
    last_used_at: Dict[str, int] = {}

    for cut_index, slot in enumerate(slots):
        section_type = slot["sectionType"]
        if section_type not in preferred_by_section:
            preferred_by_section[section_type] = {
                str(clip.get("path", ""))
                for clip in filter_clips_for_section(usable_clips, section_type, style_config)
            }
        preferred = preferred_by_section[section_type]
        affinity = section_affinity(section_type, style_config)

        slot_length = max(MIN_CUT_SECONDS, float(slot["endTime"]) - float(slot["beatTime"]))
        # Every usable clip is scored so the panel's swap picker can offer real
        # alternatives; the section preference only steers which one is taken.
        scored: List[Dict[str, Any]] = []
        for clip in usable_clips:
            result = score_clip(clip, prev_clip, section_type, affinity)

            usage = clip_usage_count.get(result["clipPath"], 0)
            if usage > 2:
                result["composite"] = max(0.0, result["composite"] - usage * OVERUSE_PENALTY)

            # A clip shorter than the slot has to be stretched or leaves a gap,
            # so rank it below an equally good clip that covers the whole cut.
            clip_length = bounded_duration(clip.get("duration"))
            if clip_length and clip_length < slot_length:
                shortfall = min(1.0, (slot_length - clip_length) / slot_length)
                result["composite"] = max(0.0, result["composite"] - SHORT_CLIP_PENALTY * shortfall)

            result["clipDuration"] = clip_length
            scored.append(result)

        # Rank once, deterministically: score first, then the clip that has
        # carried the fewest cuts, then the one idle the longest, then path.
        order = sorted(
            range(len(scored)),
            key=lambda index: (
                -scored[index]["composite"],
                clip_usage_count.get(scored[index]["clipPath"], 0),
                last_used_at.get(scored[index]["clipPath"], -1),
                scored[index]["clipPath"],
            ),
        )
        scored = [scored[index] for index in order]

        eligible = _eligible_indices(scored, recent, preferred)
        choice = eligible[0]
        best = dict(scored[choice])

        source_start, source_end = best_moment_window(
            clips_by_path.get(best["clipPath"], {}), slot_length
        )

        best["beatTime"] = slot["beatTime"]
        best["endTime"] = slot["endTime"]
        best["sectionType"] = section_type
        best["sourceStart"] = source_start
        best["sourceEnd"] = source_end
        best["score"] = round(best.pop("composite"), 2)
        best["locked"] = False
        best["alternatives"] = [
            {
                "clipPath": entry["clipPath"],
                "clipName": entry["clipName"],
                "thumbnailId": entry["thumbnailId"],
                "sceneType": entry["sceneType"],
                "score": round(entry["composite"], 2),
            }
            for index, entry in enumerate(scored)
            if index != choice
        ][:4]

        selections.append(best)
        if best["clipPath"]:
            recent.append(best["clipPath"])
            clip_usage_count[best["clipPath"]] = clip_usage_count.get(best["clipPath"], 0) + 1
            last_used_at[best["clipPath"]] = cut_index
            prev_clip = clips_by_path.get(best["clipPath"], prev_clip)

    return selections


def resolve_media_profile(clips: Sequence[Dict[str, Any]]) -> Dict[str, float]:
    """Pick the edit format from the analysed clips by majority vote."""
    sizes: Dict[Tuple[int, int], int] = {}
    rates: Dict[float, int] = {}
    for clip in clips:
        try:
            width = int(clip.get("width", 0) or 0)
            height = int(clip.get("height", 0) or 0)
            fps = round(float(clip.get("fps", 0) or 0), 3)
        except (TypeError, ValueError):
            continue
        if width > 0 and height > 0:
            sizes[(width, height)] = sizes.get((width, height), 0) + 1
        if fps > 0:
            rates[fps] = rates.get(fps, 0) + 1

    width, height = max(sizes, key=sizes.get) if sizes else (1920, 1080)
    fps = max(rates, key=rates.get) if rates else 30.0
    return {"width": width, "height": height, "fps": fps}
