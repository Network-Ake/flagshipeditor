# FlagshipEditor — Cyber-Forensic Protocol Specification

**Status:** normative design for a permanent local auditor  
**Production scope:** `beat_analysis.py` → `clip_analysis.py` → `shot_selector.py`  
**Implementation target:** `scripts/cyber_forensic_protocol.py` (separate from the three engines)  
**Principle:** isolate each signal, prove its contract, then cross-examine how the next engine consumes it. A fluent report or a visually plausible edit is not evidence.

## 1. Objective and non-objectives

The protocol SHALL detect silent drift, stale or poisoned cache results, malformed media, invalid cross-engine data, non-determinism, performance collapse, and claims that exceed the evidence. It SHALL produce a sealed, replayable local evidence bundle.

It SHALL NOT:

- modify source media or production engine files;
- upload media, paths, thumbnails, hashes, or reports;
- declare an edit artistically “good” without human-labelled ground truth;
- treat a heuristic disagreement as corruption;
- claim real Windows/After Effects end-to-end validity from Python-only tests.

## 2. Threat model

### Protected assets

1. Source-media integrity and privacy.
2. Correct temporal structure: no black gaps, overlaps, reversed windows, or out-of-range seeks.
3. Reproducibility of a selection from identical canonical inputs.
4. Traceability of every score, cut, fallback, cache hit, and error.
5. Availability on the target CPU and bounded behavior on large libraries.

### Trust boundaries and threats

| Boundary | Threat | Required control |
|---|---|---|
| Media → FFprobe/FFmpeg/OpenCV/librosa | corrupt, adversarial, truncated, zero-length, unsupported or pathological media | argument-list execution only; regular-file check; time/memory limits; per-file isolation; classified error |
| Filesystem → cache | source replaced while path/size/mtime appears stable; SQLite edited or corrupted; algorithm changed without cache invalidation | cache is untrusted acceleration; record cache key/schema/config/code hash; uncached replay before a forensic FAIL |
| Dependency/runtime → engine | library/API drift changes results | record Python, OS, CPU, package and bundled-tool versions/hashes |
| Beat → selector | fabricated section semantics, wrong beat phase, stale onsets, missing time base | schema/range checks plus cross-engine metamorphic checks; confidence-labelled claims |
| Clip → selector | incomparable motion scales, duplicate paths, missing scores, decoder-dependent sampling | canonical path identity; field contracts; decoder and sample metadata; duplicate rejection |
| Selector → After Effects | slot/source mismatch, truncation, missing provenance | full timeline and source-window invariants; renderer contract check; no E2E claim without AE evidence |
| Local operator/config → run | changed style, environment variables, thresholds, unordered inputs | canonical configuration and input ordering captured in manifest |

The protocol assumes the local user may alter files or caches accidentally. It detects tampering and drift; it is not a privileged anti-malware sandbox. Crafted codec exploits remain a dependency-security concern and SHALL be reported separately from edit-quality findings.

## 3. Current high-risk facts the auditor must expose

These are properties of the current code, not inferred future defects:

- Beat cache identity contains path, size and mtime, but no beat-analysis schema, configuration, code hash, or dependency hash. A post-upgrade cache hit can therefore be stale.
- Beat cache/progress errors are swallowed. Cache failure is not equivalent to analysis failure and must remain visible in forensic evidence.
- “Downbeats” are every fourth detected beat starting at index zero; this is an unverified 4/4 phase assumption.
- Section classification is ultimately forced to first=`intro`, last=`outro`, maximum-RMS interior=`drop`, then alternating `verse`/`chorus`. Labels are hypotheses, not ground truth.
- “808” evidence is actually onset detection below 80 Hz. It does not prove an 808 instrument, note duration, slide, or kick identity.
- `energy` has no emitted timestamp/hop metadata; `rms_times` is calculated but discarded. `phrase_boundaries` and clip `energy_score` are emitted but not consumed by selection.
- Clip cache schema is present, but analysis dimension, sample count, detector-model identity, decoder/tool hashes and dependency versions are absent from the cache key.
- Optical flow is computed between 12–16 sparse samples across the entire clip, not adjacent video frames, and is not normalized by elapsed source time. Motion values from clips of different duration or decoder sampling are not strictly comparable.
- OpenCV samples 0–100% while FFmpeg samples 5–95%, creating decoder-dependent evidence.
- The optional DNN face path tests `FLAGSHIPEDITOR_FACE_MODEL` as an existing file, then appends `.prototxt` and `.caffemodel`; a normal base-path configuration can silently fall back to Haar.
- One transient large face can classify the whole clip as `close_up`; detector exceptions silently degrade to Haar; detector confidence/provenance is absent from output.
- Selector accepts usable clips with `unknown` scene type, assumes non-empty unique paths, and uses path as identity. Duplicate/empty paths corrupt recency and usage accounting.
- Selector is deterministic only for the exact ordered/canonical input and runtime. The public `seed` is deliberately unused.
- `MAX_CUTS` truncation still ends the last retained slot at track duration, but can create an oversized final slot after the maximum-length subdivision pass. No explicit provenance field identifies boundary/onset/grid origin after cut arbitration.
- A source shorter than its assigned slot can produce `sourceEnd-sourceStart < endTime-beatTime`; without a declared renderer stretch/freeze policy this is a render-integrity failure.
- Selector computes `sourceStart`/`sourceEnd`, but the current ExtendScript `TimelineCut` contract omits both and `appendCutBatch()` never applies a source offset. The advertised “best moment” is therefore not rendered; clips start from source time zero unless another renderer path intervenes.

## 4. Forensic execution lifecycle

Every audit follows this order:

1. **PREPARE** — create run ID; snapshot code/config/dependency/tool hashes; select mode and budgets.
2. **ACQUIRE** — resolve each input path; record stat identity and sampled content fingerprint. Full SHA-256 is mandatory for golden fixtures and optional for very large ordinary libraries.
3. **CANONICALIZE** — normalize paths/case, sort unordered inputs, reject duplicate identities, serialize floats and configuration deterministically.
4. **ISOLATE** — run beat and each clip analyzer independently; retain raw result, duration, cache status, decoder, warnings, stdout/stderr tail and resource telemetry.
5. **CROSS-EXAMINE** — validate Beat→Selector, Clip→Selector and Selector→Renderer invariants.
6. **REPLAY** — repeat canonical selection three times; replay suspicious cached analysis once with cache bypass in an isolated temporary cache directory.
7. **CHAOS** — execute the mode’s adversarial fixtures and metamorphic transforms.
8. **REPORT** — emit machine-readable findings and a concise Markdown report. Every finding links to evidence IDs.
9. **SEAL** — hash every artifact, write `SHA256SUMS`, then hash the manifest. Never edit a sealed run; create a superseding run.

### Modes

| Mode | Purpose | Minimum content |
|---|---|---|
| `preflight` | every build/PR | schemas, hard invariants, 3× selector replay, compact synthetic chaos set |
| `regression` | nightly/release candidate | golden audio/video fixtures, cached-vs-uncached replay, resource telemetry, cross-engine metamorphic tests |
| `deep` | release gate/incident | full fixture matrix, full hashes, dependency/tool binary hashes, cache corruption tests, Windows+AE evidence attachment and human-labelled review |

### Delivery boundary

The current script is a **v1 synthetic preflight**, not the whole protocol. V1 may claim only the checks it actually emits and tests. `regression` and `deep` remain roadmap gates until real-media fixtures, isolated cache replay, resource telemetry, full evidence bundles and native Windows/AE evidence are implemented and verified.

