# FlagshipEditor Shot Selector Engine Analysis

**Analysis Date:** 2026-08-24  
**Scope:** Deep technical audit of `shot_selector.py` with validation against `beat_analysis.py` and `clip_analysis.py`

---

## Executive Summary

The shot selector engine implements a **two-phase architecture**: cut planning (temporal slots) followed by clip assignment (visual selection). The system is deterministic and musically grounded, but has critical failure modes in edge cases involving small clip libraries, sparse musical content, and long-form tracks.

**Key Findings:**
- ✅ Cut planning is robust: section boundaries enforced, bass onsets respected in drops
- ⚠️ Clip selection lacks context-awareness: no energy matching between clip motion and section intensity
- ❌ No narrative arc: cuts distributed uniformly, not building/releasing tension
- ❌ Small library failure: REPEAT_WINDOW=4 breaks with <5 clips
- ❌ No lyric awareness: vocal phrases ignored despite Whisper availability
- ❌ Hook detection absent: best moments not reserved for climactic sections

---

## 1. DECISION ARCHITECTURE — How Cuts Are Actually Planned

### 1.1 `plan_cuts()` Execution Flow

```
INPUT: beats[], sections[], style_config, duration, tempo, bass_onsets[]
│
├─ Step 1: normalize_sections()
│   └─ Repairs overlaps/gaps, ensures [0, duration] coverage
│   └─ Absorbs slivers < MIN_SECTION_SECONDS (1.0s)
│
├─ Step 2: _section_cut_candidates() per section
│   ├─ Section start ALWAYS added at _CUT_BOUNDARY (priority=2)
│   ├─ Beat grid walk at interval_beats (priority=0)
│   │   └─ intro/outro: 4.0 beats (1 bar)
│   │   └─ verse: 4.0 beats (1 bar)
│   │   └─ chorus: 1.0 beat (every beat)
│   │   └─ drop: 1.0 beat + bass onsets
│   │   └─ bridge: 2.0 beats
│   └─ Drop special case: bass_onsets added at _CUT_ONSET (priority=1)
│       └─ double_time_on_808 adds offbeat cuts
│
├─ Step 3: _dedupe_times()
│   └─ Collapse candidates within _DEDUPE_TOLERANCE (12ms)
│   └─ Keep highest priority (BOUNDARY > ONSET > GRID)
│
├─ Step 4: _enforce_min_spacing()
│   └─ Remove cuts creating slots < MIN_CUT_SECONDS (0.15s)
│   └─ Higher priority cuts evict lower priority neighbors
│
├─ Step 5: _subdivide_long_slots()
│   └─ Split slots exceeding SECTION_MAX_BEATS
│   └─ Prevents 8-beat single shots in high-energy sections
│
├─ Step 6: _absorb_runt_tails()
│   └─ Remove final cut if slot < 50% of expected interval
│   └─ Prevents quarter-second flash frames before transitions
│
└─ OUTPUT: slots[{beatTime, endTime, sectionType}]
```

**Validated from code:** Lines 297-378 (`plan_cuts`), 195-253 (`_section_cut_candidates`)

### 1.2 Section-to-Strategy Mapping

| Section Type | `SECTION_CUT_BEATS` | `SECTION_MAX_BEATS` | Bass Onset Driven |
|-------------|---------------------|---------------------|-------------------|
| intro | 4.0 | 8.0 | ❌ |
| verse | 4.0 | 8.0 | ❌ |
| chorus | 1.0 | 2.0 | ❌ |
| drop | 1.0 | 2.0 | ✅ Yes |
| bridge | 2.0 | 4.0 | ❌ |
| outro | 4.0 | 8.0 | ❌ |

**Override mechanism:** `style_config.cut_strategy.<section>.cut_interval` can override defaults (line 180-192).

### 1.3 `_enforce_min_spacing()` Implementation

```python
def _enforce_min_spacing(candidates, min_gap):
    kept = []
    for entry in candidates:
        time_value, _section_type, priority = entry
        while kept and time_value - kept[-1][0] < min_gap and priority > kept[-1][2]:
            kept.pop()  # Evict lower-priority cut
        if not kept or time_value - kept[-1][0] >= min_gap:
            kept.append(entry)
        elif priority == _CUT_BOUNDARY and kept[-1][2] == _CUT_BOUNDARY:
            kept.append(entry)  # Honor both boundaries
    return kept
```

**Priority hierarchy:** `_CUT_BOUNDARY`(2) > `_CUT_ONSET`(1) > `_CUT_GRID`(0)

**Behavior:** When two cuts are too close (<150ms), the higher-priority cut survives. Lower-priority cuts are removed entirely, not shifted. This means the surviving cut simply runs longer.

**Validated from code:** Lines 267-282

### 1.4 Priority System: 808 vs Grid

In drops, bass onsets compete with the metronomic grid:

```python
if section_type == "drop" and onsets:
    snap_tolerance = min(0.08, period * 0.25)  # 80ms or 25% of beat period
    for onset in onsets:
        if start <= onset < end:
            snapped = _snap_to_beat(onset, section_beats, snap_tolerance)
            candidates.append((snapped, _CUT_ONSET))  # Priority 1
            if double_time and half_step >= MIN_CUT_SECONDS:
                offbeat = snapped + half_step
                candidates.append((offbeat, _CUT_GRID))  # Priority 0
```

**Mechanism:**
- Bass onsets within 80ms of a beat are quantized onto that beat
- Onsets farther away remain as syncopated cuts
- `_dedupe_times()` resolves conflicts: if an onset lands on a grid cut, the onset's priority=1 wins over grid's priority=0

**Validated from code:** Lines 223-240, 256-265

### 1.5 `find_best_moment()` Interaction with Cut Placement

```python
def best_moment_window(clip_info, slot_length):
    clip_duration = bounded_duration(clip_info.get("duration"))
    best_moment = clip_info.get("best_moment") or {}
    best_time = float(best_moment.get("best_time", 0.0))
    
    # Center the peak ~1/3 into the cut
    source_start = best_time - slot_length * 0.35
    latest_start = max(0.0, clip_duration - slot_length)
    source_start = max(0.0, min(latest_start, source_start))
    source_end = min(clip_duration, source_start + slot_length)
    return source_start, source_end
```

**What `best_moment` contains (from `clip_analysis.py`):**
- `best_time`: timestamp (seconds) of peak frame score
- `best_start_time`, `best_end_time`: window boundaries
- `confidence`: 0.0-1.0 based on peak vs average score delta

**Scoring formula (from `find_best_moment()`):**
```python
frame_score = composition + min(100, brightness) + min(100, motion_per_frame * 3.0)
peak_idx = argmax(frame_scores)
window_size = max(1, min(5, frame_count // 3))  # 3-5 sample window
```

**Interaction:** The cut slot determines `slot_length`. `best_moment_window()` centers the clip's peak moment 35% into the slot, then clamps to clip duration. If the clip is shorter than the slot, it still gets selected but penalized later via `SHORT_CLIP_PENALTY`.

**Validated from code:** `shot_selector.py` lines 441-457, `clip_analysis.py` lines 580-610

---

## 2. FAILURE MODES — Where Selection Logic Breaks

### 2.1 Fewer Clips Than Sections

**Scenario:** 3 clips, 8 sections (intro→verse→chorus→drop→bridge→verse→chorus→outro)

**Current behavior:**
- `filter_clips_for_section()` returns preferred clips, falls back to all usable (line 389-395)
- `_eligible_indices()` enforces `REPEAT_WINDOW=4` (line 403-415)
- With 3 clips, after 3 cuts all clips are blocked
- Loop in `_eligible_indices()` reduces window from 4→3→2→1
- Eventually returns all indices when window=1 and still blocked

**Result:** System degrades gracefully but violates the no-repeat rule. A clip may appear twice within 4 cuts.

**Code evidence:** Lines 403-415 (`_eligible_indices`)

```python
def _eligible_indices(scored, recent, preferred):
    for window in range(REPEAT_WINDOW, 0, -1):  # 4, 3, 2, 1
        blocked = set(recent[-window:])
        allowed = [i for i, e in enumerate(scored) if e["clipPath"] not in blocked]
        if not allowed:
            continue
        favoured = [i for i in allowed if scored[i]["clipPath"] in preferred]
        return favoured or allowed
    return list(range(len(scored)))  # Fallback: all clips eligible
```

**Impact:** MEDIUM. Visual repetition increases, but edit completes.

### 2.2 All Clips Same Scene Type

**Scenario:** 20 clips, all `scene_type="b_roll_static"`

**Current behavior:**
- `SECTION_SCENE_AFFINITY` defines preferences per section (e.g., verse prefers `performance`, `close_up`)
- `score_clip()` adds `AFFINITY_BONUS=12.0` for matching scene types (line 125-128)
- With all clips same type, no clip receives bonus in any section
- Selection falls back to composite score alone

**Result:** All sections get same visual style. Verse lacks artist presence, drop lacks motion.

**Code evidence:** Lines 119-128, 56-72 (`SECTION_SCENE_AFFINITY`)

```python
preferred = list(affinity) if affinity is not None else list(section_affinity(section_type))
scene_type = str(clip_info.get("scene_type", "unknown"))
if scene_type in preferred:
    rank = preferred.index(scene_type)
    composite += AFFINITY_BONUS * (1.0 - rank / max(1, len(preferred)))
```

**Impact:** HIGH. Musical intent lost: verses should show artist, drops should show motion.

### 2.3 Sparse Bass Onsets (Ambient Intro)

