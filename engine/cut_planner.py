"""Where the cuts go — driven by musical events, not by a subdivision counter.

The engine this replaces walked ``position += interval_beats`` from a style
preset's ``cut_interval``. Measured on a 140 BPM track with the shipped
``worldwide_films`` preset, that produced 857 cuts across 3:30 with **nine
distinct shot lengths**; 636 of them were the same 0.214 s, and the rest were
the 0.15 s minimum-spacing clamp. Median shot length across the whole video —
verses included — was 0.21 s. For scale, MVX's own demo produces 107 cuts from
49 clips, and the shot-length convention for a commercial music video is
roughly one to two bars in a hook and two to four in a verse.

Three changes fix it, and all three matter:

* **Pacing is a distribution in bars, not a constant in beats.** A section
  declares the shortest, typical and longest it wants a shot to run. Every shot
  draws its own target from that range, so the section has a *shape* instead of
  a rate. Bars rather than seconds keeps the intent tempo-invariant.

* **The target is a request, not the answer.** The planner asks the event
  lattice for the best musical moment near the target — a bar line, a phrase
  turn, a vocal entry, a played 808. Those are unevenly spaced by construction,
  so the resulting durations are unequal even when every cut lands on
  something musical.

* **Modes.** A shot can *breathe* (the voice has stopped, the mix has emptied,
  hold), or the edit can enter a *burst* (a run of short cuts, entered on
  measured evidence and exited deliberately). Bursts are how fast cutting stays
  an effect rather than becoming the baseline.

Everything is deterministic. Variation comes from a golden-ratio additive
sequence keyed to the cut index, which is equidistributed — it spreads targets
across the allowed range instead of clustering them — and reproducible, so the
same track and library always yield the same edit.
"""

from __future__ import annotations

from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

import numpy as np

from musical_structure import (
    MusicalEvent,
    MusicalGrid,
    TensionCurve,
    events_between,
)

# Shortest cut that reads as an edit rather than a flash frame.
MIN_CUT_SECONDS = 0.15

# The absolute floor on a *non-burst* shot. A single frame of black between two
# shots is a glitch; a fifth of a second repeated four hundred times is a
# strobe. Outside a deliberate burst the planner will not go below this, which
# is the structural reason the old engine's 0.21 s median cannot recur.
MIN_SUSTAINED_SECONDS = 0.45

MAX_CUTS = 20000

# Golden-ratio conjugate. Successive multiples mod 1 are equidistributed, which
# is what gives per-shot variation without a random number generator and
# therefore without breaking determinism.
_PHI_CONJUGATE = 0.6180339887498949


class PacingProfile(NamedTuple):
    """How a section wants to be cut, in bars.

    Expressing this in bars rather than beats is the point: "hold for two bars"
    is the same editorial instruction at 75 and at 170 BPM, whereas the old
    ``0.125_beat`` meant a 53 ms shot at 140 BPM and was silently clamped by
    the minimum-spacing rule into a uniform 0.16 s machine-gun.
    """

    min_bars: float          #: shortest ordinary shot
    target_bars: float       #: what the section reaches for
    max_bars: float          #: longest ordinary shot
    burstiness: float        #: 0..1 — appetite for runs of short cuts
    breath: float            #: 0..1 — appetite for long holds when the music allows
    burst_bars: float        #: length of one shot inside a burst
    #: Lattice event kinds this section prefers to land on, best first. A
    #: verse turning over on bar lines and a drop landing on played 808s are
    #: different edits even at the same rate.
    prefers: Tuple[str, ...]


