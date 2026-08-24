import React, { useMemo, useState } from "react";
import { CutAlternative, CutDecision, thumbnailUrl } from "../lib/python";

interface Props {
  cuts: CutDecision[];
  busy: boolean;
  onSwap: (indices: number[], alternative: CutAlternative) => void;
  onToggleLock: (index: number) => void;
  onReorder: (from: number, to: number) => void;
  onRegenerateSection: (sectionType: string) => void;
}

function formatTime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00.0";
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return `${minutes}:${rest.toFixed(1).padStart(4, "0")}`;
}

const Thumbnail: React.FC<{ thumbnailId: string; alt: string }> = ({ thumbnailId, alt }) => {
  const [broken, setBroken] = useState(false);
  const source = thumbnailUrl(thumbnailId);
  if (!source || broken)
    return (
      <span className="cut-thumbnail-fallback" role="img" aria-label={`No preview for ${alt}`} title="No preview">
        🎬
      </span>
    );
  return <img src={source} alt={alt} loading="lazy" onError={() => setBroken(true)} />;
};

export const ReviewMode: React.FC<Props> = ({
  cuts,
  busy,
  onSwap,
  onToggleLock,
  onReorder,
  onRegenerateSection,
}) => {
  const [selected, setSelected] = useState<number[]>([]);
  const [focused, setFocused] = useState<number | null>(null);
  const [dragIndex, setDragIndex] = useState<number | null>(null);
  const [dropIndex, setDropIndex] = useState<number | null>(null);

  const sections = useMemo(() => {
    const seen: string[] = [];
    for (const cut of cuts) {
      if (cut.sectionType && seen.indexOf(cut.sectionType) === -1) seen.push(cut.sectionType);
    }
    return seen;
  }, [cuts]);

  const timelineEnd = useMemo(() => {
    let end = 0;
    for (const cut of cuts) if (cut.endTime > end) end = cut.endTime;
    return end > 0 ? end : 1;
  }, [cuts]);

  const lockedCount = cuts.filter((cut) => cut.locked).length;
  const focusCut = focused !== null && focused < cuts.length ? cuts[focused] : null;
  const selectionValid = selected.filter((index) => index < cuts.length);

  const handleSelect = (index: number, event: React.MouseEvent) => {
    setFocused(index);
    if (event.metaKey || event.ctrlKey) {
      setSelected((previous) =>
        previous.indexOf(index) === -1
          ? previous.concat(index)
          : previous.filter((entry) => entry !== index)
      );
      return;
    }
    if (event.shiftKey && focused !== null) {
      const from = Math.min(focused, index);
      const to = Math.max(focused, index);
      const range: number[] = [];
      for (let cursor = from; cursor <= to; cursor += 1) range.push(cursor);
      setSelected(range);
      return;
    }
    setSelected([index]);
  };

  const handleDrop = (target: number) => {
    if (dragIndex !== null && dragIndex !== target) onReorder(dragIndex, target);
    setDragIndex(null);
    setDropIndex(null);
  };

  if (cuts.length === 0) {
    return (
      <div className="review-mode">
        <div className="review-header">
          <h3>Review &amp; refine</h3>
          <p>No edit has been generated yet.</p>
        </div>
        <div className="empty-state">
          Press GENERATE EDIT — every cut lands here with its score, its alternatives and a lock.
        </div>
      </div>
    );
  }

  return (
    <div className="review-mode">
      <div className="review-header">
        <h3>Review &amp; refine</h3>
        <p>
          {cuts.length} cuts · {lockedCount} locked · drag a card to move a clip, ⌘/Ctrl-click to
          select several
        </p>
      </div>

      <div className="timeline-strip" aria-label="Cut timeline">
        {cuts.map((cut, index) => (
          <button
            key={`${cut.beatTime}-${index}`}
            type="button"
            className={`timeline-segment ${selectionValid.indexOf(index) !== -1 ? "selected" : ""}`}
            style={{ flexGrow: Math.max(0.01, (cut.endTime - cut.beatTime) / timelineEnd) }}
            data-section={cut.sectionType}
            title={`${cut.sectionType} · ${formatTime(cut.beatTime)} · ${cut.clipName}`}
            onClick={(event) => handleSelect(index, event)}
            aria-label={`Cut ${index + 1} at ${formatTime(cut.beatTime)}`}
          />
        ))}
      </div>

      {selectionValid.length > 1 && (
        <div className="alert alert-inline">
          <div className="alert-body">
            <div className="alert-title">{selectionValid.length} cuts selected</div>
            <div className="alert-text">A swap below replaces the clip on all of them.</div>
          </div>
          <button className="btn btn-sm" onClick={() => setSelected(focused === null ? [] : [focused])}>
            Clear
          </button>
        </div>
      )}

      <div className="cuts-list">
        {cuts.map((cut, index) => (
          <div
            key={`${cut.beatTime}-${cut.sectionType}-${index}`}
            className={`cut-card${cut.locked ? " locked" : ""}${
              selectionValid.indexOf(index) !== -1 ? " selected" : ""
            }${dropIndex === index ? " drop-target" : ""}`}
            onClick={(event) => handleSelect(index, event)}
            draggable={!busy}
            onDragStart={() => setDragIndex(index)}
            onDragEnd={() => {
              setDragIndex(null);
              setDropIndex(null);
            }}
            onDragOver={(event) => {
              event.preventDefault();
              if (dropIndex !== index) setDropIndex(index);
            }}
            onDrop={(event) => {
              event.preventDefault();
              handleDrop(index);
            }}
          >
            <span className="cut-index">{index + 1}</span>
            <div className="cut-thumbnail">
              <Thumbnail thumbnailId={cut.thumbnailId} alt={cut.clipName} />
            </div>
            <div className="cut-info">
              <div className="cut-info-top">
                <span className="cut-time">{formatTime(cut.beatTime)}</span>
                <span className="cut-section" data-section={cut.sectionType}>
                  {cut.sectionType}
                </span>
                <span className="badge">{cut.sceneType}</span>
              </div>
              <div className="cut-name" title={cut.clipPath}>
                {cut.clipName}
              </div>
              <div className="cut-score">
                <div className="score-bar-bg">
                  <div
                    className="score-bar-fill"
                    style={{ width: `${Math.max(0, Math.min(100, cut.score))}%` }}
                  />
                </div>
                <span>{Math.round(cut.score)}/100</span>
              </div>
            </div>
            <button
              className="lock-btn"
              onClick={(event) => {
                event.stopPropagation();
                onToggleLock(index);
              }}
              aria-label={cut.locked ? "Unlock cut" : "Lock cut"}
              title={cut.locked ? "Locked — regeneration keeps this clip" : "Unlocked"}
            >
              {cut.locked ? "🔒" : "🔓"}
            </button>
          </div>
        ))}
      </div>

      {focusCut && (
        <div className="swap-panel">
          <h4>
            Cut #{(focused ?? 0) + 1} · {focusCut.sectionType} · {formatTime(focusCut.beatTime)}
          </h4>
          <div className="score-breakdown">
            {(Object.keys(focusCut.scores) as (keyof typeof focusCut.scores)[]).map((key) => (
              <div key={key} className="score-row">
                <span className="score-name">{key.replace(/_/g, " ")}</span>
                <div className="score-bar-bg">
                  <div
                    className="score-bar-fill"
                    style={{ width: `${Math.max(0, Math.min(100, focusCut.scores[key]))}%` }}
                  />
                </div>
                <span className="score-number">{Math.round(focusCut.scores[key])}</span>
              </div>
            ))}
          </div>

          {focusCut.alternatives.length === 0 ? (
            <div className="empty-state">
              No alternative scored high enough for this cut. Import more clips for options.
            </div>
          ) : (
            <div className="alternatives">
              {focusCut.alternatives.map((alternative) => (
                <button
                  key={alternative.clipPath}
                  type="button"
                  className="alt-card"
                  onClick={() =>
                    onSwap(selectionValid.length > 0 ? selectionValid : [focused ?? 0], alternative)
                  }
                  disabled={busy || focusCut.locked}
                  title={focusCut.locked ? "Unlock this cut before swapping" : alternative.clipPath}
                >
                  <Thumbnail thumbnailId={alternative.thumbnailId} alt={alternative.clipName} />
                  <span>{alternative.clipName}</span>
                  <span className="alt-score">{Math.round(alternative.score)}/100</span>
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      <div className="section-regenerate">
        {sections.map((section) => (
          <button key={section} onClick={() => onRegenerateSection(section)} disabled={busy}>
            🔄 Regenerate {section}
          </button>
        ))}
      </div>
    </div>
  );
};

export default ReviewMode;
