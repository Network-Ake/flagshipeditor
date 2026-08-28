"""Choosing what goes in every slot, as one sequence rather than N decisions.

The engine this replaces scored each cut independently and took the winner.
With a four-cut no-repeat window and a least-recently-used tie-break, that is
not "picking the best shot" — it is a round-robin. Measured on a 3:30 track
with 24 clips, five clips were each used exactly 52 times, and 94.3 % of cuts
reused a source window that had already been on screen: only 49 distinct
windows across 857 cuts, one of them the same 0.22 seconds shown 51 times.

Independent scoring cannot fix that, because the defect is not in any single
choice. Every one of those cuts was locally optimal. The badness is a property
of the *sequence*, so the search has to be over sequences.

Beam search is the method. The state a good decision depends on — which clips
have been seen, how recently, which source windows have been spent, which
visual signatures are stacking up, which narrative roles the song still owes —
is too wide for exact dynamic programming (the state space is exponential in
the library size), and the problem is not an assignment problem because the
cost of putting a clip in a slot depends on what is in the neighbouring slots.
Beam search keeps the sequence-level view, runs in bounded time, and is
deterministic. Shot-assembly work in the literature reaches the same place.

Rejected alternatives, and why:

* **Exact DP over (slot, last-clip)** — cheap, but the state ignores global
  exposure and window reuse, which are precisely the two things that failed.
* **Hungarian / min-cost assignment** — requires the cost of a clip in a slot
  to be independent of the rest of the sequence. Continuity, contrast and
  reuse distance all violate that.
* **Greedy with stronger penalties** — what shipped. A penalty large enough to
  stop repetition also flattens the ranking; the rotation is what you get when
  the penalty wins.
"""

from __future__ import annotations

import ntpath
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

import numpy as np

from narrative import MotifLedger, NarrativePlan, NarrativeStage, classify_clip_roles, primary_role, role_affinity

# How many hypotheses survive each step. Wide enough that a locally weaker
# choice which sets up a better rest-of-song can win; narrow enough that a
# 500-clip library still plans in seconds.
DEFAULT_BEAM_WIDTH = 8

# Only the strongest candidates per slot are expanded. Bounds the search on a
# large library without changing the result on a small one.
CANDIDATE_POOL = 22

# Repetition control -------------------------------------------------------
# Distance, in cuts, below which reusing the same clip is penalised at all.
REUSE_HORIZON = 14
# Distance below which reusing the same *visual signature* — same framing, same
# face-presence, same movement class — is penalised. Shorter than the clip
# horizon because two different clips that look alike still read as a repeat.
SIGNATURE_HORIZON = 5
# Source windows this far apart in the same clip count as different material.
WINDOW_SEPARATION_SECONDS = 0.75
# The most distinct windows one clip is asked to yield. Also what the planner
# uses to estimate how much material the library holds, so the two agree on what
# "different material" means.
MAX_WINDOWS_PER_CLIP = 5
# Above this histogram similarity two clips are treated as near-duplicates and
# may not sit next to each other.
NEAR_DUPLICATE_SIMILARITY = 0.86

# Cost weights. Everything is expressed as a cost so the beam minimises; fit is
# negated on entry. These are the dials that decide whether the edit feels
# considered or mechanical, so each one is named rather than folded into a
# single magic constant.
W_FIT = 1.00
W_CLIP_REUSE = 2.40
W_WINDOW_REUSE = 3.60
W_SIGNATURE_REUSE = 1.55
W_NEAR_DUPLICATE = 2.90
W_ROLE = 1.30
W_EXPOSURE = 0.85
W_CONTINUITY = 0.55
W_RESERVE = 0.90
W_UNDERUSE = 0.70


def canonical_path(path: Any) -> str:
    """Deterministic identity for a clip. Selection accounting is keyed on it."""
    text = str(path or "").strip()
    if not text:
        return ""
    text = text.replace("\\", "/")
    while "//" in text:
        text = text.replace("//", "/")
    return text.rstrip("/").lower()


def clip_display_name(clip: Dict[str, Any]) -> str:
    name = str(clip.get("name", "") or "")
    if name:
        return name
    return ntpath.basename(str(clip.get("path", "") or "")) or "clip"


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if np.isfinite(number) else default


