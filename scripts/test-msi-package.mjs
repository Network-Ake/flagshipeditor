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

// The ProRes fixtures the installer decodes must be the committed media, not
// something the build machine synthesised on the day. The manifest itself is a
// source-tree build artifact and is not required inside the payload.
for (const entry of JSON.parse(
  fs.readFileSync(path.join(root, "engine", "fixtures", "manifest.json"), "utf8"),
).fixtures) {
  const staged = path.join(msiStage, "engine", "fixtures", entry.file);
  assert.ok(fs.existsSync(staged), `MSI payload is missing engine/fixtures/${entry.file}`);
  assert.equal(
    crypto.createHash("sha256").update(fs.readFileSync(staged)).digest("hex"),
    entry.sha256,
    `engine/fixtures/${entry.file} in the MSI payload is not the reviewed media`,
  );
  assert.equal(
    fs.statSync(staged).size, entry.bytes,
    `engine/fixtures/${entry.file} in the MSI payload has the wrong size`,
  );
}
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
  let output;
  try {
    output = execFileSync("msiinfo", ["export", msiPath, table], {
      maxBuffer: 256 * 1024 * 1024,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"],
    });
  } catch (error) {
    // A table wixl had no reason to create is equivalent to an empty one.
    if (String(error.stderr).includes("table not found")) return [];
    throw error;
  }
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
assert.equal(properties.get("ALLUSERS"), "1",
  "ALLUSERS must be 1: without it the per-machine package silently degrades to a broken per-user install.");

// A launch condition is the only authored mechanism that can refuse an
// install outright, so every row must be on this allow-list. The first
// published 3.0.0 MSI hard-blocked real machines because an After Effects
// registry search listed exact minor-version keys; environment detection
// belongs in Setup-Complete-FlagshipEditor.vbs, never here.
const launchConditions = exportTable("LaunchCondition");
assert.deepEqual(
  launchConditions.map(([condition]) => condition).sort(),
  ["NOT WIX_DOWNGRADE_DETECTED"],
  "Unexpected launch condition: only the downgrade guard may block an install."
);
assert.equal(exportTable("AppSearch").length, 0,
  "AppSearch must stay empty: install-time registry detection caused the field failure.");
assert.equal(exportTable("RegLocator").length, 0,
  "RegLocator must stay empty: install-time registry detection caused the field failure.");

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

// Upgrade coverage: older versions, the same version (a rebuilt MSI must
// replace, not stack) and a downgrade guard. Windows Installer only honours
// these across the elevation boundary when the action properties are secure.
const upgradeRows = exportTable("Upgrade");
const upgradeCode = properties.get("UpgradeCode");
assert.ok(
  upgradeRows.some(([code, min, max]) => code === upgradeCode && min === "" && max === version),
  "Earlier-version upgrade record is missing; an old install would not be replaced."
);
const sameVersionRow = upgradeRows.find(([code, min, max]) => code === upgradeCode && min === version && max === version);
assert.ok(sameVersionRow, "Same-version upgrade record is missing; reinstalling 3.0.0 would stack two products.");
assert.equal(Number(sameVersionRow[4]) & 0x300, 0x300,
  "Same-version upgrade bounds must both be inclusive.");
assert.ok(
  upgradeRows.some(([code, min, , , attributes]) =>
    code === upgradeCode && min === version && attributes === "2"),
  "Downgrade detection record is missing."
);
const secured = (properties.get("SecureCustomProperties") || "").split(";");
for (const property of ["WIX_UPGRADE_DETECTED", "WIX_SAME_VERSION_UPGRADE_DETECTED", "WIX_DOWNGRADE_DETECTED"]) {
  assert.ok(secured.includes(property), `${property} must be a secure custom property.`);
}

const customActions = exportTable("CustomAction");
assert.ok(customActions.some(([id]) => id === "StopBackend"), "Stop-backend custom action is missing.");
const sequence = exportTable("InstallExecuteSequence");
for (const id of ["SetStopBackendExe", "StopBackend"]) {
  const row = sequence.find(([action]) => action === id);
  assert.ok(row, `${id} must be sequenced, or upgrades fail on a running backend.`);
  assert.ok(row[1].includes("WIX_SAME_VERSION_UPGRADE_DETECTED"),
    `${id} must also fire on same-version upgrades, or the running backend locks the runtime.`);
}
const stopSeq = Number(sequence.find(([action]) => action === "StopBackend")[2]);
const repSeq = Number(sequence.find(([action]) => action === "RemoveExistingProducts")[2]);
assert.ok(stopSeq < repSeq, "StopBackend must run before RemoveExistingProducts.");
// REP sits in its "afterInstallValidate" slot: the old product is removed
// entirely, then the new one is laid down fresh. Any move needs a deliberate
// review of upgrade/rollback semantics.
const validateSeq = Number(sequence.find(([action]) => action === "InstallValidate")[2]);
const initializeSeq = Number(sequence.find(([action]) => action === "InstallInitialize")[2]);
assert.ok(repSeq > validateSeq && repSeq < initializeSeq,
  "RemoveExistingProducts left its reviewed scheduling window.");

