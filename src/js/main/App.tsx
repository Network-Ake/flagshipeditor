import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import MediaImport from "./components/MediaImport";
import StyleSelector from "./components/StyleSelector";
import Parameters from "./components/Parameters";
import Element3DPanel, { Element3DDetection } from "./components/Element3DPanel";
import AnalysisView from "./components/AnalysisView";
import ReviewMode from "./components/ReviewMode";
import {
  BRIDGE_ID,
  BRIDGE_VERSION,
  evalTSTimed,
  getBridgeHealth,
  getExtensionPath,
  isHostAvailable,
  openFile,
  openFiles,
  openFolder,
  startBackendProcess,
} from "./lib/bolt";
import {
  ANALYSIS_TERMINAL_STATES,
  AnalysisJobStatus,
  BeatAnalysis,
  BeatProgress,
  ClipInfo,
  CutAlternative,
  CutDecision,
  MediaProfile,
  ServerHealth,
  cancelAnalysisJob,
  createAnalysisJob,
  describeHealthGap,
  getAnalysisJob,
  getAnalysisJobResult,
  getBeatProgress,
  getServerHealth,
  runBeatAnalysis,
  scanMedia,
  selectShots,
} from "./lib/python";
import { pollPersistentJob, retryTransientOperation } from "./lib/resilient-job";
import {
  EditingParameters,
  Element3DSettings,
  StyleConfig,
  buildRuntimeStyle,
  defaultEffectToggles,
  loadStyle,
} from "./lib/styles";

type Tab = "media" | "style" | "params" | "3d" | "review" | "analysis";
type Phase =
  | "idle"
  | "importing"
  | "analyzing-clips"
  | "analyzing-beat"
  | "selecting"
  | "building"
  | "regenerating"
  | "cancelling";
type StatusState = "ready" | "busy" | "error" | "warning";

interface Notice {
  id: number;
  tone: "error" | "warning" | "success";
  title: string;
  text: string;
}

interface FailedClip {
  path: string;
  message: string;
}

interface BeginCompResult {
  started: boolean;
  compName: string;
  width: number;
  height: number;
  fps: number;
}

interface AppendBatchResult {
  added: number;
  skipped: number;
  totalAdded: number;
}

interface FinishCompResult {
  message: string;
  clipsAdded: number;
  warnings: string[];
}

interface SwapResult {
  updated: number;
  message?: string;
}

interface ReplaceSectionResult {
  updated: number;
  missing: number;
}

interface Element3DProbeResult {
  installed: boolean;
  matchName: string | null;
}

interface TimelineCutPayload {
  beatTime: number;
  endTime: number;
  clipPath: string;
  clipName: string;
  sectionType: string;
}

const TABS: { id: Tab; icon: string; label: string }[] = [
  { id: "media", icon: "📁", label: "Media" },
  { id: "style", icon: "🎨", label: "Style" },
  { id: "params", icon: "🎛", label: "Params" },
  { id: "3d", icon: "🧊", label: "3D" },
  { id: "review", icon: "👁", label: "Review" },
  { id: "analysis", icon: "📊", label: "Analysis" },
];

const VERSION = BRIDGE_VERSION;
const CLIP_FILTER = "Video files:*.mov;*.mp4;*.m4v;*.avi;*.mxf,All files:*.*";
const AUDIO_FILTER = "Audio files:*.mp3;*.wav;*.aac;*.m4a;*.flac,All files:*.*";
const DEFAULT_MEDIA_PROFILE: MediaProfile = { width: 1920, height: 1080, fps: 30 };
const HEALTH_INTERVAL_MS = 10000;
const BEAT_PROGRESS_INTERVAL_MS = 1000;
const BACKEND_BOOT_ATTEMPTS = 12;
const MAX_CUTS_PER_BATCH = 25;
const MAX_BATCH_PAYLOAD = 18000;
const BEGIN_COMP_TIMEOUT_MS = 180000;
const BATCH_TIMEOUT_MS = 300000;
const FINISH_COMP_TIMEOUT_MS = 300000;
const SWAP_TIMEOUT_MS = 120000;

/** Raised at a cancellation checkpoint so one catch ends the whole run. */
class CancelledError extends Error {
  constructor() {
    super("Cancelled");
    this.name = "CancelledError";
  }
}

function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error);
}

function baseName(path: string): string {
  const parts = path.split(/[/\\]/);
  return parts[parts.length - 1] || path;
}

function placeholderClip(path: string): ClipInfo {
  return {
    path,
    name: baseName(path),
    duration: 0,
    scene_type: "pending",
    has_face: false,
    brightness: 0,
    motion_intensity: 0,
    analyzed: false,
  };
}

function delay(milliseconds: number): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, milliseconds);
  });
}

function toPayload(cut: CutDecision): TimelineCutPayload {
  return {
    beatTime: cut.beatTime,
    endTime: cut.endTime,
    clipPath: cut.clipPath,
    clipName: cut.clipName,
    sectionType: cut.sectionType,
  };
}

