import React from "react";
import type { BeatAnalysis } from "../lib/python";

interface Props {
  analysis: BeatAnalysis | null;
}

const SECTION_COLORS: Record<string, string> = {
  intro: "badge-accent",
  verse: "badge",
  hook: "badge-accent",
  chorus: "badge-accent",
  bridge: "badge-warning",
  outro: "badge-success",
};

const AnalysisView: React.FC<Props> = ({ analysis }) => {
  if (!analysis) {
    return (
      <div className="analysis-view">
        <div className="analysis-empty">
          No analysis yet. Import media and click GENERATE.
        </div>
      </div>
    );
  }

  return (
    <div className="analysis-view">
      {/* BPM hero */}
      <div className="bpm-hero">
        <span className="bpm-number">{analysis.tempo.toFixed(0)}</span>
        <span className="bpm-label">BPM</span>
        <span className="key-badge">
          {analysis.key} {analysis.mode}
        </span>
      </div>

      {/* Sections */}
      <div className="analysis-sections">
        <span className="section-title">Sections</span>
        {analysis.sections.map((section, i) => (
          <div key={i} className="section-row">
            <span className={`badge ${SECTION_COLORS[section.type] || "badge"}`}>
              {section.type}
            </span>
            <span className="section-time">
              {formatTime(section.start)} — {formatTime(section.end)}
            </span>
          </div>
        ))}
      </div>

      {/* Stats grid */}
      <div className="stats-grid">
        <div className="stat-card">
          <span className="stat-value">{analysis.bass_onsets.length}</span>
          <span className="stat-label">808 hits</span>
        </div>
        <div className="stat-card">
          <span className="stat-value">{analysis.hihat_onsets.length}</span>
          <span className="stat-label">Hi-hat hits</span>
        </div>
        <div className="stat-card">
          <span className="stat-value">{analysis.beats.length}</span>
          <span className="stat-label">Total beats</span>
        </div>
      </div>

      {/* Energy curve */}
      <div className="param-section">
        <span className="section-title">Energy curve</span>
        <div className="energy-curve" />
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
