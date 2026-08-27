/**
 * test-msi-package.mjs
 *
 * Deterministic validation gate for the built Windows MSI. Runs entirely on
 * macOS with msitools:
 *
 *   1. Summary information must declare an x64, English package.
 *   2. The MSI tables must carry the complete install contract: AE 2024+
 *      launch gate, CEP PlayerDebugMode registry values, backend registry
 *      keys, Start Menu shortcuts, the stop-backend custom action, the major
 *      upgrade record and an embedded cabinet.
 *   3. msiextract must reproduce the staged payload byte for byte: every
 *      expected file present, no extra files, every SHA-256 equal.
 */

import assert from "node:assert/strict";
import crypto from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { execFileSync } from "node:child_process";

const root = process.cwd();
const version = JSON.parse(fs.readFileSync(path.join(root, "package.json"), "utf8")).version;
const packageName = `FlagshipEditor-${version}-Windows`;
const msiPath = path.join(root, ".build", "msi", `${packageName}.msi`);
const msiStage = path.join(root, ".build", "msi", "stage");
const cepSrc = path.join(root, "installer", "msi", "cep-src");

assert.ok(fs.existsSync(msiPath), `MSI is missing: ${msiPath}. Run scripts/build-msi.mjs first.`);
const msiSize = fs.statSync(msiPath).size;
assert.ok(msiSize > 150 * 1024 * 1024, `MSI is suspiciously small: ${msiSize} bytes.`);
assert.ok(msiSize < 2 * 1024 * 1024 * 1024, `MSI exceeds the 2 GB release-asset limit: ${msiSize} bytes.`);

function sha256(file) {
  const digest = crypto.createHash("sha256");
  const fd = fs.openSync(file, "r");
  const buffer = Buffer.alloc(1024 * 1024);
  try {
    let bytes;
    while ((bytes = fs.readSync(fd, buffer, 0, buffer.length)) > 0) {
      digest.update(buffer.subarray(0, bytes));
    }
  } finally {
    fs.closeSync(fd);
  }
  return digest.digest("hex");
}

function walkFiles(directory) {
  const files = [];
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    const candidate = path.join(directory, entry.name);
    if (entry.isDirectory()) files.push(...walkFiles(candidate));
    else files.push(candidate);
  }
  return files;
}

function exportTable(table) {
  const output = execFileSync("msiinfo", ["export", msiPath, table], {
    maxBuffer: 256 * 1024 * 1024,
    encoding: "utf8",
  });
  // msiinfo prints three header lines (column names, formats, keys) before
  // the data rows, and terminates every line with CRLF.
  return output
    .split("\n")
    .map((line) => line.replace(/\r$/, ""))
    .slice(3)
    .filter((line) => line.length > 0)
    .map((line) => line.split("\t"));
}

// ── 1. Summary information ────────────────────────────────────────────────
const suminfo = execFileSync("msiinfo", ["suminfo", msiPath], { encoding: "utf8" });
assert.ok(suminfo.includes("x64;1033"), "MSI summary must declare an x64;1033 template.");

// ── 2. Install contract in the MSI tables ─────────────────────────────────
const properties = new Map(exportTable("Property").map(([name, value]) => [name, value]));
assert.equal(properties.get("ProductVersion"), version, "ProductVersion drifted from package.json.");
assert.equal(properties.get("Manufacturer"), "ake-studio");
assert.equal(properties.get("ProductName"), `FlagshipEditor ${version}`);
assert.equal(properties.get("ARPPRODUCTICON"), "FlagshipEditor.ico", "Add/Remove Programs icon is missing.");
assert.ok(properties.get("UpgradeCode"), "UpgradeCode is missing; upgrades would stack installs.");

