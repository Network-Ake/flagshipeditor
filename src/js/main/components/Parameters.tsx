import React, { useMemo } from "react";
import {
  EFFECT_CATALOG,
  EFFECT_GROUP_LABELS,
  EditingParameters,
  EffectGroup,
  StyleConfig,
  isEffectConfig,
} from "../lib/styles";

interface Props {
  params: EditingParameters;
  style: StyleConfig;
  disabled: boolean;
  onChange: (params: EditingParameters) => void;
  onResetToStyle: () => void;
}

interface IntensityPreset {
  id: string;
  label: string;
  cutIntensity: number;
  vfxIntensity: number;
  colorGrading: number;
}

const INTENSITY_PRESETS: IntensityPreset[] = [
  { id: "subtle", label: "Subtle", cutIntensity: 4, vfxIntensity: 3, colorGrading: 5 },
  { id: "balanced", label: "Balanced", cutIntensity: 7, vfxIntensity: 5, colorGrading: 6 },
  { id: "aggressive", label: "Aggressive", cutIntensity: 10, vfxIntensity: 9, colorGrading: 8 },
];

const SLIDERS: { key: "cutIntensity" | "vfxIntensity" | "colorGrading"; label: string; hint: string }[] = [
  { key: "cutIntensity", label: "Cut intensity", hint: "10 doubles the cut density of the preset, 0 halves it." },
  { key: "vfxIntensity", label: "VFX intensity", hint: "Scales every effect magnitude. 0 disables all VFX." },
  { key: "colorGrading", label: "Color grading", hint: "Opacity of the LUT adjustment layer. 0 skips grading." },
];

// Multiplies the preset's pacing range. The engine works in bars and varies
// each shot inside the range, so this shifts the *feel* rather than selecting a
// subdivision — the fixed 1/4, 1/8, 1/16 picker this replaces is precisely what
// made every section cut at one rate.
const SHOT_LENGTH_PRESETS: { label: string; value: number }[] = [
  { label: "Long", value: 1.6 },
  { label: "Natural", value: 1 },
  { label: "Short", value: 0.65 },
];

const GROUP_ICONS: Record<EffectGroup, string> = {
  cut: "✂️",
  camera: "🎥",
  texture: "🎞",
  color: "🎨",
  time: "⏱",
};

const GROUP_ORDER: EffectGroup[] = ["cut", "camera", "texture", "time", "color"];

function sliderStyle(value: number): React.CSSProperties {
  return { "--value-percent": `${value * 10}%` } as React.CSSProperties;
}

