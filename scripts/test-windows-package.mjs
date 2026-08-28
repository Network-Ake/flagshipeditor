import assert from "node:assert/strict";
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";

import { createHostContext } from "./lib/ae-mock.mjs";

const root = process.cwd();
const version = JSON.parse(fs.readFileSync(path.join(root, "package.json"), "utf8")).version;
const stage = path.join(root, ".build", "windows", `FlagshipEditor-${version}-Windows`);
const required = [
  "INSTALL-FLAGSHIPEDITOR.cmd",
  "scripts/Start-FlagshipEditor-Backend.cmd",
  "dist/cep/CSXS/manifest.xml",
  "dist/cep/main/index.html",
  "dist/cep/jsx/index.js",
  "engine/server.py",
  "engine/analysis_jobs.py",
  "engine/self_test.py",
  "engine/fixtures/prores-422-standard.mov",
  "engine/fixtures/prores-422-hq.mov",
  "engine/VERSION",
  "runtime/python/python.exe",
  "runtime/python/pythonw.exe",
  "runtime/python/Lib/site-packages/fastapi/__init__.py",
  "runtime/python/Lib/site-packages/librosa/__init__.py",
  "runtime/python/Lib/site-packages/cv2/cv2.pyd",
  "runtime/python/Lib/site-packages/cv2/opencv_videoio_ffmpeg4120_64.dll",
  "runtime/bin/ffmpeg.exe",
  "runtime/bin/ffprobe.exe",
  "payload-checksums.json",
  "luts/cmd_command_dark_cold.cube",
  "luts/jack_rottier_cinematic.cube",
  "luts/lyrical_lemonade_neon.cube",
  "luts/lyrical_lemonade_vibrant.cube",
  "luts/ninetive_clean.cube",
  "luts/worldwide_dark.cube",
  "luts/worldwide_neon_dark.cube",
];
for (const relativePath of required) {
  assert.ok(fs.existsSync(path.join(stage, relativePath)), `Missing packaged file: ${relativePath}`);
}

// The installer decodes these two files with the bundled FFmpeg before it
// commits an install, so the payload has to carry exactly the media that was
// reviewed. Packaging used to synthesise them at build time with whatever
// FFmpeg the build machine had, which made the bytes depend on the builder and
// left a source checkout unable to run engine/self_test.py at all.
{
  const manifestPath = path.join(root, "engine", "fixtures", "manifest.json");
  assert.ok(fs.existsSync(manifestPath), "engine/fixtures/manifest.json is missing from the source tree");
  const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
  assert.ok(manifest.fixtures.length >= 2, "the fixture manifest must cover Standard and HQ");

  const stagedManifest = path.join(stage, "engine", "fixtures", "manifest.json");
  assert.ok(fs.existsSync(stagedManifest), "the fixture manifest must ship with the payload");

  const checksums = JSON.parse(fs.readFileSync(path.join(stage, "payload-checksums.json"), "utf8"));
  const byPath = new Map(checksums.map((entry) => [entry.path, entry.sha256]));

  for (const entry of manifest.fixtures) {
    const relative = `engine/fixtures/${entry.file}`;
    const staged = path.join(stage, "engine", "fixtures", entry.file);
    const source = path.join(root, "engine", "fixtures", entry.file);
    assert.ok(fs.existsSync(staged), `Missing packaged fixture: ${relative}`);

    const stagedHash = crypto.createHash("sha256").update(fs.readFileSync(staged)).digest("hex");
    const sourceHash = crypto.createHash("sha256").update(fs.readFileSync(source)).digest("hex");
    assert.equal(sourceHash, entry.sha256, `${relative}: the source tree drifted from its manifest`);
    assert.equal(stagedHash, entry.sha256, `${relative}: the packaged copy is not the reviewed media`);
    assert.equal(
      fs.statSync(staged).size, entry.bytes,
      `${relative}: packaged size does not match the manifest`,
    );
    // payload-checksums.json is what the installer verifies on the target
    // machine, so the fixtures have to be inside it and agree.
    assert.equal(byPath.get(relative), entry.sha256, `${relative} is not covered by payload-checksums.json`);
  }
}

