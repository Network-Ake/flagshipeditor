"""Musical time, tension and the event lattice a cut may land on.

The old planner walked a metronome: ``position += interval_beats``. Every cut
in a section was therefore the same length, and the measured downbeats, phrase
boundaries and accents only ever survived as decoration on top of that grid.
The evidence is in the shipped engine's own output — 857 cuts across a 3:30
track produced **nine distinct shot lengths**, 636 of them identical.

This module supplies the two things needed to replace that walk:

* :func:`build_event_lattice` — every moment in the track a cut could
  defensibly land on, each carrying what kind of musical event it is, how
  strong the evidence for it is, and where that evidence came from. Event
  spacing is *not* uniform: phrase boundaries arrive every eight bars, an 808
  lands off the grid, a vocal enters a beat and a half after the bar. A planner
  that snaps to this lattice inherits its irregularity for free.

* :func:`tension_curve` — a continuous 0..1 reading of how hard the track is
  pushing at each moment, built from energy, onset density and vocal presence
  rather than from the section label. A section label is a coarse name for a
  stretch that can run a minute; the curve is what says the last bar before the
  chorus emptied out.

Nothing here decides where a cut goes. It describes the musical surface the
planner in :mod:`cut_planner` walks over, so that a claim about the edit can be
traced to the event that justified it.
"""

from __future__ import annotations

from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

import numpy as np

# Every kind of moment a cut is allowed to land on, with the base weight that
# says how much musical authority it carries. These are *evidence strengths*,
# not preferences: a section boundary is the one edit a listener feels whether
# or not anything else agrees with it, and a plain offbeat is the weakest thing
# in the list because it is an interpolation rather than a measurement.
EVENT_WEIGHTS: Dict[str, float] = {
    "section": 1.00,
    "phrase": 0.82,
    "vocal_entry": 0.78,
    "lyric_line": 0.72,
    "downbeat": 0.62,
    "accent": 0.58,
    "vocal_exit": 0.48,
    "beat": 0.34,
    "offbeat": 0.16,
}

# An event with no measured evidence behind it — an interpolated offbeat, a
# beat inferred from tempo alone — is still usable but must never outrank a
# measured one. Multiplied into the weight above.
INFERRED_EVENT_SCALE = 0.55

# Beats per bar. Published so a caller can override for a track in 3 or 6, and
# so nothing downstream has to hard-code the assumption silently.
DEFAULT_BEATS_PER_BAR = 4

# Windows used when reading a curve around a moment, in seconds. Short enough
# to catch a bar that empties out, long enough not to chase a single frame.
TENSION_SMOOTH_SECONDS = 0.75
ONSET_DENSITY_WINDOW_SECONDS = 2.0


class MusicalEvent(NamedTuple):
    """One moment a cut may land on, and the evidence that put it there."""

    time: float
    kind: str
    weight: float
    #: The measurement this event came from, before any quantisation. A cut
    #: that lands here can prove which 808 or which vocal entry it followed.
    source_time: float
    #: ``True`` when the event was measured, ``False`` when it was interpolated
    #: from tempo or bar arithmetic. Never suppressed — a planner that only has
    #: inferred events should say so rather than claim beat-accuracy.
    measured: bool


class MusicalGrid(NamedTuple):
    """Tempo-relative time. Everything the planner asks for is in bars."""

    period: float          #: one beat, seconds
    bar_seconds: float     #: one bar, seconds
    beats_per_bar: int
    tempo: float
    #: How regular the measured beat grid actually is, 0..1. A live take or a
    #: tempo-drifting beat lowers this, and the planner widens its snapping
    #: tolerance rather than pretending the grid is exact.
    regularity: float

    def bars_to_seconds(self, bars: float) -> float:
        return float(bars) * self.bar_seconds

    def seconds_to_bars(self, seconds: float) -> float:
        if self.bar_seconds <= 0:
            return 0.0
        return float(seconds) / self.bar_seconds


def _finite_times(values: Optional[Sequence[Any]]) -> List[float]:
    """Coerce to sorted finite non-negative floats, dropping anything else."""
    out: List[float] = []
    for value in values or []:
        if isinstance(value, dict):
            value = value.get("time")
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if np.isfinite(number) and number >= 0.0:
            out.append(number)
    out.sort()
    return out


