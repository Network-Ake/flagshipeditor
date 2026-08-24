import fs from "node:fs";
import path from "node:path";
import { defineConfig } from "vite";

import react from "@vitejs/plugin-react"; // BOLT_REACT_ONLY

import { cep, CepOptions, runAction } from "vite-cep-plugin";
import cepConfig from "./cep.config";
import { extendscriptConfig } from "./vite.es.config";

const extensions = [".js", ".ts", ".tsx"];

const devDist = "dist";
const cepDist = "cep";

const src = path.resolve(__dirname, "src");
const root = path.resolve(src, "js");
const outDir = path.resolve(__dirname, "dist", cepDist);

const debugReact = process.env.DEBUG_REACT === "true";
const isProduction = process.env.NODE_ENV === "production";
const isMetaPackage = process.env.ZIP_PACKAGE === "true";
const isPackage = process.env.ZXP_PACKAGE === "true" || isMetaPackage;
const isServe = process.env.SERVE_PANEL === "true";
const action = process.env.BOLT_ACTION;

let input: { [key: string]: string } = {};
cepConfig.panels.map((panel) => {
  input[panel.name] = path.resolve(root, panel.mainPath);
});

const config: CepOptions = {
  cepConfig,
  isProduction,
  isPackage,
  isMetaPackage,
  isServe,
  debugReact,
  dir: `${__dirname}/${devDist}`,
  cepDist: cepDist,
  zxpOutput: `${__dirname}/${devDist}/zxp/${cepConfig.id}`,
  zipOutput: `${__dirname}/${devDist}/zip/${cepConfig.displayName}_${cepConfig.version}`,
  packages: cepConfig.installModules || [],
};

// vite-cep-plugin always emits an <Icons> block, filling it with the string
// "undefined" when no icons are configured. After Effects then looks for a file
// literally named "undefined". Stripping it here — in a writeBundle that runs
// before the cep plugin's, which is where the ZXP is signed — keeps the flaw
// out of the signed package, not just out of the unsigned dist/cep tree.
const sanitizeCepManifest = {
  name: "sanitize-cep-manifest",
  writeBundle() {
    const manifestPath = path.resolve(__dirname, "dist", cepDist, "CSXS", "manifest.xml");
    if (!fs.existsSync(manifestPath)) return;
    const manifest = fs.readFileSync(manifestPath, "utf8");
    const cleaned = manifest.replace(/\s*<Icons>[\s\S]*?<\/Icons>/g, (block) =>
      block.includes("undefined") ? "" : block,
    );
    if (cleaned !== manifest) fs.writeFileSync(manifestPath, cleaned, "utf8");
  },
};

const removeUnusedCepRequireShim = {
  name: "remove-unused-cep-require-shim",
  enforce: "post" as const,
  transformIndexHtml: {
    order: "post" as const,
    handler(html: string) {
      return html.replace(
        /<script>\s*"use strict";\s*window\.require =[\s\S]*?<\/script>/,
        "",
      );
    },
  },
};

const copyStaticCss = {
  name: "copy-static-css",
  enforce: "post" as const,
  transformIndexHtml: {
    order: "post" as const,
    handler(html: string) {
      if (!html.includes('href="./styles.css"') && !html.includes("href='./styles.css'")) {
        return html.replace("</head>", '  <link rel="stylesheet" href="./styles.css" />\n</head>');
      }
      return html;
    },
  },
  writeBundle() {
    const src = path.resolve(__dirname, "src", "js", "main", "styles.css");
    const dest = path.resolve(__dirname, "dist", "cep", "main", "styles.css");
    if (fs.existsSync(src)) {
      fs.mkdirSync(path.dirname(dest), { recursive: true });
      fs.copyFileSync(src, dest);
    }
  },
};

if (action) runAction(config, action);

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [
    react(), // BOLT_REACT_ONLY
    sanitizeCepManifest,
    cep(config),
    removeUnusedCepRequireShim,
    copyStaticCss,
  ],
  resolve: {
    alias: [{ find: "@esTypes", replacement: path.resolve(__dirname, "src") }],
  },
  root,
  clearScreen: false,
  server: {
    port: cepConfig.port,
  },
  preview: {
    port: cepConfig.servePort,
  },

  build: {
    sourcemap: isPackage ? cepConfig.zxp.sourceMap : cepConfig.build?.sourceMap,
    // commonjsOptions: {
    //   transformMixedEsModules: true,
    // },
    rollupOptions: {
      input,
      output: {
        // Ship a self-contained browser bundle. A shared CommonJS chunk made
        // CEP depend on Node's `require`, which crashed CEPHtmlEngine on some
        // Windows/After Effects installations and left an empty docked panel.
        inlineDynamicImports: true,
        preserveModules: false,
        format: "iife",
        entryFileNames: "assets/[name]-[hash].js",
        chunkFileNames: "assets/[name]-[hash].js",
      },
    },
    target: "chrome74",
    outDir,
  },
});

// rollup es3 build
const outPathExtendscript = path.join("dist", cepDist, "jsx", "index.js");
extendscriptConfig(
  `src/jsx/index.ts`,
  outPathExtendscript,
  cepConfig,
  extensions,
  isProduction,
  isPackage,
);
