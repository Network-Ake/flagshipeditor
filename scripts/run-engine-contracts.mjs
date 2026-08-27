import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const localPython = process.platform === "win32"
  ? path.join(root, "engine", ".venv", "Scripts", "python.exe")
  : path.join(root, "engine", ".venv", "bin", "python");

const candidates = fs.existsSync(localPython)
  ? [{ command: localPython, args: [] }]
  : process.platform === "win32"
    ? [
        { command: "python.exe", args: [] },
        { command: "py.exe", args: ["-3"] },
      ]
    : [
        { command: "python3", args: [] },
        { command: "python", args: [] },
      ];

let lastError = "No Python interpreter was found";
for (const candidate of candidates) {
  const result = spawnSync(
    candidate.command,
    [...candidate.args, path.join(root, "scripts", "test-engine-contracts.py")],
    { cwd: root, stdio: "inherit" },
  );
  if (!result.error) process.exit(result.status ?? 1);
  lastError = result.error.message;
}

console.error(`Unable to run engine contracts: ${lastError}`);
console.error("Create engine/.venv with the packaged runtime dependencies, then rerun the test.");
process.exit(1);
