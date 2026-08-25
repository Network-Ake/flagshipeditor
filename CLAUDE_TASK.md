# FlagshipEditor v2.0 — UI Overhaul Task

You are working on FlagshipEditor, an After Effects CEP panel for AI music-video editing.
The Python cutting engine was just rewritten and works (7/7 tests pass, commit 28ef954).
Now the UI needs to match the engine quality.

## Context
- This is a CEP panel (React + TypeScript + Vite), not a web app
- CEP panels are small (300-400px wide typically) — every pixel counts
- Dark theme, system fonts only, no CDN, no web fonts
- The user wants a "prestige" tool feel — references: skeet.cc, aimware.net, DaVinci Resolve timeline density
- NOT a generic web app. Dense, professional, keyboard-driven.

## Project location
`/Users/issandre/.openclaw/workspace/projects/flagshipeditor`

## Files you will modify
- `src/js/main/App.tsx` (1262 lines) — main app, tab routing, state
- `src/js/main/styles.css` (2286 lines) — all CSS, single file
- `src/js/main/components/ReviewMode.tsx` (262 lines) — review panel
- `src/js/main/components/AnalysisView.tsx` (203 lines) — analysis display
- `src/js/main/components/MediaImport.tsx` (189 lines) — import UI
- `src/js/main/components/StyleSelector.tsx` (162 lines) — style picker
- `src/js/main/components/Parameters.tsx` (265 lines) — params panel
- `src/js/main/lib/styles.ts` (299 lines) — style/effect definitions
- `src/js/main/lib/python.ts` (356 lines) — backend API client + types

## Files NOT to touch
- Anything in `engine/` (Python backend)
- Anything in `scripts/` (test files)
- Anything in `installer/` (MSI build)
- Anything in `src/jsx/` (After Effects bridge)
- `package.json`, `vite.config.ts`, `tsconfig.json`

## TASK 1: Remove the 3D tab entirely
Steve said: "VFX/Element 3D is out of scope. Focus on cutting."

- Remove "3d" from the Tab type and TABS array in App.tsx
- Remove Element3DPanel import and all element3D state/handlers from App.tsx
- Remove Element3DPanel.tsx file
- Remove element_3d from styles.ts (Element3DSettings, EFFECT_CATALOG entries for group "3d")
- Remove the "3d" group from GROUP_ORDER and GROUP_ICONS in Parameters.tsx
- Remove element3D from the beginComp call in App.tsx
- Keep everything else working

## TASK 2: Redesign ReviewMode into a professional cutting review tool
The current ReviewMode (262 lines) is "lazy" per user feedback.

### What it must become:

**A. Waveform strip (top, ~80px tall)**
- SVG waveform from BeatAnalysis.energy[] array (normalize to fit width)
- Beat markers: small vertical lines for each beat, taller for downbeats
- Bass onset markers: distinct color (e.g. accent-primary) dots/lines
- Section bands: colored background bands by section type (intro=blue, verse=gray, chorus=purple, drop=red, outro=blue)
- Cut markers: triangular markers above the waveform showing where each cut falls
- Clicking a cut marker selects that cut
- The waveform is the hero element — make it look real, not abstract

**B. Compact cut list (below waveform)**
- Dense rows, not big cards. Each row: index | time | section badge | clip name | score bar (inline) | lock icon
- Row height ~28px, font 11-12px
- Selected row highlighted with accent-soft background
- Click selects, double-click could zoom (future)
- Drag to reorder still works

**C. Detail panel (right side or bottom, for selected cut)**
- Thumbnail (small, 64x36px)
- Score breakdown: 6 horizontal bars (composition, energy, variety, sharpness, stability, face_quality) — compact, 10px height each
- Alternatives: horizontal scroll of mini cards (thumbnail 48x27 + name + score). Click to swap.
- Lock toggle button
- All very compact — this is a tool, not a dashboard

