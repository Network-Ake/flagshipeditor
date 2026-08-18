import React, { useState } from "react";

const Element3DPanel: React.FC = () => {
  const [parallaxDepth, setParallaxDepth] = useState(0.3);
  const [autoCamera, setAutoCamera] = useState(true);

  return (
    <div>
      <div style={{ fontSize: 11, color: "#888", marginBottom: 8 }}>
        ELEMENT 3D
      </div>

      <div style={{
        padding: 10,
        background: "#111122",
        borderRadius: 3,
        marginBottom: 10,
        fontSize: 11,
      }}>
        <div style={{ marginBottom: 4 }}>
          <span style={{ color: "#888" }}>Solid:</span> FlagshipEditor_3D_Solid (auto)
        </div>
        <div style={{ marginBottom: 4 }}>
          <span style={{ color: "#888" }}>3D Camera:</span> FlagshipEditor_Camera (auto)
        </div>
        <div style={{ color: "#7c1629", marginTop: 6 }}>
          ⚠ Add Element 3D effect manually after generation
        </div>
      </div>

      <div style={{ marginBottom: 10 }}>
        <label style={{ display: "flex", alignItems: "center", fontSize: 12, cursor: "pointer" }}>
          <input
            type="checkbox"
            checked={autoCamera}
            onChange={(e) => setAutoCamera(e.target.checked)}
            style={{ marginRight: 8, accentColor: "#7c1629" }}
          />
          Auto-create 3D camera
        </label>
      </div>

      <div style={{ marginBottom: 10 }}>
        <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, marginBottom: 4 }}>
          <span>Parallax depth</span>
          <span style={{ color: "#7c1629" }}>{parallaxDepth.toFixed(1)}</span>
        </div>
        <input
          type="range"
          min="0"
          max="1"
          step="0.1"
          value={parallaxDepth}
          onChange={(e) => setParallaxDepth(parseFloat(e.target.value))}
          style={{ width: "100%", accentColor: "#7c1629" }}
        />
      </div>

      <div style={{
        padding: 10,
        background: "#0f0f1e",
        borderRadius: 3,
        fontSize: 11,
        color: "#888",
      }}>
        After generation, select the FlagshipEditor_3D_Solid layer,
        add the Element 3D effect, and load your 3D model.
        The camera and parallax are already set up.
      </div>
    </div>
  );
};

export default Element3DPanel;