# ---------------------------------------------------------------------------
# Descriptors used for repetition control
# ---------------------------------------------------------------------------


def visual_signature(clip: Dict[str, Any]) -> Tuple[str, ...]:
    """A coarse description of what a shot *looks like*, for repeat detection.

    Two different files that are both a tight shot of a face against a dark
    background, handheld, read to a viewer as the same image — so the sequence
    has to control them together, not just control exact file reuse.

    This is deliberately **not** a claim about subject identity. Nothing here
    re-identifies a person; the engine has no face-recognition model and does
    not pretend to. It buckets measured descriptors, and the provenance says so.
    """
    shot = str(clip.get("shot_type", "unknown") or "unknown")
    scene = str(clip.get("scene_type", "unknown") or "unknown")
    movement = str(clip.get("camera_movement", "unknown") or "unknown")
    face = "face" if clip.get("has_face") else "noface"
    ratio = _finite(clip.get("face_size_ratio"))
    face_bucket = "none"
    if clip.get("has_face"):
        face_bucket = "tight" if ratio > 0.22 else "mid" if ratio > 0.09 else "wide"
    brightness = _finite(clip.get("brightness_mean"), _finite(clip.get("brightness_stability"), 50.0))
    light = "dark" if brightness < 34 else "bright" if brightness > 68 else "mid"
    return (shot, scene, movement, face, face_bucket, light)


def histogram_similarity(first: Any, second: Any) -> float:
    """1.0 identical, 0.0 maximally different. Mirrors the shipped distance metric."""
    try:
        left = np.array(first, dtype=np.float64).reshape(-1)
        right = np.array(second, dtype=np.float64).reshape(-1)
    except (TypeError, ValueError):
        return 0.5
    if left.size == 0 or left.size != right.size:
        return 0.5
    left_total, right_total = float(left.sum()), float(right.sum())
    if left_total <= 0 or right_total <= 0:
        return 0.5
    left /= left_total
    right /= right_total
    return float(max(0.0, min(1.0, 1.0 - 0.5 * np.abs(left - right).sum())))


def build_similarity_matrix(clips: Sequence[Dict[str, Any]]) -> np.ndarray:
    """Pairwise visual similarity, used to keep near-duplicates apart.

    Colour histogram carries most of the signal; matching shot scale and scene
    type push two clips further together, because "same framing of the same
    kind of thing in the same palette" is what a viewer registers as a repeat.
    """
    count = len(clips)
    if count == 0:
        return np.zeros((0, 0), dtype=np.float64)
    signatures = [visual_signature(clip) for clip in clips]

    # Histograms are compared as normalised L1 distance. Building one array and
    # broadcasting is what keeps a 500-clip library — 125 000 pairs — off the
    # critical path; the pairwise Python loop this replaces dominated planning
    # time on a large project.
    lengths = {
        len(clip.get("histogram") or ())
        for clip in clips
        if isinstance(clip.get("histogram"), (list, tuple, np.ndarray))
    }
    matrix = np.full((count, count), 0.5, dtype=np.float64)
    if len(lengths) == 1 and lengths != {0}:
        width = lengths.pop()
        stacked = np.zeros((count, width), dtype=np.float64)
        valid = np.zeros(count, dtype=bool)
        for index, clip in enumerate(clips):
            histogram = clip.get("histogram")
            if not isinstance(histogram, (list, tuple, np.ndarray)):
                continue
            values = np.asarray(histogram, dtype=np.float64).reshape(-1)
            total = float(values.sum())
            if values.size != width or total <= 0:
                continue
            stacked[index] = values / total
            valid[index] = True
        distance = np.abs(stacked[:, None, :] - stacked[None, :, :]).sum(axis=2)
        computed = np.clip(1.0 - 0.5 * distance, 0.0, 1.0)
        pair_valid = valid[:, None] & valid[None, :]
        matrix = np.where(pair_valid, computed, 0.5)
    else:
        for i in range(count):
            for j in range(i + 1, count):
                value = histogram_similarity(clips[i].get("histogram"), clips[j].get("histogram"))
                matrix[i, j] = matrix[j, i] = value

    # Matching descriptors push two clips further together: "same framing of the
    # same kind of thing in the same palette" is what a viewer reads as a repeat.
    signature_array = np.array(signatures, dtype=object)
    shared = np.zeros((count, count), dtype=np.float64)
    for field in range(signature_array.shape[1]):
        column = signature_array[:, field]
        known = column != "unknown"
        equal = (column[:, None] == column[None, :]) & known[:, None] & known[None, :]
        shared += equal.astype(np.float64)
    matrix = np.minimum(1.0, matrix * (1.0 + 0.06 * shared))
    np.fill_diagonal(matrix, 1.0)
    return matrix