def beat_period(beats: Sequence[float], tempo: float) -> float:
    """One beat in seconds, measured from the grid and falling back to tempo."""
    times = _finite_times(beats)
    if len(times) >= 2:
        deltas = np.diff(np.asarray(times, dtype=np.float64))
        deltas = deltas[deltas > 1e-6]
        if deltas.size:
            median = float(np.median(deltas))
            if np.isfinite(median) and median > 0:
                return median
    if tempo and float(tempo) > 0:
        return 60.0 / float(tempo)
    return 0.5


def grid_regularity(beats: Sequence[float]) -> float:
    """Return 0..1 for how evenly spaced the measured beats are.

    A programmed trap beat sits near 1.0. A live band or a track whose tempo
    was estimated from a noisy onset envelope sits lower, and the planner uses
    that to widen its snap tolerance instead of quantising a cut onto a beat
    that was never really there.
    """
    times = _finite_times(beats)
    if len(times) < 4:
        return 0.0
    deltas = np.diff(np.asarray(times, dtype=np.float64))
    deltas = deltas[deltas > 1e-6]
    if deltas.size < 3:
        return 0.0
    median = float(np.median(deltas))
    if median <= 0:
        return 0.0
    spread = float(np.median(np.abs(deltas - median))) / median
    return float(max(0.0, min(1.0, 1.0 - spread * 6.0)))


def musical_grid(
    beats: Sequence[float],
    tempo: float = 0.0,
    beats_per_bar: int = DEFAULT_BEATS_PER_BAR,
) -> MusicalGrid:
    """Build the tempo-relative frame the whole planner works in.

    Pacing is expressed in bars rather than seconds on purpose. "Hold this shot
    for two bars" means the same edit at 75 BPM and at 170 BPM; "hold it for
    three seconds" does not, and a seconds-based target is what makes an engine
    cut identically across every tempo it is given.
    """
    period = beat_period(beats, tempo)
    per_bar = max(2, min(12, int(beats_per_bar or DEFAULT_BEATS_PER_BAR)))
    resolved_tempo = float(tempo) if tempo and float(tempo) > 0 else 60.0 / period
    return MusicalGrid(
        period=period,
        bar_seconds=period * per_bar,
        beats_per_bar=per_bar,
        tempo=resolved_tempo,
        regularity=grid_regularity(beats),
    )


def infer_beats_per_bar(
    beats: Sequence[float],
    downbeats: Sequence[float],
    default: int = DEFAULT_BEATS_PER_BAR,
) -> int:
    """Recover the metre from the spacing of measured downbeats.

    Assuming 4/4 on a track in 3 shifts every bar-counted cut for the whole
    song, and the mistake is invisible in the output because the result is
    still a tidy grid. Measuring it costs one median.
    """
    beat_times = _finite_times(beats)
    down_times = _finite_times(downbeats)
    if len(beat_times) < 4 or len(down_times) < 3:
        return default
    period = beat_period(beat_times, 0.0)
    if period <= 0:
        return default
    spans = np.diff(np.asarray(down_times, dtype=np.float64)) / period
    spans = spans[(spans > 1.5) & (spans < 12.5)]
    if spans.size < 2:
        return default
    inferred = int(round(float(np.median(spans))))
    return inferred if 2 <= inferred <= 12 else default


def _normalise_curve(values: np.ndarray) -> np.ndarray:
    """Scale to 0..1 against the signal's own range, not an absolute gate.

    Modern masters are limited flat, so an absolute threshold fires everywhere
    or nowhere — which is the defect in the shipped section classifier, where
    ``rms > 0.08`` decides what a drop is.
    """
    if values.size == 0:
        return values
    low = float(np.percentile(values, 5.0))
    high = float(np.percentile(values, 95.0))
    if not np.isfinite(low) or not np.isfinite(high) or high - low < 1e-9:
        peak = float(np.max(values))
        if peak <= 1e-9:
            return np.zeros_like(values)
        return np.clip(values / peak, 0.0, 1.0)
    return np.clip((values - low) / (high - low), 0.0, 1.0)