**Scenario:** Track with 0 bass onsets in first 30 seconds (ambient pad intro)

**Current behavior:**
- `_section_cut_candidates()` checks `if section_type == "drop" and onsets:` (line 223)
- Non-drop sections never use bass onsets
- Falls back to beat grid walk using `interval_beats`
- If no beats detected either, uses tempo-based metronome (line 212-217)

```python
else:
    # No beat landed in this section — fall back to tempo
    step = max(MIN_CUT_SECONDS, interval_beats * period)
    time_value = start + step
    while time_value < end:
        candidates.append((time_value, _CUT_GRID))
        time_value += step
```

**Result:** Cuts still placed, but may feel mechanical without musical events to justify them.

**Impact:** LOW-MEDIUM. Edit completes, but rhythm may feel arbitrary in ambient sections.

### 2.4 Long Tracks (4+ Minutes) — Clip Exhaustion

**Scenario:** 240-second track, 15 clips averaging 10s each

**Cut density calculation:**
- Average BPM: 100 → beat period = 0.6s
- Verse (4 beats/cut): 1 cut per 2.4s → ~100 cuts for 240s
- Chorus/Drop (1 beat/cut): 1 cut per 0.6s → ~400 cuts for 240s
- Mixed sections: estimate 150-200 cuts total

**Clip usage:**
- `clip_usage_count` tracks how many times each clip used (line 504)
- `OVERUSE_PENALTY = 3.0` applied after 2 uses (line 481-483)
- After 3 uses: score reduced by 9 points
- After 5 uses: score reduced by 15 points

**Result:** Clips reused extensively. Penalty accumulates but doesn't prevent reuse—just deprioritizes.

**Code evidence:** Lines 480-484

```python
usage = clip_usage_count.get(result["clipPath"], 0)
if usage > 2:
    result["composite"] = max(0.0, result["composite"] - usage * OVERUSE_PENALTY)
```

**Impact:** HIGH. Visual monotony in long tracks. No mechanism to reserve "best" clips for later sections.

### 2.5 Variable Clip Durations (2s vs 30s)

**Scenario:** Library contains 2s flashes and 30s slow pans

**Current behavior:**
- `SHORT_CLIP_PENALTY = 15.0` applied proportionally (line 487-491)
- Shortfall ratio: `(slot_length - clip_length) / slot_length`
- Max penalty: 15.0 points for clips much shorter than slot

```python
clip_length = bounded_duration(clip.get("duration"))
if clip_length and clip_length < slot_length:
    shortfall = min(1.0, (slot_length - clip_length) / slot_length)
    result["composite"] = max(0.0, result["composite"] - SHORT_CLIP_PENALTY * shortfall)
```

**Problem:** A 2s clip in a 0.6s slot (chorus) incurs NO penalty because `clip_length > slot_length`. But a 30s clip in a 0.6s slot is fine—it's just trimmed.

**Hidden issue:** `best_moment_window()` extracts a window from the clip, but if the clip is 2s and the slot is 3s (verse), the window is clamped:

```python
source_end = min(clip_duration, source_start + slot_length)  # May be < slot_length
```

This creates a gap in the timeline—the clip doesn't fill its slot.

**Impact:** MEDIUM-HIGH. Short clips may leave gaps or require stretching (not handled in selector).

### 2.6 "No Repeat Within 4 Cuts" vs Small Clip Pool

**Already covered in 2.1**, but worth emphasizing:

**Mathematical constraint:** With N clips and `REPEAT_WINDOW=W`, you can make at most N cuts before violating the rule.

**Current mitigation:** Window shrinks from 4→1, but this is reactive, not proactive.

**Better approach:** Dynamically adjust `REPEAT_WINDOW` based on library size:
```python
adaptive_window = max(2, min(4, len(usable_clips) // 2))
```

**Impact:** MEDIUM. Rule violation degrades quality but doesn't break the edit.

---

## 3. NARRATIVE ARC ANALYSIS

### 3.1 Professional Music Video Editing Structure

**Based on established editing theory (no web access—drawing from canonical knowledge):**

**Three-act structure in music videos:**
1. **Setup (0-25%):** Establish artist, setting, visual motif. Cut density LOW (4-8s per shot).
2. **Confrontation (25-75%):** Build energy through rhythmic cutting. Cut density MODERATE-HIGH (1-4s per shot).
3. **Resolution (75-100%):** Release tension, often slower cuts or montage. Cut density VARIABLE.

**Energy curve in hip-hop videos:**
- **Intro:** Low energy, atmospheric shots (b-roll static, low light)
- **Verse 1:** Moderate energy, artist performance (close-ups, medium shots)
- **Chorus 1:** High energy, dynamic movement (performance + b-roll dynamic)
- **Verse 2:** Moderate-high, variation on V1
- **Chorus 2:** High, repeat visual motifs from C1
- **Bridge:** Energy dip, abstract/experimental shots
- **Final Chorus/Drop:** PEAK energy, fastest cuts, best visuals
- **Outro:** Decay, lingering shots

