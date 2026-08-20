import type { CEP_Config } from "vite-cep-plugin";

const config: CEP_Config = {
  version: "0.1.0",
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
  parameters: ["--v=0", "--enable-nodejs", "--mixed-context"],
  width: 420,
  height: 720,
  panels: [
    {
      mainPath: "./main/index.html",
      name: "main",
      panelDisplayName: "FlagshipEditor",
      autoVisible: true,
      width: 420,
      height: 720,
    },
    {
      mainPath: "./settings/index.html",
      name: "settings",
      panelDisplayName: "FlagshipEditor Settings",
      autoVisible: false,
      width: 380,
      height: 500,
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