# ---------------------------------------------------------------------------
# Source windows
# ---------------------------------------------------------------------------


class SourceWindow(NamedTuple):
    """A stretch of a clip's own timeline, and why it was chosen."""

    start: float
    end: float
    rank: int
    quality: float
    reason: str


def candidate_windows(
    clip: Dict[str, Any],
    slot_length: float,
    limit: int = MAX_WINDOWS_PER_CLIP,
) -> List[SourceWindow]:
    """Return distinct, ranked stretches of a clip worth cutting to.

    The engine this replaces had one window per clip: ``best_moment_window``
    was a pure function of the clip and the slot length, so a clip used eight
    times showed the *identical frames* eight times. That single fact accounts
    for most of the "extremely repetitive" complaint — 94.3 % of cuts reused a
    window, and the library only ever produced 49 distinct windows in total.

    Here a clip offers several windows: the analysed best moments first, then
    evenly spaced fallbacks across the clip's usable extent. Windows closer
    together than :data:`WINDOW_SEPARATION_SECONDS` are collapsed, so "a
    different window" always means genuinely different material rather than the
    same shot nudged by two frames.
    """
    duration = _finite(clip.get("duration"))
    slot_length = max(0.05, float(slot_length))
    if duration <= 0:
        return [SourceWindow(0.0, slot_length, 0, 0.5, "unknown_duration")]

    usable = max(0.0, duration - slot_length)
    windows: List[SourceWindow] = []

    def push(start: float, quality: float, reason: str) -> None:
        start = max(0.0, min(usable, float(start)))
        # Preserve a small incoming handle whenever the clip is longer than the
        # requested shot. Starting analysed moments at frame zero made them
        # indistinguishable from the old arbitrary clip-head fallback, and left
        # no room for a transition or a later source-window adjustment. Genuine
        # full-clip fallbacks still begin at zero when no handle is available.
        if reason != "clip_head" and usable >= 0.2:
            start = max(start, min(0.1, usable * 0.1))
        end = min(duration, start + slot_length)
        for existing in windows:
            if abs(existing.start - start) < WINDOW_SEPARATION_SECONDS:
                return
        windows.append(SourceWindow(round(start, 4), round(end, 4), len(windows), quality, reason))

    # Ranked moments published by clip analysis, when it found more than one.
    moments = clip.get("moment_windows")
    if isinstance(moments, (list, tuple)):
        for entry in moments:
            if not isinstance(entry, dict):
                continue
            peak = _finite(entry.get("time", entry.get("best_time")), -1.0)
            if peak < 0:
                continue
            push(peak - slot_length * 0.35, _finite(entry.get("score"), 0.6), "analysed_moment")

    best_moment = clip.get("best_moment")
    if isinstance(best_moment, dict):
        peak = _finite(best_moment.get("best_time"), -1.0)
        if peak >= 0:
            push(peak - slot_length * 0.35, _finite(best_moment.get("confidence"), 0.6) + 0.2, "best_moment")

    # Even fallbacks so a clip always has somewhere else to go. Quality decays
    # with distance from the analysed peak, which keeps the best material first
    # while making reuse possible without repeating frames.
    if usable > WINDOW_SEPARATION_SECONDS:
        divisions = max(2, min(6, int(usable / max(WINDOW_SEPARATION_SECONDS, slot_length * 0.75)) + 1))
        for index in range(divisions):
            push(usable * (index / max(1, divisions - 1)), 0.42 - 0.03 * index, "even_coverage")

    if not windows:
        push(0.0, 0.4, "clip_head")

    windows.sort(key=lambda window: (-window.quality, window.start))
    return [window._replace(rank=index) for index, window in enumerate(windows[:limit])]