# Defaults per section type. The numbers are anchored on commercial practice —
# roughly one to two bars in a hook, two to four in a verse, four or more in an
# intro — rather than on subdivisions of a beat.
# Calibration note. These are anchored on what a commercial music video
# actually does, not on subdivisions: reporting on top-charting videos puts
# chorus shots around 3.5 s and verse shots around 5-6 s, and MVX's own demo
# yields 107 cuts from 49 clips. At 140 BPM one bar is 1.71 s, so a 2.75-bar
# verse target is ~4.7 s and a 1.75-bar chorus target is ~3.0 s — inside that
# range with room to move either way. Expressing it in bars is what keeps the
# same intent true at 75 and at 170 BPM.
DEFAULT_PACING: Dict[str, PacingProfile] = {
    "intro": PacingProfile(2.0, 3.5, 7.0, 0.05, 0.75, 0.50, ("section", "phrase", "downbeat", "vocal_entry")),
    "verse": PacingProfile(1.25, 2.75, 5.0, 0.18, 0.50, 0.40, ("vocal_entry", "phrase", "downbeat", "lyric_line", "beat")),
    "chorus": PacingProfile(0.75, 1.75, 3.5, 0.32, 0.30, 0.30, ("downbeat", "accent", "phrase", "beat")),
    "drop": PacingProfile(0.50, 1.25, 3.0, 0.50, 0.25, 0.25, ("accent", "downbeat", "beat", "offbeat")),
    "bridge": PacingProfile(1.50, 3.00, 6.0, 0.08, 0.70, 0.45, ("phrase", "vocal_entry", "downbeat")),
    "outro": PacingProfile(2.0, 4.0, 9.0, 0.03, 0.80, 0.50, ("phrase", "downbeat", "section")),
}
FALLBACK_PACING = PacingProfile(
    1.25, 2.75, 5.0, 0.18, 0.5, 0.4, ("downbeat", "phrase", "beat")
)

# Hardest limit in the planner: no section may spend more than this share of
# its cuts inside bursts. A burst is an effect — the moment it becomes the
# baseline, the edit is the strobe this module exists to eliminate. Enforced as
# a budget rather than a probability so it cannot be defeated by an unlucky
# draw or by a preset asking for maximum aggression.
MAX_BURST_SHARE = 0.28

# A burst is a *run* of short shots. One short shot standing on its own reads as
# a mistake, not as acceleration, so a section either funds a real run or does
# not burst at all — there is no honest budget of one.
MIN_BURST_RUN = 2

# How much appetite a section has to declare before it is allowed to spend its
# one minimum-length burst in a stretch too short to earn a larger budget. Below
# this the style is saying it does not accelerate here, and it is believed.
BURST_APPETITE_FLOOR = 0.15

# The fewest shots a section may resolve into. Without a floor here a long
# "breath" swallows a whole sixteen-second intro in one held frame. Expressed as
# a count rather than a share of the time remaining: a per-shot share makes each
# successive shot shorter than the last, which decays geometrically in *seconds*
# and silently destroys the tempo-invariance that working in bars exists to
# provide.
MIN_SHOTS_PER_SECTION = 3
MIN_SHOTS_PER_SHORT_SECTION = 2

# When less than this multiple of the target remains, the current shot rides to
# the section boundary instead of a runt being carved out in front of it.
TAIL_ABSORB_FACTOR = 1.45

# How far a cut may be pulled from its requested time to reach a better event,
# as a fraction of the requested shot length. Wide enough to reach the bar line
# or the vocal entry that is obviously the right edit; narrow enough that the
# section's pacing intent survives.
SEARCH_BACK = 0.42
SEARCH_FORWARD = 0.55

# How many cuts one distinct source window can carry before the edit is visibly
# reusing material. Above this the answer is a slower edit, not more repetition.
ACCEPTABLE_REUSE_PER_WINDOW = 2.5

# The most the library may stretch the pacing. With almost no footage the honest
# response is longer shots, but not a single four-minute held frame — a handful
# of deliberate jump cuts inside one take is still an edit.
MAX_MATERIAL_STRETCH = 2.5

# Tension moves the target length. A section that is measurably pushing cuts
# faster than its own default; one that has emptied out holds longer. This is
# what makes the last bar before a chorus behave differently from the first.
TENSION_PACING_WEIGHT = 0.45


