#!/usr/bin/env python3
"""Deterministic engine contract checks that do not require media fixtures."""

from pathlib import Path
import os
import tempfile
import sys

import numpy as np
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))

import beat_analysis
from beat_analysis import (
    assign_section_types,
    band_onsets,
    detect_hook_section,
    detect_phrase_boundaries,
    drop_label_provenance,
    energy_envelope,
    estimate_downbeat_phase,
    label_provenance,
    separate_percussion,
)
import clip_analysis
from clip_analysis import (
    ANALYSIS_SAMPLE_WINDOW,
    SHOT_TYPES,
    _dnn_face_boxes,
    _resolve_face_model,
    classify_camera_movement,
    classify_shot_type,
    compute_visual_scores,
    detect_faces,
    flow_descriptors,
    motion_sample_policy,
    parse_frame_rate,
    resize_for_analysis,
)
from shot_selector import (
    CUT_ORIGINS,
    cut_energy_target,
    energy_match_adjustment,
    filter_clips_for_section,
    histogram_distance,
    normalize_motion_evidence,
    plan_cuts,
    reserved_clip_paths,
    score_clip,
    select_best_clips,
    track_energy_curve,
)
from server import (
    ScoreRequest,
    ShotSelectionRequest,
    score_clip_endpoint,
    select_shots as select_shots_endpoint,
)