# ---------------------------------------------------------------------------
# Beam search
# ---------------------------------------------------------------------------


class Hypothesis:
    """One candidate sequence, carrying everything a later choice depends on."""

    __slots__ = (
        "cost",
        "picks",
        "usage",
        "windows_used",
        "recent",
        "recent_signatures",
        "role_counts",
        "last_index",
        "motifs",
    )

    def __init__(self) -> None:
        self.cost: float = 0.0
        self.picks: List[Dict[str, Any]] = []
        self.usage: Dict[int, int] = {}
        self.windows_used: Dict[int, List[float]] = {}
        self.recent: List[int] = []
        self.recent_signatures: List[Tuple[str, ...]] = []
        self.role_counts: Dict[str, int] = {}
        self.last_index: int = -1
        self.motifs: List[Dict[str, Any]] = []

    def clone(self) -> "Hypothesis":
        other = Hypothesis()
        other.cost = self.cost
        other.picks = list(self.picks)
        other.usage = dict(self.usage)
        other.windows_used = {key: list(value) for key, value in self.windows_used.items()}
        other.recent = list(self.recent)
        other.recent_signatures = list(self.recent_signatures)
        other.role_counts = dict(self.role_counts)
        other.last_index = self.last_index
        other.motifs = list(self.motifs)
        return other

    def distance_since(self, clip_index: int, position: int) -> Optional[int]:
        for offset in range(1, min(len(self.recent), REUSE_HORIZON) + 1):
            if self.recent[-offset] == clip_index:
                return offset
        return None


class SlotContext(NamedTuple):
    """Everything about one slot the selector needs in order to score it."""

    index: int
    start: float
    end: float
    section_type: str
    mode: str
    stage: Optional[NarrativeStage]
    lyric_line: Any
    lyric_is_hook: bool
    in_vocal_rest: bool
    tension: float
    #: True when this slot opens a section. This used to be smuggled through
    #: ``mode == "boundary"``, which conflated *where the cut came from* with
    #: *how the shot it opens is paced* and left the slot with no pacing mode at
    #: all. ``origin`` in the cut provenance is the source of truth.
    opens_section: bool = False


def _window_conflict(used: Sequence[float], start: float) -> bool:
    return any(abs(existing - start) < WINDOW_SEPARATION_SECONDS for existing in used)