/**
 * Split the timeline into evalScript-sized batches. The bridge caps a call at
 * 24 KB and After Effects at 30 layers per call, so both limits are enforced
 * here rather than discovered as a failed build halfway through.
 */
function chunkCuts(cuts: CutDecision[]): TimelineCutPayload[][] {
  const batches: TimelineCutPayload[][] = [];
  let current: TimelineCutPayload[] = [];
  let size = 2;
  for (const cut of cuts) {
    const payload = toPayload(cut);
    const encoded = JSON.stringify(payload).length + 1;
    if (current.length > 0 && (current.length >= MAX_CUTS_PER_BATCH || size + encoded > MAX_BATCH_PAYLOAD)) {
      batches.push(current);
      current = [];
      size = 2;
    }
    current.push(payload);
    size += encoded;
  }
  if (current.length > 0) batches.push(current);
  return batches;
}

const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState<Tab>("media");
  const [clips, setClips] = useState<ClipInfo[]>([]);
  const [audioPath, setAudioPath] = useState("");
  const [styleId, setStyleId] = useState("cmd_command_drill");
  const [customStyles, setCustomStyles] = useState<Record<string, StyleConfig>>({});
  const [params, setParams] = useState<EditingParameters>(() => ({
    cutIntensity: 7,
    vfxIntensity: 5,
    colorGrading: 6,
    seed: 1,
    beatSubdivision: 1,
    effects: defaultEffectToggles(loadStyle("cmd_command_drill")),
  }));
  const [element3D, setElement3D] = useState<Element3DSettings>({
    parallaxDepth: 0.4,
    autoCamera: true,
  });
  const [element3DDetection, setElement3DDetection] = useState<Element3DDetection>({
    state: "unknown",
    matchName: "",
    message: "",
  });
  const [analysis, setAnalysis] = useState<BeatAnalysis | null>(null);
  const [beatProgress, setBeatProgress] = useState<BeatProgress | null>(null);
  const [cuts, setCuts] = useState<CutDecision[]>([]);
  const [mediaProfile, setMediaProfile] = useState<MediaProfile>(DEFAULT_MEDIA_PROFILE);
  const [analyzingPaths, setAnalyzingPaths] = useState<string[]>([]);
  const [failedClips, setFailedClips] = useState<FailedClip[]>([]);
  const [phase, setPhase] = useState<Phase>("idle");
  const [status, setStatus] = useState("Ready");
  const [statusState, setStatusState] = useState<StatusState>("ready");
  const [progress, setProgress] = useState(0);
  const [notices, setNotices] = useState<Notice[]>([]);
  const [health, setHealth] = useState<ServerHealth | null>(null);
  const [serverOnline, setServerOnline] = useState(false);
  const [hostAvailable] = useState(() => isHostAvailable());

  const cancelRef = useRef(false);
  const activeJobRef = useRef<string | null>(null);
  const buildActiveRef = useRef(false);
  const beatTimerRef = useRef<number | null>(null);
  const noticeIdRef = useRef(1);
  const clipsRef = useRef<ClipInfo[]>(clips);
  clipsRef.current = clips;

  const activeStyle = useMemo<StyleConfig>(
    () => customStyles[styleId] || loadStyle(styleId),
    [customStyles, styleId]
  );

  const busy = phase !== "idle";
  const analyzedClips = useMemo(
    () => clips.filter((clip) => clip.analyzed && clip.usable !== false),
    [clips]
  );

  const pushNotice = useCallback((tone: Notice["tone"], title: string, text: string) => {
    const id = noticeIdRef.current;
    noticeIdRef.current += 1;
    setNotices((previous) => previous.concat({ id, tone, title, text }).slice(-4));
  }, []);

  const dismissNotice = useCallback((id: number) => {
    setNotices((previous) => previous.filter((notice) => notice.id !== id));
  }, []);

  const updateStatus = useCallback((message: string, state: StatusState, percent?: number) => {
    setStatus(message);
    setStatusState(state);
    if (percent !== undefined) setProgress(Math.max(0, Math.min(100, percent)));
  }, []);

  const checkpoint = useCallback(() => {
    if (cancelRef.current) throw new CancelledError();
  }, []);

  // --- Backend health ------------------------------------------------------

  const refreshHealth = useCallback(async () => {
    try {
      const report = await getServerHealth();
      setHealth(report);
      setServerOnline(true);
      return report;
    } catch {
      setHealth(null);
      setServerOnline(false);
      return null;
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    const tick = () => {
      if (!cancelled) void refreshHealth();
    };
    tick();
    const timer = window.setInterval(tick, HEALTH_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [refreshHealth]);

  useEffect(() => {
    if (!health) return;
    const gap = describeHealthGap(health);
    if (gap) pushNotice("warning", "Backend incomplete", gap);
  }, [health, pushNotice]);

  // The ExtendScript bridge ships inside the same extension as this panel; a
  // mismatch means a stale jsx/index.js survived an install and the two halves
  // no longer agree on the payload contract.
  useEffect(() => {
    if (!isHostAvailable()) return;
    let cancelled = false;
    void (async () => {
      try {
        const bridge = await getBridgeHealth();
        if (cancelled) return;
        if (bridge.appId !== BRIDGE_ID || bridge.version !== BRIDGE_VERSION) {
          pushNotice(
            "warning",
            "After Effects bridge mismatch",
            `Panel ${BRIDGE_ID} ${BRIDGE_VERSION} is talking to ${bridge.appId} ${bridge.version}. Reinstall the extension.`
          );
        }
      } catch (error) {
        if (!cancelled) {
          pushNotice("warning", "After Effects bridge unavailable", errorMessage(error));
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [pushNotice]);

  useEffect(() => {
    return () => {
      if (beatTimerRef.current !== null) window.clearInterval(beatTimerRef.current);
    };
  }, []);

  const handleStartBackend = useCallback(async () => {
    updateStatus("Starting the analysis backend…", "busy");
    try {
      const launch = await startBackendProcess();
      for (let attempt = 0; attempt < BACKEND_BOOT_ATTEMPTS; attempt += 1) {
        await delay(1000);
        const report = await refreshHealth();
        if (report) {
          updateStatus("Backend online", "ready");
          return;
        }
      }
      updateStatus("The backend did not answer", "error");
      pushNotice(
        "error",
        "Backend did not start",
        `Launched ${launch.launcher} but 127.0.0.1:18791 never answered. Start it manually and check the console window.`
      );
    } catch (error) {
      updateStatus("The backend could not be started", "error");
      pushNotice("error", "Backend could not be started", errorMessage(error));
    }
  }, [pushNotice, refreshHealth, updateStatus]);

  // --- Clip analysis -------------------------------------------------------

  const analyzeClips = useCallback(
    async (paths: string[]): Promise<ClipInfo[]> => {
      if (paths.length === 0) return clipsRef.current;
      setPhase("analyzing-clips");
      setAnalyzingPaths(paths);
      updateStatus(`Analysing ${paths.length} clip(s)…`, "busy", 0);
      try {
        const job = await retryTransientOperation(() => createAnalysisJob(paths));
        activeJobRef.current = job.jobId;
        const finalStatus = await pollPersistentJob<AnalysisJobStatus>({
          terminalStates: ANALYSIS_TERMINAL_STATES,
          getStatus: () => getAnalysisJob(job.jobId),
          cancel: () => cancelAnalysisJob(job.jobId),
          cancellationRequested: () => cancelRef.current,
          onStatus: (current) => {
            setAnalyzingPaths(current.currentFiles.length > 0 ? current.currentFiles : []);
            const eta = current.etaSeconds !== null ? ` · ${Math.round(current.etaSeconds)}s left` : "";
            updateStatus(
              `Analysing clips ${current.completed}/${current.total}${eta}`,
              "busy",
              current.progress
            );
          },
          onReconnect: (notice) =>
            updateStatus(`Backend unreachable — reconnecting (${notice.attempt})…`, "warning"),
        });
        activeJobRef.current = null;

        const payload = await getAnalysisJobResult(job.jobId);
        const analysed = new Map(payload.results.map((clip) => [clip.path, clip]));
        const merged = clipsRef.current.map((clip) => {
          const update = analysed.get(clip.path);
          return update ? { ...clip, ...update, analyzed: true } : clip;
        });
        clipsRef.current = merged;
        setClips(merged);

        const failures = payload.errors.map((entry) => ({ path: entry.path, message: entry.message }));
        setFailedClips((previous) => {
          const kept = previous.filter((entry) => !paths.includes(entry.path));
          return kept.concat(failures);
        });

        if (finalStatus.state === "cancelled") {
          updateStatus("Clip analysis cancelled", "warning");
        } else if (failures.length > 0) {
          updateStatus(`${failures.length} clip(s) could not be analysed`, "warning", 100);
          pushNotice(
            "warning",
            `${failures.length} clip(s) failed analysis`,
            failures[0].message
          );
        } else {
          updateStatus(`Analysed ${payload.results.length} clip(s)`, "ready", 100);
        }
        return merged;
      } finally {
        activeJobRef.current = null;
        setAnalyzingPaths([]);
        setPhase((current) => (current === "analyzing-clips" ? "idle" : current));
      }
    },
    [pushNotice, updateStatus]
  );

  const addClips = useCallback(
    async (paths: string[]) => {
      const known = new Set(clipsRef.current.map((clip) => clip.path));
      const fresh = paths.filter((path) => path && !known.has(path));
      if (fresh.length === 0) {
        updateStatus("Those clips are already imported", "warning");
        return;
      }
      const merged = clipsRef.current.concat(fresh.map(placeholderClip));
      clipsRef.current = merged;
      setClips(merged);
      cancelRef.current = false;
      try {
        await analyzeClips(fresh);
      } catch (error) {
        if (error instanceof CancelledError) return;
        updateStatus("Clip analysis failed", "error");
        pushNotice("error", "Clip analysis failed", errorMessage(error));
      }
    },
    [analyzeClips, pushNotice, updateStatus]
  );

  const handleImportClips = useCallback(async () => {
    try {
      const paths = await openFiles(CLIP_FILTER);
      if (paths.length === 0) return;
      await addClips(paths);
    } catch (error) {
      pushNotice("error", "Import failed", errorMessage(error));
    }
  }, [addClips, pushNotice]);

  const handleImportFolder = useCallback(async () => {
    try {
      const folder = await openFolder();
      if (!folder) return;
      setPhase("importing");
      updateStatus(`Scanning ${folder}…`, "busy");
      const scan = await retryTransientOperation(() => scanMedia(folder, true));
      setPhase("idle");
      if (scan.paths.length === 0) {
        updateStatus("That folder holds no supported video files", "warning");
        return;
      }
      updateStatus(`Found ${scan.totalFiles} clip(s), ${scan.skipped} skipped`, "busy");
      await addClips(scan.paths);
    } catch (error) {
      setPhase("idle");
      updateStatus("Folder scan failed", "error");
      pushNotice("error", "Folder scan failed", errorMessage(error));
    }
  }, [addClips, pushNotice, updateStatus]);

  const handleImportMusic = useCallback(async () => {
    try {
      const path = await openFile(AUDIO_FILTER);
      if (!path) return;
      setAudioPath(path);
      setAnalysis(null);
      setBeatProgress(null);
      updateStatus(`Music set: ${baseName(path)}`, "ready");
    } catch (error) {
      pushNotice("error", "Music import failed", errorMessage(error));
    }
  }, [pushNotice, updateStatus]);

  const handleRemoveClip = useCallback((path: string) => {
    setClips((previous) => previous.filter((clip) => clip.path !== path));
    setFailedClips((previous) => previous.filter((entry) => entry.path !== path));
  }, []);

  const handleClearClips = useCallback(() => {
    setClips([]);
    setFailedClips([]);
    setCuts([]);
  }, []);

  const handleRetryFailed = useCallback(async () => {
    const paths = failedClips.map((entry) => entry.path);
    if (paths.length === 0) return;
    setFailedClips([]);
    cancelRef.current = false;
    try {
      await analyzeClips(paths);
    } catch (error) {
      if (error instanceof CancelledError) return;
      pushNotice("error", "Retry failed", errorMessage(error));
    }
  }, [analyzeClips, failedClips, pushNotice]);

  // --- Style & parameters --------------------------------------------------

  const handleSelectStyle = useCallback(
    (nextId: string) => {
      setStyleId(nextId);
      const style = customStyles[nextId] || loadStyle(nextId);
      setParams((previous) => ({ ...previous, effects: defaultEffectToggles(style) }));
      const depth = style.element_3d && typeof style.element_3d.parallax_depth === "number"
        ? (style.element_3d.parallax_depth as number)
        : element3D.parallaxDepth;
      setElement3D((previous) => ({ ...previous, parallaxDepth: depth }));
    },
    [customStyles, element3D.parallaxDepth]
  );

  const handleCustomizeStyle = useCallback(
    (targetId: string, style: StyleConfig) => {
      setCustomStyles((previous) => ({ ...previous, [targetId]: style }));
      setParams((previous) => ({ ...previous, effects: defaultEffectToggles(style) }));
      pushNotice("success", "Preset updated", `${style.display_name} now uses your edited JSON.`);
    },
    [pushNotice]
  );

  const handleResetCustomization = useCallback(
    (targetId: string) => {
      setCustomStyles((previous) => {
        const next = { ...previous };
        delete next[targetId];
        return next;
      });
      setParams((previous) => ({ ...previous, effects: defaultEffectToggles(loadStyle(targetId)) }));
    },
    []
  );

  const handleResetEffects = useCallback(() => {
    setParams((previous) => ({ ...previous, effects: defaultEffectToggles(activeStyle) }));
  }, [activeStyle]);

  const handleProbeElement3D = useCallback(async () => {
    if (!hostAvailable) {
      setElement3DDetection({
        state: "error",
        matchName: "",
        message: "After Effects is not connected to this panel.",
      });
      return;
    }
    setElement3DDetection({ state: "checking", matchName: "", message: "" });
    try {
      const result = await evalTSTimed<Element3DProbeResult>("probeElement3D", 30000);
      setElement3DDetection({
        state: result.installed ? "installed" : "missing",
        matchName: result.matchName || "",
        message: "",
      });
    } catch (error) {
      setElement3DDetection({ state: "error", matchName: "", message: errorMessage(error) });
    }
  }, [hostAvailable]);

  useEffect(() => {
    if (hostAvailable) void handleProbeElement3D();
    // The probe only has to run once per panel session.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hostAvailable]);

  // --- Generation ----------------------------------------------------------

  const stopBeatProgress = useCallback(() => {
    if (beatTimerRef.current !== null) {
      window.clearInterval(beatTimerRef.current);
      beatTimerRef.current = null;
    }
  }, []);

  const startBeatProgress = useCallback(() => {
    stopBeatProgress();
    beatTimerRef.current = window.setInterval(() => {
      void getBeatProgress()
        .then((report) => {
          setBeatProgress(report);
          if (report.state === "running") {
            updateStatus(`Beat analysis — ${report.step}`, "busy", 5 + report.progress * 0.2);
          }
        })
        .catch(() => undefined);
    }, BEAT_PROGRESS_INTERVAL_MS);
  }, [stopBeatProgress, updateStatus]);

  const buildComposition = useCallback(
    async (
      decisions: CutDecision[],
      beat: BeatAnalysis,
      runtimeStyle: StyleConfig,
      profile: MediaProfile
    ) => {
      const extensionPath = await getExtensionPath();
      checkpoint();
      updateStatus("Creating the composition…", "busy", 78);
      await evalTSTimed<BeginCompResult>(
        "beginComp",
        BEGIN_COMP_TIMEOUT_MS,
        beat.duration,
        audioPath,
        runtimeStyle,
        params,
        element3D,
        beat.sections,
        extensionPath,
        profile,
        beat.tempo
      );
      buildActiveRef.current = true;

      const batches = chunkCuts(decisions);
      let placed = 0;
      let skipped = 0;
      for (let index = 0; index < batches.length; index += 1) {
        checkpoint();
        const result = await evalTSTimed<AppendBatchResult>(
          "appendCutBatch",
          BATCH_TIMEOUT_MS,
          batches[index]
        );
        placed += result.added;
        skipped += result.skipped;
        updateStatus(
          `Placing clips ${placed}/${decisions.length}…`,
          "busy",
          80 + Math.round(((index + 1) / batches.length) * 15)
        );
      }

      checkpoint();
      updateStatus("Applying grading, 3D and markers…", "busy", 96);
      const finished = await evalTSTimed<FinishCompResult>("finishComp", FINISH_COMP_TIMEOUT_MS);
      buildActiveRef.current = false;

      if (skipped > 0) {
        pushNotice(
          "warning",
          `${skipped} cut(s) skipped`,
          "After Effects could not place every clip. Check the missing files in the Review tab."
        );
      }
      for (const warning of finished.warnings.slice(0, 3)) {
        pushNotice("warning", "Build warning", warning);
      }
      updateStatus(`${finished.message} — ${finished.clipsAdded} clips placed`, "ready", 100);
    },
    [audioPath, checkpoint, element3D, params, pushNotice, updateStatus]
  );

  const handleGenerate = useCallback(async () => {
    if (busy) return;
    if (!audioPath) {
      updateStatus("Import a music track first", "warning");
      setActiveTab("media");
      return;
    }
    if (clipsRef.current.length === 0) {
      updateStatus("Import clips first", "warning");
      setActiveTab("media");
      return;
    }
    if (!serverOnline) {
      updateStatus("The analysis backend is offline", "error");
      pushNotice("error", "Backend offline", "Start the backend from the panel header, then generate again.");
      return;
    }
    if (!hostAvailable) {
      updateStatus("After Effects is not connected", "error");
      pushNotice(
        "error",
        "After Effects not connected",
        "Open FlagshipEditor from Window > Extensions inside After Effects to build a composition."
      );
      return;
    }

    cancelRef.current = false;
    buildActiveRef.current = false;
    setNotices([]);
    setProgress(0);

    try {
      const pending = clipsRef.current.filter((clip) => !clip.analyzed).map((clip) => clip.path);
      const library = pending.length > 0 ? await analyzeClips(pending) : clipsRef.current;
      checkpoint();

      const usable = library.filter((clip) => clip.analyzed && clip.usable !== false);
      if (usable.length === 0) {
        throw new Error("No clip survived analysis. Import footage After Effects can decode.");
      }

      setPhase("analyzing-beat");
      updateStatus("Analysing the track…", "busy", 5);
      startBeatProgress();
      let beat: BeatAnalysis;
      try {
        beat = await runBeatAnalysis(audioPath);
      } finally {
        stopBeatProgress();
      }
      setAnalysis(beat);
      checkpoint();
      updateStatus(
        `${beat.tempo.toFixed(1)} BPM · ${beat.key} ${beat.mode} · ${beat.sections.length} sections`,
        "busy",
        30
      );

      setPhase("selecting");
      updateStatus("Planning the cut grid…", "busy", 45);
      const runtimeStyle = buildRuntimeStyle(activeStyle, params);
      const selection = await retryTransientOperation(() =>
        selectShots({
          clips: usable,
          beats: beat.beats,
          sections: beat.sections,
          styleConfig: runtimeStyle,
          duration: beat.duration,
          tempo: beat.tempo,
          bassOnsets: beat.bass_onsets,
          seed: params.seed,
        })
      );
      checkpoint();
      setCuts(selection.selections);
      setMediaProfile(selection.mediaProfile);
      updateStatus(`${selection.cutCount} cuts planned`, "busy", 70);

      setPhase("building");
      await buildComposition(selection.selections, beat, runtimeStyle, selection.mediaProfile);
      setActiveTab("review");
    } catch (error) {
      if (error instanceof CancelledError) {
        updateStatus("Cancelled", "warning", 0);
      } else {
        updateStatus(errorMessage(error), "error");
        pushNotice("error", "Generation failed", errorMessage(error));
      }
      if (buildActiveRef.current) {
        try {
          await evalTSTimed<{ aborted: boolean }>("abortComp", 30000);
        } catch (abortError) {
          pushNotice("warning", "Cleanup incomplete", errorMessage(abortError));
        }
        buildActiveRef.current = false;
      }
    } finally {
      stopBeatProgress();
      setPhase("idle");
    }
  }, [
    activeStyle,
    analyzeClips,
    audioPath,
    buildComposition,
    busy,
    checkpoint,
    hostAvailable,
    params,
    pushNotice,
    serverOnline,
    startBeatProgress,
    stopBeatProgress,
    updateStatus,
  ]);

  const handleCancel = useCallback(async () => {
    if (phase === "idle" || phase === "cancelling") return;
    cancelRef.current = true;
    setPhase("cancelling");
    updateStatus("Stopping…", "warning");
    const jobId = activeJobRef.current;
    if (jobId) {
      try {
        await cancelAnalysisJob(jobId);
      } catch (error) {
        pushNotice("warning", "Cancel incomplete", errorMessage(error));
      }
    }
  }, [phase, pushNotice, updateStatus]);

  // --- Review actions ------------------------------------------------------

  const applySwap = useCallback(
    async (index: number, alternative: CutAlternative, list: CutDecision[]): Promise<boolean> => {
      const cut = list[index];
      if (!cut || cut.locked) return false;
      const result = await evalTSTimed<SwapResult>(
        "swapCut",
        SWAP_TIMEOUT_MS,
        cut.beatTime,
        cut.sectionType,
        alternative.clipPath,
        alternative.clipName
      );
      if (result.updated === 0) {
        pushNotice("warning", "Cut not swapped", result.message || "The cut layer was not found.");
        return false;
      }
      return true;
    },
    [pushNotice]
  );

  const handleSwap = useCallback(
    async (indices: number[], alternative: CutAlternative) => {
      if (!hostAvailable) {
        pushNotice("error", "After Effects not connected", "Open the panel inside After Effects to swap a cut.");
        return;
      }
      setPhase("building");
      updateStatus(`Swapping ${indices.length} cut(s)…`, "busy");
      const list = cuts;
      const applied: number[] = [];
      try {
        for (const index of indices) {
          const done = await applySwap(index, alternative, list);
          if (done) applied.push(index);
        }
        if (applied.length > 0) {
          setCuts((previous) =>
            previous.map((cut, index) => {
              if (applied.indexOf(index) === -1) return cut;
              const replaced: CutAlternative = {
                clipPath: cut.clipPath,
                clipName: cut.clipName,
                thumbnailId: cut.thumbnailId,
                sceneType: cut.sceneType,
                score: cut.score,
              };
              return {
                ...cut,
                clipPath: alternative.clipPath,
                clipName: alternative.clipName,
                thumbnailId: alternative.thumbnailId,
                sceneType: alternative.sceneType,
                score: alternative.score,
                alternatives: [replaced].concat(
                  cut.alternatives.filter((entry) => entry.clipPath !== alternative.clipPath)
                ),
              };
            })
          );
        }
        updateStatus(`Swapped ${applied.length}/${indices.length} cut(s)`, applied.length > 0 ? "ready" : "warning");
      } catch (error) {
        updateStatus("Swap failed", "error");
        pushNotice("error", "Swap failed", errorMessage(error));
      } finally {
        setPhase("idle");
      }
    },
    [applySwap, cuts, hostAvailable, pushNotice, updateStatus]
  );

  const handleToggleLock = useCallback((index: number) => {
    setCuts((previous) =>
      previous.map((cut, position) => (position === index ? { ...cut, locked: !cut.locked } : cut))
    );
  }, []);

  const handleReorder = useCallback(
    async (from: number, to: number) => {
      if (from === to) return;
      const source = cuts;
      if (from >= source.length || to >= source.length) return;
      if (source[from].locked || source[to].locked) {
        pushNotice("warning", "Cut is locked", "Unlock both cuts before moving a clip between them.");
        return;
      }

      // The beat grid never moves: only the clip assigned to each slot travels.
      const payloads = source.map((cut) => ({
        clipPath: cut.clipPath,
        clipName: cut.clipName,
        thumbnailId: cut.thumbnailId,
        sceneType: cut.sceneType,
        clipDuration: cut.clipDuration,
        score: cut.score,
        scores: cut.scores,
        alternatives: cut.alternatives,
      }));
      const [moved] = payloads.splice(from, 1);
      payloads.splice(to, 0, moved);

      const next = source.map((cut, index) => ({ ...cut, ...payloads[index] }));
      const changed: number[] = [];
      for (let index = 0; index < next.length; index += 1) {
        if (next[index].clipPath !== source[index].clipPath) changed.push(index);
      }
      if (changed.length === 0) return;

      setCuts(next);
      if (!hostAvailable) return;

      setPhase("building");
      updateStatus(`Moving ${changed.length} clip(s) in After Effects…`, "busy");
      try {
        for (const index of changed) {
          const cut = next[index];
          const result = await evalTSTimed<SwapResult>(
            "swapCut",
            SWAP_TIMEOUT_MS,
            cut.beatTime,
            cut.sectionType,
            cut.clipPath,
            cut.clipName
          );
          if (result.updated === 0) {
            pushNotice("warning", "Cut not moved", result.message || "The cut layer was not found.");
          }
        }
        updateStatus("Timeline reordered", "ready");
      } catch (error) {
        updateStatus("Reorder failed", "error");
        pushNotice("error", "Reorder failed", errorMessage(error));
        setCuts(source);
      } finally {
        setPhase("idle");
      }
    },
    [cuts, hostAvailable, pushNotice, updateStatus]
  );

  const handleRegenerateSection = useCallback(
    async (sectionType: string) => {
      if (busy) return;
      if (!analysis) {
        pushNotice("warning", "Nothing to regenerate", "Generate an edit before regenerating a section.");
        return;
      }
      const usable = analyzedClips;
      if (usable.length === 0) {
        pushNotice("warning", "No analysed clips", "Import and analyse clips before regenerating.");
        return;
      }

      setPhase("regenerating");
      updateStatus(`Regenerating ${sectionType}…`, "busy");
      try {
        const runtimeStyle = buildRuntimeStyle(activeStyle, params);
        const selection = await retryTransientOperation(() =>
          selectShots({
            clips: usable,
            beats: analysis.beats,
            sections: analysis.sections,
            styleConfig: runtimeStyle,
            duration: analysis.duration,
            tempo: analysis.tempo,
            bassOnsets: analysis.bass_onsets,
            // A fresh seed is what makes a regeneration produce a new take.
            seed: 1 + Math.floor(Math.random() * 999998),
          })
        );

        const replacements = new Map<string, CutDecision>();
        for (const decision of selection.selections) {
          if (decision.sectionType === sectionType) {
            replacements.set(decision.beatTime.toFixed(4), decision);
          }
        }

        const next: CutDecision[] = [];
        const toReplace: CutDecision[] = [];
        for (const cut of cuts) {
          if (cut.sectionType !== sectionType || cut.locked) {
            next.push(cut);
            continue;
          }
          const replacement = replacements.get(cut.beatTime.toFixed(4));
          if (!replacement || replacement.clipPath === cut.clipPath) {
            next.push(cut);
            continue;
          }
          const merged = { ...replacement, locked: false };
          next.push(merged);
          toReplace.push(merged);
        }

        if (toReplace.length === 0) {
          updateStatus(`${sectionType} already holds the best takes`, "ready");
          return;
        }

        setCuts(next);
        if (hostAvailable) {
          const result = await evalTSTimed<ReplaceSectionResult>(
            "replaceSectionCuts",
            BATCH_TIMEOUT_MS,
            sectionType,
            toReplace.map(toPayload)
          );
          if (result.missing > 0) {
            pushNotice(
              "warning",
              `${result.missing} cut(s) not replaced`,
              "Those layers are missing from the generated comp."
            );
          }
          updateStatus(`${sectionType}: ${result.updated} cut(s) regenerated`, "ready");
        } else {
          updateStatus(`${sectionType}: ${toReplace.length} cut(s) re-planned`, "ready");
        }
      } catch (error) {
        updateStatus("Regeneration failed", "error");
        pushNotice("error", "Regeneration failed", errorMessage(error));
      } finally {
        setPhase("idle");
      }
    },
    [activeStyle, analysis, analyzedClips, busy, cuts, hostAvailable, params, pushNotice, updateStatus]
  );

  // --- Render --------------------------------------------------------------

  const canGenerate =
    !busy && serverOnline && hostAvailable && audioPath !== "" && clips.length > 0;
  const generateHint = !hostAvailable
    ? "After Effects is not connected to this panel"
    : !serverOnline
      ? "The analysis backend is offline"
      : clips.length === 0
        ? "Import clips first"
        : !audioPath
          ? "Import a music track first"
          : "";

  return (
    <div className="app-shell">
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

      <main className="app-main">
        <header className="app-topbar">
          <div className="topbar-brand">
            <span className="brand-name">FlagshipEditor</span>
            <span className="version-badge">v{VERSION}</span>
          </div>
          <div className="topbar-actions">
            <span
              className={`server-indicator ${serverOnline ? "online" : "offline"}`}
              title={
                health
                  ? `Backend ${health.version} · pid ${health.processId} · ${health.status}`
                  : "Analysis backend offline"
              }
            >
              {serverOnline ? "●" : "○"}
            </span>
            {!serverOnline && (
              <button className="icon-btn" onClick={handleStartBackend} title="Start the backend" disabled={busy}>
                ▶
              </button>
            )}
            <span className={`host-indicator ${hostAvailable ? "online" : "offline"}`} title={
              hostAvailable ? "After Effects bridge connected" : "Running outside After Effects"
            }>
              AE
            </span>
          </div>
        </header>

        {notices.length > 0 && (
          <div className="notice-stack">
            {notices.map((notice) => (
              <div key={notice.id} className={`alert alert-${notice.tone}`}>
                <div className="alert-body">
                  <div className="alert-title">{notice.title}</div>
                  <div className="alert-text">{notice.text}</div>
                </div>
                <button
                  className="link-btn"
                  onClick={() => dismissNotice(notice.id)}
                  aria-label="Dismiss"
                >
                  ✕
                </button>
              </div>
            ))}
          </div>
        )}

        <div className="app-content">
          {activeTab === "media" && (
            <MediaImport
              clips={clips}
              audioPath={audioPath}
              busy={busy}
              analyzingPaths={analyzingPaths}
              failedClips={failedClips}
              onImportClips={handleImportClips}
              onImportFolder={handleImportFolder}
              onImportMusic={handleImportMusic}
              onRemoveClip={handleRemoveClip}
              onClearClips={handleClearClips}
              onRetryFailed={handleRetryFailed}
            />
          )}
          {activeTab === "style" && (
            <StyleSelector
              selected={styleId}
              style={activeStyle}
              customized={Boolean(customStyles[styleId])}
              onSelect={handleSelectStyle}
              onCustomize={handleCustomizeStyle}
              onResetCustomization={handleResetCustomization}
            />
          )}
          {activeTab === "params" && (
            <Parameters
              params={params}
              style={activeStyle}
              disabled={busy}
              onChange={setParams}
              onResetToStyle={handleResetEffects}
            />
          )}
          {activeTab === "3d" && (
            <Element3DPanel
              settings={element3D}
              enabled={params.effects.element_3d === true}
              detection={element3DDetection}
              disabled={busy}
              onChange={setElement3D}
              onToggleEnabled={(enabled) =>
                setParams((previous) => ({
                  ...previous,
                  effects: { ...previous.effects, element_3d: enabled },
                }))
              }
              onProbe={handleProbeElement3D}
            />
          )}
          {activeTab === "review" && (
            <ReviewMode
              cuts={cuts}
              busy={busy}
              onSwap={handleSwap}
              onToggleLock={handleToggleLock}
              onReorder={handleReorder}
              onRegenerateSection={handleRegenerateSection}
            />
          )}
          {activeTab === "analysis" && (
            <AnalysisView
              analysis={analysis}
              beatProgress={beatProgress}
              clips={clips}
              busy={busy}
            />
          )}
        </div>

        <footer className="app-bottombar">
          <div className="status-row">
            <span className={`status-dot ${statusState}`} />
            <span className="status-text" title={status}>
              {status}
            </span>
            {busy && phase !== "cancelling" && (
              <button className="cancel-btn" onClick={handleCancel}>
                Cancel task
              </button>
            )}
          </div>
          {busy && (
            <div
              className="progress-bar"
              role="progressbar"
              aria-label={status}
              aria-valuenow={Math.round(progress)}
              aria-valuemin={0}
              aria-valuemax={100}
            >
              <div className="progress-fill" style={{ width: `${Math.max(2, progress)}%` }} />
            </div>
          )}
          <button
            className="generate-btn"
            onClick={handleGenerate}
            disabled={!canGenerate}
            title={generateHint}
          >
            <span className="generate-btn-content">
              {busy && <span className="spinner" />}
              {busy ? "Working…" : "⚡ GENERATE EDIT"}
            </span>
          </button>
          {!canGenerate && !busy && generateHint && (
            <div className="generate-hint">{generateHint}</div>
          )}
          {mediaProfile.width > 0 && cuts.length > 0 && (
            <div className="generate-hint">
              Comp {mediaProfile.width}×{mediaProfile.height} @ {mediaProfile.fps.toFixed(2)} fps ·{" "}
              {cuts.length} cuts
            </div>
          )}
        </footer>
      </main>
    </div>
  );
};

export default App;
