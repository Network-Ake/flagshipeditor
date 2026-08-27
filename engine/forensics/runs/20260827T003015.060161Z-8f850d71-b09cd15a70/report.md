# FlagshipEditor — Cyber-Forensic Engine Report

- Verdict: **WARN**
- Exit code: `2`
- Generated: `2026-08-27T00:30:26+00:00`
- Protocol: `1.0.0`
- Commit: `8f850d71d1b4826a3fd118b509a202ea7a0588d9`
- Network boundary: 0 undeclared network-capable import(s) measured; see `network_boundary` and Limitations

## Gate summary

- Static/cross-engine checks: {'pass': 36, 'warn': 7, 'fail': 0}
- Existing dynamic tests: {'pass': 3, 'fail': 0, 'not_run': 0}
- Baseline: `match`
- Inventory: 36 files hashed with SHA-256

## Findings

- **PASS** `required-symbols` — engine/beat_analysis.py exposes every required contract symbol
  - `engine/beat_analysis.py:581 analyze_track`
  - `engine/beat_analysis.py:1222 detect_phrase_boundaries`
  - `engine/beat_analysis.py:199 frequency_filter`
- **PASS** `network-surface` — No network-capable imports found in engine/beat_analysis.py
- **PASS** `dynamic-code-execution` — No eval/exec/compile calls in engine/beat_analysis.py
- **PASS** `shell-injection-surface` — No shell=True subprocess in engine/beat_analysis.py
- **PASS** `selector-determinism-surface` — No forbidden random selection calls in engine/beat_analysis.py
- **PASS** `required-symbols` — engine/clip_analysis.py exposes every required contract symbol
  - `engine/clip_analysis.py:24 ANALYSIS_SCHEMA_VERSION`
  - `engine/clip_analysis.py:1450 classify_clip`
  - `engine/clip_analysis.py:1411 compute_visual_scores`
  - `engine/clip_analysis.py:1129 find_best_moment`
- **PASS** `network-surface` — No network-capable imports found in engine/clip_analysis.py
- **PASS** `dynamic-code-execution` — No eval/exec/compile calls in engine/clip_analysis.py
- **PASS** `shell-injection-surface` — No shell=True subprocess in engine/clip_analysis.py
- **PASS** `selector-determinism-surface` — No forbidden random selection calls in engine/clip_analysis.py
- **PASS** `required-symbols` — engine/shot_selector.py exposes every required contract symbol
  - `engine/shot_selector.py:28 SECTION_WEIGHTS`
  - `engine/shot_selector.py:90 SECTION_SCENE_AFFINITY`
  - `engine/shot_selector.py:175 MIN_CUT_SECONDS`
  - `engine/shot_selector.py:1145 plan_cuts`
  - `engine/shot_selector.py:554 score_clip`
  - `engine/shot_selector.py:1540 select_best_clips`
- **PASS** `network-surface` — No network-capable imports found in engine/shot_selector.py
- **PASS** `dynamic-code-execution` — No eval/exec/compile calls in engine/shot_selector.py
- **PASS** `shell-injection-surface` — No shell=True subprocess in engine/shot_selector.py
- **PASS** `selector-determinism-surface` — No forbidden random selection calls in engine/shot_selector.py
- **PASS** `required-symbols` — engine/server.py exposes every required contract symbol
  - `engine/server.py:83 app`
  - `engine/server.py:446 main`
- **PASS** `network-surface` — Network imports in engine/server.py match its declared server surface
  - `engine/server.py:18 import uvicorn`
  - `engine/server.py:19 import fastapi`
  - `engine/server.py:20 import fastapi.middleware.cors`
  - `engine/server.py:21 import fastapi.staticfiles`
- **PASS** `dynamic-code-execution` — No eval/exec/compile calls in engine/server.py
- **PASS** `shell-injection-surface` — No shell=True subprocess in engine/server.py
- **PASS** `selector-determinism-surface` — No forbidden random selection calls in engine/server.py
- **PASS** `S13` — Selector best-moment source window reaches and is applied by After Effects
  - `engine/shot_selector.py:1762 selector emits sourceStart`
  - `src/js/main/lib/python.ts:215 CutDecision source fields=True`
  - `src/js/main/App.tsx:105 payload source fields=True`
  - `src/js/main/App.tsx:174 serialization drops source fields=False`
  - `src/jsx/aeft/aeft.ts:80 renderer contract source fields=True`
  - `src/jsx/aeft/aeft.ts:275 renderer source offset applied=True`
