import React, { useState } from 'react';

interface CutDecision {
  beatTime: number;
  clipPath: string;
  clipName: string;
  score: number;
  scores: {
    composition: number;
    energy: number;
    variety: number;
    sharpness: number;
    stability: number;
    face_quality: number;
  };
  sectionType: string;
  locked: boolean;
  alternatives: Array<{
    clipPath: string;
    clipName: string;
    score: number;
  }>;
}

const SECTION_COLORS: Record<string, string> = {
  intro: '#6366f1',
  verse: '#8b5cf6',
  hook: '#ec4899',
  chorus: '#ec4899',
  bridge: '#f59e0b',
  outro: '#10b981',
  default: '#71717a',
};

export const ReviewMode: React.FC<{
  cuts: CutDecision[];
  onSwap: (index: number, newClipPath: string) => void;
  onLock: (index: number) => void;
  onRegenerateSection: (sectionType: string) => void;
}> = ({ cuts, onSwap, onLock, onRegenerateSection }) => {
  const [selectedCut, setSelectedCut] = useState<number | null>(null);

  const sections = [...new Set(cuts.map(c => c.sectionType))];

  const totalDuration = cuts.length > 0
    ? Math.max(...cuts.map(c => c.beatTime)) + 2
    : 1;

  return (
    <div className="review-mode">
      <div className="review-header">
        <h3>Review & Refine</h3>
        <p>{cuts.length} cuts generated · Click any cut to swap or lock</p>
      </div>

      {cuts.length > 0 && (
        <div className="timeline-strip" aria-label="Cut timeline">
          {cuts.map((cut, i) => {
            const width = Math.max(2, (2 / totalDuration) * 100);
            return (
              <div
                key={i}
                className="timeline-segment"
                style={{ width: `${width}%` } as React.CSSProperties}
                data-section={cut.sectionType}
                title={`${cut.sectionType} @ ${formatTime(cut.beatTime)}`}
                onClick={() => setSelectedCut(i)}
              />
            );
          })}
        </div>
      )}

      <div className="cuts-list">
        {cuts.map((cut, i) => (
          <div
            key={i}
            className={`cut-card ${cut.locked ? 'locked' : ''} ${selectedCut === i ? 'selected' : ''}`}
            onClick={() => setSelectedCut(i)}
          >
            <div className="cut-thumbnail">
              <img src={getThumbnail(cut.clipPath)} alt={cut.clipName} onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; (e.target as HTMLImageElement).parentElement!.textContent = 'No preview'; }} />
            </div>
            <div className="cut-info">
              <span className="cut-time">{formatTime(cut.beatTime)}</span>
              <span className="cut-section">{cut.sectionType}</span>
              <div className="cut-score">
                <div className="score-bar-bg">
                  <div className="score-bar-fill" style={{ width: `${cut.score}%` } as React.CSSProperties} />
                </div>
                <span>{Math.round(cut.score)}/100</span>
              </div>
            </div>
            <button
              className="lock-btn"
              onClick={(e) => { e.stopPropagation(); onLock(i); }}
              aria-label={cut.locked ? 'Unlock cut' : 'Lock cut'}
              title={cut.locked ? 'Locked' : 'Unlocked'}
            >
              {cut.locked ? '🔒' : '🔓'}
            </button>
          </div>
        ))}
      </div>

      {selectedCut !== null && cuts[selectedCut] && (
        <div className="swap-panel">
          <h4>Swap shot — Cut #{selectedCut + 1}</h4>
          <div className="alternatives">
            {cuts[selectedCut].alternatives.map((alt, j) => (
              <div key={j} className="alt-card" onClick={() => onSwap(selectedCut, alt.clipPath)}>
                <img src={getThumbnail(alt.clipPath)} alt={alt.clipName} onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; (e.target as HTMLImageElement).parentElement!.textContent = 'No preview'; }} />
                <span>{alt.clipName}</span>
                <span className="alt-score">{Math.round(alt.score)}/100</span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="section-regenerate">
        {sections.map(sec => (
          <button key={sec} onClick={() => onRegenerateSection(sec)}>
            🔄 Regenerate {sec}
          </button>
        ))}
      </div>
    </div>
  );
};

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
}

function getThumbnail(clipPath: string): string {
  const thumbName = clipPath.split(/[\\/]/).pop()?.replace(/\.[^.]+$/, '') + '_thumb.jpg';
  return `http://127.0.0.1:18791/thumbnails/${thumbName}`;
}
