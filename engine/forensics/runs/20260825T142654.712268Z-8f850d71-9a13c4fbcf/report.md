# FlagshipEditor — Cyber-Forensic Engine Report

- Verdict: **FAIL**
- Exit code: `1`
- Generated: `2026-08-25T14:29:00+00:00`
- Protocol: `1.0.0`
- Commit: `8f850d71d1b4826a3fd118b509a202ea7a0588d9`
- Network boundary: the protocol implements no network calls; child tests are **not** OS-level network-sandboxed

## Gate summary

- Static/cross-engine checks: {'pass': 23, 'warn': 15, 'fail': 0}
- Existing dynamic tests: {'pass': 2, 'fail': 1, 'not_run': 0}
- Baseline: `drift`
- Inventory: 34 files hashed with SHA-256

## Findings

- **PASS** `required-symbols` — engine/beat_analysis.py exposes every required contract symbol
  - `engine/beat_analysis.py:287 analyze_track`
  - `engine/beat_analysis.py:820 detect_phrase_boundaries`
  - `engine/beat_analysis.py:100 frequency_filter`
- **PASS** `network-surface` — No network-capable imports found in engine/beat_analysis.py
- **PASS** `dynamic-code-execution` — No eval/exec/compile calls in engine/beat_analysis.py
- **PASS** `shell-injection-surface` — No shell=True subprocess in engine/beat_analysis.py
- **PASS** `selector-determinism-surface` — No forbidden random selection calls in engine/beat_analysis.py
- **PASS** `required-symbols` — engine/clip_analysis.py exposes every required contract symbol
  - `engine/clip_analysis.py:24 ANALYSIS_SCHEMA_VERSION`
  - `engine/clip_analysis.py:1091 classify_clip`
  - `engine/clip_analysis.py:1052 compute_visual_scores`
  - `engine/clip_analysis.py:909 find_best_moment`
- **PASS** `network-surface` — No network-capable imports found in engine/clip_analysis.py
- **PASS** `dynamic-code-execution` — No eval/exec/compile calls in engine/clip_analysis.py
- **PASS** `shell-injection-surface` — No shell=True subprocess in engine/clip_analysis.py
- **PASS** `selector-determinism-surface` — No forbidden random selection calls in engine/clip_analysis.py
- **PASS** `required-symbols` — engine/shot_selector.py exposes every required contract symbol
  - `engine/shot_selector.py:28 SECTION_WEIGHTS`
  - `engine/shot_selector.py:90 SECTION_SCENE_AFFINITY`
  - `engine/shot_selector.py:175 MIN_CUT_SECONDS`
  - `engine/shot_selector.py:930 plan_cuts`
  - `engine/shot_selector.py:447 score_clip`
  - `engine/shot_selector.py:1204 select_best_clips`
- **PASS** `network-surface` — No network-capable imports found in engine/shot_selector.py
- **PASS** `dynamic-code-execution` — No eval/exec/compile calls in engine/shot_selector.py
- **PASS** `shell-injection-surface` — No shell=True subprocess in engine/shot_selector.py
- **PASS** `selector-determinism-surface` — No forbidden random selection calls in engine/shot_selector.py
- **WARN** `B06` — Energy samples are emitted without their calculated time base
  - `engine/beat_analysis.py:371 rms_times is calculated`
  - `engine/beat_analysis.py:455 result emits energy only`
- **WARN** `B09` — Musical labels remain heuristic and carry no confidence/provenance
  - `engine/beat_analysis.py:330 every fourth beat is labelled downbeat`
  - `engine/beat_analysis.py:589 first section is forced to intro`
  - `engine/beat_analysis.py:590 last section is forced to outro`
- **WARN** `CACHE-BEAT-PROVENANCE` — Beat cache identity omits schema, code hash, and analysis configuration
  - `engine/beat_analysis.py:82 key uses size, mtime and path`
- **WARN** `C02` — Clip cache key does not bind every analysis setting/tool identity
  - `engine/clip_analysis.py:177 cache identity`
  - `engine/clip_analysis.py:25 analysis dimension`
  - `engine/clip_analysis.py:26 sample count`
- **WARN** `C06` — Face results omit detector/fallback provenance
  - `engine/clip_analysis.py:1012 face output boundary`
- **WARN** `C10` — Sparse optical-flow values are not normalized by elapsed source time/decoder policy
  - `engine/clip_analysis.py:578 flow signature`
  - `engine/clip_analysis.py:26 sparse sample count`
