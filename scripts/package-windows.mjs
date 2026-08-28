import crypto from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { execFileSync } from "node:child_process";

const root = process.cwd();
const packageJson = JSON.parse(fs.readFileSync(path.join(root, "package.json"), "utf8"));
const version = packageJson.version;
const packageName = `FlagshipEditor-${version}-Windows`;
const buildRoot = path.join(root, ".build", "windows");
const stage = path.join(buildRoot, packageName);
const zipPath = path.join(root, "flagshipeditor.zip");
const downloadsPath = path.join("/Users/issandre/Downloads", `${packageName}.zip`);
const cacheDir = path.join(os.tmpdir(), "flagshipeditor-windows-runtime-cache");

execFileSync(process.execPath, [path.join(root, "scripts", "generate-luts.mjs")], {
  cwd: root,
  stdio: "inherit",
});

const pythonArchive = {
  url: "https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip",
  file: path.join(cacheDir, "python-3.12.10-embed-amd64.zip"),
  sha256: "4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3",
};
const ffmpegArchive = {
  url: "https://www.gyan.dev/ffmpeg/builds/packages/ffmpeg-9.0.1-essentials_build.zip",
  file: path.join(cacheDir, "ffmpeg-9.0.1-essentials_build.zip"),
  sha256: "fec81ae03971d9dd4be3ebe02e263bd2ec1d789483f931bdba5f5715e65da2e9",
};

function sha256(file) {
  return crypto.createHash("sha256").update(fs.readFileSync(file)).digest("hex");
}

function downloadVerified(archive) {
  fs.mkdirSync(cacheDir, { recursive: true });
  if (!fs.existsSync(archive.file) || sha256(archive.file) !== archive.sha256) {
    fs.rmSync(archive.file, { force: true });
    execFileSync("curl", ["-fL", archive.url, "-o", archive.file], { stdio: "inherit" });
  }
  const actualHash = sha256(archive.file);
  if (actualHash !== archive.sha256) {
    throw new Error(`Archive checksum mismatch for ${archive.file}: ${actualHash}`);
  }
}

function findFile(directory, filename) {
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    const candidate = path.join(directory, entry.name);
    if (entry.isDirectory()) {
      const nested = findFile(candidate, filename);
      if (nested) return nested;
    } else if (entry.name.toLowerCase() === filename.toLowerCase()) {
      return candidate;
    }
  }
  return null;
}

function walkFiles(directory) {
  const files = [];
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    const candidate = path.join(directory, entry.name);
    if (entry.isDirectory()) files.push(...walkFiles(candidate));
    else files.push(candidate);
  }
  return files;
}

fs.rmSync(stage, { recursive: true, force: true });
fs.mkdirSync(stage, { recursive: true });

for (const [source, destination] of [
  ["dist/cep", "dist/cep"],
  ["engine", "engine"],
  ["styles", "styles"],
  ["luts", "luts"],
  ["scripts/Start-FlagshipEditor-Backend.cmd", "scripts/Start-FlagshipEditor-Backend.cmd"],
  ["INSTALL-FLAGSHIPEDITOR.cmd", "INSTALL-FLAGSHIPEDITOR.cmd"],
]) {
  const from = path.join(root, source);
  const to = path.join(stage, destination);
  if (!fs.existsSync(from)) throw new Error(`Windows package input is missing: ${from}`);
  fs.mkdirSync(path.dirname(to), { recursive: true });
  fs.cpSync(from, to, {
    recursive: true,
    filter: (item) => !item.includes(`${path.sep}.venv`) && !item.includes(`${path.sep}__pycache__`),
  });
}
fs.writeFileSync(path.join(stage, "engine", "VERSION"), `${version}\n`);

downloadVerified(pythonArchive);
const portablePython = path.join(stage, "runtime", "python");
fs.mkdirSync(portablePython, { recursive: true });
execFileSync("unzip", ["-q", pythonArchive.file, "-d", portablePython]);
fs.mkdirSync(path.join(portablePython, "Lib", "site-packages"), { recursive: true });
execFileSync("python3", [
  "-m", "pip", "install", "--disable-pip-version-check", "--no-compile", "--ignore-installed",
  "--target", path.join(portablePython, "Lib", "site-packages"),
  "--platform", "win_amd64", "--implementation", "cp", "--python-version", "3.12", "--abi", "cp312",
  "--only-binary=:all:", "--requirement", path.join(root, "engine", "requirements-windows.lock"),
], { stdio: "inherit" });
fs.writeFileSync(path.join(portablePython, "python312._pth"), "python312.zip\n.\nLib\\site-packages\nimport site\n");

