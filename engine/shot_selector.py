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

from cut_planner import (
    MIN_SUSTAINED_SECONDS,
    PlannedCut,
    duration_histogram,
    material_pacing_scale,
    plan_musical_cuts,
    resolve_pacing,
)
from musical_structure import (
    build_event_lattice,
    infer_beats_per_bar,
    musical_grid,
    tension_curve,
)
from narrative import (
    MotifLedger,
    build_narrative_plan,
    classify_clip_roles,
    primary_role,
)
import lyric_analysis
import sequence_selector
from sequence_selector import (
    MAX_WINDOWS_PER_CLIP,
    WINDOW_SEPARATION_SECONDS,
    SlotContext,
    build_similarity_matrix,
    canonical_path as _sequence_path,
    candidate_windows,
    decide_transition,
    select_sequence,
    visual_signature,
)

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

# Top-level provenance distinguishes how the planner resolved the boundary;
# the musical reason is published separately as ``eventKind``. This keeps one
# stable schema for downbeats, phrases, lyrics, played accents and action cues
# instead of overloading ``origin`` with both mechanism and meaning.
CUT_ORIGINS = ("boundary", "event", "fallback")
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

# How much a trusted lyric line may move a clip's fit, on the 0..100 scale.
# Deliberately modest. A lyric is one input among several, and an engine that
# lets the words dominate produces the literal, on-the-nose result the brief
# explicitly rules out — "car" fetching a car every time is not direction, it
# is illustration.
LYRIC_WEIGHT = 9.0

# Maps a lyric's imagery onto the narrative roles footage can play. This is the
# indirection that keeps the edit from being literal: a line about money does
# not ask for a shot of money, it raises detail and celebration footage, and
# everything else about the cut still gets a vote.
LYRIC_IMAGERY_ROLES: Dict[str, Tuple[str, ...]] = {
    "environment": ("environment", "establishing"),
    "establishing": ("establishing", "environment"),
    "architecture": ("establishing", "environment"),
    "low_light": ("environment", "symbolic"),
    "neon": ("environment", "detail"),
    "vehicle": ("action", "bridge"),
    "travel": ("bridge", "action", "establishing"),
    "motion": ("action", "escalation"),
    "face": ("emotional", "character", "performance"),
    "closeness": ("emotional", "character"),
    "touch": ("detail", "emotional"),
    "direct_address": ("performance", "character"),
    "performance": ("performance",),
    "crowd": ("action", "environment"),
    "light": ("symbolic", "environment"),
    "excess": ("detail", "action"),
    "cash": ("detail",),
    "jewellery": ("detail",),
    "exchange": ("detail", "action"),
    "tension": ("escalation", "reaction"),
    "confrontation": ("action", "reaction"),
    "threat": ("escalation", "symbolic"),
    "group": ("action", "environment"),
    "gesture": ("detail", "reaction"),
    "absence": ("environment", "symbolic"),
    "memory": ("symbolic", "resolution"),
    "stillness": ("resolution", "symbolic", "emotional"),
    "ascent": ("escalation", "establishing"),
    "work": ("action", "detail"),
    "distance": ("establishing", "environment"),
    "effort": ("action", "escalation"),
    "weight": ("emotional", "symbolic"),
    "endurance": ("emotional", "resolution"),
    "haze": ("environment", "symbolic"),
    "close_detail": ("detail",),
    "slow": ("resolution", "emotional"),
    "isolation": ("symbolic", "environment"),
    "turning_away": ("reaction", "symbolic"),
    "elevation": ("establishing", "symbolic"),
    "passage": ("bridge", "environment"),
    "contrast": ("symbolic",),
}

# How a lyric is allowed to be answered. Rotating deterministically through
# these — rather than always taking the first — is what stops the same line
# producing the same kind of image every time it recurs, which is the specific
# failure the brief calls "excessive literalism".
LYRIC_RESPONSES = ("literal", "emotional", "symbolic", "performance", "contrast", "restraint")


