/**
 * build-msi.mjs
 *
 * Builds the one-click Windows MSI from the already-validated Windows package
 * stage (.build/windows/FlagshipEditor-<version>-Windows). The MSI recipe
 * lives in installer/msi and is compiled with msitools' wixl, so this runs
 * entirely on macOS.
 *
 * Output: .build/msi/FlagshipEditor-<version>-Windows.msi
 *         plus a copy in ~/Downloads.
 *
 * The build fails closed: the package stage must pass its own validation gate
 * first, and the finished MSI must pass test-msi-package.mjs (msiextract
 * byte-for-byte comparison and MSI table checks) before anything is copied
 * out.
 */

import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { execFileSync, spawnSync } from "node:child_process";

const root = process.cwd();
const version = JSON.parse(fs.readFileSync(path.join(root, "package.json"), "utf8")).version;
const packageName = `FlagshipEditor-${version}-Windows`;
const stage = path.join(root, ".build", "windows", packageName);
const msiDir = path.join(root, "installer", "msi");
const fragDir = path.join(msiDir, "frag");
const cepSrc = path.join(msiDir, "cep-src");
const msiBuildDir = path.join(root, ".build", "msi");
const msiStage = path.join(msiBuildDir, "stage");
const msiPath = path.join(msiBuildDir, `${packageName}.msi`);
// FLAGSHIPEDITOR_OUT_DIR exists so a test can build into a scratch directory
// instead of the real Downloads folder.
const outDir = process.env.FLAGSHIPEDITOR_OUT_DIR || "/Users/issandre/Downloads";
const downloadsPath = path.join(outDir, `${packageName}.msi`);

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
  for (const entry of fs.readdirSync(directory, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
    const candidate = path.join(directory, entry.name);
    if (entry.isDirectory()) files.push(...walkFiles(candidate));
    else files.push(candidate);
  }
  return files;
}

const copyFilter = (item) =>
  !item.includes(`${path.sep}__pycache__`) &&
  !item.endsWith(`${path.sep}.DS_Store`) &&
  !item.endsWith(".pyc");

// ── 1. The package stage is the single source of truth; gate on it ────────
if (!fs.existsSync(stage)) {
  throw new Error(`Windows package stage is missing: ${stage}. Run "npm run zip" first.`);
}
execFileSync(process.execPath, [path.join(root, "scripts", "test-windows-package.mjs")], {
  cwd: root,
  stdio: "inherit",
});

// ── 2. Sync the tracked CEP payload from the validated stage ──────────────
// cep-src mirrors what the MSI installs into the CEP extensions folder: the
// built panel plus luts and styles, and the panel-side backend bridge CMD
// that is MSI-specific and therefore maintained here, not in dist.
const cepBridge = path.join(cepSrc, "Start-FlagshipEditor-Backend.cmd");
if (!fs.existsSync(cepBridge)) {
  throw new Error(`MSI panel bridge is missing: ${cepBridge}`);
}
for (const stale of ["CSXS", "assets", "jsx", "main", "luts", "styles", ".debug"]) {
  fs.rmSync(path.join(cepSrc, stale), { recursive: true, force: true });
}
for (const [source, destination] of [
  [path.join(stage, "dist", "cep", "CSXS"), path.join(cepSrc, "CSXS")],
  [path.join(stage, "dist", "cep", "assets"), path.join(cepSrc, "assets")],
  [path.join(stage, "dist", "cep", "jsx"), path.join(cepSrc, "jsx")],
  [path.join(stage, "dist", "cep", "main"), path.join(cepSrc, "main")],
  [path.join(stage, "dist", "cep", ".debug"), path.join(cepSrc, ".debug")],
  [path.join(stage, "luts"), path.join(cepSrc, "luts")],
  [path.join(stage, "styles"), path.join(cepSrc, "styles")],
]) {
  if (!fs.existsSync(source)) throw new Error(`MSI CEP payload input is missing: ${source}`);
  fs.cpSync(source, destination, { recursive: true, filter: copyFilter });
}

// ── 3. Assemble the backend payload staging trees ─────────────────────────
fs.rmSync(msiStage, { recursive: true, force: true });
for (const dir of ["root", "engine", "runtime"]) {
  fs.mkdirSync(path.join(msiStage, dir), { recursive: true });
}
for (const vbs of [
  "Start-FlagshipEditor-Backend.vbs",
  "Stop-FlagshipEditor-Backend.vbs",
  "Setup-Complete-FlagshipEditor.vbs",
]) {
  fs.copyFileSync(path.join(msiDir, vbs), path.join(msiStage, "root", vbs));
}
fs.cpSync(path.join(stage, "engine"), path.join(msiStage, "engine"), { recursive: true, filter: copyFilter });
// The installer's ProRes gate decodes these with the bundled FFmpeg before it
// commits an install, so the MSI has to carry exactly the reviewed media.
for (const entry of JSON.parse(
  fs.readFileSync(path.join(root, "engine", "fixtures", "manifest.json"), "utf8"),
).fixtures) {
  const staged = path.join(msiStage, "engine", "fixtures", entry.file);
  if (!fs.existsSync(staged)) {
    throw new Error(`MSI engine payload is missing the media fixture: engine/fixtures/${entry.file}`);
  }
  const hash = sha256(staged);
  if (hash !== entry.sha256) {
    throw new Error(
      `MSI fixture engine/fixtures/${entry.file} does not match the committed manifest ` +
      `(${hash} != ${entry.sha256}). Regenerate with "npm run generate:fixtures".`,
    );
  }
}
// backend_launcher.py redirects every writable path out of Program Files
// before importing the server; it only exists in the MSI layout.
fs.copyFileSync(path.join(msiDir, "backend_launcher.py"), path.join(msiStage, "engine", "backend_launcher.py"));
fs.cpSync(path.join(stage, "runtime"), path.join(msiStage, "runtime"), { recursive: true, filter: copyFilter });

