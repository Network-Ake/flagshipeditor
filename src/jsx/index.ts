// FlagshipEditor — ExtendScript Entry Point
// This file is compiled to ES3 and loaded by After Effects

// @include './lib/json2.js'
// @include './aeft/aeft.ts'

import { buildComp } from "./aeft/aeft";

// Expose functions to evalTS
export const buildComp = buildComp;
export const getHostInfo = () => {
  return {
    name: app.appName,
    version: app.version,
  };
};

export const openFileDialog = (filter: string) => {
  return File.openDialog("Select a file", filter, false);
};

export const openFilesDialog = (filter: string) => {
  const files = File.openDialog("Select files", filter, true);
  if (!files) return "[]";
  return JSON.stringify(files.map((f: File) => f.fsName));
};