def _lyric_affinity(line: Any, roles: Dict[str, float], clip: Dict[str, Any]) -> float:
    """Return −1..1 for how well a clip answers a lyric line.

    The answer is not always literal correspondence. The response mode is
    chosen deterministically from the line's own index, its intensity and its
    address, so a hook that recurs four times is answered four different ways —
    once by illustrating it, once by the face delivering it, once by an image
    that stands for it, once by holding back. A human editor does exactly this;
    matching every line the same way is what reads as a machine.
    """
    mode = LYRIC_RESPONSES[
        int(
            (line.index * 2 + int(line.intensity * 3) + (1 if line.address == "first_person" else 0))
            % len(LYRIC_RESPONSES)
        )
    ]

    if mode == "restraint":
        # Deliberately no opinion: the words are left to carry the moment.
        return 0.0

    if mode == "performance":
        return float(roles.get("performance", 0.0) * 0.9 + roles.get("character", 0.0) * 0.5) - 0.15

    wanted: Dict[str, float] = {}
    for item in line.imagery:
        for rank, role in enumerate(LYRIC_IMAGERY_ROLES.get(item, ())):
            wanted[role] = max(wanted.get(role, 0.0), 1.0 - 0.25 * rank)
    if not wanted:
        return 0.0

    match = 0.0
    for role, weight in wanted.items():
        match = max(match, roles.get(role, 0.0) * weight)

    if mode == "literal":
        return float(match) - 0.15
    if mode == "emotional":
        # Answer the feeling rather than the noun: intensity and valence steer
        # towards emotional or escalating footage instead of the named object.
        emotional = roles.get("emotional", 0.0) if line.valence < 0 else roles.get("escalation", 0.0)
        return float(0.55 * match + 0.65 * emotional) - 0.15
    if mode == "symbolic":
        return float(0.35 * match + 0.85 * roles.get("symbolic", 0.0)) - 0.15
    # contrast: reward footage that does *not* illustrate the line, which is
    # how an editor undercuts a lyric on purpose.
    return float(0.55 * (1.0 - min(1.0, match)) * roles.get("neutral", 0.0) * 2.0) - 0.2



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


def available_material_scale(
    clips: Sequence[Dict[str, Any]],
    duration: float,
    style_config: Optional[Dict[str, Any]] = None,
) -> float:
    """How much the pacing must stretch for the library the editor actually has.

    Counts the distinct source windows the library can offer — the same
    ``WINDOW_SEPARATION_SECONDS`` rule the selector uses, so the planner and the
    selector agree on what "different material" means — and asks the planner to
    slow down if the song wants more cuts than that material can carry.

    A normal shoot returns 1.0 and nothing changes. It is one clip, or four,
    that used to produce a timeline indistinguishable from a hundred-clip one.
    """
    if not clips or duration <= 0:
        return 1.0

    targets = [
        resolve_pacing(section_type, style_config).target_bars
        for section_type in ("verse", "chorus", "drop", "intro", "outro")
    ]
    # A bar in seconds is not known here, so work from the style's mean target
    # in bars against a nominal four-beat bar at the track's own tempo. The
    # ratio is what matters, and it is tempo-invariant either way.
    mean_target_bars = float(np.mean(targets)) if targets else 2.5

    windows = 0
    for clip in clips:
        clip_duration = bounded_duration(clip.get("duration"))
        if clip_duration <= 0:
            windows += 1
            continue
        analysed = clip.get("moment_windows")
        offered = len(analysed) if isinstance(analysed, (list, tuple)) and analysed else 0
        spread = 1 + int(max(0.0, clip_duration - MIN_SUSTAINED_SECONDS) / WINDOW_SEPARATION_SECONDS)
        windows += max(1, min(MAX_WINDOWS_PER_CLIP, max(offered, spread)))

    # Nominal shot length in seconds for the scale calculation: bars are only
    # meaningful against a tempo, and the caller's tempo cancels out of the
    # ratio, so a 2 s bar is used consistently on both sides.
    nominal_bar_seconds = 2.0
    return material_pacing_scale(
        windows, duration, mean_target_bars * nominal_bar_seconds
    )


