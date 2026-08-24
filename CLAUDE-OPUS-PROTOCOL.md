# CLAUDE OPUS — FLAGSHIP EDITOR BUILD PROTOCOL
## For Claude Code Opus 4.1 with Max Effort + Thinking Activated in VS Code

---

## IDENTITY & CONTEXT

You are Claude Opus 4.1 operating inside VS Code with Claude Code, max effort mode, thinking activated. You have been assigned the task of building **FlagshipEditor** — an AI-powered music video editor plugin for Adobe After Effects.

This is not a toy project. This is a commercial product that will compete with MVX (mvx.io), AutoEdit, and BeatEdit. It must work flawlessly on Windows 10/11 with After Effects 2024+.

**The project is located at:**
```
/Users/issandre/.openclaw/workspace/projects/flagshipeditor/
```

**The team:**
- **Issandre Maccotta** — product owner, designer, brand strategist
- **HeliMAn (BandzMadeHer)** — developer, builds and tests on native Windows/AE
- **You (Claude Opus)** — lead engineer for this session

---

## WHAT FLAGSHIPEditor IS

FlagshipEditor is a CEP (Common Extensibility Platform) extension for Adobe After Effects that:

1. **Imports media** (video clips + music track)
2. **Analyzes the music** (beat detection, tempo, key, sections, energy) using a Python backend (librosa)
3. **Analyzes the clips** (scene type, face detection, brightness, motion intensity, composition, sharpness) using OpenCV
4. **Selects the best shots** for each beat using an AI shot selector (6-criteria scoring: composition, energy, variety, sharpness, stability, face quality)
5. **Builds a composition in After Effects** automatically — placing clips on the timeline at beat positions, applying VFX, color grading, and section markers
6. **Allows review and swap** — users can review each cut, swap clips, lock cuts, regenerate sections
7. **Supports 6 style presets** (CMD COMMAND UK Drill, Lyrical Lemonade, Jack Rottier, Ninetive, Worldwide Films, Custom)
8. **Applies 24 VFX effects** programmatically (zoom punch, camera shake, whip pan, glitch, speed ramp, freeze frame, face mask, smoke/fog, slow-mo, beat flash, light leaks, VHS overlay, film grain, letterbox, depth blur, smooth transitions, mask transition, picture flash, selective color, slow push in, RGB split, strobe, light wrap, Element 3D)

---

## CURRENT ARCHITECTURE

### Tech Stack
- **Frontend:** React 18 + TypeScript, built with Vite + bolt-cep
- **CEP Panel:** HTML/CSS/JS rendered in Chromium embedded (no Node.js in CEP — causes crashes)
- **ExtendScript:** TypeScript compiled to ES3, runs inside After Effects
- **Python Backend:** FastAPI server on localhost:18791, handles beat analysis (librosa) and clip analysis (OpenCV)
- **Build:** Vite + bolt-cep → ZXP package for Adobe

