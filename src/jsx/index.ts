// FlagshipEditor — ExtendScript Entry Point
// This file is compiled to ES3 and loaded by After Effects

// @include './lib/json2.js'

import {
  abortComp as abortComposition,
  appendCutBatch as appendCompositionCutBatch,
  beginComp as beginComposition,
  finishComp as finishComposition,
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
thisObj.getBridgeHealth = () => {
  return JSON.stringify({
    __result: {
      appId: "com.akestudio.flagshipeditor.bridge",
      version: "0.1.9",
      hostName: "After Effects",
      hostVersion: app.version,
    },
  });
};

thisObj.openFileDialog = (filter: string) => {
  const file = File.openDialog("Select a file", filter, false);
  return file ? file.fsName : "null";
};

thisObj.openFilesDialog = (filter: string) => {
  const files: any = File.openDialog("Select files", filter, true);
  if (!files) return "[]";
  const paths: string[] = [];
  // ExtendScript may return a File object even when multiSelect is true.
  // File.length is the byte size, so detect a single file by fsName instead.
  if (files.fsName) {
    paths.push(files.fsName);
    return JSON.stringify(paths);
  }
  for (let i = 0; i < files.length; i++) {
    paths.push(files[i].fsName);
  }
  return JSON.stringify(paths);
};

thisObj.openFolderDialog = () => {
  const folder = Folder.selectDialog("Select a media folder");
  return folder ? folder.fsName : "null";
};
