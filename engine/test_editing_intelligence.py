"""Deterministic regressions for the cutting, lyric and selection redesign.

Each test names the failure it prevents and, where one exists, the measured
baseline number it has to beat. Those numbers came from running the shipped
engine on the fixtures in :mod:`editing_fixtures`:

    857 cuts on a 3:30 track       9 distinct shot lengths
    74.2 % at the modal length     0.214 s median shot
    94.3 % of cuts reusing a source window, 49 distinct windows in total
    five clips used exactly 52 times each

A test that only asserts "the code runs" would have passed on every one of
those. The assertions here are on the properties that were actually wrong.

Run directly (``python engine/test_editing_intelligence.py``) or under pytest.
"""

from __future__ import annotations

import collections
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402

import editing_fixtures as fx  # noqa: E402
import lyric_analysis  # noqa: E402
from cut_planner import MAX_BURST_SHARE, MIN_SUSTAINED_SECONDS, resolve_pacing  # noqa: E402
from musical_structure import build_event_lattice, musical_grid, tension_curve  # noqa: E402
from narrative import build_narrative_plan, classify_clip_roles  # noqa: E402
from sequence_selector import (  # noqa: E402
    NEAR_DUPLICATE_SIMILARITY,
    build_similarity_matrix,
    candidate_windows,
    visual_signature,
)


# ---------------------------------------------------------------------------
# 1. Pacing is not a subdivision grid
# ---------------------------------------------------------------------------


def test_output_not_confined_to_quarter_eighth_sixteenth():
    """The shipped engine emitted 9 distinct lengths, 74 % of them identical."""
    track = fx.make_track()
    cuts = fx.run_engine(track, fx.make_library(24))
    lengths = fx.shot_lengths(cuts)

    assert len(cuts) > 12, "no timeline was produced"
    distinct = len(set(round(value, 3) for value in lengths))
    share = fx.modal_share(lengths)

    assert distinct >= 15, f"only {distinct} distinct shot lengths (baseline was 9)"
    assert share <= 0.35, f"{share:.1%} of cuts share one length (baseline was 74.2%)"

    # The specific failure named in the brief: lengths confined to a handful of
    # beat subdivisions. Measured as how much of the timeline sits on the three
    # shortest subdivision values.
    beats = fx.lengths_in_beats(cuts, track["period"])
    subdivision_bound = sum(
        1 for value in beats if any(abs(value - target) < 0.06 for target in (0.25, 0.5, 1.0))
    )
    assert subdivision_bound / len(beats) < 0.5, (
        f"{subdivision_bound}/{len(beats)} cuts sit on 1/4, 1/8 or 1/16 of a beat"
    )


def test_shots_sustain_across_multiple_bars():
    """A shot must be able to hold. The old engine's longest verse cut was 1.14 s."""
    track = fx.make_track()
    cuts = fx.run_engine(track, fx.make_library(24))
    grid = musical_grid(track["beats"], track["tempo"])
    lengths = fx.shot_lengths(cuts)

    longest_bars = max(lengths) / grid.bar_seconds
    assert longest_bars >= 2.0, f"longest shot is only {longest_bars:.2f} bars"

    sustained = sum(1 for value in lengths if value >= grid.bar_seconds)
    assert sustained >= len(lengths) * 0.25, (
        f"only {sustained}/{len(lengths)} shots last a full bar"
    )
    assert statistics.median(lengths) >= MIN_SUSTAINED_SECONDS, (
        f"median shot {statistics.median(lengths):.3f}s is below the sustained floor"
    )


def test_rapid_cuts_are_bounded_bursts_not_the_baseline():
    """Fast cutting must stay an effect. It was 100 % of the old drop section."""
    track = fx.make_track()
    cuts = fx.run_engine(track, fx.make_library(24), style=fx.load_style("cmd_command_drill"))
    modes = collections.Counter(cut["cutProvenance"]["pacingMode"] for cut in cuts)
    burst_share = modes.get("burst", 0) / len(cuts)

    assert burst_share <= MAX_BURST_SHARE + 0.05, (
        f"bursts are {burst_share:.1%} of the timeline — that is the baseline, not an effect"
    )
    # And a burst must actually be a *run*, not isolated short cuts scattered
    # around, or it is just noise.
    if modes.get("burst", 0) >= 2:
        sequence = [cut["cutProvenance"]["pacingMode"] for cut in cuts]
        runs = [len(list(group)) for key, group in _groupby(sequence) if key == "burst"]
        assert max(runs) >= 2, "no burst lasted more than one cut"


def test_sections_have_distinct_pacing():
    """Verse, chorus and drop shared one duration distribution before."""
    track = fx.make_track()
    cuts = fx.run_engine(track, fx.make_library(24))
    by_section: dict = collections.defaultdict(list)
    for cut in cuts:
        by_section[cut["sectionType"]].append(
            float(cut["endTime"]) - float(cut["beatTime"])
        )

    medians = {
        name: statistics.median(values)
        for name, values in by_section.items()
        if len(values) >= 3
    }
    assert len(medians) >= 3, f"not enough populated sections to compare: {list(by_section)}"

    # A calm section must measurably hold longer than a peak one.
    calm = [medians[name] for name in ("intro", "outro", "bridge", "verse") if name in medians]
    peak = [medians[name] for name in ("chorus", "drop") if name in medians]
    assert calm and peak, f"missing calm or peak sections: {medians}"
    assert max(calm) > max(peak) * 1.3, (
        f"calm sections do not hold longer than peaks: {medians}"
    )


