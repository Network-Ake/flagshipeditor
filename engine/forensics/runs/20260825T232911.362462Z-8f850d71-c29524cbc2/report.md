# FlagshipEditor — Cyber-Forensic Engine Report

- Verdict: **WARN**
- Exit code: `2`
- Generated: `2026-08-25T23:29:21+00:00`
- Protocol: `1.0.0`
- Commit: `8f850d71d1b4826a3fd118b509a202ea7a0588d9`
- Network boundary: the protocol implements no network calls; child tests are **not** OS-level network-sandboxed

## Gate summary

- Static/cross-engine checks: {'pass': 31, 'warn': 7, 'fail': 0}
- Existing dynamic tests: {'pass': 3, 'fail': 0, 'not_run': 0}
- Baseline: `drift`
- Inventory: 34 files hashed with SHA-256

## Findings

- **PASS** `required-symbols` — engine/beat_analysis.py exposes every required contract symbol
  - `engine/beat_analysis.py:565 analyze_track`
  - `engine/beat_analysis.py:1205 detect_phrase_boundaries`
  - `engine/beat_analysis.py:198 frequency_filter`
- **PASS** `network-surface` — No network-capable imports found in engine/beat_analysis.py
- **PASS** `dynamic-code-execution` — No eval/exec/compile calls in engine/beat_analysis.py
- **PASS** `shell-injection-surface` — No shell=True subprocess in engine/beat_analysis.py
- **PASS** `selector-determinism-surface` — No forbidden random selection calls in engine/beat_analysis.py
- **PASS** `required-symbols` — engine/clip_analysis.py exposes every required contract symbol
  - `engine/clip_analysis.py:24 ANALYSIS_SCHEMA_VERSION`
  - `engine/clip_analysis.py:1372 classify_clip`
  - `engine/clip_analysis.py:1333 compute_visual_scores`
  - `engine/clip_analysis.py:1088 find_best_moment`
- **PASS** `network-surface` — No network-capable imports found in engine/clip_analysis.py
- **PASS** `dynamic-code-execution` — No eval/exec/compile calls in engine/clip_analysis.py
- **PASS** `shell-injection-surface` — No shell=True subprocess in engine/clip_analysis.py
- **PASS** `selector-determinism-surface` — No forbidden random selection calls in engine/clip_analysis.py
- **PASS** `required-symbols` — engine/shot_selector.py exposes every required contract symbol
  - `engine/shot_selector.py:28 SECTION_WEIGHTS`
  - `engine/shot_selector.py:90 SECTION_SCENE_AFFINITY`
  - `engine/shot_selector.py:175 MIN_CUT_SECONDS`
  - `engine/shot_selector.py:1062 plan_cuts`
  - `engine/shot_selector.py:496 score_clip`
  - `engine/shot_selector.py:1449 select_best_clips`
- **PASS** `network-surface` — No network-capable imports found in engine/shot_selector.py
- **PASS** `dynamic-code-execution` — No eval/exec/compile calls in engine/shot_selector.py
- **PASS** `shell-injection-surface` — No shell=True subprocess in engine/shot_selector.py
- **PASS** `selector-determinism-surface` — No forbidden random selection calls in engine/shot_selector.py
- **PASS** `S13` — Selector best-moment source window reaches and is applied by After Effects
  - `engine/shot_selector.py:1663 selector emits sourceStart`
  - `src/js/main/lib/python.ts:203 CutDecision source fields=True`
  - `src/js/main/App.tsx:105 payload source fields=True`
  - `src/js/main/App.tsx:174 serialization drops source fields=False`
  - `src/jsx/aeft/aeft.ts:80 renderer contract source fields=True`
  - `src/jsx/aeft/aeft.ts:277 renderer source offset applied=True`
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
  - `analyze_track_missing_keys=[]`
- **PASS** `CACHE-BEAT-PROVENANCE` — Beat cache identity binds schema, code hash, configuration and dependencies
  - `identity_fields=['code', 'config', 'dependencies', 'schema']`
  - `distinct_keys_under_drift=4/4`
  - `restored_key_stable=True`
- **PASS** `C02` — Clip cache identity binds schema, code, sampling config and tool identity
  - `identity_fields=['code', 'config', 'dependencies', 'schema', 'tools']`
  - `tool_identities=['ffmpeg', 'ffprobe']`
  - `distinct_keys_under_drift=5/5`
- **PASS** `C06` — Face results record the detector, its confidence and any fallback
  - `detector=haar_cascade fallback='dnn_not_configured'`
  - `has_face_implies_ratio=True`
  - `dnn_volume_boxes_above_threshold=1`
  - `classify_clip_missing_keys=[]`
- **PASS** `C10` — Motion evidence is normalized by elapsed source time and declares its sampling policy
  - `magnitude_per_second_times_elapsed_equals_magnitude=True`
  - `both_decoders_share_sample_window=True`
  - `policy_declares_normalization=True`
  - `classify_clip_missing_keys=[]`