- **WARN** `ROADMAP-REAL-MEDIA` — Real-media decoder and semantic accuracy are not exercised by preflight
  - `v1 preflight scope boundary`
- **WARN** `ROADMAP-CACHE-REPLAY` — Cached-vs-uncached semantic equality is not exercised by preflight
  - `v1 preflight scope boundary`
- **WARN** `ROADMAP-NATIVE-AE` — Native Windows/After Effects composition inspection is not exercised
  - `v1 preflight scope boundary`
- **WARN** `ROADMAP-ARTISTIC` — Artistic quality has no labelled fixtures or blind human validation
  - `v1 preflight scope boundary`
- **WARN** `ROADMAP-NETWORK-SANDBOX` — The protocol performs no network calls, but child tests are not kernel-level network-sandboxed
  - `v1 preflight scope boundary`
- **WARN** `ROADMAP-PROCESS-CONTAINMENT` — Child output is buffered and timeout handling does not guarantee termination of descendant processes
  - `v1 preflight scope boundary`
- **WARN** `ROADMAP-TS-PARSER` — The S13 contract uses multi-boundary source inspection, not a TypeScript AST parser or native AE execution
  - `v1 preflight scope boundary`
- **PASS** `B06` — Energy samples carry an emitted, exact time base
  - `energy_envelope reproduces n*hop/sr within 1ms=True`
  - `non_finite_samples_reported=1`
  - `analyze_track_missing_keys=[]`
- **PASS** `B09` — Musical labels carry a measured method and a bounded confidence
  - `accented_phase_recovered=2 confidence=1.0`
  - `no_accent_evidence_method=assumed_first_beat`
  - `section_label_sources=['measured', 'measured_energy', 'positional']`
  - `drop_label_method=measured_energy`
  - `selector_first_measured_downbeat_cut=0.5`
  - `analyze_track_missing_keys=[]`
- **PASS** `CACHE-BEAT-PROVENANCE` — Beat cache identity binds schema, code hash, configuration and dependencies
  - `identity_fields=['code', 'config', 'dependencies', 'schema']`
  - `distinct_keys_under_drift=4/4`
  - `restored_key_stable=True`
- **PASS** `C02` — Clip cache identity binds schema, code, sampling config and tool identity
  - `identity_fields=['code', 'config', 'dependencies', 'schema', 'tools']`
  - `tool_identities=['ffmpeg', 'ffprobe']`
  - `distinct_keys_under_drift=5/5`
  - `same_path_face_model_replacement_moves_key=True`
- **PASS** `C06` — Face results record the detector, its confidence and any fallback
  - `detector=haar_cascade fallback='dnn_not_configured'`
  - `has_face_implies_ratio=True`
  - `dnn_volume_boxes_above_threshold=1`
  - `haar_loads_for_two_clips_same_thread=1`
  - `haar_confidence_kind=unavailable`
  - `classify_clip_missing_keys=[]`
- **PASS** `C10` — Motion evidence is normalized by elapsed source time and declares its sampling policy
  - `magnitude_per_second_times_elapsed_equals_magnitude=True`
  - `both_decoders_share_sample_window=True`
  - `policy_declares_normalization=True`
  - `selector_prefers_higher_rate_over_higher_raw_displacement=True`
  - `selector_rejects_unverified_rate_fields=True`
  - `classify_clip_missing_keys=[]`
- **PASS** `UNUSED_SIGNAL` — Every audited upstream signal changes selector output when supplied
  - `phrase_boundaries_create_cuts=True`
  - `downbeats_shift_bar_grid=True`
  - `energy_curve_changes_selection=True`
  - `normalized_motion_changes_ranking=True`
  - `energy_source_declared_per_cut=True`
