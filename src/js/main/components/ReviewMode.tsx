import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CutAlternative, CutDecision, BeatAnalysis, thumbnailUrl } from "../lib/python";

interface Props {
  cuts: CutDecision[];
  busy: boolean;
  onSwap: (indices: number[], alternative: CutAlternative) => void;
  onToggleLock: (index: number) => void;
  onReorder: (from: number, to: number) => void;
  onRegenerateSection: (sectionType: string) => void;
  beatAnalysis?: BeatAnalysis | null;
}

const SECTION_COLORS: Record<string, string> = {
  intro: "#3b82f6",
  verse: "#71717a",
  chorus: "#8b5cf6",
  drop: "#ef4444",
  outro: "#3b82f6",
  bridge: "#10b981",
};

const SCORE_KEYS: { key: string; label: string }[] = [
  { key: "composition_score", label: "Composition" },
  { key: "energy_score", label: "Energy" },
  { key: "variety_score", label: "Variety" },
  { key: "sharpness_score", label: "Sharpness" },
  { key: "stability_score", label: "Stability" },
  { key: "face_quality_score", label: "Face quality" },
];

function formatTime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00.0";
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return `${minutes}:${rest.toFixed(1).padStart(4, "0")}`;
}

function sectionColor(type: string): string {
  return SECTION_COLORS[type] || "#71717a";
}

// ── Thumbnail ──────────────────────────────────────────────────────────────

const Thumbnail: React.FC<{ thumbnailId: string; alt: string; w?: number; h?: number }> = ({
  thumbnailId,
  alt,
  w,
  h,
}) => {
  const [broken, setBroken] = useState(false);
  const source = thumbnailUrl(thumbnailId);
  const style: React.CSSProperties = {};
  if (w) style.width = w;
  if (h) style.height = h;

  if (!source || broken)
    return (
      <span className="cut-thumbnail-fallback" style={style} role="img" aria-label={`No preview for ${alt}`}>
        🎬
      </span>
    );
  return <img src={source} alt={alt} loading="lazy" style={style} onError={() => setBroken(true)} />;
};

// ── Waveform strip ─────────────────────────────────────────────────────────

const WAVEFORM_HEIGHT = 80;

const WaveformStrip: React.FC<{
  cuts: CutDecision[];
  beat: BeatAnalysis | null;
  selected: number;
  onSelect: (index: number) => void;
}> = ({ cuts, beat, selected, onSelect }) => {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const width = 1000; // viewBox width; CSS scales it

  const timelineEnd = useMemo(() => {
    let end = 0;
    for (const c of cuts) if (c.endTime > end) end = c.endTime;
    return end > 0 ? end : beat?.duration ?? 1;
  }, [cuts, beat]);

  const energy = beat?.energy ?? [];
  const beats = beat?.beats ?? [];
  const downbeats = beat?.downbeats ?? [];
  const bassOnsets = beat?.bass_onsets ?? [];
  const sections = beat?.sections ?? [];

  const energyMax = useMemo(() => {
    let max = 0;
    for (const v of energy) if (v > max) max = v;
    return max > 0 ? max : 1;
  }, [energy]);

  const xForTime = useCallback(
    (t: number) => (timelineEnd > 0 ? (t / timelineEnd) * width : 0),
    [timelineEnd, width]
  );

  // Build waveform path from energy samples
  const waveformPath = useMemo(() => {
    if (energy.length === 0) return "";
    const step = width / energy.length;
    let path = `M 0 ${WAVEFORM_HEIGHT / 2}`;
    for (let i = 0; i < energy.length; i++) {
      const x = i * step;
      const h = (energy[i] / energyMax) * (WAVEFORM_HEIGHT / 2 - 4);
      path += ` L ${x.toFixed(1)} ${(WAVEFORM_HEIGHT / 2 - h).toFixed(1)}`;
    }
    // mirror down
    for (let i = energy.length - 1; i >= 0; i--) {
      const x = i * step;
      const h = (energy[i] / energyMax) * (WAVEFORM_HEIGHT / 2 - 4);
      path += ` L ${x.toFixed(1)} ${(WAVEFORM_HEIGHT / 2 + h).toFixed(1)}`;
    }
    path += " Z";
    return path;
  }, [energy, energyMax, width]);

  return (
    <div className="review-waveform">
      <svg
        ref={svgRef}
        viewBox={`0 0 ${width} ${WAVEFORM_HEIGHT}`}
        preserveAspectRatio="none"
        style={{ width: "100%", height: WAVEFORM_HEIGHT }}
      >
        {/* Section bands */}
        {sections.map((sec, i) => {
          const x1 = xForTime(sec.start);
          const x2 = xForTime(sec.end);
          return (
            <rect
              key={`sec-${i}`}
              x={x1}
              y={0}
              width={Math.max(0, x2 - x1)}
              height={WAVEFORM_HEIGHT}
              fill={sectionColor(sec.type)}
              opacity={0.12}
            />
          );
        })}

        {/* Waveform */}
        {waveformPath && <path d={waveformPath} fill="rgba(120,120,140,0.35)" />}

        {/* Beat lines */}
        {beats.map((b, i) => {
          const x = xForTime(b);
          const isDown = downbeats.indexOf(b) !== -1;
          return (
            <line
              key={`beat-${i}`}
              x1={x}
              y1={isDown ? 4 : 12}
              x2={x}
              y2={isDown ? WAVEFORM_HEIGHT - 4 : WAVEFORM_HEIGHT - 12}
              stroke={isDown ? "rgba(255,255,255,0.5)" : "rgba(255,255,255,0.18)"}
              strokeWidth={isDown ? 1.5 : 0.8}
            />
          );
        })}

        {/* Bass onsets */}
        {bassOnsets.map((b, i) => {
          const x = xForTime(b);
          return (
            <circle
              key={`bass-${i}`}
              cx={x}
              cy={WAVEFORM_HEIGHT - 6}
              r={2.5}
              fill="#f59e0b"
              opacity={0.85}
            />
          );
        })}

        {/* Cut markers (triangles) */}
        {cuts.map((cut, i) => {
          const x = xForTime(cut.beatTime);
          const isSel = i === selected;
          const triColor = isSel ? "#fff" : "rgba(255,255,255,0.6)";
          const size = isSel ? 7 : 5;
          return (
            <g key={`cut-${i}`} onClick={() => onSelect(i)} style={{ cursor: "pointer" }}>
              <polygon
                points={`${x - size},2 ${x + size},2 ${x},${2 + size * 1.4}`}
                fill={triColor}
              />
            </g>
          );
        })}
      </svg>
    </div>
  );
};