**What FlagshipEditor does:**
- ✅ Section detection identifies intro/verse/chorus/drop/bridge/outro
- ✅ Cut density varies by section (4 beats in verse, 1 beat in chorus)
- ❌ No progressive intensification: chorus 1 = chorus 2 = chorus 3
- ❌ No visual motif tracking: same scene affinity every time
- ❌ Best clips assigned by score alone, not reserved for climax

### 3.2 "Phrasing" in Music Video Editing

**Definition:** Phrasing is the grouping of cuts into musical units (bars, phrases, periods).

**Typical hip-hop phrasing:**
- **Micro-rhythm (within a bar):** 2 fast cuts + 1 hold (e.g., 0.5s + 0.5s + 1s = 2-bar phrase)
- **Phrase (4 bars):** Build-up (cuts accelerate) → downbeat (hold) → release
- **Period (16 bars):** Complete emotional arc (tension → climax → resolution)

**How editors create micro-rhythms:**
1. **Pattern establishment:** First 4 bars set a rhythm (e.g., cut on beats 1, 2, 4)
2. **Pattern variation:** Next 4 bars alter rhythm (e.g., cut on 1, 3, 4)
3. **Pattern break:** Downbeat of bar 9 holds for 2 beats (surprise)
4. **New pattern:** Bars 9-12 establish new rhythm

**What FlagshipEditor does:**
- ✅ Cuts align to beats (metronomic grid)
- ✅ Drops follow bass onsets (syncopation)
- ❌ No pattern establishment: every bar identical cut rhythm
- ❌ No variation: chorus cut interval constant throughout
- ❌ No pattern breaks: no intentional holds for surprise

**Recommendation:** Implement `cut_pattern` in style_config:
```json
{
  "cut_strategy": {
    "chorus": {
      "pattern": [0.5, 0.5, 1.0, 0.5, 0.5, 2.0],  // beats per cut
      "repeat": true  // loop pattern across section
    }
  }
}
```

### 3.3 MVX AI "3-Step Workflow" Research

**Unable to verify via web search (search disabled).** Based on typical AI video editor patterns:

**Hypothetical MVX workflow:**
1. **Import:** Analyze clips (scene type, motion, faces)
2. **Cut:** Detect beats/sections, place cut points
3. **Select:** Match clips to cuts based on energy/scene type

**What FlagshipEditor does better:**
- Bass onset detection in drops
- Best moment extraction (not just head/tail trimming)
- Face consistency scoring (performance vs b-roll classification)

**What MVX might do better (speculation):**
- Lyric synchronization (if they have licensing deals)
- Hook detection (identifying catchiest moment)
- Narrative arc (reserving best clips for climax)

**Status:** UNABLE TO VALIDATE without web access. Recommend manual verification of MVX documentation.

---

## 4. SCORING SYSTEM ANALYSIS

### 4.1 Current Score Computation

**Six criteria with section-specific weights:**

```python
scores = {
    "composition": bounded_score(clip_info.get("composition_score"), 50),
    "energy": min(100, motion_intensity * 0.6 + motion_variance * 3.0),
    "variety": histogram_distance(clip, prev_clip),  # 0-100 color difference
    "sharpness": bounded_score(clip_info.get("sharpness_score"), 50),
    "stability": bounded_score(clip_info.get("brightness_stability", 100), 100),
    "face_quality": face_quality_score + face_consistency * 0.2
}

weights = SECTION_WEIGHTS[section_type]  # e.g., drop: energy=0.35, variety=0.25
composite = sum(scores[key] * weights[key] for key in scores)

# Affinity bonus
if scene_type in preferred:
    composite += AFFINITY_BONUS * (1.0 - rank / len(preferred))  # +12 max
```

**Section weight examples:**

| Criterion | Intro | Verse | Chorus | Drop | Bridge | Outro |
|-----------|-------|-------|--------|------|--------|-------|
| composition | 0.30 | 0.20 | 0.20 | 0.15 | 0.30 | 0.30 |
| energy | 0.10 | 0.15 | 0.30 | 0.35 | 0.10 | 0.10 |
| variety | 0.20 | 0.15 | 0.20 | 0.25 | 0.20 | 0.20 |
| sharpness | 0.20 | 0.15 | 0.15 | 0.15 | 0.20 | 0.20 |
| stability | 0.15 | 0.10 | 0.05 | 0.05 | 0.15 | 0.15 |
| face_quality | 0.05 | 0.25 | 0.10 | 0.05 | 0.05 | 0.05 |

**Validated from code:** Lines 14-54 (`SECTION_WEIGHTS`), 103-134 (`score_clip`)

