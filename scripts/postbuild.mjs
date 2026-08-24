import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";

const root = process.cwd();
const packageVersion = JSON.parse(fs.readFileSync(path.join(root, "package.json"), "utf8")).version;
const dist = path.join(root, "dist", "cep");
const manifestPath = path.join(dist, "CSXS", "manifest.xml");
const requiredFiles = [
  manifestPath,
  path.join(dist, "main", "index.html"),
  path.join(dist, "jsx", "index.js"),
];

for (const file of requiredFiles) {
  if (!fs.existsSync(file)) {
    throw new Error(`Required CEP build artifact is missing: ${file}`);
  }
}

let manifest = fs.readFileSync(manifestPath, "utf8");
manifest = manifest.replace(/\s*<Icons>[\s\S]*?<\/Icons>/g, (block) =>
  block.includes("undefined") ? "" : block,
);
fs.writeFileSync(manifestPath, manifest, "utf8");

const html = fs.readFileSync(path.join(dist, "main", "index.html"), "utf8");
const jsx = fs.readFileSync(path.join(dist, "jsx", "index.js"), "utf8");

for (const forbidden of ["--enable-nodejs", "--mixed-context"]) {
  if (manifest.includes(forbidden)) {
    throw new Error(`Unsafe CEP flag found in manifest: ${forbidden}`);
  }
}
if (!manifest.includes("<ScriptPath>./jsx/index.js</ScriptPath>")) {
  throw new Error("CEP manifest does not load the ExtendScript bridge.");
}
for (const expected of [
  `ExtensionBundleVersion="${packageVersion}"`,
  `<Extension Id="com.akestudio.flagshipeditor.main" Version="${packageVersion}"`,
]) {
  if (!manifest.includes(expected)) throw new Error(`CEP version drift: ${expected}`);
}
const assetMatch = html.match(/\.\.\/assets\/(main-[^"']+\.js)/);
if (!assetMatch) {
  throw new Error("Main panel HTML does not reference its UI bundle.");
}
const guiBundlePath = path.join(dist, "assets", assetMatch[1]);
if (!fs.existsSync(guiBundlePath)) throw new Error(`Referenced UI bundle is missing: ${guiBundlePath}`);
const guiBundle = fs.readFileSync(guiBundlePath, "utf8");
for (const forbidden of ["window.require =", "getSynchXHR", "--enable-nodejs", "--mixed-context"]) {
  if (html.includes(forbidden) || guiBundle.includes(forbidden)) {
    throw new Error(`Unsafe or unnecessary CEP runtime surface remains: ${forbidden}`);
  }
}
for (const required of ["boot-status", "__flagshipShowFatal", "panel-message--error"]) {
  if (!html.includes(required)) throw new Error(`Visible startup fallback is missing: ${required}`);
}
execFileSync(process.execPath, ["--check", guiBundlePath], { stdio: "pipe" });
execFileSync(process.execPath, ["--check", path.join(dist, "jsx", "index.js")], { stdio: "pipe" });
if (/(?:^|\n)\s*(?:import|export)\s/.test(jsx)) {
  throw new Error("ExtendScript bundle still contains module syntax.");
}
for (const symbol of [
  "getBridgeHealth",
  "beginComp",
  "appendCutBatch",
  "finishComp",
  "abortComp",
  "openFileDialog",
  "openFilesDialog",
  "openFolderDialog",
]) {
  if (!jsx.includes(`thisObj.${symbol}`)) {
    throw new Error(`ExtendScript bridge did not expose ${symbol}.`);
  }
}
if (!guiBundle.includes("Adobe bridge payload is too large")) {
  throw new Error("Panel no longer guards the CEP evalScript payload size.");
}
if (!guiBundle.includes("appendCutBatch")) {
  throw new Error("Panel is not using batched After Effects composition generation.");
}
for (const windowsFilter of [
  "Video files:*.mov;*.mp4;*.m4v;*.avi;*.mxf,All files:*.*",
  "Audio files:*.mp3;*.wav;*.aac;*.m4a;*.flac,All files:*.*",
  "clip(s) failed analysis",
  "/analysis-jobs",
  "/media/scan",
  "Cancel task",
  "role:\"progressbar\"",
]) {
  if (!guiBundle.includes(windowsFilter)) {
    throw new Error(`Windows media filter regressed: ${windowsFilter}`);
  }
}
for (const identity of ["com.akestudio.flagshipeditor.bridge", packageVersion]) {
  if (!guiBundle.includes(identity) || !jsx.includes(identity)) {
    throw new Error(`Panel/JSX bridge identity drift: ${identity}`);
  }
}

execFileSync(process.execPath, [path.join(root, "scripts", "test-ae-bridge.mjs")], {
  cwd: root,
  stdio: "inherit",
});

console.log("CEP post-build validation passed.");
