import fs from "node:fs";
import path from "node:path";

const root = process.cwd();
const output = path.join(root, "luts");
const size = 17;

const presets = {
  "cmd_command_dark_cold.cube": { exposure: 0.86, contrast: 1.12, gamma: 0.96, tint: [-0.018, -0.005, 0.035], saturation: 0.88 },
  "jack_rottier_cinematic.cube": { exposure: 0.94, contrast: 1.08, gamma: 0.98, tint: [0.018, 0.002, -0.012], saturation: 0.82 },
  "lyrical_lemonade_neon.cube": { exposure: 1.02, contrast: 1.15, gamma: 0.94, tint: [0.022, -0.008, 0.028], saturation: 1.22 },
  "lyrical_lemonade_vibrant.cube": { exposure: 1.03, contrast: 1.08, gamma: 0.95, tint: [0.018, 0.008, 0.012], saturation: 1.18 },
  "ninetive_clean.cube": { exposure: 1.01, contrast: 1.03, gamma: 0.99, tint: [0.004, 0.003, 0.006], saturation: 1.04 },
  "worldwide_dark.cube": { exposure: 0.82, contrast: 1.16, gamma: 0.98, tint: [-0.008, -0.012, 0.02], saturation: 0.84 },
  "worldwide_neon_dark.cube": { exposure: 0.88, contrast: 1.2, gamma: 0.93, tint: [0.018, -0.018, 0.035], saturation: 1.24 },
};

function clamp(value) {
  return Math.max(0, Math.min(1, value));
}

function grade(rgb, preset) {
  let values = rgb.map((value) => Math.pow(value, preset.gamma));
  values = values.map((value) => (value - 0.5) * preset.contrast + 0.5);
  values = values.map((value, channel) => value * preset.exposure + preset.tint[channel]);
  const luma = values[0] * 0.2126 + values[1] * 0.7152 + values[2] * 0.0722;
  return values.map((value) => clamp(luma + (value - luma) * preset.saturation));
}

fs.mkdirSync(output, { recursive: true });
for (const [filename, preset] of Object.entries(presets)) {
  const lines = [
    `TITLE "FlagshipEditor original preset: ${filename}"`,
    `LUT_3D_SIZE ${size}`,
    "DOMAIN_MIN 0.0 0.0 0.0",
    "DOMAIN_MAX 1.0 1.0 1.0",
  ];
  for (let blue = 0; blue < size; blue += 1) {
    for (let green = 0; green < size; green += 1) {
      for (let red = 0; red < size; red += 1) {
        const graded = grade(
          [red / (size - 1), green / (size - 1), blue / (size - 1)],
          preset,
        );
        lines.push(graded.map((value) => value.toFixed(6)).join(" "));
      }
    }
  }
  fs.writeFileSync(path.join(output, filename), `${lines.join("\n")}\n`);
}

console.log(`Generated ${Object.keys(presets).length} original 17-point LUTs.`);