downloadVerified(ffmpegArchive);
const ffmpegExtractDir = path.join(cacheDir, "ffmpeg-9.0.1-extracted");
fs.rmSync(ffmpegExtractDir, { recursive: true, force: true });
fs.mkdirSync(ffmpegExtractDir, { recursive: true });
execFileSync("unzip", ["-q", ffmpegArchive.file, "-d", ffmpegExtractDir]);
const runtimeBin = path.join(stage, "runtime", "bin");
fs.mkdirSync(runtimeBin, { recursive: true });
for (const executable of ["ffmpeg.exe", "ffprobe.exe"]) {
  const source = findFile(ffmpegExtractDir, executable);
  if (!source) throw new Error(`${executable} is missing from the verified FFmpeg archive.`);
  fs.copyFileSync(source, path.join(runtimeBin, executable));
}
// The ProRes fixtures the installer's self-test decodes are committed media,
// copied in with the rest of `engine/` above. They used to be re-synthesised
// here with whatever `ffmpeg` sat on the build machine, which made the payload
// depend on the builder and left a source checkout with no fixtures at all —
// `engine/self_test.py` could not run outside a package. Verify the staged
// bytes against the committed manifest instead, and fail the build closed.
const fixtureDirectory = path.join(stage, "engine", "fixtures");
const fixtureManifest = JSON.parse(
  fs.readFileSync(path.join(root, "engine", "fixtures", "manifest.json"), "utf8"),
);
for (const entry of fixtureManifest.fixtures) {
  const sourceFixture = path.join(root, "engine", "fixtures", entry.file);
  const stagedFixture = path.join(fixtureDirectory, entry.file);
  if (!fs.existsSync(sourceFixture)) {
    throw new Error(
      `Packaged media fixture is missing from the source tree: engine/fixtures/${entry.file}. ` +
      `Run "npm run generate:fixtures".`,
    );
  }
  if (!fs.existsSync(stagedFixture)) {
    throw new Error(`Packaged media fixture did not reach the stage: engine/fixtures/${entry.file}`);
  }
  const stagedHash = sha256(stagedFixture);
  if (stagedHash !== entry.sha256) {
    throw new Error(
      `Staged fixture engine/fixtures/${entry.file} does not match the committed manifest ` +
      `(${stagedHash} != ${entry.sha256}). Regenerate with "npm run generate:fixtures".`,
    );
  }
}
fs.writeFileSync(path.join(stage, "runtime", "THIRD-PARTY-NOTICES.txt"), [
  "Python 3.12.10 embeddable runtime — Python Software Foundation License",
  "Source: https://www.python.org/ftp/python/3.12.10/",
  "",
  "FFmpeg 9.0.1 essentials build — GPLv3",
  "Binary source: https://www.gyan.dev/ffmpeg/builds/",
  "Corresponding source: https://github.com/FFmpeg/FFmpeg/tree/n9.0.1",
  "",
].join("\n"));

const checksumRoots = ["dist/cep", "engine", "styles", "luts", "runtime"];
const checksums = checksumRoots.flatMap((relativeRoot) => {
  const absoluteRoot = path.join(stage, relativeRoot);
  return walkFiles(absoluteRoot).map((file) => ({
    path: path.relative(stage, file).split(path.sep).join("/"),
    sha256: sha256(file),
  }));
}).sort((a, b) => a.path.localeCompare(b.path));
fs.writeFileSync(path.join(stage, "payload-checksums.json"), `${JSON.stringify(checksums, null, 2)}\n`);

// Validate the exact staged tree before any deliverable is created. Packaging must
// fail closed: a structurally incomplete or version-drifted build is never copied
// to Downloads.
execFileSync(process.execPath, [path.join(root, "scripts", "test-windows-package.mjs")], {
  cwd: root,
  stdio: "inherit",
});

for (const target of [zipPath, downloadsPath]) fs.rmSync(target, { force: true });
execFileSync("/usr/bin/zip", ["-q", "-r", zipPath, packageName], { cwd: buildRoot });
fs.copyFileSync(zipPath, downloadsPath);
execFileSync("/usr/bin/unzip", ["-tq", downloadsPath], { stdio: "inherit" });

console.log(`Windows package created: ${zipPath}`);
console.log(`Download copy created: ${downloadsPath}`);
console.log(`SHA-256: ${sha256(downloadsPath)}`);