**Implemented in the current v1 script:** SHA-256 inventory and drift signatures for engines, auditor, renderer boundaries, dependencies, styles and critical tests; AST/symbol static gates; isolated child-test execution with tracked-file non-mutation verification; known-gap WARNs; synthetic section, visual-feature, timeline and selector contracts; three-run canonical selector replay; duplicate-identity rejection check; source-window, component-score and alternatives validation; static selector→TypeScript→After Effects source-window inspection (S13); bounded phrase times; explicit missing-baseline/drift verdicts; and a sealed bundle containing JSON, Markdown, JSONL checks and manifest evidence.

**Not implemented in current v1 and therefore never implied by a v1 PASS:** real audio/video decoding; B01–B09 and C01–C10 against real media; cached-vs-uncached replay or cache corruption recovery; planted NaN/gap/MAX_CUTS chaos; parser-backed TypeScript validation; bounded streaming capture and descendant-process termination; cold/warm performance and RSS budgets; raw input fingerprints and full bundle replay; human-labelled accuracy; native Windows installer behavior; native After Effects composition inspection; and artistic quality.

Until those gates exist, v1 output SHALL preserve an explicit limitation boundary. A v1 PASS means only “static gates, listed synthetic contracts, selected existing tests and reviewed baseline match passed.”

## 5. Evidence bundle

Default path: `engine/forensics/runs/<UTC>-<run-id>/`

Required artifacts for the full regression/deep protocol:

```text
manifest.json                 canonical run identity, config, code/dependencies/tools
inputs.json                   opaque input IDs, canonical identities, stats/fingerprints
beat.raw.json                 raw beat result plus cache/provenance envelope
clips/<opaque-id>.raw.json    raw clip result plus decoder/sample/provenance envelope
selector.input.json           exact canonical selector request
selector.run-{1,2,3}.json     replay outputs
checks.jsonl                  one immutable finding per line
telemetry.json                wall/CPU time, peak RSS, cache hits, comparison count
report.md                     human-readable summary
SHA256SUMS                    seal of all preceding artifacts
```

Every check record SHALL include: `check_id`, `stage`, `status`, `severity`, `claim`, `observed`, `expected`, `tolerance`, `evidence_ids`, `code_locations`, `cache_state`, `timestamp_utc`, and `remediation`. Paths in shareable reports SHALL be replaced by opaque IDs; raw local paths stay only in the private manifest.

The manifest SHALL include hashes of the three engine files, forensic script, style JSON, requirements lock, Python executable, FFmpeg and FFprobe binaries; package versions; relevant `FLAGSHIPEDITOR_*` variables; `ANALYSIS_SCHEMA_VERSION`; analysis dimension/sample count; and target machine details.

Current v1 emits `report.json`, `report.md`, `checks.jsonl`, `manifest.json`, `SHA256SUMS` and `SHA256SUMS.sha256`. A reviewed baseline, when one can be accepted without hard failures, lives outside the immutable run directory. This is sufficient for the limited synthetic preflight claim, not for regression/deep replay or cryptographic attestation against an external trust root.

## 6. Normative invariants

Tolerances: timestamp equality `1 ms`, timeline adjacency `1 ms`, score bounds `1e-6`, histogram mass `1e-6`. NaN and Infinity always FAIL.

### A. Beat-analysis contract

| ID | Invariant | Result |
|---|---|---|
| B01 | input is a readable, non-empty regular file; decoded duration is finite and >0 | FAIL otherwise |
| B02 | `tempo` finite and >0; 40–240 BPM is normal, 20–300 is admissible | WARN outside normal; FAIL outside admissible |
| B03 | beats/downbeats/onsets/phrase boundaries are finite, sorted, deduplicated and within `[0,duration]` | FAIL |
| B04 | sections are finite, ordered, positive-length, contiguous and exactly cover `[0,duration]` | FAIL |
| B05 | section types belong to the public taxonomy | FAIL unknown value; WARN if forced fallback dominates |
| B06 | energy is non-empty, finite and non-negative; time-base metadata exists in forensic envelope | FAIL invalid data; WARN if time base is inferred rather than emitted |
| B07 | every reported downbeat is also a beat within tolerance | FAIL |
| B08 | cached and uncached canonical results match within numeric tolerance | FAIL after uncached confirmation |
| B09 | labels `downbeat`, `drop`, `phrase`, and `808` carry method and confidence | WARN when heuristic-only; FAIL only for a false hard claim in a release report |

