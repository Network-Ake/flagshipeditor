# FlagshipEditor — Comprehensive Gap Report

**Audit date:** 2026-08-22
**Version audited:** 0.1.8
**Files reviewed:** 30 source files + 2 research documents
**Auditor:** Automated deep audit for production-grade readiness

---

## Table of Contents

1. [ExtendScript Gaps](#1-extendscript-gaps)
2. [React/UI Gaps](#2-reactui-gaps)
3. [Python Engine Gaps](#3-python-engine-gaps)
4. [CEP/Build Gaps](#4-cepbuild-gaps)
5. [Commercial Gaps](#5-commercial-gaps)
6. [Architecture Gaps](#6-architecture-gaps)
7. [Documentation Gaps](#7-documentation-gaps)
8. [Priority Summary](#8-priority-summary)

---

## 1. ExtendScript Gaps

### 1.1 Unimplemented VFX (19 effects declared in styles, only 4 implemented)

**CRITICAL — The majority of style-preset effects are declared in JSON but never executed.**

The `appendUnsupportedEffectWarnings()` function in `aeft.ts` explicitly lists 19 unimplemented effects that are silently skipped:

| Effect | Declared In Styles | Implementation Status |
|--------|-------------------|----------------------|
| `face_mask` | cmd_command_drill | **STUB** — warning only |
| `smoke_fog` | cmd_command_drill | **STUB** — warning only |
| `slow_mo` | cmd_command_drill | **STUB** — warning only |
| `beat_flash` | cmd_command_drill | **STUB** — warning only |
| `light_leaks` | lyrical_lemonade | **STUB** — warning only |
| `vhs_overlay` | lyrical_lemonade | **STUB** — warning only |
| `film_grain` | jack_rottier | **STUB** — warning only |
| `letterbox` | jack_rottier | **STUB** — warning only |
| `depth_blur` | ninetive | **STUB** — warning only |
| `smooth_transitions` | (declared) | **STUB** — warning only |
| `mask_transition` | worldwide_films | **STUB** — warning only |
| `picture_flash` | (declared) | **STUB** — warning only |
| `selective_color` | (declared) | **STUB** — warning only |
| `slow_push_in` | (declared) | **STUB** — warning only |
| `rgb_split` | worldwide_films | **STUB** — warning only |
| `strobe` | worldwide_films | **STUB** — warning only |
| `light_wrap` | (declared) | **STUB** — warning only |
| `speed_ramp` | cmd_command_drill | **PARTIAL** — `applySpeedRamp()` exists in vfx_engine.ts but is never called from `applyVFXToLayer()` |
| `freeze_frame` | cmd_command_drill | **PARTIAL** — `applyFreezeFrame()` exists in vfx_engine.ts but is never called from `applyVFXToLayer()` |

**Impact:** Users select a style like "CMD COMMAND — UK Drill" expecting face masking, smoke/fog, slow-mo, and beat flashes. They get a warning in the task issues panel instead. This is the biggest gap between promised and delivered functionality.

### 1.2 VFX Engine Issues (`vfx_engine.ts`)

**applyZoomPunch:**
- No easing curves applied — `setInterpolationTypeAtKey` is called in a try/catch but no specific ease handles are set. The zoom will feel linear and mechanical, not punchy.
- Scale values are 2D arrays `[100, 100]` but AE scale property may need `[100, 100, 100]` for 3D layers. No dimension check.
- No randomization or variation — every zoom punch is identical. Real music videos vary intensity.

**applyCameraShake:**
- Uses `wiggle()` expression string — this is fine but expressions are slow in AE, especially with many layers. No keyframe-based alternative for performance.
- No time bounding — the wiggle expression applies for the entire layer duration, not just the section. Should be bounded to the section's time range.
- No decay — real camera shake decays over time. `wiggle()` is constant amplitude.

**applyWhipPan:**
- Only animates position X — a real whip pan also involves rotation and motion blur. Missing rotation keyframes.
- No direction variation — always pans from left. Should alternate or randomize direction.
- `layer.motionBlur = true` enables the switch but doesn't enable motion blur for the **comp**. The comp's motion blur toggle must also be on.

**applyGlitch:**
- RGB Split via `ADBE Shift Channels` is incorrect — Shift Channels remaps channels but doesn't create a chromatic aberration split. Should use `ADBE Displacement Map` with offset or duplicate layers with channel offsets.
- No time-bounded effect animation — the displacement and RGB split are applied but not keyframed to disappear after the 808 hit. The effect persists for the entire layer.
- Opacity keyframes are set but at 100%→100% — this does nothing. Should animate the effect's intensity parameter, not layer opacity.

**applySpeedRamp (implemented but unused):**
- `rampDur` calculation uses `60/30` hardcoded instead of actual FPS. Should use the `fps` parameter.
- No ease into/out of speed change — linear time remap creates jarring motion.

**applyFreezeFrame (implemented but unused):**
- Correctly sets time remap to freeze, but doesn't handle the transition in/out of the freeze. The clip will jump.

### 1.3 Color Grading Issues (`color_grading.ts`)

- **Lumetri Color match name:** Uses `"ADBE Lumetri Color"` — this is correct for AE 2024+, but no fallback for older versions that use `"ADBE Lumetri Color 2"` or the legacy `"ADBE Color Balance"`.
- **LUT file path:** Uses `extensionRoot + "/luts/" + lutName` — hardcoded forward slash. On Windows, `extensionRoot` may use backslashes. Should use `File()` constructor to normalize.
- **Opacity capping:** `config.opacity` is set to `params.colorGrading * 10` in `aeft.ts`, giving a range of 0–100. But `applyColorParams()` tries to set temperature/contrast/saturation on the **top layer** which may not be the LUT layer if multiple adjustment layers exist.
- **No section-specific params:** `config.params` (temperature, contrast, saturation) are global, not per-section. The style JSON declares them globally but users may want different grading per section.
- **applyColorParams** finds `comp.layer(1)` — this is the topmost layer, which may not be the LUT adjustment layer if layers were added after. Should track the LUT layer reference.

### 1.4 Element 3D Issues (`element_3d.ts`)

- **No actual Element 3D effect application:** The code creates a solid and a camera but does NOT apply the Element 3D effect. The user is told to do it manually. This is a major workflow gap — the plugin should at least attempt to apply the effect if Element 3D is installed.
- **No Element 3D detection:** No check for whether the Element 3D plugin is actually installed. The solid is created regardless.
- **Parallax expression:** `wiggle(0.5, depth * 100)` is applied to camera position — this is a random wiggle, not a controlled parallax. Real parallax requires linked position expressions with depth offset.
- **No 3D model loading:** No mechanism to load or configure 3D models. The style JSON has no model path field.
- **Camera zoom hardcoded:** `2000` — no relation to comp size or desired framing.

### 1.5 Comp Builder Issues (`aeft.ts`)

- **Hardcoded FPS:** `30` is used everywhere (`addComp` calls, VFX calculations). No detection of the project's frame rate or the footage's native FPS. If the project is 24fps or 25fps, all timing will be wrong.
- **Hardcoded resolution:** `1920, 1080` — no option for 4K, vertical (1080×1920), or square (1080×1080) formats. Modern music videos are often vertical for TikTok/Reels.
- **No undo group:** All operations are wrapped in try/catch but not in `app.beginUndoGroup()`/`app.endUndoGroup()`. If something fails mid-build, the user can't undo cleanly — they have to manually delete layers.
- **`buildComp()` is dead code:** The function exists but is never called from the React UI (which uses `beginComp`/`appendCutBatch`/`finishComp` instead). It duplicates logic and can drift.
- **No layer ordering:** Layers are added in cut order, so the last cut is on top. But AE stacks layers with the first-added on top. The timeline may look correct but the layer panel order is reversed.
- **`selectClipsForSection()` in aeft.ts** is a client-side clip selector that duplicates the Python `shot_selector.py` logic. The React app uses the Python backend for shot selection, so this function is dead code.
- **No audio level normalization:** The music audio is imported but no audio level is set. If the music is too loud or quiet, no normalization is applied.
- **No fade out:** The music doesn't fade out at the end. It cuts abruptly at the comp's end.
- **`parseBeatInterval()` only handles "beat" unit:** If a style uses "bar" or "second" units, it silently falls back to 1.
- **No validation of cut data:** `appendCutBatch` checks `cut.endTime <= cut.beatTime` but doesn't check for NaN, negative values, or paths with special characters that might break `File()`.
- **`importFile()` doesn't handle sequences:** If a user selects an image sequence, `ImportOptions` needs different handling. Currently only handles single files.

### 1.6 Bridge Issues (`index.ts`)

- **`getBridgeHealth()` version is hardcoded:** Returns `"0.1.8"` — must be manually kept in sync with `APP_VERSION` in App.tsx and `VERSION` file. Should read from a single source.
- **No error handling in dialog functions:** `openFileDialog`, `openFilesDialog`, `openFolderDialog` don't catch exceptions from `File.openDialog` or `Folder.selectDialog`.
- **Filter format:** The filter string is passed directly to `File.openDialog` — on macOS, the filter parameter works differently than Windows. No cross-platform normalization.

---

## 2. React/UI Gaps

### 2.1 Missing Components

- **No Settings/Preferences panel:** No way for users to configure backend URL, FFprobe path, analysis worker count, or thumbnail quality. These are hardcoded or env-var only.
- **No Help/Tutorial overlay:** No first-run experience, no tooltips, no walkthrough. New users will be confused.
- **No Preview/Scrub component:** Users can't preview the timeline before generating. They click GENERATE and hope for the best.
- **No Export/Render component:** After generation, there's no "Export to AME" or "Render" button. Users must use AE's native render queue.
- **No Style Editor:** The "Custom" style exists but there's no UI to edit it. Users must hand-edit JSON.
- **No Clip Preview/Thumbnail viewer:** MediaImport shows clip names but no thumbnails. The backend generates thumbnails but they're only used in ReviewMode.
- **No Audio Waveform visualization:** AnalysisView shows BPM and sections but no waveform. Users can't see the music structure visually.
- **No Keyboard shortcuts:** No hotkeys for generate, cancel, tab switching, etc.
- **No Drag-and-drop import:** MediaImport only uses file dialogs. No drag-and-drop from Finder/Explorer.

### 2.2 State Management Issues

- **No global state store:** All state is in `App.tsx` with `useState`. With 10+ state variables, this is getting unwieldy. No Context, Redux, or Zustand.
- **No persistence:** Style selection, parameters, and Element 3D settings are not persisted across panel reloads. Users must reconfigure every time.
- **`ANALYSIS_JOB_STORAGE_KEY` is truncated:** `"flagsh…obId"` — this looks like a display truncation, not an actual key. If this is the real localStorage key, it's malformed.
- **No state validation:** No schema validation on loaded styles. If a style JSON is malformed, the app will crash with an unhelpful error.

### 2.3 UX Issues

- **No progress indication for style loading:** `loadStyle()` is async but no loading state is shown.
- **No error boundaries:** A React error in any component crashes the entire panel with no recovery.
- **Tab order is fixed:** Media → Style → Params → 3D → Review → Analysis. Users can't reorder or hide tabs they don't use.
- **No responsive design:** The panel is 420px wide. If resized smaller, the tab labels will overflow. No media queries.
- **Color contrast:** `#666` on `#0f0f1e` background is below WCAG AA. Several text colors fail accessibility standards.
- **No ARIA labels on most elements:** Only TaskProgress has `aria-label`. Buttons, tabs, and inputs are unlabeled.
- **No focus management:** Tab buttons don't manage focus properly. No `tabindex` handling.
- **ReviewMode uses className but no CSS:** The component references `className="review-mode"`, `className="cut-card"`, etc., but there's no CSS file. These classes do nothing — all styling is inline in other components.
- **No loading state for ReviewMode:** When swapping cuts, there's no spinner or disabled state. Users can click multiple times.
- **No confirmation for destructive actions:** "Clear" in MediaImport removes all clips with no confirmation dialog.
- **No clip count limit warning:** Users can import 50,000 clips but there's no warning about how long analysis will take.

### 2.4 Parameters Component Issues

- **No preset save/load:** Users can't save their parameter combinations as presets.
- **No fine-grained control:** Sliders are 0–10 integers. No decimal precision for fine-tuning.
- **Missing parameter descriptions:** No tooltips or help text explaining what each parameter does.
- **Hardcoded "not available" message:** "Face masking, smoke/fog, and text generation are not available in this build." — this is a permanent apology, not a temporary state.

### 2.5 StyleSelector Issues

- **No style preview:** Users see a radio button with a name. No thumbnail, no example video, no description of what the style does.
- **No style comparison:** Can't see two styles side by side.
- **No custom style upload:** Can't import a style JSON from disk.
- **No style search/filter:** With only 6 styles this is fine, but won't scale.

### 2.6 AnalysisView Issues

- **No energy curve visualization:** The `energy` array is returned from the backend but never plotted. Users see a number, not a curve.
- **No beat grid:** Beats are counted but not visualized on a timeline.
- **No section preview:** Sections are listed as text but not shown on a timeline strip.
- **No export of analysis data:** Can't export beat data, sections, or key for use in other tools.

---

## 3. Python Engine Gaps

### 3.1 Beat Analysis (`beat_analysis.py`)

- **No tempo doubling/halving correction:** librosa's `beat_track` can return half or double tempo. No validation against typical music tempo ranges (60–200 BPM).
- **No time signature detection:** Assumes 4/4 time. `downbeats = [beat_times[i] for i in range(0, len(beat_times), 4)]` — hardcoded 4. Won't work for 3/4, 6/8, or 5/4.
- **No confidence scoring:** No measure of how confident the beat detection is. Users don't know if the BPM is reliable.
- **Section classification is naive:** `classify_section_type()` uses RMS threshold heuristics. No ML-based classification. The thresholds (0.01, 0.1, 0.05) are arbitrary and won't generalize across genres.
- **`assign_section_types()` forces intro/outro:** First section is always "intro", last is always "outro". This is wrong for songs that start with a chorus or end with a drop.
- **No drop detection:** The "drop" is assigned to the highest-energy section, but in electronic music, the drop is a specific moment, not just the loudest section.
- **Key detection is basic:** Krumhansl-Schmuckler correlation is known to be inaccurate for minor keys and modal music. No fallback or confidence score.
- **No harmonic analysis:** No chord detection, no chord progression, no harmonic complexity metric.
- **No vocal detection:** No separation of vocal vs. instrumental sections.
- **No drop/chorus differentiation:** The algorithm can't tell the difference between a chorus (melodic) and a drop (instrumental/energy peak).
- **Energy curve resolution:** `frame_length=2048, hop_length=512` gives ~43Hz resolution at 22050Hz. This is fine but the energy array is returned as a flat list with no timestamps. The UI can't align it with the timeline.
- **No caching:** Beat analysis is re-run every time. No SQLite cache like clip analysis has. For long songs, this is 10–30 seconds of redundant work.
- **Memory usage:** `librosa.load(audio_path, sr=22050)` loads the entire audio into memory. For a 10-minute song at 22050Hz, that's ~13M samples × 4 bytes = ~52MB. No chunked processing.
- **No progress reporting:** Beat analysis is synchronous. The UI shows "Analyzing beat..." with no progress bar. For long files, this looks frozen.

### 3.2 Clip Analysis (`clip_analysis.py`)

- **Face detection is outdated:** Uses Haar cascades (`haarcascade_frontalface_default.xml`) which are fast but inaccurate. No DNN-based face detection (`cv2.dnn` with Caffe models). Misses profile faces, faces with sunglasses, faces in low light.
- **No person detection:** No full-body or person detection. Only faces. Can't identify "performance" shots without faces (e.g., hands on instrument).
- **No scene detection:** No shot boundary detection. The entire clip is classified as one scene type. A clip may contain multiple scenes.
- **No audio analysis of video clips:** No extraction of audio from video to check if a clip has sync sound or music.
- **No stabilization detection:** No detection of whether a clip is already stabilized or shot on a gimbal.
- **No quality scoring beyond sharpness:** No noise/grain assessment, no compression artifact detection, no color cast detection.
- **Optical flow performance:** `cv2.calcOpticalFlowFarneback` is CPU-only and slow for large frames. No GPU-accelerated optical flow (`cv2.cuda` or `cv2.optflow.DualTVL1OpticalFlow`).
- **Thumbnail quality:** JPEG quality 78 is low. No option for higher quality. No thumbnail size options.
- **Cache eviction:** LRU cache with 50,000 entry limit. No size-based eviction. 50,000 entries × ~2KB each = ~100MB. No disk space check.
- **No concurrent thumbnail generation:** Thumbnails are generated during analysis, blocking the analysis pipeline.
- **`extract_frames_opencv` seeks by frame number:** `cap.set(cv2.CAP_PROP_POS_FRAMES, ...)` is slow for large files because it decodes from the nearest keyframe. Should use `cap.set(cv2.CAP_PROP_POS_MSEC, ...)` for faster seeking.
- **No support for image sequences:** Only video files. If a user has a PNG sequence, it won't be analyzed.
- **No RAW support:** No support for RAW video formats (CinemaDNG, BRAW).
- **`ANALYSIS_MAX_DIMENSION` default 640:** This is low for quality assessment. Fine for classification but too low for sharpness scoring — downscaled images hide blur.

### 3.3 Shot Selector (`shot_selector.py`)

- **No learning from user choices:** The selector doesn't remember which clips the user swapped or locked. No preference learning.
- **No temporal coherence:** Selects clips independently per beat. No consideration of clip duration — a 2-second clip assigned to a 0.5-second cut will be trimmed abruptly.
- **No transition awareness:** No consideration of how clips transition into each other. Two visually similar clips in a row are boring.
- **`used_recently` penalty is fixed at 15 points:** No adaptive penalty based on library size. With 5 clips, 15 points is too much. With 500 clips, it's too little.
- **No section-specific scoring weights:** The composite score uses fixed weights (composition 25%, energy 20%, etc.). Different sections need different weights — a drop needs energy, an intro needs stability.
- **No diversity guarantee:** Can still select the same clip twice if the penalty isn't enough.
- **No clip duration matching:** Doesn't check if a clip is long enough for its assigned cut duration.
- **`face_quality_score` is simplistic:** `100 - abs(face_ratio - 0.15) * 500` — this penalizes any face that isn't exactly 15% of frame area. No consideration of face position, angle, or expression.
- **No alternative ranking:** Alternatives are just "next 3 by score" — no diversity in alternatives. All 3 might be from the same scene.

### 3.4 Analysis Jobs (`analysis_jobs.py`)

- **Worker count hardcoded to 2:** `max(1, min(2, int(worker_count)))` — caps at 2 workers even on machines with more cores. The env var `FLAGSHIPEDITOR_ANALYSIS_WORKERS` is read but clamped.
- **No job priority:** All jobs have equal priority. A quick 5-clip job waits behind a 5000-clip job.
- **No job expiration:** Old completed jobs stay in the database forever. No TTL or cleanup.
- **No job listing endpoint:** No API to list all jobs. The UI can only check a specific job ID.
- **No job deletion:** No API to delete a completed job and its results from the database.
- **Database size unbounded:** No vacuum or size limit on the SQLite database.
- **No retry on transient failures:** If a clip analysis fails with a transient error (e.g., file locked), it's marked as failed permanently. No retry count.
- **`_drain_queue_tokens` is O(n):** Drains the entire queue to remove tokens for one job. With many jobs, this is slow.

### 3.5 Server (`server.py`)

- **No authentication:** The server listens on `127.0.0.1` only, but any process on the machine can call it. No API key or token.
- **No rate limiting:** A malicious or buggy client could flood the server with requests.
- **No request logging:** No structured logging. `uvicorn` logs to stdout but no file logging or rotation.
- **No graceful shutdown on SIGTERM:** The `shutdown_server` endpoint exists but SIGTERM/SIGINT aren't handled. If the process is killed, the PID file may remain.
- **FFMPEG_PATH Windows bias:** `str(Path(FFPROBE_PATH).with_name("ffmpeg.exe"))` — hardcodes `.exe` extension. On macOS/Linux, this produces `ffmpeg.exe` which doesn't exist.
- **No health check for disk space:** The server doesn't check if there's enough disk space for thumbnails or cache.
- **No CORS restriction:** `allow_origins=["*"]` — any origin is allowed. Should be restricted to the CEP extension origin.
- **No API versioning:** Endpoints are unversioned. Breaking changes would require a new server port.
- **No WebSocket for real-time updates:** The UI polls every 600ms. A WebSocket would be more efficient and provide real-time progress.

### 3.6 Self Test (`self_test.py`)

- **Requires fixture files:** `prores-422-standard.mov` and `prores-422-hq.mov` must exist in `engine/fixtures/`. No fixture generation or download mechanism.
- **Only tests ProRes decoding:** No test for beat analysis, shot selection, or the full pipeline.
- **No CI integration:** The test is manual. No GitHub Actions or CI pipeline.

---

## 4. CEP/Build Gaps

### 4.1 Manifest Issues (`CSXS/manifest.xml`)

- **CSXS Version 6.0 / RequiredRuntime 9.0:** This targets CEP 9 (AE 2024+). But the `cep.config.ts` says `extensionManifestVersion: 6.0` and `requiredRuntimeVersion: 9.0`. These are consistent but exclude AE 2023 and earlier.
- **No `HostList` version upper bound issue:** `[24.0,99.9]` — the upper bound 99.9 is fine but could be more specific.
- **No `ExtensionBundleId` certificate info:** No signing certificate reference in the manifest.
- **No `Geometry` `DefaultPosition`:** The panel doesn't specify where it should dock by default.
- **No `ScriptPath` for settings panel:** The manifest only has one panel. No settings or configuration panel.

### 4.2 CEP Config Issues (`cep.config.ts`)

- **`symlink: "local"`:** This creates a symlink for dev mode. No documentation on how to switch to production mode.
- **`port: 3000` and `servePort: 5000`:** These are dev ports. No documentation on whether they need to be changed for production.
- **`parameters: ["--v=0", "--allow-file-access", "--allow-file-access-from-files"]`:** Missing `--enable-nodejs` (intentionally disabled per comment, but limits functionality).
- **`width: 420, height: 720`:** Fixed size. No responsive behavior.
- **`build: { jsxBin: "off", sourceMap: false }`:** No source maps for debugging ExtendScript.
- **`zxp.password: "flagshipeditor"`:** The ZXP signing password is in plaintext in the config. Should be in an env var or CI secret.
- **`zxp.tsa: ["http://timestamp.digicert.com/"]`:** Single TSA. No fallback if this TSA is down.
- **`installModules: []` and `copyAssets: []`:** No assets are copied during build. LUTs and styles must be manually placed.
- **No `copyZipAssets`:** Empty. No mechanism to bundle the Python backend into the ZXP.

### 4.3 Package.json Issues

- **No `engines` field:** No Node.js version requirement specified.
- **No `peerDependencies`:** React 18 is a dependency but no peer deps for Adobe CEP.
- **Missing test scripts:** No `test` script. Tests exist but must be run individually.
- **No lint script:** No ESLint or Prettier configuration.
- **No `prepublish` or `prepack` script:** No build verification before packaging.
- **`@types/node: "^18.0.0"` but Node 24 is the runtime:** Type definitions are outdated.
- **No `tsconfig.json` reference:** No TypeScript configuration is referenced or documented.
- **No dependency on `typescript` in `dependencies`:** TypeScript is in devDependencies, which is correct, but no `tsc` script for type checking.

### 4.4 Build/Packaging Gaps

- **No macOS packaging:** `package-windows.mjs` exists but no macOS equivalent. The README says "Windows 11 + macOS" but only Windows is packaged.
- **No auto-update mechanism:** No version check, no update notification, no auto-update. Users must manually reinstall.
- **No installer verification:** No checksum or signature verification of the installer.
- **No Python backend bundling:** The ZXP doesn't include the Python backend. Users must install Python and dependencies separately.
- **No bundled FFmpeg/FFprobe:** Users must install FFmpeg separately. Top plugins bundle their dependencies.
- **No bundled Python:** Users need Python 3.10+ installed. No embedded Python.
- **No `.dmg` or `.pkg` for macOS:** No macOS installer format.

---

## 5. Commercial Gaps

### 5.1 What Top Plugins Have That FlagshipEditor Lacks

| Feature | Top Plugins | FlagshipEditor |
|---------|-------------|---------------|
| **Presets library** | 50–3000+ presets | 6 style JSONs |
| **Preset browser UI** | Visual preset gallery with thumbnails | Radio button list |
| **Tutorials** | Video tutorials, written guides, sample projects | README only |
| **Licensing system** | Floating licenses, activation/deactivation, machine ID | None (MIT license) |
| **Auto-update** | In-app update checker, delta updates | None |
| **Crash reporting** | Sentry, custom crash reporters | None |
| **Analytics/telemetry** | Usage analytics (opt-in) | None |
| **Discord community** | Active Discord servers (Plugin Everything, Video Copilot) | None |
| **Documentation site** | Dedicated docs site (docs.borisfx.com, etc.) | README only |
| **Sample projects** | Downloadable sample projects | None |
| **Trial/free version** | Free tier or trial period | Open source (MIT) |
| **Pro tier** | Paid features, premium support | No tiers |
| **Changelog** | Detailed version history | Version numbers only |
| **Roadmap** | Public roadmap | None |
| **Social media** | YouTube, Twitter, Instagram presence | None |
| **Email newsletter** | Product updates | None |
| **Affiliate program** | Referral commissions | None |
| **Bundle deals** | Multi-product bundles | None |
| **Educational discounts** | Student/teacher pricing | None (open source) |
| **Enterprise licensing** | Site licenses, volume discounts | None |
| **Localization** | Multi-language UI (EN, JP, DE, FR, ES, CN) | English only |
| **Accessibility** | Screen reader support, high contrast mode | Minimal ARIA |
| **Keyboard shortcuts** | Comprehensive hotkey system | None |
| **Undo/Redo** | Full undo support in panel | None |
| **Context menus** | Right-click menus | None |
| **Multi-panel** | Dockable panels, multi-window | Single panel |
| **Command palette** | Quick action search | None |
| **Batch processing** | Process multiple songs/projects | One at a time |
| **Render queue** | Queue multiple renders | None |
| **Export presets** | Render settings presets | None |
| **Project templates** | Starting project templates | None |
| **Asset library** | Bundled stock footage, music, LUTs | 7 LUTs only |
| **Plugin marketplace** | Third-party extensions | None |
| **API/SDK** | Third-party integration | None |
| **Mobile companion** | iOS/Android remote control | None |
| **Cloud sync** | Sync settings across machines | None |

### 5.2 Pricing & Business Model Gaps

- **No monetization strategy:** MIT license with no revenue model. Top plugins charge $29–$295+.
- **No freemium tier:** No "free with watermark" or "free for personal use" tier.
- **No subscription option:** No recurring revenue model.
- **No upgrade pricing:** No mechanism for paid major version upgrades.
- **No referral program:** No incentive for users to spread the word.

### 5.3 Marketing Gaps

- **No demo video:** No YouTube demo or showcase reel.
- **No before/after gallery:** No visual comparison of raw footage vs. FlagshipEditor output.
- **No user testimonials:** No social proof.
- **No case studies:** No "how FlagshipEditor was used on X project" stories.
- **No SEO content:** No blog posts, no tutorials, no SEO-optimized landing page.
- **No product hunt launch:** No Product Hunt or similar launch.
- **No influencer outreach:** No outreach to AE YouTubers (School of Motion, Mt. Mograph, etc.).

---

## 6. Architecture Gaps

### 6.1 Performance

| Area | Top Plugins | FlagshipEditor |
|------|-------------|----------------|
| **GPU acceleration** | OpenGL/CUDA/Metal for rendering | None — all CPU |
| **Multi-Frame Rendering (MFR)** | MFR-compatible | Not MFR-aware |
| **Caching** | Disk-persistent render caches | Clip analysis cache only |
| **Threading** | Multi-threaded rendering | 2-worker analysis only |
| **Memory management** | Pooled VRAM, texture pools | No pooling |
| **Lazy loading** | Effects loaded on demand | All loaded at startup |
| **Debouncing** | UI operations debounced | No debouncing |

### 6.2 Cross-Platform Issues

- **FFMPEG_PATH:** `str(Path(FFPROBE_PATH).with_name("ffmpeg.exe"))` hardcodes `.exe` — broken on macOS/Linux.
- **`LOCALAPPDATA` env var:** Used for cache directory — Windows-only. On macOS, should use `~/Library/Caches/` or `~/Library/Application Support/`.
- **`TEMP`/`TMP` env vars:** Used as fallback — Windows-centric. macOS uses `$TMPDIR`.
- **No macOS installer:** Only Windows installer exists.
- **No macOS signing:** No `.app` bundle, no notarization, no Gatekeeper compatibility.
- **Path separators:** Mix of `/` and `\\` handling. `normalizeMediaPath` in aeft.ts handles this, but Python code doesn't normalize.
- **No Linux support:** Server runs on any platform with Python, but no installer or testing.

### 6.3 Error Handling & Resilience

- **No circuit breaker:** If the Python backend is down, the UI keeps trying. No circuit breaker pattern.
- **No dead letter queue:** Failed clip analyses are marked as failed but no retry mechanism.
- **No idempotency:** Starting an analysis job is not idempotent. If the UI retries, duplicate jobs are created.
- **No distributed locking:** If two UI instances run, they can both try to manage the same job.
- **No health check watchdog:** The backend doesn't monitor its own health (memory, disk, CPU).
- **No backpressure:** If the UI sends requests faster than the backend can process, there's no backpressure mechanism.

### 6.4 Testing Gaps

- **No unit tests for ExtendScript:** VFX functions, comp builder, color grading — all untested.
- **No integration tests:** No end-to-end test from import → analyze → generate.
- **No UI tests:** No component testing, no screenshot testing, no E2E browser tests.
- **No performance tests:** No benchmarks for analysis speed, rendering speed, or UI responsiveness.
- **No regression tests:** No tests to verify that a fix doesn't break existing functionality.
- **No mock AE environment:** Tests require a real After Effects instance.
- **Test coverage unknown:** No coverage reporting tool configured.

### 6.5 Security Gaps

- **No input sanitization:** File paths from the UI are passed directly to `File()` in ExtendScript and `os.path` in Python. Path traversal attacks are possible.
- **No command injection protection:** `subprocess.run([FFPROBE_PATH, ...])` is safe (list form), but `FFPROBE_PATH` comes from an env var that could be manipulated.
- **No SSRF protection:** The server accepts any `audioPath` or `videoPath` — could be used to access system files.
- **No file type validation:** The server accepts any file path for analysis. No magic number validation — a renamed `.txt` file with a `.mov` extension will be processed.
- **No resource limits:** No memory limit, CPU limit, or disk usage limit for analysis operations.

### 6.6 Scalability

- **Single-user design:** The backend serves one UI. No multi-user or multi-session support.
- **No job queue persistence across restarts:** Jobs are recovered from SQLite but in-progress items are re-queued, not resumed.
- **No horizontal scaling:** The backend is single-process. No multi-process or multi-machine support.
- **No streaming results:** Results are returned as a single JSON response. For large libraries, this could be hundreds of MB.

---

## 7. Documentation Gaps

### 7.1 Missing Documentation

| Document | Status | Priority |
|----------|--------|----------|
| **Installation guide (detailed)** | Missing — README has 4 lines | HIGH |
| **User manual** | Missing | HIGH |
| **Style preset reference** | Missing — no doc explaining what each style does | HIGH |
| **VFX reference** | Missing — no doc on what each effect does | MEDIUM |
| **API reference (Python backend)** | Missing | MEDIUM |
| **Troubleshooting guide** | Missing | HIGH |
| **FAQ** | Missing | MEDIUM |
| **Changelog** | Missing — only version numbers | MEDIUM |
| **Migration guide** | Missing | LOW |
| **Developer guide** | Missing — no doc for contributors | LOW |
| **Architecture document** | Missing | LOW |
| **Security guide** | Missing | LOW |

### 7.2 README Gaps

The current README is 60 lines. Missing sections:

- **Screenshots/GIFs:** No visual preview of the panel.
- **Feature list:** No explicit list of what the plugin does.
- **System requirements (detailed):** No specific OS versions, RAM requirements, disk space.
- **Installation steps (Windows):** No step-by-step Windows installation.
- **Installation steps (macOS):** No macOS installation instructions.
- **Python backend setup (detailed):** No virtualenv instructions, no troubleshooting for common pip issues.
- **FFmpeg installation:** No instructions for installing FFmpeg.
- **Usage guide:** No step-by-step guide on how to use the plugin.
- **Style customization:** No guide on creating custom styles.
- **LUT creation:** No guide on the LUT format and how to add custom LUTs.
- **Keyboard shortcuts:** No shortcut reference (because there are none).
- **Known issues:** No list of known bugs or limitations.
- **Contributing guide:** No instructions for contributors.
- **License details:** MIT mentioned but no full license text.
- **Credits:** No attribution to libraries used (librosa, OpenCV, etc.).
- **Contact/support:** No support email, no issue tracker link.

### 7.3 Missing Tutorials

- **Getting started tutorial:** Import media → select style → generate.
- **Style selection guide:** When to use each style.
- **Parameter tuning guide:** How to adjust cut intensity, VFX intensity, color grading.
- **Review mode tutorial:** How to swap cuts, lock cuts, regenerate sections.
- **Custom style tutorial:** How to create a custom style JSON.
- **Element 3D workflow:** How to use the Element 3D integration.
- **Troubleshooting backend issues:** How to diagnose and fix Python backend problems.
- **Performance optimization:** How to optimize analysis for large libraries.

### 7.4 Missing Code Documentation

- **No JSDoc/TSDoc comments:** Most functions have no documentation comments.
- **No inline comments:** Complex logic (e.g., `getCutTimesInRange`, `pollPersistentJob`) has no explanatory comments.
- **No architecture diagram:** No visual representation of the system architecture.
- **No data flow diagram:** No diagram showing how data flows from UI → Python → ExtendScript → AE.

---

## 8. Priority Summary

### P0 — Critical (Blocks production use)

1. **19 unimplemented VFX effects** — styles promise effects that don't exist
2. **`speed_ramp` and `freeze_frame` implemented but never called** — dead code that should be wired up
3. **Hardcoded FPS (30) and resolution (1920×1080)** — breaks for any other format
4. **FFMPEG_PATH `.exe` hardcode** — breaks on macOS
5. **No undo group in ExtendScript** — failed builds leave orphaned layers
6. **`LOCALAPPDATA` cache path** — breaks on macOS
7. **No macOS installer** — README claims macOS support but no installer exists

### P1 — High (Significant quality issues)

8. **No beat analysis caching** — 10–30s redundant work per generate
9. **No beat analysis progress** — UI looks frozen for long songs
10. **No tempo doubling/halving correction** — wrong BPM is common
11. **Face detection uses Haar cascades** — misses many faces
12. **No GPU acceleration** — all analysis is CPU-only
13. **No MFR compatibility** — AE's Multi-Frame Rendering not supported
14. **No error boundaries in React** — single component crash kills panel
15. **No state persistence** — users reconfigure on every panel reload
16. **No clip thumbnails in MediaImport** — poor UX for large libraries
17. **No audio waveform visualization** — can't see music structure
18. **No keyboard shortcuts** — power users can't work fast
19. **No Settings/Preferences panel** — can't configure backend URL or paths
20. **Glitch effect implementation is wrong** — RGB split via Shift Channels doesn't work
21. **Camera shake not time-bounded** — wiggle expression applies to entire layer
22. **Whip pan missing rotation** — only position X is animated
23. **No confirmation for destructive actions** — Clear removes all clips silently
24. **No troubleshooting guide** — users can't self-diagnose

### P2 — Medium (Should fix before commercial release)

25. **No presets library** — only 6 styles, no preset browser
26. **No tutorial content** — no videos, no written guides
27. **No localization** — English only
28. **No accessibility** — WCAG failures, no screen reader support
29. **No crash reporting** — no Sentry or equivalent
30. **No auto-update** — users must manually reinstall
31. **No Discord community** — no user community platform
32. **No documentation site** — README only
33. **No demo video** — no visual showcase
34. **No performance tests** — no benchmarks
35. **No unit tests for ExtendScript** — VFX untested
36. **No UI tests** — components untested
37. **No API authentication** — any local process can call backend
38. **No rate limiting** — DoS possible
39. **No file type validation** — renamed files accepted
40. **No job expiration** — database grows forever
41. **No WebSocket** — polling every 600ms is wasteful
42. **No macOS signing/notarization** — Gatekeeper will block
43. **ZXP password in plaintext** — security risk
44. **No bundled FFmpeg** — extra install step
45. **No bundled Python** — extra install step
46. **No vertical video support** — 1920×1080 hardcoded
47. **No 4K support** — resolution hardcoded
48. **No clip duration matching** — short clips assigned to long cuts
49. **No transition awareness** — no clip-to-clip transition logic
50. **No learning from user choices** — no preference learning

### P3 — Low (Nice to have)

51. **No style editor UI** — custom styles require JSON editing
52. **No style preview thumbnails** — radio buttons only
53. **No drag-and-drop import** — file dialog only
54. **No export to AME** — no render queue integration
55. **No batch processing** — one song at a time
56. **No command palette** — no quick action search
57. **No mobile companion** — no remote control
58. **No cloud sync** — no settings sync
59. **No affiliate program** — no referral incentive
60. **No educational discounts** — no student pricing
61. **No enterprise licensing** — no site licenses
62. **No plugin marketplace** — no third-party extensions
63. **No API/SDK** — no third-party integration
64. **No changelog** — no version history
65. **No roadmap** — no public future plans
66. **No social media presence** — no YouTube/Twitter/Instagram
67. **No email newsletter** — no product updates
68. **No SEO content** — no blog posts
69. **No case studies** — no user stories
70. **No influencer outreach** — no AE YouTuber partnerships

---

## Summary Statistics

| Category | P0 (Critical) | P1 (High) | P2 (Medium) | P3 (Low) | Total |
|----------|---------------|-----------|-------------|----------|-------|
| ExtendScript | 3 | 5 | 0 | 0 | 8 |
| React/UI | 0 | 6 | 3 | 5 | 14 |
| Python Engine | 0 | 4 | 5 | 0 | 9 |
| CEP/Build | 2 | 0 | 3 | 0 | 5 |
| Commercial | 0 | 0 | 8 | 10 | 18 |
| Architecture | 2 | 4 | 6 | 5 | 17 |
| Documentation | 0 | 2 | 5 | 6 | 13 |
| **Total** | **7** | **21** | **30** | **26** | **84** |

**Bottom line:** FlagshipEditor has a solid foundation — the incremental build pipeline, persistent job system, and resilient recovery are well-engineered. But it ships with 19 promised VFX effects that don't exist, hardcoded FPS/resolution that limits format support, Windows-only path handling that breaks macOS, and no macOS installer. The Python engine is competent but lacks GPU acceleration, caching for beat analysis, and modern face detection. The UI is functional but missing basic features like state persistence, error boundaries, keyboard shortcuts, and accessibility. For commercial release, the biggest gaps are in VFX implementation, cross-platform support, documentation, and community/marketing infrastructure.

**Recommended next steps:**
1. Implement the 19 stubbed VFX effects (or remove them from style JSONs)
2. Wire up `speed_ramp` and `freeze_frame` in `applyVFXToLayer()`
3. Fix hardcoded FPS, resolution, and Windows path issues
4. Add macOS installer and signing
5. Add beat analysis caching and progress
6. Add React error boundaries and state persistence
7. Write user documentation and troubleshooting guide
8. Create demo video and tutorial content