### File Structure (key files only)
```
flagshipeditor/
├── cep.config.ts                    # CEP extension config (manifest, hosts, panels)
├── package.json                      # Dependencies (React 18, bolt-cep, Vite)
├── src/
│   ├── js/
│   │   ├── main/
│   │   │   ├── App.tsx               # Main React app (6 tabs: Media, Style, Params, 3D, Review, Analysis)
│   │   │   ├── index.tsx             # React entry point
│   │   │   ├── index.html            # Panel HTML
│   │   │   ├── styles.css            # All CSS (dark theme, sidebar layout)
│   │   │   ├── lib/
│   │   │   │   ├── bolt.ts           # CEP evalScript wrapper
│   │   │   │   ├── python.ts         # Python backend API client
│   │   │   │   ├── CSInterface.js    # Adobe CEP bridge
│   │   │   │   └── styles.ts         # Style preset loader
│   │   │   └── components/
│   │   │       ├── MediaImport.tsx   # File/folder import UI
│   │   │       ├── StyleSelector.tsx # 6 style presets
│   │   │       ├── Parameters.tsx    # VFX intensity sliders
│   │   │       ├── Element3DPanel.tsx# 3D parallax settings
│   │   │       ├── AnalysisView.tsx  # Beat/clip analysis display
│   │   │       └── ReviewMode.tsx    # Cut review/swap/lock
│   ├── jsx/
│   │   ├── index.ts                  # ExtendScript entry (publishes bridge functions)
│   │   ├── lib/json2.js              # JSON polyfill for ES3
│   │   └── aeft/
│   │       ├── aeft.ts               # Main AE bridge (beginComp, appendCutBatch, finishComp, swapCut, replaceSectionCuts)
│   │       ├── vfx_engine.ts         # 24 VFX effect implementations
│   │       ├── color_grading.ts      # Lumetri Color / LUT application
│   │       └── element_3d.ts         # Element 3D solid + camera setup
│   └── settings/                     # Settings panel
├── engine/                           # Python backend
│   ├── server.py                     # FastAPI server (localhost:18791)
│   ├── beat_analysis.py             # librosa beat detection
│   ├── clip_analysis.py             # OpenCV clip classification
│   ├── shot_selector.py             # AI shot selection (6-criteria scoring)
│   ├── analysis_jobs.py             # SQLite-backed async job system
│   └── self_test.py                 # Engine self-diagnostics
├── styles/                           # Style preset JSON files
│   ├── cmd_command_drill.json
│   ├── lyrical_lemonade.json
│   ├── jack_rottier.json
│   ├── ninetive.json
│   ├── worldwide_films.json
│   └── custom.json
├── luts/                             # 7 custom LUT files (.cube)
├── scripts/                          # Build + test scripts
├── CSXS/                             # CEP manifest (generated)
├── dist/                             # Build output
└── GAP-REPORT.md                     # Comprehensive audit (READ THIS)
```

### How It Works (flow)
1. User opens FlagshipEditor panel in AE (Window > Extensions > FlagshipEditor)
2. User imports clips (file picker or folder scan) and selects a music track
3. User clicks "GENERATE EDIT"
4. React calls Python backend:
   - `POST /analyze/beat` → librosa analyzes music → returns {tempo, beats[], downbeats[], sections[], energy[], bass_onsets[], hihat_onsets[], key, mode, duration}
   - `POST /analyze/clip` (per clip, async via SQLite job queue) → OpenCV analyzes → returns {scene_type, has_face, brightness, motion_intensity, composition_score, sharpness_score, histogram, thumbnail_id}
   - `POST /select-shots` → shot_selector.py scores clips per section → returns cut decisions
5. React calls ExtendScript via `evalScript`:
   - `beginComp(duration, audioPath, styleConfig, params, element3D, sections, extensionPath)` → creates comp, imports audio, sets up undo group
   - `appendCutBatch(cuts[])` → adds clips to comp at beat positions, applies VFX per layer
   - `finishComp()` → applies color grading, Element 3D, section markers, opens comp
6. User reviews cuts in the Review tab, can swap/lock/regenerate

---

## KNOWN BUGS & GAPS (from GAP-REPORT.md)

### CRITICAL — Must Fix Before Anything Else

1. **19 of 24 VFX effects are STUBS** — `appendUnsupportedEffectWarnings()` in `aeft.ts` has an empty `unsupported` array, but the GAP-REPORT found 19 effects declared in style JSONs that were never called from `applyVFXToLayer()`. The code in `vfx_engine.ts` HAS implementations for all 24 effects, but the routing in `aeft.ts` was missing calls to: `speed_ramp`, `freeze_frame`, `face_mask`, `smoke_fog`, `slow_mo`, `beat_flash`, `light_leaks`, `vhs_overlay`, `film_grain`, `letterbox`, `depth_blur`, `smooth_transitions`, `mask_transition`, `picture_flash`, `selective_color`, `slow_push_in`, `rgb_split`, `strobe`, `light_wrap`.

   **FIX:** The `applyVFXToLayer()` function in `aeft.ts` already has routing for all 24 effects (verified in the current source). The `appendUnsupportedEffectWarnings()` function should be removed or its array kept empty. Verify that ALL 24 effects are actually routed.