const installer = fs.readFileSync(path.join(stage, "INSTALL-FLAGSHIPEDITOR.cmd"), "utf8");
for (const forbidden of ["powershell", "winget", "Python.Python.3.12"]) {
  assert.ok(!installer.includes(forbidden), `Installer still depends on ${forbidden}`);
}
assert.ok(!/\bpy\.exe\b/i.test(installer), "Installer still depends on py.exe");
assert.ok(installer.includes("Native Windows installer"), "Installer must identify the CMD-only path.");
assert.ok(installer.includes("FLAGSHIPEDITOR_TEST_ROOT"), "Installer must support isolated Windows self-testing.");
assert.ok(installer.includes(":rollback_cep"), "Installer must preserve rollback on activation failure.");
assert.ok(installer.includes("Testing packaged ProRes 422 Standard and HQ decoding"), "Installer must run the packaged ProRes media gate.");
assert.ok(installer.includes('pushd "%~dp0"'), "Installer must map UNC package paths with PUSHD.");
assert.ok(!installer.includes('cd /d "%~dp0"'), "Installer must not rely on CD /D for UNC package paths.");
assert.ok(installer.includes(":LeavePackageRoot"), "Installer must balance its package-root PUSHD.");
assert.ok(installer.includes(".flagshipeditor.pid"), "Installer must use the backend-owned PID file.");
assert.ok(installer.includes("s.isdigit()"), "Installer must reject unsafe PID-file content before CMD expansion.");
assert.ok(installer.includes("d.get('processId')==int(sys.argv[2])"),
  "Graceful shutdown must bind health identity to the PID file.");
assert.ok(installer.includes('IMAGENAME eq pythonw.exe'), "Installer must verify the fallback process image.");
assert.ok(installer.includes("taskkill /PID %BACKEND_PID% /T /F"), "Installer must terminate a locked unhealthy backend by its guarded PID.");
assert.ok(installer.includes(":WaitForPidExit"), "Installer must wait for runtime locks to be released.");
assert.ok(installer.includes(":RemoveTree"), "Installer must verify bounded runtime-tree deletion.");
const stopBeforeActivation = installer.indexOf("call :StopInstalledBackend");
const backendActivation = installer.indexOf('move "%APP_FINAL%" "%APP_BACKUP%"');
assert.ok(stopBeforeActivation >= 0 && stopBeforeActivation < backendActivation,
  "Installer must stop the existing backend before moving its runtime directory.");
const rollbackApp = installer.slice(installer.lastIndexOf("\n:rollback_app"), installer.lastIndexOf("\n:rollback_cep"));
assert.ok(rollbackApp.indexOf("call :StopInstalledBackend") < rollbackApp.indexOf('call :RemoveTree "%APP_FINAL%"'),
  "Rollback must stop the new backend before removing its runtime directory.");
assert.ok((installer.match(/call :LeavePackageRoot/g) || []).length >= 2,
  "Installer must POPD on both successful and failed exits.");

const launcher = fs.readFileSync(path.join(stage, "scripts", "Start-FlagshipEditor-Backend.cmd"), "utf8");
assert.ok(launcher.includes("FLAGSHIPEDITOR_FFPROBE"), "Launcher must configure bundled FFprobe.");
assert.ok(launcher.includes("FLAGSHIPEDITOR_FFMPEG"), "Launcher must configure bundled FFmpeg.");
assert.ok(launcher.includes("curl.exe"), "Launcher must verify backend identity and capabilities.");
assert.ok(launcher.includes("call :StopStartedBackend"), "Launcher must stop a backend that never becomes healthy.");
assert.ok(launcher.includes(".flagshipeditor.pid"), "Launcher cleanup must use the backend-owned PID file.");
assert.ok(launcher.includes('IMAGENAME eq pythonw.exe'), "Launcher cleanup must guard taskkill by process image.");

const clipAnalysis = fs.readFileSync(path.join(stage, "engine", "clip_analysis.py"), "utf8");
assert.ok(clipAnalysis.includes("parse_frame_rate"), "Safe ffprobe frame-rate parsing is missing.");
assert.ok(!clipAnalysis.includes("eval(stream.get"), "Unsafe ffprobe frame-rate eval regressed.");
assert.ok(clipAnalysis.includes("extract_frames_ffmpeg"), "Explicit bundled FFmpeg frame extraction is missing.");
assert.ok(clipAnalysis.includes("ANALYSIS_MAX_DIMENSION"), "Analysis frame memory cap is missing.");

