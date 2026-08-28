// Style presets and the runtime style the whole edit is generated from.
//
// The JSON presets are bundled at build time rather than fetched: the installer
// copies `styles/` next to the panel, but a CEP panel resolves relative URLs
// against `main/index.html`, so a fetch would 404 on every real install.

import cmdCommandDrill from "../../../../styles/cmd_command_drill.json";
import custom from "../../../../styles/custom.json";
import jackRottier from "../../../../styles/jack_rottier.json";
import lyricalLemonade from "../../../../styles/lyrical_lemonade.json";
import ninetive from "../../../../styles/ninetive.json";
import worldwideFilms from "../../../../styles/worldwide_films.json";

export type EffectGroup = "cut" | "camera" | "texture" | "color" | "time";

export interface EffectConfig {
  enabled?: boolean;
  sections?: string[];
  [key: string]: unknown;
}

export interface ColorGradingConfig {
  enabled?: boolean;
  global_lut?: string | null;
  section_luts?: Record<string, string>;
  params?: Record<string, number>;
  opacity?: number;
  extension_root?: string;
  [key: string]: unknown;
}

export interface CutStrategyEntry {
  cut_interval?: string;
  variation?: string;
  double_time_on_808?: boolean;
  double_time_on_drop?: boolean;
  [key: string]: unknown;
}

/** How long shots run in a section, in bars, and how the section varies. */
export interface PacingEntry {
  min_bars: number;
  target_bars: number;
  max_bars: number;
  burstiness: number;
  breath: number;
  burst_bars: number;
  [key: string]: number;
}

export interface StyleConfig {
  style_name: string;
  display_name: string;
  cut_strategy: Record<string, CutStrategyEntry>;
  /**
   * The section pacing ranges the engine actually cuts to. Replaces the former
   * `cut_strategy.cut_interval`, which named a fixed beat subdivision and is
   * why every section produced one shot length.
   */
  pacing?: Record<string, PacingEntry>;
  /** Sequence-level preferences: continuity, repetition tolerance, and so on. */
  selection?: Record<string, number>;
  color_grading?: ColorGradingConfig;
  element_3d?: EffectConfig;
  [key: string]: unknown;
}

export interface EditingParameters {
  cutIntensity: number;
  vfxIntensity: number;
  colorGrading: number;
  seed: number;
  beatSubdivision: number;
  effects: Record<string, boolean>;
}

export interface StyleSummary {
  id: string;
  name: string;
  description: string;
  accent: string;
}

// Every effect the After Effects bridge routes. The order is the order the
// Params tab shows them in.
export const EFFECT_CATALOG: { key: string; label: string; group: EffectGroup }[] = [
  { key: "zoom_punch", label: "Zoom punch", group: "cut" },
  { key: "slow_push_in", label: "Slow push in", group: "cut" },
  { key: "whip_pan", label: "Whip pan", group: "cut" },
  { key: "smooth_transitions", label: "Smooth transitions", group: "cut" },
  { key: "mask_transition", label: "Mask transition", group: "cut" },
  { key: "camera_shake", label: "Camera shake", group: "camera" },
  { key: "beat_flash", label: "Beat flash", group: "camera" },
  { key: "picture_flash", label: "Picture flash", group: "camera" },
  { key: "strobe", label: "Strobe", group: "camera" },
  { key: "glitch_effect", label: "Glitch", group: "texture" },
  { key: "rgb_split", label: "RGB split", group: "texture" },
  { key: "vhs_overlay", label: "VHS overlay", group: "texture" },
  { key: "film_grain", label: "Film grain", group: "texture" },
  { key: "light_leaks", label: "Light leaks", group: "texture" },
  { key: "light_wrap", label: "Light wrap", group: "texture" },
  { key: "smoke_fog", label: "Smoke / fog", group: "texture" },
  { key: "letterbox", label: "Letterbox", group: "texture" },
  { key: "speed_ramp", label: "Speed ramp", group: "time" },
  { key: "slow_mo", label: "Slow motion", group: "time" },
  { key: "freeze_frame", label: "Freeze frame", group: "time" },
  { key: "face_mask", label: "Face mask", group: "color" },
  { key: "depth_blur", label: "Depth blur", group: "color" },
  { key: "selective_color", label: "Selective color", group: "color" },
];