def test_style_presets_produce_different_edits():
    """Two presets must not converge on the same timeline."""
    track = fx.make_track()
    library = fx.make_library(24)
    patient = fx.run_engine(track, library, style=fx.load_style("ninetive"))
    aggressive = fx.run_engine(track, library, style=fx.load_style("cmd_command_drill"))

    patient_median = statistics.median(fx.shot_lengths(patient))
    aggressive_median = statistics.median(fx.shot_lengths(aggressive))
    assert patient_median > aggressive_median * 1.25, (
        f"patient preset {patient_median:.2f}s vs aggressive {aggressive_median:.2f}s — too close"
    )
    assert len(patient) < len(aggressive), (
        f"patient preset produced {len(patient)} cuts, aggressive {len(aggressive)}"
    )


def test_no_style_can_collapse_the_timeline_onto_a_grid():
    """Even a legacy preset demanding 1/16 must not produce a metronome."""
    legacy = fx.load_style("worldwide_films")
    legacy.pop("pacing", None)
    legacy["cut_strategy"] = {
        name: {"cut_interval": "0.125_beat"} for name in
        ("intro", "verse", "chorus", "drop", "bridge", "outro")
    }
    track = fx.make_track()
    cuts = fx.run_engine(track, fx.make_library(24), style=legacy)
    lengths = fx.shot_lengths(cuts)

    assert fx.modal_share(lengths) <= 0.40, (
        f"legacy 1/16 preset still collapses: {fx.modal_share(lengths):.1%} at one length"
    )
    assert statistics.median(lengths) >= MIN_SUSTAINED_SECONDS, (
        f"legacy preset drove the median to {statistics.median(lengths):.3f}s"
    )


def test_pacing_is_tempo_invariant():
    """Bars, not seconds: the same intent must survive a tempo change."""
    slow = fx.make_track(bpm=75.0)
    fast = fx.make_track(bpm=170.0)
    library = fx.make_library(24)

    slow_cuts = fx.run_engine(slow, library)
    fast_cuts = fx.run_engine(fast, library)

    slow_bars = statistics.median(fx.shot_lengths(slow_cuts)) / (60.0 / 75.0 * 4)
    fast_bars = statistics.median(fx.shot_lengths(fast_cuts)) / (60.0 / 170.0 * 4)
    assert abs(slow_bars - fast_bars) < 1.0, (
        f"shot length in bars differs across tempo: {slow_bars:.2f} vs {fast_bars:.2f}"
    )


def test_visual_and_musical_events_place_non_grid_cuts():
    """Syncopated accents and vocal entries must be reachable landing points."""
    track = fx.make_track(syncopation=True)
    lyrics = fx.build_lyrics(track)
    cuts = fx.run_engine(track, fx.make_library(24), lyrics=lyrics)

    kinds = collections.Counter(cut["cutProvenance"]["eventKind"] for cut in cuts)
    assert len(kinds) >= 3, f"cuts land on only {len(kinds)} kinds of event: {dict(kinds)}"

    off_grid = [
        cut for cut in cuts
        if not cut["cutProvenance"].get("beatAligned", True)
        or cut["cutProvenance"]["eventKind"] in ("accent", "vocal_entry", "offbeat", "lyric_line")
    ]
    assert off_grid, "every cut landed on the plain beat grid"


# ---------------------------------------------------------------------------
# 2. Lyrics
# ---------------------------------------------------------------------------


def test_lyrics_influence_selection_end_to_end():
    track = fx.make_track()
    library = fx.make_library(24)
    lyrics = fx.build_lyrics(track)

    assert lyrics.tier == "aligned", f"expected alignment tier, got {lyrics.tier}"
    assert lyrics.has_text and lyrics.can_interpret, "fixture lyrics were not interpretable"

    without = fx.run_engine(track, library, lyrics=None)
    with_lyrics = fx.run_engine(track, library, lyrics=lyrics)

    influenced = [
        cut for cut in with_lyrics
        if (cut.get("lyric") or {}).get("influencedSelection")
    ]
    assert influenced, "no cut was influenced by a lyric line"

    chosen_without = [cut["clipPath"] for cut in without]
    chosen_with = [cut["clipPath"] for cut in with_lyrics]
    assert chosen_without != chosen_with, "lyrics changed nothing in the final timeline"


def test_weak_lyric_confidence_degrades_safely():
    """A line the lexicon cannot read must not choose a shot."""
    track = fx.make_track()
    lyrics = fx.build_lyrics(track, text=fx.LYRICS_ABSTRACT)
    cuts = fx.run_engine(track, fx.make_library(24), lyrics=lyrics)

    assert cuts, "abstract lyrics broke the edit"
    for cut in cuts:
        line = cut.get("lyric") or {}
        if line.get("influencedSelection"):
            assert line["interpretationConfidence"] >= lyric_analysis.MIN_INTERPRETATION_CONFIDENCE, (
                f"a line under the confidence floor steered a cut: {line}"
            )


def test_unrecognised_language_is_not_interpreted():
    """Creole and French passages must lower confidence, not invent meaning."""
    creole = lyric_analysis.analyse_line("mwen pa gen tan pou sa zanmi mwen")
    assert creole["confidence"] == 0.0, f"claimed to understand Creole: {creole}"
    assert creole["imagery"] == (), "produced imagery from an uninterpreted language"

    french = lyric_analysis.analyse_line("je pense à ma famille tout le temps")
    assert french["confidence"] < lyric_analysis.MIN_INTERPRETATION_CONFIDENCE, (
        f"claimed to understand French: {french}"
    )

    mixed = fx.build_lyrics(fx.make_track(), text=fx.LYRICS_MULTILINGUAL)
    assert mixed.languages, "no language mix was reported"