// ── 4. Regenerate the WiX fragments with wixl-heat ────────────────────────
const fragments = [
  { name: "root", prefix: path.join(msiStage, "root"), variable: "var.RootDir", directoryRef: "INSTALLDIR", group: "RootFiles", win64: true },
  { name: "engine", prefix: path.join(msiStage, "engine"), variable: "var.EngineDir", directoryRef: "ENGINEDIR", group: "EngineFiles", win64: true },
  { name: "runtime", prefix: path.join(msiStage, "runtime"), variable: "var.RuntimeDir", directoryRef: "RUNTIMEDIR", group: "RuntimeFiles", win64: true },
  // The CEP extension lives under the 32-bit Common Files tree, so its
  // components deliberately stay 32-bit.
  { name: "cep", prefix: cepSrc, variable: "var.CepDir", directoryRef: "CEPEXTDIR", group: "CepFiles", win64: false },
];
for (const fragment of fragments) {
  const files = walkFiles(fragment.prefix);
  if (files.length === 0) throw new Error(`MSI staging tree is empty: ${fragment.prefix}`);
  const args = [
    "--var", fragment.variable,
    "--directory-ref", fragment.directoryRef,
    "--component-group", fragment.group,
    "--prefix", `${fragment.prefix}/`,
  ];
  if (fragment.win64) args.push("--win64");
  const wxs = execFileSync("wixl-heat", args, {
    input: `${files.join("\n")}\n`,
    maxBuffer: 64 * 1024 * 1024,
  });
  fs.writeFileSync(path.join(fragDir, `${fragment.name}.wxs`), wxs);
  console.log(`Fragment regenerated: frag/${fragment.name}.wxs (${files.length} files)`);
}

// ── 5. Compile the MSI with wixl ──────────────────────────────────────────
// The ui/ directory is intentionally NOT compiled: wixl has no Dialog
// support, so those unported WiX v4 sources would only inject dangling
// dialog references into InstallUISequence. The MSI uses the Windows
// Installer native UI plus the Setup-Complete success script.
fs.rmSync(msiPath, { force: true });
console.log("Compiling MSI with wixl (this takes a few minutes)...");
// wixl errors on unknown elements but silently ignores unknown attributes,
// so any diagnostics it does emit are treated as fatal; attribute-level
// behaviour is additionally pinned by the table assertions in
// test-msi-package.mjs.
const wixlResult = spawnSync("wixl", [
  "--arch", "x64",
  "-D", "Win64=yes",
  "-D", `AssetDir=${path.join(root, "scripts")}`,
  "-D", `RootDir=${path.join(msiStage, "root")}`,
  "-D", `EngineDir=${path.join(msiStage, "engine")}`,
  "-D", `RuntimeDir=${path.join(msiStage, "runtime")}`,
  "-D", `CepDir=cep-src`,
  "-o", msiPath,
  "FlagshipEditor.wxs",
  path.join("frag", "root.wxs"),
  path.join("frag", "engine.wxs"),
  path.join("frag", "runtime.wxs"),
  path.join("frag", "cep.wxs"),
], { cwd: msiDir, encoding: "utf8", maxBuffer: 64 * 1024 * 1024 });
const wixlOutput = `${wixlResult.stdout || ""}${wixlResult.stderr || ""}`;
if (wixlOutput.trim()) console.log(wixlOutput.trim());
if (wixlResult.status !== 0) {
  throw new Error(`wixl failed with exit code ${wixlResult.status}.`);
}
if (/warning|unhandled/i.test(wixlOutput)) {
  throw new Error("wixl reported diagnostics; refusing to ship an MSI wixl only partially understood.");
}

// ── 6. Validate the finished MSI before copying it anywhere ───────────────
execFileSync(process.execPath, [path.join(root, "scripts", "test-msi-package.mjs")], {
  cwd: root,
  stdio: "inherit",
});

fs.rmSync(downloadsPath, { force: true });
fs.copyFileSync(msiPath, downloadsPath);

const size = fs.statSync(msiPath).size;
console.log(`\nMSI created: ${msiPath}`);
console.log(`Download copy created: ${downloadsPath}`);
console.log(`Size: ${(size / 1024 / 1024).toFixed(1)} MB`);
console.log(`SHA-256: ${sha256(msiPath)}`);