// Custom action types are pinned: 51 sets a property, 114 = 50 (run EXE from
// a property) + 64 (continue on failure). Nothing this installer runs may be
// able to fail the install, and nothing may run deferred/elevated.
const expectedTypes = new Map([
  ["SetStopBackendExe", "51"],
  ["StopBackend", "114"],
  ["SetSetupCompleteExe", "51"],
  ["SetupComplete", "114"],
]);
assert.equal(customActions.length, expectedTypes.size, "Unexpected custom action count.");
for (const [id, type] of customActions) {
  assert.equal(type, expectedTypes.get(id), `Custom action ${id} has unexpected type ${type}.`);
}

// Every sequenced action must be a Windows Installer standard action or a
// defined custom action; anything else is a dangling reference msiexec
// resolves only at run time (debug error 2726 at best, a broken install at
// worst).
const standardActions = new Set([
  "FindRelatedProducts", "AppSearch", "LaunchConditions", "ValidateProductID",
  "CostInitialize", "FileCost", "CostFinalize", "MigrateFeatureStates",
  "ExecuteAction", "InstallValidate", "InstallInitialize", "RemoveExistingProducts",
  "ProcessComponents", "UnpublishFeatures", "RemoveRegistryValues", "RemoveShortcuts",
  "RemoveFiles", "RemoveFolders", "CreateFolders", "InstallFiles", "DuplicateFiles",
  "CreateShortcuts", "WriteRegistryValues", "RegisterUser", "RegisterProduct",
  "PublishFeatures", "PublishProduct", "InstallFinalize", "InstallAdminPackage",
]);
const definedCustomActions = new Set(customActions.map(([id]) => id));
for (const table of ["InstallExecuteSequence", "InstallUISequence", "AdminExecuteSequence", "AdminUISequence", "AdvtExecuteSequence"]) {
  for (const [action] of exportTable(table)) {
    assert.ok(standardActions.has(action) || definedCustomActions.has(action),
      `${table} references an action that does not exist: ${action}`);
  }
}

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

// The Setup-Complete script carries the environment validation the MSI
// deliberately no longer performs. Read it from the staging tree the MSI is
// byte-compared against, so these checks hold for the exact shipped bytes.
const setupCompleteScript = fs.readFileSync(
  path.join(msiStage, "root", "Setup-Complete-FlagshipEditor.vbs"), "utf8");
assert.ok(setupCompleteScript.includes("EnumKey"),
  "AE detection must enumerate every installed version, never probe fixed keys.");
assert.ok(setupCompleteScript.includes("SOFTWARE\\Adobe\\After Effects"),
  "AE detection must read Adobe's version registry.");
assert.ok(/After Effects "\s*&\s*year/.test(setupCompleteScript),
  "AE detection must keep the default-folder fallback.");
assert.ok(!/After Effects\\2[0-9]\./.test(setupCompleteScript),
  "Fixed AE version keys are forbidden; they caused the field failure.");
assert.ok(setupCompleteScript.includes("For generation = 9 To 13"),
  "PlayerDebugMode must cover CSXS generations 9-13 for the invoking user.");
for (const requiredBehaviour of [
  "PlayerDebugMode",
  "RemoveLegacyZipInstall",
  "\\engine\\server.py",
  "\\runtime\\python\\pythonw.exe",
  "BackendIsHealthy",
  "WScript.Quit 0",
]) {
  assert.ok(setupCompleteScript.includes(requiredBehaviour),
    `Setup-Complete script is missing required behaviour: ${requiredBehaviour}`);
}

// ── 3. Install simulation from the MSI tables themselves ──────────────────
// msiextract dumps every file regardless of feature wiring or directory
// resolution, so it can validate payload bytes while msiexec would still
// install nothing, or install to the wrong place. Re-derive what msiexec
// will actually do purely from the tables.
const featureRows = exportTable("Feature");
assert.equal(featureRows.length, 1, "Exactly one feature is expected.");
assert.equal(featureRows[0][5], "1", "The feature must install at the default INSTALLLEVEL.");
const componentRows = exportTable("Component");
const wiredComponents = new Set(exportTable("FeatureComponents").map(([, component]) => component));
for (const [componentId] of componentRows) {
  assert.ok(wiredComponents.has(componentId),
    `Component is not wired to any feature and would silently never install: ${componentId}`);
}