### B. Clip-analysis contract

| ID | Invariant | Result |
|---|---|---|
| C01 | result path identity matches acquired source; path identities are non-empty and unique | FAIL |
| C02 | output `analysis_schema` equals runtime schema; cache envelope matches code/config/tools | FAIL schema mismatch; WARN incomplete provenance |
| C03 | duration/fps/dimensions are finite and positive; decoder is declared | FAIL |
| C04 | composition, energy, sharpness and stability are finite in `[0,100]`; brightness finite in `[0,255]`; motion fields finite and non-negative | FAIL |
| C05 | histogram has exactly 32 finite non-negative bins and sums to 1 | FAIL |
| C06 | face ratio/consistency are finite in `[0,1]`; `has_face=false` implies ratio=0; detector and fallback are recorded | FAIL numeric contradiction; WARN missing detector provenance |
| C07 | `best_time`, start and end lie inside clip duration and are ordered; confidence lies in `[0,1]` | FAIL |
| C08 | scene type belongs to taxonomy and is compatible with its decisive measured rule | FAIL impossible rule; WARN low-confidence classification |
| C09 | identical sampled frames are deterministic; cache bypass preserves result | FAIL after replay |
| C10 | motion comparisons across clips include sample timestamps, elapsed-time normalization and decoder/sample policy | WARN until implemented; quality claims cannot PASS without it |

### C. Selector and renderer contract

| ID | Invariant | Result |
|---|---|---|
| S01 | output is non-empty, sorted and begins at 0; every `beatTime < endTime` | FAIL |
| S02 | slots have no gap/overlap and end at track duration | FAIL |
| S03 | every slot is at least `MIN_CUT_SECONDS` and no longer than its effective section maximum, except an explicitly documented cap/terminal policy | FAIL |
| S04 | every selection references exactly one unique usable input clip | FAIL |
| S05 | all six component scores and final score are finite in `[0,100]`; weights sum to 1 per section | FAIL |
| S06 | source window is ordered, non-negative and inside clip duration | FAIL |
| S07 | source-window duration covers target-slot duration or an explicit renderer stretch/freeze policy is present | FAIL |
| S08 | selected clip is absent from alternatives; alternatives are unique, valid inputs with finite scores | FAIL |
| S09 | three runs over canonical inputs produce byte-equivalent canonical outputs | FAIL |
| S10 | no-repeat holds for `min(REPEAT_WINDOW, unique_usable_clips-1)`; degradation is explicit | WARN quality degradation; FAIL back-to-back repeat when ≥2 alternatives exist |
| S11 | `cutCount == len(selections)` and cut cap does not truncate track coverage | FAIL |
| S12 | each cut records or reconstructs boundary/onset/grid provenance; an “808-synced” claim requires onset evidence | WARN absent provenance; FAIL unsupported release claim |
| S13 | renderer payload carries and applies selector `sourceStart`/`sourceEnd`; rendered source offset matches selected best-moment window | FAIL when best-moment behavior is claimed but fields are dropped/ignored |

### D. Symbiotic cross-engine checks

1. Beat duration, section end, selector duration and rendered composition duration must agree within 1 ms.
2. Selector beat/onset inputs must hash-match `beat.raw.json`; selector clip payloads must hash-match accepted clip results.
3. A cut claimed as beat-aligned must be within the declared snap tolerance of an input beat. A bass-driven cut must match an input bass onset before or after documented snapping.
4. Section labels must not silently change between beat output and selector output.
5. Clip fields emitted but ignored (`energy_score`) and beat fields emitted but ignored (`phrase_boundaries`, current `energy`) are `UNUSED_SIGNAL` WARNs, never proof of quality.
6. Removing all bass onsets may change drop onset cuts but must not alter clip metadata. Reordering input clips must not change canonical output. Duplicating a path must be rejected, not alter selection.
7. Changing only a clip’s motion evidence should affect energy ranking only where section weights/policy permit; changing only histogram should affect variety relative to the predecessor, not beat placement.
8. Cache hit/miss must not change accepted semantic output. Decoder policy changes require a new analysis identity.