def _smooth(values: np.ndarray, times: np.ndarray, seconds: float) -> np.ndarray:
    """Box-smooth a curve over a fixed number of seconds."""
    if values.size < 3 or seconds <= 0:
        return values
    step = float(np.median(np.diff(times))) if times.size > 1 else 0.0
    if step <= 0:
        return values
    width = max(1, int(round(seconds / step)))
    if width < 2:
        return values
    kernel = np.ones(width, dtype=np.float64) / float(width)
    return np.convolve(values, kernel, mode="same")


class TensionCurve(NamedTuple):
    """How hard the track is pushing, sampled on a regular time base."""

    times: np.ndarray
    values: np.ndarray
    #: Which signals actually contributed. A curve built from energy alone is
    #: weaker evidence than one that also saw onsets and vocals, and the
    #: planner is told which it got rather than being left to assume.
    sources: Tuple[str, ...]

    def at(self, time_value: float) -> float:
        """Read the curve at a moment, clamped to its own extent."""
        if self.times.size == 0:
            return 0.5
        index = int(np.searchsorted(self.times, float(time_value), side="left"))
        index = max(0, min(self.values.size - 1, index))
        return float(self.values[index])

    def mean_between(self, start: float, end: float) -> float:
        """Mean tension across a window; falls back to the nearest sample."""
        if self.times.size == 0:
            return 0.5
        first = int(np.searchsorted(self.times, float(start), side="left"))
        last = int(np.searchsorted(self.times, float(end), side="left"))
        if last <= first:
            return self.at(start)
        window = self.values[first:last]
        return float(np.mean(window)) if window.size else self.at(start)

    def slope_at(self, time_value: float, span: float = 2.0) -> float:
        """Signed rate of change, −1..1. Positive means the track is building.

        A buildup and a comedown can read the same absolute tension; only the
        direction separates them, and the direction is what tells the planner
        to accelerate into an event rather than relax away from one.
        """
        before = self.mean_between(time_value - span, time_value)
        after = self.mean_between(time_value, time_value + span)
        return float(max(-1.0, min(1.0, (after - before) * 2.0)))


def tension_curve(
    duration: float,
    energy: Optional[Sequence[Any]] = None,
    energy_times: Optional[Sequence[Any]] = None,
    onsets: Optional[Sequence[float]] = None,
    accents: Optional[Sequence[float]] = None,
    vocal_segments: Optional[Sequence[Any]] = None,
    resolution: float = 0.1,
) -> TensionCurve:
    """Combine the measured signals into one 0..1 reading of musical pressure.

    Three independent things make a track feel like it is pushing: it gets
    louder, events arrive more often, and a voice is present. Each is optional —
    a caller with only an energy curve still gets a usable result, and the
    result says which signals it was built from so nothing downstream can claim
    more resolution than the inputs support.
    """
    duration = float(duration) if duration and np.isfinite(duration) else 0.0
    if duration <= 0:
        return TensionCurve(np.asarray([]), np.asarray([]), ())

    step = max(0.02, float(resolution))
    times = np.arange(0.0, duration, step, dtype=np.float64)
    if times.size == 0:
        return TensionCurve(np.asarray([]), np.asarray([]), ())

    components: List[np.ndarray] = []
    weights: List[float] = []
    sources: List[str] = []

    energy_values = np.asarray(
        [v for v in (energy or []) if isinstance(v, (int, float)) and np.isfinite(v)],
        dtype=np.float64,
    )
    if energy_values.size >= 4:
        base_times = np.asarray(
            [v for v in (energy_times or []) if isinstance(v, (int, float))],
            dtype=np.float64,
        )
        if base_times.size < energy_values.size:
            base_times = np.linspace(0.0, duration, energy_values.size, dtype=np.float64)
        else:
            base_times = base_times[: energy_values.size]
        if np.all(np.diff(base_times) > 0):
            resampled = np.interp(times, base_times, energy_values)
            curve = _smooth(_normalise_curve(resampled), times, TENSION_SMOOTH_SECONDS)
            components.append(curve)
            weights.append(0.45)
            sources.append("energy")

    onset_times = _finite_times(list(onsets or []) + list(accents or []))
    if len(onset_times) >= 4:
        array = np.asarray(onset_times, dtype=np.float64)
        half = ONSET_DENSITY_WINDOW_SECONDS * 0.5
        left = np.searchsorted(array, times - half, side="left")
        right = np.searchsorted(array, times + half, side="right")
        density = (right - left).astype(np.float64) / ONSET_DENSITY_WINDOW_SECONDS
        curve = _smooth(_normalise_curve(density), times, TENSION_SMOOTH_SECONDS)
        components.append(curve)
        weights.append(0.35)
        sources.append("onset_density")

    presence = np.zeros_like(times)
    marked = False
    for segment in vocal_segments or []:
        try:
            if isinstance(segment, dict):
                start = float(segment.get("start", 0.0))
                end = float(segment.get("end", 0.0))
            else:
                start, end = float(segment[0]), float(segment[1])
        except (TypeError, ValueError, IndexError):
            continue
        if end <= start:
            continue
        presence[(times >= start) & (times < end)] = 1.0
        marked = True
    if marked:
        components.append(_smooth(presence, times, TENSION_SMOOTH_SECONDS))
        weights.append(0.20)
        sources.append("vocal_presence")

    if not components:
        # Nothing measurable arrived. A flat mid curve is an honest "no
        # opinion" — it leaves the planner on its section defaults instead of
        # inventing a shape the audio never had.
        return TensionCurve(times, np.full_like(times, 0.5), ())

    total = float(sum(weights))
    stacked = sum(component * (weight / total) for component, weight in zip(components, weights))
    return TensionCurve(times, np.clip(stacked, 0.0, 1.0), tuple(sources))


