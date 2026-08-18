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

  const updateParam = (key: keyof ParamState, value: number | boolean) => {
    setParams({ ...params, [key]: value });
  };

  return (
    <div>
      <div style={{ fontSize: 11, color: "#888", marginBottom: 8 }}>PARAMETERS</div>

      {/* Sliders */}
      {([
        ["cutIntensity", "Cut intensity"],
        ["vfxIntensity", "VFX intensity"],
        ["colorGrading", "Color grading"],
        ["textOverlays", "Text overlays"],
      ] as [keyof ParamState, string][]).map(([key, label]) => (
        <div key={key} style={{ marginBottom: 10 }}>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, marginBottom: 4 }}>
            <span>{label}</span>
            <span style={{ color: "#7c1629" }}>{params[key] as number}/10</span>
          </div>
          <input
            type="range"
            min="0"
            max="10"
            value={params[key] as number}
            onChange={(e) => updateParam(key, parseInt(e.target.value))}
            style={{ width: "100%", accentColor: "#7c1629" }}
          />
        </div>
      ))}

      {/* Toggles */}
      <div style={{ fontSize: 11, color: "#888", margin: "12px 0 8px" }}>EFFECTS</div>
      {([
        ["zoomPunch", "Zoom punches"],
        ["whipPan", "Whip pans"],
        ["cameraShake", "Camera shake"],
        ["glitch", "Glitch on 808"],
        ["element3d", "Element 3D solid (auto)"],
        ["faceMask", "Face mask (auto)"],
        ["smokeFog", "Smoke/fog"],
      ] as [keyof ParamState, string][]).map(([key, label]) => (
        <label
          key={key}
          style={{
            display: "flex",
            alignItems: "center",
            padding: "5px 0",
            fontSize: 12,
            cursor: "pointer",
          }}
        >
          <input
            type="checkbox"
            checked={params[key] as boolean}
            onChange={(e) => updateParam(key, e.target.checked)}
            style={{ marginRight: 8, accentColor: "#7c1629" }}
          />
          {label}
        </label>
      ))}
    </div>
  );
};

export default Parameters;