def resolve_pacing(
    section_type: str,
    style_config: Optional[Dict[str, Any]] = None,
) -> PacingProfile:
    """Return the pacing for a section, honouring a style preset's override.

    Presets may carry a ``pacing`` block in bars. The legacy ``cut_interval``
    key is still read, but only as a *hint about relative speed*: it is
    converted into a bar range around itself rather than used as a constant.
    A preset asking for ``0.125_beat`` gets the fastest profile available, not
    a 53 ms metronome, because no style is permitted to collapse the timeline
    onto a subdivision grid.
    """
    base = DEFAULT_PACING.get(section_type, FALLBACK_PACING)
    config = style_config or {}

    pacing_block = (config.get("pacing") or {}).get(section_type)
    if isinstance(pacing_block, dict):
        def read(key: str, default: float) -> float:
            try:
                value = float(pacing_block.get(key, default))
            except (TypeError, ValueError):
                return default
            return value if np.isfinite(value) else default

        minimum = max(0.15, read("min_bars", base.min_bars))
        target = max(minimum, read("target_bars", base.target_bars))
        maximum = max(target, read("max_bars", base.max_bars))
        return PacingProfile(
            minimum,
            target,
            maximum,
            max(0.0, min(1.0, read("burstiness", base.burstiness))),
            max(0.0, min(1.0, read("breath", base.breath))),
            max(0.1, read("burst_bars", base.burst_bars)),
            tuple(pacing_block.get("prefers") or base.prefers),
        )

    strategy = (config.get("cut_strategy") or {}).get(section_type)
    if isinstance(strategy, dict) and strategy.get("cut_interval") is not None:
        beats = _legacy_interval_beats(strategy.get("cut_interval"))
        if beats is not None:
            # Compatibility only, for a preset written against the old engine.
            # The legacy value is read as a *relative appetite for speed*, never
            # as a rate: ``0.125_beat`` meant a 53 ms shot, which the old
            # planner silently clamped into a uniform 0.16 s machine-gun. It is
            # therefore mapped onto a position between the section's own
            # slowest and fastest sensible pacing, and the section default is
            # the floor. No preset can drive the baseline below it — only
            # bursts go faster, and bursts are budgeted.
            speed = max(0.0, min(1.0, 1.0 - (beats / 4.0)))
            return PacingProfile(
                min_bars=max(base.min_bars * 0.7, base.min_bars * (1.0 - 0.3 * speed)),
                target_bars=max(
                    base.min_bars * 1.2,
                    base.target_bars * (1.0 - 0.42 * speed),
                ),
                max_bars=max(base.target_bars, base.max_bars * (1.0 - 0.25 * speed)),
                burstiness=min(0.55, base.burstiness + 0.25 * speed),
                breath=max(0.08, base.breath * (1.0 - 0.35 * speed)),
                burst_bars=base.burst_bars,
                prefers=base.prefers,
            )
    return base


def _legacy_interval_beats(raw: Any) -> Optional[float]:
    """Read a legacy ``"0.5_beat"`` string as a beat count."""
    if raw is None:
        return None
    text = str(raw).strip().lower()
    for suffix in ("_beats", "_beat"):
        if text.endswith(suffix):
            text = text[: -len(suffix)]
            break
    try:
        value = float(text)
    except ValueError:
        return None
    if not np.isfinite(value) or value <= 0:
        return None
    return max(0.0625, min(64.0, value))


def _variation(index: int, salt: int = 0) -> float:
    """A deterministic, equidistributed value in [0, 1) for shot ``index``.

    Deliberately not a random number generator: the same track must always
    produce the same edit, or an approved sequence changes under the editor
    when they re-run. An additive golden-ratio recurrence gives per-shot
    variety with that guarantee, and — unlike a hash — spreads successive
    values across the range rather than clumping them.
    """
    return float(((index + 1) * _PHI_CONJUGATE + salt * 0.37) % 1.0)


class PlannedCut(NamedTuple):
    """One planned slot, with everything needed to justify it later."""

    start: float
    end: float
    section_type: str
    origin: str
    source_time: float
    event_kind: str
    measured: bool
    mode: str
    target_bars: float
    actual_bars: float
    tension: float


