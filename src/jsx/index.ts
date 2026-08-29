// FlagshipEditor — ExtendScript Entry Point
// This file is compiled to ES3 and loaded by After Effects.

// @include './lib/json2.js'

import {
  abortComp as abortComposition,
  appendCutBatch as appendCompositionCutBatch,
  beginComp as beginComposition,
  describeStyleCoverage as describeCompositionStyleCoverage,
  finishComp as finishComposition,
  getBuildWarnings as getCompositionBuildWarnings,
  probeElement3D as probeCompositionElement3D,
  replaceSectionCuts as replaceSectionCutsInComp,
  swapCut as swapCompositionCut,
} from "./aeft/aeft";

// Rollup wraps this file in an IIFE. Explicitly publish the bridge functions on
// the ExtendScript global object so CEP's evalScript can call them by name.
declare const thisObj: any;

thisObj.beginComp = beginComposition;
thisObj.appendCutBatch = appendCompositionCutBatch;
thisObj.finishComp = finishComposition;
thisObj.abortComp = abortComposition;
thisObj.swapCut = swapCompositionCut;
thisObj.replaceSectionCuts = replaceSectionCutsInComp;
thisObj.describeStyleCoverage = describeCompositionStyleCoverage;
thisObj.getBuildWarnings = getCompositionBuildWarnings;
thisObj.probeElement3D = probeCompositionElement3D;

thisObj.getBridgeHealth = function () {
  return JSON.stringify({
    __result: {
      appId: "com.akestudio.flagshipeditor.bridge",
      version: "3.1.0",
      hostName: "After Effects",
      hostVersion: app.version,
    },
  });
};

// $.fileName names this file only while After Effects is loading it. Inside a
// function reached through evalScript it names the host executable instead,
// which is how the backend search ended up probing
// C:\Program Files\Adobe\Adobe After Effects 2026. Capture it once, at load
// time, and only trust it when it really is a script file.
var FLAGSHIP_SCRIPT_PATH = (function () {
  try {
    var name = String($.fileName);
    return /\.(js|jsx|jsxbin)$/i.test(name) ? name : "";
  } catch (e) {
    return "";
  }
})();

// The panel is laid out as <extension>/jsx/index.js, so its root is the folder
// above jsx/. Returns null rather than a wrong guess when $.fileName was no help.
function flagshipEditorExtensionRoot(): any {
  try {
    if (!FLAGSHIP_SCRIPT_PATH) return null;
    var jsxFolder = new File(FLAGSHIP_SCRIPT_PATH).parent;
    if (!jsxFolder) return null;
    return jsxFolder.parent ? jsxFolder.parent : jsxFolder;
  } catch (e) {
    return null;
  }
}

// The panel needs the on-disk extension root to resolve the bundled LUTs.
thisObj.getExtensionRoot = function () {
  try {
    var root = flagshipEditorExtensionRoot();
    return JSON.stringify({ __result: { root: root ? root.fsName : "" } });
  } catch (e) {
    return JSON.stringify({ __error: String(e) });
  }
};

thisObj.openFileDialog = function (filter: string) {
  try {
    var file = File.openDialog("Select a file", filter, false);
    if (!file) return JSON.stringify({ __result: null });
    return JSON.stringify({ __result: file.fsName });
  } catch (e) {
    return JSON.stringify({ __error: "File dialog failed: " + String(e) });
  }
};

thisObj.openFilesDialog = function (filter: string) {
  try {
    var files: any = File.openDialog("Select files", filter, true);
    if (!files) return JSON.stringify({ __result: [] });
    var paths: string[] = [];
    // ExtendScript may return a File object even when multiSelect is true.
    // File.length is the byte size, so detect a single file by fsName instead.
    if (files.fsName) {
      paths.push(files.fsName);
      return JSON.stringify({ __result: paths });
    }
    for (var i = 0; i < files.length; i++) {
      paths.push(files[i].fsName);
    }
    return JSON.stringify({ __result: paths });
  } catch (e) {
    return JSON.stringify({ __error: "File dialog failed: " + String(e) });
  }
};