2. **applyZoomPunch** — No easing curves (linear, not punchy). Scale arrays are 2D but may need 3D for 3D layers. No randomization.

3. **applyCameraShake** — `wiggle()` expression applies for entire layer duration, not bounded to section. No decay. Expressions are slow with many layers.

4. **applyWhipPan** — Only animates position X. Missing rotation keyframes (already added in current code but verify). Comp motion blur toggle not enabled.

5. **applyGlitch** — RGB split via Shift Channels works but opacity keyframes at 100%→100% do nothing. Should animate effect intensity, not layer opacity. Effect not time-bounded — persists for entire layer.

6. **applySpeedRamp** — `rampDur` uses `60/30` hardcoded instead of actual FPS. No ease into/out of speed change.

7. **applyFreezeFrame** — No transition in/out of freeze. Clip jumps.

8. **Color Grading** — Lumetri Color match name may differ on older AE versions. LUT file path uses hardcoded forward slash. Opacity capping logic is wrong. `applyColorParams` finds `comp.layer(1)` which may not be the LUT layer.

9. **Element 3D** — No actual Element 3D effect application (just creates solid + camera). No detection of whether Element 3D is installed. Parallax expression is random wiggle, not controlled parallax.

10. **Comp Builder** — No FPS detection from footage (hardcoded 30). No resolution detection (hardcoded 1920x1080). Both are partially implemented but fragile.

11. **Python Backend** — Server must be started manually. No auto-start from CEP. No health check retry logic. FFprobe/FFmpeg paths not validated on Windows.

12. **Build/Packaging** — ZXP signing is self-signed. No installer for macOS. Windows installer is CMD-based (not MSIX). No auto-update mechanism.

---

## YOUR MISSION

Build a **production-ready, commercial-grade** FlagshipEditor that:
1. Works flawlessly on Windows 10/11 with After Effects 2024+
2. All 24 VFX effects are implemented, routed, and produce visible results
3. The Python backend auto-starts and is robust
4. The UI is polished, responsive, and professional
5. The code is clean, typed, and maintainable
6. No crashes, no silent failures, no stubs

---

## PROTOCOL — STEP BY STEP

### Phase 1: Audit & Understand (30 min max)

1. Read EVERY file in the project. Start with:
   - `GAP-REPORT.md` — the full audit
   - `src/jsx/aeft/aeft.ts` — the AE bridge
   - `src/jsx/aeft/vfx_engine.ts` — all 24 VFX
   - `src/jsx/aeft/color_grading.ts` — color grading
   - `src/jsx/aeft/element_3d.ts` — Element 3D
   - `src/js/main/App.tsx` — main React app
   - `src/js/main/lib/python.ts` — Python API client
   - `src/js/main/lib/bolt.ts` — CEP bridge
   - `engine/server.py` — Python backend
   - `engine/beat_analysis.py` — beat detection
   - `engine/clip_analysis.py` — clip analysis
   - `engine/shot_selector.py` — shot selection
   - `engine/analysis_jobs.py` — job system
   - All 6 style JSON files in `styles/`
   - `cep.config.ts` — CEP config
   - `package.json` — dependencies

2. Create a checklist of every issue found in GAP-REPORT.md and every issue you discover yourself.

3. DO NOT start coding until you have read every file and understand the full system.

### Phase 2: Fix ExtendScript (aeft.ts + vfx_engine.ts + color_grading.ts + element_3d.ts)

This is the most critical phase. The ExtendScript runs inside After Effects and must be ES3-compatible, error-tolerant, and performant.

