import type { CEP_Config } from "vite-cep-plugin";

const config: CEP_Config = {
  version: "2.0.0",
  id: "com.akestudio.flagshipeditor",
  displayName: "FlagshipEditor",
  symlink: "local",
  port: 3000,
  servePort: 5000,
  startingDebugPort: 8860,
  extensionManifestVersion: 6.0,
  requiredRuntimeVersion: 9.0,
  hosts: [{ name: "AEFT", version: "[24.0,99.9]" }],
  type: "Panel",
  // The panel only needs Adobe's CEP bridge. Enabling Node inside CEF caused
  // CEPHtmlEngine to crash on Windows before React could mount.
  parameters: ["--v=0", "--allow-file-access", "--allow-file-access-from-files"],
  width: 420,
  height: 720,
  panels: [
    {
      mainPath: "./main/index.html",
      scriptPath: "./jsx/index.js",
      name: "main",
      panelDisplayName: "FlagshipEditor",
      autoVisible: true,
      width: 420,
      height: 720,
    },
  ],
  build: { jsxBin: "off", sourceMap: false },
  zxp: {
    country: "CA",
    province: "QC",
    org: "ake-studio",
    password: "flagshipeditor",
    tsa: ["http://timestamp.digicert.com/"],
    allowSkipTSA: true,
    sourceMap: false,
    jsxBin: "off",
  },
  installModules: [],
  copyAssets: [],
  copyZipAssets: [],
};

export default config;