export const EFFECT_GROUP_LABELS: Record<EffectGroup, string> = {
  cut: "Cut",
  camera: "Camera",
  texture: "Texture",
  color: "Color",
  time: "Time",
};

// Scaling these keys is what turns the VFX intensity slider into something the
// render actually shows; every other field keeps the preset author's intent.
const MAGNITUDE_KEYS = ["displacement_px", "blur_radius", "randomness", "intensity", "opacity_peak"];
const SCALE_KEYS = ["scale_target", "target_scale", "scale_end"];

const PRESETS: Record<string, StyleConfig> = {
  cmd_command_drill: cmdCommandDrill as StyleConfig,
  lyrical_lemonade: lyricalLemonade as StyleConfig,
  ninetive: ninetive as StyleConfig,
  jack_rottier: jackRottier as StyleConfig,
  worldwide_films: worldwideFilms as StyleConfig,
  custom: custom as StyleConfig,
};

const STYLE_SUMMARIES: StyleSummary[] = [
  {
    id: "cmd_command_drill",
    name: "CMD COMMAND — UK Drill",
    description: "Quarter-beat cuts, cold grade, glitch and strobe locked to the 808.",
    accent: "linear-gradient(135deg, #6366f1, #ec4899)",
  },
  {
    id: "lyrical_lemonade",
    name: "Lyrical Lemonade",
    description: "Cole Bennett energy — saturated grade, zoom punches, light leaks.",
    accent: "linear-gradient(135deg, #f59e0b, #ec4899, #6366f1)",
  },
  {
    id: "ninetive",
    name: "Ninetive",
    description: "Fast trap cutting with RGB split, depth blur and selective color.",
    accent: "linear-gradient(135deg, #ef4444, #8b5cf6)",
  },
  {
    id: "jack_rottier",
    name: "Jack Rottier",
    description: "Cinematic pacing — slow push-ins, letterbox, film grain, light wrap.",
    accent: "linear-gradient(135deg, #10b981, #3b82f6)",
  },
  {
    id: "worldwide_films",
    name: "World Wide Films",
    description: "Dark trap and drill with mask transitions and hard strobe.",
    accent: "linear-gradient(135deg, #1f2937, #6366f1)",
  },
  {
    id: "custom",
    name: "Custom",
    description: "A neutral base — drive everything from the Params tab.",
    accent: "linear-gradient(135deg, #71717a, #a1a1aa)",
  },
];

export function getAvailableStyles(): StyleSummary[] {
  return STYLE_SUMMARIES.slice();
}

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

/** A fresh, mutable copy of a bundled preset. */
export function loadStyle(styleId: string): StyleConfig {
  const preset = PRESETS[styleId];
  if (!preset) throw new Error(`Unknown style preset: ${styleId}`);
  return clone(preset);
}