def material_pacing_scale(
    distinct_windows: int,
    duration: float,
    mean_target_seconds: float,
) -> float:
    """How much to stretch the pacing because the library cannot fill it.

    The planner used to lay out the same 77 cuts whether the editor had loaded
    one clip or a hundred and fifty, and the selector was left to spread an
    impossible amount of reuse — one clip meant the same eight windows cycling
    seventy-seven times. Scarcity was measured (``search.scarcity``) but only
    ever used to *soften the penalties* for repeating, never to cut less.

    Returns 1.0 — no change at all — as soon as the library can actually carry
    the edit, which is the normal case for any real shoot.
    """
    if not (np.isfinite(duration) and np.isfinite(mean_target_seconds)):
        return 1.0
    if duration <= 0 or mean_target_seconds <= 0:
        return 1.0
    if not np.isfinite(distinct_windows):
        return 1.0
    affordable = max(1.0, float(distinct_windows) * ACCEPTABLE_REUSE_PER_WINDOW)
    desired = duration / mean_target_seconds
    return max(1.0, min(MAX_MATERIAL_STRETCH, desired / affordable))


def scale_pacing(pacing: PacingProfile, scale: float) -> PacingProfile:
    """Stretch a pacing profile without flattening its shape.

    ``burst_bars`` is stretched at a fraction of the rate: a scarce library
    should hold longer, but a burst that is no longer fast has stopped being a
    burst and become a slightly quicker sustain.
    """
    if scale <= 1.0:
        return pacing
    burst_scale = 1.0 + (scale - 1.0) * 0.35
    return pacing._replace(
        min_bars=pacing.min_bars * scale,
        target_bars=pacing.target_bars * scale,
        max_bars=pacing.max_bars * scale,
        burst_bars=pacing.burst_bars * burst_scale,
    )


def burst_budget(expected_shots: float, pacing: PacingProfile) -> int:
    """How many cuts a section may spend inside bursts.

    Scaled from the shots the section will hold at its own target pace, capped
    by :data:`MAX_BURST_SHARE`, and then rounded to something a burst can
    actually be spent on. The previous ``int()`` truncation was the reason whole
    sections never accelerated: ``ninetive``'s drop scored 1.98 and was floored
    to 1, and a budget of 1 can only buy the isolated cut that
    :data:`MIN_BURST_RUN` forbids. Rounding alone is not enough — the result has
    to be either zero or large enough to carry a run.
    """
    if not np.isfinite(expected_shots):
        return 0
    raw = max(0.0, float(expected_shots)) * MAX_BURST_SHARE * (0.5 + pacing.burstiness)
    budget = int(round(min(raw, float(MAX_CUTS))))
    if budget >= MIN_BURST_RUN:
        return budget
    # Too small to fund a run on its own. A section that has declared real
    # appetite and is long enough to absorb one still gets exactly one minimum
    # burst; anything quieter or shorter honestly gets none.
    if pacing.burstiness >= BURST_APPETITE_FLOOR and expected_shots >= MIN_BURST_RUN * 2:
        return MIN_BURST_RUN
    return 0


def _score_event(
    event: MusicalEvent,
    requested: float,
    window_back: float,
    window_forward: float,
    prefers: Sequence[str],
) -> float:
    """How good a landing this event is for a cut requested at ``requested``.

    Three factors, multiplied: the event's own musical authority, whether the
    section is looking for that kind of event, and how far the cut has to move
    to reach it. Multiplying rather than adding means a strong event that is
    far away does not beat a decent one that is right where the pacing wanted
    it — the section's intent is preserved.
    """
    distance = event.time - requested
    span = window_forward if distance >= 0 else window_back
    if span <= 0:
        return 0.0
    proximity = max(0.0, 1.0 - abs(distance) / span)
    # Squared so the falloff is gentle near the target and sharp at the edges.
    proximity *= proximity

    preference = 1.0
    if prefers:
        try:
            rank = list(prefers).index(event.kind)
            preference = 1.0 + 0.55 * (1.0 - rank / max(1, len(prefers)))
        except ValueError:
            preference = 0.72

    return event.weight * preference * (0.25 + 0.75 * proximity)


def _pick_event(
    lattice: Sequence[MusicalEvent],
    requested: float,
    earliest: float,
    latest: float,
    prefers: Sequence[str],
) -> Optional[MusicalEvent]:
    """Best lattice event inside the acceptance window, or ``None``."""
    window = events_between(lattice, earliest, latest)
    if not window:
        return None
    back = max(1e-6, requested - earliest)
    forward = max(1e-6, latest - requested)
    best: Optional[MusicalEvent] = None
    best_score = 0.0
    for event in window:
        score = _score_event(event, requested, back, forward, prefers)
        if score > best_score:
            best_score = score
            best = event
    return best