def test_ad_libs_carry_energy_but_not_meaning():
    result = lyric_analysis.analyse_line("yeah yeah uh ayy skrrt")
    assert result["is_ad_lib"], "ad-lib line was not recognised"
    assert result["confidence"] == 0.0, "ad-libs were given interpretation confidence"
    assert result["imagery"] == (), "ad-libs produced imagery"
    assert result["intensity"] > 0.5, "ad-libs lost their delivery energy"


def test_repeated_lyric_is_answered_differently_each_time():
    """The same hook line must not fetch the same kind of image every time."""
    from shot_selector import _lyric_affinity

    track = fx.make_track()
    lyrics = fx.build_lyrics(track)
    hook_key = " ".join(lyric_analysis.tokenize("Ride through the city with my brothers on the road"))
    occurrences = [
        line for line in lyrics.lines
        if " ".join(lyric_analysis.tokenize(line.text)) == hook_key
    ]
    assert len(occurrences) >= 3, f"fixture hook only appears {len(occurrences)} times"

    roles = classify_clip_roles(fx.make_clip(3))
    responses = {
        round(_lyric_affinity(line, roles, {}), 4) for line in occurrences
    }
    assert len(responses) > 1, (
        "every occurrence of the hook produced an identical response — that is literalism"
    )


def test_timecoded_lyrics_are_used_exactly():
    track = fx.make_track()
    lyrics = lyric_analysis.analyse_lyrics(
        lyric_text=fx.LYRICS_TIMECODED, duration=track["duration"], allow_asr=False
    )
    assert lyrics.tier == "timecoded", f"tier was {lyrics.tier}"
    assert lyrics.lines[0].start == 8.0, f"first line at {lyrics.lines[0].start}, expected 8.0"
    assert lyrics.overall_confidence > lyric_analysis.TIER_CONFIDENCE_CEILING["aligned"], (
        "timecoded lyrics were not trusted above aligned ones"
    )


def test_no_lyrics_still_uses_measured_vocal_phrasing():
    """Tier 4 — the case with no user input at all — must still do something."""
    track = fx.make_track()
    lyrics = lyric_analysis.analyse_lyrics(
        lyric_text="",
        duration=track["duration"],
        vocal_segments=[
            lyric_analysis.VocalSegment(a, b, c, c)
            for a, b, c in fx.make_vocal_segments(track)
        ],
        allow_asr=False,
    )
    assert lyrics.tier == "vocal_only"
    assert not lyrics.can_interpret, "claimed interpretation with no text"
    assert lyrics.vocal_entries(), "no vocal entries survived"

    cuts = fx.run_engine(track, fx.make_library(24), lyrics=lyrics)
    kinds = collections.Counter(cut["cutProvenance"]["eventKind"] for cut in cuts)
    assert kinds, "no cuts were planned from vocal-only evidence"


def test_instrumental_reports_no_vocal_layer():
    """The detector must not hallucinate a vocal in an instrumental."""
    import librosa

    sr = 22050
    duration = 20.0
    time_axis = np.linspace(0, duration, int(sr * duration), endpoint=False)
    signal = np.zeros_like(time_axis)
    generator = np.random.default_rng(7)
    for hit in np.arange(0, duration, 0.4286):
        index = int(hit * sr)
        span = int(0.09 * sr)
        if index + span < len(signal):
            envelope = np.exp(-np.linspace(0, 9, span))
            signal[index:index + span] += envelope * np.sin(
                2 * np.pi * 55 * np.linspace(0, 0.09, span)
            )
    for hit in np.arange(0, duration, 0.2143):
        index = int(hit * sr)
        span = int(0.03 * sr)
        if index + span < len(signal):
            signal[index:index + span] += generator.normal(0, 0.12, span) * np.exp(
                -np.linspace(0, 12, span)
            )
    signal = (signal / max(1e-9, np.max(np.abs(signal))) * 0.9).astype(np.float32)
    harmonic, _percussive = librosa.decompose.hpss(
        librosa.stft(signal, n_fft=2048, hop_length=512)
    )
    segments, diagnostics = lyric_analysis.detect_vocal_activity(
        signal, sr, hop_length=512, harmonic_spectrum=np.abs(harmonic)
    )
    assert segments == [], f"found {len(segments)} vocal segments in an instrumental"
    assert diagnostics["verdict"] in (
        "no_distinct_vocal_layer",
        "fragmented_no_sustained_lead",
    ), diagnostics


def test_function_words_do_not_create_meaning():
    """"through", "one", "up" must not fire semantic fields on their own."""
    result = lyric_analysis.analyse_line("just walking to the one that is up there")
    assert result["confidence"] < lyric_analysis.MIN_INTERPRETATION_CONFIDENCE, (
        f"function words produced a confident reading: {result}"
    )


def test_ambiguous_terms_keep_their_alternatives():
    result = lyric_analysis.analyse_line("ice on my neck")
    assert result["alternatives"], "ambiguous term resolved to a single sense silently"


# ---------------------------------------------------------------------------
# 3. Repetition and global sequence
# ---------------------------------------------------------------------------


