import React from "react";
import type { BeatAnalysis } from "../lib/python";

interface Props {
  analysis: BeatAnalysis | null;
}

const AnalysisView: React.FC<Props> = ({ analysis }) => {
  if (!analysis) {
    return (
      <div style={{ fontSize: 11, color: "#555", padding: 8 }}>
        No analysis yet. Import media and click GENERATE.
      </div>
    );
  }

  return (
    <div>
      <div style={{ fontSize: 11, color: "#888", marginBottom: 8 }}>ANALYSIS</div>

      <div style={{
        padding: 10,
        background: "#111122",
        borderRadius: 3,
        marginBottom: 10,
        fontSize: 12,
      }}>
        <div>BPM: <span style={{ color: "#7c1629" }}>{analysis.tempo.toFixed(0)}</span></div>
        <div>Key: <span style={{ color: "#7c1629" }}>{analysis.key} {analysis.mode}</span></div>
        <div>Duration: <span style={{ color: "#7c1629" }}>{formatTime(analysis.duration)}</span></div>
      </div>

      <div style={{ fontSize: 11, color: "#888", marginBottom: 6 }}>SECTIONS</div>
      {analysis.sections.map((section, i) => (
        <div
          key={i}
          style={{
            display: "flex",
            justifyContent: "space-between",
            padding: "5px 8px",
            background: "#111122",
            borderRadius: 3,
            marginBottom: 3,
            fontSize: 11,
          }}
        >
          <span style={{ textTransform: "uppercase", fontWeight: 600 }}>
            {section.type}
          </span>
          <span style={{ color: "#888" }}>
            {formatTime(section.start)} - {formatTime(section.end)}
          </span>
        </div>
      ))}

      <div style={{ fontSize: 11, color: "#888", margin: "10px 0 6px" }}>ONSETS</div>
      <div style={{ fontSize: 11, padding: "5px 8px", background: "#111122", borderRadius: 3 }}>
        <div>808 hits: <span style={{ color: "#7c1629" }}>{analysis.bass_onsets.length}</span></div>
        <div>Hi-hat hits: <span style={{ color: "#7c1629" }}>{analysis.hihat_onsets.length}</span></div>
        <div>Total beats: <span style={{ color: "#7c1629" }}>{analysis.beats.length}</span></div>
      </div>
    </div>
  );
};

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export default AnalysisView;