**Rules for ExtendScript:**
- NO arrow functions (`=>`)
- NO `const` or `let` — use `var` only
- NO template literals (backticks)
- NO `for...of` loops — use `for (var i = 0; i < arr.length; i++)`
- NO `Array.prototype.map/filter/reduce` — use manual loops
- NO destructuring
- NO default parameters
- NO `async/await` — ExtendScript is synchronous
- NO `JSON.parse` without json2.js polyfill (already included)
- All function calls to AE DOM must be wrapped in try/catch
- All return values must be JSON strings with `{ __result: ... }` or `{ __error: "..." }`
- Use `app.beginUndoGroup()` / `app.endUndoGroup()` for all modifications
- Clean up on error — remove any created items if the operation fails

**Fixes required:**

2.1. **Verify all 24 VFX are routed in `applyVFXToLayer()`** — check that every effect in the style JSONs has a corresponding `if (style.effect_name && style.effect_name.enabled)` block. If any are missing, add them.

2.2. **Fix applyZoomPunch:**
- Add bezier easing with proper ease-in/ease-out handles (not just `BEZIER` interpolation type — set actual temporal ease values)
- Check if layer is 3D and use `[scale, scale, scale]` if so
- Add randomization: vary `scale_target` by ±10% per call using `Math.random()`
- Add variation in duration: vary `durIn` and `durOut` by ±2 frames

2.3. **Fix applyCameraShake:**
- Replace `wiggle()` expression with keyframe-based shake for performance (generate 20-30 position keyframes with random offsets)
- Time-bound the shake to the section duration, not the entire layer
- Add exponential decay: amplitude decreases over the shake duration
- Use `config.decay_factor` (default 0.85) to control decay

2.4. **Fix applyWhipPan:**
- Verify rotation keyframes are present (they are in current code)
- Enable comp motion blur: `layer.containingComp.motionBlur = true`
- Add direction randomization: `direction = Math.random() > 0.5 ? 1 : -1` (unless config.direction is explicitly set)

2.5. **Fix applyGlitch:**
- Animate the RGB split layer OPACITY from 100→0 (not 100→100)
- Time-bound the displacement map effect: keyframe `ADBE Displacement Map-0001` and `ADBE Displacement Map-0002` from `maxOffset` to `0` over `durFrames`
- Add randomization to displacement offset: `maxOffset * (0.7 + Math.random() * 0.6)`

2.6. **Fix applySpeedRamp:**
- Replace hardcoded `60/30` with actual FPS from parameter
- Add bezier easing on time remap keyframes for smooth speed transitions
- Add ease-in: slow ramp from 100% to target speed, not instant jump

2.7. **Fix applyFreezeFrame:**
- Add smooth transition into freeze: 2-frame ease from normal speed to frozen
- Add smooth transition out of freeze: 2-frame ease from frozen to normal speed

2.8. **Fix color_grading.ts:**
- Use `File()` constructor for LUT path to handle cross-platform paths
- Try `"ADBE Lumetri Color"` first, fall back to `"ADBE Lumetri Color 2"`, then `"ADBE Color Balance"`
- Track the LUT adjustment layer by name ("FlagshipEditor_LUT") instead of `comp.layer(1)`
- Apply color params (temperature, contrast, saturation) to the LUT layer specifically, not whatever is on top