def select_sequence(
    slots: Sequence[SlotContext],
    clips: Sequence[Dict[str, Any]],
    base_scores: np.ndarray,
    similarity: np.ndarray,
    clip_roles: Sequence[Dict[str, float]],
    reserved: Sequence[bool],
    hook_slots: Sequence[bool],
    style_selection: Dict[str, float],
    beam_width: int = DEFAULT_BEAM_WIDTH,
) -> Tuple[List[Dict[str, Any]], MotifLedger, Dict[str, Any]]:
    """Search for the best whole sequence, not the best clip per slot.

    ``base_scores`` is ``[slot][clip]`` fit on the existing 0..100 scale, which
    keeps the published per-clip scoring contract intact — the change is what
    the engine does with those numbers, not how it computes them.

    Returns the chosen sequence, the motif ledger recording every justified
    repeat, and diagnostics describing what the search actually did.
    """
    count = len(clips)
    if count == 0 or not slots:
        return [], MotifLedger(), {"verdict": "no_input"}

    signatures = [visual_signature(clip) for clip in clips]
    repetition_tolerance = float(style_selection.get("repetition_tolerance", 0.25))
    continuity = float(style_selection.get("continuity", 0.5))
    subject_persistence = float(style_selection.get("subject_persistence", 0.45))

    # A small library physically cannot avoid repeating. Softening the
    # penalties in proportion is what makes it degrade honestly instead of
    # deadlocking or emptying the timeline.
    scarcity = max(0.0, min(1.0, 1.0 - count / max(1.0, len(slots) * 0.5)))
    reuse_scale = (1.0 - 0.75 * scarcity) * (1.0 - 0.5 * repetition_tolerance)

    # Fair share: how many cuts each clip would carry if the library were used
    # evenly. Exposure cost is measured against this rather than against a
    # fixed count, so the same rule works for 6 clips and for 600.
    fair_share = len(slots) / float(count)

    beam: List[Hypothesis] = [Hypothesis()]
    expansions = 0
    # Windows depend only on the clip and the slot length, and the beam asks
    # for the same pair thousands of times. Caching turns the search from
    # seconds into milliseconds on a large library.
    window_cache: Dict[Tuple[int, int], List[SourceWindow]] = {}

    def windows_for(clip_index: int, length: float) -> List[SourceWindow]:
        key = (clip_index, int(round(length * 100.0)))
        cached = window_cache.get(key)
        if cached is None:
            cached = candidate_windows(clips[clip_index], length)
            window_cache[key] = cached
        return cached

    for position, slot in enumerate(slots):
        slot_scores = base_scores[position]
        # Prune to a candidate pool. Ordering is by fit and then by index, so
        # the pool is deterministic.
        pool = list(np.argsort(-slot_scores, kind="stable")[:CANDIDATE_POOL])
        stage = slot.stage
        stage_roles = stage.roles if stage else ()

        candidates: List[Tuple[Any, ...]] = []
        for hypothesis in beam:
            # Adjacency is a *hard* constraint, not a penalty. Two identical or
            # visually equivalent shots back to back is the one repetition a
            # viewer cannot miss, and a penalty — however large — still loses to
            # a high enough score, which is exactly how the shipped engine put
            # the same shot next to itself. Candidates that would violate it are
            # removed from the pool rather than fined.
            allowed = [int(index) for index in pool]
            previous = hypothesis.last_index
            if previous >= 0 and len(allowed) > 1:
                filtered = [
                    index
                    for index in allowed
                    if index != previous
                    and float(similarity[previous][index]) < NEAR_DUPLICATE_SIMILARITY
                ]
                # Falling back keeps a two-clip library from deadlocking. The
                # relaxation is ordered so identity is given up last.
                if not filtered:
                    filtered = [
                        index for index in allowed
                        if float(similarity[previous][index]) < NEAR_DUPLICATE_SIMILARITY
                    ]
                if not filtered:
                    filtered = [index for index in allowed if index != previous]
                if filtered:
                    allowed = filtered

            for clip_index in allowed:
                clip_index = int(clip_index)
                fit = float(slot_scores[clip_index]) / 100.0
                cost = -W_FIT * fit
                notes: Dict[str, Any] = {}

                # --- clip reuse ----------------------------------------------
                distance = hypothesis.distance_since(clip_index, position)
                justification: Optional[Dict[str, Any]] = None
                if distance is not None:
                    closeness = 1.0 - distance / float(REUSE_HORIZON)
                    penalty = W_CLIP_REUSE * closeness * closeness * reuse_scale
                    # A repeat may be *intentional*. The ledger decides, and a
                    # justified callback pays a fraction of the cost.
                    tolerance = stage.motif_tolerance if stage else 0.25
                    if slot.lyric_is_hook or (tolerance >= 0.45 and hook_slots[position]):
                        justification = {
                            "reason": "lyric_callback" if slot.lyric_is_hook else "hook_callback",
                            "stage": stage.name if stage else "unknown",
                            "gapCuts": distance,
                            "motifTolerance": round(tolerance, 3),
                        }
                        penalty *= 0.35
                    cost += penalty
                    notes["reuseDistance"] = distance

                # --- source window reuse -------------------------------------
                used_windows = hypothesis.windows_used.get(clip_index, [])
                windows = windows_for(clip_index, slot.end - slot.start)
                chosen_window: Optional[SourceWindow] = None
                for window in windows:
                    if not _window_conflict(used_windows, window.start):
                        chosen_window = window
                        break
                if chosen_window is None:
                    # Every distinct window in this clip has been spent. Reusing
                    # one is allowed but expensive, and the pick records that it
                    # is showing frames the viewer has already seen.
                    chosen_window = windows[0]
                    cost += W_WINDOW_REUSE * reuse_scale
                    notes["windowExhausted"] = True
                else:
                    cost -= 0.12 * chosen_window.quality

                # --- visual signature reuse ----------------------------------
                signature = signatures[clip_index]
                for offset, previous in enumerate(hypothesis.recent_signatures[-SIGNATURE_HORIZON:]):
                    if previous == signature:
                        recency = 1.0 - offset / float(SIGNATURE_HORIZON)
                        cost += (
                            W_SIGNATURE_REUSE
                            * recency
                            * reuse_scale
                            * (1.0 - 0.5 * subject_persistence)
                        )
                        notes["signatureRepeat"] = True
                        break

                # --- near duplicates adjacent --------------------------------
                if hypothesis.last_index >= 0:
                    adjacency = float(similarity[hypothesis.last_index][clip_index])
                    if adjacency >= NEAR_DUPLICATE_SIMILARITY and hypothesis.last_index != clip_index:
                        cost += W_NEAR_DUPLICATE * (adjacency - NEAR_DUPLICATE_SIMILARITY) * 7.0
                        notes["nearDuplicateOfPrevious"] = round(adjacency, 4)
                    # Continuity versus contrast is a style choice: a patient
                    # preset wants adjacent shots to relate, an aggressive one
                    # wants them to collide.
                    target = 0.35 + 0.4 * continuity
                    cost += W_CONTINUITY * abs(adjacency - target)

                # --- narrative role ------------------------------------------
                affinity = role_affinity(stage, clip_roles[clip_index])
                cost += W_ROLE * (1.0 - affinity)
                if stage_roles:
                    role_name, _confidence = primary_role(clip_roles[clip_index])
                    seen = hypothesis.role_counts.get(role_name, 0)
                    # Roles should develop across the song rather than one role
                    # carrying everything.
                    cost += W_ROLE * 0.18 * min(1.0, seen / max(1.0, fair_share * 2.0))

                # --- global exposure -----------------------------------------
                used = hypothesis.usage.get(clip_index, 0)
                if used > fair_share:
                    cost += W_EXPOSURE * ((used - fair_share) / max(1.0, fair_share))
                elif used == 0 and position > len(slots) * 0.25:
                    # Footage that has never appeared is worth reaching for:
                    # coverage of the library is part of what makes the video
                    # feel authored rather than assembled from favourites.
                    cost -= W_UNDERUSE * 0.5

                # --- reservation ---------------------------------------------
                if reserved[clip_index] and not hook_slots[position]:
                    cost += W_RESERVE
                elif reserved[clip_index] and hook_slots[position]:
                    cost -= W_RESERVE * 0.6

                # Only the survivors are materialised. Cloning every candidate
                # meant copying the whole running state 22 times per beam per
                # slot; scoring first and cloning after the cut is a ~20x
                # reduction in allocation with an identical result.
                candidates.append(
                    (
                        hypothesis.cost + cost,
                        hypothesis,
                        clip_index,
                        chosen_window,
                        fit,
                        affinity,
                        notes,
                        justification,
                        signature,
                    )
                )
                expansions += 1

        if not candidates:
            break
        # Deterministic ordering: cost first, then the sequence of clip indices
        # reached so far, so two candidates with identical cost always resolve
        # the same way regardless of dict or set iteration order.
        candidates.sort(key=lambda item: (round(item[0], 9), tuple(item[1].recent), item[2]))

        next_beam = []
        for (
            total_cost,
            parent,
            clip_index,
            chosen_window,
            fit,
            affinity,
            notes,
            justification,
            signature,
        ) in candidates[:beam_width]:
            child = parent.clone()
            child.cost = total_cost
            child.picks.append(
                {
                    "clipIndex": clip_index,
                    "window": chosen_window,
                    "fit": fit,
                    "roleAffinity": affinity,
                    "notes": notes,
                    "motif": justification,
                }
            )
            child.usage[clip_index] = child.usage.get(clip_index, 0) + 1
            child.windows_used.setdefault(clip_index, []).append(chosen_window.start)
            child.recent.append(clip_index)
            child.recent_signatures.append(signature)
            role_name, _confidence = primary_role(clip_roles[clip_index])
            child.role_counts[role_name] = child.role_counts.get(role_name, 0) + 1
            child.last_index = clip_index
            if justification:
                child.motifs.append(dict(justification, cutIndex=position))
            next_beam.append(child)
        beam = next_beam

    best = beam[0]
    ledger = MotifLedger()
    for position, pick in enumerate(best.picks):
        clip = clips[pick["clipIndex"]]
        ledger.record(canonical_path(clip.get("path")), slots[position].start,
                      slots[position].stage.name if slots[position].stage else "unknown", position)
        if pick.get("motif"):
            ledger.accept(canonical_path(clip.get("path")), pick["motif"])

    diagnostics = {
        "beamWidth": beam_width,
        "candidatePool": min(CANDIDATE_POOL, count),
        "expansions": expansions,
        "finalCost": round(best.cost, 4),
        "scarcity": round(scarcity, 4),
        "reuseScale": round(reuse_scale, 4),
        "distinctClipsUsed": len(best.usage),
        "libraryCoverage": round(len(best.usage) / float(count), 4),
    }
    return best.picks, ledger, diagnostics


