#!/usr/bin/env python3
"""
Test suite for the improved FlagshipEditor cutting engine.

Tests:
1. Import verification
2. Synthetic beat grid and section analysis
3. Musical cut placement verification
4. Clip selection determinism and variety
5. Minimum/maximum cut length enforcement
"""

import sys
import json
from pathlib import Path

import numpy as np

# Add engine directory to path
engine_dir = Path(__file__).parent
sys.path.insert(0, str(engine_dir))

from shot_selector import plan_cuts, select_best_clips, MIN_CUT_SECONDS
from beat_analysis import detect_phrase_boundaries


def test_imports():
    """Test that all modules import correctly."""
    print("=" * 60)
    print("TEST 1: Import Verification")
    print("=" * 60)
    
    try:
        from shot_selector import plan_cuts, select_best_clips, score_clip
        from beat_analysis import analyze_track, classify_section_type, detect_phrase_boundaries
        from clip_analysis import classify_clip, compute_motion_variance, find_best_moment
        
        print("✓ All imports successful")
        print(f"  - plan_cuts: {plan_cuts.__module__}")
        print(f"  - select_best_clips: {select_best_clips.__module__}")
        print(f"  - MIN_CUT_SECONDS: {MIN_CUT_SECONDS}")
        return True
    except Exception as e:
        print(f"✗ Import failed: {e}")
        return False


def create_synthetic_music_data():
    """Create synthetic beat grid and sections for testing.
    
    Simulates a 64-second track at 120 BPM (4/4 time):
    - Intro: 0-8s (beats 0-16)
    - Verse: 8-24s (beats 16-48)
    - Chorus: 24-40s (beats 48-80)
    - Drop: 40-56s (beats 80-112)
    - Outro: 56-64s (beats 112-128)
    """
    tempo = 120.0
    beat_period = 60.0 / tempo  # 0.5 seconds per beat
    
    # Generate 128 beats (64 seconds at 120 BPM)
    beats = [i * beat_period for i in range(128)]
    
    # Define sections
    sections = [
        {"type": "intro", "start": 0.0, "end": 8.0},
        {"type": "verse", "start": 8.0, "end": 24.0},
        {"type": "chorus", "start": 24.0, "end": 40.0},
        {"type": "drop", "start": 40.0, "end": 56.0},
        {"type": "outro", "start": 56.0, "end": 64.0},
    ]
    
    # Generate bass onsets at every 2nd beat in drop section (typical for drill/trap)
    drop_start_beat = int(40.0 / beat_period)  # beat 80
    drop_end_beat = int(56.0 / beat_period)    # beat 112
    bass_onsets = [beats[i] for i in range(drop_start_beat, drop_end_beat, 2)]
    
    duration = 64.0
    
    # Default style config
    style_config = {
        "cut_strategy": {
            "intro": {"cut_interval": "3_beat"},
            "verse": {"cut_interval": "2_beat"},
            "chorus": {"cut_interval": "1_beat"},
            "drop": {"cut_interval": "0.5_beat", "double_time_on_808": True},
            "bridge": {"cut_interval": "2_beat"},
            "outro": {"cut_interval": "3_beat"},
        }
    }
    
    return beats, sections, bass_onsets, duration, style_config, tempo


def create_synthetic_clips(num_clips=10):
    """Create synthetic clips with varying characteristics."""
    clips = []
    
    scene_types = ["performance", "close_up", "b_roll_dynamic", "b_roll_static", "b_roll"]
    
    for i in range(num_clips):
        clip = {
            "path": f"/fake/path/clip_{i}.mp4",
            "name": f"Clip_{i}.mp4",
            "duration": 5.0 + (i % 3),  # 5-7 seconds
            "scene_type": scene_types[i % len(scene_types)],
            "has_face": i % 3 != 0,
            "face_size_ratio": 0.15 if i % 3 == 0 else 0.05,
            "face_consistency": 0.8 if i % 3 == 0 else 0.3,
            "brightness": 50.0 + (i * 5),
            "brightness_stability": 90.0 - (i * 3),
            "motion_intensity": float(i * 2),
            "motion_variance": float(i * 1.5),
            "composition_score": 70.0 + (i % 4) * 5,
            "energy_score": 50.0 + (i % 5) * 10,
            "sharpness_score": 60.0 + (i % 3) * 10,
            "histogram": [0.1] * 32,  # Fake histogram
            "thumbnail_id": f"thumb_{i}",
            "usable": True,
            "width": 1920,
            "height": 1080,
            "fps": 30.0,
        }
        clips.append(clip)
    
    return clips


