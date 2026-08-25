// Section identity — one colour per song section, shared by every surface that
// draws the track (waveform, cut rows, section maps, regenerate pills).
//
// The values are duplicated as CSS custom properties in styles.css because SVG
// fills are computed in TypeScript while HTML surfaces are styled by attribute.
// Both read from this table, so a section can never wear two different colours.

export const SECTION_COLORS: Record<string, string> = {
  intro: "#3b82f6",
  verse: "#64748b",
  hook: "#a855f7",
  chorus: "#a855f7",
  drop: "#ef4444",
  build: "#f59e0b",
  bridge: "#f59e0b",
  breakdown: "#14b8a6",
  outro: "#3b82f6",
};

export const SECTION_FALLBACK = "#71717a";

export function sectionColor(type: string | undefined): string {
  if (!type) return SECTION_FALLBACK;
  return SECTION_COLORS[type.toLowerCase()] || SECTION_FALLBACK;
}

/** `0:00.0` — the timecode format used across the review surfaces. */
export function formatTimecode(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00.0";
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return `${minutes}:${rest.toFixed(1).padStart(4, "0")}`;
}

/** `0:00` — the coarser format used for axis labels and durations. */
export function formatClock(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00";
  const minutes = Math.floor(seconds / 60);
  const rest = Math.floor(seconds % 60);
  return `${minutes}:${rest.toString().padStart(2, "0")}`;
}