- **PASS** `UNUSED_SIGNAL` — Every audited upstream signal changes selector output when supplied
  - `phrase_boundaries_create_cuts=True`
  - `energy_curve_changes_selection=True`
  - `energy_source_declared_per_cut=True`
- **PASS** `S12` — Every cut records the boundary/onset/phrase/grid evidence behind it
  - `slots_with_declared_origin=True`
  - `section_boundaries_traced=True`
  - `onset_cuts_match_input_onsets=True count=5`
  - `beat_aligned_claims_within_tolerance=True`
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
- **PASS** `TEST-MUTATION` — Child tests left all tracked engine/test/render files bit-identical
  - `tracked_files=1702`
  - `changed=[]`
  - `git_status_changed=False`

## Existing dynamic tests

- **PASS** `engine-contracts` — exit=0, stdout_sha256=`5ea384633b3294c3a7cd2a26e1784990b4a2a83141d50db92449510a3eb09aa1`, stderr_sha256=`e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`
- **PASS** `analysis-jobs` — exit=0, stdout_sha256=`7793d8f19cafe81e6338fbd56af15fbb1f7bb1eaf16aac575148eafd94b0a658`, stderr_sha256=`e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`
- **PASS** `server-health` — exit=0, stdout_sha256=`a953ffec512a75af25c13980726d00bac039253ca10bec732df0121a40bb6535`, stderr_sha256=`e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`

## Baseline drift

- Status: **drift**
- Changed: `engine/beat_analysis.py` — expected `cd7d805b9fd819bd2afee3f1cd7fec6519b58b7dabc3f72deaea52252f554608`, actual `3c4b910be99b9b6a284b48951e5cc8a760711f2e1e8de78e8428db53d7a104d3`
- Changed: `engine/clip_analysis.py` — expected `e2c80f512a6fff8ba504f3e1f664b281f36c63b8f107557130c1c336055e4551`, actual `21a6f5c0def248e619dc69a3f849f4c27ac901be2f48a3a0c9df8a097eade1ad`
- Changed: `engine/shot_selector.py` — expected `59d8100caeeb3cf6c464d7b8bbcc34de897fe59434a29d13632269a9188fd9f3`, actual `dc52501ac3f803ab6ff03168c6a00f68e8369cc2ee551cef63b0e3e89a36be19`
- Changed: `scripts/cyber_forensic_protocol.py` — expected `44084a4e923ea425011134f1d016357fd0f129ddeebeec437933263d0ed58ab0`, actual `b878a684df8f9747e7e241ae811f0302df5ff8c02274a0b360ae90ba1593c8fc`
- Changed: `scripts/test-engine-contracts.py` — expected `521a572a6dc457389e281234a246f7d920905bcc16b5e985ccae30a3fb28d356`, actual `583d5c86430f68d0d513b6195262e0a117b64b087548d841847f947e7b9f8662`
- Changed: `src/js/main/App.tsx` — expected `2f01ac49a93b59d455c112f2008540efaeebb5e9d910043e70868111906c4219`, actual `9fe546fc0f995067684cf81214cc2032c281cc4f5e16a14815fd7ac15a4b8244`
- Changed: `src/js/main/lib/python.ts` — expected `3e14d062ecbca3b392521a107bf11b277a6173e1018482e781ad5beab284e8c7`, actual `ebaf79cf740e1b502025e298f9c850a60c133f9b66591d3040586a02dc1e787f`
- Changed: `src/jsx/aeft/aeft.ts` — expected `8be40170274f6af55d002dd8862bad6c0f007b76e43fbadbe7c42d1065c38756`, actual `2aa491c72a5887487a1664e0bec872c441b0c1b1597763faf2fd7062c85d976b`
- Contract fingerprint changed: `f06eb01a8b71e63238318532307a8588670da201692dcfbd4bf833e8bff8c616` → `8fc538dd5933db6421191669a07baad58cd190bb8d1609320fbf29251c43ccf4`

## Engine SHA-256

- `engine/beat_analysis.py` — `3c4b910be99b9b6a284b48951e5cc8a760711f2e1e8de78e8428db53d7a104d3` (48697 bytes)
- `engine/clip_analysis.py` — `21a6f5c0def248e619dc69a3f849f4c27ac901be2f48a3a0c9df8a097eade1ad` (63401 bytes)
- `engine/shot_selector.py` — `dc52501ac3f803ab6ff03168c6a00f68e8369cc2ee551cef63b0e3e89a36be19` (69248 bytes)

## Interpretation boundary

A PASS proves only the checked source integrity, static gates, synthetic cross-engine contracts, and local tests listed above. It does not prove subjective edit quality, native After Effects behavior, real-media accuracy, or claims from the analysis notes that lack fixtures or human validation.
