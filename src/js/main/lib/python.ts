// Client for the local FlagshipEditor analysis backend (127.0.0.1:18791).
//
// Every shape here mirrors engine/server.py exactly. FastAPI reports failures as
// {"detail": "..."} and those sentences are written for the user, so they are
// unwrapped and rethrown verbatim instead of being replaced by a status code.

export const PYTHON_SERVER = "http://127.0.0.1:18791";

const HEALTH_TIMEOUT_MS = 4000;
const DEFAULT_TIMEOUT_MS = 30000;
const BEAT_TIMEOUT_MS = 300000;
const RESULT_TIMEOUT_MS = 120000;

export interface BeatSection {
  type: string;
  start: number;
  end: number;
  // What the audio measured before position overrode it, and how much the
  // published name is worth. Optional: a result restored from an older cache
  // carries neither.
  measured_type?: string;
  label_source?: "measured" | "measured_energy" | "positional";
  label_confidence?: number;
}

// How one musical label was derived and how sure that is. Every label this
// engine publishes is an inference; this is what separates a measurement from
// a convention.
export interface BeatLabel {
  method: string;
  confidence: number;
  claim: string;
  [key: string]: unknown;
}

// The stretch of the track measured as its peak. Optional so a beat analysis
// restored from an older cache still type-checks.
export interface BeatHook {
  index: number;
  type: string;
  start: number;
  end: number;
  score: number;
  confidence: number;
}

// A span where sub-bass is held rather than re-struck — the part of an 808 that
// percussive isolation deliberately keeps out of the onset list.
export interface BassSustainSpan {
  start: number;
  end: number;
}

export interface BeatAnalysis {
  tempo: number;
  beats: number[];
  downbeats: number[];
  sections: BeatSection[];
  energy: number[];
  bass_onsets: number[];
  hihat_onsets: number[];
  key: string;
  mode: string;
  duration: number;
  bass_sustain?: BassSustainSpan[];
  hook?: BeatHook | null;
  rhythm_source?: "percussive" | "full_mix";
  analysis_schema?: string;
  // Where the phrases turn over, and the time base of the energy curve. Both
  // optional: a result restored from a cache written before they existed has
  // neither, and the selector falls back to what it did then.
  phrase_boundaries?: number[];
  energy_times?: number[];
  energy_sample_rate?: number;
  energy_hop_length?: number;
  energy_frame_length?: number;
  labels?: Record<string, BeatLabel>;
  cache_state?: string;
  // Measured vocal phrasing. Present from analysis schema 5 onward; a result
  // restored from an older cache has neither and the editor falls back to
  // cutting without vocal evidence.
  vocal_segments?: VocalSegment[];
  vocal_diagnostics?: Record<string, unknown>;
}

export interface BeatProgress {
  state: "idle" | "running" | "completed" | "failed";
  step: string;
  progress: number;
  audioPath: string;
  message: string;
  elapsedSeconds: number;
  timeoutSeconds: number;
}

// The panel holds clips in two states: freshly imported (path + name only) and
// analysed (every OpenCV field present). One optional-field type keeps a single
// list instead of two that can drift apart.
export interface ClipInfo {
  path: string;
  name: string;
  duration: number;
  scene_type: string;
  has_face: boolean;
  brightness: number;
  motion_intensity: number;
  motion_variance?: number;
  motion_intensity_per_second?: number | null;
  motion_variance_per_second?: number | null;
  motion_sample_times?: number[];
  motion_sample_policy?: Record<string, unknown>;
  face_size_ratio?: number;
  face_consistency?: number;
  face_detector?: string;
  face_detector_fallback?: string;
  face_detector_model?: string;
  face_detector_confidence?: number;
  face_detector_confidence_kind?: "detector_score" | "unavailable";
  face_frames_examined?: number;
  composition_score?: number;
  energy_score?: number;
  sharpness_score?: number;
  // Seven-level shot scale and camera movement, published alongside the legacy
  // scene_type rather than replacing it. Optional: a clip analysed before these
  // existed is scored without them.
  shot_type?: string;
  shot_type_confidence?: number;
  shot_scale?: number;
  shot_type_basis?: string;
  camera_movement?: string;
  camera_movement_confidence?: number;
  camera_movement_source?: string;
  histogram?: number[];
  thumbnail_id?: string;
  codec?: string;
  profile?: string;
  pixel_format?: string;
  width?: number;
  height?: number;
  fps?: number;
  decoder?: string;
  usable?: boolean;
  analysis_schema?: string;
  analyzed?: boolean;
}