### 4.2 Context-Awareness Analysis

**Question:** Does a clip score differently in a verse vs a drop?

**Answer:** YES, via weights and affinity.

- **Energy score** same everywhere, but weight differs: 0.15 (verse) vs 0.35 (drop)
- **Face quality** weighted 0.25 in verse, 0.05 in drop
- **Scene affinity** bonus applies only if clip matches section preference

**Example:** High-motion clip (energy=80):
- In verse: 80 × 0.15 = 12 points
- In drop: 80 × 0.35 = 28 points
- **Delta:** +16 points in drop

**Limitation:** Score doesn't consider what came BEFORE or what comes AFTER.

### 4.3 Negative Scoring for Visual Repetition

**Current state:** Only `clip_usage_count` penalty exists (line 481-483).

```python
if usage > 2:
    composite -= usage * OVERUSE_PENALTY  # -3 per use after 2nd
```

**What's missing:**
- No penalty for repeating SAME SCENE TYPE recently
- No penalty for repeating SAME COLOR PALETTE (histogram similarity to recent clips)
- No penalty for repeating SAME MOTION PATTERN (high→low→high energy sequence)

**Recommended addition:**
```python
def recency_penalty(clip_path, recent_clips, clip_scene_type, recent_scene_types):
    penalty = 0.0
    # Same clip in last 2 cuts
    if clip_path in recent_clips[-2:]:
        penalty += 20.0
    # Same scene type in last 3 cuts
    if recent_scene_types.count(clip_scene_type) >= 2:
        penalty += 10.0
    return penalty
```

**Impact:** Would improve visual variety without relying solely on `REPEAT_WINDOW`.

### 4.4 Energy Matching: Clip Motion → Section Energy

**Current state:** NOT implemented.

**Section energy levels (inferred from cut density and weights):**
- Intro: 0.2 (low)
- Verse: 0.4 (moderate)
- Chorus: 0.7 (high)
- Drop: 0.9 (peak)
- Bridge: 0.3 (dip)
- Outro: 0.2 (decay)

**Clip energy metric (from `clip_analysis.py`):**
```python
motion_intensity = compute_motion_intensity(frames)  # Mean optical flow
motion_variance = compute_motion_variance(frames)     # Variance of flow
energy_score = min(100, motion_intensity * 0.6 + motion_variance * 3.0)
```

**Mismatch example:**
- Drop section (energy weight=0.35) selects clip with energy_score=15 (static b-roll)
- Because composition=90, sharpness=85 outweigh energy in composite
- Result: Visually beautiful but tonally wrong shot for climax

**Recommended fix:** Add energy matching bonus/penalty:
```python
section_energy_target = {"intro": 0.2, "verse": 0.4, "chorus": 0.7, "drop": 0.9, "bridge": 0.3, "outro": 0.2}
clip_energy_normalized = clip_energy_score / 100.0
energy_delta = abs(clip_energy_normalized - section_energy_target[section_type])
energy_match_bonus = (1.0 - energy_delta) * 15.0  # Up to +15 for perfect match
```

**Impact:** HIGH. Would ensure high-motion clips land in drops, calm clips in bridges.

---

## 5. LYRIC AWARENESS

### 5.1 Timed Lyrics API Availability

**Unable to verify current API status (web search disabled).** Known options:

| API | Cost | Timestamps | Real-time | Notes |
|-----|------|------------|-----------|-------|
| Musixmatch | Freemium | ✅ Synced lyrics | Rate limited | Requires licensing for commercial use |
| Genius | Free | ❌ No timestamps | Unlimited | Text only, no alignment |
| Spotify | Paid | ✅ Via API | Rate limited | Requires Premium account |
| Whisper | Free (local) | ⚠️ Vocal activity only | CPU-intensive | Transcription possible, but no lyric database |

**Whisper for vocal activity detection:**
- Can detect WHEN vocals are present (vs instrumental)
- Cannot identify WHAT words are sung without transcription
- Transcription accuracy varies by language/accent

**Feasibility in FlagshipEditor:**
```python
import whisper

model = whisper.load_model("base")
result = model.transcribe(audio_path, word_timestamps=True)
# Returns: [{word: "yeah", start: 12.3, end: 12.8}, ...]
```

**Processing time:** ~30s for 3-min track on CPU (M1: ~10s)

### 5.2 Cut Alignment to Lyric Phrases

**If timestamps available:**

**Principle:** Cuts should align to lyric boundaries, not just beats.

**Example:**
```
Lyric: "I been grinding since the bottom / Now they watching like I'm God"
Beat:  1    2    3    4     1    2    3    4
Cut:   [----phrase 1----]  [----phrase 2----]
```