## 7. False-positive controls

1. **Hard contract vs heuristic:** structural/numeric violations can FAIL; artistic, semantic and detector-confidence disagreements default to WARN.
2. **Two-pass confirmation:** cache-related or drift findings SHALL be rerun with an isolated empty cache. A non-reproduced anomaly becomes `WARN/TRANSIENT`, not FAIL.
3. **Two independent signals:** section/energy/face/motion quality findings require either human ground truth or two independent measurements. A single heuristic never proves misclassification.
4. **Environmental separation:** missing codec/tool, permission denial, timeout and cancellation are `ENVIRONMENT` or `AVAILABILITY`, not “bad engine selection.”
5. **Tolerance and canonicalization:** normalize ordering, paths, float serialization and timestamps before comparing.
6. **Fixture confidence:** synthetic fixtures prove contracts only. Real artistic-quality PASS requires labelled footage and blind human review.
7. **No unsupported causality:** the report says “correlated with” unless a metamorphic test changes one variable and reproduces the effect.

## 8. Mandatory chaos matrix

| Family | Cases | Expected behavior |
|---|---|---|
| Audio integrity | missing, empty, corrupt, silence, 1-frame/very short, NaN-like metadata | classified bounded failure; no hang or cache write of invalid result |
| Musical ambiguity | non-4/4 pickup, half/double-time, tempo switch, sparse drums, sustained/side-chained/sliding 808, triplets, flat-RMS limited master, vocal-only bridge | no crash; hard contracts PASS; semantic uncertainty WARN |
| Video integrity | missing, zero-byte, truncated, unsupported codec/profile, variable frame rate, single decodable frame, very short clip | isolated classified failure; rest of job completes |
| Visual ambiguity | LOG/HDR, low light, strobe, profile/occluded/multiple faces, crowd motion, whip pan, slow zoom, camera shake, portrait/ultrawide | no false hard claim; confidence/provenance WARN where unresolved |
| Payload mutation | unsorted/duplicate/out-of-range beats/onsets, overlapping/gapped/NaN sections, unknown types, empty/duplicate paths, scores outside range | reject or canonicalize explicitly; never silently accept contradiction |
| Scale | 1/2/3/4 clips, all same scene, 4+ minute track, 50k-file job, cut density near `MAX_CUTS`, comparison explosion | bounded completion, explicit degradation, no timeline truncation |
| Cache | corrupt JSON/SQLite, stale schema/config/code, source changed, read-only cache, cache deleted mid-run | safe miss/rebuild; cached-vs-uncached equivalence; source untouched |
| Concurrency | two workers, cancellation during decode/write, backend restart, repeated same path | terminal job state, no duplicate result, no orphaned work |

Each regression fixture SHALL define expected status and contract facts, not an exact heuristic label unless human-annotated.

## 9. Performance budgets

Hard budgets mirror current runtime limits and are measured on the target Windows machine; development-Mac results are comparative only.

| Stage | Soft budget | Hard budget / result |
|---|---|---|
| Beat, ordinary ≤5 min track, cold | 60 s | 180 s → FAIL timeout |
| Clip, cold | 30 s | 120 s per clip → FAIL timeout |
| Clip, warm cache | 0.5 s | 2 s → WARN/FAIL if reproducible |
| Selector, ordinary ≤1,000 cuts and ≤1,000 clips | 2 s | 10 s → FAIL |
| Preflight suite | 30 s | 120 s → FAIL |
| Regression suite excluding media decode | 5 min | 15 min → FAIL |
| Worker peak RSS | 512 MiB soft | 1 GiB → FAIL |
| Beat process peak RSS | 1 GiB soft | 2 GiB → FAIL |

