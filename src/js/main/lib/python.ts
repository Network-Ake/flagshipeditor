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

export async function runBeatAnalysis(audioPath: string): Promise<BeatAnalysis> {
  const res = await fetch(`${PYTHON_SERVER}/analyze-beat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ audioPath }),
  });
  if (!res.ok) throw new Error(`Beat analysis failed: ${res.statusText}`);
  return res.json();
}

export async function runClipAnalysis(videoPath: string): Promise<ClipInfo> {
  const res = await fetch(`${PYTHON_SERVER}/analyze-clip`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ videoPath }),
  });
  if (!res.ok) throw new Error(`Clip analysis failed: ${res.statusText}`);
  return res.json();
}

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

export async function checkPythonServer(): Promise<boolean> {
  try {
    const res = await fetch(`${PYTHON_SERVER}/health`);
    return res.ok;
  } catch {
    return false;
  }
}

export async function startPythonServer(): Promise<boolean> {
  try {
    const res = await fetch(`${PYTHON_SERVER}/start`, { method: "POST" });
    return res.ok;
  } catch {
    return false;
  }
}