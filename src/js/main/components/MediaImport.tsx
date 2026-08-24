import React, { useState } from "react";
import { openFiles, openFile } from "../lib/bolt";

interface ClipInfo {
  path: string;
  name: string;
  duration: number;
  scene_type: string;
  has_face: boolean;
  brightness: number;
  motion_intensity: number;
}

interface Props {
  clips: ClipInfo[];
  setClips: (clips: ClipInfo[]) => void;
  audioPath: string;
  setAudioPath: (path: string) => void;
}

const SCENE_COLORS: Record<string, string> = {
  pending: "badge",
  intro: "badge-accent",
  verse: "badge",
  hook: "badge-accent",
  chorus: "badge-accent",
  bridge: "badge-warning",
  outro: "badge",
};

const MediaImport: React.FC<Props> = ({ clips, setClips, audioPath, setAudioPath }) => {
  const [importing, setImporting] = useState(false);

  const handleImportClips = async () => {
    setImporting(true);
    try {
      const files = await openFiles("Video files:*.mov;*.mp4;*.m4v;*.avi;*.mxf,All files:*.*");
      if (files.length > 0) {
        const newClips = files.map((path) => ({
          path,
          name: path.split(/[/\\]/).pop() || path,
          duration: 0,
          scene_type: "pending",
          has_face: false,
          brightness: 0,
          motion_intensity: 0,
        }));
        setClips([...clips, ...newClips]);
      }
    } finally {
      setImporting(false);
    }
  };

  const handleImportMusic = async () => {
    const file = await openFile("Audio files:*.mp3;*.wav;*.aac;*.m4a,All files:*.*");
    if (file) {
      setAudioPath(file);
    }
  };

  const removeClip = (index: number) => {
    setClips(clips.filter((_, i) => i !== index));
  };

  return (
    <div className="media-import">
      {/* Drop zone */}
      <div className="drop-zone" onClick={handleImportClips}>
        <div className="drop-zone-icon">📂</div>
        <div className="drop-zone-text">Drop clips or click to browse</div>
        <div className="drop-zone-hint">ProRes 422 .mov, .mp4, .m4v</div>
      </div>

      {/* Quick actions */}
      <div className="media-actions">
        <button className="btn btn-secondary btn-sm" onClick={handleImportClips} disabled={importing}>
          {importing ? "Importing..." : "+ Import Clips"}
        </button>
        <button className="btn btn-secondary btn-sm" onClick={handleImportMusic}>
          🎵 Import Music
        </button>
      </div>

      {/* Clips grid */}
      <div className="clips-section">
        <div className="clips-header">
          <span className="section-title">Clips</span>
          <span className="badge">{clips.length}</span>
        </div>

        {clips.length === 0 ? (
          <div className="empty-state">
            No clips imported yet. Drop files above or click Import Clips.
          </div>
        ) : (
          <div className="clip-grid">
            {clips.map((clip, i) => (
              <div key={i} className="clip-card">
                <div className="clip-thumbnail">🎬</div>
                <button
                  className="clip-remove"
                  onClick={() => removeClip(i)}
                  aria-label="Remove clip"
                  title="Remove"
                >
                  ✕
                </button>
                <div className="clip-info">
                  <div className="clip-name" title={clip.name}>
                    {clip.name}
                  </div>
                  <div className="clip-meta">
                    <span className={`badge ${SCENE_COLORS[clip.scene_type] || "badge"}`}>
                      {clip.scene_type}
                    </span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Music card */}
      <div className="music-section">
        <span className="section-title">Music</span>
        {audioPath ? (
          <div className="music-card">
            <div className="music-icon">🎵</div>
            <div className="music-info">
              <div className="music-name" title={audioPath}>
                {audioPath.split(/[/\\]/).pop()}
              </div>
              <div className="music-hint">Audio track</div>
            </div>
            <div className="waveform-placeholder" />
          </div>
        ) : (
          <div className="empty-state">
            No music imported. Click Import Music to load a track.
          </div>
        )}
      </div>
    </div>
  );
};

export default MediaImport;
