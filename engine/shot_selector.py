"""AI shot selection — plans the cut grid and picks the best clip for each cut.

Two responsibilities live here:

* ``plan_cuts`` turns the beat grid, the section map and the style's
  ``cut_strategy`` into concrete ``(start, end, section)`` slots. Nothing used
  to read ``cut_strategy``, so every style cut on every beat and no cut had an
  end time.
* ``select_best_clips`` scores the analysed clips against each slot on six
  criteria, weighted by what the section calls for.
"""

from __future__ import annotations

import random
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
    "verse": ("performance", "close_up"),
    "chorus": ("close_up", "performance", "b_roll_dynamic"),
    "drop": ("b_roll_dynamic", "close_up", "performance"),
    "bridge": ("b_roll_static", "b_roll_low_light", "b_roll"),
    "outro": ("b_roll_static", "b_roll", "performance"),
}

AFFINITY_BONUS = 12.0
SHORT_CLIP_PENALTY = 15.0
REPEAT_PENALTY = 18.0
REPEAT_WINDOW = 3
EXPLORATION_RATE = 0.2
EXPLORATION_POOL = 3
MIN_CUT_SECONDS = 0.08
MAX_CUTS = 20000


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
        left = np.asarray(first, dtype=np.float64).reshape(-1)
        right = np.asarray(second, dtype=np.float64).reshape(-1)
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
    """Score a single clip on six criteria and return the weighted composite."""
    scores: Dict[str, float] = {}
    scores["composition"] = bounded_score(clip_info.get("composition_score"), 50)
    scores["energy"] = bounded_score(clip_info.get("energy_score"), 50)

    if prev_clip_info and clip_info.get("histogram") and prev_clip_info.get("histogram"):
        scores["variety"] = histogram_distance(clip_info["histogram"], prev_clip_info["histogram"])
    else:
        scores["variety"] = 80.0

    scores["sharpness"] = bounded_score(clip_info.get("sharpness_score"), 50)

    try:
        motion = float(clip_info.get("motion_intensity", 0) or 0)
    except (TypeError, ValueError):
        motion = 0.0
    scores["stability"] = max(0.0, 100.0 - min(100.0, motion * 2.0))

    scores["face_quality"] = face_quality_score(clip_info) if clip_info.get("has_face") else 50.0

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


def _parse_cut_interval(raw: Any, default: float = 1.0) -> float:
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


def plan_cuts(
    beats: Sequence[float],
    sections: Sequence[Dict[str, Any]],
    style_config: Dict[str, Any],
    duration: float,
    tempo: float = 0.0,
    bass_onsets: Optional[Sequence[float]] = None,
) -> List[Dict[str, Any]]:
    """Turn the beat grid and the style's cut strategy into timed cut slots.

    Every slot carries a start and an end, so After Effects can trim each clip
    instead of receiving a start time and no duration.
    """
    beats = [float(beat) for beat in (beats or []) if np.isfinite(beat)]
    beats.sort()
    period = _median_beat_period(beats, tempo)
    cut_strategy = (style_config or {}).get("cut_strategy") or {}
    onsets = sorted(float(onset) for onset in (bass_onsets or []) if np.isfinite(onset))

    ordered_sections = sorted(
        (section for section in (sections or []) if section),
        key=lambda section: float(section.get("start", 0.0)),
    )
    if not ordered_sections:
        ordered_sections = [{"type": "verse", "start": 0.0, "end": float(duration)}]

    slots: List[Dict[str, Any]] = []
    for section in ordered_sections:
        section_type = str(section.get("type", "verse"))
        start = max(0.0, float(section.get("start", 0.0)))
        end = min(float(duration), float(section.get("end", duration)))
        if end - start < MIN_CUT_SECONDS:
            continue

        strategy = cut_strategy.get(section_type) or {}
        interval = _parse_cut_interval(strategy.get("cut_interval"), 1.0)
        double_time = bool(
            strategy.get("double_time_on_808") or strategy.get("double_time_on_drop")
        )

        # Walk the section in fractional beat steps so a 0.25_beat drill section
        # and an 8_beat cinematic intro use the same code path.
        if beats:
            start_index = float(np.searchsorted(np.asarray(beats), start, side="left"))
        else:
            start_index = start / period if period > 0 else 0.0

        cursor = start_index
        times: List[float] = []
        guard = 0
        while guard < MAX_CUTS:
            guard += 1
            time = _beat_position(beats, cursor, period)
            if time >= end - MIN_CUT_SECONDS:
                break
            if time >= start:
                times.append(time)
            step = interval
            if double_time and _has_onset_between(onsets, time, time + interval * period):
                step = interval / 2.0
            cursor += step
            if step <= 0:
                break

        if not times:
            times = [start]

        for position, time in enumerate(times):
            slot_end = times[position + 1] if position + 1 < len(times) else end
            if slot_end - time < MIN_CUT_SECONDS:
                continue
            slots.append(
                {
                    "beatTime": round(float(time), 6),
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

    rng = random.Random(int(seed))
    selections: List[Dict[str, Any]] = []
    recent: List[str] = []
    prev_clip: Optional[Dict[str, Any]] = None
    clips_by_path = {str(clip.get("path", "")): clip for clip in usable_clips}
    preferred_by_section: Dict[str, set] = {}

    for slot in slots:
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
            if result["clipPath"] in recent[-REPEAT_WINDOW:]:
                result["composite"] = max(0.0, result["composite"] - REPEAT_PENALTY)
            # A clip shorter than the slot has to be stretched or leaves a gap,
            # so rank it below an equally good clip that covers the whole cut.
            clip_length = bounded_duration(clip.get("duration"))
            if clip_length and clip_length < slot_length:
                shortfall = min(1.0, (slot_length - clip_length) / slot_length)
                result["composite"] = max(0.0, result["composite"] - SHORT_CLIP_PENALTY * shortfall)
            result["clipDuration"] = clip_length
            scored.append(result)

        scored.sort(key=lambda entry: entry["composite"], reverse=True)

        eligible = [index for index, entry in enumerate(scored) if entry["clipPath"] in preferred]
        if not eligible:
            eligible = list(range(len(scored)))

        # Occasionally take a runner-up so a long section does not lock onto one
        # clip whenever the library is small.
        choice = eligible[0]
        if len(eligible) > 1 and rng.random() < EXPLORATION_RATE:
            choice = eligible[rng.randrange(1, min(EXPLORATION_POOL, len(eligible)))]
        best = dict(scored[choice])

        best["beatTime"] = slot["beatTime"]
        best["endTime"] = slot["endTime"]
        best["sectionType"] = section_type
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