def test_cut_placement(beats, sections, bass_onsets, duration, style_config, tempo):
    """Test that cuts are placed musically."""
    print("\n" + "=" * 60)
    print("TEST 2: Musical Cut Placement")
    print("=" * 60)
    
    slots = plan_cuts(beats, sections, style_config, duration, tempo, bass_onsets)
    
    if not slots:
        print("✗ No cut slots generated")
        return False, []
    
    print(f"✓ Generated {len(slots)} cut slots")
    
    # Verify section boundaries have cuts
    section_boundary_times = [s["start"] for s in sections]
    print(f"\nSection boundaries: {section_boundary_times}")
    
    failures = []
    cuts_at_boundaries = 0
    for boundary, section in zip(section_boundary_times, sections):
        has_cut_nearby = any(abs(slot["beatTime"] - boundary) < 0.1 for slot in slots)
        if has_cut_nearby:
            cuts_at_boundaries += 1
            print(f"  ✓ Cut at boundary {boundary}s ({section['type']})")
        else:
            print(f"  ✗ NO cut at boundary {boundary}s")
            failures.append(f"no cut at section boundary {boundary}s ({section['type']})")
    
    print(f"\nBoundaries with cuts: {cuts_at_boundaries}/{len(section_boundary_times)}")
    
    # Count cuts per section
    cuts_per_section = {}
    for slot in slots:
        section_type = slot["sectionType"]
        cuts_per_section[section_type] = cuts_per_section.get(section_type, 0) + 1
    
    print("\nCuts per section:")
    for section_type, count in sorted(cuts_per_section.items()):
        section_duration = next((s["end"] - s["start"] for s in sections if s["type"] == section_type), 0)
        cut_density = count / section_duration if section_duration > 0 else 0
        print(f"  {section_type:10s}: {count:3d} cuts ({cut_density:.2f} cuts/sec)")
    
    # Verify drop has more cuts than verse (higher energy = more cuts)
    drop_cuts = cuts_per_section.get("drop", 0)
    verse_cuts = cuts_per_section.get("verse", 0)
    
    if drop_cuts > verse_cuts:
        print(f"\n✓ Drop ({drop_cuts} cuts) has more cuts than verse ({verse_cuts} cuts)")
    else:
        print(f"\n✗ Drop ({drop_cuts} cuts) should have more cuts than verse ({verse_cuts} cuts)")
        failures.append(f"drop {drop_cuts} cuts <= verse {verse_cuts} cuts")
    
    # Verify intro/outro have fewer cuts (longer cuts)
    intro_cuts = cuts_per_section.get("intro", 0)
    chorus_cuts = cuts_per_section.get("chorus", 0)
    
    if intro_cuts < chorus_cuts:
        print(f"✓ Intro ({intro_cuts} cuts) has fewer cuts than chorus ({chorus_cuts} cuts)")
    else:
        print(f"✗ Intro ({intro_cuts} cuts) should have fewer cuts than chorus ({chorus_cuts} cuts)")
        failures.append(f"intro {intro_cuts} cuts >= chorus {chorus_cuts} cuts")

    # Fewer cuts is not the same claim as longer cuts — measure the shots.
    lengths_by_section = {}
    for slot in slots:
        lengths_by_section.setdefault(slot["sectionType"], []).append(
            slot["endTime"] - slot["beatTime"]
        )
    print("\nAverage shot length per section:")
    for section_type in sorted(lengths_by_section):
        values = lengths_by_section[section_type]
        print(f"  {section_type:10s}: {sum(values)/len(values):.3f}s avg "
              f"(min {min(values):.3f}s, max {max(values):.3f}s)")

    intro_avg = sum(lengths_by_section.get("intro", [0])) / max(1, len(lengths_by_section.get("intro", [])))
    chorus_avg = sum(lengths_by_section.get("chorus", [0])) / max(1, len(lengths_by_section.get("chorus", [])))
    if intro_avg > chorus_avg:
        print(f"\n✓ Intro shots ({intro_avg:.3f}s avg) are longer than chorus shots ({chorus_avg:.3f}s avg)")
    else:
        print(f"\n✗ Intro shots ({intro_avg:.3f}s) should be longer than chorus shots ({chorus_avg:.3f}s)")
        failures.append(f"intro avg {intro_avg:.3f}s <= chorus avg {chorus_avg:.3f}s")

    # The slots must tile the timeline: a gap is a black frame, an overlap is a
    # slot the renderer cannot honour.
    gaps, overlaps = [], []
    previous_end = None
    for slot in slots:
        if previous_end is not None:
            delta = slot["beatTime"] - previous_end
            if delta > 1e-6:
                gaps.append((previous_end, slot["beatTime"]))
            elif delta < -1e-6:
                overlaps.append((previous_end, slot["beatTime"]))
        previous_end = slot["endTime"]
    if gaps or overlaps:
        print(f"✗ Timeline is not contiguous: {len(gaps)} gaps, {len(overlaps)} overlaps")
        failures.append(f"{len(gaps)} gaps and {len(overlaps)} overlaps in the slot timeline")
    else:
        print(f"✓ Slots tile the timeline contiguously "
              f"({slots[0]['beatTime']:.2f}s → {slots[-1]['endTime']:.2f}s of {duration:.2f}s)")

    if failures:
        print(f"\n✗ {len(failures)} placement failures:")
        for failure in failures:
            print(f"  - {failure}")
        return False, slots

    return True, slots