export interface AnalysisJobError {
  path: string;
  code: string;
  message: string;
}

export interface AnalysisJobStatus {
  jobId: string;
  state: "queued" | "running" | "cancelling" | "completed" | "completed_with_errors" | "cancelled" | "failed";
  total: number;
  completed: number;
  succeeded: number;
  failed: number;
  cancelled: number;
  cached: number;
  progress: number;
  currentFiles: string[];
  elapsedSeconds: number;
  etaSeconds: number | null;
  errorCount: number;
  errors: AnalysisJobError[];
}

export interface AnalysisJobResults {
  jobId: string;
  state: AnalysisJobStatus["state"];
  results: ClipInfo[];
  errors: AnalysisJobError[];
}

export const ANALYSIS_TERMINAL_STATES = new Set<string>([
  "completed",
  "completed_with_errors",
  "cancelled",
  "failed",
]);

export interface ClipScores {
  composition: number;
  energy: number;
  variety: number;
  sharpness: number;
  stability: number;
  face_quality: number;
}

export interface CutAlternative {
  clipPath: string;
  clipName: string;
  thumbnailId: string;
  sceneType: string;
  shotType: string;
  cameraMovement: string;
  clipDuration: number;
  sourceStart: number;
  sourceEnd: number;
  score: number;
}

// What put a cut where it is. ``origin`` names the input event behind it,
// ``sourceTime`` is that event as it was measured and ``snapDelta`` how far
// quantisation moved it, so a claim like "this lands on the 808" is traceable.
export interface CutProvenance {
  origin: "boundary" | "onset" | "phrase" | "grid" | "subdivision";
  sourceTime: number | null;
  snapDelta: number | null;
  beatDelta: number | null;
  beatAligned: boolean;
  snapTolerance: number;
  energyTarget?: number;
  energySource?: "measured_curve" | "section_default";
}

/**
 * How a shot joins the one before it. Decided by the engine from the two
 * adjacent shots, the lyric line and the musical mode — never sprinkled at a
 * configured percentage. Most types resolve to a plain hard cut in After
 * Effects and exist to record *why* the cut is hard; only `dissolve` and
 * `phrase_transition` build a real overlap.
 */
export interface CutTransition {
  type: string;
  reason: string;
}

export interface CutDecision {
  beatTime: number;
  endTime: number;
  sourceStart: number;
  sourceEnd: number;
  sectionType: string;
  // Optional so a project saved before provenance existed still type-checks.
  cutProvenance?: CutProvenance;
  clipPath: string;
  clipName: string;
  thumbnailId: string;
  sceneType: string;
  shotType: string;
  cameraMovement: string;
  clipDuration: number;
  score: number;
  scores: ClipScores;
  locked: boolean;
  alternatives: CutAlternative[];
  // Optional so a project saved before transitions existed still type-checks.
  transition?: CutTransition;
}

export interface MediaProfile {
  width: number;
  height: number;
  fps: number;
}

export interface ShotSelection {
  selections: CutDecision[];
  mediaProfile: MediaProfile;
  cutCount: number;
  /** What the engine knew about the words, and how far it trusted itself. */
  lyrics?: LyricSummary;
}

export interface MediaScan {
  rootPath: string;
  paths: string[];
  totalFiles: number;
  totalBytes: number;
  skipped: number;
}

export interface ServerHealth {
  appId: string;
  processId: number;
  status: "ok" | "degraded";
  version: string;
  librosa: boolean;
  opencv: boolean;
  shot_selector: boolean;
  ffprobe: boolean;
  ffmpeg: boolean;
  missingTools: string[];
  importErrors: Record<string, string>;
  analysis_schema: string | null;
  beat: BeatProgress;
}

