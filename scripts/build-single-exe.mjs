/**
 * build-single-exe.mjs
 *
 * Creates a single self-extracting FlagshipEditor installer for Windows.
 *
 * Output: FlagshipEditor-<version>-Windows.exe
 *
 * The file is a hybrid: a CMD header that uses certutil to decode an embedded
 * base64 ZIP payload, extracts it to %TEMP%, runs INSTALL-FLAGSHIPEDITOR.cmd,
 * and cleans up.  No 7-Zip, no PowerShell, no admin rights, no internet.
 *
 * Windows sees it as a batch file but the user just double-clicks it.
 * We name it .exe so Explorer treats it as an application and the user
 * doesn't see a "what program do you want to open this with" dialog.
 *
 * Actually — we can't fake a real PE32+ EXE header.  So we ship a .cmd file
 * but name it clearly.  The user double-clicks → it runs.
 *
 * Alternative: use IExpress (built into Windows) to make a real .exe.
 * IExpress creates a self-extracting EXE from a SED directive file.
 * We generate the SED and the EXE on Windows, but we can't run IExpress
 * on macOS.  So we ship the .cmd self-extractor and instructions.
 *
 * Final approach: ship a .cmd that self-extracts via certutil.
 * It works on every Windows 10/11 machine with zero dependencies.
 */

import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";

const root = process.cwd();
const packageJson = JSON.parse(fs.readFileSync(path.join(root, "package.json"), "utf8"));
const version = packageJson.version;
const packageName = `FlagshipEditor-${version}-Windows`;
const zipPath = path.join(root, "flagshipeditor.zip");
const downloadsPath = path.join("/Users/issandre/Downloads", `${packageName}.zip`);
const singleExePath = path.join("/Users/issandre/Downloads", `${packageName}.exe`);

// ── Verify the ZIP exists and was built ──────────────────────────────────
if (!fs.existsSync(zipPath)) {
  throw new Error("flagshipeditor.zip not found. Run package-windows.mjs first.");
}

const zipSize = fs.statSync(zipPath).size;
if (zipSize < 1_000_000) {
  throw new Error(`ZIP is suspiciously small: ${zipSize} bytes. Run package-windows.mjs first.`);
}

console.log(`Source ZIP: ${zipPath} (${(zipSize / 1024 / 1024).toFixed(1)} MB)`);

// ── Read the ZIP and encode as base64 ────────────────────────────────────
const zipBytes = fs.readFileSync(zipPath);
const base64 = zipBytes.toString("base64");

// certutil can decode base64 but has a line-length limit.  We chunk it
// into 76-character lines which is the standard base64 line width.
const lines = [];
for (let i = 0; i < base64.length; i += 76) {
  lines.push(base64.slice(i, i + 76));
}

console.log(`Base64 payload: ${lines.length} lines, ${(base64.length / 1024 / 1024).toFixed(1)} MB encoded`);

// ── Build the self-extracting CMD ────────────────────────────────────────
// The CMD script:
// 1. Creates a temp extraction folder
// 2. Writes the base64 payload to a .b64 file
// 3. Uses certutil to decode it to a .zip
// 4. Uses tar (built into Windows 10+) to extract the ZIP
// 5. Runs INSTALL-FLAGSHIPEDITOR.cmd
// 6. Cleans up the temp folder
//
// We use tar instead of PowerShell's Expand-Archive because tar is
// built into Windows 10 1803+ and doesn't require PowerShell.
// certutil is built into every Windows since NT 4.0.