thisObj.openFolderDialog = function () {
  try {
    var folder = Folder.selectDialog("Select a media folder");
    if (!folder) return JSON.stringify({ __result: null });
    return JSON.stringify({ __result: folder.fsName });
  } catch (e) {
    return JSON.stringify({ __error: "Folder dialog failed: " + String(e) });
  }
};

// Starting the backend is the one job the panel cannot do itself: CEP runs
// without Node, so the only process launcher available is ExtendScript's
// `system.callSystem`. Every branch detaches immediately — the panel polls
// /health rather than blocking After Effects on a synchronous shell call.

var FLAGSHIP_EXTENSION_ID = "com.akestudio.flagshipeditor";
var FLAGSHIP_LAUNCHER = "Start-FlagshipEditor-Backend";
var FLAGSHIP_IS_WINDOWS = /Windows/.test(String($.os));

// Appends a path unless an equivalent one is already listed. Trailing
// separators are trimmed so the "looked in" list in the error stays readable.
function flagshipEditorPush(list: string[], seen: any, path: string): void {
  if (!path) return;
  if (FLAGSHIP_IS_WINDOWS) path = path.replace(/\//g, "\\");
  while (path.length > 3) {
    var last = path.charAt(path.length - 1);
    if (last !== "\\" && last !== "/") break;
    path = path.substring(0, path.length - 1);
  }
  var key = path.toLowerCase();
  if (seen[key]) return;
  seen[key] = 1;
  list.push(path);
}

// The numeric runs in a path's last segment ("...\\2.0.0" -> [2, 0, 0]), for
// version-aware folder ordering. A folder without digits yields [] and sorts
// oldest.
function flagshipEditorVersionParts(path: string): number[] {
  var name = path.replace(/[\\\/]+$/, "");
  var cut = name.lastIndexOf("\\");
  var slash = name.lastIndexOf("/");
  if (slash > cut) cut = slash;
  if (cut !== -1) name = name.substring(cut + 1);
  var runs = name.match(/\d+/g);
  var parts: number[] = [];
  if (runs) {
    for (var i = 0; i < runs.length; i++) {
      parts[parts.length] = parseInt(runs[i], 10);
    }
  }
  return parts;
}

// Every directory a FlagshipEditor *install* can occupy, newest layout first:
// v2.0.0's MSI is per-machine under Program Files, v0.1.x's .cmd installer was
// per-user under LOCALAPPDATA, and a dev build runs out of the checkout itself.
function flagshipEditorInstallRoots(): string[] {
  var roots: string[] = [];
  var seen: any = {};
  var i;

  // ProgramW6432 is the 64-bit tree even when the host process is 32-bit.
  var programFiles = FLAGSHIP_IS_WINDOWS
    ? [$.getenv("ProgramW6432"), $.getenv("ProgramFiles"), "C:\\Program Files"]
    : [];
  for (i = 0; i < programFiles.length; i++) {
    if (programFiles[i]) flagshipEditorPush(roots, seen, programFiles[i] + "\\FlagshipEditor");
  }

  var localAppData = FLAGSHIP_IS_WINDOWS ? $.getenv("LOCALAPPDATA") : null;
  if (localAppData) {
    var installRoot = new Folder(localAppData + "\\ake-studio\\FlagshipEditor");
    if (installRoot.exists) {
      var entries = installRoot.getFiles();
      var versions: string[] = [];
      for (i = 0; i < entries.length; i++) {
        if (entries[i] instanceof Folder) versions.push(entries[i].fsName);
      }
      // Newest install first, so an upgrade wins over a leftover build. The
      // entries are full fsName paths, so only the last path segment is
      // compared, and its digit runs are compared numerically: a plain string
      // sort put 1.10.0 before 1.9.0. ES3-safe — ExtendScript has no
      // Array.prototype.map.
      versions.sort(function (a, b) {
        var aParts = flagshipEditorVersionParts(a);
        var bParts = flagshipEditorVersionParts(b);
        var length = aParts.length > bParts.length ? aParts.length : bParts.length;
        for (var part = 0; part < length; part++) {
          var aValue = part < aParts.length ? aParts[part] : 0;
          var bValue = part < bParts.length ? bParts[part] : 0;
          if (aValue !== bValue) return aValue - bValue;
        }
        return a < b ? -1 : a > b ? 1 : 0;
      });
      for (var v = versions.length - 1; v >= 0; v--) flagshipEditorPush(roots, seen, versions[v]);
      flagshipEditorPush(roots, seen, installRoot.fsName);
    }
  }

  // A dev build has engine/ a few levels above dist/cep; on macOS this is the
  // only branch that ever matches.
  var folder = flagshipEditorExtensionRoot();
  for (var depth = 0; depth < 4 && folder; depth++) {
    flagshipEditorPush(roots, seen, folder.fsName);
    folder = folder.parent;
  }
  return roots;
}

// The installers also drop a one-line bridge, Start-FlagshipEditor-Backend.cmd,
// next to the panel itself; it reads InstallDir out of HKLM and hands off to the
// real launcher. These extension folders are spelled out because $.fileName
// cannot be relied on to find them from inside an evalScript call.
function flagshipEditorPanelRoots(): string[] {
  var roots: string[] = [];
  var seen: any = {};

  var root = flagshipEditorExtensionRoot();
  if (root) flagshipEditorPush(roots, seen, root.fsName);

  // v2.0.0 MSI, system-wide. After Effects only scans the 32-bit Common Files
  // tree for shared CEP extensions, which is where the package puts the panel.
  var common = FLAGSHIP_IS_WINDOWS
    ? $.getenv("CommonProgramFiles(x86)") || $.getenv("CommonProgramFiles")
    : null;
  if (common) {
    flagshipEditorPush(roots, seen, common + "\\Adobe\\CEP\\extensions\\" + FLAGSHIP_EXTENSION_ID);
  }
  // v0.1.x .cmd installer, per-user.
  var appData = FLAGSHIP_IS_WINDOWS ? $.getenv("APPDATA") : null;
  if (appData) {
    flagshipEditorPush(roots, seen, appData + "\\Adobe\\CEP\\extensions\\" + FLAGSHIP_EXTENSION_ID);
  }
  return roots;
}

// HKLM\Software\ake-studio\FlagshipEditor\InstallDir is written by the MSI from
// a 64-bit component. It is the only thing that can find an install the user
// moved off Program Files, but reading it costs a synchronous `reg query`, so
// it is asked for only once every well-known location has already missed.
var FLAGSHIP_REGISTRY_ROOT: any = null;

function flagshipEditorRegistryRoots(): string[] {
  if (FLAGSHIP_REGISTRY_ROOT === null) {
    FLAGSHIP_REGISTRY_ROOT = "";
    try {
      var out = String(
        system.callSystem(
          'cmd.exe /c reg query "HKLM\\Software\\ake-studio\\FlagshipEditor" /v InstallDir /reg:64 2>nul'
        )
      );
      // reg prints "    InstallDir    REG_SZ    C:\Program Files\FlagshipEditor\".
      var at = out.indexOf("REG_SZ");
      if (at !== -1) {
        var value = out.substring(at + 6);
        var end = value.search(/[\r\n]/);
        if (end !== -1) value = value.substring(0, end);
        FLAGSHIP_REGISTRY_ROOT = value.replace(/^\s+/, "").replace(/\s+$/, "");
      }
    } catch (e) {
      FLAGSHIP_REGISTRY_ROOT = "";
    }
  }
  var roots: string[] = [];
  var seen: any = {};
  flagshipEditorPush(roots, seen, FLAGSHIP_REGISTRY_ROOT);
  return roots;
}

// A launcher comes in either flavour: the MSI ships the windowless .vbs, while
// the older installer and the CEP bridge ship .cmd.
function flagshipEditorLaunchersIn(roots: string[]): string[] {
  var candidates: string[] = [];
  var seen: any = {};
  for (var i = 0; i < roots.length; i++) {
    flagshipEditorPush(candidates, seen, roots[i] + "\\" + FLAGSHIP_LAUNCHER + ".vbs");
    flagshipEditorPush(candidates, seen, roots[i] + "\\" + FLAGSHIP_LAUNCHER + ".cmd");
    flagshipEditorPush(candidates, seen, roots[i] + "\\scripts\\" + FLAGSHIP_LAUNCHER + ".cmd");
  }
  return candidates;
}

function flagshipEditorServersIn(roots: string[]): string[] {
  var candidates: string[] = [];
  var seen: any = {};
  // The VBS launcher exports this, so a backend already started by hand keeps
  // pointing the panel at the same engine.
  var override = $.getenv("FLAGSHIPEDITOR_ENGINE");
  if (override) flagshipEditorPush(candidates, seen, override + "/server.py");
  for (var i = 0; i < roots.length; i++) {
    flagshipEditorPush(candidates, seen, roots[i] + "/engine/server.py");
  }
  return candidates;
}

// wscript runs a .vbs with no console of its own; a .cmd goes straight to the
// shell. `start` detaches either way, so After Effects is never held up.
function flagshipEditorLaunch(path: string): void {
  var isVbs = path.length > 4 && path.substring(path.length - 4).toLowerCase() === ".vbs";
  if (isVbs) {
    system.callSystem(
      'cmd.exe /c start "FlagshipEditor Backend" /min wscript.exe //nologo "' + path + '"'
    );
  } else {
    system.callSystem('cmd.exe /c start "FlagshipEditor Backend" /min "' + path + '"');
  }
}

thisObj.startBackend = function () {
  try {
    var isWindows = FLAGSHIP_IS_WINDOWS;
    var attempted: string[] = [];
    var attemptedSeen: any = {};
    var i;

    // Two passes over the same search. The first only touches paths that are
    // free to test; the second prepends whatever the registry names, and runs
    // only when the first found nothing.
    for (var pass = 0; pass < 2; pass++) {
      var extra = pass === 0 ? [] : flagshipEditorRegistryRoots();
      if (pass === 1 && !extra.length) break;
      var installRoots = extra.concat(flagshipEditorInstallRoots());

      if (isWindows) {
        var launchers = flagshipEditorLaunchersIn(installRoots.concat(flagshipEditorPanelRoots()));
        for (i = 0; i < launchers.length; i++) {
          flagshipEditorPush(attempted, attemptedSeen, launchers[i]);
          if (!new File(launchers[i]).exists) continue;
          flagshipEditorLaunch(launchers[i]);
          return JSON.stringify({ __result: { launched: true, launcher: launchers[i] } });
        }
      }

      // Windows falls through to here when the installer's launcher is gone but
      // the engine folder survived; macOS always uses this branch.
      var scripts = flagshipEditorServersIn(installRoots);
      for (i = 0; i < scripts.length; i++) {
        flagshipEditorPush(attempted, attemptedSeen, scripts[i]);
        var scriptFile = new File(scripts[i]);
        if (!scriptFile.exists) continue;
        var engineFolder = scriptFile.parent.fsName;
        if (isWindows) {
          system.callSystem(
            'cmd.exe /c start "FlagshipEditor Backend" /min cmd /c "cd /d ""' +
              engineFolder +
              '"" && python server.py"'
          );
        } else {
          system.callSystem(
            "/bin/sh -c \"cd '" + engineFolder + "' && nohup python3 server.py >/dev/null 2>&1 &\""
          );
        }
        return JSON.stringify({ __result: { launched: true, launcher: scripts[i] } });
      }
    }

    return JSON.stringify({
      __error:
        "The FlagshipEditor backend could not be found. Run the installer again. Looked in: " +
        attempted.join(", "),
    });
  } catch (e) {
    return JSON.stringify({ __error: "The backend could not be started: " + String(e) });
  }
};