**Implementation:**
```python
def align_cuts_to_lyrics(cuts, lyrics):
    """Shift cut points to nearest lyric boundary within tolerance."""
    tolerance = 0.2  # 200ms
    for cut in cuts:
        # Find nearest lyric start/end
        for lyric in lyrics:
            if abs(cut['beatTime'] - lyric['start']) < tolerance:
                cut['beatTime'] = lyric['start']
                break
            if abs(cut['endTime'] - lyric['end']) < tolerance:
                cut['endTime'] = lyric['end']
                break
    return cuts
```

**Benefit:** Cuts feel more intentional, synchronized to meaning not just rhythm.

### 5.3 Whisper Vocal Activity Detection (Without Transcription)

**Lightweight approach:**
```python
import whisper

model = whisper.load_model("tiny")  # Fastest
audio = whisper.load_audio(audio_path)

# Extract features without full transcription
mel = whisper.log_mel_spectrogram(audio)

# Detect vocal segments (simplified)
vocal_activity = []
for segment in mel.T:
    energy = np.sum(segment)
    is_vocal = energy > threshold  # Heuristic
    vocal_activity.append(is_vocal)
```

**Use case:** Place cuts at vocal ONSETS (when singer starts a phrase), not just bass onsets.

**Integration point:** In `_section_cut_candidates()`, add vocal onsets alongside bass onsets:
```python
if section_type in ["verse", "chorus"] and vocal_onsets:
    for onset in vocal_onsets:
        if start <= onset < end:
            candidates.append((onset, _CUT_VOCAL))  # New priority level
```

**Priority hierarchy update:** `_CUT_BOUNDARY`(2) > `_CUT_VOCAL`(2) > `_CUT_ONSET`(1) > `_CUT_GRID`(0)

**Rationale:** Vocal entrances are as important as section boundaries for viewer attention.

---

## 6. HOOK DETECTION

### 6.1 Identifying the Most Memorable Moment

**Audio features correlated with hooks:**

1. **Repetition:** Hook phrases repeat 2-4x in a song
2. **Energy peak:** Highest RMS/loudness section
3. **Bass density:** Most 808 onsets per bar
4. **Vocal prominence:** Vocal energy >> instrumental energy
5. **Simplicity:** Melodic contour less complex than verses

**What FlagshipEditor can detect NOW:**
- ✅ Energy peak (via RMS in `beat_analysis.py`)
- ✅ Bass density (via `bass_onsets` array)
- ⚠️ Vocal prominence (via Whisper, not implemented)
- ❌ Repetition detection (requires lyric/transcription analysis)
- ❌ Melodic simplicity (requires pitch tracking)

### 6.2 Hook Detection Algorithm (Implementable Now)

```python
def detect_hook(sections, energy_curve, bass_onsets):
    """Identify hook section by combining energy + bass density."""
    hook_score = {}
    
    for section in sections:
        sec_start = section['start']
        sec_end = section['end']
        sec_type = section['type']
        
        # Energy component
        sec_energy = np.mean([
            e for t, e in zip(energy_times, energy_curve)
            if sec_start <= t < sec_end
        ])
        
        # Bass density component
        bass_count = sum(1 for onset in bass_onsets if sec_start <= onset < sec_end)
        bass_density = bass_count / (sec_end - sec_start)
        
        # Repetition heuristic: chorus/drop appearing multiple times
        repetition_bonus = 1.5 if sec_type in ['chorus', 'drop'] else 1.0
        
        hook_score[sec_type] = sec_energy * bass_density * repetition_bonus
    
    # Highest score = hook
    hook_section = max(hook_score, key=hook_score.get)
    return hook_section
```

**Integration:** Run during `analyze_track()` in `beat_analysis.py`, store as `track_info['hook_section']`.

### 6.3 Clip Reservation Strategy

**Current behavior:** Best clips (highest composite score) assigned to earliest cuts, regardless of section importance.

**Problem:** By the time the hook arrives (75% through track), best clips already used 2-3 times.

**Recommended fix:** Reserve top clips for hook section.

```python
def select_best_clips_with_reservation(...):
    # Phase 1: Identify hook section
    hook_section = detect_hook(sections, energy, bass_onsets)
    
    # Phase 2: Partition clips into tiers
    scored_all = [(clip, score_clip(clip)) for clip in usable_clips]
    scored_all.sort(key=lambda x: -x[1]['composite'])
    
    tier_size = len(scored_all) // 3
    premium_tier = scored_all[:tier_size]      # Top 33%
    standard_tier = scored_all[tier_size:2*tier_size]
    utility_tier = scored_all[2*tier_size:]    # Bottom 33%
    
    # Phase 3: Assign clips
    for slot in slots:
        if slot['sectionType'] == hook_section:
            candidates = premium_tier  # Best clips for hook
        elif slot['sectionType'] in ['intro', 'outro']:
            candidates = utility_tier  # Save good clips for later
        else:
            candidates = standard_tier
        
        # Select from tier, respecting repeat rules
        best = select_from_tier(candidates, recent, preferred)
```

