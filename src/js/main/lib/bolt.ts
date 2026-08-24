// Bolt CEP bridge — evalTS and evalES wrappers
// Type-safe communication between React frontend and ExtendScript backend

declare global {
  interface Window {
    __adobe_cep__: any;
    csInterface: any;
  }
}

// evalTS — type-safe call to ExtendScript functions
export async function evalTS(funcName: string, ...args: any[]): Promise<any> {
  const cs = window.csInterface;
  if (!cs) {
    console.warn("CSInterface not available — running outside AE?");
    return null;
  }
  return new Promise((resolve, reject) => {
    const argStr = args.map((a) => JSON.stringify(a)).join(", ");
    const script = `${funcName}(${argStr})`;
    cs.evalScript(script, (result: string) => {
      try {
        const parsed = JSON.parse(result);
        if (parsed.__error) {
          reject(new Error(parsed.__error));
        } else {
          resolve(parsed.__result !== undefined ? parsed.__result : parsed);
        }
      } catch {
        resolve(result);
      }
    });
  });
}

// evalES — direct ExtendScript eval (no type safety)
export async function evalES(script: string, global = false): Promise<string> {
  const cs = window.csInterface;
  if (!cs) {
    console.warn("CSInterface not available — running outside AE?");
    return "";
  }
  return new Promise((resolve) => {
    cs.evalScript(script, (result: string) => {
      resolve(result);
    });
  });
}

// Get host app info
export function getHostInfo() {
  const cs = window.csInterface;
  if (!cs) return { name: "browser", version: "0" };
  const env = cs.getHostEnvironment();
  return {
    name: env.appName,
    version: env.appVersion,
  };
}

// Open file dialog
export function openFile(filter: string = "*"): Promise<string | null> {
  return new Promise((resolve) => {
    const cs = window.csInterface;
    if (!cs) {
      // Fallback for browser dev
      const input = document.createElement("input");
      input.type = "file";
      input.accept = filter;
      input.onchange = () => {
        const file = input.files?.[0];
        resolve((file as any)?.path || null);
      };
      input.click();
      return;
    }
    cs.evalScript(`openFileDialog("${filter}")`, (result: string) => {
      resolve(result === "null" ? null : result);
    });
  });
}

// Open multiple files dialog
export function openFiles(filter: string = "*"): Promise<string[]> {
  return new Promise((resolve) => {
    const cs = window.csInterface;
    if (!cs) {
      resolve([]);
      return;
    }
    cs.evalScript(`openFilesDialog("${filter}")`, (result: string) => {
      try {
        resolve(JSON.parse(result) || []);
      } catch {
        resolve(result ? [result] : []);
      }
    });
  });
}