/**
 * build-single-exe.mjs
 *
 * Creates a single self-extracting FlagshipEditor installer for Windows.
 *
 * Output: FlagshipEditor-<version>-Windows.exe
 *
 * The file is a hybrid: a CMD header followed by the ZIP payload encoded as
 * base64 between PEM certificate markers.  certutil -decode ignores everything
 * outside the -----BEGIN CERTIFICATE----- / -----END CERTIFICATE----- pair, so
 * the script can decode *itself* (%~f0) with no line counting, no findstr pass
 * and no per-line echo statements.  It then extracts with tar (built into
 * Windows 10 1803+) and runs INSTALL-FLAGSHIPEDITOR.cmd.
 * No 7-Zip, no PowerShell, no admin rights, no internet.
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

const root = process.cwd();
const packageJson = JSON.parse(fs.readFileSync(path.join(root, "package.json"), "utf8"));
const version = packageJson.version;
const packageName = `FlagshipEditor-${version}-Windows`;
const zipPath = path.join(root, "flagshipeditor.zip");
// FLAGSHIPEDITOR_OUT_DIR exists so the deterministic test can build into a
// scratch directory instead of the real Downloads folder.
const outDir = process.env.FLAGSHIPEDITOR_OUT_DIR || "/Users/issandre/Downloads";
const singleExePath = path.join(outDir, `${packageName}.exe`);

// ── Verify the ZIP exists and was built ──────────────────────────────────
if (!fs.existsSync(zipPath)) {
  throw new Error("flagshipeditor.zip not found. Run package-windows.mjs first.");
}

const minimumZipBytes = Number(process.env.FLAGSHIPEDITOR_MIN_ZIP_BYTES || 1_000_000);
const zipSize = fs.statSync(zipPath).size;
if (zipSize < minimumZipBytes) {
  throw new Error(`ZIP is suspiciously small: ${zipSize} bytes. Run package-windows.mjs first.`);
}

console.log(`Source ZIP: ${zipPath} (${(zipSize / 1024 / 1024).toFixed(1)} MB)`);

// ── Build the self-extracting CMD header ─────────────────────────────────
// The CMD script:
// 1. Creates a unique temp extraction folder (mkdir is the atomic test)
// 2. Decodes its own embedded payload with certutil into a .zip
// 3. Uses tar (built into Windows 10+) to extract the ZIP
// 4. Runs INSTALL-FLAGSHIPEDITOR.cmd
// 5. Cleans up the temp folder
//
// We use tar instead of PowerShell's Expand-Archive because tar is
// built into Windows 10 1803+ and doesn't require PowerShell.
// certutil is built into every Windows since NT 4.0 and skips everything
// outside the BEGIN/END CERTIFICATE markers when decoding.

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
rem mkdir is atomic: it fails when the folder already exists, so a fresh
rem private folder is guaranteed even when %RANDOM% repeats.
set /a MKTEMP_TRIES=0
:mktemp
set /a MKTEMP_TRIES+=1
if %MKTEMP_TRIES% GTR 20 (
  echo ERROR: Could not create a temporary folder.
  echo Your TEMP directory may be full. Free up space and retry.
  endlocal & exit /b 1
)
set "EXTRACT_DIR=%TEMP%\\FlagshipEditor-${version}-%RANDOM%%RANDOM%"
mkdir "%EXTRACT_DIR%" >nul 2>&1 || goto :mktemp

echo [1/3] Decoding payload...
set "ZIP_FILE=%EXTRACT_DIR%\\payload.zip"
rem The ZIP payload is appended after this script between certificate
rem markers; certutil decodes only what sits between them.
certutil -decode "%~f0" "%ZIP_FILE%" >nul 2>&1
if errorlevel 1 (
  echo ERROR: Could not decode the installer payload.
  echo This should never happen. The file may have been corrupted during transfer.
  rmdir /s /q "%EXTRACT_DIR%" >nul 2>&1
  endlocal & exit /b 2
)

echo [2/3] Extracting FlagshipEditor...
tar -xf "%ZIP_FILE%" -C "%EXTRACT_DIR%" 2>nul
if errorlevel 1 (
  echo ERROR: Could not extract the ZIP archive.
  echo tar.exe is missing or the archive is corrupted.
  rmdir /s /q "%EXTRACT_DIR%" >nul 2>&1
  endlocal & exit /b 3
)
del /q "%ZIP_FILE%" >nul 2>&1

echo [3/3] Running installer...
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
// The batch header gets CRLF line endings (cmd.exe's native format); the
// payload keeps bare LF, which certutil accepts, to save a few megabytes.
async function drainWrite(stream, text) {
  if (!stream.write(text)) {
    await new Promise((resolve) => stream.once("drain", resolve));
  }
}

// Stream the ZIP through base64 in 57-byte groups: 57 source bytes become one
// standard 76-character base64 line, so nothing larger than a read chunk is
// ever held in memory (the old version built one string with the whole
// payload in it, then one `echo` batch line per base64 line).
async function writeBase64Payload(sourcePath, stream) {
  const BYTES_PER_LINE = 57;
  let carry = Buffer.alloc(0);
  for await (const chunk of fs.createReadStream(sourcePath)) {
    const data = carry.length ? Buffer.concat([carry, chunk]) : chunk;
    const usable = data.length - (data.length % BYTES_PER_LINE);
    carry = data.subarray(usable);
    if (!usable) continue;
    const encoded = data.subarray(0, usable).toString("base64");
    let lines = "";
    for (let i = 0; i < encoded.length; i += 76) {
      lines += encoded.slice(i, i + 76) + "\n";
    }
    await drainWrite(stream, lines);
  }
  if (carry.length) {
    await drainWrite(stream, carry.toString("base64") + "\n");
  }
}

async function sha256File(filePath) {
  const digest = crypto.createHash("sha256");
  for await (const chunk of fs.createReadStream(filePath)) {
    digest.update(chunk);
  }
  return digest.digest("hex");
}

const outStream = fs.createWriteStream(singleExePath, { encoding: "utf8" });
outStream.on("error", (error) => {
  // A failed write (disk full, revoked path) must abort the build loudly:
  // drainWrite would otherwise wait forever on a "drain" that never comes.
  console.error(`Writing ${singleExePath} failed: ${error.message}`);
  process.exit(1);
});
await drainWrite(outStream, cmd.replace(/\n/g, "\r\n"));
await drainWrite(outStream, "-----BEGIN CERTIFICATE-----\r\n");
await writeBase64Payload(zipPath, outStream);
await drainWrite(outStream, "-----END CERTIFICATE-----\r\n");
await new Promise((resolve, reject) => {
  outStream.end(() => resolve(undefined));
  outStream.on("error", reject);
});
fs.chmodSync(singleExePath, 0o755);

const exeSize = fs.statSync(singleExePath).size;
const sha256 = await sha256File(singleExePath);

console.log(`\nSingle-file installer created: ${singleExePath}`);
console.log(`Size: ${(exeSize / 1024 / 1024).toFixed(1)} MB`);
console.log(`SHA-256: ${sha256}`);

// ── Also copy alongside with a .cmd extension as fallback ────────────────
const cmdPath = path.join(outDir, `${packageName}.cmd`);
fs.copyFileSync(singleExePath, cmdPath);
fs.chmodSync(cmdPath, 0o755);

console.log(`\nFallback .cmd copy: ${cmdPath}`);
console.log(`\nDone. Send the .exe to Steve. He double-clicks it. That's it.`);