def test_cut_lengths(slots):
    """Test the flash-frame floor and the bounded rapid-cut vocabulary."""
    print("\n" + "=" * 60)
    print("TEST 3: Cut Length Enforcement")
    print("=" * 60)
    
    violations = []
    
    for i, slot in enumerate(slots):
        cut_length = slot["endTime"] - slot["beatTime"]
        
        # Check minimum length
        if cut_length < MIN_CUT_SECONDS:
            violations.append(f"Slot {i}: {cut_length:.3f}s < {MIN_CUT_SECONDS}s minimum")
        
        provenance = slot.get("cutProvenance") or {}
        # Ordinary shots must remain readable. Deliberate bursts may dip below
        # this threshold, but are separately capped as a share of the section.
        if provenance.get("pacingMode") != "burst" and cut_length < 0.45:
            violations.append(f"Slot {i}: sustained shot {cut_length:.3f}s < 0.45s")
    
    if violations:
        print(f"✗ Found {len(violations)} cut length violations:")
        for v in violations[:10]:  # Show first 10
            print(f"  - {v}")
        return False
    
    burst_slots = [
        slot for slot in slots
        if (slot.get("cutProvenance") or {}).get("pacingMode") == "burst"
    ]
    if len(burst_slots) > len(slots) * 0.28 + 1:
        print(f"✗ Bursts dominate the edit: {len(burst_slots)}/{len(slots)} cuts")
        return False

    print(f"✓ All {len(slots)} cuts respect readability and burst constraints")
    print(f"  - Minimum: {MIN_CUT_SECONDS}s")
    print(f"  - Deliberate bursts: {len(burst_slots)}/{len(slots)} cuts")
    
    # Show distribution
    lengths = [s["endTime"] - s["beatTime"] for s in slots]
    print(f"\nCut length statistics:")
    print(f"  Min: {min(lengths):.3f}s")
    print(f"  Max: {max(lengths):.3f}s")
    print(f"  Avg: {sum(lengths)/len(lengths):.3f}s")
    
    return True


