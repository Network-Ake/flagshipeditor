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

import ntpath
import os
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

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

# Shot scale a section prefers, best first. Published by clip analysis as
# ``shot_type``; a clip whose scale could not be measured reports ``unknown``
# and is scored without an opinion either way.
SECTION_SHOT_AFFINITY: Dict[str, Sequence[str]] = {
    "intro": ("extreme_long_shot", "long_shot", "medium_long_shot"),
    "verse": ("medium_close_up", "close_up", "medium_shot"),
    "chorus": ("close_up", "extreme_close_up", "medium_close_up"),
    "drop": ("medium_shot", "medium_long_shot", "close_up"),
    "bridge": ("long_shot", "medium_long_shot", "medium_shot"),
    "outro": ("long_shot", "extreme_long_shot", "medium_long_shot"),
}

# Camera movement a section prefers. An intro wants the frame to settle; a drop
# can carry a moving camera because the cut rate hides the settle.
SECTION_MOVEMENT_AFFINITY: Dict[str, Sequence[str]] = {
    "intro": ("static", "push_pull"),
    "verse": ("static", "pan", "push_pull"),
    "chorus": ("push_pull", "pan", "handheld"),
    "drop": ("handheld", "push_pull", "pan"),
    "bridge": ("static", "push_pull"),
    "outro": ("static", "pan"),
}

# How energetic a section's footage should look, 0..1. A drop that cuts every
# beat and lands on a static locked-off shot reads as a mistake even when that
# shot is the best-composed clip in the library — which is exactly what a
# composition-led composite used to choose.
SECTION_ENERGY_TARGETS: Dict[str, float] = {
    "intro": 0.2,
    "verse": 0.4,
    "chorus": 0.7,
    "drop": 0.9,
    "bridge": 0.3,
    "outro": 0.2,
}
DEFAULT_ENERGY_TARGET = 0.5

AFFINITY_BONUS = 12.0
SHOT_AFFINITY_BONUS = 6.0
MOVEMENT_AFFINITY_BONUS = 4.0
# Signed, not a bonus: a perfect match adds this, the worst mismatch subtracts
# it. A one-sided bonus would lift every composite towards the 0..100 ceiling
# and flatten the ranking it is supposed to sharpen.
ENERGY_MATCH_WEIGHT = 10.0
SHORT_CLIP_PENALTY = 15.0
OVERUSE_PENALTY = 3.0
REPEAT_WINDOW = 4  # A clip may not come back within this many consecutive cuts.

# Clip reservation. The strongest clips are held back from the run-up so they
# are still fresh when the hook arrives, instead of being spent on the intro
# and returning to the chorus already worn out.
HOOK_SECTIONS = ("chorus", "drop")
RESERVATION_MIN_CLIPS = 5  # Below this the library cannot spare anything.
RESERVATION_FRACTION = 1.0 / 3.0
RESERVATION_PENALTY = 9.0
HOOK_RELEASE_BONUS = 9.0
# A reserved clip is not banned from the run-up — an editor still shows their
# best footage in a verse. It is rationed: once it has carried its share of the
# cuts before the hook it steps aside, so it reaches the hook fresh instead of
# arriving on its sixth appearance and carrying an overuse penalty. Half the
# exposure of an unreserved clip, and never less than one appearance.
RESERVATION_EXPOSURE_RATIO = 0.5

# Mirrors ``beat_analysis.HOOK_SECTION_WEIGHT``. The two engines are kept
# independent on purpose — shot selection has to run on a machine where librosa
# failed to load — so the selector carries its own copy for the case where the
# caller supplies no analysed hook.
HOOK_SECTION_WEIGHT: Dict[str, float] = {
    "chorus": 1.0,
    "drop": 1.0,
    "bridge": 0.55,
    "verse": 0.45,
    "intro": 0.2,
    "outro": 0.2,
}
DEFAULT_HOOK_SECTION_WEIGHT = 0.45
MIN_CUT_SECONDS = 0.15  # Below this a cut reads as a flash frame, not an edit.
MIN_SECTION_SECONDS = 1.0  # Shorter segments are merged into their neighbour.
MAX_CUTS = 20000
_DEDUPE_TOLERANCE = 0.012  # Two cut candidates this close are the same edit.

# How much a cut candidate is worth when two of them are too close together to
# both survive. A section change outranks everything; inside a drop a played
# bass hit outranks the metronome, so a syncopated 808 keeps its own edit
# instead of being crushed by the grid cut that happens to precede it. A phrase
# boundary sits between the two: it is where the music turns over, but a bar
# line that happens to coincide with an 808 hit is still the 808's edit.
_CUT_GRID = 0
_CUT_PHRASE = 1
_CUT_ONSET = 2
_CUT_BOUNDARY = 3

# What put a cut where it is. Published on every slot so a claim about the edit
# — "this lands on the 808", "this is on the bar line" — can be traced to the
# input event that produced it instead of being asserted.
CUT_ORIGINS = ("boundary", "onset", "phrase", "grid", "subdivision")
_ORIGIN_BY_PRIORITY = {
    _CUT_BOUNDARY: "boundary",
    _CUT_ONSET: "onset",
    _CUT_PHRASE: "phrase",
    _CUT_GRID: "grid",
}
# Largest distance at which a cut may still be called beat-aligned. The planner
# narrows it to a quarter of the beat period on a slow track; the value actually
# used travels with each cut.
CUT_SNAP_TOLERANCE_SECONDS = 0.08
# How much the measured energy of the track at a cut moves that cut's energy
# target away from its section default. The section still dominates: a chorus
# stays a chorus, but a bar where the mix drops out stops asking for the most
# frantic clip in the library.
ENERGY_CURVE_WEIGHT = 0.35