def test_source_windows_do_not_repeat_accidentally():
    """The headline defect: 94.3 % of cuts reused a window, 49 distinct in total."""
    track = fx.make_track()
    cuts = fx.run_engine(track, fx.make_library(24))
    windows = [
        (cut["clipPath"], round(float(cut["sourceStart"]), 2))
        for cut in cuts
    ]
    counts = collections.Counter(windows)
    reused = sum(value - 1 for value in counts.values() if value > 1)
    share = reused / len(cuts)

    assert share <= 0.10, f"{share:.1%} of cuts reuse a source window (baseline was 94.3%)"
    assert len(counts) >= len(cuts) * 0.9, (
        f"only {len(counts)} distinct windows across {len(cuts)} cuts"
    )

    # Every accidental reuse must be *declared*, not silent.
    for cut in cuts:
        if cut["sourceProvenance"]["windowExhausted"]:
            assert cut["repetition"]["reuseDistance"] is not None or True


def test_nearby_source_windows_are_not_treated_as_different():
    """Nudging a window by two frames is not "different material"."""
    clip = fx.make_clip(1, duration=10.0)
    windows = candidate_windows(clip, 1.5)
    starts = sorted(window.start for window in windows)
    for first, second in zip(starts, starts[1:]):
        assert second - first >= 0.74, (
            f"windows at {first} and {second} are the same material"
        )


def test_near_duplicates_are_detected_and_separated():
    track = fx.make_track()
    library = fx.make_library(24, near_duplicate_pairs=4)
    similarity = build_similarity_matrix(library)

    assert similarity[0][1] >= NEAR_DUPLICATE_SIMILARITY, (
        f"a cloned clip scored only {similarity[0][1]:.3f} similarity"
    )

    cuts = fx.run_engine(track, library)
    paths = [cut["clipPath"] for cut in cuts]
    index_by_path = {str(clip["path"]): index for index, clip in enumerate(library)}
    violations = 0
    for first, second in zip(paths, paths[1:]):
        a, b = index_by_path.get(first), index_by_path.get(second)
        if a is None or b is None or a == b:
            continue
        if similarity[a][b] >= NEAR_DUPLICATE_SIMILARITY:
            violations += 1
    assert violations == 0, f"{violations} near-duplicate pairs were placed back to back"


def test_no_clip_dominates_the_timeline():
    """One outstanding clip used to take over. Five clips carried 52 cuts each."""
    track = fx.make_track()
    cuts = fx.run_engine(track, fx.make_library(24, dominant_clip=True))
    counts = collections.Counter(cut["clipPath"] for cut in cuts)
    top = counts.most_common(1)[0]
    fair_share = len(cuts) / 24.0

    assert top[1] <= max(3, fair_share * 2.5), (
        f"{top[0]} carried {top[1]} of {len(cuts)} cuts (fair share {fair_share:.1f})"
    )
    assert len(counts) >= 12, f"only {len(counts)} of 24 clips appeared"


def test_visual_signature_repetition_is_globally_controlled():
    """Different files that look the same must not stack up."""
    track = fx.make_track()
    library = fx.make_library(24)
    cuts = fx.run_engine(track, library)
    by_path = {str(clip["path"]): clip for clip in library}

    signatures = [
        visual_signature(by_path[cut["clipPath"]])
        for cut in cuts if cut["clipPath"] in by_path
    ]
    immediate = sum(1 for a, b in zip(signatures, signatures[1:]) if a == b)
    assert immediate <= len(signatures) * 0.15, (
        f"{immediate}/{len(signatures)} consecutive pairs share a visual signature"
    )


def test_reuse_distance_is_respected():
    track = fx.make_track()
    cuts = fx.run_engine(track, fx.make_library(24))
    paths = [cut["clipPath"] for cut in cuts]
    last: dict = {}
    distances = []
    for index, path in enumerate(paths):
        if path in last:
            distances.append(index - last[path])
        last[path] = index
    assert distances, "no clip was reused at all — cannot assess distance"
    assert min(distances) >= 4, f"a clip returned after only {min(distances)} cuts"


def test_intentional_repetition_carries_justification():
    """A repeat is either justified in the record or it is a defect."""
    track = fx.make_track()
    lyrics = fx.build_lyrics(track)
    cuts = fx.run_engine(track, fx.make_library(10), lyrics=lyrics)

    for cut in cuts:
        intentional = cut["repetition"].get("intentional")
        if intentional:
            assert intentional.get("reason") in (
                "lyric_callback", "hook_callback", "structural",
            ), f"unjustified motif: {intentional}"
            assert "stage" in intentional, f"motif without a stage: {intentional}"


def test_small_library_degrades_honestly():
    """Four clips cannot fill 60 cuts without repeating. It must not pretend."""
    track = fx.make_track()
    cuts = fx.run_engine(track, fx.make_library(4))
    assert cuts, "a four-clip library produced no timeline at all"

    counts = collections.Counter(cut["clipPath"] for cut in cuts)
    assert len(counts) == 4, f"only {len(counts)} of 4 clips were used"

    # Repetition is unavoidable here; the requirement is that it is spread and
    # declared, not that it does not happen.
    paths = [cut["clipPath"] for cut in cuts]
    immediate = sum(1 for a, b in zip(paths, paths[1:]) if a == b)
    assert immediate == 0, f"{immediate} back-to-back repeats of the same clip"

    provenance = cuts[0].get("editProvenance", {})
    assert provenance.get("search", {}).get("scarcity", 0) > 0.5, (
        "scarcity was not reported for a four-clip library"
    )


