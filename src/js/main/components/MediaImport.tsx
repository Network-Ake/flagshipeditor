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

const MediaImport: React.FC<Props> = ({ clips, setClips, audioPath, setAudioPath }) => {
  const [importing, setImporting] = useState(false);

  const handleImportClips = async () => {
    setImporting(true);
    try {
      const files = await openFiles("*.mov,*.mp4,*.m4v");
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
    const file = await openFile("*.mp3,*.wav,*.aac,*.m4a");
    if (file) {
      setAudioPath(file);
    }
  };

  const removeClip = (index: number) => {
    setClips(clips.filter((_, i) => i !== index));
  };

  return (
    <div>
      <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
        <button
          onClick={handleImportClips}
          disabled={importing}
          style={btnStyle}
        >
          {importing ? "..." : "+ Import Clips"}
        </button>
        <button onClick={handleImportMusic} style={btnStyle}>
          + Import Music
        </button>
      </div>

      {/* Clips list */}
      <div style={{ marginBottom: 12 }}>
        <div style={{ fontSize: 11, color: "#888", marginBottom: 6 }}>
          CLIPS ({clips.length})
        </div>
        {clips.length === 0 ? (
          <div style={{ fontSize: 11, color: "#555", padding: 8 }}>
            No clips imported. Import ProRes 422 .mov files.
          </div>
        ) : (
          clips.map((clip, i) => (
            <div
              key={i}
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                padding: "6px 8px",
                background: "#111122",
                borderRadius: 3,
                marginBottom: 3,
                fontSize: 11,
              }}
            >
              <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1 }}>
                🎬 {clip.name}
              </span>
              <span style={{ color: "#666", marginLeft: 8 }}>
                {clip.scene_type}
              </span>
              <button
                onClick={() => removeClip(i)}
                style={{ background: "none", border: "none", color: "#7c1629", cursor: "pointer", marginLeft: 8 }}
              >
                ✕
              </button>
            </div>
          ))
        )}
      </div>

      {/* Music */}
      <div>
        <div style={{ fontSize: 11, color: "#888", marginBottom: 6 }}>MUSIC</div>
        {audioPath ? (
          <div style={{ padding: "6px 8px", background: "#111122", borderRadius: 3, fontSize: 11 }}>
            🎵 {audioPath.split(/[/\\]/).pop()}
          </div>
        ) : (
          <div style={{ fontSize: 11, color: "#555", padding: 8 }}>
            No music imported.
          </div>
        )}
      </div>
    </div>
  );
};

const btnStyle: React.CSSProperties = {
  flex: 1,
  padding: "8px 12px",
  background: "#1a1a2e",
  color: "#e0e0e0",
  border: "1px solid #2a2a4a",
  borderRadius: 3,
  cursor: "pointer",
  fontSize: 12,
};

export default MediaImport;