def bar_times(
    beats: Sequence[float],
    downbeats: Sequence[float],
    grid: MusicalGrid,
    duration: float,
) -> List[Tuple[float, bool]]:
    """Return every bar line as ``(time, measured)``.

    Measured downbeats are used wherever they exist. Where they run out — a
    downbeat tracker that gave up over an ambient intro — bar lines are counted
    off the beat grid from the last known downbeat, and flagged as inferred so
    a cut that lands on one cannot claim to be on a measured bar line.
    """
    beat_times = _finite_times(beats)
    down_times = _finite_times(downbeats)
    out: List[Tuple[float, bool]] = [(time, True) for time in down_times if time < duration]

    if beat_times:
        # Fill the gaps between measured downbeats — and the head and tail —
        # by counting bars off the beat grid.
        anchor_index = 0
        if down_times:
            first = down_times[0]
            anchor_index = int(np.argmin(np.abs(np.asarray(beat_times) - first)))
        step = grid.beats_per_bar
        known = set(round(time, 3) for time in down_times)
        for index in range(anchor_index % step, len(beat_times), step):
            time = float(beat_times[index])
            if time >= duration:
                break
            if round(time, 3) not in known:
                out.append((time, False))
    elif grid.bar_seconds > 0:
        count = int(duration / grid.bar_seconds) + 1
        out.extend((index * grid.bar_seconds, False) for index in range(count))

    out.sort(key=lambda entry: entry[0])
    # Collapse bar lines that describe the same moment, keeping the measured one.
    collapsed: List[Tuple[float, bool]] = []
    for time, measured in out:
        if collapsed and time - collapsed[-1][0] < grid.period * 0.4:
            if measured and not collapsed[-1][1]:
                collapsed[-1] = (time, True)
            continue
        collapsed.append((time, measured))
    return collapsed


