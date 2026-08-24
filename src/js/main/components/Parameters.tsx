import React, { useState } from "react";

interface ParamState {
  cutIntensity: number;
  vfxIntensity: number;
  colorGrading: number;
  textOverlays: number;
  zoomPunch: boolean;
  whipPan: boolean;
  cameraShake: boolean;
  glitch: boolean;
  element3d: boolean;
  faceMask: boolean;
  smokeFog: boolean;
}

const PRESETS = [
  { id: "subtle", label: "Subtle" },
  { id: "balanced", label: "Balanced" },
  { id: "aggressive", label: "Aggressive" },
  { id: "custom", label: "Custom" },
];

const PRESET_VALUES: Record<string, Partial<ParamState>> = {
  subtle: {
    cutIntensity: 4,
    vfxIntensity: 3,
    colorGrading: 5,
    textOverlays: 2,
    zoomPunch: false,
    whipPan: false,
    cameraShake: false,
    glitch: false,
    element3d: false,
    faceMask: false,
    smokeFog: false,
  },
  balanced: {
    cutIntensity: 7,
    vfxIntensity: 5,
    colorGrading: 6,
    textOverlays: 4,
    zoomPunch: true,
    whipPan: true,
    cameraShake: false,
    glitch: true,
    element3d: true,
    faceMask: true,
    smokeFog: false,
  },
  aggressive: {
    cutIntensity: 10,
    vfxIntensity: 9,
    colorGrading: 8,
    textOverlays: 7,
    zoomPunch: true,
    whipPan: true,
    cameraShake: true,
    glitch: true,
    element3d: true,
    faceMask: true,
    smokeFog: true,
  },
};

const SLIDERS: { key: keyof ParamState; label: string }[] = [
  { key: "cutIntensity", label: "Cut intensity" },
  { key: "vfxIntensity", label: "VFX intensity" },
  { key: "colorGrading", label: "Color grading" },
  { key: "textOverlays", label: "Text overlays" },
];

const TOGGLES: { key: keyof ParamState; label: string; group: "cut" | "vfx" | "color" | "3d" }[] = [
  { key: "zoomPunch", label: "Zoom punches", group: "cut" },
  { key: "whipPan", label: "Whip pans", group: "cut" },
  { key: "cameraShake", label: "Camera shake", group: "vfx" },
  { key: "glitch", label: "Glitch on 808", group: "vfx" },
  { key: "element3d", label: "Element 3D solid", group: "3d" },
  { key: "faceMask", label: "Face mask", group: "vfx" },
  { key: "smokeFog", label: "Smoke / fog", group: "color" },
];

const GROUP_ICONS: Record<string, string> = {
  cut: "✂️",
  vfx: "✨",
  color: "🎨",
  "3d": "🧊",
};

const Parameters: React.FC = () => {
  const [params, setParams] = useState<ParamState>({
    cutIntensity: 8,
    vfxIntensity: 6,
    colorGrading: 7,
    textOverlays: 5,
    zoomPunch: true,
    whipPan: true,
    cameraShake: true,
    glitch: true,
    element3d: true,
    faceMask: true,
    smokeFog: false,
  });
  const [activePreset, setActivePreset] = useState("custom");

  const updateParam = (key: keyof ParamState, value: number | boolean) => {
    setParams((prev) => ({ ...prev, [key]: value }));
    setActivePreset("custom");
  };

  const applyPreset = (id: string) => {
    if (id === "custom") return;
    const values = PRESET_VALUES[id];
    if (values) {
      setParams((prev) => ({ ...prev, ...values }));
    }
    setActivePreset(id);
  };

  const groupedToggles = TOGGLES.reduce((acc, toggle) => {
    if (!acc[toggle.group]) acc[toggle.group] = [];
    acc[toggle.group].push(toggle);
    return acc;
  }, {} as Record<string, typeof TOGGLES>);

  const sliderStyle = (value: number) => ({
    "--value-percent": `${value * 10}%`,
  } as React.CSSProperties);

  return (
    <div className="parameters">
      {/* Preset chips */}
      <div className="preset-chips">
        {PRESETS.map((preset) => (
          <button
            key={preset.id}
            className={`preset-chip ${activePreset === preset.id ? "active" : ""}`}
            onClick={() => applyPreset(preset.id)}
          >
            {preset.label}
          </button>
        ))}
      </div>

      {/* Sliders */}
      <div className="param-section">
        <div className="param-section-title">
          <span>{GROUP_ICONS.cut}</span> Cut
        </div>
        {SLIDERS.map(({ key, label }) => (
          <div key={key} className="param-row">
            <div className="slider-label-row">
              <span className="slider-label">{label}</span>
              <span className="slider-value">{params[key] as number}/10</span>
            </div>
            <input
              type="range"
              min="0"
              max="10"
              value={params[key] as number}
              onChange={(e) => updateParam(key, parseInt(e.target.value))}
              className="range-slider"
              data-value="true"
              style={sliderStyle(params[key] as number)}
            />
          </div>
        ))}
      </div>

      {/* Toggles grouped */}
      {Object.entries(groupedToggles).map(([group, toggles]) => (
        <div key={group} className="param-section">
          <div className="param-section-title">
            <span>{GROUP_ICONS[group]}</span> {group === "3d" ? "3D" : group.charAt(0).toUpperCase() + group.slice(1)}
          </div>
          <div className="param-toggles">
            {toggles.map(({ key, label }) => (
              <label key={key} className="toggle-switch">
                <input
                  type="checkbox"
                  checked={params[key] as boolean}
                  onChange={(e) => updateParam(key, e.target.checked)}
                />
                <span className="toggle-track">
                  <span className="toggle-thumb" />
                </span>
                <span className="toggle-label">{label}</span>
              </label>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
};

export default Parameters;
