import React from "react";
import { createRoot } from "react-dom/client";

const SettingsApp: React.FC = () => {
  return (
    <div style={{
      padding: 16,
      background: "#1a1a2e",
      color: "#e0e0e0",
      fontFamily: "-apple-system, sans-serif",
      fontSize: 13,
      height: "100vh",
    }}>
      <h2 style={{ color: "#7c1629", marginBottom: 16 }}>FlagshipEditor Settings</h2>

      <div style={{ marginBottom: 16 }}>
        <label style={{ display: "block", marginBottom: 4, color: "#888" }}>
          Python Server Port
        </label>
        <input
          type="number"
          defaultValue={18791}
          style={inputStyle}
        />
      </div>

      <div style={{ marginBottom: 16 }}>
        <label style={{ display: "block", marginBottom: 4, color: "#888" }}>
          Default Comp Resolution
        </label>
        <select style={inputStyle}>
          <option>1920 × 1080</option>
          <option>3840 × 2160</option>
          <option>1080 × 1920 (Vertical)</option>
        </select>
      </div>

      <div style={{ marginBottom: 16 }}>
        <label style={{ display: "block", marginBottom: 4, color: "#888" }}>
          Default FPS
        </label>
        <select style={inputStyle}>
          <option>30</option>
          <option>24</option>
          <option>60</option>
          <option>25</option>
        </select>
      </div>

      <div style={{ marginBottom: 16 }}>
        <label style={{ display: "block", marginBottom: 4, color: "#888" }}>
          ProRes Codec
        </label>
        <select style={inputStyle}>
          <option>ProRes 422 (Standard)</option>
          <option>ProRes 422 HQ</option>
          <option>ProRes 422 LT</option>
          <option>ProRes 4444</option>
        </select>
      </div>

      <button style={{
        padding: "8px 16px",
        background: "#7c1629",
        color: "#fff",
        border: "none",
        borderRadius: 4,
        cursor: "pointer",
      }}>
        Save Settings
      </button>
    </div>
  );
};

const inputStyle: React.CSSProperties = {
  width: "100%",
  padding: "6px 8px",
  background: "#111122",
  color: "#e0e0e0",
  border: "1px solid #2a2a4a",
  borderRadius: 3,
  fontSize: 12,
};

const container = document.getElementById("root")!;
createRoot(container).render(<SettingsApp />);