const launchConditions = exportTable("LaunchCondition");
const aeGate = launchConditions.find(([condition]) => condition.includes("AE2024"));
assert.ok(aeGate, "After Effects 2024+ launch condition is missing.");
assert.ok(aeGate[0].startsWith("Installed OR "), "AE gate must not block repair or uninstall.");
assert.ok(aeGate[1].includes("After Effects 2024 or newer"), "AE gate error message must name the requirement.");

const regLocator = exportTable("RegLocator");
const aeSearches = regLocator.filter(([, , key]) => key.startsWith("SOFTWARE\\Adobe\\After Effects\\"));
assert.equal(aeSearches.length, 6, "Expected registry searches for AE 24.0/24.1/25.0/25.1/26.0/26.1.");
for (const [, rootId, , name, type] of aeSearches) {
  assert.equal(rootId, "2", "AE registry searches must target HKLM.");
  assert.equal(name, "InstallPath");
  assert.equal(type, "18", "AE registry searches must be raw 64-bit lookups.");
}
assert.equal(exportTable("AppSearch").length, 6, "Every AE search property must be wired into AppSearch.");

const registry = exportTable("Registry");
for (const generation of [9, 10, 11, 12, 13]) {
  assert.ok(
    registry.some(([, rootId, key, name, value]) =>
      rootId === "1" && key === `Software\\Adobe\\CSXS.${generation}` && name === "PlayerDebugMode" && value === "1"),
    `PlayerDebugMode for CSXS.${generation} is missing (unsigned panel would not load).`
  );
}
// wixl stores keys declared through <RegistryKey> with a trailing backslash;
// msiexec creates the same key either way.
const backendKeys = registry.filter(([, rootId, key]) =>
  rootId === "2" && key.replace(/\\$/, "") === "Software\\ake-studio\\FlagshipEditor");
for (const [name, value] of [
  ["InstallDir", "[INSTALLDIR]"],
  ["Version", version],
  ["CepDir", "[CEPEXTDIR]"],
  ["BackendPort", "#18791"],
]) {
  assert.ok(
    backendKeys.some((row) => row[3] === name && row[4] === value),
    `HKLM backend registry value is missing or wrong: ${name}=${value}`
  );
}

const shortcuts = exportTable("Shortcut");
assert.equal(shortcuts.length, 3, "Expected Start/Stop/Uninstall Start Menu shortcuts.");
assert.ok(shortcuts.some((row) => row.some((cell) => cell.includes("Start-FlagshipEditor-Backend.vbs"))));
assert.ok(shortcuts.some((row) => row.some((cell) => cell.includes("Stop-FlagshipEditor-Backend.vbs"))));
assert.ok(shortcuts.some((row) => row.some((cell) => cell.includes("[ProductCode]"))));

assert.ok(
  exportTable("Upgrade").some(([code]) => code === properties.get("UpgradeCode")),
  "MajorUpgrade record is missing; a new version would not replace the old one."
);

const customActions = exportTable("CustomAction");
assert.ok(customActions.some(([id]) => id === "StopBackend"), "Stop-backend custom action is missing.");
const sequence = exportTable("InstallExecuteSequence");
assert.ok(sequence.some(([action]) => action === "StopBackend"),
  "StopBackend must be sequenced, or upgrades fail on a running backend.");

const uiSequence = exportTable("InstallUISequence");
const executeAction = uiSequence.find(([action]) => action === "ExecuteAction");
const setupComplete = uiSequence.find(([action]) => action === "SetupComplete");
assert.ok(executeAction && setupComplete, "Interactive success confirmation is missing.");
assert.ok(Number(setupComplete[2]) > Number(executeAction[2]),
  "The success confirmation must run only after a successful install.");
assert.equal(setupComplete[1], "NOT Installed",
  "The success confirmation must not fire on repair or uninstall.");