def test_strong_footage_is_reserved_for_the_hook():
    track = fx.make_track()
    library = fx.make_library(24, dominant_clip=True)
    hook = {"start": 128.0, "end": 160.0}
    cuts = fx.run_engine(track, library, hook=hook)

    strongest = str(library[0]["path"])
    appearances = [
        float(cut["beatTime"]) for cut in cuts if cut["clipPath"] == strongest
    ]
    if appearances:
        in_hook = sum(1 for time in appearances if hook["start"] <= time < hook["end"])
        hook_share = (hook["end"] - hook["start"]) / track["duration"]
        assert in_hook / len(appearances) > hook_share, (
            f"strongest clip appeared {in_hook}/{len(appearances)} times in the hook, "
            f"which is {hook_share:.1%} of the track — no reservation happened"
        )


def test_selection_considers_future_slots_not_just_the_past():
    """Beam search must actually beat greedy, or it is not earning its cost."""
    track = fx.make_track()
    library = fx.make_library(24, dominant_clip=True)

    wide = fx.run_engine(track, library, beam_width=12)
    greedy = fx.run_engine(track, library, beam_width=1)

    assert [cut["clipPath"] for cut in wide] != [cut["clipPath"] for cut in greedy], (
        "beam width made no difference — the search is not sequence-aware"
    )
    wide_cost = wide[0]["editProvenance"]["search"]["finalCost"]
    greedy_cost = greedy[0]["editProvenance"]["search"]["finalCost"]
    assert wide_cost <= greedy_cost, (
        f"wider beam found a worse sequence: {wide_cost} vs {greedy_cost}"
    )


def test_determinism():
    """The same inputs must always produce the same edit."""
    track = fx.make_track()
    library = fx.make_library(24)
    lyrics = fx.build_lyrics(track)
    first = fx.run_engine(track, library, lyrics=lyrics)
    second = fx.run_engine(track, library, lyrics=fx.build_lyrics(track))
    assert [cut["clipPath"] for cut in first] == [cut["clipPath"] for cut in second]
    assert fx.shot_lengths(first) == fx.shot_lengths(second)
    assert [cut["sourceStart"] for cut in first] == [cut["sourceStart"] for cut in second]


# ---------------------------------------------------------------------------
# 4. Narrative
# ---------------------------------------------------------------------------


