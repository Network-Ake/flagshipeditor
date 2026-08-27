// startBackend() is the one bridge function that talks to the world outside
// After Effects, and a wrong path there is invisible until someone installs the
// package and opens the panel — which is exactly how v2.0.0 shipped a backend
// the panel could not find. These tests load the real compiled bundle into an
// emulated ExtendScript host and walk it over the exact directory layouts our
// installers produce, so every path the panel searches is checked against a
// place a shipped installer actually writes to.
import fs from "node:fs";
import vm from "node:vm";
import path from "node:path";

const BRIDGE = path.resolve("dist/cep/jsx/index.js");
const source = fs.readFileSync(BRIDGE, "utf8");

const norm = (p) => String(p).replace(/\//g, "\\").replace(/\\+/g, "\\").replace(/\\$/, "");
const key = (p) => norm(p).toLowerCase();

function makeHost({ files, env, os, scriptFile, reg }) {
  const fileSet = new Set(files.map(key));
  const dirs = new Map();
  for (const f of files) {
    let d = norm(f);
    while (d.includes("\\")) { d = d.slice(0, d.lastIndexOf("\\")); if (d) dirs.set(d.toLowerCase(), d); }
  }
  const dirSet = new Set(dirs.keys());
  const calls = [];

  class VFile {
    constructor(p) { this.fsName = norm(p); }
    get exists() { return fileSet.has(key(this.fsName)); }
    get parent() {
      const i = this.fsName.lastIndexOf("\\");
      return i <= 0 ? null : new VFolder(this.fsName.slice(0, i));
    }
  }
  class VFolder {
    constructor(p) { this.fsName = norm(p); }
    get exists() { return dirSet.has(key(this.fsName)); }
    get parent() {
      const i = this.fsName.lastIndexOf("\\");
      return i <= 0 ? null : new VFolder(this.fsName.slice(0, i));
    }
    getFiles() {
      const prefix = key(this.fsName) + "\\";
      const kids = new Set();
      for (const d of dirSet) if (d.startsWith(prefix) && !d.slice(prefix.length).includes("\\")) kids.add(d);
      const out = [];
      for (const d of kids) out.push(new VFolder(dirs.get(d)));
      for (const f of fileSet) if (f.startsWith(prefix) && !f.slice(prefix.length).includes("\\")) out.push(new VFile(f));
      return out;
    }
  }

  const sandbox = {
    app: { version: "26.0" },
    JSON,
    File: VFile,
    Folder: VFolder,
    system: {
      callSystem(cmd) {
        calls.push(cmd);
        if (/reg query/i.test(cmd)) {
          return reg ? `\r\nHKEY_LOCAL_MACHINE\\Software\\ake-studio\\FlagshipEditor\r\n    InstallDir    REG_SZ    ${reg}\r\n\r\n` : "";
        }
        return "";
      },
    },
    $: { fileName: scriptFile, os, getenv: (n) => (n in env ? env[n] : null), writeln() {} },
  };
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(source, sandbox, { filename: BRIDGE });
  return { thisObj: sandbox, calls };
}

// ---- the exact layout the v2.0.0 MSI writes ---------------------------------
const CEP = "C:\\Program Files (x86)\\Common Files\\Adobe\\CEP\\extensions\\com.akestudio.flagshipeditor";
const PF = "C:\\Program Files\\FlagshipEditor";
const msiFiles = [
  `${PF}\\Start-FlagshipEditor-Backend.vbs`,
  `${PF}\\Stop-FlagshipEditor-Backend.vbs`,
  `${PF}\\engine\\server.py`,
  `${PF}\\engine\\backend_launcher.py`,
  `${PF}\\runtime\\python\\pythonw.exe`,
  `${PF}\\runtime\\bin\\ffmpeg.exe`,
  `${CEP}\\CSXS\\manifest.xml`,
  `${CEP}\\jsx\\index.js`,
  `${CEP}\\main\\index.html`,
  `${CEP}\\Start-FlagshipEditor-Backend.cmd`,
];
const winEnv = {
  ProgramW6432: "C:\\Program Files",
  ProgramFiles: "C:\\Program Files",
  "CommonProgramFiles(x86)": "C:\\Program Files (x86)\\Common Files",
  CommonProgramFiles: "C:\\Program Files\\Common Files",
  APPDATA: "C:\\Users\\Steve\\AppData\\Roaming",
  LOCALAPPDATA: "C:\\Users\\Steve\\AppData\\Local",
};
const AE_EXE = "C:\\Program Files\\Adobe\\Adobe After Effects 2026\\Support Files\\AfterFX.exe";

let failures = 0;
function check(name, fn) {
  try { fn(); console.log(`  PASS  ${name}`); }
  catch (e) { failures++; console.log(`  FAIL  ${name}\n        ${e.message}`); }
}
const assert = (cond, msg) => { if (!cond) throw new Error(msg); };

console.log("\nScenario 1 — Steve's machine: MSI installed, panel loaded from the CEP folder");
{
  const h = makeHost({ files: msiFiles, env: winEnv, os: "Windows 10", scriptFile: `${CEP}\\jsx\\index.js` });
  const r = JSON.parse(h.thisObj.startBackend());
  check("backend is found", () => assert(r.__result && r.__result.launched, `got error: ${r.__error}`));
  check("it is the Program Files VBS launcher", () =>
    assert(r.__result.launcher === `${PF}\\Start-FlagshipEditor-Backend.vbs`, `launched ${r.__result.launcher}`));
  check("launched through wscript //nologo, minimised and detached", () =>
    assert(/^cmd\.exe \/c start "FlagshipEditor Backend" \/min wscript\.exe \/\/nologo "C:\\Program Files\\FlagshipEditor\\Start-FlagshipEditor-Backend\.vbs"$/.test(h.calls[0]),
      `command was: ${h.calls[0]}`));
  check("no reg query needed on the happy path", () =>
    assert(!h.calls.some((c) => /reg query/i.test(c)), "registry was queried unnecessarily"));
  check("getExtensionRoot resolves the panel, not After Effects", () =>
    assert(JSON.parse(h.thisObj.getExtensionRoot()).__result.root === CEP, "extension root wrong"));
}

console.log("\nScenario 2 — the v2.0.0 regression: $.fileName is AfterFX.exe at load time");
{
  const h = makeHost({ files: msiFiles, env: winEnv, os: "Windows 10", scriptFile: AE_EXE });
  const r = JSON.parse(h.thisObj.startBackend());
  check("still finds the backend via the absolute Program Files path", () =>
    assert(r.__result && r.__result.launcher === `${PF}\\Start-FlagshipEditor-Backend.vbs`, `got ${JSON.stringify(r)}`));
  check("the bogus After Effects paths are never probed", () =>
    assert(JSON.parse(h.thisObj.getExtensionRoot()).__result.root === "", "AfterFX.exe was accepted as a script path"));
}

console.log("\nScenario 3 — custom INSTALLDIR: only HKLM knows where it went");
{
  const custom = "D:\\Apps\\FlagshipEditor";
  const files = msiFiles
    .filter((f) => !f.startsWith(PF) && f !== `${CEP}\\Start-FlagshipEditor-Backend.cmd`)
    .concat([`${custom}\\Start-FlagshipEditor-Backend.vbs`, `${custom}\\engine\\server.py`]);
  const h = makeHost({ files, env: winEnv, os: "Windows 10", scriptFile: `${CEP}\\jsx\\index.js`, reg: `${custom}\\` });
  const r = JSON.parse(h.thisObj.startBackend());
  check("registry fallback finds it", () =>
    assert(r.__result && r.__result.launcher === `${custom}\\Start-FlagshipEditor-Backend.vbs`, `got ${JSON.stringify(r)}`));
  check("the trailing backslash from [INSTALLDIR] is trimmed", () =>
    assert(!r.__result.launcher.includes("\\\\"), `double separator in ${r.__result.launcher}`));
}

console.log("\nScenario 4 — custom INSTALLDIR reached through the CEP bridge .cmd");
{
  const custom = "D:\\Apps\\FlagshipEditor";
  const files = msiFiles.filter((f) => !f.startsWith(PF))
    .concat([`${custom}\\Start-FlagshipEditor-Backend.vbs`]);
  const h = makeHost({ files, env: winEnv, os: "Windows 10", scriptFile: AE_EXE, reg: `${custom}\\` });
  const r = JSON.parse(h.thisObj.startBackend());
  check("the panel-adjacent bridge .cmd is used", () =>
    assert(r.__result && r.__result.launcher === `${CEP}\\Start-FlagshipEditor-Backend.cmd`, `got ${JSON.stringify(r)}`));
  check("a .cmd is run directly, not through wscript", () =>
    assert(!/wscript/.test(h.calls[0]) && /\/min "/.test(h.calls[0]), `command was: ${h.calls[0]}`));
}

console.log("\nScenario 5 — v0.1.x per-user install still works (backward compatibility)");
{
  const old = "C:\\Users\\Steve\\AppData\\Local\\ake-studio\\FlagshipEditor";
  const files = [
    `${old}\\0.1.8\\Start-FlagshipEditor-Backend.cmd`,
    `${old}\\0.1.9\\Start-FlagshipEditor-Backend.cmd`,
    `${old}\\0.1.9\\engine\\server.py`,
    `C:\\Users\\Steve\\AppData\\Roaming\\Adobe\\CEP\\extensions\\com.akestudio.flagshipeditor\\jsx\\index.js`,
  ];
  const h = makeHost({ files, env: winEnv, os: "Windows 10",
    scriptFile: `C:\\Users\\Steve\\AppData\\Roaming\\Adobe\\CEP\\extensions\\com.akestudio.flagshipeditor\\jsx\\index.js` });
  const r = JSON.parse(h.thisObj.startBackend());
  check("newest versioned install wins", () =>
    assert(r.__result && r.__result.launcher === `${old}\\0.1.9\\Start-FlagshipEditor-Backend.cmd`, `got ${JSON.stringify(r)}`));
}

console.log("\nScenario 5b — version folders sort numerically: 1.10.0 beats 1.9.0");
{
  const old = "C:\\Users\\Steve\\AppData\\Local\\ake-studio\\FlagshipEditor";
  const files = [
    `${old}\\1.9.0\\Start-FlagshipEditor-Backend.cmd`,
    `${old}\\1.10.0\\Start-FlagshipEditor-Backend.cmd`,
    `C:\\Users\\Steve\\AppData\\Roaming\\Adobe\\CEP\\extensions\\com.akestudio.flagshipeditor\\jsx\\index.js`,
  ];
  const h = makeHost({ files, env: winEnv, os: "Windows 10",
    scriptFile: `C:\\Users\\Steve\\AppData\\Roaming\\Adobe\\CEP\\extensions\\com.akestudio.flagshipeditor\\jsx\\index.js` });
  const r = JSON.parse(h.thisObj.startBackend());
  check("1.10.0 wins over 1.9.0 (a plain string sort picks 1.9.0)", () =>
    assert(r.__result && r.__result.launcher === `${old}\\1.10.0\\Start-FlagshipEditor-Backend.cmd`, `got ${JSON.stringify(r)}`));
}

console.log("\nScenario 6 — engine present but launcher gone: server.py fallback");
{
  const files = [`${PF}\\engine\\server.py`, `${CEP}\\jsx\\index.js`];
  const h = makeHost({ files, env: winEnv, os: "Windows 10", scriptFile: `${CEP}\\jsx\\index.js` });
  const r = JSON.parse(h.thisObj.startBackend());
  check("falls back to running server.py", () =>
    assert(r.__result && r.__result.launcher === `${PF}\\engine\\server.py`.replace(/\\/g, "\\"), `got ${JSON.stringify(r)}`));
}

console.log("\nScenario 7 — nothing installed: the error must be honest and free of junk paths");
{
  const h = makeHost({ files: [`${CEP}\\jsx\\index.js`], env: winEnv, os: "Windows 10", scriptFile: `${CEP}\\jsx\\index.js` });
  const r = JSON.parse(h.thisObj.startBackend());
  check("reports failure", () => assert(r.__error, "expected an error"));
  check("names the real MSI location", () =>
    assert(r.__error.includes(`${PF}\\Start-FlagshipEditor-Backend.vbs`), "Program Files VBS not listed"));
  check("names the CEP bridge location", () =>
    assert(r.__error.includes(`${CEP}\\Start-FlagshipEditor-Backend.cmd`), "CEP bridge not listed"));
  check("never suggests the After Effects program folder", () =>
    assert(!/Adobe After Effects/.test(r.__error), `junk path present:\n${r.__error}`));
  check("every listed path uses Windows separators", () =>
    assert(!r.__error.split("Looked in: ")[1].includes("/"), "a listed path mixes separators"));
  check("no path is listed twice", () => {
    const parts = r.__error.split("Looked in: ")[1].split(", ").map((s) => s.toLowerCase());
    assert(new Set(parts).size === parts.length, "duplicate entries in the looked-in list");
  });
  console.log("\n        looked in:\n" + r.__error.split("Looked in: ")[1].split(", ").map((s) => "          " + s).join("\n"));
}

console.log("\nScenario 8 — macOS dev checkout uses the POSIX branch");
{
  const repo = "/Users/issandre/flagshipeditor";
  const h = makeHost({
    files: [`${repo}/engine/server.py`, `${repo}/dist/cep/jsx/index.js`],
    env: {}, os: "Macintosh OS 15.7", scriptFile: `${repo}/dist/cep/jsx/index.js`,
  });
  const r = JSON.parse(h.thisObj.startBackend());
  check("finds engine/server.py above dist/cep", () => assert(r.__result && r.__result.launched, `got ${JSON.stringify(r)}`));
  check("uses nohup python3, not cmd.exe", () =>
    assert(/nohup python3 server\.py/.test(h.calls[0]) && !/cmd\.exe/.test(h.calls[0]), `command was: ${h.calls[0]}`));
}

console.log(
  failures === 0
    ? "\nBackend search tests passed (MSI layout, evalScript $.fileName regression, custom INSTALLDIR via registry and via the CEP bridge, v0.1.x per-user install, server.py fallback, error reporting, macOS)."
    : `\n${failures} backend-search check(s) FAILED.`
);
process.exit(failures === 0 ? 0 : 1);