def plan_cuts(
    beats: Sequence[float],
    sections: Sequence[Dict[str, Any]],
    style_config: Dict[str, Any],
    duration: float,
    tempo: float = 0.0,
    bass_onsets: Optional[Sequence[float]] = None,
    phrase_boundaries: Optional[Sequence[Any]] = None,
    downbeats: Optional[Sequence[float]] = None,
    energy: Optional[Sequence[Any]] = None,
    energy_times: Optional[Sequence[Any]] = None,
    lyrics: Any = None,
    material_scale: float = 1.0,
) -> List[Dict[str, Any]]:
    """Lay out the timeline from musical events at a varying, section-led pace.

    This used to walk a metronome — ``position += interval_beats`` from the
    style's ``cut_interval`` — and that is what produced the mechanical result:
    857 cuts on a 3:30 track, nine distinct shot lengths, 636 of them identical,
    a 0.21 s median across verses and choruses alike.

    The walk is now over the *musical event lattice*: bar lines, phrase turns,
    played accents, vocal entries and section boundaries, which are unevenly
    spaced by construction. Each shot draws its own target length from the
    section's pacing range in bars, modulated by measured tension, and then
    lands on the best real event near that target. Fast runs still happen, as
    bounded bursts entered on measured evidence, not as the baseline.

    The returned shape is unchanged — ``beatTime``, ``endTime``,
    ``sectionType`` and ``cutProvenance`` — so the After Effects bridge and the
    panel need no translation. ``cutProvenance`` now also carries the pacing
    mode, the requested and achieved length in bars, and the local tension, so
    any claim about why a cut is where it is can be checked.
    """
    duration = float(duration) if np.isfinite(duration) else 0.0
    if duration <= 0:
        return []

    beat_times = _clean_times(beats)
    downbeat_times = _clean_times(downbeats)
    onsets = _clean_times(bass_onsets)
    phrases = [value for value in _phrase_times(phrase_boundaries) if 0.0 < value < duration]
    style_config = style_config or {}

    ordered_sections = normalize_sections(sections, duration)
    if not ordered_sections:
        return []

    beats_per_bar = infer_beats_per_bar(beat_times, downbeat_times)
    grid = musical_grid(beat_times, tempo, beats_per_bar)

    curve = tension_curve(
        duration,
        energy=energy,
        energy_times=energy_times,
        onsets=onsets,
        accents=onsets,
        vocal_segments=[
            {"start": segment.start, "end": segment.end}
            for segment in getattr(lyrics, "vocal_segments", ()) or ()
        ],
    )

    lattice = build_event_lattice(
        duration=duration,
        grid=grid,
        beats=beat_times,
        downbeats=downbeat_times,
        phrase_boundaries=phrases,
        section_boundaries=[float(section["start"]) for section in ordered_sections],
        accents=onsets,
        vocal_entries=lyrics.vocal_entries() if lyrics is not None else (),
        vocal_exits=lyrics.vocal_exits() if lyrics is not None else (),
        lyric_lines=[
            {"start": line.start}
            for line in getattr(lyrics, "lines", ()) or ()
            if line.start is not None
            and line.timing_confidence >= lyric_analysis.MIN_TIMING_CONFIDENCE
        ],
    )

    planned = plan_musical_cuts(
        sections=ordered_sections,
        lattice=lattice,
        grid=grid,
        duration=duration,
        style_config=style_config,
        tension=curve,
        lyrics=lyrics,
        accents=onsets,
        material_scale=material_scale,
    )
    if not planned:
        return []
    if len(planned) > MAX_CUTS:
        planned = planned[:MAX_CUTS]

    snap_tolerance = min(CUT_SNAP_TOLERANCE_SECONDS, grid.period * 0.25)
    beat_array = np.asarray(beat_times, dtype=np.float64) if beat_times else np.asarray([])

    slots: List[Dict[str, Any]] = []
    for cut in planned:
        beat_delta = (
            float(np.min(np.abs(beat_array - cut.start))) if beat_array.size else None
        )
        slots.append(
            {
                "beatTime": round(float(cut.start), 6),
                "endTime": round(float(cut.end), 6),
                "sectionType": cut.section_type,
                "cutProvenance": {
                    "origin": cut.origin,
                    "eventKind": cut.event_kind,
                    "sourceTime": round(float(cut.source_time), 6),
                    "snapDelta": round(float(cut.start - cut.source_time), 6),
                    "beatDelta": round(beat_delta, 6) if beat_delta is not None else None,
                    "beatAligned": bool(
                        beat_delta is not None and beat_delta <= snap_tolerance
                    ),
                    "snapTolerance": round(float(snap_tolerance), 6),
                    "measuredEvent": bool(cut.measured),
                    "pacingMode": cut.mode,
                    "targetBars": cut.target_bars,
                    "actualBars": cut.actual_bars,
                    "tension": round(float(cut.tension), 4),
                    "beatsPerBar": grid.beats_per_bar,
                    "gridRegularity": round(float(grid.regularity), 4),
                },
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
    lyrics: Any = None,
    beam_width: int = sequence_selector.DEFAULT_BEAM_WIDTH,
) -> List[Dict[str, Any]]:
    """Plan the timeline and choose the whole sequence of shots.

    The order of operations is the point. Before any clip is picked the engine
    establishes what the song *is*: where the musical events are, how hard it is
    pushing at each moment, what the words say when they can be trusted, and
    what narrative arc that evidence supports. Only then are shots chosen — and
    chosen as a sequence, by beam search, so a locally weaker pick that leaves
    the hook with fresh footage can win.

    This replaces per-slot greedy scoring. That approach was not merely
    suboptimal: with a four-cut no-repeat window and a least-recently-used
    tie-break it degenerated into a round-robin, and because the source window
    was a pure function of the clip, a reused clip showed identical frames every
    time. 94.3 % of cuts on the measured baseline reused a window.

    Selection remains fully deterministic — no sampling, no exploration — so a
    re-run never reshuffles an approved sequence. ``seed`` is accepted for API
    compatibility and deliberately unused.

    Every returned cut carries its musical, lyrical, visual, narrative, source
    and decision provenance, which is what makes the result reviewable and what
    lets a later learning pass reconstruct why each choice was made.
    """
    style_config = style_config or {}
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
        energy=energy,
        energy_times=energy_times,
        lyrics=lyrics,
        material_scale=available_material_scale(usable_clips, duration, style_config),
    )
    if not slots:
        return []

    ordered_sections = normalize_sections(sections, duration)
    energy_curve = track_energy_curve(
        energy, energy_times, duration, energy_hop_length, energy_sample_rate
    )
    tension = tension_curve(
        duration,
        energy=energy,
        energy_times=energy_times,
        onsets=_clean_times(bass_onsets),
        accents=_clean_times(bass_onsets),
        vocal_segments=[
            {"start": segment.start, "end": segment.end}
            for segment in getattr(lyrics, "vocal_segments", ()) or ()
        ],
    )

    hook_window = resolve_hook_window(
        hook, ordered_sections, _clean_times(bass_onsets), duration
    )
    plan = build_narrative_plan(
        ordered_sections, duration, tension, lyrics, hook_window
    )

    reserved_paths = reserved_clip_paths(usable_clips) if hook_window else set()
    clip_paths = [str(clip.get("path", "")) for clip in usable_clips]
    clip_roles = [classify_clip_roles(clip) for clip in usable_clips]
    reserved_flags = [path in reserved_paths for path in clip_paths]
    similarity = build_similarity_matrix(usable_clips)

    style_selection = dict(style_config.get("selection") or {})
    lyric_sensitivity = float(style_selection.get("lyric_sensitivity", 0.7))
    lyric_usable = bool(lyrics is not None and getattr(lyrics, "can_interpret", False))
    hook_line_keys = set(getattr(lyrics, "hook_lines", ()) or ())

    # --- build the per-slot context and the fit matrix ---------------------
    contexts: List[SlotContext] = []
    hook_slots: List[bool] = []
    section_score_cache: Dict[str, List[Dict[str, Any]]] = {}
    base_scores = np.zeros((len(slots), len(usable_clips)), dtype=np.float64)

    for index, slot in enumerate(slots):
        section_type = slot["sectionType"]
        slot_start = float(slot["beatTime"])
        slot_end = float(slot["endTime"])
        slot_length = max(MIN_CUT_SECONDS, slot_end - slot_start)
        provenance = slot.get("cutProvenance") or {}

        stage = plan.stage_at(slot_start)
        line = lyrics.line_at(slot_start) if lyrics is not None else None
        line_is_hook = bool(
            line is not None
            and hook_line_keys
            and " ".join(lyric_analysis.tokenize(line.text)) in hook_line_keys
        )
        in_rest = bool(
            lyrics is not None
            and getattr(lyrics, "vocal_segments", ())
            and lyrics.in_vocal_rest(slot_start, slot_end)
        )
        in_hook = bool(hook_window) and slot_start < hook_window[1] and slot_end > hook_window[0]

        contexts.append(
            SlotContext(
                index=index,
                start=slot_start,
                end=slot_end,
                section_type=section_type,
                mode=str(provenance.get("pacingMode", "sustain")),
                opens_section=str(provenance.get("origin", "")) == "boundary",
                stage=stage,
                lyric_line=line,
                lyric_is_hook=line_is_hook,
                in_vocal_rest=in_rest,
                tension=float(provenance.get("tension", 0.5)),
            )
        )
        hook_slots.append(in_hook)

        energy_target = cut_energy_target(
            energy_curve, section_type, slot_start, slot_end, style_config
        )
        affinity = section_affinity(section_type, style_config)
        shots = shot_affinity(section_type, style_config)
        movements = movement_affinity(section_type, style_config)

        # The section-dependent part of the score is identical for every slot
        # in a section, so it is computed once. Only the energy term, which
        # tracks the measured curve cut by cut, is recomputed per slot. On a
        # 500-clip library this is the difference between scoring the library
        # once per section and once per cut.
        cached = section_score_cache.get(section_type)
        if cached is None:
            cached = [
                score_clip(
                    clip, None, section_type, affinity, shots, movements,
                    style_config, None,
                )
                for clip in usable_clips
            ]
            section_score_cache[section_type] = cached

        for clip_index, clip in enumerate(usable_clips):
            result = cached[clip_index]
            composite = result["composite"] + energy_match_adjustment(
                clip, section_type, style_config, energy_target
            )

            # A clip shorter than the slot has to be stretched or leaves a gap.
            clip_length = bounded_duration(clip.get("duration"))
            if clip_length and clip_length < slot_length:
                shortfall = min(1.0, (slot_length - clip_length) / slot_length)
                composite = max(0.0, composite - SHORT_CLIP_PENALTY * shortfall)

            # Lyric influence. Gated on interpretation confidence: a line the
            # lexicon did not understand may not choose a shot, and a line
            # whose alignment is weak may not either. Imagery is matched
            # against the clip's narrative roles rather than literally, so a
            # line about a car does not demand a car — it raises movement and
            # action footage and leaves the choice to the rest of the evidence.
            if lyric_usable and line is not None and not line.is_ad_lib:
                if line.interpretation_confidence >= lyric_analysis.MIN_INTERPRETATION_CONFIDENCE:
                    composite += _lyric_affinity(
                        line, clip_roles[clip_index], clip
                    ) * LYRIC_WEIGHT * lyric_sensitivity

            base_scores[index][clip_index] = max(0.0, min(100.0, composite))

    picks, ledger, search_diagnostics = select_sequence(
        slots=contexts,
        clips=usable_clips,
        base_scores=base_scores,
        similarity=similarity,
        clip_roles=clip_roles,
        reserved=reserved_flags,
        hook_slots=hook_slots,
        style_selection=style_selection,
        beam_width=beam_width,
    )
    if not picks:
        return []

    # --- publish -----------------------------------------------------------
    selections: List[Dict[str, Any]] = []
    previous_published: Optional[Dict[str, Any]] = None
    previous_index = -1

    for index, pick in enumerate(picks):
        context = contexts[index]
        slot = slots[index]
        clip_index = pick["clipIndex"]
        clip = usable_clips[clip_index]
        window = pick["window"]
        role_name, role_confidence = primary_role(clip_roles[clip_index])

        entry = score_clip(
            clip,
            usable_clips[previous_index] if previous_index >= 0 else None,
            context.section_type,
            section_affinity(context.section_type, style_config),
            shot_affinity(context.section_type, style_config),
            movement_affinity(context.section_type, style_config),
            style_config,
            cut_energy_target(
                energy_curve, context.section_type, context.start, context.end, style_config
            ),
        )
        best: Dict[str, Any] = dict(entry)
        best["beatTime"] = slot["beatTime"]
        best["endTime"] = slot["endTime"]
        best["sectionType"] = context.section_type
        best["sourceStart"] = window.start
        best["sourceEnd"] = window.end
        best["clipDuration"] = bounded_duration(clip.get("duration"))
        best["score"] = round(float(base_scores[index][clip_index]), 2)
        best.pop("composite", None)
        best["locked"] = False

        adjacency = (
            float(similarity[previous_index][clip_index]) if previous_index >= 0 else 0.0
        )
        best["transition"] = decide_transition(
            previous_published, best, context, adjacency, style_selection
        )

        best["cutProvenance"] = dict(
            slot.get("cutProvenance") or {},
            energyTarget=round(
                float(
                    cut_energy_target(
                        energy_curve, context.section_type, context.start, context.end, style_config
                    )
                ),
                4,
            ),
            energySource="measured_curve" if energy_curve is not None else "section_default",
        )
        best["narrative"] = {
            "stage": context.stage.name if context.stage else "unknown",
            "stageConfidence": round(context.stage.confidence, 4) if context.stage else 0.0,
            "role": role_name,
            "roleConfidence": round(role_confidence, 4),
            "roleAffinity": round(float(pick["roleAffinity"]), 4),
            "planConfidence": round(plan.confidence, 4),
        }
        best["sourceProvenance"] = {
            "windowRank": window.rank,
            "windowReason": window.reason,
            "windowQuality": round(float(window.quality), 4),
            "windowExhausted": bool(pick["notes"].get("windowExhausted", False)),
            "clipDuration": best["clipDuration"],
        }
        best["repetition"] = {
            "reuseDistance": pick["notes"].get("reuseDistance"),
            "signatureRepeat": bool(pick["notes"].get("signatureRepeat", False)),
            "nearDuplicateOfPrevious": pick["notes"].get("nearDuplicateOfPrevious"),
            "visualSignature": list(visual_signature(clip)),
            "signatureMethod": "descriptor_buckets_not_identity",
            "intentional": pick.get("motif"),
        }
        line = context.lyric_line
        if line is not None:
            best["lyric"] = {
                "text": line.text,
                "start": line.start,
                "end": line.end,
                "timingConfidence": round(line.timing_confidence, 4),
                "interpretationConfidence": round(line.interpretation_confidence, 4),
                "fields": [name for name, _weight in line.fields],
                "imagery": list(line.imagery),
                "isAdLib": line.is_ad_lib,
                "isHookLine": context.lyric_is_hook,
                "influencedSelection": bool(
                    lyric_usable
                    and not line.is_ad_lib
                    and line.interpretation_confidence
                    >= lyric_analysis.MIN_INTERPRETATION_CONFIDENCE
                ),
                "timingSource": line.timing_source,
                "alternatives": [name for name, _weight in line.alternatives],
            }
        elif lyrics is not None and getattr(lyrics, "vocal_segments", ()):
            best["lyric"] = {
                "text": None,
                "inVocalRest": context.in_vocal_rest,
                "influencedSelection": False,
                "timingSource": getattr(lyrics, "tier", "vocal_only"),
            }

        # Alternatives for the panel's swap picker, ranked by the same fit the
        # sequence used, with their own distinct source windows so a swap does
        # not silently reintroduce a frame the timeline already spent.
        order = np.argsort(-base_scores[index], kind="stable")
        alternatives: List[Dict[str, Any]] = []
        for other in order:
            other = int(other)
            if other == clip_index:
                continue
            other_clip = usable_clips[other]
            other_windows = candidate_windows(other_clip, context.end - context.start)
            other_window = other_windows[0]
            other_role, other_confidence = primary_role(clip_roles[other])
            alternatives.append(
                {
                    "clipPath": str(other_clip.get("path", "")),
                    "clipName": str(other_clip.get("name", "")),
                    "thumbnailId": str(other_clip.get("thumbnail_id", "")),
                    "sceneType": str(other_clip.get("scene_type", "unknown")),
                    "shotType": str(other_clip.get("shot_type", "unknown")),
                    "cameraMovement": str(other_clip.get("camera_movement", "unknown")),
                    "clipDuration": bounded_duration(other_clip.get("duration")),
                    "sourceStart": other_window.start,
                    "sourceEnd": other_window.end,
                    "score": round(float(base_scores[index][other]), 2),
                    "narrativeRole": other_role,
                    "roleConfidence": round(other_confidence, 4),
                    "similarityToChosen": round(float(similarity[clip_index][other]), 4),
                }
            )
            if len(alternatives) >= 4:
                break
        best["alternatives"] = alternatives

        selections.append(best)
        previous_published = best
        previous_index = clip_index

    if selections:
        selections[0]["editProvenance"] = {
            "planner": "musical_event_lattice",
            "selector": "beam_search_global_sequence",
            "narrativePlan": plan.as_dict(),
            "motifs": ledger.as_dict(),
            "search": search_diagnostics,
            "lyrics": lyrics.as_dict() if lyrics is not None else {"tier": "none"},
            "pacing": duration_histogram(
                [
                    PlannedCut(
                        float(slot["beatTime"]), float(slot["endTime"]),
                        slot["sectionType"], "", 0.0, "", True,
                        str((slot.get("cutProvenance") or {}).get("pacingMode", "sustain")),
                        0.0, 0.0, 0.0,
                    )
                    for slot in slots
                ]
            ),
        }
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