// ── Cut list ───────────────────────────────────────────────────────────────

const CutList: React.FC<{
  cuts: CutDecision[];
  selected: number;
  busy: boolean;
  onSelect: (index: number) => void;
  onReorder: (from: number, to: number) => void;
}> = ({ cuts, selected, busy, onSelect, onReorder }) => {
  const [dragIndex, setDragIndex] = useState<number | null>(null);
  const [dropIndex, setDropIndex] = useState<number | null>(null);

  const handleDrop = (target: number) => {
    if (dragIndex !== null && dragIndex !== target) onReorder(dragIndex, target);
    setDragIndex(null);
    setDropIndex(null);
  };

  return (
    <div className="review-cut-list">
      {cuts.map((cut, index) => (
        <div
          key={`${cut.beatTime}-${index}`}
          className={`cut-row${index === selected ? " selected" : ""}${cut.locked ? " locked" : ""}${
            dropIndex === index ? " drop-target" : ""
          }`}
          onClick={() => onSelect(index)}
          draggable={!busy}
          onDragStart={() => setDragIndex(index)}
          onDragEnd={() => {
            setDragIndex(null);
            setDropIndex(null);
          }}
          onDragOver={(e) => {
            e.preventDefault();
            if (dropIndex !== index) setDropIndex(index);
          }}
          onDrop={(e) => {
            e.preventDefault();
            handleDrop(index);
          }}
        >
          <span className="cut-row-idx">{index + 1}</span>
          <span className="cut-row-time">{formatTime(cut.beatTime)}</span>
          <span
            className="cut-row-section"
            style={{ background: sectionColor(cut.sectionType), opacity: 0.7 }}
          >
            {cut.sectionType}
          </span>
          <span className="cut-row-name" title={cut.clipPath}>
            {cut.clipName}
          </span>
          <span className="cut-row-score">
            <span className="cut-row-score-bar">
              <span
                className="cut-row-score-fill"
                style={{ width: `${Math.max(0, Math.min(100, cut.score))}%` }}
              />
            </span>
            <span className="cut-row-score-num">{Math.round(cut.score)}</span>
          </span>
          <span className="cut-row-lock">{cut.locked ? "🔒" : ""}</span>
        </div>
      ))}
    </div>
  );
};

// ── Detail panel ────────────────────────────────────────────────────────────

