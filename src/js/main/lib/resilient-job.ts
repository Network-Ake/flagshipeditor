// Recovery primitives shared by every long-running panel operation.
//
// The Python backend is a separate process: it can be restarted, paused by the
// OS, or simply slow to answer while OpenCV holds the GIL. A dropped request is
// therefore normal, not fatal, and the panel has to distinguish "the connection
// blinked" from "this job is gone" without ever stranding a spinner.

export interface ReconnectNotice {
  attempt: number;
  error: unknown;
}

export type SleepFn = (milliseconds: number) => Promise<void>;

const DEFAULT_POLL_INTERVAL_MS = 600;
const DEFAULT_RECONNECT_BASE_MS = 1000;
const DEFAULT_MAX_RECONNECT_ATTEMPTS = 5;
const DEFAULT_RETRIES = 3;

function defaultSleep(milliseconds: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, milliseconds);
  });
}

// A request that never reached a handler has no status; anything the backend
// answered with is a decision, not a hiccup.
export function isTransientBackendError(error: unknown): boolean {
  const status = (error as { status?: number } | null)?.status;
  if (typeof status === "number") return status === 408 || status === 425 || status === 429 || status >= 500;
  return true;
}

export interface JobStatusLike {
  state: string;
}

export interface PollPersistentJobOptions<T extends JobStatusLike> {
  terminalStates: Set<string>;
  getStatus: () => Promise<T>;
  cancel: () => Promise<T | null | undefined>;
  cancellationRequested: () => boolean;
  onStatus: (status: T) => void;
  isTransient?: (error: unknown) => boolean;
  onReconnect?: (notice: ReconnectNotice) => void;
  sleep?: SleepFn;
  pollIntervalMs?: number;
  reconnectBaseMs?: number;
  maxReconnectAttempts?: number;
}

/**
 * Follow a backend job to a terminal state, surviving dropped connections.
 *
 * Cancellation stays actionable across a reconnect: the request is issued once,
 * the moment a status answer proves the backend is reachable again.
 */
export async function pollPersistentJob<T extends JobStatusLike>(
  options: PollPersistentJobOptions<T>
): Promise<T> {
  const sleep = options.sleep || defaultSleep;
  const isTransient = options.isTransient || isTransientBackendError;
  const pollIntervalMs = options.pollIntervalMs ?? DEFAULT_POLL_INTERVAL_MS;
  const reconnectBaseMs = options.reconnectBaseMs ?? DEFAULT_RECONNECT_BASE_MS;
  const maxReconnectAttempts = options.maxReconnectAttempts ?? DEFAULT_MAX_RECONNECT_ATTEMPTS;

  let reconnectAttempt = 0;
  let cancelIssued = false;

  for (;;) {
    let status: T;
    try {
      status = await options.getStatus();
    } catch (error) {
      if (!isTransient(error)) throw error;
      reconnectAttempt += 1;
      if (reconnectAttempt > maxReconnectAttempts) throw error;
      if (options.onReconnect) options.onReconnect({ attempt: reconnectAttempt, error });
      await sleep(reconnectBaseMs * reconnectAttempt);
      continue;
    }

    reconnectAttempt = 0;
    options.onStatus(status);
    if (options.terminalStates.has(status.state)) return status;

    if (!cancelIssued && options.cancellationRequested()) {
      cancelIssued = true;
      const cancelled = await options.cancel();
      if (cancelled) {
        options.onStatus(cancelled);
        if (options.terminalStates.has(cancelled.state)) return cancelled;
      }
    }

    await sleep(pollIntervalMs);
  }
}

export interface RetryOptions {
  isTransient?: (error: unknown) => boolean;
  onReconnect?: (notice: ReconnectNotice) => void;
  sleep?: SleepFn;
  retries?: number;
  reconnectBaseMs?: number;
}

/** Run a one-shot backend call, retrying only failures that can succeed later. */
export async function retryTransientOperation<T>(
  operation: () => Promise<T>,
  options: RetryOptions = {}
): Promise<T> {
  const sleep = options.sleep || defaultSleep;
  const isTransient = options.isTransient || isTransientBackendError;
  const retries = options.retries ?? DEFAULT_RETRIES;
  const reconnectBaseMs = options.reconnectBaseMs ?? DEFAULT_RECONNECT_BASE_MS;

  let attempt = 0;
  for (;;) {
    try {
      return await operation();
    } catch (error) {
      attempt += 1;
      if (attempt > retries || !isTransient(error)) throw error;
      if (options.onReconnect) options.onReconnect({ attempt, error });
      await sleep(reconnectBaseMs * attempt);
    }
  }
}