def build_event_lattice(
    duration: float,
    grid: MusicalGrid,
    beats: Sequence[float],
    downbeats: Sequence[float] = (),
    phrase_boundaries: Sequence[Any] = (),
    section_boundaries: Sequence[float] = (),
    accents: Sequence[float] = (),
    vocal_entries: Sequence[float] = (),
    vocal_exits: Sequence[float] = (),
    lyric_lines: Sequence[Any] = (),
    include_offbeats: bool = True,
) -> List[MusicalEvent]:
    """Return every moment a cut may land on, strongest evidence first per time.

    This is the whole point of the redesign. The old planner could only ever
    produce times of the form ``section_start + k * interval``; this lattice
    contains bar lines, phrase turns, syncopated accents, the beat a voice
    actually enters on and the beat it leaves on — spacings that are unequal by
    construction. A planner that walks it cannot emit a uniform duration
    histogram unless the music itself is uniform.

    Events at the same instant are collapsed to the strongest, so a downbeat
    that is also a phrase boundary is one cut opportunity described by its
    strongest evidence rather than two competing ones.
    """
    duration = float(duration)
    if duration <= 0:
        return []

    events: List[MusicalEvent] = []

    def add(time: float, kind: str, measured: bool, source: Optional[float] = None) -> None:
        if not np.isfinite(time) or time < 0.0 or time >= duration:
            return
        weight = EVENT_WEIGHTS.get(kind, 0.2)
        if not measured:
            weight *= INFERRED_EVENT_SCALE
        events.append(
            MusicalEvent(
                time=float(time),
                kind=kind,
                weight=float(weight),
                source_time=float(source if source is not None else time),
                measured=bool(measured),
            )
        )

    for time in _finite_times(section_boundaries):
        add(time, "section", True)
    for time in _finite_times(phrase_boundaries):
        add(time, "phrase", True)
    for time in _finite_times(vocal_entries):
        add(time, "vocal_entry", True)
    for time in _finite_times(vocal_exits):
        add(time, "vocal_exit", True)
    for entry in lyric_lines or []:
        time = entry.get("start") if isinstance(entry, dict) else entry
        try:
            add(float(time), "lyric_line", True)
        except (TypeError, ValueError):
            continue
    for time in _finite_times(accents):
        add(time, "accent", True)

    for time, measured in bar_times(beats, downbeats, grid, duration):
        add(time, "downbeat", measured)

    beat_times = _finite_times(beats)
    for time in beat_times:
        add(time, "beat", True)
    if not beat_times and grid.period > 0:
        # No measured beats at all. A tempo metronome is still better than
        # nothing, but every event it produces is flagged inferred.
        count = int(duration / grid.period) + 1
        for index in range(count):
            add(index * grid.period, "beat", False)

    if include_offbeats and grid.period > 0:
        source = beat_times or [index * grid.period for index in range(int(duration / grid.period) + 1)]
        for time in source:
            add(time + grid.period * 0.5, "offbeat", False, source=time)

    events.sort(key=lambda item: (item.time, -item.weight))

    # Collapse near-simultaneous events. Two cuts 8 ms apart are one edit; the
    # survivor is the one with the strongest musical claim.
    tolerance = max(0.012, grid.period * 0.06)
    collapsed: List[MusicalEvent] = []
    for event in events:
        if collapsed and event.time - collapsed[-1].time <= tolerance:
            if event.weight > collapsed[-1].weight:
                collapsed[-1] = event
            continue
        collapsed.append(event)
    return collapsed


def events_between(
    lattice: Sequence[MusicalEvent],
    start: float,
    end: float,
) -> List[MusicalEvent]:
    """Return the lattice events inside ``[start, end)`` without copying it all."""
    if not lattice:
        return []
    times = [event.time for event in lattice]
    first = int(np.searchsorted(times, start, side="left"))
    last = int(np.searchsorted(times, end, side="left"))
    return list(lattice[first:last])


def section_tension(
    curve: TensionCurve,
    sections: Sequence[Dict[str, Any]],
) -> Dict[int, float]:
    """Mean tension per section index, used to rank sections against each other.

    A "chorus" label is worth very little on its own — the shipped classifier
    assigns verse/chorus by alternating position, not by measurement. Ranking
    sections by what they measurably do recovers the ordering the label was
    supposed to carry.
    """
    out: Dict[int, float] = {}
    for index, section in enumerate(sections or []):
        try:
            start = float(section.get("start", 0.0))
            end = float(section.get("end", 0.0))
        except (TypeError, ValueError):
            continue
        if end > start:
            out[index] = curve.mean_between(start, end)
    return out
