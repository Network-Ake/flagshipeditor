import { defineConfig } from "bolt-cep";

export default defineConfig({
  id: "com.akestudio.flagshipeditor",
  name: "FlagshipEditor",
  version: "0.1.0",
  hosts: [
    {
      name: "AEFT",
      version: "25.0",
      debug: true,
    },
  ],
  panels: [
    {
      name: "main",
      title: "FlagshipEditor",
      type: "Panel",
      width: 420,
      height: 720,
      minSize: [320, 500],
      maxSize: [600, 1200],
      icons: {
        normal: "assets/icon-normal.png",
        rollOver: "assets/icon-rollover.png",
      },
    },
    {
      name: "settings",
      title: "FlagshipEditor Settings",
      type: "Panel",
      width: 380,
      height: 500,
      minSize: [300, 400],
      maxSize: [500, 700],
    },
  ],
  zxp: {
    publisher: "ake-studio",
    countryCode: "CA",
    certPath: "./cert/cert.p12",
    certPassword: "",
  },
  copyAssets: ["styles", "luts", "assets", "python", "ffmpeg"],
});