Additionally, a runtime regression >25% against the median of five same-machine baseline runs is WARN; >50% is FAIL after one clean rerun. The selector SHALL estimate `cuts × usable_clips` before execution: >5 million comparisons is WARN, >20 million requires an explicit deep-mode override. No budget relaxation may hide a timeline-integrity failure.

## 10. Verdict and release gates

Per-check statuses are `PASS`, `WARN`, `FAIL`, or `SKIP` with reason.

- **PASS:** observed evidence satisfies a deterministic contract within tolerance.
- **WARN:** output remains usable but evidence is weak, heuristic, degraded, unused, transient, unlabelled, or over a soft budget.
- **FAIL:** a hard invariant breaks; evidence/replay is internally contradictory; a crash/hang exceeds hard budget; input integrity is lost; selector is non-deterministic; or the rendered timeline/source contract cannot be honoured.

Aggregate full-protocol verdict:

- any FAIL → `FAIL` and non-zero exit;
- no FAIL but ≥1 WARN → `WARN`;
- all required checks PASS and none WARN → `PASS`;
- required check SKIP without an approved reason → `FAIL`.

Recommended full-protocol exit codes: `0=PASS`, `2=WARN`, `1=FAIL`, `3=auditor/internal error`.

Current v1 compatibility statuses are `PASS=0`, `FAIL=1`, `DRIFT=2`, `PROTOCOL_ERROR=3`. `DRIFT` is a warn-class baseline mismatch, not a semantic engine PASS and not proof of corruption.

Release claims are gated separately:

1. Python contract PASS does not authorize “professional edit quality.”
2. Semantic-quality PASS requires labelled fixtures and blind human comparison.
3. Native E2E PASS requires the sealed Windows/After Effects run, installed packaged runtime, real source media, final composition inspection and named human validator.

## 11. Script interface and minimum self-test

Implemented v1 CLI:

```bash
python scripts/cyber_forensic_protocol.py --tests full
python scripts/cyber_forensic_protocol.py --tests core --output forensics/evidence/preflight
python scripts/cyber_forensic_protocol.py --update-baseline --accept-baseline "review reason"
```

Roadmap CLI surface, not currently implemented: explicit `selfcheck`, `audit --mode regression|deep`, `compare` and `verify-seal` operations.

The future `selfcheck` SHALL deliberately inject one NaN, one duplicate path, one stale cache envelope, one selector output gap and one altered evidence file. It passes only if all five are detected with the expected category and the source fixtures remain byte-identical.

## 12. Acceptance criteria and implementation status boundary

### Current V1 preflight acceptance

The current v1 is accepted only for its limited preflight claim when its inventory/static checks, synthetic cross-engine invariants, requested existing tests, reviewed baseline comparison and report seal complete with the documented exit code. This does not satisfy the full protocol acceptance criteria.

Before v1 can claim conformance to all preflight requirements in this specification, it still must gain stable IDs and planted tests for every advertised B/C/S invariant, NaN/gap/MAX_CUTS chaos, parser-backed renderer validation, bounded subprocess capture/tree termination, and an explicit selfcheck CLI. Current seal-tamper, duplicate-path, missing-baseline, output-safety and three-run replay regressions cover only the implemented subset.

### Regression/deep completion roadmap

The full protocol is complete only when:

1. all checks above have stable IDs and unit tests;
2. a run can be replayed from `selector.input.json` without source discovery;
3. cached and uncached paths are both testable without touching the user’s live cache;
4. the synthetic chaos suite detects every planted contradiction;
5. the evidence seal detects a one-byte modification;
6. the auditor itself distinguishes engine FAIL from auditor/internal error;
7. source media hashes before and after are identical;
8. current known limitations appear as WARNs rather than being silently labelled PASS;
9. preflight integrates with the existing engine-contract tests; and
10. a human can trace any final verdict from report → check → raw evidence → code/config identity.
