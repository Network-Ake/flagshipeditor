import React, { useState, useCallback, useRef, useEffect } from "react";
import MediaImport from "./components/MediaImport";
import StyleSelector from "./components/StyleSelector";
import Parameters from "./components/Parameters";
import Element3DPanel from "./components/Element3DPanel";
import AnalysisView from "./components/AnalysisView";
import { ReviewMode } from "./components/ReviewMode";
import { evalTS } from "./lib/bolt";
import {
  runBeatAnalysis,
  createAnalysisJob,
  getAnalysisJob,
  getAnalysisJobResult,
  cancelAnalysisJob,
  selectShots,
  checkPythonServer,
  startPythonServer,
  getServerHealth,
  scanMedia,
  BeatAnalysis,
  ClipInfo,
} from "./lib/python";

type Tab = "media" | "style" | "params" | "3d" | "review" | "analysis";
type GenState = "idle" | "analyzing-beat" | "analyzing-clips" | "selecting-shots" | "building" | "cancelling";

const TABS: { id: Tab; icon: string; label: string }[] = [
  { id: "media", icon: "📁", label: "Media" },
  { id: "style", icon: "🎨", label: "Style" },
  { id: "params", icon: "🎛", label: "Params" },
  { id: "3d", icon: "🧊", label: "3D" },
  { id: "review", icon: "👁", label: "Review" },
  { id: "analysis", icon: "📊", label: "Analysis" },
];

const VERSION = "0.1.9";
const BRIDGE_ID = "com.akestudio.flagshipeditor.bridge";