class _Candidate(NamedTuple):
    """One possible cut: when, in which section, how strong, and from what."""

    time: float
    section_type: str
    priority: int
    origin: str
    evidence: Optional[float]

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


def _canonical_clip_path(path: Any) -> str:
    """Return the deterministic identity used for a usable media clip.

    Selection accounting is keyed by path, so an empty path or two lexical
    spellings of the same path would collapse dictionaries and silently corrupt
    repeat/usage tracking.  Windows paths are normalized with Windows rules
    even when contracts run on macOS; native paths are made absolute and have
    symlinks/``..`` resolved lexically by ``realpath``.
    """
    if not isinstance(path, str) or not path.strip():
        raise ValueError("usable clip path must be a non-empty string")

    cleaned = path.strip()
    looks_windows = (
        (len(cleaned) >= 2 and cleaned[1] == ":")
        or cleaned.startswith("\\\\")
    )
    if looks_windows:
        return ntpath.normcase(ntpath.normpath(cleaned))
    return os.path.normcase(
        os.path.realpath(os.path.abspath(os.path.expanduser(cleaned)))
    )


def _validated_usable_clips(
    clips: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Copy usable clips, canonicalize paths, and reject duplicate identities."""
    validated: List[Dict[str, Any]] = []
    first_index_by_path: Dict[str, int] = {}
    for index, clip in enumerate(clips):
        if not clip.get("usable", True):
            continue
        try:
            identity = _canonical_clip_path(clip.get("path"))
        except ValueError as error:
            raise ValueError(f"Invalid usable clip at index {index}: {error}") from error
        if identity in first_index_by_path:
            first_index = first_index_by_path[identity]
            raise ValueError(
                "Duplicate usable clip path at indices "
                f"{first_index} and {index}: {identity}"
            )
        first_index_by_path[identity] = index
        # The canonical value is identity-only. Preserve the caller's cleaned
        # path for the CEP/API boundary: lowercasing or resolving a symlink in
        # an output payload would be an unnecessary downstream behaviour
        # change even though both paths identify the same file.
        normalized = dict(clip)
        normalized["path"] = str(clip["path"]).strip()
        validated.append(normalized)
    return validated


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


def shot_affinity(
    section_type: str,
    style_config: Optional[Dict[str, Any]] = None,
) -> Sequence[str]:
    """Return the shot scales a section prefers, honouring a style override.

    A preset carries ``"shot_affinity": {"drop": ["long_shot"]}`` to change how
    tight the edit sits without touching the scoring weights.
    """
    overrides = (style_config or {}).get("shot_affinity") or {}
    override = overrides.get(section_type)
    if isinstance(override, (list, tuple)) and override:
        return tuple(str(entry) for entry in override)
    return SECTION_SHOT_AFFINITY.get(section_type, ())


def movement_affinity(
    section_type: str,
    style_config: Optional[Dict[str, Any]] = None,
) -> Sequence[str]:
    """Return the camera movements a section prefers, honouring a style override."""
    overrides = (style_config or {}).get("movement_affinity") or {}
    override = overrides.get(section_type)
    if isinstance(override, (list, tuple)) and override:
        return tuple(str(entry) for entry in override)
    return SECTION_MOVEMENT_AFFINITY.get(section_type, ())


def _ranked_bonus(value: str, preferred: Sequence[str], bonus: float) -> float:
    """Award ``bonus`` for the first entry of a preference list, less for later ones."""
    if not preferred or not value or value == "unknown":
        return 0.0
    try:
        rank = list(preferred).index(value)
    except ValueError:
        return 0.0
    return bonus * (1.0 - rank / max(1, len(preferred)))


def _finite(value: Any) -> Optional[float]:
    """Return the value as a float only when it is genuinely a finite number."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def normalize_motion_evidence(
    clips: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Normalize elapsed-time motion rates against the supplied library.

    Optical-flow pixels per second have no universal absolute scale: frame
    resolution, lens and subject distance all affect the number. Cross-clip
    ranking only needs a stable scale *inside this library*, so the 90th
    percentile becomes 100 and every clip is measured relative to it. This
    consumes the elapsed-time-normalized evidence without inventing a global
    calibration before real-media fixtures exist. Legacy clips with no rate
    retain their previous raw-motion scoring.
    """
    result = [dict(clip) for clip in clips]

    def _trusted_rate(clip: Dict[str, Any], field: str) -> Optional[float]:
        policy = clip.get("motion_sample_policy")
        if not isinstance(policy, dict) or policy.get("elapsed_normalized") is not True:
            return None
        return _finite(clip.get(field))

    def _reference(field: str) -> Optional[float]:
        values = [
            value
            for value in (_trusted_rate(clip, field) for clip in result)
            if value is not None and value >= 0.0
        ]
        if not values:
            return None
        reference = float(np.percentile(np.asarray(values, dtype=np.float64), 90.0))
        return reference if np.isfinite(reference) and reference > 1e-9 else None

    intensity_reference = _reference("motion_intensity_per_second")
    variance_reference = _reference("motion_variance_per_second")
    for clip in result:
        intensity = _trusted_rate(clip, "motion_intensity_per_second")
        variance = _trusted_rate(clip, "motion_variance_per_second")
        if intensity is not None and intensity_reference is not None:
            clip["_selector_motion_intensity"] = max(
                0.0, min(100.0, intensity / intensity_reference * 100.0)
            )
        if variance is not None and variance_reference is not None:
            clip["_selector_motion_variance"] = max(
                0.0, min(100.0, variance / variance_reference * 100.0)
            )
    return result


def clip_energy_profile(clip_info: Dict[str, Any]) -> Optional[float]:
    """Return how energetic a clip looks on a 0..100 scale, or ``None``.

    ``None`` means the record carries no energy evidence at all — an analysis
    from before these fields existed, or a clip whose motion pass produced
    nothing. That is deliberately distinct from "measured, and it is zero":
    scoring a record with no evidence as motionless would push every legacy clip
    out of every drop, which is a worse answer than having no opinion.

    Motion is the primary evidence. ``energy_score`` from clip analysis also
    folds in brightness and saturation, which is what separates a bright,
    saturated, static shot from a dim one — so when it is present the two are
    averaged rather than one being thrown away.
    """
    normalized_intensity = _finite(clip_info.get("_selector_motion_intensity"))
    normalized_variance = _finite(clip_info.get("_selector_motion_variance"))
    intensity = _finite(clip_info.get("motion_intensity"))
    variance = _finite(clip_info.get("motion_variance"))
    analysed = _finite(clip_info.get("energy_score"))
    if normalized_intensity is None and normalized_variance is None and intensity is None and variance is None and analysed is None:
        return None

    if normalized_intensity is not None or normalized_variance is not None:
        # ``energy_score`` contains the old spacing-dependent raw motion, so it
        # must not leak back into a record that carries normalized evidence.
        return (
            max(0.0, normalized_intensity or 0.0) * 0.7
            + max(0.0, normalized_variance or 0.0) * 0.3
        )

    components: List[float] = []
    if intensity is not None or variance is not None:
        components.append(
            min(
                100.0,
                max(0.0, intensity or 0.0) * 0.6 + max(0.0, variance or 0.0) * 3.0,
            )
        )
    if analysed is not None:
        components.append(max(0.0, min(100.0, analysed)))
    return sum(components) / len(components)


def section_energy_target(
    section_type: str,
    style_config: Optional[Dict[str, Any]] = None,
) -> float:
    """Return how energetic a section's footage should look, 0..1."""
    overrides = (style_config or {}).get("energy_targets") or {}
    target = _finite(overrides.get(section_type))
    if target is None:
        target = SECTION_ENERGY_TARGETS.get(section_type, DEFAULT_ENERGY_TARGET)
    return max(0.0, min(1.0, float(target)))


def energy_match_adjustment(
    clip_info: Dict[str, Any],
    section_type: str,
    style_config: Optional[Dict[str, Any]] = None,
    energy_target: Optional[float] = None,
) -> float:
    """Reward footage whose energy matches what the section is doing.

    The composite already weights energy more heavily in a drop than in a verse,
    but weighting only scales a score — it cannot express that 90% energy is
    *right* for a drop and *wrong* for a bridge. This does: the adjustment peaks
    when the clip sits on the target and goes negative as it drifts away in
    either direction, so a frantic handheld shot is pushed out of an intro just
    as firmly as a locked-off still is pushed out of a drop.

    ``energy_target`` overrides the section default with what the track was
    measured doing at this cut. Passing ``None`` keeps the section default,
    which is what a caller with no energy curve gets.
    """
    profile = clip_energy_profile(clip_info)
    if profile is None:
        return 0.0
    target = _finite(energy_target)
    if target is None:
        target = section_energy_target(section_type, style_config)
    target = max(0.0, min(1.0, float(target)))
    delta = abs(profile / 100.0 - target)
    return (1.0 - 2.0 * delta) * ENERGY_MATCH_WEIGHT


def score_clip(
    clip_info: Dict[str, Any],
    prev_clip_info: Optional[Dict[str, Any]] = None,
    section_type: str = "",
    affinity: Optional[Sequence[str]] = None,
    shot_preference: Optional[Sequence[str]] = None,
    movement_preference: Optional[Sequence[str]] = None,
    style_config: Optional[Dict[str, Any]] = None,
    energy_target: Optional[float] = None,
) -> Dict[str, Any]:
    """Score a single clip on six criteria and return the weighted composite.

    ``energy`` blends average motion with motion variance, so a clip whose
    movement builds or breaks scores above one that pans at a constant rate.
    ``stability`` reads the brightness jitter measured during clip analysis, and
    ``face_quality`` rewards a face that is present in most frames rather than
    one that flashes through a single sample.

    Four things then move the composite away from raw quality and towards fit:
    the legacy scene affinity, the shot scale the section calls for, the camera
    movement it can carry, and how close the clip's energy sits to the
    section's target. Every one of them is inert on a record that does not carry
    the field, so an analysis produced before those fields existed scores
    exactly as it did before.

    The six component scores are unchanged and remain the public contract; fit
    is expressed in the composite alone.
    """
    scores: Dict[str, float] = {}
    scores["composition"] = bounded_score(clip_info.get("composition_score"), 50)

    normalized_intensity = _finite(clip_info.get("_selector_motion_intensity"))
    normalized_variance = _finite(clip_info.get("_selector_motion_variance"))
    if normalized_intensity is not None or normalized_variance is not None:
        scores["energy"] = min(
            100.0,
            max(0.0, normalized_intensity or 0.0) * 0.7
            + max(0.0, normalized_variance or 0.0) * 0.3,
        )
    else:
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

    preferred = (
        list(affinity)
        if affinity is not None
        else list(section_affinity(section_type, style_config))
    )
    scene_type = str(clip_info.get("scene_type", "unknown"))
    if scene_type in preferred:
        rank = preferred.index(scene_type)
        composite += AFFINITY_BONUS * (1.0 - rank / max(1, len(preferred)))

    shot_type = str(clip_info.get("shot_type", "unknown") or "unknown")
    shot_preferred = (
        list(shot_preference)
        if shot_preference is not None
        else list(shot_affinity(section_type, style_config))
    )
    composite += _ranked_bonus(shot_type, shot_preferred, SHOT_AFFINITY_BONUS)

    camera_movement = str(clip_info.get("camera_movement", "unknown") or "unknown")
    movement_preferred = (
        list(movement_preference)
        if movement_preference is not None
        else list(movement_affinity(section_type, style_config))
    )
    composite += _ranked_bonus(camera_movement, movement_preferred, MOVEMENT_AFFINITY_BONUS)

    composite += energy_match_adjustment(
        clip_info, section_type, style_config, energy_target
    )

    return {
        "scores": scores,
        "composite": max(0.0, min(100.0, composite)),
        "clipPath": str(clip_info.get("path", "")),
        "clipName": str(clip_info.get("name", "")),
        "thumbnailId": str(clip_info.get("thumbnail_id", "")),
        "sceneType": scene_type,
        "shotType": shot_type,
        "cameraMovement": camera_movement,
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
    phrases: Sequence[float] = (),
    downbeats: Sequence[float] = (),
) -> List[_Candidate]:
    """Return the cut candidates for one section, each with what produced it.

    The section start is always emitted at ``_CUT_BOUNDARY``. What follows
    depends on the section type: a drop follows its bass onsets, everything else
    walks the beat grid at the section's cut interval. Phrase boundaries are
    added everywhere — they are where the music turns over, and an edit that
    ignores them cuts across the phrase instead of with it.
    """
    section_type = str(section.get("type", "verse"))
    start = float(section["start"])
    end = float(section["end"])
    interval_beats = get_cut_interval_for_section(section_type, style_config)

    candidates: List[_Candidate] = [
        _Candidate(start, section_type, _CUT_BOUNDARY, "boundary", start)
    ]

    first_index, last_index = _section_beat_indices(beats, start, end)
    section_beats = list(beats[first_index:last_index])

    if section_beats:
        # Anchor bar-counted cuts to the measured downbeat phase when it is
        # available. A structural section boundary can land mid-bar; assuming
        # it is always beat one shifts every verse cut for the whole section.
        position = 0.0
        if downbeats:
            tolerance = min(CUT_SNAP_TOLERANCE_SECONDS, period * 0.25)
            for local_index, beat in enumerate(section_beats):
                if any(abs(float(beat) - float(downbeat)) <= tolerance for downbeat in downbeats):
                    position = float(local_index)
                    break
        limit = float(last_index - first_index)
        while position < limit:
            grid_time = _beat_position(beats, first_index + position, period)
            candidates.append(
                _Candidate(
                    grid_time,
                    section_type,
                    _CUT_GRID,
                    "grid",
                    grid_time,
                )
            )
            position += interval_beats
    else:
        # No beat landed in this section — fall back to a metronome from tempo.
        step = max(MIN_CUT_SECONDS, interval_beats * period)
        time_value = start + step
        while time_value < end:
            candidates.append(
                _Candidate(time_value, section_type, _CUT_GRID, "grid", time_value)
            )
            time_value += step

    # A phrase boundary is a cut whether or not the section's interval happens
    # to land on it, and it outranks the grid tick beside it in the spacing
    # arbitration below.
    for phrase in phrases:
        if start < phrase < end:
            candidates.append(
                _Candidate(float(phrase), section_type, _CUT_PHRASE, "phrase", float(phrase))
            )

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
            # ``evidence`` keeps the onset as it was played, so a cut can prove
            # which 808 hit it came from even after quantisation moved it.
            candidates.append(
                _Candidate(snapped, section_type, _CUT_ONSET, "onset", float(onset))
            )
            if double_time and half_step >= MIN_CUT_SECONDS:
                offbeat = snapped + half_step
                if offbeat < end:
                    candidates.append(
                        _Candidate(offbeat, section_type, _CUT_GRID, "grid", offbeat)
                    )

    return [entry for entry in candidates if start <= entry.time < end]


def _dedupe_times(candidates: List[_Candidate]) -> List[_Candidate]:
    """Collapse candidates that describe the same edit, keeping the strongest.

    A bass onset quantised onto the beat lands on a grid candidate that is
    already there; the two are one edit, and the survivor keeps the higher
    priority so the later spacing pass — and the cut's own provenance — knows
    the 808 was played here.
    """
    ordered = sorted(candidates, key=lambda entry: (entry.time, -entry.priority))
    deduped: List[_Candidate] = []
    for entry in ordered:
        if deduped and entry.time - deduped[-1].time <= _DEDUPE_TOLERANCE:
            if entry.priority > deduped[-1].priority:
                deduped[-1] = entry
            continue
        deduped.append(entry)
    return deduped


def _enforce_min_spacing(
    candidates: List[_Candidate],
    min_gap: float,
) -> List[_Candidate]:
    """Drop cuts that would produce a sub-``min_gap`` slot, weakest first.

    Cuts are removed rather than shortened, so the surviving cut simply runs
    longer and the timeline stays gap-free. When two cuts crowd each other the
    higher-priority one wins: a section boundary evicts an ordinary cut, and a
    bass onset evicts the grid tick next to it. Evicting can uncover a third cut
    that is now too close, so the walk back continues until the spacing holds.
    """
    kept: List[_Candidate] = []
    for entry in candidates:
        time_value, priority = entry.time, entry.priority
        while kept and time_value - kept[-1].time < min_gap and priority > kept[-1].priority:
            kept.pop()
        if not kept:
            kept.append(entry)
            continue
        if time_value - kept[-1].time >= min_gap:
            kept.append(entry)
        elif priority == _CUT_BOUNDARY and kept[-1].priority == _CUT_BOUNDARY:
            # Two boundaries this close cannot happen after normalize_sections,
            # but honour both rather than silently losing a section.
            kept.append(entry)
    return kept


def _subdivide_long_slots(
    candidates: List[_Candidate],
    end_time: float,
    beats: Sequence[float],
    period: float,
    style_config: Dict[str, Any],
) -> List[_Candidate]:
    """Split any slot that outruns its section's maximum cut length.

    Splitting beats truncating: a truncated slot leaves the timeline empty until
    the next cut, whereas an extra cut keeps the edit continuous.
    """
    if not candidates:
        return candidates
    expanded: List[_Candidate] = []
    for index, entry in enumerate(candidates):
        expanded.append(entry)
        time_value, section_type = entry.time, entry.section_type
        slot_end = candidates[index + 1].time if index + 1 < len(candidates) else end_time
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
            requested_split = time_value + step * piece
            split = _snap_to_beat(requested_split, beats, snap_tolerance)
            if split - previous < MIN_CUT_SECONDS or slot_end - split < MIN_CUT_SECONDS:
                continue
            expanded.append(
                _Candidate(
                    split,
                    section_type,
                    _CUT_GRID,
                    "subdivision",
                    requested_split,
                )
            )
            previous = split
    expanded.sort(key=lambda item: item.time)
    return expanded


def _absorb_runt_tails(
    candidates: List[_Candidate],
    end_time: float,
    period: float,
    style_config: Dict[str, Any],
) -> List[_Candidate]:
    """Remove a cut whose slot is a stub against the next section boundary.

    A section rarely divides evenly by its cut interval, which leaves a runt at
    the tail — a quarter-second flash right before the transition. Dropping that
    cut lets the previous shot ride into the boundary, which is what an editor
    does. Boundary cuts themselves are never removed.
    """
    if len(candidates) < 2:
        return candidates
    kept: List[_Candidate] = [candidates[0]]
    for index in range(1, len(candidates)):
        time_value = candidates[index].time
        section_type = candidates[index].section_type
        if candidates[index].priority == _CUT_BOUNDARY:
            kept.append(candidates[index])
            continue
        slot_end = candidates[index + 1].time if index + 1 < len(candidates) else end_time
        interval_seconds = get_cut_interval_for_section(section_type, style_config) * period
        if slot_end - time_value < interval_seconds * 0.5:
            continue
        kept.append(candidates[index])
    return kept


def _phrase_times(phrase_boundaries: Optional[Sequence[Any]]) -> List[float]:
    """Accept phrase boundaries as plain times or as beat-analysis records.

    ``beat_analysis`` publishes them as bare seconds, but its internal form is
    ``{"time": ..., "phrase_length": ...}`` and a caller that forwards the
    richer shape should not silently lose every boundary.
    """
    values: List[Any] = []
    for entry in phrase_boundaries or []:
        if isinstance(entry, dict):
            values.append(entry.get("time"))
        else:
            values.append(entry)
    return _clean_times(values)


def _cut_provenance(
    candidate: _Candidate,
    beats: Sequence[float],
    snap_tolerance: float,
) -> Dict[str, Any]:
    """Record what put this cut here, and how far it moved to get there.

    Without this a finished timeline is a list of numbers: "the edit follows the
    808" and "the edit follows a metronome" look identical. ``origin`` names the
    input that produced the cut, ``sourceTime`` is that input event as it was
    measured, and ``snapDelta`` is how far quantisation moved it. ``beatAligned``
    is a claim with a declared tolerance rather than an assertion.
    """
    beat_delta = None
    if len(beats):
        grid = np.asarray(beats, dtype=np.float64)
        beat_delta = float(np.min(np.abs(grid - candidate.time)))
    return {
        "origin": candidate.origin,
        "sourceTime": round(float(candidate.evidence), 6) if candidate.evidence is not None else None,
        "snapDelta": (
            round(float(candidate.time - candidate.evidence), 6)
            if candidate.evidence is not None
            else None
        ),
        "beatDelta": round(beat_delta, 6) if beat_delta is not None else None,
        "beatAligned": bool(beat_delta is not None and beat_delta <= snap_tolerance),
        "snapTolerance": round(float(snap_tolerance), 6),
    }


def plan_cuts(
    beats: Sequence[float],
    sections: Sequence[Dict[str, Any]],
    style_config: Dict[str, Any],
    duration: float,
    tempo: float = 0.0,
    bass_onsets: Optional[Sequence[float]] = None,
    phrase_boundaries: Optional[Sequence[Any]] = None,
    downbeats: Optional[Sequence[float]] = None,
) -> List[Dict[str, Any]]:
    """Turn the beat grid and the style's cut strategy into timed cut slots.

    The rules, in the order they are applied:

    * every section boundary is a cut, whether or not a beat lands there;
    * a drop cuts on its bass onsets, quantised onto the beat when they are a
      near miss, so the edit follows the 808 rather than a metronome;
    * a phrase boundary is a cut in every section, and outranks the grid tick
      beside it when the two are too close to both survive;
    * every other section walks the beat grid at its own interval — one cut per
      bar in a verse, one per beat in a chorus, one per bar in intro and outro;
    * no slot is shorter than ``MIN_CUT_SECONDS`` or longer than its section's
      maximum, and the slots tile ``[0, duration]`` with no gap or overlap.

    Every slot carries a start, an end, and the provenance of its own cut, so
    After Effects can trim each clip and any claim made about the edit can be
    traced back to the input event behind it.
    """
    duration = float(duration) if np.isfinite(duration) else 0.0
    if duration <= 0:
        return []

    beat_times = _clean_times(beats)
    period = _median_beat_period(beat_times, tempo)
    if not np.isfinite(period) or period <= 0:
        period = 0.5
    onsets = _clean_times(bass_onsets)
    phrases = [
        value for value in _phrase_times(phrase_boundaries) if 0.0 < value < duration
    ]
    downbeat_times = _clean_times(downbeats)
    style_config = style_config or {}

    ordered_sections = normalize_sections(sections, duration)
    if not ordered_sections:
        return []

    candidates: List[_Candidate] = []
    for section in ordered_sections:
        candidates.extend(
            _section_cut_candidates(
                section,
                beat_times,
                onsets,
                period,
                style_config,
                phrases,
                downbeat_times,
            )
        )

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

    snap_tolerance = min(CUT_SNAP_TOLERANCE_SECONDS, period * 0.25)
    slots: List[Dict[str, Any]] = []
    for index, candidate in enumerate(candidates):
        slot_end = candidates[index + 1].time if index + 1 < len(candidates) else duration
        if slot_end - candidate.time < MIN_CUT_SECONDS:
            continue
        slots.append(
            {
                "beatTime": round(float(candidate.time), 6),
                "endTime": round(float(slot_end), 6),
                "sectionType": candidate.section_type,
                "cutProvenance": _cut_provenance(candidate, beat_times, snap_tolerance),
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
    rationed: Optional[set] = None,
) -> List[int]:
    """Return candidate indices honouring the no-repeat rule as far as possible.

    A clip used in the last ``REPEAT_WINDOW`` cuts is excluded outright rather
    than merely penalised — a penalty still loses to a high enough score, which
    is how the same shot ends up back-to-back. When the library is smaller than
    the window the constraint is relaxed one cut at a time, so a three-clip
    project still alternates instead of failing.

    ``rationed`` names reserved clips that have already spent their run-up
    budget. They step aside only while something else can fill the cut: a score
    penalty alone cannot hold footage back on a long track, because the
    no-repeat rule forces the library to rotate and the rotation, not the score,
    decides what appears. Stepping aside is what makes the reservation real,
    and falling back to them when nothing else is eligible is what stops it
    from ever emptying the timeline.
    """
    for window in range(REPEAT_WINDOW, 0, -1):
        blocked = set(recent[-window:])
        allowed = [
            index for index, entry in enumerate(scored) if entry["clipPath"] not in blocked
        ]
        if not allowed:
            continue
        if rationed:
            spare = [index for index in allowed if scored[index]["clipPath"] not in rationed]
            if spare:
                allowed = spare
        favoured = [index for index in allowed if scored[index]["clipPath"] in preferred]
        return favoured or allowed
    return list(range(len(scored)))


class TrackEnergyCurve(NamedTuple):
    """The track's own loudness curve, normalised against its own peak."""

    times: Any
    values: Any

    def mean_between(self, start: float, end: float) -> Optional[float]:
        """Mean normalised energy inside ``[start, end)``, or ``None``."""
        if self.times.size == 0:
            return None
        first = int(np.searchsorted(self.times, start, side="left"))
        last = int(np.searchsorted(self.times, end, side="left"))
        if last <= first:
            # A cut shorter than one analysis frame still has a nearest sample.
            index = min(max(first, 0), self.values.size - 1)
            return float(self.values[index])
        window = self.values[first:last]
        return float(np.mean(window)) if window.size else None


def track_energy_curve(
    energy: Optional[Sequence[Any]],
    energy_times: Optional[Sequence[Any]] = None,
    duration: float = 0.0,
    hop_length: Optional[float] = None,
    sample_rate: Optional[float] = None,
) -> Optional[TrackEnergyCurve]:
    """Turn the beat engine's RMS curve into something a cut can be scored against.

    The curve arrives as bare numbers. Its time base is taken, in order of
    preference, from the timestamps the beat engine now publishes, from the
    hop length and sample rate it was measured at, or — for a result restored
    from an older cache that carries neither — from spreading the samples
    evenly across the track. The last case is an inference and is only used
    because dropping the signal entirely would be worse.

    Values are normalised against the track's own peak rather than an absolute
    threshold: modern masters are limited flat, and an absolute gate would fire
    everywhere or nowhere. Returns ``None`` when there is nothing usable, which
    is the signal to keep the section defaults exactly as they were.
    """
    values = np.asarray(
        [value for value in (energy or []) if isinstance(value, (int, float))],
        dtype=np.float64,
    )
    if values.size < 2 or not np.all(np.isfinite(values)):
        return None
    peak = float(np.max(values))
    if not np.isfinite(peak) or peak <= 0:
        return None

    times = np.asarray(
        [value for value in (energy_times or []) if isinstance(value, (int, float))],
        dtype=np.float64,
    )
    if times.size >= values.size and np.all(np.isfinite(times[: values.size])):
        times = times[: values.size]
    else:
        step = None
        hop = _finite(hop_length)
        rate = _finite(sample_rate)
        if hop and rate and hop > 0 and rate > 0:
            step = hop / rate
        elif duration and duration > 0:
            step = float(duration) / float(values.size)
        if not step or step <= 0:
            return None
        times = np.arange(values.size, dtype=np.float64) * step
    if times.size != values.size or not np.all(np.diff(times) > 0):
        return None
    return TrackEnergyCurve(times, values / peak)


def cut_energy_target(
    curve: Optional[TrackEnergyCurve],
    section_type: str,
    start: float,
    end: float,
    style_config: Optional[Dict[str, Any]] = None,
) -> float:
    """Blend what the section calls for with what the track is actually doing.

    A section label is a coarse description of a stretch that can be a minute
    long. Inside it the mix drops out, the beat comes back in, the last bar
    empties before the chorus — and the label says none of that, so every cut in
    the section asks for identically energetic footage. The measured curve
    supplies the missing resolution while the section keeps the final say: the
    blend is deliberately weighted towards the label so a chorus still reads as
    a chorus.
    """
    target = section_energy_target(section_type, style_config)
    if curve is None:
        return target
    measured = curve.mean_between(float(start), float(end))
    if measured is None or not np.isfinite(measured):
        return target
    measured = max(0.0, min(1.0, float(measured)))
    return max(
        0.0,
        min(1.0, target * (1.0 - ENERGY_CURVE_WEIGHT) + measured * ENERGY_CURVE_WEIGHT),
    )


def _infer_hook_window(
    sections: Sequence[Dict[str, Any]],
    onsets: Sequence[float],
    duration: float,
) -> Optional[Tuple[float, float]]:
    """Estimate the hook from section labels and bass density alone.

    This is the standalone path: ``/select-shots`` can be called without a beat
    analysis attached, and the reservation still has to know which stretch of
    the track is worth saving footage for. Bass density is the only intensity
    evidence available here — the energy curve lives in the beat engine — so the
    section label and a mild preference for the back half carry more of the
    decision than they do in ``beat_analysis.detect_hook_section``.
    """
    if not sections or duration <= 0:
        return None
    onset_array = np.asarray(onsets, dtype=np.float64) if len(onsets) else np.asarray([])
    densities = []
    for section in sections:
        start = float(section["start"])
        end = float(section["end"])
        span = max(1e-9, end - start)
        count = (
            int(np.sum((onset_array >= start) & (onset_array < end)))
            if onset_array.size
            else 0
        )
        densities.append(count / span)
    peak_density = max(densities) if densities else 0.0

    best_index = -1
    best_score = 0.0
    for index, section in enumerate(sections):
        start = float(section["start"])
        end = float(section["end"])
        label_weight = HOOK_SECTION_WEIGHT.get(
            str(section.get("type", "verse")), DEFAULT_HOOK_SECTION_WEIGHT
        )
        density = densities[index] / peak_density if peak_density > 0 else 0.0
        midpoint = (start + end) * 0.5
        lateness = max(0.0, min(1.0, midpoint / duration))
        # Without an energy curve, a labelled chorus with no measured bass must
        # still beat an unlabelled stretch, so the label contributes a floor
        # rather than only scaling the density.
        score = (0.35 + 0.65 * density) * label_weight * (1.0 + 0.25 * lateness)
        if score > best_score:
            best_score = score
            best_index = index
    if best_index < 0:
        return None
    chosen = sections[best_index]
    return float(chosen["start"]), float(chosen["end"])


def resolve_hook_window(
    hook: Optional[Dict[str, Any]],
    sections: Sequence[Dict[str, Any]],
    onsets: Sequence[float],
    duration: float,
) -> Optional[Tuple[float, float]]:
    """Return the ``(start, end)`` of the hook, preferring the analysed one.

    A hook supplied by ``beat_analysis`` was measured against the actual energy
    curve and sustained bass, so it wins whenever it is present and usable.
    Anything malformed falls through to the local estimate rather than
    disabling reservation, because a wrong hook window costs a little ordering
    and a missing one costs the whole feature.
    """
    if isinstance(hook, dict):
        start = _finite(hook.get("start"))
        end = _finite(hook.get("end"))
        if start is not None and end is not None:
            start = max(0.0, min(duration, start))
            end = max(0.0, min(duration, end))
            if end > start:
                return start, end
    return _infer_hook_window(sections, onsets, duration)


def reserved_clip_paths(clips: Sequence[Dict[str, Any]]) -> set:
    """Return the paths of the strongest third of the library.

    Quality here is deliberately section-agnostic: a clip is reserved because it
    is good, not because it suits the hook's section type, and the hook's own
    affinities then decide which of the reserved clips actually lands there.

    A library too small to spare anything reserves nothing — holding footage
    back from a four-clip project would starve the run-up without ever filling
    the hook with something new.
    """
    if len(clips) < RESERVATION_MIN_CLIPS:
        return set()
    ranked = sorted(
        (
            (score_clip(clip, None, "")["composite"], str(clip.get("path", "")))
            for clip in clips
        ),
        key=lambda entry: (-entry[0], entry[1]),
    )
    count = max(1, int(len(ranked) * RESERVATION_FRACTION))
    return {path for _score, path in ranked[:count]}


def select_best_clips(
    clips: Sequence[Dict[str, Any]],
    beats: Sequence[float],
    sections: Sequence[Dict[str, Any]],
    style_config: Optional[Dict[str, Any]] = None,
    duration: float = 0.0,
    tempo: float = 0.0,
    bass_onsets: Optional[Sequence[float]] = None,
    seed: int = 1,
    hook: Optional[Dict[str, Any]] = None,
    phrase_boundaries: Optional[Sequence[Any]] = None,
    energy: Optional[Sequence[Any]] = None,
    energy_times: Optional[Sequence[Any]] = None,
    energy_hop_length: Optional[float] = None,
    energy_sample_rate: Optional[float] = None,
    downbeats: Optional[Sequence[float]] = None,
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

    A fourth rule shapes *where* the good footage lands. Scoring each cut on its
    own merits spends the strongest clips on whatever comes first, so by the
    time the hook arrives they have already been seen two or three times and are
    carrying an overuse penalty. The strongest third of the library is therefore
    held back through the run-up and released at the hook — the section
    ``beat_analysis`` measured as the track's peak, or the selector's own
    estimate when no analysis was supplied. ``hook`` is optional and the
    reservation disables itself entirely on a library too small to spare
    anything, so a small or uniform project behaves exactly as it did before.

    Two more beat signals shape the result when the caller has them.
    ``phrase_boundaries`` become cut points, so the edit turns over where the
    music does. The ``energy`` curve — with the time base the beat engine
    publishes alongside it — moves each cut's energy target towards what the
    track measurably does at that moment, instead of every cut in a section
    asking for the same thing. Both are optional and inert when absent, so a
    caller that supplies neither gets exactly the previous behaviour.

    The result is ordered by time and uses the same camelCase field names the
    After Effects bridge consumes, so no translation layer can drift.
    """
    style_config = style_config or {}
    # Identity must be validated before any path-keyed dictionary or counter is
    # constructed. Otherwise duplicate/empty paths alias one another and make
    # repeat prevention and usage penalties dishonest.
    usable_clips = normalize_motion_evidence(_validated_usable_clips(clips))
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

    slots = plan_cuts(
        beats,
        sections,
        style_config,
        duration,
        tempo,
        bass_onsets,
        phrase_boundaries,
        downbeats,
    )
    if not slots:
        return []

    energy_curve = track_energy_curve(
        energy, energy_times, duration, energy_hop_length, energy_sample_rate
    )

    hook_window = resolve_hook_window(
        hook,
        normalize_sections(sections, duration),
        _clean_times(bass_onsets),
        duration,
    )
    reserved = reserved_clip_paths(usable_clips) if hook_window else set()
    # Each reserved clip may carry half the cuts an unreserved one would, which
    # scales the reservation to the track rather than to a fixed number: a
    # sixteen-bar intro and a four-minute run-up cannot share one budget.
    run_up_cuts = (
        sum(
            1
            for slot in slots
            if float(slot["endTime"]) <= hook_window[0]
            and slot["sectionType"] not in HOOK_SECTIONS
        )
        if hook_window
        else 0
    )
    reservation_budget = (
        max(1, int(round(run_up_cuts * RESERVATION_EXPOSURE_RATIO / len(usable_clips))))
        if reserved
        else 0
    )

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
        shots = shot_affinity(section_type, style_config)
        movements = movement_affinity(section_type, style_config)

        slot_start = float(slot["beatTime"])
        slot_end_time = float(slot["endTime"])
        # A cut counts as part of the hook when it overlaps the hook window at
        # all, and as run-up only when it finishes before the hook opens.
        in_hook = bool(hook_window) and slot_start < hook_window[1] and slot_end_time > hook_window[0]
        before_hook = bool(hook_window) and slot_end_time <= hook_window[0]
        # A chorus on the way to the hook is still a peak of its own, so it is
        # never asked to hand its footage over.
        holding_back = before_hook and section_type not in HOOK_SECTIONS

        slot_length = max(MIN_CUT_SECONDS, slot_end_time - slot_start)
        energy_target = cut_energy_target(
            energy_curve, section_type, slot_start, slot_end_time, style_config
        )
        # Every usable clip is scored so the panel's swap picker can offer real
        # alternatives; the section preference only steers which one is taken.
        scored: List[Dict[str, Any]] = []
        for clip in usable_clips:
            result = score_clip(
                clip,
                prev_clip,
                section_type,
                affinity,
                shots,
                movements,
                style_config,
                energy_target,
            )

            # Reservation is a penalty rather than a filter: a reserved clip
            # that is still far better than anything else available will win the
            # cut anyway, so the run-up can never be starved.
            if reserved and result["clipPath"] in reserved:
                if holding_back:
                    result["composite"] = max(0.0, result["composite"] - RESERVATION_PENALTY)
                elif in_hook:
                    result["composite"] = min(100.0, result["composite"] + HOOK_RELEASE_BONUS)

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

        rationed = (
            {
                path
                for path in reserved
                if clip_usage_count.get(path, 0) >= reservation_budget
            }
            if holding_back and reserved
            else None
        )
        eligible = _eligible_indices(scored, recent, preferred, rationed)
        choice = eligible[0]
        best = dict(scored[choice])

        source_start, source_end = best_moment_window(
            clips_by_path.get(best["clipPath"], {}), slot_length
        )

        best["beatTime"] = slot["beatTime"]
        best["endTime"] = slot["endTime"]
        best["sectionType"] = section_type
        # The cut keeps the provenance of its own boundary: what put it there,
        # which input event it came from, and how far quantisation moved it.
        best["cutProvenance"] = dict(
            slot.get("cutProvenance") or {},
            energyTarget=round(float(energy_target), 4),
            energySource="measured_curve" if energy_curve is not None else "section_default",
        )
        best["sourceStart"] = source_start
        best["sourceEnd"] = source_end
        best["score"] = round(best.pop("composite"), 2)
        best["locked"] = False
        alternatives: List[Dict[str, Any]] = []
        for index, entry in enumerate(scored):
            if index == choice:
                continue
            alternative_start, alternative_end = best_moment_window(
                clips_by_path.get(entry["clipPath"], {}), slot_length
            )
            alternatives.append({
                "clipPath": entry["clipPath"],
                "clipName": entry["clipName"],
                "thumbnailId": entry["thumbnailId"],
                "sceneType": entry["sceneType"],
                "shotType": entry["shotType"],
                "cameraMovement": entry["cameraMovement"],
                "clipDuration": entry["clipDuration"],
                "sourceStart": alternative_start,
                "sourceEnd": alternative_end,
                "score": round(entry["composite"], 2),
            })
            if len(alternatives) >= 4:
                break
        best["alternatives"] = alternatives

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