**D. Keyboard shortcuts**
- J = previous cut, L = next cut, K = play/pause (visual toggle only, no audio API needed), Space = same
- Left/Right arrows = nudge selection by 1
- Delete/Backspace = remove cut (call onReorder to move it away or mark for removal)
- Shift+L = toggle lock on selected cut
- Show a small shortcut hint bar at the bottom (faded, 10px font)

**E. Regenerate section toolbar**
- Compact horizontal buttons, one per section type
- Icon + section name, small, pill-shaped
- Disabled when busy

### Props (keep same interface, add optional beatAnalysis):
```typescript
interface Props {
  cuts: CutDecision[];
  busy: boolean;
  onSwap: (indices: number[], alternative: CutAlternative) => void;
  onToggleLock: (index: number) => void;
  onReorder: (from: number, to: number) => void;
  onRegenerateSection: (sectionType: string) => void;
  beatAnalysis?: BeatAnalysis | null;  // NEW optional prop
}
```

### Types you need (from lib/python.ts):
```typescript
interface CutDecision {
  beatTime: number; endTime: number; sectionType: string;
  clipPath: string; clipName: string; thumbnailId: string;
  sceneType: string; clipDuration: number; score: number;
  scores: ClipScores; locked: boolean; alternatives: CutAlternative[];
}
interface ClipScores { composition: number; energy: number; variety: number; sharpness: number; stability: number; face_quality: number; }
interface CutAlternative { clipPath: string; clipName: string; thumbnailId: string; sceneType: string; score: number; }
interface BeatAnalysis { tempo: number; beats: number[]; downbeats: number[]; sections: BeatSection[]; energy: number[]; bass_onsets: number[]; hihat_onsets: number[]; key: string; mode: string; duration: number; }
interface BeatSection { type: string; start: number; end: number; }
```

### Update App.tsx:
- Pass `beatAnalysis={beatAnalysis}` to ReviewMode
- Import BeatAnalysis type if needed

## TASK 3: Polish the overall UI to "prestige" level

**A. Compact status bar (bottom of app, ~24px tall)**
- Backend status: green/red dot + "Backend" text
- BPM display (from beatAnalysis)
- Key + mode (from beatAnalysis)
- Section count
- Cut count
- Use existing health/analysis data from App.tsx state
- Monospace font for numbers

**B. Tab bar improvements**
- More compact: icon + label in tighter layout, smaller padding
- Active tab: accent underline (2px) instead of full background fill
- Hover: subtle background change
- Remove the 3D tab (from Task 1)

**C. AnalysisView improvements**
- Replace the simple SVG energy curve with a proper waveform-style visualization
- Add section overlay bands on the waveform
- Add beat markers on the waveform
- Keep the stats grid but make it more compact
- Add a "section timeline" strip at the top showing the full track structure

**D. MediaImport improvements**
- More compact drop zone: remove big emoji, use subtle dashed border with small icon
- Professional file list: compact rows with file icon, name, size, status badge
- Keep the same functionality (file dialog, folder dialog, drag-drop)

**E. Global CSS polish**
- Tighten spacing: reduce padding/margins by ~30% on key components
- Ensure consistent border-radius (use existing --r-sm, --r-md vars)
- Add subtle transitions on state changes (100-150ms)
- Make sure scrollbars are styled (already done, verify)
- Ensure focus states are visible (accessibility + pro tool feel)

## Build & test commands
```bash
npm run build    # Vite build + post-build validation — MUST PASS
npm test         # All JS/TS test suites — MUST PASS
```

## After all changes
1. Run `npm run build` — must succeed
2. Run `npm test` — all suites must pass
3. Run `git add -A && git commit -m "feat: UI overhaul — remove 3D tab, redesign review mode with waveform, prestige polish" && git push`

## Quality bar
This is a professional tool for music video editors. The UI should feel like DaVinci Resolve's timeline panel, not a web form. Dense, fast, keyboard-friendly, visually precise. Every pixel earns its place.