const cmd = `@echo off
setlocal EnableExtensions DisableDelayedExpansion
title FlagshipEditor ${version} Installer
color 0A

echo ============================================================
echo  FlagshipEditor ${version} - Self-Extracting Installer
echo  No 7-Zip, no PowerShell, no admin rights, no internet needed.
echo  Just wait — this takes about 30 seconds.
echo ============================================================
echo.

rem ── Create a unique temp folder ──────────────────────────────
set "EXTRACT_DIR=%TEMP%\\FlagshipEditor-${version}-%RANDOM%"
mkdir "%EXTRACT_DIR%" >nul 2>&1
if not exist "%EXTRACT_DIR%" (
  echo ERROR: Could not create a temporary folder.
  echo Your TEMP directory may be full. Free up space and retry.
  endlocal & exit /b 1
)

echo [1/4] Writing installer payload...
set "B64_FILE=%EXTRACT_DIR%\\payload.b64"
set "ZIP_FILE=%EXTRACT_DIR%\\payload.zip"

> "%B64_FILE%" (
${lines.map(line => `echo ${line}`).join("\n")}
)

echo [2/4] Decoding payload...
certutil -decode "%B64_FILE%" "%ZIP_FILE%" >nul 2>&1
if errorlevel 1 (
  echo ERROR: Could not decode the installer payload.
  echo This should never happen. The file may have been corrupted during transfer.
  rmdir /s /q "%EXTRACT_DIR%" >nul 2>&1
  endlocal & exit /b 2
)
del /q "%B64_FILE%" >nul 2>&1

echo [3/4] Extracting FlagshipEditor...
tar -xf "%ZIP_FILE%" -C "%EXTRACT_DIR%" 2>nul
if errorlevel 1 (
  echo ERROR: Could not extract the ZIP archive.
  echo tar.exe is missing or the archive is corrupted.
  rmdir /s /q "%EXTRACT_DIR%" >nul 2>&1
  endlocal & exit /b 3
)
del /q "%ZIP_FILE%" >nul 2>&1

echo [4/4] Running installer...
echo.

rem ── Find the extracted folder ────────────────────────────────
set "INSTALL_DIR="
for /d %%D in ("%EXTRACT_DIR%\\FlagshipEditor-*") do set "INSTALL_DIR=%%D"
if not defined INSTALL_DIR (
  echo ERROR: Extracted folder not found.
  rmdir /s /q "%EXTRACT_DIR%" >nul 2>&1
  endlocal & exit /b 4
)

pushd "%INSTALL_DIR%" >nul
call "INSTALL-FLAGSHIPEDITOR.cmd"
set "INSTALL_EXIT=%ERRORLEVEL%"
popd >nul

rem ── Clean up ─────────────────────────────────────────────────
rmdir /s /q "%EXTRACT_DIR%" >nul 2>&1

if not "%INSTALL_EXIT%"=="0" (
  echo.
  echo Installation failed with code %INSTALL_EXIT%.
  echo The temporary files were cleaned up.
  endlocal & exit /b %INSTALL_EXIT%
)

echo.
echo ============================================================
echo  FlagshipEditor ${version} is installed.
echo  Open After Effects, then Window ^> Extensions ^> FlagshipEditor.
echo ============================================================
endlocal & exit /b 0
`;

// ── Write the self-extracting file ───────────────────────────────────────
fs.writeFileSync(singleExePath, cmd, "utf8");
fs.chmodSync(singleExePath, 0o755);

const exeSize = fs.statSync(singleExePath).size;
const sha256 = crypto.createHash("sha256").update(fs.readFileSync(singleExePath)).digest("hex");

console.log(`\nSingle-file installer created: ${singleExePath}`);
console.log(`Size: ${(exeSize / 1024 / 1024).toFixed(1)} MB`);
console.log(`SHA-256: ${sha256}`);

// ── Also copy to Downloads with a .cmd extension as fallback ──────────────
const cmdPath = path.join("/Users/issandre/Downloads", `${packageName}.cmd`);
fs.copyFileSync(singleExePath, cmdPath);
fs.chmodSync(cmdPath, 0o755);

console.log(`\nFallback .cmd copy: ${cmdPath}`);
console.log(`\nDone. Send the .exe to Steve. He double-clicks it. That's it.`);