**Impact:** HIGH. Climactic sections get visually climactic shots.

---

## 7. CONCRETE IMPROVEMENTS — Ranked by Impact/Effort

### Priority 1: CRITICAL (Breaks in Edge Cases)

#### 7.1.1 Adaptive Repeat Window

**Problem:** `REPEAT_WINDOW=4` fails with <5 clips.

**Solution:**
```python
# In shot_selector.py, line 34
REPEAT_WINDOW_BASE = 4

def get_adaptive_repeat_window(usable_clips_count):
    if usable_clips_count < 3:
        return 1  # No meaningful restriction
    elif usable_clips_count < 6:
        return 2
    elif usable_clips_count < 10:
        return 3
    else:
        return REPEAT_WINDOW_BASE
```

**Modified function:**
```python
# In select_best_clips(), line 467
adaptive_window = get_adaptive_repeat_window(len(usable_clips))

def _eligible_indices(scored, recent, preferred, window_size):
    for window in range(window_size, 0, -1):
        # ... existing logic
```

**Data needed:** `len(usable_clips)` (already available)

**Processing time impact:** NEGLIGIBLE (<1ms)

**Test:** Run with 2, 4, 8, 20 clips. Verify no IndexError, edit completes.

---

#### 7.1.2 Energy Matching Bonus

**Problem:** High-energy drops get low-energy clips because composition score dominates.

**Solution:**
```python
# Add to shot_selector.py
SECTION_ENERGY_TARGETS = {
    "intro": 0.2, "verse": 0.4, "chorus": 0.7,
    "drop": 0.9, "bridge": 0.3, "outro": 0.2
}

def energy_match_bonus(clip_energy_score, section_type):
    target = SECTION_ENERGY_TARGETS.get(section_type, 0.5)
    clip_normalized = clip_energy_score / 100.0
    delta = abs(clip_normalized - target)
    return (1.0 - delta) * 15.0  # Max +15 points
```

**Integration in `score_clip()`:**
```python
# After line 132 (composite calculation)
energy_match = energy_match_bonus(scores["energy"], section_type)
composite += energy_match
```

**Data needed:** `clip_info["motion_intensity"]`, `clip_info["motion_variance"]` (already computed)

**Processing time impact:** NEGLIGIBLE

**Test:** Compare clip assignments before/after on a track with clear drop section.

---

### Priority 2: HIGH (Quality Improvements)

#### 7.2.1 Hook Detection + Clip Reservation

**Problem:** Best clips used early, hook section gets leftovers.

**Solution:** Implement tier-based reservation (see 6.3).

**Functions to modify:**
- `select_best_clips()` (major refactor)
- Add `detect_hook_section(sections, energy_curve, bass_onsets)` to `beat_analysis.py`

**Data needed:**
- `energy_curve` from `beat_analysis.py` (already returned)
- `bass_onsets` (already passed to `select_best_clips`)
- Section boundaries (already available)

**Processing time impact:** LOW (~50ms for hook detection)

**Test:** Verify hook section (usually final chorus/drop) gets highest-average-score clips.

---

#### 7.2.2 Recency Penalty for Scene Types

**Problem:** Same scene type can appear consecutively if scores are high enough.

**Solution:**
```python
def scene_recency_penalty(clip_scene_type, recent_clips_info):
    penalty = 0.0
    recent_scene_types = [c.get("scene_type") for c in recent_clips_info[-3:]]
    
    # Same scene type twice in last 3 cuts
    if recent_scene_types.count(clip_scene_type) >= 2:
        penalty += 10.0
    
    # Three different scene types in last 3 cuts = variety bonus
    if len(set(recent_scene_types)) == 3:
        penalty -= 5.0  # Reward variety
    
    return penalty
```

**Integration:** Apply in scoring loop, similar to `OVERUSE_PENALTY`.

