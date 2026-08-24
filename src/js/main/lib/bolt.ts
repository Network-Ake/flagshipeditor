// CEP ↔ ExtendScript bridge.
//
// The panel runs without Node (enabling it crashed CEPHtmlEngine on Windows),
// so `window.__adobe_cep__` is the only channel to After Effects. Every call is
// wrapped so a host-side failure arrives as a rejected promise with the exact
// sentence the ExtendScript bridge produced, never as a silent `null`.

export const BRIDGE_ID = "com.akestudio.flagshipeditor.bridge";
export const BRIDGE_VERSION = "2.0.0";

// CEPHtmlEngine drops evalScript payloads beyond roughly 24 KB.
const MAX_PAYLOAD = 24000;
const DEFAULT_TIMEOUT_MS = 60000;

interface CepApi {
  evalScript(script: string, callback: (result: string) => void): void;
  getHostEnvironment(): string;
  getSystemPath(pathType: string): string;
}

interface HostEnvironment {
  appName: string;
  appVersion: string;
  appLocale?: string;
}

declare global {
  interface Window {
    __adobe_cep__?: CepApi;
    csInterface?: { evalScript(script: string, callback: (result: string) => void): void };
  }
}

/** Thrown when the panel is running outside After Effects (browser preview). */
export class HostUnavailableError extends Error {
  constructor() {
    super("After Effects is not connected to this panel. Open it from Window > Extensions.");
    this.name = "HostUnavailableError";
  }
}

function cep(): CepApi | null {
  return typeof window !== "undefined" && window.__adobe_cep__ ? window.__adobe_cep__ : null;
}

export function isHostAvailable(): boolean {
  return cep() !== null;
}

// JSON is valid ExtendScript literal syntax apart from U+2028/U+2029, which ES3
// treats as line terminators and which real filenames can contain.
function encodeArgument(value: unknown): string {
  return JSON.stringify(value === undefined ? null : value)
    .replace(/\u2028/g, "\\u2028")
    .replace(/\u2029/g, "\\u2029");
}

function parseBridgeResponse<T>(raw: string, funcName: string): T {
  if (raw === "EvalScript error." || raw === "") {
    throw new Error(`After Effects could not run ${funcName}. Check the ExtendScript console.`);
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    throw new Error(`After Effects returned an unreadable answer for ${funcName}: ${raw}`);
  }
  if (typeof parsed === "object" && parsed !== null) {
    const payload = parsed as { __error?: unknown; __result?: unknown };
    if (typeof payload.__error === "string") throw new Error(payload.__error);
    if ("__result" in payload) return payload.__result as T;
  }
  return parsed as T;
}

/** Call a published ExtendScript bridge function and resolve its `__result`. */
export function evalTSTimed<T>(funcName: string, timeoutMs: number, ...args: unknown[]): Promise<T> {
  const host = cep();
  if (!host) return Promise.reject(new HostUnavailableError());

  const script = `${funcName}(${args.map(encodeArgument).join(", ")})`;
  if (script.length > MAX_PAYLOAD) {
    return Promise.reject(
      new Error(
        `Adobe bridge payload is too large (${script.length} characters). Generate in smaller batches.`
      )
    );
  }

  return new Promise<T>((resolve, reject) => {
    let settled = false;
    const timer = window.setTimeout(() => {
      settled = true;
      reject(new Error(`After Effects did not answer ${funcName} within ${Math.round(timeoutMs / 1000)}s.`));
    }, timeoutMs);
    try {
      host.evalScript(script, (raw: string) => {
        if (settled) return;
        window.clearTimeout(timer);
        settled = true;
        try {
          resolve(parseBridgeResponse<T>(raw, funcName));
        } catch (error) {
          reject(error);
        }
      });
    } catch (error) {
      window.clearTimeout(timer);
      settled = true;
      reject(new Error(`The After Effects bridge rejected ${funcName}: ${String(error)}`));
    }
  });
}

export function evalTS<T>(funcName: string, ...args: unknown[]): Promise<T> {
  return evalTSTimed<T>(funcName, DEFAULT_TIMEOUT_MS, ...args);
}

export interface BridgeHealth {
  appId: string;
  version: string;
  hostName: string;
  hostVersion: string;
}

export function getBridgeHealth(): Promise<BridgeHealth> {
  return evalTSTimed<BridgeHealth>("getBridgeHealth", 10000);
}

export function getHostInfo(): { name: string; version: string } {
  const host = cep();
  if (!host) return { name: "browser", version: "0" };
  try {
    const env = JSON.parse(host.getHostEnvironment()) as HostEnvironment;
    return { name: env.appName, version: env.appVersion };
  } catch {
    return { name: "unknown", version: "0" };
  }
}

/**
 * On-disk root of the installed extension — where the bundled LUTs live.
 * CEP answers instantly; the ExtendScript bridge is the fallback when the
 * host does not expose the extension path.
 */
export async function getExtensionPath(): Promise<string> {
  const host = cep();
  if (host) {
    try {
      const path = host.getSystemPath("extension");
      if (path) return path;
    } catch {
      // Fall through to the ExtendScript bridge.
    }
  }
  const result = await evalTSTimed<{ root: string }>("getExtensionRoot", 10000);
  return result.root;
}

export function openFile(filter: string): Promise<string | null> {
  return evalTSTimed<string>("openFileDialog", 600000, filter).then((path) =>
    !path || path === "null" ? null : path
  );
}

export function openFiles(filter: string): Promise<string[]> {
  return evalTSTimed<string[] | string>("openFilesDialog", 600000, filter).then((paths) => {
    if (Array.isArray(paths)) return paths;
    if (typeof paths === "string" && paths && paths !== "null") {
      try {
        const parsed: unknown = JSON.parse(paths);
        return Array.isArray(parsed) ? (parsed as string[]) : [paths];
      } catch {
        return [paths];
      }
    }
    return [];
  });
}

export function openFolder(): Promise<string | null> {
  return evalTSTimed<string>("openFolderDialog", 600000).then((path) =>
    !path || path === "null" ? null : path
  );
}

/** Ask After Effects to launch the bundled Python backend (detached). */
export function startBackendProcess(): Promise<{ launched: boolean; launcher: string }> {
  return evalTSTimed<{ launched: boolean; launcher: string }>("startBackend", 30000);
}