const Parameters: React.FC<Props> = ({ params, style, disabled, onChange, onResetToStyle }) => {
  const activePreset = useMemo(() => {
    const match = INTENSITY_PRESETS.find(
      (preset) =>
        preset.cutIntensity === params.cutIntensity &&
        preset.vfxIntensity === params.vfxIntensity &&
        preset.colorGrading === params.colorGrading
    );
    return match ? match.id : "custom";
  }, [params.cutIntensity, params.vfxIntensity, params.colorGrading]);

  const grouped = useMemo(() => {
    const map = new Map<EffectGroup, typeof EFFECT_CATALOG>();
    for (const group of GROUP_ORDER) map.set(group, []);
    for (const effect of EFFECT_CATALOG) {
      const bucket = map.get(effect.group);
      if (bucket) bucket.push(effect);
    }
    return map;
  }, []);

  const enabledCount = EFFECT_CATALOG.filter((effect) => params.effects[effect.key] === true).length;

  const setNumber = (key: "cutIntensity" | "vfxIntensity" | "colorGrading", value: number) => {
    onChange({ ...params, [key]: value });
  };

  const applyPreset = (preset: IntensityPreset) => {
    onChange({
      ...params,
      cutIntensity: preset.cutIntensity,
      vfxIntensity: preset.vfxIntensity,
      colorGrading: preset.colorGrading,
    });
  };

  const toggleEffect = (key: string, enabled: boolean) => {
    onChange({ ...params, effects: { ...params.effects, [key]: enabled } });
  };

  const setSeed = (raw: string) => {
    const parsed = Number.parseInt(raw, 10);
    onChange({ ...params, seed: Number.isFinite(parsed) && parsed > 0 ? parsed : 1 });
  };

  return (
    <div className="parameters">
      <div className="preset-chips">
        {INTENSITY_PRESETS.map((preset) => (
          <button
            key={preset.id}
            type="button"
            className={`preset-chip ${activePreset === preset.id ? "active" : ""}`}
            onClick={() => applyPreset(preset)}
            disabled={disabled}
          >
            {preset.label}
          </button>
        ))}
        <button
          type="button"
          className={`preset-chip ${activePreset === "custom" ? "active" : ""}`}
          disabled
        >
          Custom
        </button>
      </div>

      <div className="param-section">
        <div className="param-section-title">
          <span>🎚</span> Intensity
        </div>
        {SLIDERS.map(({ key, label, hint }) => (
          <div key={key} className="param-row">
            <div className="slider-label-row">
              <span className="slider-label">{label}</span>
              <span className="slider-value">{params[key]}/10</span>
            </div>
            <input
              type="range"
              min="0"
              max="10"
              step="1"
              value={params[key]}
              onChange={(event) => setNumber(key, Number(event.target.value))}
              className="range-slider"
              data-value="true"
              style={sliderStyle(params[key])}
              disabled={disabled}
              aria-label={label}
            />
            <div className="param-hint">{hint}</div>
          </div>
        ))}
      </div>

      <div className="param-section">
        <div className="param-section-title">
          <span>🎯</span> Timing &amp; repeatability
        </div>
        <div className="param-row">
          <div className="slider-label-row">
            <span className="slider-label">Shot length</span>
          </div>
          <div className="segmented">
            {SHOT_LENGTH_PRESETS.map((option) => (
              <button
                key={option.label}
                type="button"
                className={`segmented-item ${params.beatSubdivision === option.value ? "active" : ""}`}
                onClick={() => onChange({ ...params, beatSubdivision: option.value })}
                disabled={disabled}
              >
                {option.label}
              </button>
            ))}
          </div>
          <div className="param-hint">
            Scales how long shots run, in bars. The engine varies every shot inside
            that range and lands each cut on a real musical event, so no setting
            produces a fixed 1/4, 1/8 or 1/16 grid.
          </div>
        </div>

        <div className="param-row">
          <div className="slider-label-row">
            <span className="slider-label">Random seed</span>
            <span className="slider-value">{params.seed}</span>
          </div>
          <div className="seed-row">
            <input
              type="number"
              min="1"
              max="999999"
              step="1"
              className="number-input"
              value={params.seed}
              onChange={(event) => setSeed(event.target.value)}
              disabled={disabled}
              aria-label="Random seed"
            />
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={() => onChange({ ...params, seed: 1 + Math.floor(Math.random() * 999998) })}
              disabled={disabled}
            >
              🎲 Shuffle
            </button>
          </div>
          <div className="param-hint">
            The same seed, clips and track always produce the same edit.
          </div>
        </div>
      </div>

      <div className="param-section">
        <div className="param-section-title">
          <span>✨</span> Effects
          <span className="badge">{enabledCount}/{EFFECT_CATALOG.length}</span>
          <button className="link-btn" onClick={onResetToStyle} disabled={disabled}>
            Reset to {style.display_name}
          </button>
        </div>
        {params.vfxIntensity === 0 && (
          <div className="alert alert-warning alert-inline">
            VFX intensity is 0 — every effect below is skipped at build time.
          </div>
        )}
      </div>

      {GROUP_ORDER.map((group) => {
        const effects = grouped.get(group) || [];
        if (effects.length === 0) return null;
        return (
          <div key={group} className="param-section">
            <div className="param-section-title">
              <span>{GROUP_ICONS[group]}</span> {EFFECT_GROUP_LABELS[group]}
            </div>
            <div className="param-toggles">
              {effects.map((effect) => {
                const declared = isEffectConfig(style[effect.key]);
                return (
                  <label key={effect.key} className="toggle-switch">
                    <input
                      type="checkbox"
                      checked={params.effects[effect.key] === true}
                      onChange={(event) => toggleEffect(effect.key, event.target.checked)}
                      disabled={disabled}
                    />
                    <span className="toggle-track">
                      <span className="toggle-thumb" />
                    </span>
                    <span className="toggle-label">{effect.label}</span>
                    {!declared && <span className="badge badge-warning">engine default</span>}
                  </label>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
};

export default Parameters;