- **PASS** `S12` — Every cut records the boundary/onset/phrase/grid evidence behind it
  - `slots_with_declared_origin=True`
  - `section_boundaries_traced=True`
  - `onset_cuts_match_input_onsets=True count=5`
  - `beat_aligned_claims_within_tolerance=True`
  - `all_origins_reconstruct_from_source_time_and_snap=True`
  - `selection_carries_provenance=True`
- **PASS** `section-contract` — Beat/clip/selector section vocabulary is aligned
  - `required=['bridge', 'chorus', 'drop', 'intro', 'outro', 'verse']`
  - `missing_weights=[]`
  - `missing_affinities=[]`
  - `weight_sums={'bridge': 1.0, 'chorus': 1.0, 'drop': 1.0, 'intro': 1.0, 'outro': 1.0, 'verse': 1.0}`
- **PASS** `clip-selector-feature-contract` — Clip features satisfy selector input contracts
  - `keys=['composition_score', 'energy_score', 'histogram', 'sharpness_score']`
  - `histogram_bins=32`
- **PASS** `timeline-invariants` — Cut planner is deterministic and tiles the full timeline
  - `slot_count=27`
  - `boundary_count=4`
  - `minimum_slot_seconds=0.25`
  - `contiguous=True`
  - `deterministic=True`
- **PASS** `selection-invariants` — Selector output is deterministic, bounded, and non-repeating
  - `selection_count=27`
  - `slot_count=27`
  - `repeat_violations=0`
  - `three_run_deterministic=True`
  - `source_window_failures=[]`
  - `score_failures=[]`
  - `alternative_failures=[]`
- **PASS** `S04-DUPLICATE-IDENTITY` — Duplicate clip identities are explicitly rejected
  - `input_count=9`
  - `unique_paths=8`
  - `output_count=0`
- **PASS** `beat-selector-time-contract` — Beat-derived phrase times are ordered and bounded
  - `phrase_boundary_count=6`
  - `first_phrase_anchored_to_measured_downbeat=8.5`
- **PASS** `TEST-MUTATION` — Child tests left all tracked engine/test/render files bit-identical
  - `tracked_files=1702`
  - `changed=[]`
  - `git_status_changed=False`

## Existing dynamic tests

- **PASS** `engine-contracts` — exit=0, stdout_sha256=`5ea384633b3294c3a7cd2a26e1784990b4a2a83141d50db92449510a3eb09aa1`, stderr_sha256=`e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`
- **PASS** `analysis-jobs` — exit=0, stdout_sha256=`7793d8f19cafe81e6338fbd56af15fbb1f7bb1eaf16aac575148eafd94b0a658`, stderr_sha256=`e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`
- **PASS** `server-health` — exit=0, stdout_sha256=`a953ffec512a75af25c13980726d00bac039253ca10bec732df0121a40bb6535`, stderr_sha256=`e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`

## Baseline drift

- Status: **match**

## Engine SHA-256

- `engine/beat_analysis.py` — `132327ce5afd5191a5903f171e247c5f0929715a52e4fa1ae83ea48ec634e482` (50003 bytes)
- `engine/clip_analysis.py` — `881eebbd55da33cf8e091c121dc5d3203880b6014cc0bea37ee60421f03c4dff` (66298 bytes)
- `engine/shot_selector.py` — `1ab60c71289bb85c1be5c3bcdac56c906642c388d21f547acc2c3afc92667a5b` (73471 bytes)
- `engine/server.py` — `8bfc4124cb65ab84ab814f7cb30c399fd8afc9d30f095333f39ddb1d4dced050` (17170 bytes)

## Limitations

- No real media fixture is decoded by the forensic cross-engine invariant gate.
- No native Windows or After Effects host is exercised.
- No subjective edit-quality claim is inferred from passing tests.
- Analysis-note claims marked as requiring validation remain unproven.
- network_boundary.measured_imports is a static AST measurement; that the protocol itself performs no network calls, and that child tests are not kernel-level network-sandboxed, are declared scope boundaries, not measured runtime properties.

## Interpretation boundary

A PASS proves only the checked source integrity, static gates, synthetic cross-engine contracts, and local tests listed above. It does not prove subjective edit quality, native After Effects behavior, real-media accuracy, or claims from the analysis notes that lack fixtures or human validation.