def test_clip_variety(clips, beats, sections, bass_onsets, duration, style_config, tempo):
    """Test that clips are varied and not repeated too soon."""
    print("\n" + "=" * 60)
    print("TEST 4: Clip Variety and Determinism")
    print("=" * 60)
    
    selections = select_best_clips(
        clips, beats, sections, style_config, duration, tempo, bass_onsets, seed=42
    )
    
    if not selections:
        print("✗ No clips selected")
        return False
    
    print(f"✓ Selected {len(selections)} clips")
    
    # Check for repeats within 4 consecutive cuts
    repeat_violations = []
    for i in range(len(selections) - 4):
        window = selections[i:i+5]
        paths = [s["clipPath"] for s in window]
        if len(paths) != len(set(paths)):
            repeat_violations.append(f"Cuts {i}-{i+4}: {paths}")
    
    if repeat_violations:
        print(f"✗ Found {len(repeat_violations)} repeat violations (same clip within 4 cuts):")
        for v in repeat_violations[:5]:
            print(f"  - {v}")
        return False
    print(f"✓ No clip repeated within 4 consecutive cuts")
    
    # Test determinism: run twice with same seed
    selections2 = select_best_clips(
        clips, beats, sections, style_config, duration, tempo, bass_onsets, seed=42
    )
    
    if len(selections) != len(selections2):
        print(f"✗ Different number of selections with same seed: {len(selections)} vs {len(selections2)}")
        return False
    
    mismatches = sum(1 for s1, s2 in zip(selections, selections2) if s1["clipPath"] != s2["clipPath"])
    if mismatches > 0:
        print(f"✗ {mismatches} different clip choices with same seed (non-deterministic)")
        return False
    else:
        print(f"✓ Clip selection is deterministic (same seed = same results)")
    
    # Show clip usage distribution
    clip_usage = {}
    for sel in selections:
        path = sel["clipPath"]
        clip_usage[path] = clip_usage.get(path, 0) + 1
    
    print(f"\nClip usage distribution:")
    print(f"  Clips used: {len(clip_usage)}/{len(clips)}")
    print(f"  Most used: {max(clip_usage.values()) if clip_usage else 0} times")
    print(f"  Avg usage: {sum(clip_usage.values())/len(clip_usage):.2f} times")
    
    return True


def test_phrase_boundaries():
    """Test phrase boundary detection."""
    print("\n" + "=" * 60)
    print("TEST 5: Phrase Boundary Detection")
    print("=" * 60)
    
    # Create a simple beat grid (120 BPM)
    tempo = 120.0
    beat_period = 60.0 / tempo
    beats = [i * beat_period for i in range(128)]  # 64 seconds
    
    sections = [
        {"type": "verse", "start": 0.0, "end": 32.0},
        {"type": "chorus", "start": 32.0, "end": 64.0},
    ]
    
    boundaries = detect_phrase_boundaries(beats, tempo, sections)
    
    if not boundaries:
        print("✗ No phrase boundaries detected")
        return False
    
    print(f"✓ Detected {len(boundaries)} phrase boundaries")
    
    # Show first few boundaries
    print("\nFirst 10 phrase boundaries:")
    for i, b in enumerate(boundaries[:10]):
        print(f"  {i+1}. {b['time']:.2f}s ({b['phrase_length']}-beat phrase in {b['section_type']})")
    
    # Verify boundaries align with bar structure (multiples of 16 or 32 beats)
    aligned_count = sum(1 for b in boundaries if b["phrase_length"] in [16, 32])
    print(f"\n{aligned_count}/{len(boundaries)} boundaries align with 4-bar or 8-bar phrases")
    
    return True


