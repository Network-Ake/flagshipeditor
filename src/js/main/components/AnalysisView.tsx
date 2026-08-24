import React, { useMemo } from "react";
import type { BeatAnalysis, BeatProgress, ClipInfo } from "../lib/python";

interface Props {
  analysis: BeatAnalysis | null;
  beatProgress: BeatProgress | null;
  clips: ClipInfo[];
  busy: boolean;
}

const SECTION_BADGES: Record<string, string> = {
  intro: "badge-accent",
  verse: "badge",
  hook: "badge-accent",
  chorus: "badge-accent",
  drop: "badge-error",
  bridge: "badge-warning",
  outro: "badge-success",
};

const CURVE_POINTS = 160;
const CURVE_HEIGHT = 40;

function formatTime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00";
  const minutes = Math.floor(seconds / 60);
  const rest = Math.floor(seconds % 60);
  return `${minutes}:${rest.toString().padStart(2, "0")}`;
}

/** Reduce the RMS curve to a fixed number of peaks so it draws in one pass. */
function buildCurve(energy: number[]): string {
  if (!energy || energy.length === 0) return "";
  const buckets = Math.min(CURVE_POINTS, energy.length);
  const perBucket = energy.length / buckets;
  const peaks: number[] = [];
  let maximum = 0;
  for (let index = 0; index < buckets; index += 1) {
    const start = Math.floor(index * perBucket);
    const end = Math.max(start + 1, Math.floor((index + 1) * perBucket));
    let peak = 0;
    for (let sample = start; sample < end && sample < energy.length; sample += 1) {
      const value = energy[sample];
      if (Number.isFinite(value) && value > peak) peak = value;
    }
    peaks.push(peak);
    if (peak > maximum) maximum = peak;
  }
  if (maximum <= 0) return "";
  const step = buckets > 1 ? 100 / (buckets - 1) : 100;
  const points: string[] = [];
  for (let index = 0; index < peaks.length; index += 1) {
    const x = (index * step).toFixed(3);
    const y = (CURVE_HEIGHT - (peaks[index] / maximum) * CURVE_HEIGHT).toFixed(3);
    points.push(`${x},${y}`);
  }
  return points.join(" ");
}

const AnalysisView: React.FC<Props> = ({ analysis, beatProgress, clips, busy }) => {
  const curve = useMemo(() => (analysis ? buildCurve(analysis.energy) : ""), [analysis]);

  const clipStats = useMemo(() => {
    const analyzed = clips.filter((clip) => clip.analyzed);
    const withFaces = analyzed.filter((clip) => clip.has_face).length;
    const sceneTypes = new Set(analyzed.map((clip) => clip.scene_type));
    return { analyzed: analyzed.length, withFaces, sceneTypes: sceneTypes.size };
  }, [clips]);

  if (!analysis) {
    return (
      <div className="analysis-view">
        {busy && beatProgress ? (
          <div className="analysis-progress">
            <div className="analysis-progress-step">{beatProgress.step || "Analysing the track…"}</div>
            <div className="progress-bar">
              <div
                className="progress-fill"
                style={{ width: `${Math.max(2, Math.min(100, beatProgress.progress))}%` }}
              />
            </div>
            <div className="param-hint">
              {Math.round(beatProgress.elapsedSeconds)}s elapsed · times out at{" "}
              {Math.round(beatProgress.timeoutSeconds)}s
            </div>
          </div>
        ) : (
          <div className="analysis-empty">
            No analysis yet. Import a track and clips, then press GENERATE EDIT.
          </div>
        )}
      </div>
    );
  }

  const duration = analysis.duration > 0 ? analysis.duration : 1;

  return (
    <div className="analysis-view">
      <div className="bpm-hero">
        <span className="bpm-number">{analysis.tempo.toFixed(0)}</span>
        <span className="bpm-label">BPM</span>
        <span className="key-badge">
          {analysis.key} {analysis.mode}
        </span>
      </div>

      <div className="param-section">
        <span className="section-title">Energy curve</span>
        <div className="energy-curve">
          {curve ? (
            <svg
              className="energy-svg"
              viewBox={`0 0 100 ${CURVE_HEIGHT}`}
              preserveAspectRatio="none"
              role="img"
              aria-label="Track energy over time"
            >
              <polyline className="energy-line" points={curve} />
              <polyline className="energy-area" points={`0,${CURVE_HEIGHT} ${curve} 100,${CURVE_HEIGHT}`} />
            </svg>
          ) : (
            <div className="empty-state">The track carries no measurable energy curve.</div>
          )}
        </div>
        <div className="curve-axis">
          <span>0:00</span>
          <span>{formatTime(analysis.duration)}</span>
        </div>
      </div>

      <div className="analysis-sections">
        <span className="section-title">Sections</span>
        <div className="section-map">
          {analysis.sections.map((section) => (
            <span
              key={`${section.type}-${section.start}`}
              className="section-map-block"
              data-section={section.type}
              title={`${section.type} · ${formatTime(section.start)} — ${formatTime(section.end)}`}
              style={{ flexGrow: Math.max(0.01, (section.end - section.start) / duration) }}
            />
          ))}
        </div>
        {analysis.sections.map((section) => (
          <div key={`${section.type}-row-${section.start}`} className="section-row">
            <span className={`badge ${SECTION_BADGES[section.type] || "badge"}`}>{section.type}</span>
            <span className="section-time">
              {formatTime(section.start)} — {formatTime(section.end)}
            </span>
          </div>
        ))}
      </div>

      <div className="stats-grid">
        <div className="stat-card">
          <span className="stat-value">{analysis.beats.length}</span>
          <span className="stat-label">Beats</span>
        </div>
        <div className="stat-card">
          <span className="stat-value">{analysis.downbeats.length}</span>
          <span className="stat-label">Downbeats</span>
        </div>
        <div className="stat-card">
          <span className="stat-value">{analysis.bass_onsets.length}</span>
          <span className="stat-label">808 hits</span>
        </div>
        <div className="stat-card">
          <span className="stat-value">{analysis.hihat_onsets.length}</span>
          <span className="stat-label">Hi-hat hits</span>
        </div>
        <div className="stat-card">
          <span className="stat-value">{formatTime(analysis.duration)}</span>
          <span className="stat-label">Track length</span>
        </div>
        <div className="stat-card">
          <span className="stat-value">{analysis.sections.length}</span>
          <span className="stat-label">Sections</span>
        </div>
      </div>

      <div className="param-section">
        <span className="section-title">Clip library</span>
        <div className="stats-grid">
          <div className="stat-card">
            <span className="stat-value">{clipStats.analyzed}</span>
            <span className="stat-label">Analysed clips</span>
          </div>
          <div className="stat-card">
            <span className="stat-value">{clipStats.withFaces}</span>
            <span className="stat-label">With faces</span>
          </div>
          <div className="stat-card">
            <span className="stat-value">{clipStats.sceneTypes}</span>
            <span className="stat-label">Scene types</span>
          </div>
        </div>
      </div>
    </div>
  );
};

export default AnalysisView;