- **WARN** `UNUSED_SIGNAL` — Signals are emitted by upstream engines but ignored by selector
  - `beat.phrase_boundaries`
  - `beat.energy`
- **WARN** `S12` — Final cuts do not record boundary/onset/grid provenance after arbitration
  - `engine/shot_selector.py:997 slot output fields`
- **PASS** `S13` — Selector best-moment source window reaches and is applied by After Effects
  - `engine/shot_selector.py:1382 selector emits sourceStart`
  - `src/js/main/lib/python.ts:163 CutDecision source fields=True`
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

- **PASS** `engine-contracts` — exit=0, stdout_sha256=`6884808a8bd0342c8ae207afce9c50cb64a877e5bd1ee71f3d87246701965e5f`, stderr_sha256=`e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`
- **FAIL** `analysis-jobs` — exit=None, stdout_sha256=`e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`, stderr_sha256=`b6bb8b8cfd701628639ca308161e0b655dc33e1ea6966e67c616222a2901fcf2`
- **PASS** `server-health` — exit=0, stdout_sha256=`a953ffec512a75af25c13980726d00bac039253ca10bec732df0121a40bb6535`, stderr_sha256=`e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`

## Baseline drift

- Status: **drift**
- Changed: `engine/beat_analysis.py` — expected `cd7d805b9fd819bd2afee3f1cd7fec6519b58b7dabc3f72deaea52252f554608`, actual `d1fa045fdcbd3fe45de534bf3a09a73fbd3da64fe66567b1869cce6ba9301b37`
- Changed: `engine/clip_analysis.py` — expected `e2c80f512a6fff8ba504f3e1f664b281f36c63b8f107557130c1c336055e4551`, actual `b4fa7e847f80af3e2d8979bff63b1f6267624203cea4b29156c40bd7aeab8dc8`
- Changed: `engine/shot_selector.py` — expected `59d8100caeeb3cf6c464d7b8bbcc34de897fe59434a29d13632269a9188fd9f3`, actual `b68a793c4fddaece07d10a782581b613c1cfef21cb6e364f1d6a99fea29fadb5`
- Changed: `scripts/test-engine-contracts.py` — expected `521a572a6dc457389e281234a246f7d920905bcc16b5e985ccae30a3fb28d356`, actual `4a22acbe801626cfc4bdb989cd8d0b0d17cac0001e080b01399bc265112e86bb`
- Changed: `src/js/main/App.tsx` — expected `2f01ac49a93b59d455c112f2008540efaeebb5e9d910043e70868111906c4219`, actual `c30c70213ebf04134be001508d8a85520ddb3c1aad6d961b04f59bb0baa6e489`
- Changed: `src/js/main/lib/python.ts` — expected `3e14d062ecbca3b392521a107bf11b277a6173e1018482e781ad5beab284e8c7`, actual `eb5d335e73b59148adef638c0dae1244a3ac9c674783493d91586ba1e7999b0a`
- Changed: `src/jsx/aeft/aeft.ts` — expected `8be40170274f6af55d002dd8862bad6c0f007b76e43fbadbe7c42d1065c38756`, actual `4a8547b4786ca5b8985b34d6db500c2849c873d38066286179d8a7f426896c53`
- Contract fingerprint changed: `f06eb01a8b71e63238318532307a8588670da201692dcfbd4bf833e8bff8c616` → `a4f216c3deb441e1f905d4b5a003a5dd3b66a5d1048587495ba336f104304f65`

## Engine SHA-256

- `engine/beat_analysis.py` — `d1fa045fdcbd3fe45de534bf3a09a73fbd3da64fe66567b1869cce6ba9301b37` (32064 bytes)
- `engine/clip_analysis.py` — `b4fa7e847f80af3e2d8979bff63b1f6267624203cea4b29156c40bd7aeab8dc8` (50177 bytes)
- `engine/shot_selector.py` — `b68a793c4fddaece07d10a782581b613c1cfef21cb6e364f1d6a99fea29fadb5` (58026 bytes)

## Interpretation boundary

A PASS proves only the checked source integrity, static gates, synthetic cross-engine contracts, and local tests listed above. It does not prove subjective edit quality, native After Effects behavior, real-media accuracy, or claims from the analysis notes that lack fixtures or human validation.