# ---------------------------------------------------------------------------
# Transitions
# ---------------------------------------------------------------------------

TRANSITIONS = (
    "hard_cut",
    "cut_on_action",
    "match_cut",
    "motion_continuation",
    "motion_contrast",
    "phrase_transition",
    "hold_through",
    "speed_ramp",
    "dissolve",
    "fade",
)


def decide_transition(
    previous: Optional[Dict[str, Any]],
    current: Dict[str, Any],
    slot: SlotContext,
    similarity_value: float,
    style_selection: Dict[str, float],
) -> Dict[str, Any]:
    """Choose a transition from the two shots it actually joins.

    Nothing is randomised and nothing is applied to hide a weak selection. Each
    branch names the evidence it used, so a reviewer can see why a dissolve
    appeared instead of finding one sprinkled at a configured percentage — which
    is what the competitor presets this product was benchmarked against do.
    """
    if previous is None:
        return {"type": "hard_cut", "reason": "first_shot", "evidence": {}}

    previous_movement = str(previous.get("cameraMovement", "unknown") or "unknown")
    current_movement = str(current.get("cameraMovement", "unknown") or "unknown")
    previous_shot = str(previous.get("shotType", "unknown") or "unknown")
    current_shot = str(current.get("shotType", "unknown") or "unknown")

    evidence = {
        "previousMovement": previous_movement,
        "movement": current_movement,
        "similarity": round(float(similarity_value), 4),
        "sectionType": slot.section_type,
        "mode": slot.mode,
        "opensSection": bool(slot.opens_section),
    }

    # A section boundary that is also a phrase turn is the one place a soft
    # transition is defensible in this idiom.
    if slot.opens_section and slot.section_type in ("outro", "bridge", "intro"):
        return {"type": "phrase_transition", "reason": "section_change_low_energy", "evidence": evidence}

    if slot.in_vocal_rest and slot.tension < 0.32 and similarity_value > 0.62:
        return {"type": "dissolve", "reason": "vocal_rest_related_images", "evidence": evidence}

    if similarity_value >= NEAR_DUPLICATE_SIMILARITY - 0.06 and previous_shot != current_shot:
        return {"type": "match_cut", "reason": "similar_frame_different_scale", "evidence": evidence}

    if previous_movement != "static" and previous_movement == current_movement:
        return {"type": "motion_continuation", "reason": "same_camera_movement", "evidence": evidence}

    if previous_movement not in ("static", "unknown") and current_movement == "static":
        return {"type": "motion_contrast", "reason": "movement_into_stillness", "evidence": evidence}

    if slot.mode == "burst":
        return {"type": "hard_cut", "reason": "inside_burst", "evidence": evidence}

    if slot.mode == "breath":
        return {"type": "hold_through", "reason": "sustained_shot", "evidence": evidence}

    if _finite(current.get("clipMotion")) > 55 and slot.tension > 0.62:
        return {"type": "cut_on_action", "reason": "high_motion_high_tension", "evidence": evidence}

    return {"type": "hard_cut", "reason": "default", "evidence": evidence}
