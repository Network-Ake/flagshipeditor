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

export const ReviewMode: React.FC<{
  cuts: CutDecision[];
  onSwap: (index: number, newClipPath: string) => void;
  onLock: (index: number) => void;
  onRegenerateSection: (sectionType: string) => void;
}> = ({ cuts, onSwap, onLock, onRegenerateSection }) => {
  const [selectedCut, setSelectedCut] = useState<number | null>(null);

  const sections = [...new Set(cuts.map(c => c.sectionType))];

  return (
    <div className="review-mode">
      <div className="review-header">
        <h3>Review & Refine</h3>
        <p>{cuts.length} cuts generated · Click any cut to swap or lock</p>
      </div>

      <div className="cuts-timeline">
        {cuts.map((cut, i) => (
          <div
            key={i}
            className={`cut-card ${cut.locked ? 'locked' : ''} ${selectedCut === i ? 'selected' : ''}`}
            onClick={() => setSelectedCut(i)}
          >
            <div className="cut-thumbnail">
              <img src={getThumbnail(cut.clipPath)} alt={cut.clipName} />
            </div>
            <div className="cut-info">
              <span className="cut-time">{formatTime(cut.beatTime)}</span>
              <span className="cut-section">{cut.sectionType}</span>
              <div className="cut-score">
                <div className="score-bar" style={{ width: `${cut.score}%` }} />
                <span>{Math.round(cut.score)}/100</span>
              </div>
            </div>
            <button
              className="lock-btn"
              onClick={(e) => { e.stopPropagation(); onLock(i); }}
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
                <img src={getThumbnail(alt.clipPath)} alt={alt.clipName} />
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