**Data needed:** `recent_clips_info` (track last 3 selected clips' metadata)

**Processing time impact:** NEGLIGIBLE

**Test:** Count scene type repetitions in output. Should decrease.

---

#### 7.2.3 Cut Pattern Support

**Problem:** Every bar in a chorus has identical cut rhythm (1 cut/beat).

**Solution:** Add `cut_pattern` to style_config:
```json
{
  "cut_strategy": {
    "chorus": {
      "pattern": [0.5, 0.5, 1.0, 0.5, 0.5, 2.0],
      "pattern_offset": 0  // Start at bar 1
    }
  }
}
```

**Modified `_section_cut_candidates()`:**
```python
strategy = ((style_config or {}).get("cut_strategy") or {}).get(section_type) or {}
pattern = strategy.get("pattern")

if pattern:
    # Walk pattern instead of fixed interval
    pattern_index = 0
    position = 0.0
    while position < limit:
        interval = pattern[pattern_index % len(pattern)]
        candidates.append((_beat_position(beats, first_index + position, period), _CUT_GRID))
        position += interval
        pattern_index += 1
else:
    # Existing fixed-interval logic
```

**Data needed:** Style config (user-provided)

**Processing time impact:** NEGLIGIBLE

**Test:** Create style with pattern `[0.5, 0.5, 1.0]`. Verify cuts follow pattern.

---

### Priority 3: MEDIUM (Advanced Features)

#### 7.3.1 Whisper Vocal Activity Detection

**Problem:** Cuts ignore vocal entrances.

**Solution:**
```python
# New function in beat_analysis.py
def detect_vocal_onsets(audio_path, tempo):
    import whisper
    model = whisper.load_model("tiny")
    audio = whisper.load_audio(audio_path)
    
    # Simplified: detect energy spikes in vocal frequency range (300Hz-3kHz)
    # Full implementation would use transcription with word_timestamps=True
    
    vocal_onsets = []
    # ... detection logic
    return vocal_onsets
```

**Integration:** Pass `vocal_onsets` to `plan_cuts()`, add `_CUT_VOCAL` priority.

**Data needed:** Audio file path (already available)

**Processing time impact:** HIGH (~10-30s per track on CPU)

**Mitigation:** Cache results in `beat_analysis.sqlite3` (cache infrastructure exists)

**Test:** Compare cut placements with/without vocal onsets enabled.

---

#### 7.3.2 Lyric Phrase Alignment

**Problem:** Cuts don't align to lyric boundaries.

**Prerequisites:** 
- Musixmatch API key (licensing required)
- OR Whisper transcription with word timestamps

**Implementation:** Similar to 7.3.1, but parse lyric text + timestamps.

**Processing time impact:** HIGH (API call or transcription)

**Recommendation:** Defer until vocal activity detection proven valuable.

---

### Priority 4: LOW (Polish)

#### 7.4.1 Dynamic Section Max Beats

**Current:** `SECTION_MAX_BEATS` is static (e.g., chorus always 2.0 beats max).

**Improvement:** Scale based on track length:
```python
def adaptive_max_beats(section_type, track_duration):
    base = SECTION_MAX_BEATS.get(section_type, 4.0)
    if track_duration > 240:  # Long track
        return base * 0.8  # Faster cuts to maintain interest
    elif track_duration < 120:  # Short track
        return base * 1.2  # Slower cuts to extend footage
    return base
```

**Impact:** Minor quality improvement.

---

## Summary Table

| Improvement | Priority | Impact | Effort | Processing Cost | Test Method |
|-------------|----------|--------|--------|-----------------|-------------|
| Adaptive repeat window | P1 | HIGH | LOW | None | 2-4 clip library |
| Energy matching bonus | P1 | HIGH | LOW | None | Drop section analysis |
| Hook detection + reservation | P2 | HIGH | MEDIUM | ~50ms | Clip score distribution |
| Scene recency penalty | P2 | MEDIUM | LOW | None | Scene type count |
| Cut pattern support | P2 | MEDIUM | MEDIUM | None | Pattern verification |
| Whisper vocal onsets | P3 | MEDIUM | HIGH | 10-30s | Cut placement shift |
| Lyric phrase alignment | P3 | LOW | HIGH | API/transcription | Lyric boundary check |
| Dynamic max beats | P4 | LOW | LOW | None | Track length variance |

---

## Validation Notes

**Claims validated from code:**
- ✅ Cut planning architecture (lines 297-378)
- ✅ Priority system implementation (lines 256-265, 267-282)
- ✅ Scoring weights per section (lines 14-54)
- ✅ Clip usage penalty (lines 480-484)
- ✅ Short clip penalty (lines 487-491)
- ✅ Best moment window extraction (lines 441-457)
- ✅ Section normalization (lines 152-178)

**Claims based on editing theory (not code-validated):**
- Narrative arc structure (industry standard)
- Phrasing patterns (canonical knowledge)
- Hook detection heuristics (music theory)
- MVX AI workflow (UNABLE TO VERIFY—web search disabled)

**Recommendations requiring external validation:**
- Musixmatch API pricing/terms
- Whisper transcription accuracy on French/Creole lyrics
- Commercial licensing for synced lyrics

---

## Next Steps

1. **Immediate (P1):** Implement adaptive repeat window + energy matching
2. **Short-term (P2):** Add hook detection + clip reservation
3. **Medium-term (P3):** Prototype Whisper vocal detection
4. **Long-term:** Evaluate lyric API integration

**Testing protocol:** For each change, run A/B comparison on 3 tracks (short/medium/long) with 10/50/200 clip libraries. Measure:
- Visual variety (scene type entropy)
- Energy alignment (clip motion vs section intensity correlation)
- User preference (blind test)