2.9. **Fix element_3d.ts:**
- Check if Element 3D is installed by searching for the effect match name `"Video Copilot Element 3D"` in a temp comp
- If installed, apply the effect to the solid
- If not installed, add a warning to the build warnings and skip (don't create the solid)
- Replace `wiggle(0.5, depth * 100)` with a controlled parallax expression: `transform.position + [0, 0, Math.sin(time * 0.5) * depth * 50]`
- Make camera zoom proportional to comp size: `comp.width * 1.05` instead of hardcoded `2000`

2.10. **Fix aeft.ts comp builder:**
- FPS detection: iterate through all project items to find the first footage item with a valid `frameRate` (not just `project.item(1)`)
- Resolution detection: same — find first footage with valid `width` and `height`
- Add `app.scheduleTask()` fallback for long operations to prevent AE UI freeze
- Batch clip imports: group `appendCutBatch` calls to max 30 clips per `evalScript` call to prevent timeout

### Phase 3: Fix Python Backend (engine/)

3.1. **Auto-start from CEP:**
- In `python.ts`, add `startPythonServer()` that:
  - Finds the bundled Python executable (Windows: `runtime/python/python.exe`, macOS: system Python)
  - Finds `server.py` relative to the extension path
  - Spawns it as a child process with `--headless` flag
  - Waits up to 10 seconds for health check to pass
  - Returns true/false

3.2. **Robust health checking:**
- Retry health check 3 times with 1-second delay before declaring failure
- Show specific error message: "Python not found", "FFmpeg not found", "Port in use", etc.

3.3. **FFmpeg/FFprobe path resolution:**
- On Windows: check `runtime/ffmpeg/ffmpeg.exe` and `runtime/ffmpeg/ffprobe.exe` first
- Fall back to system PATH
- Validate with `--version` call at startup
- Log which paths are used

3.4. **Beat analysis improvements:**
- Add timeout: if librosa takes > 60 seconds, return error
- Add progress reporting via WebSocket or polling (for large files)

3.5. **Clip analysis improvements:**
- Batch processing: process clips in parallel (max 4 concurrent)
- Add timeout per clip: 120 seconds max
- Better error messages: "Corrupt video file", "Unsupported codec", "No video stream"

3.6. **Shot selector improvements:**
- Add "avoid repeat" logic: don't use the same clip within 3 cuts (already partially implemented)
- Add section-aware selection: verse sections prefer face clips, chorus prefers high-energy clips, bridge prefers B-roll
- Add randomness factor: 20% chance to pick a non-top clip for variety

### Phase 4: Fix React UI (App.tsx + components)

4.1. **Loading states:**
- Show skeleton/spinner during analysis
- Disable Generate button until clips AND audio are loaded
- Show clip thumbnails in MediaImport (use thumbnail_id from analysis)

4.2. **Error handling:**
- Show toast/error messages for all failed operations
- Retry button for failed clip analyses
- Clear error state when user takes corrective action

4.3. **Review Mode:**
- Show thumbnail for each cut
- Show section type badge (VERSE, CHORUS, BRIDGE, etc.)
- Drag-to-reorder cuts
- Multi-select for batch swap

4.4. **Parameters tab:**
- Add per-effect toggles (not just global VFX intensity)
- Add "Random seed" input for reproducible results
- Add "Beat subdivision" selector (1/4, 1/8, 1/16)

4.5. **Style tab:**
- Show preview image for each style
- Show which VFX effects are included in each style
- Allow style customization (edit JSON in-panel)

### Phase 5: Build & Package

5.1. **Build the ZXP:**
```bash
npm run zxp
```

5.2. **Test the build:**
- Verify `dist/cep/` contains all files
- Verify `CSXS/manifest.xml` is correct
- Verify JSX is compiled to ES3
- Verify no Node.js in CEP (must be browser-only JS)

5.3. **Create Windows installer:**
- Use the existing `scripts/package-windows.mjs`
- Bundle Python 3.12.10 embedded distribution
- Bundle FFmpeg + FFprobe
- Bundle all Python dependencies (librosa, opencv-python, fastapi, uvicorn, numpy)
- Create self-extracting EXE

5.4. **Verify SHA-256 checksums**

### Phase 6: Testing

6.1. **Unit tests:**
- Run `npm run test:ae-bridge` — verify ExtendScript compiles
- Run `npm run test:engine-contracts` — verify Python engine
- Run `npm run test:analysis-jobs` — verify job system
- Run `npm run test:prores` — verify ProRes handling

6.2. **Integration tests:**
- Start Python server, verify health
- Run beat analysis on a test audio file
- Run clip analysis on a test video file
- Run shot selection
- Verify JSON output format

6.3. **UI tests:**
- Load panel in browser (dev mode)
- Verify all 6 tabs render
- Verify Generate button works
- Verify Cancel works
- Verify Review mode shows cuts

6.4. **Build tests:**
- Verify ZXP packages correctly
- Verify all files present in ZXP
- Verify manifest is valid

---

## CRITICAL RULES — NO MISTAKES ALLOWED

### Code Quality
1. **Every function must have error handling.** try/catch in ExtendScript, try/except in Python, error boundaries in React.
2. **Every return value must be validated.** Check for null, undefined, NaN, empty arrays.
3. **No silent failures.** If something fails, log it, show it, return an error. Never swallow an error.
4. **No stubs.** No `// TODO`, no `// implement later`, no `console.log("not implemented")`. If you write a function, it works. Fully.
5. **No placeholder values.** No hardcoded test data. No "Lorem ipsum". Real values from real data.
6. **No unused variables.** Clean code. If you declare it, use it. If you don't need it, delete it.
7. **No inconsistent naming.** camelCase for JS/TS, snake_case for Python. Be consistent.
8. **Every file must end with a newline.** No trailing whitespace.

### ExtendScript Specific
9. **ES3 only.** No ES6+ features. If you're unsure, don't use it.
10. **No `JSON` object without polyfill.** json2.js is included — make sure it's loaded before any JSON.parse/JSON.stringify.
11. **All AE DOM calls in try/catch.** After Effects can throw at any time. Protect every call.
12. **Undo groups must be balanced.** Every `beginUndoGroup` must have a matching `endUndoGroup`, even on error.

### React Specific
13. **No inline styles.** Use CSS classes from styles.css.
14. **No `any` types.** Type everything properly.
15. **All async operations must have error handling and loading states.**
16. **All state updates must be immutable.** Never mutate state directly.

### Python Specific
17. **All functions must have type hints.**
18. **All functions must have docstrings.**
19. **All external calls (subprocess, file I/O) must have timeouts.**
20. **All paths must be cross-platform (use pathlib.Path).**

### Build Specific
21. **Never break the build.** After every change, verify `npm run build` succeeds.
22. **Never commit broken code.** Run tests before committing.
23. **Never change cep.config.ts without understanding the consequences.** The CEP manifest is critical.

---

## NO TOKENS WASTED

- Do not explain what you're about to do. Just do it.
- Do not write comments that explain obvious code.
- Do not create documentation files unless asked.
- Do not create test files unless asked.
- Do not create helper files unless needed.
- Every line of code you write must serve the product.
- If you're unsure about something, read the file again instead of guessing.
- Use `git diff` to review your changes before committing.
- Work in logical order: ExtendScript first, then Python, then React, then build.

---

## SUCCESS CRITERIA

The task is complete when:

1. ✅ All 24 VFX effects are implemented and routed in `applyVFXToLayer()`
2. ✅ `applyZoomPunch` has bezier easing, randomization, and 3D layer support
3. ✅ `applyCameraShake` uses keyframes (not expressions), is time-bounded, and has decay
4. ✅ `applyWhipPan` has rotation, motion blur on comp, and direction randomization
5. ✅ `applyGlitch` has correct opacity animation and time-bounded displacement
6. ✅ `applySpeedRamp` uses actual FPS and has smooth easing
7. ✅ `applyFreezeFrame` has smooth transitions in/out
8. ✅ Color grading handles multiple Lumetri match names and tracks the LUT layer
9. ✅ Element 3D detects if plugin is installed and applies effect if available
10. ✅ Comp builder detects FPS and resolution from footage
11. ✅ Python backend auto-starts from CEP panel
12. ✅ Health check has retry logic
13. ✅ FFmpeg/FFprobe paths are validated at startup
14. ✅ Shot selector has section-aware selection and variety logic
15. ✅ React UI has proper loading states, error handling, and review mode with thumbnails
16. ✅ `npm run build` succeeds with no errors
17. ✅ `npm run zxp` produces a valid ZXP
18. ✅ All existing tests pass
19. ✅ No `any` types in TypeScript
20. ✅ No ES6+ in ExtendScript files
21. ✅ No silent failures anywhere in the codebase

---

## START

Read every file in the project. Then fix everything. Don't stop until all 21 success criteria are met.

This is a commercial product. It must work. No excuses.