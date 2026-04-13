/**
 * Domain types — TTS Harness v2
 *
 * Frontend types = camelCase projection of backend Pydantic schemas.
 * Source of truth: server/core/domain.py
 *
 * Rules:
 * - All camelCase
 * - No frontend-only data shapes — mirror backend exactly
 * - This file MUST NOT import any adapter implementation
 */

// ===== IDs =====
export type EpisodeId = string;
export type ChunkId = string;
export type TakeId = string;

// ===== Enums =====
export type EpisodeStatus = "empty" | "ready" | "running" | "failed" | "done";
export type ChunkStatus = "pending" | "synth_done" | "verified" | "needs_review" | "failed";
export type StageName = "p1" | "p1c" | "p2" | "p2c" | "p2v" | "p5" | "p6" | "p6v";
export type StageStatus = "pending" | "running" | "ok" | "failed";

// ===== Stage Run (backend: StageRunView) =====
export interface StageRun {
  stage: StageName;
  status: StageStatus;
  attempt: number;
  startedAt?: string;
  finishedAt?: string;
  durationMs?: number;
  error?: string;
  logUri?: string;
  stale: boolean;
}

// ===== Take (backend: TakeView) =====
export interface Take {
  id: TakeId;
  audioUri: string;
  durationS: number;
  params: Record<string, unknown>;
  createdAt: string;
}

// ===== Chunk (backend: ChunkDetail = ChunkView + takes + stage_runs) =====
export interface Chunk {
  id: ChunkId;
  episodeId: string;
  shotId: string;
  idx: number;
  text: string;
  textNormalized: string;
  subtitleText: string | null;
  status: ChunkStatus;
  selectedTakeId: TakeId | null;
  boundaryHash?: string;
  charCount: number;
  lastEditedAt?: string;
  metadata: Record<string, unknown>;
  takes: Take[];
  stageRuns: StageRun[];
  attemptHistory?: AttemptRecord[];
  verifyScores?: VerifyScores;
  verifyDiagnosis?: {
    verdict?: string;
    type?: string;       // "speed_anomaly" | "silence_anomaly" | null
    detail?: string;     // 人可读描述
  };
}

// ===== Episode (backend: EpisodeDetail) =====
export interface Episode {
  id: EpisodeId;
  title: string;
  description: string | null;
  status: EpisodeStatus;
  locked: boolean;
  scriptUri: string;
  config: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
  metadata: Record<string, unknown>;
  chunks: Chunk[];
}

// ===== EpisodeSummary (list view, backend: EpisodeSummary) =====
export interface EpisodeSummary {
  id: EpisodeId;
  title: string;
  status: EpisodeStatus;
  locked: boolean;
  chunkCount: number;
  doneCount: number;
  failedCount: number;
  updatedAt: string;
}

// ===== Script (pre-P1 source data for ScriptPreview) =====
export interface ScriptSegment {
  id: string | number;
  type?: string;
  topic?: string;
  text: string;
}

// ===== Edits =====
export interface ChunkEdit {
  textNormalized?: string;
  subtitleText?: string;
}
export type EditBatch = Record<ChunkId, ChunkEdit>;

// ===== SSE Event =====
export interface StageEvent {
  episodeId: string;
  chunkId?: string;
  kind: string;
  payload: Record<string, unknown>;
}

// ===== P2v Verify Scores =====
export interface VerifyScores {
  durationRatio: number;
  silence: number;
  phoneticDistance: number;
  charRatio: number;
  asrConfidence: number;
  weightedScore: number;
}

// ===== Attempt Record =====
export interface AttemptRecord {
  attempt: number;
  level: number;
  verdict: "pass" | "fail";
  scores: VerifyScores;
  diagnosis?: {
    type?: string;       // "speed_anomaly" | "silence_anomaly" | null
    detail?: string;     // 人可读描述
  };
  params: Record<string, unknown>;
  textUsed: string;
  transcribedText: string;
  durationMs: number;
  timestamp: string;
}

// ===== Helpers =====
export function getStageRun(
  stageRuns: StageRun[],
  stage: StageName,
): StageRun | undefined {
  return stageRuns.find((sr) => sr.stage === stage);
}

export function hasLog(stageRun: StageRun | undefined): boolean {
  return stageRun?.logUri != null;
}

export const STAGE_ORDER: readonly StageName[] = [
  "p1",
  "p1c",
  "p2",
  "p2c",
  "p2v",
  "p5",
  "p6",
  "p6v",
];

/** Chunk-level stages only (shown in per-chunk pipeline pill row) */
export const CHUNK_STAGE_ORDER: readonly StageName[] = [
  "p2",
  "p2c",
  "p2v",
  "p5",
];