/** An error carrying the HTTP status, so retry logic can tell 404 from 503. */
export class BackendError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "BackendError";
    this.status = status;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

async function readErrorDetail(response: Response, fallback: string): Promise<string> {
  try {
    const payload: unknown = await response.json();
    if (isRecord(payload)) {
      const detail = payload.detail;
      if (typeof detail === "string" && detail.length > 0) return detail;
      if (Array.isArray(detail) && detail.length > 0) {
        const first = detail[0];
        if (isRecord(first) && typeof first.msg === "string") return `${fallback}: ${first.msg}`;
      }
    }
  } catch {
    // A non-JSON body means the failure happened below FastAPI; keep the fallback.
  }
  return fallback;
}

async function request<T>(
  path: string,
  init: RequestInit = {},
  timeoutMs: number = DEFAULT_TIMEOUT_MS
): Promise<T> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  let response: Response;
  try {
    response = await fetch(`${PYTHON_SERVER}${path}`, { ...init, signal: controller.signal });
  } catch (error) {
    const aborted = error instanceof DOMException && error.name === "AbortError";
    throw new BackendError(
      aborted
        ? `The analysis backend did not answer ${path} within ${Math.round(timeoutMs / 1000)}s.`
        : `The analysis backend is unreachable on ${PYTHON_SERVER}. Start it from the panel header.`,
      0
    );
  } finally {
    window.clearTimeout(timer);
  }
  if (!response.ok) {
    throw new BackendError(
      await readErrorDetail(response, `${path} failed (HTTP ${response.status})`),
      response.status
    );
  }
  return (await response.json()) as T;
}

function postJson<T>(path: string, body: unknown, timeoutMs?: number): Promise<T> {
  return request<T>(
    path,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
    timeoutMs
  );
}

// --- Health -----------------------------------------------------------------

export async function getServerHealth(): Promise<ServerHealth> {
  return request<ServerHealth>("/health", {}, HEALTH_TIMEOUT_MS);
}

export async function checkPythonServer(): Promise<boolean> {
  try {
    const health = await getServerHealth();
    return health.appId === "com.akestudio.flagshipeditor.backend";
  } catch {
    return false;
  }
}

/** Turn a degraded health report into the one sentence the user must act on. */
export function describeHealthGap(health: ServerHealth): string {
  const missing: string[] = [];
  if (!health.librosa) missing.push("librosa (beat analysis)");
  if (!health.opencv) missing.push("OpenCV (clip analysis)");
  if (!health.shot_selector) missing.push("NumPy (shot selection)");
  if (!health.ffprobe) missing.push("ffprobe");
  if (!health.ffmpeg) missing.push("ffmpeg");
  if (missing.length === 0) return "";
  return `The backend is running but incomplete — missing ${missing.join(", ")}. Reinstall the FlagshipEditor runtime.`;
}

// --- Beat analysis ----------------------------------------------------------

export function runBeatAnalysis(audioPath: string): Promise<BeatAnalysis> {
  return postJson<BeatAnalysis>("/analyze-beat", { audioPath }, BEAT_TIMEOUT_MS);
}

export function getBeatProgress(): Promise<BeatProgress> {
  return request<BeatProgress>("/analyze-beat/progress", {}, HEALTH_TIMEOUT_MS);
}

// --- Clip analysis ----------------------------------------------------------

export function runClipAnalysis(videoPath: string): Promise<ClipInfo> {
  return postJson<ClipInfo>("/analyze-clip", { videoPath }, RESULT_TIMEOUT_MS);
}

export function createAnalysisJob(videoPaths: string[]): Promise<AnalysisJobStatus> {
  return postJson<AnalysisJobStatus>("/analysis-jobs", { videoPaths });
}

export function getAnalysisJob(jobId: string): Promise<AnalysisJobStatus> {
  return request<AnalysisJobStatus>(`/analysis-jobs/${encodeURIComponent(jobId)}`, {}, 10000);
}