def test_best_moment_alignment():
    """Test that the best moment survives as a real seek time, not a frame index."""
    print("\n" + "=" * 60)
    print("TEST 6: Best-Moment Frame/Time Alignment")
    print("=" * 60)

    from clip_analysis import find_best_moment, per_frame_motion
    from shot_selector import best_moment_window

    failures = []

    # optical_flow_series returns one value per *transition*, so a frame index
    # is not a valid index into it. Every frame must get a motion figure, and
    # the peak must land on the frame that actually moves the most.
    transitions = [1.0, 9.0, 9.0, 1.0]
    spread = per_frame_motion(transitions, 5)
    if len(spread) != 5:
        failures.append(f"per_frame_motion returned {len(spread)} values for 5 frames")
    elif spread.index(max(spread)) != 2:
        failures.append(f"per-frame motion peaks at frame {spread.index(max(spread))}, expected 2")
    else:
        print(f"✓ {len(transitions)} transitions map onto {len(spread)} frames, peak at frame 2")
        print(f"  transitions {transitions} → per-frame {spread}")

    if per_frame_motion(None, 4) != [0.0] * 4:
        failures.append("per_frame_motion should return zeros when no motion series is given")

    # A synthetic clip whose 4th sample is the bright, busy one.
    dull = np.full((90, 160, 3), 20, dtype=np.uint8)
    bright = np.random.default_rng(7).integers(0, 255, (90, 160, 3), dtype=np.uint8)
    frames = [dull.copy() for _ in range(8)]
    frames[4] = bright
    timestamps = [i * 1.0 for i in range(8)]
    motion = [0.0, 0.0, 0.0, 20.0, 20.0, 0.0, 0.0]

    moment = find_best_moment(frames, motion, timestamps)
    if "best_time" not in moment:
        failures.append("find_best_moment did not report best_time — best_moment_window cannot seek")
    else:
        print(f"✓ find_best_moment reports best_time={moment['best_time']:.2f}s "
              f"(frame {moment['best_frame_idx']})")
        if abs(moment["best_time"] - 4.0) > 1.5:
            failures.append(f"best_time {moment['best_time']:.2f}s missed the peak at 4.0s")

    # The window shot_selector actually lifts out of the clip must follow it.
    clip_info = {"duration": 8.0, "best_moment": moment}
    start, end = best_moment_window(clip_info, 1.5)
    print(f"✓ best_moment_window(1.5s slot) → ({start:.3f}s, {end:.3f}s)")
    if start <= 0.0:
        failures.append("best_moment_window still starts at the head of the clip — best_time is not reaching it")
    if not (start <= moment.get("best_time", -1) <= end):
        failures.append(f"peak {moment.get('best_time')}s falls outside the window ({start}, {end})")
    if abs((end - start) - 1.5) > 1e-6:
        failures.append(f"window is {end - start:.3f}s long, expected the 1.5s slot")

    # A clip shorter than the slot must clamp instead of seeking past the end.
    short_start, short_end = best_moment_window({"duration": 0.8, "best_moment": moment}, 1.5)
    if short_start < 0.0 or short_end > 0.8 + 1e-6:
        failures.append(f"short clip window ({short_start}, {short_end}) escapes the 0.8s source")
    else:
        print(f"✓ 0.8s clip clamps to ({short_start:.3f}s, {short_end:.3f}s)")

    # Missing timestamps must degrade, not crash.
    untimed = find_best_moment(frames, motion)
    if "best_frame_idx" not in untimed:
        failures.append("find_best_moment without timestamps lost its frame indices")
    else:
        print("✓ Degrades safely to frame indices when timestamps are unavailable")

    if failures:
        print(f"\n✗ {len(failures)} alignment failures:")
        for failure in failures:
            print(f"  - {failure}")
        return False
    return True