def main() -> None:
    assert parse_frame_rate("30000/1001") == 30000 / 1001
    assert parse_frame_rate("0/0") == 30.0
    assert parse_frame_rate("not-a-rate") == 30.0
    assert parse_frame_rate(None) == 30.0
    resized = resize_for_analysis(np.zeros((2160, 3840, 3), dtype=np.uint8), 640)
    assert max(resized.shape[:2]) == 640
    visual = compute_visual_scores(
        [
            np.zeros((90, 160, 3), dtype=np.uint8),
            np.full((90, 160, 3), 180, dtype=np.uint8),
        ],
        motion=4.0,
    )
    assert len(visual["histogram"]) == 32
    assert abs(sum(visual["histogram"]) - 1.0) < 1e-9
    for key in ("composition_score", "energy_score", "sharpness_score"):
        assert 0.0 <= visual[key] <= 100.0
    assert histogram_distance([1, 0], [1, 0]) == 0.0
    assert histogram_distance([1, 0], [0, 1]) == 100.0
    strong = score_clip({
        "path": "strong.mov",
        "name": "strong.mov",
        "composition_score": 90,
        "energy_score": 85,
        "sharpness_score": 95,
        "motion_intensity": 2,
        "has_face": True,
        "face_size_ratio": 0.15,
        "histogram": [1, 0],
    })
    weak = score_clip({
        "path": "weak.mov",
        "name": "weak.mov",
        "composition_score": 15,
        "energy_score": 20,
        "sharpness_score": 10,
        "motion_intensity": 40,
        "has_face": False,
        "histogram": [0, 1],
    })
    assert strong["composite"] > weak["composite"]

    # New fields are additive: a schema-v4/cache-era record has no energy,
    # shot-scale, or camera evidence and must retain a neutral score.
    legacy = score_clip({"path": "legacy.mov", "name": "legacy.mov"}, section_type="drop")
    assert legacy["shotType"] == "unknown"
    assert legacy["cameraMovement"] == "unknown"
    assert energy_match_adjustment({"path": "legacy.mov"}, "drop") == 0.0
    assert energy_match_adjustment({"energy_score": 10}, "intro") > energy_match_adjustment(
        {"energy_score": 90}, "intro"
    )
    assert energy_match_adjustment({"energy_score": 90}, "drop") > energy_match_adjustment(
        {"energy_score": 10}, "drop"
    )

    # The professional shot scale exposes all seven ordered levels while
    # preserving an explicit unknown when no frame evidence exists.
    frame = np.zeros((32, 32, 3), dtype=np.uint8)
    ratios = (0.50, 0.30, 0.20, 0.10, 0.05, 0.02, 0.005)
    measured_types = tuple(
        classify_shot_type(
            [frame],
            {"has_face": True, "face_size_ratio": ratio, "face_consistency": 1.0},
        )["shot_type"]
        for ratio in ratios
    )
    assert measured_types == SHOT_TYPES
    assert classify_shot_type([], {})["shot_type"] == "unknown"

    # Camera movement classification must degrade to unknown without optional
    # CV evidence and separate the five supported movement families when it is
    # present.
    assert classify_camera_movement([])["camera_movement"] == "unknown"
    motion_cases = {
        "static": [{"magnitude": 0.1, "mean_x": 0.0, "mean_y": 0.0, "coherence": 0.0, "radial": 0.0}],
        "pan": [{"magnitude": 2.0, "mean_x": 2.0, "mean_y": 0.1, "coherence": 0.95, "radial": 0.0}] * 3,
        "tilt": [{"magnitude": 2.0, "mean_x": 0.1, "mean_y": 2.0, "coherence": 0.95, "radial": 0.0}] * 3,
        "push_pull": [{"magnitude": 2.0, "mean_x": 0.1, "mean_y": 0.1, "coherence": 0.1, "radial": 0.8}] * 3,
        "handheld": [
            {"magnitude": 2.0, "mean_x": 2.0, "mean_y": 0.0, "coherence": 0.2, "radial": 0.0},
            {"magnitude": 2.0, "mean_x": -2.0, "mean_y": 0.0, "coherence": 0.2, "radial": 0.0},
        ],
    }
    for expected, descriptors in motion_cases.items():
        assert classify_camera_movement(descriptors)["camera_movement"] == expected

    # HPSS must keep a held 55 Hz 808 out of attack evidence while retaining
    # four deliberately injected bass transients.
    sample_rate = 22050
    sample_times = np.arange(sample_rate * 2, dtype=np.float64) / sample_rate
    synthetic = 0.3 * np.sin(2.0 * np.pi * 55.0 * sample_times)
    expected_attacks = (0.25, 0.75, 1.25, 1.75)
    for attack_time in expected_attacks:
        start = int(attack_time * sample_rate)
        burst = np.hanning(400)
        synthetic[start : start + len(burst)] += burst
    separated = separate_percussion(synthetic.astype(np.float32), sample_rate)
    attacks = band_onsets(
        separated["bass_band"],
        sample_rate,
        separated["hop_length"],
        0.116,
        0.30,
        6,
    )
    assert separated["source"] == "percussive"
    assert len(attacks) == len(expected_attacks)
    assert all(abs(float(actual) - expected) < 0.08 for actual, expected in zip(attacks, expected_attacks))

    # The duration guard must run before the full complex STFT is allocated.
    # This protects long-form input on the packaged 8 GB Windows baseline.
    original_limit = beat_analysis.HPSS_MAX_SECONDS
    original_stft = beat_analysis.librosa.stft
    stft_called = False

    def forbidden_stft(*_args, **_kwargs):
        nonlocal stft_called
        stft_called = True
        raise AssertionError("duration guard ran after STFT allocation")

    try:
        beat_analysis.HPSS_MAX_SECONDS = 0.01
        beat_analysis.librosa.stft = forbidden_stft
        guarded = separate_percussion(np.zeros(441, dtype=np.float32), sample_rate)
    finally:
        beat_analysis.HPSS_MAX_SECONDS = original_limit
        beat_analysis.librosa.stft = original_stft
    assert not stft_called
    assert guarded["source"] == "full_mix"
    assert guarded["bass_band"] is None and guarded["hihat_band"] is None

    hook = detect_hook_section(
        [
            {"type": "verse", "start": 0.0, "end": 2.0},
            {"type": "chorus", "start": 2.0, "end": 4.0},
        ],
        np.asarray([0.1, 0.1, 0.9, 0.9]),
        np.asarray([0.0, 1.0, 2.0, 3.0]),
        [2.1, 2.5, 3.0],
        [{"start": 2.0, "end": 4.0}],
        4.0,
    )
    assert hook and hook["index"] == 1 and hook["type"] == "chorus"
    produced_types = [
        {"scene_type": scene_type}
        for scene_type in (
            "close_up", "performance", "b_roll_low_light",
            "b_roll_static", "b_roll_dynamic", "b_roll",
        )
    ]
    for section_type in ("intro", "verse", "chorus", "drop", "bridge", "outro"):
        assert filter_clips_for_section(produced_types, section_type, {})
    assert not filter_clips_for_section([{"scene_type": "unknown", "usable": False}], "verse", {})

    selector_clips = [
        {
            "path": "/fixtures/clip-a.mov",
            "name": "clip-a.mov",
            "duration": 4.0,
            "scene_type": "performance",
            "usable": True,
        },
        {
            "path": "/fixtures/clip-b.mov",
            "name": "clip-b.mov",
            "duration": 4.0,
            "scene_type": "b_roll_dynamic",
            "usable": True,
        },
    ]
    selector_args = (
        [0.0, 0.5, 1.0, 1.5],
        [{"type": "verse", "start": 0.0, "end": 2.0}],
        {},
        2.0,
        120.0,
        [],
    )
    normal = select_best_clips(selector_clips, *selector_args)
    assert normal and {entry["clipPath"] for entry in normal} <= {
        "/fixtures/clip-a.mov",
        "/fixtures/clip-b.mov",
    }
    assert all(
        {"sourceStart", "sourceEnd", "shotType", "cameraMovement"} <= entry.keys()
        for entry in normal
    )
    original_windows_path = r"C:\Fixtures\Clip-A.mov"
    windows_normal = select_best_clips(
        [dict(selector_clips[0], path=original_windows_path)], *selector_args
    )
    assert windows_normal
    assert all(entry["clipPath"] == original_windows_path for entry in windows_normal)

    for invalid_clips, expected_text in (
        ([dict(selector_clips[0], path="")], "non-empty"),
        ([selector_clips[0], dict(selector_clips[0])], "Duplicate usable clip path"),
        (
            [selector_clips[0], dict(selector_clips[0], path="/fixtures/./clip-a.mov")],
            "Duplicate usable clip path",
        ),
    ):
        try:
            select_best_clips(invalid_clips, *selector_args)
        except ValueError as error:
            assert expected_text in str(error)
        else:
            raise AssertionError(f"selector accepted invalid clip identities: {invalid_clips!r}")

    # Small and homogeneous libraries must never be starved by reservation,
    # and long selections remain deterministic regardless of the legacy seed.
    homogeneous = [
        {
            "path": f"/fixtures/homogeneous-{index}.mov",
            "name": f"homogeneous-{index}.mov",
            "duration": 12.0,
            "scene_type": "performance",
            "usable": True,
            "composition_score": 50.0 + index,
            "energy_score": 50.0,
            "sharpness_score": 60.0,
        }
        for index in range(4)
    ]
    assert reserved_clip_paths(homogeneous) == set()
    long_beats = [index * 0.5 for index in range(480)]
    long_sections = [
        {"type": "verse", "start": 0.0, "end": 80.0},
        {"type": "chorus", "start": 80.0, "end": 160.0},
        {"type": "verse", "start": 160.0, "end": 240.0},
    ]
    long_hook = {"start": 80.0, "end": 160.0}
    long_a = select_best_clips(
        homogeneous, long_beats, long_sections, {}, 240.0, 120.0, [], seed=1, hook=long_hook
    )
    long_b = select_best_clips(
        homogeneous, long_beats, long_sections, {}, 240.0, 120.0, [], seed=999, hook=long_hook
    )
    assert long_a == long_b
    assert {entry["clipPath"] for entry in long_a} == {
        entry["path"] for entry in homogeneous
    }

    # With enough footage to reserve, the strongest third must appear more
    # often inside the measured hook than in the held-back run-up. This is a
    # behavioural assertion, not merely a test that paths were ranked.
    scenes = (
        "performance",
        "close_up",
        "b_roll_dynamic",
        "b_roll_static",
        "b_roll",
        "b_roll_with_face",
    )
    shots = (
        "close_up",
        "medium_close_up",
        "medium_shot",
        "medium_long_shot",
        "long_shot",
        "extreme_long_shot",
        "extreme_close_up",
    )
    movements = ("static", "pan", "tilt", "push_pull", "handheld")
    reservation_clips = []
    for index in range(9):
        histogram = [0.0] * 32
        histogram[index] = 1.0
        quality = index / 8.0
        reservation_clips.append(
            {
                "path": f"/fixtures/reservation-{index}.mov",
                "name": f"reservation-{index}.mov",
                "duration": 12.0 + index * 0.2,
                "scene_type": scenes[index % len(scenes)],
                "shot_type": shots[index % len(shots)],
                "camera_movement": movements[index % len(movements)],
                "has_face": index % 3 != 2,
                "face_size_ratio": 0.05 + 0.02 * (index % 6),
                "face_consistency": 0.2 + 0.15 * (index % 5),
                "brightness_stability": 50.0 + 45.0 * quality,
                "motion_intensity": 1.0 + 30.0 * ((index * 7) % 9) / 9.0,
                "motion_variance": 0.2 + 10.0 * ((index * 5) % 9) / 9.0,
                "composition_score": 45.0 + 50.0 * quality,
                "sharpness_score": 45.0 + 50.0 * quality,
                "energy_score": 15.0 + 80.0 * ((index * 11) % 9) / 9.0,
                "histogram": histogram,
                "thumbnail_id": f"reservation-{index}",
                "usable": True,
                "best_moment": {"best_time": 3.0 + index * 0.1},
            }
        )
    reservation_sections = [
        {"type": "intro", "start": 0.0, "end": 12.0},
        {"type": "verse", "start": 12.0, "end": 48.0},
        {"type": "drop", "start": 48.0, "end": 80.0},
        {"type": "outro", "start": 80.0, "end": 100.0},
    ]
    reservation_hook = {"start": 48.0, "end": 80.0}
    reserved = reserved_clip_paths(reservation_clips)
    reserved_selection = select_best_clips(
        reservation_clips,
        [index * 0.5 for index in range(200)],
        reservation_sections,
        {},
        100.0,
        120.0,
        [48.0 + index * 0.75 for index in range(40)],
        hook=reservation_hook,
    )
    run_up = [
        entry
        for entry in reserved_selection
        if entry["endTime"] <= 48.0 and entry["sectionType"] not in ("chorus", "drop")
    ]
    hook_cuts = [
        entry
        for entry in reserved_selection
        if entry["beatTime"] < 80.0 and entry["endTime"] > 48.0
    ]
    run_up_share = sum(entry["clipPath"] in reserved for entry in run_up) / len(run_up)
    hook_share = sum(entry["clipPath"] in reserved for entry in hook_cuts) / len(hook_cuts)
    assert hook_share > run_up_share

    # Selector identity violations are invalid client input, not backend faults.
    invalid_request = ShotSelectionRequest(
        clips=[
            {"path": "C:/same.mov", "duration": 2.0},
            {"path": "c:/SAME.mov", "duration": 2.0},
        ],
        beats=[0.0, 1.0],
        sections=[{"type": "verse", "start": 0.0, "end": 2.0}],
        styleConfig={},
        duration=2.0,
        tempo=120.0,
        bassOnsets=[],
        seed=1,
    )
    try:
        select_shots_endpoint(invalid_request)
    except HTTPException as error:
        assert error.status_code == 422
        assert "Invalid shot-selection input" in str(error.detail)
    else:
        raise AssertionError("duplicate clip identities must produce HTTP 422")

    # --- B06: the energy curve is published with its own time base ----------
    envelope = energy_envelope([0.0, 0.5, 1.0, 0.25], 22050, 512, 2048)
    step = 512.0 / 22050.0
    assert len(envelope["energy_times"]) == len(envelope["energy"]) == 4
    assert all(
        abs(envelope["energy_times"][index] - index * step) <= 1e-3 for index in range(4)
    )
    assert envelope["energy_times"] == sorted(envelope["energy_times"])
    assert envelope["energy_sample_rate"] == 22050.0
    assert envelope["energy_hop_length"] == 512
    assert envelope["energy_frame_length"] == 2048
    # A NaN never reaches the published curve, and never disappears silently.
    sanitised = energy_envelope([float("nan"), float("inf"), 0.5], 22050, 512, 2048)
    assert sanitised["energy_nonfinite_samples"] == 2
    assert all(np.isfinite(value) for value in sanitised["energy"])
    # A zero or missing sample rate cannot produce a zero-length time base.
    fallback = energy_envelope([0.1, 0.2], 0, 0, 2048)
    assert fallback["energy_times"][1] > fallback["energy_times"][0]

    # --- B09: musical labels carry a measured method and a confidence -------
    grid = [index * 0.5 for index in range(32)]
    accented = estimate_downbeat_phase(grid, [1.0 + index * 2.0 for index in range(8)])
    assert accented["phase"] == 2 and accented["method"] == "bass_accent_phase"
    assert 0.0 < accented["confidence"] <= 1.0
    # With no accent evidence the old assumption survives — labelled as one.
    assert estimate_downbeat_phase(grid, [])["method"] == "assumed_first_beat"
    assert estimate_downbeat_phase(grid, [])["phase"] == 0
    assert estimate_downbeat_phase([0.0, 0.5], [0.0])["method"] == "insufficient_beats"
    phase_shifted = plan_cuts(
        grid,
        [{"type": "verse", "start": 0.0, "end": 8.0}],
        {},
        8.0,
        120.0,
        [],
        [],
        [0.5, 2.5, 4.5, 6.5],
    )
    measured_grid_times = [
        slot["beatTime"]
        for slot in phase_shifted
        if slot["cutProvenance"]["origin"] == "grid"
    ]
    assert measured_grid_times and measured_grid_times[0] == 0.5
    labelled = assign_section_types(
        [
            {"type": "verse", "start": 0.0, "end": 1.0},
            {"type": "chorus", "start": 1.0, "end": 2.0},
            {"type": "verse", "start": 2.0, "end": 3.0},
            {"type": "verse", "start": 3.0, "end": 4.0},
        ],
        np.concatenate(
            [
                0.1 * np.sin(2.0 * np.pi * 220.0 * np.arange(sample_rate) / sample_rate),
                0.6 * np.sin(2.0 * np.pi * 220.0 * np.arange(sample_rate) / sample_rate),
                0.1 * np.sin(2.0 * np.pi * 220.0 * np.arange(sample_rate) / sample_rate),
                0.1 * np.sin(2.0 * np.pi * 220.0 * np.arange(sample_rate) / sample_rate),
            ]
        ).astype(np.float32),
        sample_rate,
    )
    assert labelled[0]["type"] == "intro" and labelled[0]["label_source"] == "positional"
    assert labelled[1]["type"] == "drop" and labelled[1]["label_source"] == "measured_energy"
    assert all(section.get("measured_type") for section in labelled)
    assert all(0.0 <= section["label_confidence"] <= 1.0 for section in labelled)
    drop_label = drop_label_provenance(labelled)
    assert drop_label["method"] == "measured_energy"
    assert drop_label["candidates"] == 1 and 0.0 <= drop_label["confidence"] <= 1.0
    assert label_provenance("unit", 4.0, "claim")["confidence"] == 1.0
    assert label_provenance("unit", float("nan"), "claim")["confidence"] == 0.0

    # --- CACHE-BEAT-PROVENANCE / C02: identity moves when the analysis does --
    beat_identity = beat_analysis.analysis_identity()
    assert {"schema", "code", "config", "dependencies"} <= set(beat_identity)
    assert len(beat_identity["code"]) == 64
    clip_identity = clip_analysis.analysis_identity()
    assert {"schema", "code", "config", "tools", "dependencies"} <= set(clip_identity)
    assert {"ffmpeg", "ffprobe"} <= set(clip_identity["tools"])
    with tempfile.TemporaryDirectory(prefix="flagship-identity-") as identity_dir:
        audio_fixture = Path(identity_dir) / "identity.wav"
        audio_fixture.write_bytes(b"RIFF" + b"\0" * 64)
        clip_fixture = Path(identity_dir) / "identity.mov"
        clip_fixture.write_bytes(b"\0" * 512)

        def beat_key() -> str:
            return beat_analysis._beat_cache_key(str(audio_fixture))[3]

        def clip_key() -> str:
            return clip_analysis._source_identity(str(clip_fixture))[2]

        base_beat_key = beat_key()
        base_clip_key = clip_key()
        drifted = set()
        for module, attribute, value, produce in (
            (beat_analysis, "BEAT_ANALYSIS_SCHEMA_VERSION", "drift", beat_key),
            (beat_analysis, "BASS_MIN_SPACING_SECONDS", 0.5, beat_key),
            (beat_analysis, "ENERGY_HOP_LENGTH", 1024, beat_key),
        ):
            original = getattr(module, attribute)
            try:
                setattr(module, attribute, value)
                drifted.add(produce())
            finally:
                setattr(module, attribute, original)
        assert base_beat_key not in drifted and len(drifted) == 3
        assert beat_key() == base_beat_key
        relative_audio = os.path.relpath(audio_fixture, Path.cwd())
        assert beat_analysis._beat_cache_key(relative_audio)[3] == base_beat_key

        drifted = set()
        for attribute, value in (
            ("ANALYSIS_SCHEMA_VERSION", "drift"),
            ("ANALYSIS_SAMPLES", clip_analysis.ANALYSIS_SAMPLES + 1),
            ("ANALYSIS_MAX_DIMENSION", clip_analysis.ANALYSIS_MAX_DIMENSION + 1),
            ("ANALYSIS_SAMPLE_WINDOW", (0.0, 1.0)),
        ):
            original = getattr(clip_analysis, attribute)
            try:
                setattr(clip_analysis, attribute, value)
                drifted.add(clip_key())
            finally:
                setattr(clip_analysis, attribute, original)
        assert base_clip_key not in drifted and len(drifted) == 4
        assert clip_key() == base_clip_key

        model_root = Path(identity_dir) / "face-model"
        prototxt = model_root.with_suffix(".prototxt")
        caffemodel = model_root.with_suffix(".caffemodel")
        prototxt.write_bytes(b"proto-v1")
        caffemodel.write_bytes(b"weights-v1")
        original_model = os.environ.get("FLAGSHIPEDITOR_FACE_MODEL")
        try:
            os.environ["FLAGSHIPEDITOR_FACE_MODEL"] = str(model_root)
            model_key_v1 = clip_key()
            model_stat = caffemodel.stat()
            caffemodel.write_bytes(b"weights-v2")
            os.utime(
                caffemodel,
                ns=(model_stat.st_atime_ns, model_stat.st_mtime_ns),
            )
            model_key_v2 = clip_key()
            assert model_key_v2 != model_key_v1
        finally:
            if original_model is None:
                os.environ.pop("FLAGSHIPEDITOR_FACE_MODEL", None)
            else:
                os.environ["FLAGSHIPEDITOR_FACE_MODEL"] = original_model

    # --- C06: a face verdict says which detector produced it -----------------
    face = detect_faces([np.zeros((64, 64, 3), dtype=np.uint8)])
    assert face["face_detector"] in {"dnn_caffe", "haar_cascade", "unavailable"}
    assert bool(face["has_face"]) == (face["face_size_ratio"] > 0.0)
    assert 0.0 <= face["face_consistency"] <= 1.0
    assert 0.0 <= face["face_detector_confidence"] <= 1.0
    assert face["face_detector_confidence_kind"] in {"detector_score", "unavailable"}
    if face["face_detector"] == "haar_cascade":
        assert face["face_detector_confidence"] == 0.0

    original_cascade = clip_analysis.cv2.CascadeClassifier
    load_count = 0

    class StubCascade:
        def empty(self):
            return False

        def detectMultiScale(self, *_args, **_kwargs):
            return []

    def counted_cascade(*_args, **_kwargs):
        nonlocal load_count
        load_count += 1
        return StubCascade()

    try:
        clip_analysis._FACE_DETECTOR_LOCAL.cache = {}
        clip_analysis.cv2.CascadeClassifier = counted_cascade
        detect_faces([np.zeros((64, 64, 3), dtype=np.uint8)])
        detect_faces([np.zeros((64, 64, 3), dtype=np.uint8)])
    finally:
        clip_analysis.cv2.CascadeClassifier = original_cascade
        clip_analysis._FACE_DETECTOR_LOCAL.cache = {}
    assert load_count == 1
    assert face["face_frames_examined"] == 1
    assert "face_detector_fallback" in face
    assert detect_faces([])["face_detector"]
    # The Caffe SSD volume is (1, 1, N, 7); reading it as (N, 7) is what used to
    # send every configured DNN run into the Haar fallback.
    volume = np.zeros((1, 1, 2, 7), dtype=np.float32)
    volume[0, 0, 0] = [0.0, 1.0, 0.9, 0.25, 0.25, 0.75, 0.75]
    volume[0, 0, 1] = [0.0, 1.0, 0.2, 0.0, 0.0, 1.0, 1.0]
    boxes = _dnn_face_boxes(volume, 100, 100)
    assert len(boxes) == 1 and abs(boxes[0][0] - 0.25) < 1e-6 and abs(boxes[0][1] - 0.9) < 1e-6
    # A base path is the documented configuration and must resolve as one.
    with tempfile.TemporaryDirectory(prefix="flagship-face-model-") as model_dir:
        base = Path(model_dir) / "res10"
        assert _resolve_face_model(str(base)) == ("", "", "res10")
        base.with_suffix(".prototxt").write_text("stub", encoding="utf-8")
        base.with_suffix(".caffemodel").write_bytes(b"stub")
        prototxt, caffemodel, identity = _resolve_face_model(str(base))
        assert prototxt.endswith(".prototxt") and caffemodel.endswith(".caffemodel")
        assert identity == "res10"
        assert _resolve_face_model(str(base) + ".prototxt")[1] == caffemodel
    assert _resolve_face_model("") == ("", "", "")

    # --- C10: motion evidence is normalized by elapsed source time -----------
    texture = np.zeros((96, 96, 3), dtype=np.uint8)
    texture[:, ::8] = 255
    texture[::8, :] = 200
    pair = [texture, np.roll(texture, 4, axis=1)]
    timed = flow_descriptors(pair, timestamps=[0.0, 2.0])
    assert timed and timed[0]["elapsed"] == 2.0
    assert abs(timed[0]["magnitude_per_second"] * 2.0 - timed[0]["magnitude"]) < 1e-9
    # Without timestamps the rate is absent rather than invented.
    assert "magnitude_per_second" not in flow_descriptors(pair)[0]
    # Two samples at the same instant describe no rate at all.
    assert flow_descriptors(pair, timestamps=[1.0, 1.0])[0]["magnitude_per_second"] is None
    # Both decoders must walk the same window: OpenCV used to sample 0-100%
    # while FFmpeg sampled 5-95%, so the same footage produced different sample
    # spacing — and therefore different motion — depending on which one opened
    # it. OpenCV cannot decode in this headless build, so the capture is stubbed
    # to observe the positions the engine actually asks for.
    class _StubCapture:
        def __init__(self, total: int, fps: float) -> None:
            self.total = total
            self.fps = fps
            self.requested: list = []

        def isOpened(self) -> bool:  # noqa: N802 - OpenCV's spelling
            return True

        def get(self, prop):
            if prop == clip_analysis.cv2.CAP_PROP_FRAME_COUNT:
                return float(self.total)
            if prop == clip_analysis.cv2.CAP_PROP_FPS:
                return self.fps
            return 0.0

        def set(self, prop, value):
            if prop == clip_analysis.cv2.CAP_PROP_POS_FRAMES:
                self.requested.append(int(value))
            return True

        def read(self):
            return True, np.zeros((16, 16, 3), dtype=np.uint8)

        def release(self) -> None:
            return None

    stub = _StubCapture(101, 25.0)
    original_capture = clip_analysis.cv2.VideoCapture
    try:
        clip_analysis.cv2.VideoCapture = lambda *_args, **_kwargs: stub
        _stub_frames, stub_times = clip_analysis._extract_frames_opencv_timed("stub.mov", 5)
    finally:
        clip_analysis.cv2.VideoCapture = original_capture
    last_index = stub.total - 1
    assert len(stub.requested) == 5
    assert stub.requested[0] == int(round(last_index * ANALYSIS_SAMPLE_WINDOW[0]))
    assert stub.requested[-1] == int(round(last_index * ANALYSIS_SAMPLE_WINDOW[1]))
    assert stub_times == [position / stub.fps for position in stub.requested]

    policy = motion_sample_policy("opencv", [0.0, 2.0], timed, 10.0)
    assert policy["elapsed_normalized"] is True
    assert policy["consecutive_frames"] is False
    assert tuple(policy["window"]) == tuple(ANALYSIS_SAMPLE_WINDOW)
    assert policy["coverage_fraction"] == 0.2 and policy["mean_spacing_seconds"] == 2.0
    assert motion_sample_policy("ffmpeg", [], [], 0.0)["elapsed_normalized"] is False

    # Cross-clip ranking must consume rates, not the spacing-dependent raw
    # displacement. Reversing only raw motion cannot reverse the normalized
    # profiles; reversing the rates must.
    motion_library = [
        {
            "path": "/fixtures/slow-rate.mov",
            "motion_intensity": 90.0,
            "motion_variance": 30.0,
            "motion_intensity_per_second": 5.0,
            "motion_variance_per_second": 1.0,
            "motion_sample_policy": {"elapsed_normalized": True},
        },
        {
            "path": "/fixtures/fast-rate.mov",
            "motion_intensity": 5.0,
            "motion_variance": 1.0,
            "motion_intensity_per_second": 50.0,
            "motion_variance_per_second": 10.0,
            "motion_sample_policy": {"elapsed_normalized": True},
        },
    ]
    normalized_motion = normalize_motion_evidence(motion_library)
    assert normalized_motion[1]["_selector_motion_intensity"] > normalized_motion[0]["_selector_motion_intensity"]
    assert score_clip(normalized_motion[1], section_type="drop")["scores"]["energy"] > score_clip(
        normalized_motion[0], section_type="drop"
    )["scores"]["energy"]
    untrusted_motion = normalize_motion_evidence(
        [
            {
                "path": "/fixtures/untrusted-rate.mov",
                "motion_intensity": 42.0,
                "motion_intensity_per_second": 999.0,
                "motion_sample_policy": {"elapsed_normalized": False},
            }
        ]
    )[0]
    assert "_selector_motion_intensity" not in untrusted_motion
    assert score_clip(untrusted_motion, section_type="drop")["scores"]["energy"] == 25.2

    # Manual swap scoring can use the same library-relative normalization as
    # automatic selection while remaining backward compatible with old callers.
    score_response = score_clip_endpoint(
        ScoreRequest(
            clip=motion_library[1],
            library=motion_library,
            sectionType="drop",
        )
    )
    assert score_response["motionNormalizationContext"] == "library"
    legacy_score_response = score_clip_endpoint(
        ScoreRequest(clip=motion_library[1], sectionType="drop")
    )
    assert legacy_score_response["motionNormalizationContext"] == "legacy_single_clip"

    # --- UNUSED_SIGNAL: phrase boundaries and the energy curve reach the cut --
    signal_beats = [index * 0.5 for index in range(48)]
    signal_sections = [
        {"type": "verse", "start": 0.0, "end": 12.0},
        {"type": "chorus", "start": 12.0, "end": 24.0},
    ]
    without_phrases = plan_cuts(signal_beats, signal_sections, {}, 24.0, 120.0, [])
    with_phrases = plan_cuts(
        signal_beats, signal_sections, {}, 24.0, 120.0, [], [4.0, 8.0, 16.0]
    )
    origins_without = {slot["cutProvenance"]["origin"] for slot in without_phrases}
    origins_with = {slot["cutProvenance"]["origin"] for slot in with_phrases}
    assert "phrase" not in origins_without and "phrase" in origins_with
    # Phrase records straight from beat analysis carry a time, not a float.
    assert plan_cuts(
        signal_beats, signal_sections, {}, 24.0, 120.0, [], [{"time": 8.0}]
    ) == plan_cuts(signal_beats, signal_sections, {}, 24.0, 120.0, [], [8.0])
    measured_phrase_beats = [index * 0.5 for index in range(48)]
    measured_phrases = detect_phrase_boundaries(
        measured_phrase_beats,
        120.0,
        [{"type": "verse", "start": 0.0, "end": 24.0}],
        [0.5 + index * 2.0 for index in range(12)],
    )
    assert measured_phrases and measured_phrases[0]["time"] == 8.5

    def energy_clip(index: int, energy_score: float) -> dict:
        histogram = [0.0] * 32
        histogram[index] = 1.0
        return {
            "path": f"/fixtures/energy-{index}.mov",
            "name": f"energy-{index}.mov",
            "duration": 12.0,
            "scene_type": "performance",
            "usable": True,
            "energy_score": energy_score,
            "motion_intensity": 10.0,
            "motion_variance": 1.0,
            "composition_score": 60.0,
            "sharpness_score": 60.0,
            "brightness_stability": 80.0,
            "histogram": histogram,
        }

    energy_clips = [energy_clip(0, 5.0), energy_clip(1, 95.0)]
    curve_times = [index * 24.0 / 480.0 for index in range(480)]
    loud_first = [1.0] * 240 + [0.05] * 240
    quiet_first = [0.05] * 240 + [1.0] * 240
    selector_energy_args = (energy_clips, signal_beats, signal_sections, {}, 24.0, 120.0, [])
    loud = select_best_clips(
        *selector_energy_args, energy=loud_first, energy_times=curve_times
    )
    quiet = select_best_clips(
        *selector_energy_args, energy=quiet_first, energy_times=curve_times
    )
    plain = select_best_clips(*selector_energy_args)
    assert [entry["clipPath"] for entry in loud] != [entry["clipPath"] for entry in quiet]
    assert loud[0]["cutProvenance"]["energySource"] == "measured_curve"
    assert plain[0]["cutProvenance"]["energySource"] == "section_default"
    # A cache-era beat result has no time base; the hop/rate it was measured at,
    # then the track duration, stand in rather than dropping the signal.
    assert track_energy_curve(loud_first, None, 24.0) is not None
    assert track_energy_curve(loud_first, None, 0.0, 512, 22050) is not None
    assert track_energy_curve(loud_first, [], 0.0) is None
    assert track_energy_curve([], None, 24.0) is None
    assert track_energy_curve([0.0, 0.0], None, 24.0) is None
    assert track_energy_curve([float("nan"), 1.0], None, 24.0) is None
    # A malformed curve must not disturb a caller that supplies one.
    assert select_best_clips(*selector_energy_args, energy=[float("nan")]) == plain
    # The section still dominates the blend it is mixed into.
    steady = track_energy_curve([1.0] * 480, curve_times)
    assert cut_energy_target(None, "drop", 0.0, 1.0, {}) == 0.9
    assert 0.9 < cut_energy_target(steady, "drop", 0.0, 1.0, {}) <= 1.0
    assert 0.2 < cut_energy_target(steady, "intro", 0.0, 1.0, {}) < 0.6

    # --- S12: every cut records the evidence behind its own boundary ---------
    provenance_sections = [
        {"type": "intro", "start": 0.0, "end": 4.0},
        {"type": "verse", "start": 4.0, "end": 12.0},
        {"type": "drop", "start": 12.0, "end": 20.0},
        {"type": "outro", "start": 20.0, "end": 24.0},
    ]
    provenance_onsets = [12.25, 13.0, 14.25, 16.0, 18.25]
    provenance_slots = plan_cuts(
        signal_beats, provenance_sections, {}, 24.0, 120.0, provenance_onsets, [8.0]
    )
    section_starts = {round(float(item["start"]), 6) for item in provenance_sections}
    assert provenance_slots
    assert all(
        slot["cutProvenance"]["origin"] in CUT_ORIGINS for slot in provenance_slots
    )
    assert all(
        slot["cutProvenance"]["origin"] == "boundary"
        for slot in provenance_slots
        if round(float(slot["beatTime"]), 6) in section_starts
    )
    onset_slots = [
        slot for slot in provenance_slots if slot["cutProvenance"]["origin"] == "onset"
    ]
    # An "808-synced" cut has to name the attack it came from, and how far
    # quantisation moved it from where it was played.
    assert onset_slots
    assert all(
        slot["cutProvenance"]["sourceTime"] in provenance_onsets
        and abs(slot["cutProvenance"]["snapDelta"]) <= slot["cutProvenance"]["snapTolerance"]
        for slot in onset_slots
    )
    assert all(
        not slot["cutProvenance"]["beatAligned"]
        or slot["cutProvenance"]["beatDelta"] <= slot["cutProvenance"]["snapTolerance"]
        for slot in provenance_slots
    )
    assert all(
        slot["cutProvenance"]["sourceTime"] is not None
        and abs(
            slot["beatTime"]
            - slot["cutProvenance"]["sourceTime"]
            - slot["cutProvenance"]["snapDelta"]
        ) < 1e-6
        for slot in provenance_slots
    )
    assert all(entry["cutProvenance"]["origin"] in CUT_ORIGINS for entry in loud)

    print(
        "Engine contract tests passed "
        "(metadata, HPSS, energy matching, shot taxonomy, camera movement, "
        "hook reservation, determinism, source windows, clip identity, "
        "energy time base, label provenance, cache identity, face provenance, "
        "motion normalization, consumed beat signals, cut provenance)."
    )


if __name__ == "__main__":
    main()
