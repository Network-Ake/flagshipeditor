"""Deterministic fixtures for the editing-intelligence regressions.

Every fixture is a pure function of its arguments — no randomness, no file I/O,
no clock — so a failing assertion always reproduces. The library generators
deliberately produce *awkward* footage as well as good footage: near-duplicate
pairs, a library of four clips, one clip that outclasses everything else. A
suite built only on well-behaved input proves nothing about the failures this
work exists to fix.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

SECTION_ENERGY = {
    "intro": 0.22,
    "verse": 0.50,
    "chorus": 0.80,
    "drop": 0.95,
    "bridge": 0.32,
    "outro": 0.18,
}

# Arrangements covering the styles the product targets.
ARRANGEMENTS: Dict[str, List[Tuple[str, float, float]]] = {
    "trap": [
        ("intro", 0, 16), ("verse", 16, 48), ("chorus", 48, 72), ("verse", 72, 104),
        ("chorus", 104, 128), ("drop", 128, 160), ("verse", 160, 184), ("outro", 184, 210),
    ],
    "melodic": [
        ("intro", 0, 20), ("verse", 20, 56), ("chorus", 56, 88), ("verse", 88, 124),
        ("chorus", 124, 156), ("bridge", 156, 176), ("chorus", 176, 205), ("outro", 205, 230),
    ],
    "atmospheric": [
        ("intro", 0, 32), ("verse", 32, 80), ("bridge", 80, 104), ("verse", 104, 152),
        ("chorus", 152, 184), ("outro", 184, 220),
    ],
    "drill": [
        ("intro", 0, 12), ("verse", 12, 44), ("chorus", 44, 64), ("verse", 64, 96),
        ("chorus", 96, 116), ("drop", 116, 140), ("outro", 140, 158),
    ],
    "short": [("intro", 0, 8), ("verse", 8, 32), ("chorus", 32, 56), ("outro", 56, 70)],
}


def make_track(
    bpm: float = 140.0,
    arrangement: str = "trap",
    beats_per_bar: int = 4,
    syncopation: bool = True,
    with_energy: bool = True,
) -> Dict[str, Any]:
    """Build a synthetic but musically coherent track description."""
    plan = ARRANGEMENTS[arrangement]
    duration = float(plan[-1][2])
    period = 60.0 / bpm

    beats: List[float] = []
    time_value = 0.0
    while time_value < duration:
        beats.append(round(time_value, 6))
        time_value += period

    downbeats = [beat for index, beat in enumerate(beats) if index % beats_per_bar == 0]
    phrases = [beat for index, beat in enumerate(beats) if index % (beats_per_bar * 4) == 0]

    accents: List[float] = []
    for index, beat in enumerate(beats):
        if index % beats_per_bar == 0:
            accents.append(beat)
        elif syncopation and index % 8 == 3:
            # A played 808 that does not sit on the grid. The planner must be
            # able to land on it, which is impossible for a subdivision walker.
            accents.append(round(beat + period * 0.5, 6))
        elif syncopation and index % 12 == 7:
            accents.append(round(beat + period * 0.25, 6))

    sections = [{"type": name, "start": float(a), "end": float(b)} for name, a, b in plan]

    energy: List[float] = []
    energy_times: List[float] = []
    if with_energy:
        step = 0.1
        samples = int(duration / step)
        for index in range(samples):
            moment = index * step
            energy_times.append(round(moment, 4))
            level = 0.3
            for name, a, b in plan:
                if a <= moment < b:
                    level = SECTION_ENERGY.get(name, 0.5)
                    # Last two bars of a section empty out or build, so the
                    # tension curve has real internal shape rather than a step.
                    tail = (b - moment) / max(1e-6, b - a)
                    if tail < 0.12:
                        level *= 0.72 if name in ("verse", "bridge") else 1.08
            energy.append(round(level + 0.07 * math.sin(moment * 1.7), 5))

    return {
        "beats": beats,
        "downbeats": downbeats,
        "phrases": phrases,
        "accents": accents,
        "sections": sections,
        "energy": energy,
        "energy_times": energy_times,
        "duration": duration,
        "tempo": bpm,
        "period": period,
        "beats_per_bar": beats_per_bar,
        "arrangement": arrangement,
    }


_SCENES = ("performance", "close_up", "b_roll_dynamic", "b_roll_static", "b_roll_with_face", "b_roll")
_SHOTS = ("close_up", "medium_shot", "long_shot", "medium_close_up", "extreme_long_shot", "medium_long_shot")
_MOVES = ("static", "pan", "handheld", "push_pull")


def make_clip(index: int, duration: float = 8.0, **overrides: Any) -> Dict[str, Any]:
    """One analysed clip record, shaped exactly as ``clip_analysis`` publishes it."""
    clip: Dict[str, Any] = {
        "path": f"/media/clip_{index:03d}.mp4",
        "name": f"clip_{index:03d}.mp4",
        "usable": True,
        "duration": float(duration),
        "scene_type": _SCENES[index % len(_SCENES)],
        "shot_type": _SHOTS[index % len(_SHOTS)],
        "camera_movement": _MOVES[index % len(_MOVES)],
        "composition_score": 40 + (index * 7) % 55,
        "sharpness_score": 45 + (index * 11) % 50,
        "brightness_stability": 70 + (index * 13) % 30,
        "brightness_mean": 25 + (index * 17) % 55,
        "motion_intensity": (index * 17) % 100,
        "motion_variance": ((index * 5) % 40) / 10.0,
        "has_face": index % 3 == 0,
        "face_size_ratio": 0.10 + ((index % 5) * 0.03),
        "face_consistency": 0.45 + ((index % 4) * 0.13),
        "histogram": [((index * k) % 16) + 1 for k in range(16)],
        "best_moment": {"best_time": min(duration * 0.6, 1.0 + (index % 5) * 0.8), "confidence": 0.7},
        "moment_windows": [
            {"time": round(min(duration * 0.9, 0.6 + step * (duration / 5.0)), 3), "score": 0.9 - 0.12 * step}
            for step in range(4)
        ],
        "thumbnail_id": f"t{index}",
    }
    clip.update(overrides)
    return clip


def make_library(
    count: int = 24,
    duration: float = 8.0,
    near_duplicate_pairs: int = 0,
    dominant_clip: bool = False,
    varied_durations: bool = True,
) -> List[Dict[str, Any]]:
    """Build a clip library, optionally seeded with the hard cases.

    ``near_duplicate_pairs`` clones a clip's histogram and every descriptor
    except its path, which is the situation the shipped engine had no way to
    detect: two different files that are the same image.

    ``dominant_clip`` gives one clip a near-perfect score on every criterion,
    reproducing the "strongest clip takes over the timeline" failure.
    """
    clips = [
        make_clip(index, duration + ((index % 5) * 2.0 if varied_durations else 0.0))
        for index in range(count)
    ]

    for pair in range(min(near_duplicate_pairs, count // 2)):
        source = clips[pair * 2]
        twin = clips[pair * 2 + 1]
        for key in (
            "histogram", "scene_type", "shot_type", "camera_movement",
            "has_face", "face_size_ratio", "brightness_mean",
            "composition_score", "motion_intensity",
        ):
            twin[key] = source[key]

    if dominant_clip and clips:
        clips[0].update(
            {
                "composition_score": 99.0,
                "sharpness_score": 99.0,
                "brightness_stability": 99.0,
                "motion_intensity": 85.0,
                "motion_variance": 3.5,
                "has_face": True,
                "face_size_ratio": 0.15,
                "face_consistency": 0.98,
            }
        )
    return clips


# Lyric fixtures ------------------------------------------------------------
#
# Written to exercise the cases the brief names: English-dominant rap with
# regional vocabulary, a hook that recurs verbatim, ad-libs, occasional French
# and Creole, and a passage that carries no interpretable imagery at all.

LYRICS_NARRATIVE = """Woke up on the block before the sun came through
Cold nights on the corner, nothing left to lose
Momma said be patient but the pressure never sleeps
Counting every dollar while the city never sleeps
Ride through the city with my brothers on the road
Ride through the city with my brothers on the road
Yeah, yeah, uh, skrrt
Diamonds on my neck now, came up from the floor
Ride through the city with my brothers on the road
They switched up on me when the money came around
Long nights turned to daylight, now I'm wearing the crown
Ride through the city with my brothers on the road
Pray for me, I made it out the cold
"""

LYRICS_MULTILINGUAL = """Late night in Montreal, the snow is on the street
Mwen pa gen tan pou sa, my heart is on repeat
Je pense à ma famille every time I close my eyes
Ride through the city with my brothers on the road
Yeah, ayy, uh
Ride through the city with my brothers on the road
"""

LYRICS_ABSTRACT = """Circles into circles, what it is, it is
Maybe if it happens then it happens how it is
Something in the nothing and the nothing in between
Circles into circles, what it is, it is
"""

LYRICS_TIMECODED = """[00:08.00]Woke up on the block before the sun came through
[00:12.50]Cold nights on the corner, nothing left to lose
[00:17.00]Ride through the city with my brothers on the road
[00:22.00]Diamonds on my neck now, came up from the floor
[00:27.50]Ride through the city with my brothers on the road
"""


def make_vocal_segments(
    track: Dict[str, Any],
    coverage: float = 0.6,
    phrase_bars: float = 2.0,
) -> List[Tuple[float, float, float]]:
    """Vocal phrases laid over the arrangement, as ``(start, end, confidence)``.

    Instrumental sections get no vocal, which is what gives the planner
    somewhere legitimate to breathe.
    """
    period = track["period"]
    bar = period * track["beats_per_bar"]
    phrase = bar * phrase_bars
    out: List[Tuple[float, float, float]] = []
    for section in track["sections"]:
        if section["type"] in ("intro", "outro"):
            continue
        cursor = float(section["start"]) + bar * 0.25
        while cursor + phrase * coverage < float(section["end"]):
            out.append((round(cursor, 4), round(cursor + phrase * coverage, 4), 0.62))
            cursor += phrase
    return out


def build_lyrics(
    track: Dict[str, Any],
    text: str = LYRICS_NARRATIVE,
    coverage: float = 0.6,
    with_vocals: bool = True,
):
    """Run the real lyric pipeline over a fixture. No mocks — this is the code path."""
    import lyric_analysis

    segments = []
    if with_vocals:
        segments = [
            lyric_analysis.VocalSegment(start, end, confidence, confidence)
            for start, end, confidence in make_vocal_segments(track, coverage)
        ]
    return lyric_analysis.analyse_lyrics(
        lyric_text=text,
        duration=track["duration"],
        vocal_segments=segments,
        allow_asr=False,
    )


def load_style(name: str = "worldwide_films") -> Dict[str, Any]:
    """Load a shipped style preset from disk, so tests bind to the real config."""
    import json
    import os

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "styles", f"{name}.json"), "r", encoding="utf-8") as handle:
        return json.load(handle)


def run_engine(
    track: Dict[str, Any],
    clips: Sequence[Dict[str, Any]],
    style: Optional[Dict[str, Any]] = None,
    lyrics: Any = None,
    hook: Optional[Dict[str, float]] = None,
    **overrides: Any,
) -> List[Dict[str, Any]]:
    """Run the production selection path end to end on a fixture."""
    from shot_selector import select_best_clips

    kwargs: Dict[str, Any] = {
        "clips": list(clips),
        "beats": track["beats"],
        "sections": track["sections"],
        "style_config": style if style is not None else load_style(),
        "duration": track["duration"],
        "tempo": track["tempo"],
        "bass_onsets": track["accents"],
        "downbeats": track["downbeats"],
        "phrase_boundaries": track["phrases"],
        "energy": track["energy"],
        "energy_times": track["energy_times"],
        "hook": hook,
        "lyrics": lyrics,
    }
    kwargs.update(overrides)
    return select_best_clips(**kwargs)


def shot_lengths(cuts: Sequence[Dict[str, Any]]) -> List[float]:
    return [round(float(cut["endTime"]) - float(cut["beatTime"]), 6) for cut in cuts]


def lengths_in_beats(cuts: Sequence[Dict[str, Any]], period: float) -> List[float]:
    return [round(length / period, 3) for length in shot_lengths(cuts)]


def modal_share(values: Sequence[float], tolerance: float = 0.02) -> float:
    """Share of values sitting at the single most common quantised length."""
    if not values:
        return 0.0
    buckets: Dict[int, int] = {}
    for value in values:
        key = int(round(value / tolerance))
        buckets[key] = buckets.get(key, 0) + 1
    return max(buckets.values()) / len(values)