const DetailPanel: React.FC<{
  cut: CutDecision;
  index: number;
  busy: boolean;
  onSwap: (indices: number[], alt: CutAlternative) => void;
  onToggleLock: (index: number) => void;
}> = ({ cut, index, busy, onSwap, onToggleLock }) => {
  const scores = cut.scores as Record<string, number>;

  return (
    <div className="cut-detail">
      <div className="detail-header">
        <div className="detail-thumb">
          <Thumbnail thumbnailId={cut.thumbnailId} alt={cut.clipName} w={64} h={36} />
        </div>
        <div className="detail-meta">
          <span className="detail-title">
            #{index + 1} · {cut.clipName}
          </span>
          <span className="detail-sub">
            {cut.sectionType} · {formatTime(cut.beatTime)} · {cut.sceneType}
          </span>
        </div>
        <button
          className={`lock-toggle ${cut.locked ? "locked" : ""}`}
          onClick={() => onToggleLock(index)}
          disabled={busy}
          title={cut.locked ? "Unlock cut" : "Lock cut"}
        >
          {cut.locked ? "🔒 Locked" : "🔓 Unlocked"}
        </button>
      </div>

      <div className="detail-scores">
        {SCORE_KEYS.map(({ key, label }) => {
          const val = scores[key] ?? 0;
          return (
            <div key={key} className="detail-score-row">
              <span className="detail-score-label">{label}</span>
              <span className="detail-score-bar">
                <span
                  className="detail-score-fill"
                  style={{ width: `${Math.max(0, Math.min(100, val))}%` }}
                />
              </span>
              <span className="detail-score-num">{Math.round(val)}</span>
            </div>
          );
        })}
      </div>

      {cut.alternatives.length > 0 && (
        <div className="detail-alternatives">
          {cut.alternatives.map((alt) => (
            <button
              key={alt.clipPath}
              className="alt-mini"
              onClick={() => onSwap([index], alt)}
              disabled={busy || cut.locked}
              title={alt.clipPath}
            >
              <Thumbnail thumbnailId={alt.thumbnailId} alt={alt.clipName} w={48} h={27} />
              <span className="alt-mini-name">{alt.clipName}</span>
              <span className="alt-mini-score">{Math.round(alt.score)}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
};

// ── Main ReviewMode ────────────────────────────────────────────────────────

export const ReviewMode: React.FC<Props> = ({
  cuts,
  busy,
  onSwap,
  onToggleLock,
  onReorder,
  onRegenerateSection,
  beatAnalysis,
}) => {
  const [selected, setSelected] = useState(0);
  const [playing, setPlaying] = useState(false);

  const sections = useMemo(() => {
    const seen: string[] = [];
    for (const cut of cuts) {
      if (cut.sectionType && seen.indexOf(cut.sectionType) === -1) seen.push(cut.sectionType);
    }
    return seen;
  }, [cuts]);

  const selectCut = useCallback(
    (index: number) => {
      if (index < 0 || index >= cuts.length) return;
      setSelected(index);
    },
    [cuts.length]
  );

  // Keyboard shortcuts
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      // Don't intercept if focus is in an input/textarea
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA") return;

      switch (e.key) {
        case "j":
        case "J":
          e.preventDefault();
          selectCut(selected - 1);
          break;
        case "l":
        case "L":
          if (e.shiftKey) {
            e.preventDefault();
            onToggleLock(selected);
          } else {
            e.preventDefault();
            selectCut(selected + 1);
          }
          break;
        case "k":
        case "K":
        case " ":
          e.preventDefault();
          setPlaying((p) => !p);
          break;
        case "ArrowLeft":
          e.preventDefault();
          selectCut(selected - 1);
          break;
        case "ArrowRight":
          e.preventDefault();
          selectCut(selected + 1);
          break;
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [selected, selectCut, onToggleLock]);

  if (cuts.length === 0) {
    return (
      <div className="review-mode">
        <div className="review-header">
          <h3>Review &amp; refine</h3>
          <p>No edit has been generated yet.</p>
        </div>
        <div className="empty-state">
          Press GENERATE EDIT — every cut lands here with its score, alternatives and a lock.
        </div>
      </div>
    );
  }

  const focusCut = selected < cuts.length ? cuts[selected] : null;

  return (
    <div className="review-mode">
      <div className="review-header">
        <h3>Review &amp; refine</h3>
        <p>
          {cuts.length} cuts · {cuts.filter((c) => c.locked).length} locked ·{" "}
          {playing ? "▶ playing" : "⏸ paused"}
        </p>
      </div>

      <WaveformStrip
        cuts={cuts}
        beat={beatAnalysis ?? null}
        selected={selected}
        onSelect={setSelected}
      />

      <CutList
        cuts={cuts}
        selected={selected}
        busy={busy}
        onSelect={setSelected}
        onReorder={onReorder}
      />

      {focusCut && (
        <DetailPanel
          cut={focusCut}
          index={selected}
          busy={busy}
          onSwap={onSwap}
          onToggleLock={onToggleLock}
        />
      )}

      <div className="review-toolbar">
        {sections.map((section) => (
          <button
            key={section}
            className="section-pill"
            onClick={() => onRegenerateSection(section)}
            disabled={busy}
          >
            <span
              className="section-pill-dot"
              style={{ background: sectionColor(section) }}
            />
            {section}
          </button>
        ))}
      </div>

      <div className="review-shortcuts">
        J prev · L next · K / Space play-pause · ← → nudge · Shift+L lock
      </div>
    </div>
  );
};

export default ReviewMode;