const jsx = fs.readFileSync(path.join(stage, "dist", "cep", "jsx", "index.js"), "utf8");
for (const bridgeFunction of [
  "getBridgeHealth",
  "beginComp",
  "appendCutBatch",
  "finishComp",
  "abortComp",
  "swapCut",
  "replaceSectionCuts",
]) {
  assert.ok(jsx.includes(`thisObj.${bridgeFunction}`), `Missing AE bridge: ${bridgeFunction}`);
}
// The bundle reads ExtendScript globals ($.os, Folder, app) at load time, so
// it must run inside the same host mock the ae-bridge gate uses; a bare
// context throws before any bridge function is installed.
const jsxContext = createHostContext().context;
vm.createContext(jsxContext);
vm.runInContext(jsx, jsxContext, { filename: "jsx/index.js" });
for (const bridgeFunction of ["getBridgeHealth", "beginComp", "appendCutBatch", "finishComp", "abortComp"]) {
  assert.equal(typeof jsxContext[bridgeFunction], "function", `AE bridge failed to initialize: ${bridgeFunction}`);
}
assert.ok(!jsx.includes("parseInt(parts[0])"), "Fractional beat intervals regressed.");
// ExtendScript (ES3) has String.prototype.indexOf but not Array.prototype
// .indexOf. The registry parse calls it on a String()-wrapped value, which is
// safe; anything beyond that reviewed call must fail until it is reviewed too.
const unreviewedIndexOf = jsx
  .split("\n")
  .filter((line) => line.includes(".indexOf(") && !line.includes('out.indexOf("REG_SZ")'));
assert.equal(
  unreviewedIndexOf.length,
  0,
  `ExtendScript bundle gained unreviewed .indexOf( calls (Array.prototype.indexOf does not exist in ES3): ${unreviewedIndexOf.join(" | ")}`
);
assert.ok(jsx.includes("Style effect is not implemented and was skipped"),
  "Unsupported enabled style effects must not be silently ignored.");
assert.ok(jsx.includes("Math.abs(taggedBeat - beatTime) < 0.05"),
  "Review cut lookup must tolerate harmless beat-time round trips.");

const html = fs.readFileSync(path.join(stage, "dist", "cep", "main", "index.html"), "utf8");
const assetMatch = html.match(/src="\.\.\/assets\/([^"]+\.js)"/);
assert.ok(assetMatch, "Panel JavaScript asset reference is missing.");
const panelAsset = fs.readFileSync(path.join(stage, "dist", "cep", "assets", assetMatch[1]), "utf8");
for (const requiredPanelFeature of [
  "/select-shots",
  "/health",
  "appendCutBatch",
  "Adobe bridge payload is too large",
  "Video files:*.mov;*.mp4;*.m4v;*.avi;*.mxf,All files:*.*",
  "Audio files:*.mp3;*.wav;*.aac;*.m4a;*.flac,All files:*.*",
  "clip(s) failed analysis",
  "/analysis-jobs",
  "/media/scan",
  "Cancel task",
  "Regenerate",
  "No preview",
  "com.akestudio.flagshipeditor.bridge",
  version,
]) {
  assert.ok(panelAsset.includes(requiredPanelFeature), `Panel feature wiring is missing: ${requiredPanelFeature}`);
}
assert.ok(!fs.existsSync(path.join(stage, "INSTALL-FLAGSHIPEDITOR-UI.cmd")),
  "A UI-only installer must not ship without its matching backend runtime.");

const checksums = JSON.parse(fs.readFileSync(path.join(stage, "payload-checksums.json"), "utf8"));
assert.ok(checksums.length > 100, "Checksum manifest is unexpectedly small.");
for (const entry of checksums) {
  const data = fs.readFileSync(path.join(stage, entry.path));
  const actual = crypto.createHash("sha256").update(data).digest("hex");
  assert.equal(actual, entry.sha256, `Checksum mismatch: ${entry.path}`);
}

assert.equal(fs.readFileSync(path.join(stage, "engine", "VERSION"), "utf8").trim(), version);
const manifest = fs.readFileSync(path.join(stage, "dist", "cep", "CSXS", "manifest.xml"), "utf8");
assert.ok(manifest.includes(`ExtensionBundleVersion="${version}"`), "CEP bundle version drifted from package version.");
assert.ok(manifest.includes(`<Extension Id="com.akestudio.flagshipeditor.main" Version="${version}"`), "CEP extension version drifted from package version.");
console.log(`Windows package validation passed (${checksums.length} payload files).`);
