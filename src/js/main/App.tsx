import React, { useState, useCallback } from "react";
import MediaImport from "./components/MediaImport";
import StyleSelector from "./components/StyleSelector";
import Parameters from "./components/Parameters";
import Element3DPanel from "./components/Element3DPanel";
import AnalysisView from "./components/AnalysisView";
import { evalTS } from "./lib/bolt";
import { runBeatAnalysis, runClipAnalysis } from "./lib/python";

type Tab = "media" | "style" | "params" | "3d" | "analysis";

const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState<Tab>("media");
  const [clips, setClips] = useState<ClipInfo[]>([]);
  const [audioPath, setAudioPath] = useState<string>("");
  const [selectedStyle, setSelectedStyle] = useState<string>("cmd_command_drill");
  const [analysis, setAnalysis] = useState<BeatAnalysis | null>(null);
  const [isGenerating, setIsGenerating] = useState(false);
  const [status, setStatus] = useState<string>("");

  const handleGenerate = useCallback(async () => {
    if (!audioPath || clips.length === 0) {
      setStatus("⚠️ Import clips and music first");
      return;
    }
    setIsGenerating(true);
    setStatus("🎵 Analyzing beat...");
    try {
      const beatData = await runBeatAnalysis(audioPath);
      setAnalysis(beatData);
      setStatus("🎬 Analyzing clips...");
      const clipData = await Promise.all(
        clips.map((c) => runClipAnalysis(c.path))
      );
      setStatus("⚡ Generating comp...");
      await evalTS("buildComp", beatData, clipData, selectedStyle, audioPath);
      setStatus("✅ Comp generated! Add your effects and Element 3D.");
    } catch (err) {
      setStatus(`❌ Error: ${err}`);
    } finally {
      setIsGenerating(false);
    }
  }, [audioPath, clips, selectedStyle]);

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      {/* Header */}
      <div style={{
        padding: "10px 14px",
        background: "#0f0f1e",
        borderBottom: "1px solid #2a2a4a",
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
      }}>
        <span style={{ fontWeight: 700, fontSize: 15, color: "#7c1629" }}>
          FlagshipEditor™
        </span>
        <span style={{ fontSize: 11, color: "#666" }}>v0.1.0</span>
      </div>

      {/* Tabs */}
      <div style={{ display: "flex", borderBottom: "1px solid #2a2a4a" }}>
        {([
          ["media", "📁 Media"],
          ["style", "🎨 Style"],
          ["params", "🎛 Params"],
          ["3d", "🧊 3D"],
          ["analysis", "📊 Analysis"],
        ] as [Tab, string][]).map(([tab, label]) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            style={{
              flex: 1,
              padding: "8px 4px",
              background: activeTab === tab ? "#1a1a2e" : "transparent",
              border: "none",
              borderBottom: activeTab === tab ? "2px solid #7c1629" : "2px solid transparent",
              color: activeTab === tab ? "#e0e0e0" : "#666",
              cursor: "pointer",
              fontSize: 11,
            }}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Content */}
      <div style={{ flex: 1, overflow: "auto", padding: "12px" }}>
        {activeTab === "media" && (
          <MediaImport
            clips={clips}
            setClips={setClips}
            audioPath={audioPath}
            setAudioPath={setAudioPath}
          />
        )}
        {activeTab === "style" && (
          <StyleSelector
            selected={selectedStyle}
            onSelect={setSelectedStyle}
          />
        )}
        {activeTab === "params" && <Parameters />}
        {activeTab === "3d" && <Element3DPanel />}
        {activeTab === "analysis" && <AnalysisView analysis={analysis} />}
      </div>

      {/* Footer */}
      <div style={{
        padding: "10px 14px",
        background: "#0f0f1e",
        borderTop: "1px solid #2a2a4a",
      }}>
        <div style={{ fontSize: 11, color: "#888", marginBottom: 8, minHeight: 16 }}>
          {status}
        </div>
        <button
          onClick={handleGenerate}
          disabled={isGenerating}
          style={{
            width: "100%",
            padding: "10px",
            background: isGenerating ? "#333" : "#7c1629",
            color: "#fff",
            border: "none",
            borderRadius: 4,
            cursor: isGenerating ? "wait" : "pointer",
            fontSize: 13,
            fontWeight: 600,
          }}
        >
          {isGenerating ? "⏳ Generating..." : "⚡ GENERATE EDIT"}
        </button>
      </div>
    </div>
  );
};

export default App;