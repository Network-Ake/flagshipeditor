import React from "react";
import { ClipInfo, thumbnailUrl } from "../lib/python";

interface Props {
  clips: ClipInfo[];
  audioPath: string;
  busy: boolean;
  analyzingPaths: string[];
  failedClips: { path: string; message: string }[];
  onImportClips: () => void;
  onImportFolder: () => void;
  onImportMusic: () => void;
  onRemoveClip: (path: string) => void;
  onClearClips: () => void;
  onRetryFailed: () => void;
}

const SCENE_BADGES: Record<string, string> = {
  close_up: "badge-accent",
  performance: "badge-accent",
  b_roll: "badge",
  b_roll_dynamic: "badge-success",
  b_roll_static: "badge",
  b_roll_low_light: "badge-warning",
  unknown: "badge-warning",
};

function formatDuration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return "—";
  const minutes = Math.floor(seconds / 60);
  const rest = Math.floor(seconds % 60);
  return minutes > 0 ? `${minutes}:${rest.toString().padStart(2, "0")}` : `${seconds.toFixed(1)}s`;
}

function formatFormat(clip: ClipInfo): string {
  if (!clip.width || !clip.height) return "";
  const fps = clip.fps ? ` · ${clip.fps.toFixed(clip.fps % 1 === 0 ? 0 : 2)}fps` : "";
  return `${clip.width}×${clip.height}${fps}`;
}

const MediaImport: React.FC<Props> = ({
  clips,
  audioPath,
  busy,
  analyzingPaths,
  failedClips,
  onImportClips,
  onImportFolder,
  onImportMusic,
  onRemoveClip,
  onClearClips,
  onRetryFailed,
}) => {
  const analyzing = new Set(analyzingPaths);
  const failedByPath = new Map(failedClips.map((entry) => [entry.path, entry.message]));
  const analyzedCount = clips.filter((clip) => clip.analyzed).length;

  return (
    <div className="media-import">
      <div
        className="drop-zone"
        onClick={busy ? undefined : onImportClips}
        role="button"
        tabIndex={0}
        aria-disabled={busy}
        onKeyDown={(event) => {
          if (!busy && (event.key === "Enter" || event.key === " ")) onImportClips();
        }}
      >
        <div className="drop-zone-icon">📂</div>
        <div className="drop-zone-text">Click to browse clips</div>
        <div className="drop-zone-hint">ProRes 422 .mov, .mp4, .m4v, .avi, .mxf</div>
      </div>

      <div className="media-actions">
        <button className="btn btn-secondary btn-sm" onClick={onImportClips} disabled={busy}>
          + Import clips
        </button>
        <button className="btn btn-secondary btn-sm" onClick={onImportFolder} disabled={busy}>
          📁 Scan folder
        </button>
        <button className="btn btn-secondary btn-sm" onClick={onImportMusic} disabled={busy}>
          🎵 Import music
        </button>
      </div>

      {failedClips.length > 0 && (
        <div className="alert alert-error">
          <div className="alert-body">
            <div className="alert-title">{failedClips.length} clip(s) could not be analysed</div>
            <div className="alert-text">{failedClips[0].message}</div>
          </div>
          <button className="btn btn-sm" onClick={onRetryFailed} disabled={busy}>
            Retry
          </button>
        </div>
      )}

      <div className="clips-section">
        <div className="clips-header">
          <span className="section-title">Clips</span>
          <span className="badge">{clips.length}</span>
          {clips.length > 0 && (
            <span className="clips-header-meta">
              {analyzedCount}/{clips.length} analysed
            </span>
          )}
          {clips.length > 0 && (
            <button className="link-btn" onClick={onClearClips} disabled={busy}>
              Clear all
            </button>
          )}
        </div>

        {clips.length === 0 ? (
          <div className="empty-state">No clips imported yet. Browse files or scan a folder.</div>
        ) : (
          <div className="clip-grid">
            {clips.map((clip) => {
              const thumbnail = thumbnailUrl(clip.thumbnail_id);
              const isAnalyzing = analyzing.has(clip.path);
              const failure = failedByPath.get(clip.path);
              return (
                <div
                  key={clip.path}
                  className={`clip-card${isAnalyzing ? " is-analyzing" : ""}${failure ? " is-failed" : ""}`}
                  title={failure || clip.path}
                >
                  <div className="clip-thumbnail">
                    {thumbnail ? (
                      <img src={thumbnail} alt="" className="clip-thumbnail-img" loading="lazy" />
                    ) : isAnalyzing ? (
                      <span className="skeleton skeleton-thumb" />
                    ) : (
                      <span className="clip-thumbnail-fallback">🎬</span>
                    )}
                    {isAnalyzing && <span className="clip-thumbnail-spinner spinner" />}
                  </div>
                  <button
                    className="clip-remove"
                    onClick={() => onRemoveClip(clip.path)}
                    aria-label={`Remove ${clip.name}`}
                    disabled={busy}
                  >
                    ✕
                  </button>
                  <div className="clip-info">
                    <div className="clip-name" title={clip.name}>
                      {clip.name}
                    </div>
                    <div className="clip-meta">
                      <span className={`badge ${SCENE_BADGES[clip.scene_type] || "badge"}`}>
                        {failure ? "failed" : isAnalyzing ? "analysing" : clip.scene_type}
                      </span>
                      <span className="clip-duration">{formatDuration(clip.duration)}</span>
                    </div>
                    {clip.analyzed && <div className="clip-format">{formatFormat(clip)}</div>}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      <div className="music-section">
        <span className="section-title">Music</span>
        {audioPath ? (
          <div className="music-card">
            <div className="music-icon">🎵</div>
            <div className="music-info">
              <div className="music-name" title={audioPath}>
                {audioPath.split(/[/\\]/).pop()}
              </div>
              <div className="music-hint">Beat grid is analysed when you generate</div>
            </div>
            <button className="link-btn" onClick={onImportMusic} disabled={busy}>
              Change
            </button>
          </div>
        ) : (
          <div className="empty-state">No music imported. Click Import music to load a track.</div>
        )}
      </div>
    </div>
  );
};

export default MediaImport;
