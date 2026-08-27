// Deterministic regression test for build-single-exe.mjs.
//
// Builds a self-extracting installer from a small fixture payload and proves
// the properties the Windows host relies on: a CRLF batch header with an
// atomic temp-folder loop, exactly one PEM marker pair, certutil-compatible
// 76-character base64 lines, and a payload that decodes bit-identically back
// to the source ZIP.  Running certutil/tar for real remains a Windows-only
// check.

import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptsDir = path.dirname(fileURLToPath(import.meta.url));
const buildScript = path.join(scriptsDir, "build-single-exe.mjs");

const fixture = fs.mkdtempSync(path.join(os.tmpdir(), "flagship-single-exe-"));
try {
  const outDir = path.join(fixture, "out");
  fs.mkdirSync(outDir);
  fs.writeFileSync(
    path.join(fixture, "package.json"),
    JSON.stringify({ name: "fixture", version: "9.9.9" }),
    "utf8"
  );

  // 123457 bytes: not a multiple of 57 (exercises the streaming carry) and
  // not a multiple of 3 (exercises base64 padding on the final line).
  const payload = Buffer.alloc(123457);
  for (let i = 0; i < payload.length; i++) payload[i] = i % 251;
  fs.writeFileSync(path.join(fixture, "flagshipeditor.zip"), payload);

  execFileSync(process.execPath, [buildScript], {
    cwd: fixture,
    stdio: "pipe",
    env: {
      ...process.env,
      FLAGSHIPEDITOR_OUT_DIR: outDir,
      FLAGSHIPEDITOR_MIN_ZIP_BYTES: "1000",
    },
  });

  const exePath = path.join(outDir, "FlagshipEditor-9.9.9-Windows.exe");
  const cmdPath = path.join(outDir, "FlagshipEditor-9.9.9-Windows.cmd");
  const built = fs.readFileSync(exePath, "latin1");

  const beginMarker = "-----BEGIN CERTIFICATE-----\r\n";
  const endMarker = "-----END CERTIFICATE-----\r\n";
  const beginAt = built.indexOf(beginMarker);
  const endAt = built.indexOf(endMarker);
  assert.ok(beginAt > 0, "installer has a payload BEGIN marker");
  assert.ok(endAt > beginAt, "installer has a payload END marker after BEGIN");
  assert.equal(built.indexOf("CERTIFICATE"), beginAt + 11, "no marker text before the payload");
  assert.equal(endAt + endMarker.length, built.length, "nothing follows the END marker");

  const header = built.slice(0, beginAt);
  for (const line of header.split("\r\n")) {
    assert.ok(!line.includes("\n"), "batch header lines all end with CRLF");
  }
  assert.ok(header.includes('certutil -decode "%~f0"'), "batch decodes itself via certutil");
  assert.ok(header.includes("%RANDOM%%RANDOM%"), "temp folder name uses stacked RANDOM values");
  assert.ok(/mkdir "%EXTRACT_DIR%" >nul 2>&1 \|\| goto :mktemp/.test(header), "mkdir is the atomic uniqueness test");
  assert.ok(header.includes("MKTEMP_TRIES"), "temp folder loop is bounded");
  assert.ok(!header.includes("findstr"), "no findstr self-filtering pass remains");
  assert.ok(!/\bmore \+/.test(header), "no line-skipping `more` pass remains");
  assert.ok(!/^echo [A-Za-z0-9+/]{60,}/m.test(header), "payload is not embedded as echo lines");

  const base64Lines = built.slice(beginAt + beginMarker.length, endAt).split("\n").filter(Boolean);
  for (const [index, line] of base64Lines.entries()) {
    assert.ok(line.length <= 76, `base64 line ${index} fits certutil's width`);
    if (index < base64Lines.length - 1) {
      assert.equal(line.length, 76, `base64 line ${index} is a full 76-character line`);
    }
  }
  const decoded = Buffer.from(base64Lines.join(""), "base64");
  assert.ok(decoded.equals(payload), "payload decodes bit-identically to the source ZIP");

  assert.ok(fs.readFileSync(cmdPath).equals(fs.readFileSync(exePath)), ".cmd fallback is identical");

  console.log("build-single-exe regression test passed (markers, header, payload round-trip).");
} finally {
  fs.rmSync(fixture, { recursive: true, force: true });
}
