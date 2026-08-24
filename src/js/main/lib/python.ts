// Python backend bridge — communicates with local Python server
// The Python server runs on localhost:18791

const PYTHON_SERVER = "http://127.0.0.1:18791";

export interface BeatAnalysis {
  tempo: number;
  beats: number[];
  downbeats: number[];
  sections: { type: string; start: number; end: number }[];
  energy: number[];
  bass_onsets: number[];
  hihat_onsets: number[];
  key: string;
  mode: string;
  duration: number;
}

export interface ClipInfo {
  path: string;
  name: string;
  duration: number;
  scene_type: string;
  has_face: boolean;
  brightness: number;
  motion_intensity: number;
}

export interface AnalysisJob {
  id: string;
  state: "queued" | "running" | "completed" | "failed" | "cancelled";
  progress: number;
  result?: any;
  error?: string;
}

// --- Beat Analysis ---
export async function runBeatAnalysis(audioPath: string): Promise<BeatAnalysis> {
  const res = await fetch(`${PYTHON_SERVER}/analyze-beat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ audioPath }),
  });
  if (!res.ok) throw new Error(`Beat analysis failed: ${res.statusText}`);
  return res.json();
}

// --- Clip Analysis (simple, single clip) ---
export async function runClipAnalysis(videoPath: string): Promise<ClipInfo> {
  const res = await fetch(`${PYTHON_SERVER}/analyze-clip`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ videoPath }),
  });
  if (!res.ok) throw new Error(`Clip analysis failed: ${res.statusText}`);
  return res.json();
}

// --- Analysis Jobs (async batch analysis) ---
export async function createAnalysisJob(videoPath: string): Promise<AnalysisJob> {
  const res = await fetch(`${PYTHON_SERVER}/analysis-jobs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ videoPath }),
  });
  if (!res.ok) throw new Error(`Failed to create analysis job: ${res.statusText}`);
  return res.json();
}

export async function getAnalysisJob(jobId: string): Promise<AnalysisJob> {
  const res = await fetch(`${PYTHON_SERVER}/analysis-jobs/${encodeURIComponent(jobId)}`, {}, 10000);
  if (!res.ok) throw new Error(`Failed to get analysis job status: ${res.statusText}`);
  return res.json();
}

export async function getAnalysisJobResult(jobId: string): Promise<any> {
  const res = await fetch(`${PYTHON_SERVER}/analysis-jobs/${encodeURIComponent(jobId)}/result`, {}, 60000);
  if (!res.ok) throw new Error(`Failed to get analysis job result: ${res.statusText}`);
  return res.json();
}

export async function cancelAnalysisJob(jobId: string): Promise<void> {
  await fetch(`${PYTHON_SERVER}/analysis-jobs/${encodeURIComponent(jobId)}/cancel`, {
    method: "POST",
  });
}

// --- Shot Selection ---
export async function selectShots(
  clips: ClipInfo[],
  beatTimes: number[],
  sectionType: string,
  styleConfig: Record<string, unknown> = {},
  usedRecently: string[] = []
): Promise<any[]> {
  const res = await fetch(`${PYTHON_SERVER}/select-shots`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ clips, beatTimes, sectionType, styleConfig, usedRecently }),
  });
  if (!res.ok) throw new Error(`Shot selection failed: ${res.statusText}`);
  const data = await res.json();
  return data.selections;
}

// --- Media Scan (recursive folder import) ---
export async function scanMedia(folderPath: string): Promise<{ files: string[]; skipped: number }> {
  const res = await fetch(`${PYTHON_SERVER}/media/scan`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ folderPath }),
  });
  if (!res.ok) throw new Error(`Media scan failed: ${res.statusText}`);
  return res.json();
}

// --- Server Health ---
export async function checkPythonServer(): Promise<boolean> {
  try {
    const res = await fetch(`${PYTHON_SERVER}/health`);
    return res.ok;
  } catch {
    return false;
  }
}

export async function getServerHealth(): Promise<any> {
  const res = await fetch(`${PYTHON_SERVER}/health`);
  if (!res.ok) throw new Error(`Health check failed: ${res.statusText}`);
  return res.json();
}

export async function startPythonServer(): Promise<boolean> {
  try {
    const res = await fetch(`${PYTHON_SERVER}/start`, { method: "POST" });
    return res.ok;
  } catch {
    return false;
  }
}