export function isEffectConfig(value: unknown): value is EffectConfig {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Effects a preset ships with, split by whether the preset turns them on. */
export function describeStyleEffects(style: StyleConfig): { on: string[]; available: string[] } {
  const on: string[] = [];
  const available: string[] = [];
  for (const effect of EFFECT_CATALOG) {
    const config = style[effect.key];
    if (!isEffectConfig(config)) continue;
    if (config.enabled === true) on.push(effect.label);
    else available.push(effect.label);
  }
  return { on, available };
}

export function defaultEffectToggles(style: StyleConfig): Record<string, boolean> {
  const toggles: Record<string, boolean> = {};
  for (const effect of EFFECT_CATALOG) {
    const config = style[effect.key];
    toggles[effect.key] = isEffectConfig(config) && config.enabled === true;
  }
  return toggles;
}

function parseCutInterval(raw: unknown): number {
  const text = String(raw ?? "1").trim().toLowerCase().replace(/_beats?$/, "");
  const value = Number(text);
  if (!Number.isFinite(value) || value <= 0) return 1;
  return value;
}

function scaleMagnitudes(config: EffectConfig, factor: number): void {
  for (const key of MAGNITUDE_KEYS) {
    const value = config[key];
    if (typeof value === "number" && Number.isFinite(value)) {
      config[key] = Math.round(value * factor * 100) / 100;
    }
  }
  for (const key of SCALE_KEYS) {
    const value = config[key];
    if (typeof value === "number" && Number.isFinite(value)) {
      config[key] = Math.round((100 + (value - 100) * factor) * 100) / 100;
    }
  }
}

/**
 * Merge a preset with the panel's parameters into the exact object that is sent
 * to both `/select-shots` and `beginComp`, so the planned grid and the rendered
 * comp can never disagree.
 */
export function buildRuntimeStyle(base: StyleConfig, params: EditingParameters): StyleConfig {
  const style = clone(base);

  // Cut density. The engine no longer takes a subdivision — a fixed 1/4, 1/8 or
  // 1/16 interval is what produced the mechanical timeline — so intensity now
  // scales the *pacing range* each section works in. A higher intensity pulls
  // the whole range shorter and raises appetite for bursts; a lower one lets
  // shots run. The range is preserved either way, so no setting can collapse
  // the edit back onto a grid.
  const lengthFactor = params.beatSubdivision > 0 ? params.beatSubdivision : 1;
  const densityFactor = Math.pow(2, (5 - params.cutIntensity) / 5) * lengthFactor;
  const pacing: Record<string, PacingEntry> = style.pacing || {};
  for (const section of Object.keys(pacing)) {
    const entry = pacing[section];
    if (!entry || typeof entry !== "object") continue;
    const scaled: Record<string, number> = { ...entry };
    for (const key of ["min_bars", "target_bars", "max_bars"]) {
      const value = Number(scaled[key]);
      if (Number.isFinite(value) && value > 0) {
        // Floored at an eighth of a bar: below that a "shot" is a flash frame,
        // and the planner would only clamp it back anyway.
        scaled[key] = Math.max(0.125, Math.round(value * densityFactor * 1000) / 1000);
      }
    }
    const burstiness = Number(scaled.burstiness);
    if (Number.isFinite(burstiness)) {
      const shift = (params.cutIntensity - 5) / 10;
      scaled.burstiness = Math.max(0, Math.min(0.6, burstiness + shift * 0.3));
    }
    const breath = Number(scaled.breath);
    if (Number.isFinite(breath)) {
      const shift = (5 - params.cutIntensity) / 10;
      scaled.breath = Math.max(0, Math.min(0.95, breath + shift * 0.3));
    }
    pacing[section] = scaled as PacingEntry;
  }
  style.pacing = pacing;

  // A user can switch on an effect the preset never declared; the bridge only
  // routes effects that exist as objects, so create one with engine defaults.
  const vfxFactor = Math.max(0, params.vfxIntensity) / 5;
  for (const effect of EFFECT_CATALOG) {
    const requested = params.effects[effect.key];
    const existing = style[effect.key];
    if (isEffectConfig(existing)) {
      if (params.vfxIntensity !== 5) {
        scaleMagnitudes(existing, vfxFactor);
      }
    } else if (requested === true) {
      style[effect.key] = { enabled: true };
    }
  }

  return style;
}

export function normalizeParameters(params: EditingParameters): EditingParameters {
  return {
    cutIntensity: params.cutIntensity,
    vfxIntensity: params.vfxIntensity,
    colorGrading: params.colorGrading,
    seed: params.seed,
    beatSubdivision: params.beatSubdivision,
    effects: { ...params.effects },
  };
}

/** Parse a hand-edited preset, rejecting anything the bridge cannot consume. */
export function parseStyleJson(text: string): StyleConfig {
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch (error) {
    throw new Error(`That is not valid JSON: ${(error as Error).message}`);
  }
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    throw new Error("A style must be a JSON object.");
  }
  const style = parsed as Partial<StyleConfig>;
  if (typeof style.style_name !== "string" || !style.style_name) {
    throw new Error('A style needs a "style_name" string.');
  }
  if (typeof style.display_name !== "string" || !style.display_name) {
    throw new Error('A style needs a "display_name" string.');
  }
  if (typeof style.cut_strategy !== "object" || style.cut_strategy === null) {
    throw new Error('A style needs a "cut_strategy" object.');
  }
  return style as StyleConfig;
}

export function styleToJson(style: StyleConfig): string {
  return JSON.stringify(style, null, 2);
}
