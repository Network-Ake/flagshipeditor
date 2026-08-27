// Deterministic regression test for generate-luts.mjs.
//
// Regenerates the LUTs into a scratch directory (never the repo's luts/) and
// checks the two properties the grade pipeline must hold: every emitted value
// sits inside [0, 1], and the luma used for the saturation mix is measured on
// the *clamped* channels — the original code measured it before clamping, so
// contrast/exposure overshoot skewed the mix.

import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptsDir = path.dirname(fileURLToPath(import.meta.url));
const generateScript = path.join(scriptsDir, "generate-luts.mjs");

const SIZE = 17;
const clamp = (value) => Math.max(0, Math.min(1, value));

// Reference implementation of the corrected pipeline: gamma, contrast,
// exposure+tint, clamp, then saturation mixed around the clamped luma.
function gradeReference(rgb, preset) {
  let values = rgb.map((value) => Math.pow(value, preset.gamma));
  values = values.map((value) => (value - 0.5) * preset.contrast + 0.5);
  values = values.map((value, channel) => value * preset.exposure + preset.tint[channel]);
  values = values.map(clamp);
  const luma = values[0] * 0.2126 + values[1] * 0.7152 + values[2] * 0.0722;
  return values.map((value) => clamp(luma + (value - luma) * preset.saturation));
}

// This preset overshoots 1.0 on blue at the white corner before clamping, so
// it distinguishes clamped-luma output from the pre-clamp ordering.
const NEON_DARK = {
  file: "worldwide_neon_dark.cube",
  preset: { exposure: 0.88, contrast: 1.2, gamma: 0.93, tint: [0.018, -0.018, 0.035], saturation: 1.24 },
};

const fixture = fs.mkdtempSync(path.join(os.tmpdir(), "flagship-luts-"));
try {
  execFileSync(process.execPath, [generateScript], { cwd: fixture, stdio: "pipe" });

  const generated = fs.readdirSync(path.join(fixture, "luts")).sort();
  assert.equal(generated.length, 7, "all seven presets are generated");

  for (const filename of generated) {
    const lines = fs.readFileSync(path.join(fixture, "luts", filename), "utf8").trim().split("\n");
    assert.equal(lines[1], `LUT_3D_SIZE ${SIZE}`, `${filename} declares its size`);
    const rows = lines.slice(4);
    assert.equal(rows.length, SIZE * SIZE * SIZE, `${filename} has a full ${SIZE}^3 grid`);
    for (const row of rows) {
      for (const field of row.split(" ")) {
        const value = Number(field);
        assert.ok(Number.isFinite(value) && value >= 0 && value <= 1, `${filename}: out-of-range value ${field}`);
      }
    }
  }

  const lines = fs
    .readFileSync(path.join(fixture, "luts", NEON_DARK.file), "utf8")
    .trim()
    .split("\n")
    .slice(4);
  let index = 0;
  for (let blue = 0; blue < SIZE; blue += 1) {
    for (let green = 0; green < SIZE; green += 1) {
      for (let red = 0; red < SIZE; red += 1) {
        const expected = gradeReference(
          [red / (SIZE - 1), green / (SIZE - 1), blue / (SIZE - 1)],
          NEON_DARK.preset
        );
        const actual = lines[index].split(" ").map(Number);
        for (let channel = 0; channel < 3; channel += 1) {
          assert.ok(
            Math.abs(actual[channel] - expected[channel]) < 1e-6,
            `${NEON_DARK.file} grid point ${index} channel ${channel}: ${actual[channel]} != ${expected[channel]}`
          );
        }
        index += 1;
      }
    }
  }

  // Prove the fixture preset actually exercises the defect: the white corner
  // must overshoot before clamping, and the old pre-clamp luma ordering must
  // produce a different mix there.
  const white = [1, 1, 1];
  const raw = white
    .map((value) => Math.pow(value, NEON_DARK.preset.gamma))
    .map((value) => (value - 0.5) * NEON_DARK.preset.contrast + 0.5)
    .map((value, channel) => value * NEON_DARK.preset.exposure + NEON_DARK.preset.tint[channel]);
  assert.ok(raw.some((value) => value > 1), "fixture preset overshoots before clamping");
  const oldLuma = raw[0] * 0.2126 + raw[1] * 0.7152 + raw[2] * 0.0722;
  const oldMix = raw.map((value) => clamp(oldLuma + (value - oldLuma) * NEON_DARK.preset.saturation));
  const corrected = gradeReference(white, NEON_DARK.preset);
  assert.ok(
    oldMix.some((value, channel) => Math.abs(value - corrected[channel]) > 1e-6),
    "clamped-luma output differs from the pre-clamp ordering at the white corner"
  );

  console.log("generate-luts regression test passed (range, grid, clamped-luma saturation mix).");
} finally {
  fs.rmSync(fixture, { recursive: true, force: true });
}