const longName = (value) => {
  const target = value.split(":")[0];
  const parts = target.split("|");
  return parts[parts.length - 1];
};
const directoryRows = exportTable("Directory");
const directoryById = new Map(directoryRows.map(([id, parent, defaultDir]) => [id, { parent, name: longName(defaultDir) }]));
const componentDirectory = new Map(componentRows.map((row) => [row[0], row[2]]));

// Resolve a directory to its anchor (INSTALLDIR or CEPEXTDIR) plus the
// relative segments below it. "." contributes no segment; every payload file
// must live under one of the two anchors.
function resolveDirectory(id) {
  const segments = [];
  let current = id;
  while (current) {
    if (current === "INSTALLDIR" || current === "CEPEXTDIR") {
      return { anchor: current, relative: segments.join("/") };
    }
    const row = directoryById.get(current);
    assert.ok(row, `Directory table chain is broken at: ${current}`);
    if (row.name !== "." && row.name !== "SourceDir") segments.unshift(row.name);
    current = row.parent;
  }
  return { anchor: null, relative: segments.join("/") };
}

const fileRows = exportTable("File");
const resolvedByAnchor = { INSTALLDIR: new Set(), CEPEXTDIR: new Set() };
let maxSequence = 0;
const sequenceByName = new Map();
for (const [, component, fileName, , , , , sequence] of fileRows) {
  const directoryId = componentDirectory.get(component);
  assert.ok(directoryId, `File belongs to an unknown component: ${component}`);
  const { anchor, relative } = resolveDirectory(directoryId);
  assert.ok(anchor, `File resolves outside INSTALLDIR and CEPEXTDIR: ${fileName} (directory ${directoryId})`);
  const name = longName(fileName);
  resolvedByAnchor[anchor].add(relative ? `${relative}/${name}` : name);
  sequenceByName.set(name, Number(sequence));
  if (Number(sequence) > maxSequence) maxSequence = Number(sequence);
}
const mediaRows = exportTable("Media");
assert.equal(Number(mediaRows[0][1]), maxSequence,
  "Media.LastSequence must cover every file or the tail of the payload is never copied.");
assert.equal(fileRows.length, maxSequence, "File sequences must be dense.");

// ── 4. Copy-order race contract ───────────────────────────────────────────
// The VBS scripts are the first files copied while pythonw.exe is nearly the
// last, so anything that runs them around install time can observe a
// half-copied tree - that is exactly the second field failure. The scripts
// must therefore synchronise on the committed payload themselves.
assert.ok(sequenceByName.get("pythonw.exe") > sequenceByName.get("Start-FlagshipEditor-Backend.vbs"),
  "Copy-order precondition changed; revisit the payload-wait contract.");
const setupCompleteSource = fs.readFileSync(
  path.join(msiStage, "root", "Setup-Complete-FlagshipEditor.vbs"), "utf8");
for (const waitBehaviour of [
  "WaitForCommittedPayload",
  "PayloadReady",
  "HKLM\\SOFTWARE\\ake-studio\\FlagshipEditor\\Version",
  "\\runtime\\python\\pythonw.exe",
  "\\engine\\backend_launcher.py",
  "sizeBefore = sizeAfter",
  "waitedSeconds <= 300",
]) {
  assert.ok(setupCompleteSource.includes(waitBehaviour),
    `Setup-Complete no longer waits for the committed payload: missing ${waitBehaviour}`);
}
assert.ok(setupCompleteSource.indexOf("WaitForCommittedPayload()") < setupCompleteSource.indexOf("RemoveLegacyZipInstall()"),
  "Setup-Complete must wait for the payload before doing anything else.");
const startVbsSource = fs.readFileSync(
  path.join(msiStage, "root", "Start-FlagshipEditor-Backend.vbs"), "utf8");
assert.ok(startVbsSource.includes("RuntimePresent()") && startVbsSource.includes("waited < 15"),
  "The backend launcher must retry before declaring the runtime incomplete.");
assert.ok(startVbsSource.includes("wait for it to finish"),
  "The backend launcher's failure message must mention an in-flight installation.");

// ── 5. Byte-for-byte payload comparison via msiextract ────────────────────
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

assert.equal(
  fileRows.length,
  expectedInstall.size + expectedCep.size,
  "MSI File table row count must equal the staged payload file count."
);

// The table-resolved install targets must reproduce the staged trees exactly:
// this is what msiexec will lay down, feature-wired and directory-resolved,
// with no msiextract in the loop.
assert.deepEqual(
  [...resolvedByAnchor.INSTALLDIR].sort(),
  [...expectedInstall.keys()].sort(),
  "Directory-table resolution under INSTALLDIR drifted from the staged backend payload."
);
assert.deepEqual(
  [...resolvedByAnchor.CEPEXTDIR].sort(),
  [...expectedCep.keys()].sort(),
  "Directory-table resolution under CEPEXTDIR drifted from the staged panel payload."
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
