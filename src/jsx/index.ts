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
      version: "2.0.0",
      hostName: "After Effects",
      hostVersion: app.version,
    },
  });
};

// The panel needs the on-disk extension root to resolve the bundled LUTs.
thisObj.getExtensionRoot = function () {
  try {
    var scriptFile = new File($.fileName);
    var jsxFolder = scriptFile.parent;
    var root = jsxFolder && jsxFolder.parent ? jsxFolder.parent : jsxFolder;
    return JSON.stringify({ __result: { root: root ? root.fsName : "" } });
  } catch (e) {
    return JSON.stringify({ __error: String(e) });
  }
};

thisObj.openFileDialog = function (filter: string) {
  var file = File.openDialog("Select a file", filter, false);
  return file ? file.fsName : "null";
};

thisObj.openFilesDialog = function (filter: string) {
  var files: any = File.openDialog("Select files", filter, true);
  if (!files) return "[]";
  var paths: string[] = [];
  // ExtendScript may return a File object even when multiSelect is true.
  // File.length is the byte size, so detect a single file by fsName instead.
  if (files.fsName) {
    paths.push(files.fsName);
    return JSON.stringify(paths);
  }
  for (var i = 0; i < files.length; i++) {
    paths.push(files[i].fsName);
  }
  return JSON.stringify(paths);
};

thisObj.openFolderDialog = function () {
  var folder = Folder.selectDialog("Select a media folder");
  return folder ? folder.fsName : "null";
};

// Starting the backend is the one job the panel cannot do itself: CEP runs
// without Node, so the only process launcher available is ExtendScript's
// `system.callSystem`. Both branches detach immediately — the panel polls
// /health rather than blocking After Effects on a synchronous shell call.
function flagshipEditorExtensionRoot(): any {
  var scriptFile = new File($.fileName);
  var jsxFolder = scriptFile.parent;
  return jsxFolder && jsxFolder.parent ? jsxFolder.parent : jsxFolder;
}

function flagshipEditorWindowsLaunchers(): string[] {
  var candidates: string[] = [];
  var localAppData = $.getenv("LOCALAPPDATA");
  if (localAppData) {
    var installRoot = new Folder(localAppData + "/ake-studio/FlagshipEditor");
    if (installRoot.exists) {
      var entries = installRoot.getFiles();
      var versions: string[] = [];
      for (var i = 0; i < entries.length; i++) {
        if (entries[i] instanceof Folder) versions.push(entries[i].fsName);
      }
      // Newest install first, so an upgrade is preferred over a leftover build.
      versions.sort();
      for (var v = versions.length - 1; v >= 0; v--) {
        candidates.push(versions[v] + "\\Start-FlagshipEditor-Backend.cmd");
      }
    }
  }
  var root = flagshipEditorExtensionRoot();
  if (root) {
    candidates.push(root.fsName + "\\Start-FlagshipEditor-Backend.cmd");
    if (root.parent) {
      candidates.push(root.parent.fsName + "\\Start-FlagshipEditor-Backend.cmd");
      if (root.parent.parent) {
        candidates.push(root.parent.parent.fsName + "\\scripts\\Start-FlagshipEditor-Backend.cmd");
      }
    }
  }
  return candidates;
}

function flagshipEditorServerScripts(): string[] {
  var candidates: string[] = [];
  var override = $.getenv("FLAGSHIPEDITOR_ENGINE");
  if (override) candidates.push(override + "/server.py");
  var localAppData = $.getenv("LOCALAPPDATA");
  if (localAppData) {
    var installRoot = new Folder(localAppData + "/ake-studio/FlagshipEditor");
    if (installRoot.exists) {
      var entries = installRoot.getFiles();
      var versions: string[] = [];
      for (var i = 0; i < entries.length; i++) {
        if (entries[i] instanceof Folder) versions.push(entries[i].fsName);
      }
      versions.sort();
      for (var v = versions.length - 1; v >= 0; v--) candidates.push(versions[v] + "/engine/server.py");
    }
  }
  var folder = flagshipEditorExtensionRoot();
  for (var depth = 0; depth < 4 && folder; depth++) {
    candidates.push(folder.fsName + "/engine/server.py");
    folder = folder.parent;
  }
  return candidates;
}

thisObj.startBackend = function () {
  try {
    var isWindows = /Windows/.test(String($.os));
    var attempted: string[] = [];
    var i;

    if (isWindows) {
      var launchers = flagshipEditorWindowsLaunchers();
      for (i = 0; i < launchers.length; i++) {
        attempted.push(launchers[i]);
        if (!new File(launchers[i]).exists) continue;
        system.callSystem(
          'cmd.exe /c start "FlagshipEditor Backend" /min "' + launchers[i] + '"'
        );
        return JSON.stringify({ __result: { launched: true, launcher: launchers[i] } });
      }
    }

    // Windows falls through to this branch when the installer's launcher is
    // gone but the engine folder survived; macOS always uses it.
    var scripts = flagshipEditorServerScripts();
    for (i = 0; i < scripts.length; i++) {
      attempted.push(scripts[i]);
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

    return JSON.stringify({
      __error:
        "The FlagshipEditor backend could not be found. Run the installer again. Looked in: " +
        attempted.join(", "),
    });
  } catch (e) {
    return JSON.stringify({ __error: "The backend could not be started: " + String(e) });
  }
};