const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState<Tab>("media");
  const [clips, setClips] = useState<ClipInfo[]>([]);
  const [audioPath, setAudioPath] = useState<string>("");
  const [selectedStyle, setSelectedStyle] = useState<string>("cmd_command_drill");
  const [analysis, setAnalysis] = useState<BeatAnalysis | null>(null);
  const [isGenerating, setIsGenerating] = useState(false);
  const [status, setStatus] = useState<string>("Ready");
  const [statusState, setStatusState] = useState<"ready" | "busy" | "error" | "warning">("ready");
  const [genState, setGenState] = useState<GenState>("idle");
  const [progress, setProgress] = useState<number>(0);
  const [cutDecisions, setCutDecisions] = useState<any[]>([]);
  const [serverOnline, setServerOnline] = useState<boolean>(false);
  const [bridgeInfo] = useState(() => ({ appId: BRIDGE_ID, version: VERSION }));
  const cancelRef = useRef<boolean>(false);
  const activeJobsRef = useRef<Set<string>>(new Set());

  // Check server health on mount
  useEffect(() => {
    const checkHealth = async () => {
      const online = await checkPythonServer();
      setServerOnline(online);
      if (!online) {
        setStatus("⚠️ Python backend offline. Click to start.");
        setStatusState("warning");
      } else {
        setStatus("Ready");
        setStatusState("ready");
      }
    };
    checkHealth();
    const interval = setInterval(checkHealth, 10000);
    return () => clearInterval(interval);
  }, []);

  const updateStatus = useCallback((msg: string, state: "ready" | "busy" | "error" | "warning" = "busy", pct?: number) => {
    setStatus(msg);
    setStatusState(state);
    if (pct !== undefined) setProgress(pct);
  }, []);

  const handleGenerate = useCallback(async () => {
    if (!audioPath || clips.length === 0) {
      updateStatus("⚠️ Import clips and music first", "warning");
      return;
    }
    if (genState !== "idle") return;

    cancelRef.current = false;
    setIsGenerating(true);
    setGenState("analyzing-beat");
    setProgress(0);
    activeJobsRef.current = new Set();

    try {
      // Step 1: Beat analysis
      updateStatus("🎵 Analyzing beat...", "busy", 5);
      const beatData = await runBeatAnalysis(audioPath);
      setAnalysis(beatData);
      if (cancelRef.current) { handleCancel(); return; }
      updateStatus(`🎵 Beat: ${beatData.tempo.toFixed(1)} BPM, ${beatData.key}`, "busy", 15);

      // Step 2: Clip analysis (batch via analysis-jobs)
      setGenState("analyzing-clips");
      updateStatus(`🎬 Analyzing ${clips.length} clips...`, "busy", 20);

      const clipResults: ClipInfo[] = [];
      const errors: { path: string; code: string; message: string }[] = [];

      // Create analysis jobs for all clips
      const jobPromises = clips.map(async (clip) => {
        try {
          const job = await createAnalysisJob(clip.path);
          activeJobsRef.current.add(job.id);
          return { clip, jobId: job.id };
        } catch (err: any) {
          errors.push({ path: clip.path, code: "JOB_CREATE", message: err.message });
          return null;
        }
      });
      const jobs = (await Promise.all(jobPromises)).filter(Boolean) as { clip: ClipInfo; jobId: string }[];

      // Poll for completion
      const pollInterval = 1000;
      const maxWait = 300000; // 5 min per clip
      for (const { clip, jobId } of jobs) {
        if (cancelRef.current) { handleCancel(); return; }
        const startTime = Date.now();
        let job: any = null;
        while (Date.now() - startTime < maxWait) {
          job = await getAnalysisJob(jobId);
          if (job.state === "completed" || job.state === "failed" || job.state === "cancelled") break;
          await new Promise(r => setTimeout(r, pollInterval));
        }
        activeJobsRef.current.delete(jobId);
        if (job && job.state === "completed") {
          const result = await getAnalysisJobResult(jobId);
          clipResults.push({ ...clip, ...result });
        } else if (job && job.state === "failed") {
          errors.push({ path: clip.path, code: "ANALYSIS", message: job.error || "Analysis failed" });
        }
        const pct = 20 + Math.round((clipResults.length + errors.length) / clips.length * 50);
        updateStatus(`🎬 Analyzing clips... ${clipResults.length + errors.length}/${clips.length}`, "busy", pct);
      }

      if (clipResults.length === 0) {
        throw new Error("All imported clips failed analysis. Review the task issues for details.");
      }
      if (errors.length > 0) {
        setStatus(`⚠️ ${errors.length} clip(s) failed analysis, continuing with ${clipResults.length}`);
      }

      if (cancelRef.current) { handleCancel(); return; }

      // Step 3: Shot selection
      setGenState("selecting-shots");
      updateStatus("🤖 Selecting best shots...", "busy", 75);
      const usedRecently: string[] = [];
      const sections = beatData.sections || [];
      const selections: any[] = [];
      for (const section of sections) {
        if (cancelRef.current) { handleCancel(); return; }
        const sectionShots = await selectShots(
          clipResults,
          beatData.beats,
          section.type,
          { style: selectedStyle },
          usedRecently
        );
        selections.push({ section: section.type, shots: sectionShots });
        sectionShots.forEach((s: any) => {
          if (s.clipPath) usedRecently.push(s.clipPath);
        });
      }
      setCutDecisions(selections.flatMap(s => s.shots || []));
      updateStatus(`🤖 ${selections.length} sections, ${selections.flatMap(s => s.shots || []).length} cuts selected`, "busy", 85);

      if (cancelRef.current) { handleCancel(); return; }

      // Step 4: Build comp in After Effects
      setGenState("building");
      updateStatus("⚡ Building comp in After Effects...", "busy", 90);

      // Call beginComp
      await evalTS("beginComp", beatData, selectedStyle, audioPath);
      if (cancelRef.current) { handleCancel(); return; }

      // Add clips in batches
      const allShots = selections.flatMap(s => s.shots || []);
      for (let i = 0; i < allShots.length; i++) {
        if (cancelRef.current) { handleCancel(); return; }
        updateStatus(`⚡ Adding clips ${i + 1}/${allShots.length}...`, "busy", 90 + Math.round((i / allShots.length) * 8));
        await evalTS("appendCutBatch", allShots[i]);
      }

      // Finish comp
      await evalTS("finishComp");
      updateStatus("✅ Comp generated! Review your cuts, then add effects and Element 3D.", "ready", 100);
      setGenState("idle");
    } catch (err: any) {
      updateStatus(`❌ ${err.message || err}`, "error");
      setGenState("idle");
    } finally {
      setIsGenerating(false);
      activeJobsRef.current.clear();
    }
  }, [audioPath, clips, selectedStyle, genState, analysis]);

  const handleCancel = useCallback(async () => {
    if (genState === "cancelling") return;
    setGenState("cancelling");
    cancelRef.current = true;
    updateStatus("Stopping…", "warning");

    // Cancel active analysis jobs
    for (const jobId of activeJobsRef.current) {
      try {
        await cancelAnalysisJob(jobId);
      } catch {}
    }
    activeJobsRef.current.clear();

    // Abort AE comp if building
    try {
      await evalTS("abortComp");
    } catch {}

    setGenState("idle");
    setIsGenerating(false);
    updateStatus("Cancelled", "warning");
  }, [genState]);

  const handleRegenerateSection = useCallback(async (sectionType: string) => {
    if (!analysis || clips.length === 0) return;
    updateStatus(`🔄 Regenerating ${sectionType}...`, "busy");
    try {
      const sectionShots = await selectShots(
        clips,
        analysis.beats,
        sectionType,
        { style: selectedStyle },
        []
      );
      // Swap cuts in the comp
      for (const shot of sectionShots) {
        if (shot.clipPath && shot.sectionType === sectionType) {
          await evalTS("swapCut", shot.oldClipPath || "", shot.clipPath);
        }
      }
      updateStatus(`✅ ${sectionType} regenerated`, "ready");
    } catch (err: any) {
      updateStatus(`❌ Regenerate failed: ${err.message}`, "error");
    }
  }, [analysis, clips, selectedStyle]);

  const handleSwap = useCallback(async (index: number, newClipPath: string) => {
    const updated = [...cutDecisions];
    updated[index] = { ...updated[index], clipPath: newClipPath };
    setCutDecisions(updated);
    try {
      await evalTS("swapCut", updated[index].oldClipPath || "", newClipPath);
    } catch (err: any) {
      updateStatus(`❌ Swap failed: ${err.message}`, "error");
    }
  }, [cutDecisions]);

  const handleLock = useCallback((index: number) => {
    const updated = [...cutDecisions];
    updated[index] = { ...updated[index], locked: !updated[index]?.locked };
    setCutDecisions(updated);
  }, [cutDecisions]);

  const handleStartServer = useCallback(async () => {
    updateStatus("Starting Python backend...", "busy");
    const ok = await startPythonServer();
    if (ok) {
      setServerOnline(true);
      updateStatus("Ready", "ready");
    } else {
      updateStatus("❌ Failed to start Python backend", "error");
    }
  }, []);

  // Scan a folder for media files (recursive) — used by MediaImport folder drop
  const handleScanFolder = useCallback(async (folderPath: string) => {
    updateStatus(`📂 Scanning ${folderPath}...`, "busy");
    try {
      const result = await scanMedia(folderPath);
      const newClips = result.files.map((path) => ({
        path,
        name: path.split(/[/\\]/).pop() || path,
        duration: 0,
        scene_type: "pending",
        has_face: false,
        brightness: 0,
        motion_intensity: 0,
      }));
      setClips([...clips, ...newClips]);
      updateStatus(`✅ Imported ${newClips.length} clips (${result.skipped} skipped)`, "ready");
    } catch (err: any) {
      updateStatus(`❌ Scan failed: ${err.message}`, "error");
    }
  }, [clips]);

  // Bridge health info for diagnostics
  const bridgeHealth = bridgeInfo;

  const statusText = genState === "cancelling" ? "Stopping…" : status;

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
            <span className="version-badge">v{VERSION}</span>
          </div>
          <div className="topbar-actions">
            <span className={`server-indicator ${serverOnline ? "online" : "offline"}`} title={`${bridgeInfo.appId} v${bridgeInfo.version}`}>
              {serverOnline ? "●" : "○"}
            </span>
            {!serverOnline && (
              <button className="icon-btn" onClick={handleStartServer} title="Start backend">
                ▶
              </button>
            )}
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
              onSwap={handleSwap}
              onLock={handleLock}
              onRegenerateSection={handleRegenerateSection}
            />
          )}
          {activeTab === "analysis" && <AnalysisView analysis={analysis} />}
        </div>

        {/* Bottom bar */}
        <footer className="app-bottombar">
          <div className="status-row">
            <span className={`status-dot ${statusState}`} />
            <span className="status-text">{statusText}</span>
            {isGenerating && genState !== "cancelling" && (
              <button className="cancel-btn" onClick={handleCancel}>
                Cancel task
              </button>
            )}
          </div>
          {progress > 0 && progress < 100 && (
            <div className="progress-bar">
              <div className="progress-fill" style={{ width: `${progress}%` }} />
            </div>
          )}
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