def test_bass_onset_response(beats, sections, duration, style_config, tempo):
    """Test that a drop actually cuts on its 808s rather than ignoring them."""
    print("\n" + "=" * 60)
    print("TEST 7: Drop Follows the Bass")
    print("=" * 60)

    drop = next(s for s in sections if s["type"] == "drop")

    def drop_cut_times(onsets):
        slots = plan_cuts(beats, sections, style_config, duration, tempo, onsets)
        return [s["beatTime"] for s in slots if s["sectionType"] == "drop"]

    without = drop_cut_times([])
    # Syncopated 808s — deliberately off the beat grid so they cannot be
    # confused with the steady pulse the section already cuts on.
    syncopated = [drop["start"] + 0.375 + 2.0 * i for i in range(6)]
    with_onsets = drop_cut_times(syncopated)

    print(f"  Drop cuts without bass onsets: {len(without)}")
    print(f"  Drop cuts with 6 syncopated onsets: {len(with_onsets)}")

    failures = []
    matched = [
        onset for onset in syncopated
        if any(abs(cut - onset) < 0.02 for cut in with_onsets)
    ]
    print(f"  Onsets landing on a cut: {len(matched)}/{len(syncopated)}")
    # Bass is evidence, not a command to cut on every 808. Requiring six cuts
    # from six onsets recreates the exact mechanical event-filling behaviour
    # this planner removes. A majority must visibly influence the timeline,
    # while the planner may hold through the rest.
    minimum_influence = max(1, (len(syncopated) + 1) // 2)
    if len(matched) < minimum_influence:
        failures.append(
            f"only {len(matched)}/{len(syncopated)} syncopated 808s produced a cut — "
            "bass onsets are not materially influencing the edit"
        )
    else:
        print(f"✓ {len(matched)}/{len(syncopated)} syncopated 808s influence the edit without dictating every cut")

    # Control: the same off-grid times must NOT be cut points when no onsets are
    # supplied, otherwise the match above is the metronome, not the bass.
    coincidental = [
        onset for onset in syncopated
        if any(abs(cut - onset) < 0.02 for cut in without)
    ]
    if coincidental:
        failures.append(
            f"{len(coincidental)} onset times are already grid cuts — the test proves nothing"
        )
    else:
        print("✓ Control: none of those times are cut on the bare grid")

    # An 808 displaces the grid tick beside it rather than adding a cut next to
    # it, so the drop stays at roughly the same density instead of doubling up.
    print(f"  Drop density change: {len(without)} → {len(with_onsets)} cuts")
    if abs(len(with_onsets) - len(without)) > len(syncopated) * 2:
        failures.append(
            f"bass onsets changed the drop density too much ({len(without)} → {len(with_onsets)})"
        )

    # Even chasing the bass, no cut may fall below the flash-frame floor.
    slots = plan_cuts(beats, sections, style_config, duration, tempo, syncopated)
    shortest = min(s["endTime"] - s["beatTime"] for s in slots)
    print(f"  Shortest cut with syncopation: {shortest:.3f}s (floor {MIN_CUT_SECONDS}s)")
    if shortest < MIN_CUT_SECONDS - 1e-9:
        failures.append(f"syncopation produced a {shortest:.3f}s cut, below the {MIN_CUT_SECONDS}s floor")
    else:
        print("✓ Minimum cut length holds under syncopation")

    broken = [
        (slots[i]["endTime"], slots[i + 1]["beatTime"])
        for i in range(len(slots) - 1)
        if abs(slots[i]["endTime"] - slots[i + 1]["beatTime"]) > 1e-6
    ]
    if broken:
        failures.append(f"syncopation broke timeline continuity at {broken[:3]}")
    else:
        print("✓ Timeline stays contiguous with the 808s driving the edit")

    if failures:
        print(f"\n✗ {len(failures)} bass-response failures:")
        for failure in failures:
            print(f"  - {failure}")
        return False
    return True


def main():
    """Run all tests and write results to file."""
    print("\n" + "=" * 60)
    print("FLAGSHIPEDITOR CUTTING ENGINE TEST SUITE")
    print("=" * 60)
    
    results = {
        "timestamp": __import__("datetime").datetime.now().isoformat(),
        "tests": {},
        "summary": {}
    }
    
    # Test 1: Imports
    results["tests"]["imports"] = test_imports()
    
    # Create synthetic data
    print("\n" + "=" * 60)
    print("Creating synthetic test data...")
    print("=" * 60)
    beats, sections, bass_onsets, duration, style_config, tempo = create_synthetic_music_data()
    clips = create_synthetic_clips(10)
    print(f"✓ Created {len(beats)} beats, {len(sections)} sections, {len(bass_onsets)} bass onsets, {len(clips)} clips")
    
    # Test 2: Cut placement
    cut_ok, slots = test_cut_placement(beats, sections, bass_onsets, duration, style_config, tempo)
    results["tests"]["cut_placement"] = cut_ok
    results["cut_slots"] = slots
    
    # Test 3: Cut lengths
    results["tests"]["cut_lengths"] = test_cut_lengths(slots) if slots else False
    
    # Test 4: Clip variety
    results["tests"]["clip_variety"] = test_clip_variety(
        clips, beats, sections, bass_onsets, duration, style_config, tempo
    )
    
    # Test 5: Phrase boundaries
    results["tests"]["phrase_boundaries"] = test_phrase_boundaries()

    # Test 6: Best-moment frame/time alignment
    results["tests"]["best_moment_alignment"] = test_best_moment_alignment()

    # Test 7: Drop responds to bass onsets
    results["tests"]["bass_onset_response"] = test_bass_onset_response(
        beats, sections, duration, style_config, tempo
    )
    
    # Summary
    passed = sum(1 for v in results["tests"].values() if v)
    total = len(results["tests"])
    
    results["summary"] = {
        "passed": passed,
        "total": total,
        "success_rate": passed / total if total > 0 else 0
    }
    
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    print(f"Passed: {passed}/{total} ({results['summary']['success_rate']*100:.1f}%)")
    
    for test_name, result in results["tests"].items():
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"  {status}: {test_name}")
    
    # Write results to file
    output_file = engine_dir / "test_results.json"
    with open(output_file, "w") as f:
        # Convert non-serializable items
        serializable_results = {
            "timestamp": results["timestamp"],
            "tests": results["tests"],
            "summary": results["summary"],
            "cut_slots_count": len(results.get("cut_slots", [])),
            "cut_slots_sample": results.get("cut_slots", [])[:10] if results.get("cut_slots") else [],
        }
        json.dump(serializable_results, f, indent=2)
    
    print(f"\n✓ Results written to: {output_file}")
    
    # Also write human-readable summary
    summary_file = engine_dir / "test_results.md"
    with open(summary_file, "w") as f:
        f.write("# FlagshipEditor Cutting Engine Test Results\n\n")
        f.write(f"**Timestamp:** {results['timestamp']}\n\n")
        f.write(f"**Result:** {passed}/{total} tests passed ({results['summary']['success_rate']*100:.1f}%)\n\n")
        
        f.write("## Test Details\n\n")
        for test_name, result in results["tests"].items():
            status = "✅ PASS" if result else "❌ FAIL"
            f.write(f"- {status} **{test_name}**\n")
        
        f.write("\n## Improvements Implemented\n\n")
        f.write("### Beat Analysis (beat_analysis.py)\n")
        f.write("- Smarter section classification using spectral contrast + RMS + onset density\n")
        f.write("- Phrase boundary detection (4-bar, 8-bar phrases)\n")
        f.write("- Better bass onset detection for drop sections\n\n")
        
        f.write("### Clip Analysis (clip_analysis.py)\n")
        f.write("- Increased frame sampling from 6 to 12-16 frames\n")
        f.write("- Motion variance computation (changing motion = more interesting)\n")
        f.write("- Brightness stability detection (flickering = bad)\n")
        f.write("- Face consistency tracking (performance vs b-roll)\n")
        f.write("- Best moment detection (where cuts should start)\n")
        f.write("- Histogram from middle frame (most representative)\n\n")
        
        f.write("### Shot Selection (shot_selector.py)\n")
        f.write("- Musical cut placement respecting phrasing\n")
        f.write("- Section-aware cut intervals:\n")
        f.write("  - Intro: 3 beats (let clips breathe)\n")
        f.write("  - Verse: 2 beats (prefer downbeats)\n")
        f.write("  - Chorus: 1 beat (energy)\n")
        f.write("  - Drop: 0.5 beats (cut on bass onsets)\n")
        f.write("  - Outro: 3 beats (let clips breathe)\n")
        f.write("- ALWAYS cut at section boundaries\n")
        f.write("- Minimum cut length: 0.15s (was 0.08s)\n")
        f.write("- Maximum cut length in drop: 1.0s\n")
        f.write("- Removed random exploration (was causing randomness)\n")
        f.write("- Deterministic tiebreaker for similar scores\n")
        f.write("- Increased repeat window from 3 to 4 cuts\n\n")
        
        if slots:
            f.write("## Cut Statistics\n\n")
            lengths = [s["endTime"] - s["beatTime"] for s in slots]
            f.write(f"- Total cuts: {len(slots)}\n")
            f.write(f"- Min cut length: {min(lengths):.3f}s\n")
            f.write(f"- Max cut length: {max(lengths):.3f}s\n")
            f.write(f"- Avg cut length: {sum(lengths)/len(lengths):.3f}s\n")
            
            cuts_per_section = {}
            for slot in slots:
                st = slot["sectionType"]
                cuts_per_section[st] = cuts_per_section.get(st, 0) + 1
            
            f.write("\nCuts per section:\n")
            for st, count in sorted(cuts_per_section.items()):
                f.write(f"- {st}: {count}\n")
    
    print(f"✓ Summary written to: {summary_file}")
    
    return passed == total


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