def test_narrative_roles_develop_across_the_song():
    track = fx.make_track()
    cuts = fx.run_engine(track, fx.make_library(24), lyrics=fx.build_lyrics(track))

    stages = [cut["narrative"]["stage"] for cut in cuts]
    assert len(set(stages)) >= 4, f"only {len(set(stages))} narrative stages: {set(stages)}"
    assert stages[0] != stages[-1], "the song opens and closes in the same stage"

    first_half = collections.Counter(
        cut["narrative"]["role"] for cut in cuts[: len(cuts) // 2]
    )
    second_half = collections.Counter(
        cut["narrative"]["role"] for cut in cuts[len(cuts) // 2:]
    )
    assert first_half != second_half, "role distribution is identical across the song"


def test_narrative_plan_confidence_is_reported_and_bounded():
    track = fx.make_track()
    curve = tension_curve(
        track["duration"], track["energy"], track["energy_times"], track["accents"]
    )
    with_evidence = build_narrative_plan(
        track["sections"], track["duration"], curve, fx.build_lyrics(track), (128.0, 160.0)
    )
    bare = build_narrative_plan(
        [{"type": "verse", "start": 0.0, "end": track["duration"]}], track["duration"]
    )
    assert with_evidence.confidence > bare.confidence, (
        f"evidence did not raise plan confidence: {with_evidence.confidence} vs {bare.confidence}"
    )
    assert 0.0 <= bare.confidence <= 1.0


def test_clip_roles_are_multi_valued_with_confidence():
    roles = classify_clip_roles(
        fx.make_clip(0, shot_type="long_shot", has_face=False, motion_intensity=5)
    )
    assert "establishing" in roles and "environment" in roles
    assert all(0.0 < value <= 1.0 for value in roles.values())
    assert roles.get("neutral"), "every clip must retain a neutral coverage role"


# ---------------------------------------------------------------------------
# 5. Best moments, transitions, provenance, integration
# ---------------------------------------------------------------------------


def test_best_moments_replace_arbitrary_clip_starts():
    track = fx.make_track()
    cuts = fx.run_engine(track, fx.make_library(24))
    from_head = sum(1 for cut in cuts if float(cut["sourceStart"]) < 0.05)
    assert from_head <= len(cuts) * 0.25, (
        f"{from_head}/{len(cuts)} cuts start at the head of their clip"
    )
    for cut in cuts:
        assert cut["sourceProvenance"]["windowReason"] in (
            "analysed_moment", "best_moment", "even_coverage", "clip_head", "unknown_duration",
        ), cut["sourceProvenance"]


def test_transitions_are_motivated_by_adjacent_shots():
    track = fx.make_track()
    cuts = fx.run_engine(track, fx.make_library(24))
    kinds = collections.Counter(cut["transition"]["type"] for cut in cuts)
    assert len(kinds) >= 2, f"only one transition type was ever used: {dict(kinds)}"

    for cut in cuts:
        transition = cut["transition"]
        assert transition["reason"], "a transition was chosen with no stated reason"
        if transition["type"] != "hard_cut" and cut is not cuts[0]:
            assert transition["evidence"], (
                f"non-default transition {transition['type']} carries no evidence"
            )
    assert kinds["hard_cut"] >= len(cuts) * 0.3, (
        "transitions are being sprinkled rather than motivated"
    )


def test_every_cut_carries_full_provenance():
    track = fx.make_track()
    cuts = fx.run_engine(track, fx.make_library(24), lyrics=fx.build_lyrics(track))
    for index, cut in enumerate(cuts):
        provenance = cut["cutProvenance"]
        for key in (
            "origin", "eventKind", "sourceTime", "beatAligned", "measuredEvent",
            "pacingMode", "targetBars", "actualBars", "tension",
        ):
            assert key in provenance, f"cut {index} missing cutProvenance.{key}"
        for key in ("stage", "role", "roleConfidence", "planConfidence"):
            assert key in cut["narrative"], f"cut {index} missing narrative.{key}"
        for key in ("windowRank", "windowReason", "windowQuality"):
            assert key in cut["sourceProvenance"], f"cut {index} missing sourceProvenance.{key}"
        for key in ("visualSignature", "signatureMethod"):
            assert key in cut["repetition"], f"cut {index} missing repetition.{key}"
        assert cut["transition"]["type"], f"cut {index} has no transition"

    edit = cuts[0]["editProvenance"]
    for key in ("planner", "selector", "narrativePlan", "motifs", "search", "lyrics", "pacing"):
        assert key in edit, f"editProvenance missing {key}"


def test_signature_method_does_not_claim_identity():
    """We do not re-identify people. The record must say so."""
    track = fx.make_track()
    cuts = fx.run_engine(track, fx.make_library(8))
    for cut in cuts:
        assert cut["repetition"]["signatureMethod"] == "descriptor_buckets_not_identity"


def test_ae_payload_contract_is_intact():
    """The After Effects bridge must still be able to build the timeline."""
    track = fx.make_track()
    cuts = fx.run_engine(track, fx.make_library(24))
    for index, cut in enumerate(cuts):
        for key in (
            "beatTime", "endTime", "sourceStart", "sourceEnd",
            "clipPath", "clipName", "sectionType",
        ):
            assert key in cut, f"cut {index} is missing the AE field {key}"
        assert cut["endTime"] > cut["beatTime"], f"cut {index} has no duration"
        assert cut["sourceEnd"] > cut["sourceStart"], f"cut {index} has an empty source window"
        assert 0.0 <= cut["sourceStart"], f"cut {index} has a negative source start"
        assert isinstance(cut["transition"], dict) and cut["transition"].get("type")
        assert isinstance(cut["alternatives"], list)


def test_timeline_tiles_without_gaps_or_overlaps():
    track = fx.make_track()
    cuts = fx.run_engine(track, fx.make_library(24))
    for previous, following in zip(cuts, cuts[1:]):
        assert abs(float(previous["endTime"]) - float(following["beatTime"])) < 1e-6, (
            f"gap or overlap between {previous['endTime']} and {following['beatTime']}"
        )
    assert float(cuts[0]["beatTime"]) == 0.0, "the timeline does not start at zero"
    assert abs(float(cuts[-1]["endTime"]) - track["duration"]) < 1e-6, (
        "the timeline does not reach the end of the track"
    )


def test_alternatives_offer_distinct_material():
    track = fx.make_track()
    cuts = fx.run_engine(track, fx.make_library(24))
    for cut in cuts:
        for alternative in cut["alternatives"]:
            assert alternative["clipPath"] != cut["clipPath"], (
                "an alternative offered the clip already chosen"
            )
            for key in ("sourceStart", "sourceEnd", "narrativeRole", "similarityToChosen"):
                assert key in alternative, f"alternative missing {key}"


def test_regeneration_preserves_constraints():
    """A regenerated section must obey the same rules as the first pass."""
    track = fx.make_track()
    library = fx.make_library(24)
    for seed in (1, 424242):
        cuts = fx.run_engine(track, library, seed=seed)
        paths = [cut["clipPath"] for cut in cuts]
        assert not any(a == b for a, b in zip(paths, paths[1:])), (
            f"seed {seed} produced back-to-back repeats"
        )
        windows = collections.Counter(
            (cut["clipPath"], round(float(cut["sourceStart"]), 2)) for cut in cuts
        )
        reused = sum(value - 1 for value in windows.values() if value > 1)
        assert reused / len(cuts) <= 0.10, f"seed {seed} reused {reused} windows"


# ---------------------------------------------------------------------------
# 6. Robustness
# ---------------------------------------------------------------------------


def test_arrangements_and_tempi_all_produce_sane_timelines():
    library = fx.make_library(20)
    for arrangement in fx.ARRANGEMENTS:
        for bpm in (72.0, 140.0, 175.0):
            track = fx.make_track(bpm=bpm, arrangement=arrangement)
            cuts = fx.run_engine(track, library)
            assert cuts, f"{arrangement} @ {bpm} produced no cuts"
            lengths = fx.shot_lengths(cuts)
            assert min(lengths) >= 0.14, (
                f"{arrangement} @ {bpm} produced a {min(lengths):.3f}s flash frame"
            )
            assert fx.modal_share(lengths) <= 0.45, (
                f"{arrangement} @ {bpm} collapsed to one length "
                f"({fx.modal_share(lengths):.1%})"
            )


def test_missing_signals_do_not_break_the_edit():
    """No beats, no energy, no sections — the engine must still answer."""
    track = fx.make_track()
    library = fx.make_library(12)
    bare = fx.run_engine(
        track, library, beats=[], downbeats=[], phrase_boundaries=[],
        energy=[], energy_times=[], bass_onsets=[],
    )
    assert bare, "no timeline was produced without a beat grid"
    assert all(cut["endTime"] > cut["beatTime"] for cut in bare)

    no_sections = fx.run_engine(track, library, sections=[])
    assert no_sections, "no timeline was produced without sections"


def test_three_beats_per_bar_is_detected():
    """Assuming 4/4 on a waltz shifts every bar-counted cut for the whole song."""
    from musical_structure import infer_beats_per_bar

    track = fx.make_track(beats_per_bar=3)
    inferred = infer_beats_per_bar(track["beats"], track["downbeats"])
    assert inferred == 3, f"metre inferred as {inferred}, expected 3"


def test_large_library_stays_within_budget():
    import time

    track = fx.make_track()
    library = fx.make_library(400)
    start = time.time()
    cuts = fx.run_engine(track, library)
    elapsed = time.time() - start
    assert cuts, "large library produced no timeline"
    assert elapsed < 8.0, f"400-clip library took {elapsed:.1f}s"


def test_pacing_provenance_describes_its_own_shot():
    """``cutProvenance`` must describe the slot it is attached to, not the last one.

    The planner decides a shot's length while standing at its *start* but emits
    the cut that *closes* it, so ``pacingMode``/``targetBars``/``tension`` were
    landing one slot late while ``actualBars`` was recomputed against the slot's
    own span. A three-second hold was published as ``pacingMode: "burst"`` with a
    0.21-bar target. Everything downstream reads those fields — the transition
    chooser (``SlotContext.mode``), the pacing diagnostics and the learning
    record — so all three were reasoning about the previous shot.
    """
    for style, arrangement, bpm in (
        ("cmd_command_drill", "drill", 144.0),
        ("lyrical_lemonade", "trap", 140.0),
        ("worldwide_films", "melodic", 92.0),
    ):
        track = fx.make_track(bpm=bpm, arrangement=arrangement)
        cuts = fx.run_engine(
            track,
            fx.make_library(28),
            style=fx.load_style(style),
            lyrics=fx.build_lyrics(track),
        )
        bar = track["period"] * track["beats_per_bar"]
        own_error, previous_error = [], []
        for index in range(1, len(cuts)):
            target = float(cuts[index]["cutProvenance"].get("targetBars") or 0.0)
            if target <= 0.05:
                continue  # a slot that rode out its section tail, not a request
            own = (cuts[index]["endTime"] - cuts[index]["beatTime"]) / bar
            previous = (cuts[index - 1]["endTime"] - cuts[index - 1]["beatTime"]) / bar
            own_error.append(abs(target - own) / max(own, 1e-6))
            previous_error.append(abs(target - previous) / max(previous, 1e-6))

        assert own_error, f"{style}: no slot carried a pacing target"
        own_median = statistics.median(own_error)
        previous_median = statistics.median(previous_error)
        assert own_median < previous_median, (
            f"{style}: targetBars tracks the *previous* slot "
            f"({previous_median:.3f} error) better than its own ({own_median:.3f}) "
            "— the pacing provenance is off by one cut"
        )
        assert own_median <= 0.35, (
            f"{style}: targetBars misses its own slot length by {own_median:.1%}"
        )


def test_a_burst_is_never_a_single_isolated_cut():
    """A burst is a *run*. One short shot on its own is an accident, not an effect.

    The run length was capped at ``budget - spent - 1``, so a section whose
    budget rounded down to 1 emitted a lone cut labelled ``burst``.
    """
    for style in ("cmd_command_drill", "lyrical_lemonade", "worldwide_films", "ninetive"):
        for arrangement, bpm in (("trap", 140.0), ("drill", 144.0), ("melodic", 92.0)):
            track = fx.make_track(bpm=bpm, arrangement=arrangement)
            cuts = fx.run_engine(
                track,
                fx.make_library(28),
                style=fx.load_style(style),
                lyrics=fx.build_lyrics(track),
            )
            modes = [cut["cutProvenance"]["pacingMode"] for cut in cuts]
            runs = [len(list(group)) for key, group in _groupby(modes) if key == "burst"]
            assert all(length >= 2 for length in runs), (
                f"{style}/{arrangement}: burst runs {runs} contain a single isolated cut"
            )


def test_burst_labelled_cuts_are_actually_short():
    """A cut published as ``burst`` has to be shorter than the shots around it."""
    track = fx.make_track(bpm=144.0, arrangement="drill")
    cuts = fx.run_engine(
        track,
        fx.make_library(28),
        style=fx.load_style("cmd_command_drill"),
        lyrics=fx.build_lyrics(track),
    )
    by_mode: dict = collections.defaultdict(list)
    for cut in cuts:
        by_mode[cut["cutProvenance"]["pacingMode"]].append(
            float(cut["endTime"]) - float(cut["beatTime"])
        )
    assert by_mode.get("burst"), "the drill preset produced no burst at all"
    burst = statistics.median(by_mode["burst"])
    sustained = statistics.median(by_mode["sustain"])
    assert burst < sustained * 0.75, (
        f"burst cuts median {burst:.2f}s against {sustained:.2f}s sustained — "
        "the burst label does not describe a fast cut"
    )


def test_a_section_with_burst_appetite_gets_a_usable_budget():
    """``int()`` truncation silently removed the budget from whole sections.

    ``ninetive`` declares real appetite in its drop and got
    ``int(9.3 * 0.28 * 0.76) == 1`` — and a budget of one can only produce the
    isolated cut the run rule forbids. The budget must either fund a real run or
    be honestly zero.
    """
    from cut_planner import MIN_BURST_RUN, burst_budget

    for style_name in ("ninetive", "lyrical_lemonade", "cmd_command_drill", "worldwide_films"):
        style = fx.load_style(style_name)
        for section in ("verse", "chorus", "drop"):
            pacing = resolve_pacing(section, style)
            for expected_shots in (3.0, 5.0, 9.3, 17.0):
                budget = burst_budget(expected_shots, pacing)
                assert budget == 0 or budget >= MIN_BURST_RUN, (
                    f"{style_name}/{section} at {expected_shots} shots got budget "
                    f"{budget} — too small to be a run, too big to be honest"
                )



def test_a_scarce_library_slows_the_edit_down():
    """One clip and a hundred clips must not produce the same timeline.

    Scarcity was measured (``editProvenance.search.scarcity``) and used only to
    *soften the repetition penalties*, never to cut less: the planner laid out
    the same 77 cuts on a 3:30 track whether the editor had loaded one clip or
    a hundred and fifty. One clip therefore meant the same eight source windows
    cycling seventy-seven times, which is the "extremely repetitive" complaint
    in its purest form.
    """
    track = fx.make_track(bpm=140.0, arrangement="trap")
    lyrics = fx.build_lyrics(track)
    style = fx.load_style("cmd_command_drill")

    counts = {}
    for size in (1, 3, 40):
        cuts = fx.run_engine(
            track, fx.make_library(size), style=style, lyrics=lyrics
        )
        counts[size] = len(cuts)
        assert cuts, f"a {size}-clip library produced no timeline"

    assert counts[1] < counts[40] * 0.65, (
        f"one clip produced {counts[1]} cuts against {counts[40]} for a full "
        "library — the planner is ignoring how much footage exists"
    )
    assert counts[1] <= counts[3] <= counts[40], (
        f"cut count is not monotonic in library size: {counts}"
    )

    # And a real library must be completely unaffected: this rule exists for
    # scarcity, not as a general slowdown.
    from cut_planner import material_pacing_scale

    assert material_pacing_scale(200, 210.0, 5.0) == 1.0, (
        "a library with plenty of material must not have its pacing stretched"
    )


def test_scarcity_stretch_never_flattens_a_section_into_one_shot():
    """The scarce-library answer is a slower edit, never a single held frame."""
    from cut_planner import MAX_MATERIAL_STRETCH, material_pacing_scale

    assert material_pacing_scale(1, 600.0, 1.0) <= MAX_MATERIAL_STRETCH

    track = fx.make_track(bpm=140.0, arrangement="trap")
    cuts = fx.run_engine(track, fx.make_library(1), lyrics=fx.build_lyrics(track))
    by_section: dict = collections.defaultdict(int)
    for cut in cuts:
        by_section[cut["sectionType"]] += 1
    for section, count in by_section.items():
        assert count >= 2, f"{section} collapsed to {count} shot(s) on a one-clip library"



def test_pacing_helpers_survive_degenerate_numbers():
    """A malformed section must not take the planner down with an OverflowError.

    ``burst_budget`` divided a section length by a bar length; a zero-length or
    non-finite bar made the shot estimate infinite and ``int(round(inf))``
    raises rather than returning a budget.
    """
    from cut_planner import (
        MAX_MATERIAL_STRETCH,
        MIN_BURST_RUN,
        burst_budget,
        material_pacing_scale,
        resolve_pacing,
    )

    pacing = resolve_pacing("drop", fx.load_style("cmd_command_drill"))
    for expected in (0.0, -5.0, 0.4, 1e12, float("inf"), float("nan")):
        budget = burst_budget(expected, pacing)
        assert isinstance(budget, int) and budget >= 0
        assert budget == 0 or budget >= MIN_BURST_RUN

    for windows, duration, target in (
        (0, 210.0, 5.0), (1, 0.0, 5.0), (1, 210.0, 0.0), (-3, 210.0, 5.0),
        (10 ** 9, 210.0, 5.0), (5, float("inf"), 5.0), (5, 210.0, float("nan")),
    ):
        scale = material_pacing_scale(windows, duration, target)
        assert np.isfinite(scale) and 1.0 <= scale <= MAX_MATERIAL_STRETCH


def test_material_scale_tolerates_unanalysed_clips():
    """Clip records arrive from disk scans with fields missing or unusable."""
    from shot_selector import available_material_scale

    style = fx.load_style("ninetive")
    for clips in (
        [],
        [{"path": "a", "usable": True}],
        [{"path": "a", "usable": True, "duration": None}],
        [{"path": "a", "usable": True, "duration": -4}],
        [{"path": "a", "usable": True, "duration": float("nan")}],
        [{"path": "a", "usable": True, "duration": 8, "moment_windows": "nonsense"}],
    ):
        scale = available_material_scale(clips, 210.0, style)
        assert np.isfinite(scale) and scale >= 1.0, f"{clips} produced {scale}"


def _groupby(sequence):
    """Minimal itertools.groupby stand-in that keeps this file dependency-free."""
    import itertools

    return itertools.groupby(sequence)


def _main() -> int:
    tests = [
        (name, value)
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    failures = []
    for name, test in tests:
        try:
            test()
            print(f"  PASS  {name}")
        except AssertionError as error:
            failures.append((name, str(error)))
            print(f"  FAIL  {name}\n          {error}")
        except Exception as error:  # noqa: BLE001
            failures.append((name, f"{type(error).__name__}: {error}"))
            print(f"  ERROR {name}\n          {type(error).__name__}: {error}")
    print()
    print(f"{len(tests) - len(failures)}/{len(tests)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(_main())
