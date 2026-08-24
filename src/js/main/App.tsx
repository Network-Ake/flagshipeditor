import React, { useState, useCallback } from "react";
import MediaImport from "./components/MediaImport";
import StyleSelector from "./components/StyleSelector";
import Parameters from "./components/Parameters";
import Element3DPanel from "./components/Element3DPanel";
import AnalysisView from "./components/AnalysisView";
import { ReviewMode } from "./components/ReviewMode";
import { evalTS } from "./lib/bolt";
import { runBeatAnalysis, runClipAnalysis, BeatAnalysis, ClipInfo } from "./lib/python";

type Tab = "media" | "style" | "params" | "3d" | "review" | "analysis";

const TABS: { id: Tab; icon: string; label: string }[] = [
  { id: "media", icon: "📁", label: "Media" },
  { id: "style", icon: "🎨", label: "Style" },
  { id: "params", icon: "🎛", label: "Params" },
  { id: "3d", icon: "🧊", label: "3D" },
  { id: "review", icon: "👁", label: "Review" },
  { id: "analysis", icon: "📊", label: "Analysis" },
];

const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState<Tab>("media");
  const [clips, setClips] = useState<ClipInfo[]>([]);
  const [audioPath, setAudioPath] = useState<string>("");
  const [selectedStyle, setSelectedStyle] = useState<string>("cmd_command_drill");
  const [analysis, setAnalysis] = useState<BeatAnalysis | null>(null);
  const [isGenerating, setIsGenerating] = useState(false);
  const [status, setStatus] = useState<string>("Ready");
  const [cutDecisions, setCutDecisions] = useState<any[]>([]);

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
      setStatus("🤖 Selecting best shots...");
      // Shot selection will be called per section by the comp builder
      setStatus("⚡ Generating comp (non-destructive pre-comp)...");
      await evalTS("buildComp", beatData, clipData, selectedStyle, audioPath);
      setStatus("✅ Comp generated! Review your cuts, then add effects and Element 3D.");
    } catch (err) {
      setStatus(`❌ Error: ${err}`);
    } finally {
      setIsGenerating(false);
    }
  }, [audioPath, clips, selectedStyle]);

  const statusState = isGenerating ? "busy" : status.startsWith("❌") ? "error" : status.startsWith("⚠️") ? "warning" : "ready";

  return (
    <div className="app-shell">
      {/* Sidebar */}
      <aside className="app-sidebar">
        <div className="sidebar-logo">F</div>
        <nav className="sidebar-nav">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              className={`sidebar-item ${activeTab === tab.id ? "active" : ""}`}
              onClick={() => setActiveTab(tab.id)}
              aria-label={tab.label}
            >
              <span className="sidebar-icon">{tab.icon}</span>
              <span className="sidebar-tooltip">{tab.label}</span>
            </button>
          ))}
        </nav>
      </aside>

      {/* Main area */}
      <main className="app-main">
        {/* Top bar */}
        <header className="app-topbar">
          <div className="topbar-brand">
            <span className="brand-name">FlagshipEditor</span>
            <span className="version-badge">v0.1.0</span>
          </div>
          <div className="topbar-actions">
            <button className="icon-btn" aria-label="Settings" title="Settings">
              ⚙️
            </button>
          </div>
        </header>

        {/* Content */}
        <div className="app-content">
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
          {activeTab === "review" && (
            <ReviewMode
              cuts={cutDecisions}
              onSwap={(index, newClipPath) => {
                const updated = [...cutDecisions];
                updated[index] = { ...updated[index], clipPath: newClipPath };
                setCutDecisions(updated);
              }}
              onLock={(index) => {
                const updated = [...cutDecisions];
                updated[index] = { ...updated[index], locked: !updated[index].locked };
                setCutDecisions(updated);
              }}
              onRegenerateSection={(sectionType) => {
                setStatus(`🔄 Regenerating ${sectionType}...`);
                // TODO: call backend to re-select shots for this section only
              }}
            />
          )}
          {activeTab === "analysis" && <AnalysisView analysis={analysis} />}
        </div>

        {/* Bottom bar */}
        <footer className="app-bottombar">
          <div className="status-row">
            <span className={`status-dot ${statusState}`} />
            <span className="status-text">{status}</span>
          </div>
          <button
            className="generate-btn"
            onClick={handleGenerate}
            disabled={isGenerating}
          >
            <span className="generate-btn-content">
              {isGenerating && <span className="spinner" />}
              {isGenerating ? "Generating..." : "⚡ GENERATE EDIT"}
            </span>
          </button>
        </footer>
      </main>
    </div>
  );
};

export default App;