// wixl has no Dialog support, so any dialog reference in the UI sequence
// would be dangling (Windows Installer logs debug error 2726 per entry).
for (const [action] of uiSequence) {
  assert.ok(!action.endsWith("Dlg") && action !== "ExitDialog" && action !== "FatalError" && action !== "UserExit",
    `InstallUISequence references a dialog that does not exist: ${action}`);
}
assert.ok(customActions.some(([id, , , target]) =>
  id === "SetupComplete" && String(target).includes("Setup-Complete-FlagshipEditor.vbs")),
  "SetupComplete must run the packaged confirmation script.");

assert.ok(
  exportTable("Media").some((row) => row.includes("#payload.cab")),
  "Payload cabinet must be embedded in the MSI."
);

// ── 3. Byte-for-byte payload comparison via msiextract ────────────────────
const expectedInstall = new Map();
for (const [sourceRoot, prefix] of [
  [path.join(msiStage, "root"), ""],
  [path.join(msiStage, "engine"), "engine/"],
  [path.join(msiStage, "runtime"), "runtime/"],
]) {
  assert.ok(fs.existsSync(sourceRoot), `MSI staging tree is missing: ${sourceRoot}`);
  for (const file of walkFiles(sourceRoot)) {
    expectedInstall.set(prefix + path.relative(sourceRoot, file).split(path.sep).join("/"), file);
  }
}
const expectedCep = new Map();
for (const file of walkFiles(cepSrc)) {
  expectedCep.set(path.relative(cepSrc, file).split(path.sep).join("/"), file);
}

const fileRows = exportTable("File").length;
assert.equal(
  fileRows,
  expectedInstall.size + expectedCep.size,
  "MSI File table row count must equal the staged payload file count."
);

const extractDir = fs.mkdtempSync(path.join(os.tmpdir(), "flagshipeditor-msi-verify-"));
try {
  console.log(`Extracting MSI payload for verification into ${extractDir} ...`);
  execFileSync("msiextract", ["--directory", extractDir, msiPath], { stdio: ["ignore", "ignore", "inherit"] });

  const extracted = walkFiles(extractDir);
  const installMarker = extracted.find((file) => file.endsWith(`${path.sep}Start-FlagshipEditor-Backend.vbs`));
  assert.ok(installMarker, "Extracted MSI does not contain the backend launcher.");
  const installRoot = path.dirname(installMarker);
  const cepMarker = extracted.find((file) =>
    file.includes("com.akestudio.flagshipeditor") && file.endsWith(`CSXS${path.sep}manifest.xml`));
  assert.ok(cepMarker, "Extracted MSI does not contain the CEP manifest.");
  const cepRoot = path.dirname(path.dirname(cepMarker));
  assert.ok(installRoot.endsWith(`${path.sep}FlagshipEditor`), `Unexpected install root: ${installRoot}`);
  assert.ok(cepRoot.endsWith(`${path.sep}com.akestudio.flagshipeditor`), `Unexpected CEP root: ${cepRoot}`);

  let compared = 0;
  for (const file of extracted) {
    let expectedFile;
    if (file.startsWith(installRoot + path.sep)) {
      expectedFile = expectedInstall.get(path.relative(installRoot, file).split(path.sep).join("/"));
    } else if (file.startsWith(cepRoot + path.sep)) {
      expectedFile = expectedCep.get(path.relative(cepRoot, file).split(path.sep).join("/"));
    }
    assert.ok(expectedFile, `MSI delivers an unexpected file: ${file}`);
    assert.equal(sha256(file), sha256(expectedFile), `MSI payload differs from stage: ${file}`);
    compared += 1;
  }
  assert.equal(
    compared,
    expectedInstall.size + expectedCep.size,
    "Extracted MSI is missing staged payload files."
  );
  console.log(`MSI validation passed (${compared} payload files verified byte-for-byte).`);
} finally {
  fs.rmSync(extractDir, { recursive: true, force: true });
}

console.log(`MSI: ${msiPath}`);
console.log(`Size: ${(msiSize / 1024 / 1024).toFixed(1)} MB`);
console.log(`SHA-256: ${sha256(msiPath)}`);
