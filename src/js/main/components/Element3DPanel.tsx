import React from "react";
import { Element3DSettings } from "../lib/styles";

export type Element3DDetectionState = "unknown" | "checking" | "installed" | "missing" | "error";

export interface Element3DDetection {
  state: Element3DDetectionState;
  matchName: string;
  message: string;
}

interface Props {
  settings: Element3DSettings;
  enabled: boolean;
  detection: Element3DDetection;
  disabled: boolean;
  onChange: (settings: Element3DSettings) => void;
  onToggleEnabled: (enabled: boolean) => void;
  onProbe: () => void;
}

const DETECTION_LABELS: Record<Element3DDetectionState, string> = {
  unknown: "Element 3D not checked yet",
  checking: "Checking After Effects…",
  installed: "Element 3D detected",
  missing: "Element 3D not installed",
  error: "Element 3D check failed",
};

const Element3DPanel: React.FC<Props> = ({
  settings,
  enabled,
  detection,
  disabled,
  onChange,
  onToggleEnabled,
  onProbe,
}) => {
  const pillClass = detection.state === "installed" ? "detected" : "missing";

  return (
    <div className="element3d-panel">
      <div className="info-card">
        <div className="info-card-icon">🧊</div>
        <div className="info-card-content">
          <div className="info-card-title">Element 3D integration</div>
          <div className="info-card-row">
            <span>Solid:</span>
            <span>FlagshipEditor_3D_Solid</span>
          </div>
          <div className="info-card-row">
            <span>Camera:</span>
            <span>FlagshipEditor_Camera</span>
          </div>
          {detection.state === "installed" && detection.matchName && (
            <div className="info-card-row">
              <span>Match name:</span>
              <span>{detection.matchName}</span>
            </div>
          )}
          <div className="info-card-row push-top">
            <span className={`status-pill ${pillClass}`}>
              <span className="status-dot-inline" />
              {DETECTION_LABELS[detection.state]}
            </span>
            <button className="link-btn" onClick={onProbe} disabled={disabled || detection.state === "checking"}>
              {detection.state === "checking" ? "Checking…" : "Check again"}
            </button>
          </div>
        </div>
      </div>

      {detection.state === "error" && detection.message && (
        <div className="alert alert-error alert-inline">{detection.message}</div>
      )}

      {detection.state === "missing" && (
        <div className="alert alert-warning alert-inline">
          The build skips the 3D layer entirely until Video Copilot Element 3D is installed. Every
          other effect still runs.
        </div>
      )}

      <label className="toggle-switch">
        <input
          type="checkbox"
          checked={enabled}
          onChange={(event) => onToggleEnabled(event.target.checked)}
          disabled={disabled}
        />
        <span className="toggle-track">
          <span className="toggle-thumb" />
        </span>
        <span className="toggle-label">Build the Element 3D layer</span>
      </label>

      <label className="toggle-switch">
        <input
          type="checkbox"
          checked={settings.autoCamera}
          onChange={(event) => onChange({ ...settings, autoCamera: event.target.checked })}
          disabled={disabled || !enabled}
        />
        <span className="toggle-track">
          <span className="toggle-thumb" />
        </span>
        <span className="toggle-label">Auto-create 3D camera</span>
      </label>

      <div className="param-row">
        <div className="slider-label-row">
          <span className="slider-label">Parallax depth</span>
          <span className="slider-value">{settings.parallaxDepth.toFixed(1)}</span>
        </div>
        <input
          type="range"
          min="0"
          max="1"
          step="0.1"
          value={settings.parallaxDepth}
          onChange={(event) =>
            onChange({ ...settings, parallaxDepth: Number(event.target.value) })
          }
          className="range-slider"
          data-value="true"
          style={{ "--value-percent": `${settings.parallaxDepth * 100}%` } as React.CSSProperties}
          disabled={disabled || !enabled}
          aria-label="Parallax depth"
        />
        <div className="param-hint">
          Drives the Z oscillation of the 3D layer against the camera. 0 keeps it locked flat.
        </div>
      </div>

      <div className="info-box">
        After generation, select the <strong>FlagshipEditor_3D_Solid</strong> layer and load your
        model into the Element 3D effect. The camera, parallax and depth animation are already set
        up on the comp.
      </div>
    </div>
  );
};

export default Element3DPanel;
