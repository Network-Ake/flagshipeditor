import React, { useState } from "react";

const Element3DPanel: React.FC = () => {
  const [parallaxDepth, setParallaxDepth] = useState(0.3);
  const [autoCamera, setAutoCamera] = useState(true);
  const [elementDetected] = useState(false);

  return (
    <div className="element3d-panel">
      {/* Info card */}
      <div className="info-card">
        <div className="info-card-icon">🧊</div>
        <div className="info-card-content">
          <div className="info-card-title">Element 3D Integration</div>
          <div className="info-card-row">
            <span>Solid:</span>
            <span>FlagshipEditor_3D_Solid</span>
          </div>
          <div className="info-card-row">
            <span>Camera:</span>
            <span>FlagshipEditor_Camera</span>
          </div>
          <div className="info-card-row push-top">
            <span className={`status-pill ${elementDetected ? "detected" : "missing"}`}>
              <span className="status-dot-inline" />
              {elementDetected ? "Element 3D detected" : "Element 3D not detected"}
            </span>
          </div>
        </div>
      </div>

      {/* Auto camera toggle */}
      <label className="toggle-switch">
        <input
          type="checkbox"
          checked={autoCamera}
          onChange={(e) => setAutoCamera(e.target.checked)}
        />
        <span className="toggle-track">
          <span className="toggle-thumb" />
        </span>
        <span className="toggle-label">Auto-create 3D camera</span>
      </label>

      {/* Parallax slider */}
      <div className="param-row">
        <div className="slider-label-row">
          <span className="slider-label">Parallax depth</span>
          <span className="slider-value">{parallaxDepth.toFixed(1)}</span>
        </div>
        <input
          type="range"
          min="0"
          max="1"
          step="0.1"
          value={parallaxDepth}
          onChange={(e) => setParallaxDepth(parseFloat(e.target.value))}
          className="range-slider"
          data-value="true"
          style={{ "--value-percent": `${parallaxDepth * 100}%` } as React.CSSProperties}
        />
      </div>

      {/* Info box */}
      <div className="info-box">
        After generation, select the <strong>FlagshipEditor_3D_Solid</strong> layer,
        add the Element 3D effect, and load your 3D model. The camera and parallax
        are already set up.
      </div>
    </div>
  );
};

export default Element3DPanel;