def plan_musical_cuts(
    sections: Sequence[Dict[str, Any]],
    lattice: Sequence[MusicalEvent],
    grid: MusicalGrid,
    duration: float,
    style_config: Optional[Dict[str, Any]] = None,
    tension: Optional[TensionCurve] = None,
    lyrics: Any = None,
    accents: Sequence[float] = (),
    material_scale: float = 1.0,
) -> List[PlannedCut]:
    """Lay out the whole timeline by walking musical events at a varying pace.

    The walk, per section:

    1. read the local tension and let it pull the target shot length shorter
       (the track is pushing) or longer (it has emptied out);
    2. add this shot's own equidistributed variation, so no two consecutive
       shots ask for the same length;
    3. decide the mode — *breath* when the voice has stopped or tension is in a
       trough, *burst* when tension is high and accents are dense, otherwise
       normal;
    4. ask the lattice for the best musical moment near the requested time and
       cut there.

    Section boundaries are emitted unconditionally: a transition is the one
    edit a listener feels whether or not anything else agrees with it.
    """
    duration = float(duration)
    if duration <= 0 or not sections:
        return []

    style_config = style_config or {}
    accent_array = np.asarray(sorted(float(value) for value in accents or []), dtype=np.float64)
    cuts: List[PlannedCut] = []
    shot_index = 0

    for section in sections:
        section_type = str(section.get("type", "verse"))
        section_start = float(section["start"])
        section_end = float(section["end"])
        if section_end - section_start < MIN_CUT_SECONDS:
            continue

        # The style says how this section wants to be cut; the library says how
        # much of that it can actually pay for.
        pacing = scale_pacing(resolve_pacing(section_type, style_config), material_scale)
        section_length = section_end - section_start
        # Bound the longest shot once, from the section's own length, so the
        # bound is a property of the section rather than of how far through it
        # a given shot happens to fall.
        target_seconds_nominal = grid.bars_to_seconds(pacing.target_bars)
        minimum_shots = (
            MIN_SHOTS_PER_SHORT_SECTION
            if section_length < target_seconds_nominal * 3.0
            else MIN_SHOTS_PER_SECTION
        )
        max_shot_seconds = min(
            grid.bars_to_seconds(pacing.max_bars),
            section_length / minimum_shots,
        )
        cursor = section_start
        # The section boundary itself is always a cut.
        boundary_tension = tension.at(cursor) if tension else 0.5
        cuts.append(
            PlannedCut(
                start=cursor,
                end=section_end,
                section_type=section_type,
                origin="boundary",
                source_time=cursor,
                event_kind="section",
                measured=True,
                # Filled in by the first shot this cut opens. `origin` and
                # `event_kind` already carry the fact that it is a boundary.
                mode="sustain",
                target_bars=0.0,
                actual_bars=0.0,
                tension=boundary_tension,
            )
        )

        burst_remaining = 0
        burst_cuts = 0
        section_cuts = 0
        # A burst budget scaled to how many shots this section will hold at its
        # own target pace. Computed up front so the cap is a property of the
        # section rather than of the order the draws happened to fall in.
        expected_shots = max(
            1.0, (section_end - section_start) / max(1e-6, grid.bars_to_seconds(pacing.target_bars))
        )
        section_burst_budget = burst_budget(expected_shots, pacing)
        guard = 0
        while cursor < section_end - MIN_CUT_SECONDS and guard < 4096:
            guard += 1
            shot_index += 1

            local_tension = tension.at(cursor) if tension else 0.5
            slope = tension.slope_at(cursor) if tension else 0.0

            # --- choose the mode -------------------------------------------
            mode = "sustain"
            # A run that has started always finishes: its length was bounded
            # when it was entered, and cutting it short on a budget check is how
            # a "burst" ended up being one isolated short shot.
            if burst_remaining > 0:
                mode = "burst"
                burst_remaining -= 1
            else:
                burst_remaining = 0
                in_rest = bool(
                    lyrics is not None
                    and getattr(lyrics, "vocal_segments", ())
                    and lyrics.in_vocal_rest(cursor, min(section_end, cursor + grid.bar_seconds))
                )
                breath_wanted = pacing.breath * (
                    0.55 * (1.0 - local_tension) + (0.45 if in_rest else 0.0)
                )
                # The variation draw is what stops "breathe when quiet" from
                # becoming its own rigid rule.
                if breath_wanted > 0.32 and _variation(shot_index, 3) < breath_wanted:
                    mode = "breath"
                else:
                    # A burst needs *evidence*, not just appetite: real accent
                    # density here, and a track that is actually pushing.
                    density = 0.0
                    if accent_array.size:
                        window = grid.bar_seconds * 2.0
                        left = int(np.searchsorted(accent_array, cursor, side="left"))
                        right = int(np.searchsorted(accent_array, cursor + window, side="right"))
                        density = (right - left) / max(1e-6, window / grid.period)
                    burst_wanted = pacing.burstiness * (
                        0.45 * local_tension + 0.35 * min(1.0, density) + 0.2 * max(0.0, slope)
                    )
                    if (
                        burst_wanted > 0.18
                        # Never open a run the budget cannot pay for in full.
                        and burst_cuts + MIN_BURST_RUN <= section_burst_budget
                        and _variation(shot_index, 7) < burst_wanted
                    ):
                        mode = "burst"
                        # A run of MIN_BURST_RUN..5 shots, then it stops. The
                        # lower bound is what makes this read as acceleration
                        # rather than one stray short cut; the section-wide
                        # budget caps how many runs can happen at all. Bounded
                        # length plus a bounded count is what makes this an
                        # effect rather than the 636-identical-cuts failure it
                        # replaces.
                        burst_remaining = max(
                            MIN_BURST_RUN - 1,
                            min(
                                1 + int(_variation(shot_index, 11) * 4.0),
                                max(0, section_burst_budget - burst_cuts - 1),
                            ),
                        )

            # --- choose the target length ----------------------------------
            if mode == "burst":
                target_bars = pacing.burst_bars * (0.8 + 0.5 * _variation(shot_index, 13))
            elif mode == "breath":
                target_bars = pacing.max_bars * (0.85 + 0.45 * _variation(shot_index, 17))
            else:
                spread = _variation(shot_index, 5)
                # Tension pulls the centre of the range: high tension towards
                # min_bars, low tension towards max_bars.
                pull = (0.5 - local_tension) * TENSION_PACING_WEIGHT
                centre = pacing.target_bars * (1.0 + pull)
                low = max(pacing.min_bars, centre * 0.65)
                high = min(pacing.max_bars, max(low * 1.15, centre * 1.55))
                target_bars = low + (high - low) * spread

            target_seconds = max(
                MIN_CUT_SECONDS if mode == "burst" else MIN_SUSTAINED_SECONDS,
                grid.bars_to_seconds(target_bars),
            )
            target_seconds = min(target_seconds, max_shot_seconds)
            if target_seconds < MIN_SUSTAINED_SECONDS and mode != "burst":
                target_seconds = MIN_SUSTAINED_SECONDS

            # The descriptors just chosen belong to the shot that *starts* at
            # `cursor` — the cut already sitting at the end of the list — not to
            # the cut about to be appended, which closes it. Attaching them to
            # the wrong end published a three-second hold as
            # `pacingMode: "burst"` with a 0.21-bar target, and everything that
            # reads cutProvenance (the transition chooser, the pacing
            # diagnostics, the learning record) acted on the previous shot.
            def _describe_open_shot(span: float) -> None:
                cuts[-1] = cuts[-1]._replace(
                    mode=mode,
                    target_bars=round(target_bars, 4),
                    actual_bars=round(grid.seconds_to_bars(span), 4),
                    tension=local_tension,
                )

            # Absorb the tail: when what is left is not much more than one
            # shot, let the current shot ride into the boundary rather than
            # carving a runt out in front of it. This is what an editor does,
            # and it is why the last shot of a section is often its longest.
            remaining = section_end - cursor
            if remaining < target_seconds * TAIL_ABSORB_FACTOR:
                _describe_open_shot(section_end - cuts[-1].start)
                break

            requested = cursor + target_seconds
            if requested >= section_end - MIN_CUT_SECONDS * 0.5:
                _describe_open_shot(section_end - cuts[-1].start)
                break

            # --- find the musical moment nearest the request ---------------
            earliest = max(
                cursor + (MIN_CUT_SECONDS if mode == "burst" else MIN_SUSTAINED_SECONDS),
                requested - target_seconds * SEARCH_BACK,
            )
            latest = min(section_end, requested + target_seconds * SEARCH_FORWARD)
            if latest <= earliest:
                cursor = requested
                continue

            prefers = pacing.prefers
            if mode == "burst":
                prefers = ("accent", "beat", "offbeat", "downbeat")
            elif mode == "breath":
                prefers = ("phrase", "section", "vocal_entry", "downbeat")

            event = _pick_event(lattice, requested, earliest, latest, prefers)
            if event is None:
                # Nothing musical to land on — an ambient passage with no
                # measured beat. Cutting at the requested time is honest, and
                # the provenance says the cut is unanchored rather than
                # claiming a beat that was never detected.
                cut_time = requested
                origin, kind, measured, source = "unanchored", "none", False, requested
            else:
                cut_time = event.time
                origin, kind, measured, source = "event", event.kind, event.measured, event.source_time

            if cut_time - cursor < MIN_CUT_SECONDS or section_end - cut_time < MIN_CUT_SECONDS:
                _describe_open_shot(section_end - cuts[-1].start)
                break

            _describe_open_shot(cut_time - cuts[-1].start)
            cuts.append(
                PlannedCut(
                    start=cut_time,
                    end=section_end,
                    section_type=section_type,
                    origin=origin,
                    source_time=source,
                    event_kind=kind,
                    measured=measured,
                    # Provisional: overwritten by the next iteration, or by the
                    # tail handling above when this cut opens the last shot.
                    mode="sustain",
                    target_bars=0.0,
                    actual_bars=0.0,
                    tension=local_tension,
                )
            )
            cursor = cut_time
            section_cuts += 1
            if mode == "burst":
                burst_cuts += 1

            if len(cuts) >= MAX_CUTS:
                break
        if len(cuts) >= MAX_CUTS:
            break

    cuts.sort(key=lambda cut: cut.start)

    # Close every slot against the next cut, and drop any runt the section
    # arithmetic left behind rather than shipping a flash frame.
    resolved: List[PlannedCut] = []
    for index, cut in enumerate(cuts):
        end = cuts[index + 1].start if index + 1 < len(cuts) else duration
        if end - cut.start < MIN_CUT_SECONDS:
            continue
        resolved.append(
            cut._replace(
                end=end,
                actual_bars=round(grid.seconds_to_bars(end - cut.start), 4),
            )
        )
    return resolved


def duration_histogram(cuts: Sequence[PlannedCut], tolerance: float = 0.02) -> Dict[str, Any]:
    """Measure how varied the planned shot lengths actually are.

    This exists because "the edit is not mechanical" is exactly the kind of
    claim that should be checked rather than asserted. ``concentration`` is the
    share of cuts sitting at the single most common length — the number that
    was 74 % on the engine this replaces.
    """
    if not cuts:
        return {"count": 0, "distinct": 0, "concentration": 0.0}
    lengths = [round((cut.end - cut.start) / max(tolerance, 1e-6)) for cut in cuts]
    counts: Dict[int, int] = {}
    for value in lengths:
        counts[value] = counts.get(value, 0) + 1
    modal = max(counts.values())
    seconds = [cut.end - cut.start for cut in cuts]
    return {
        "count": len(cuts),
        "distinct": len(counts),
        "concentration": round(modal / len(cuts), 4),
        "median": round(float(np.median(seconds)), 4),
        "mean": round(float(np.mean(seconds)), 4),
        "min": round(float(np.min(seconds)), 4),
        "max": round(float(np.max(seconds)), 4),
        "stdev": round(float(np.std(seconds)), 4),
    }