export function getAnalysisJobResult(jobId: string): Promise<AnalysisJobResults> {
  return request<AnalysisJobResults>(
    `/analysis-jobs/${encodeURIComponent(jobId)}/result`,
    {},
    RESULT_TIMEOUT_MS
  );
}

export function cancelAnalysisJob(jobId: string): Promise<AnalysisJobStatus> {
  return postJson<AnalysisJobStatus>(`/analysis-jobs/${encodeURIComponent(jobId)}/cancel`, {});
}

// --- Shot selection ---------------------------------------------------------

export interface ShotSelectionInput {
  clips: ClipInfo[];
  beats: number[];
  sections: BeatSection[];
  styleConfig: Record<string, unknown>;
  duration: number;
  tempo: number;
  bassOnsets: number[];
  downbeats?: number[];
  seed: number;
  hook?: BeatHook | null;
  // Optional beat signals. Omitting them is exactly the previous behaviour:
  // cuts fall on the grid alone and every cut in a section shares one energy
  // target.
  phraseBoundaries?: number[];
  energy?: number[];
  energyTimes?: number[];
  energyHopLength?: number;
  energySampleRate?: number;
  // Lyric evidence. All optional. Supplying `lyrics` as plain text is enough
  // for the engine to align it against the vocal phrasing measured during beat
  // analysis; supplying an .lrc/.srt/.vtt gives exact timings. Sending nothing
  // still gets vocal-phrasing-aware cutting from `vocalSegments`.
  lyrics?: string;
  lyricsFilename?: string;
  audioPath?: string;
  allowAsr?: boolean;
  vocalSegments?: VocalSegment[];
  beamWidth?: number;
}

export interface VocalSegment {
  start: number;
  end: number;
  confidence: number;
}

export interface LyricSummary {
  tier: "timecoded" | "asr" | "aligned" | "vocal_only";
  overallConfidence: number;
  canInterpret: boolean;
  lineCount: number;
  vocalSegmentCount: number;
  languages: Record<string, number>;
  diagnostics: Record<string, unknown>;
}

export interface LyricAnalysisResult {
  tier: string;
  overallConfidence: number;
  canInterpret: boolean;
  lines: Array<{
    index: number;
    text: string;
    start: number | null;
    end: number | null;
    timingConfidence: number;
    interpretationConfidence: number;
    imagery: string[];
    isAdLib: boolean;
    address: string;
  }>;
  vocalSegments: VocalSegment[];
  hookLines: string[];
  languages: Record<string, number>;
  diagnostics: Record<string, unknown>;
}

export function analyzeLyrics(input: {
  lyrics?: string;
  lyricsFilename?: string;
  audioPath?: string;
  duration?: number;
  allowAsr?: boolean;
  vocalSegments?: VocalSegment[];
}): Promise<LyricAnalysisResult> {
  return postJson<LyricAnalysisResult>("/analyze-lyrics", input, RESULT_TIMEOUT_MS);
}

export function selectShots(input: ShotSelectionInput): Promise<ShotSelection> {
  return postJson<ShotSelection>("/select-shots", input, RESULT_TIMEOUT_MS);
}

export interface ClipScoreResult {
  scores: ClipScores;
  composite: number;
  clipPath: string;
  clipName: string;
  thumbnailId: string;
  sceneType: string;
  shotType: string;
  cameraMovement: string;
}

export function scoreClip(clip: ClipInfo, sectionType: string): Promise<ClipScoreResult> {
  return postJson<ClipScoreResult>("/score-clip", { clip, sectionType });
}

// --- Media scan -------------------------------------------------------------

export function scanMedia(rootPath: string, recursive = true): Promise<MediaScan> {
  return postJson<MediaScan>("/media/scan", { rootPath, recursive }, RESULT_TIMEOUT_MS);
}

// --- Thumbnails -------------------------------------------------------------

/** Absolute URL of a cached thumbnail, or "" when the clip has none yet. */
export function thumbnailUrl(thumbnailId: string | undefined): string {
  if (!thumbnailId) return "";
  return `${PYTHON_SERVER}/thumbnails/${encodeURIComponent(thumbnailId)}`;
}
