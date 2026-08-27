# FlagshipEditor — Cyber-Forensic Engine Report

- Verdict: **FAIL**
- Exit code: `1`
- Generated: `2026-08-25T05:28:34+00:00`
- Protocol: `1.0.0`
- Commit: `8f850d71d1b4826a3fd118b509a202ea7a0588d9`
- Network boundary: the protocol implements no network calls; child tests are **not** OS-level network-sandboxed

## Gate summary

- Static/cross-engine checks: {'pass': 22, 'warn': 16, 'fail': 1}
- Existing dynamic tests: {'pass': 2, 'fail': 0, 'not_run': 0}
- Baseline: `missing`
- Inventory: 34 files hashed with SHA-256

## Findings

- **PASS** `required-symbols` — engine/beat_analysis.py exposes every required contract symbol
  - `engine/beat_analysis.py:81 analyze_track`
  - `engine/beat_analysis.py:403 detect_phrase_boundaries`
  - `engine/beat_analysis.py:71 frequency_filter`
- **PASS** `network-surface` — No network-capable imports found in engine/beat_analysis.py
- **PASS** `dynamic-code-execution` — No eval/exec/compile calls in engine/beat_analysis.py
- **PASS** `shell-injection-surface` — No shell=True subprocess in engine/beat_analysis.py
- **PASS** `selector-determinism-surface` — No forbidden random selection calls in engine/beat_analysis.py
- **PASS** `required-symbols` — engine/clip_analysis.py exposes every required contract symbol
  - `engine/clip_analysis.py:24 ANALYSIS_SCHEMA_VERSION`
  - `engine/clip_analysis.py:731 classify_clip`
  - `engine/clip_analysis.py:692 compute_visual_scores`
  - `engine/clip_analysis.py:549 find_best_moment`
- **PASS** `network-surface` — No network-capable imports found in engine/clip_analysis.py
- **PASS** `dynamic-code-execution` — No eval/exec/compile calls in engine/clip_analysis.py
- **PASS** `shell-injection-surface` — No shell=True subprocess in engine/clip_analysis.py
- **PASS** `selector-determinism-surface` — No forbidden random selection calls in engine/clip_analysis.py
- **PASS** `required-symbols` — engine/shot_selector.py exposes every required contract symbol
  - `engine/shot_selector.py:28 SECTION_WEIGHTS`
  - `engine/shot_selector.py:90 SECTION_SCENE_AFFINITY`
  - `engine/shot_selector.py:103 MIN_CUT_SECONDS`
  - `engine/shot_selector.py:708 plan_cuts`
  - `engine/shot_selector.py:262 score_clip`
  - `engine/shot_selector.py:866 select_best_clips`
- **PASS** `network-surface` — No network-capable imports found in engine/shot_selector.py
- **PASS** `dynamic-code-execution` — No eval/exec/compile calls in engine/shot_selector.py
- **PASS** `shell-injection-surface` — No shell=True subprocess in engine/shot_selector.py
- **PASS** `selector-determinism-surface` — No forbidden random selection calls in engine/shot_selector.py
- **WARN** `B06` — Energy samples are emitted without their calculated time base
  - `engine/beat_analysis.py:159 rms_times is calculated`
  - `engine/beat_analysis.py:191 result emits energy only`
- **WARN** `B09` — Musical labels remain heuristic and carry no confidence/provenance
  - `engine/beat_analysis.py:118 every fourth beat is labelled downbeat`
  - `engine/beat_analysis.py:321 first section is forced to intro`
  - `engine/beat_analysis.py:322 last section is forced to outro`
- **WARN** `CACHE-BEAT-PROVENANCE` — Beat cache identity omits schema, code hash, and analysis configuration
  - `engine/beat_analysis.py:53 key uses size, mtime and path`
- **WARN** `C02` — Clip cache key does not bind every analysis setting/tool identity
  - `engine/clip_analysis.py:146 cache identity`
  - `engine/clip_analysis.py:25 analysis dimension`
  - `engine/clip_analysis.py:26 sample count`
- **WARN** `C06` — Face results omit detector/fallback provenance
  - `engine/clip_analysis.py:652 face output boundary`
- **WARN** `C10` — Sparse optical-flow values are not normalized by elapsed source time/decoder policy
  - `engine/clip_analysis.py:437 flow signature`
  - `engine/clip_analysis.py:26 sparse sample count`
- **WARN** `UNUSED_SIGNAL` — Signals are emitted by upstream engines but ignored by selector
  - `beat.phrase_boundaries`
  - `beat.energy`
  - `clip.energy_score`
- **WARN** `S12` — Final cuts do not record boundary/onset/grid provenance after arbitration
  - `engine/shot_selector.py:775 slot output fields`
- **FAIL** `S13` — Selector sourceStart/sourceEnd are dropped before rendering; best moment is not applied
  - `engine/shot_selector.py:975 selector emits sourceStart`
  - `src/js/main/lib/python.ts:126 CutDecision source fields=False`
  - `src/js/main/App.tsx:105 payload source fields=False`
  - `src/js/main/App.tsx:172 serialization drops source fields=True`
  - `src/jsx/aeft/aeft.ts:77 renderer contract source fields=False`
  - `src/jsx/aeft/aeft.ts:245 renderer source offset applied=False`
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
- **WARN** `BASELINE-MISSING` — No reviewed baseline exists; drift comparison is unavailable
  - `engine/forensics/baseline.json`

## Existing dynamic tests

- **PASS** `engine-contracts` — exit=0, stdout_sha256=`d554614c17cf383a6e09a2961c87e6d34cba2d6a4582ebddd4967f528331c255`, stderr_sha256=`e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`
- **PASS** `server-health` — exit=0, stdout_sha256=`a953ffec512a75af25c13980726d00bac039253ca10bec732df0121a40bb6535`, stderr_sha256=`e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`

## Baseline drift

- Status: **missing**

## Engine SHA-256

- `engine/beat_analysis.py` — `cd7d805b9fd819bd2afee3f1cd7fec6519b58b7dabc3f72deaea52252f554608` (15486 bytes)
- `engine/clip_analysis.py` — `e2c80f512a6fff8ba504f3e1f664b281f36c63b8f107557130c1c336055e4551` (33707 bytes)
- `engine/shot_selector.py` — `a4faec413215232c0e906a46514e50218db7a588b8b0308c46c23aa3b4c28cfe` (39912 bytes)

## Interpretation boundary

A PASS proves only the checked source integrity, static gates, synthetic cross-engine contracts, and local tests listed above. It does not prove subjective edit quality, native After Effects behavior, real-media accuracy, or claims from the analysis notes that lack fixtures or human validation.
