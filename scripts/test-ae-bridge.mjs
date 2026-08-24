import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";

const root = process.cwd();
const packageVersion = JSON.parse(fs.readFileSync(path.join(root, "package.json"), "utf8")).version;
const bundlePath = path.join(root, "dist", "cep", "jsx", "index.js");
const source = fs.readFileSync(bundlePath, "utf8");
const importedPaths = [];
const comps = [];
let undoDepth = 0;
let maxUndoDepth = 0;

function removableItem(extra = {}) {
  return {
    removed: false,
    remove() { this.removed = true; },
    ...extra,
  };
}

function makeComp(name, duration) {
  const layers = [];
  const comp = removableItem({
    name,
    duration,
    width: 1920,
    height: 1080,
    pixelAspect: 1,
    layers: {
      add(item) {
        const layer = {
          source: item,
          startTime: 0,
          outPoint: duration,
          name: "",
          comment: "",
          timeRemapEnabled: false,
          timeRemapKeys: [],
          motionBlur: false,
          blendingMode: 0,
          property(name) {
            if (name === "ADBE Time Remapping") {
              if (!this.timeRemapEnabled) return null;
              const keys = this.timeRemapKeys;
              return { setValueAtTime(time, value) { keys.push([time, value]); } };
            }
            if (name === "ADBE Effect Parade") {
              return {
                addProperty(effectName) {
                  return {
                    property(propName) {
                      return { setValue() {}, setValueAtTime() {} };
                    },
                  };
                },
              };
            }
            if (name === "ADBE Transform Group") {
              return {
                property(subName) {
                  if (subName === "ADBE Opacity") return { setValueAtTime() {}, setValue() {} };
                  if (subName === "ADBE Position") return { valueAtTime() { return [0, 0]; }, setValueAtTime() {} };
                  if (subName === "ADBE Scale") return { setValueAtTime() {}, valueAtTime() { return [100, 100]; } };
                  if (subName === "ADBE Rotate Z") return { setValueAtTime() {} };
                  return null;
                },
              };
            }
            return null;
          },
        };
        layers.push(layer);
        return layer;
      },
      addSolid() {
        const solid = {
          source: { name: 'solid' },
          startTime: 0,
          outPoint: duration,
          name: '',
          comment: '',
          threeDLayer: false,
          blendingMode: 0,
          motionBlur: false,
          property(name) {
            if (name === 'ADBE Transform Group') {
              return {
                property(subName) {
                  if (subName === 'ADBE Opacity') return { setValueAtTime() {}, setValue() {} };
                  if (subName === 'ADBE Position') return { valueAtTime() { return [0, 0]; }, setValueAtTime() {} };
                  if (subName === 'ADBE Scale') return { setValueAtTime() {} };
                  if (subName === 'ADBE Rotate Z') return { setValueAtTime() {} };
                  return null;
                },
              };
            }
            if (name === 'ADBE Effect Parade') {
              return {
                addProperty(effectName) {
                  return {
                    property(propName) {
                      return { setValue() {}, setValueAtTime() {} };
                    },
                  };
                },
              };
            }
            return null;
          },
          moveToStart() {},
          moveToEnd() {},
        };
        layers.push(solid);
        return solid;
      },
      addCamera() {
        const camera = {
          property(name) {
            if (name === 'ADBE Camera Options Group') {
              return { property() { return { setValue() {} }; } };
            }
            if (name === 'ADBE Transform Group') {
              return { property() { return { expression: '', setValue() {}, setValueAtTime() {} }; } };
            }
            return null;
          },
        };
        layers.push(camera);
        return camera;
      },
    },
    markerProperty: { setValueAtTime() {} },
    openInViewer() {},
    testLayers: layers,
  });
  comps.push(comp);
  return comp;
}

function FileMock(filePath) {
  this.fsName = filePath;
  this.exists = !String(filePath).includes("missing");
}
FileMock.openDialog = () => null;

function FolderMock(folderPath) {
  this.fsName = folderPath;
}
FolderMock.selectDialog = () => null;

const context = {
  app: {
    version: "24.6",
    beginUndoGroup(_name) {
      undoDepth += 1;
      maxUndoDepth = Math.max(maxUndoDepth, undoDepth);
    },
    endUndoGroup() {
      undoDepth -= 1;
      if (undoDepth < 0) throw new Error("endUndoGroup called without a matching beginUndoGroup");
    },
    project: {
      items: {
        addComp(name, _width, _height, _pixelAspect, duration) {
          return makeComp(name, duration);
        },
        addFolder(name) { return removableItem({ name }); },
      },
      importFile(options) {
        importedPaths.push(options.file.fsName);
        return removableItem({ path: options.file.fsName });
      },
    },
  },
  File: FileMock,
  Folder: FolderMock,
  ImportOptions: function ImportOptions(file) { this.file = file; },
  MarkerValue: function MarkerValue(comment) { this.comment = comment; },
  Math,
  Date,
  JSON,
  String,
  Number,
  Boolean,
  Object,
  Array,
  Error,
  SyntaxError,
  isFinite,
  isNaN,
};
vm.createContext(context);
vm.runInContext(source, context, { filename: bundlePath });

for (const name of ["getBridgeHealth", "beginComp", "appendCutBatch", "finishComp", "abortComp"]) {
  assert.equal(typeof context[name], "function", `Missing compiled AE bridge function: ${name}`);
}

FileMock.openDialog = (_prompt, _filter, multiSelect) => {
  if (!multiSelect) return null;
  const single = new FileMock("C:/media/single.mov");
  single.length = 987654;
  return single;
};
assert.deepEqual(
  JSON.parse(context.openFilesDialog("Video files:*.mov;*.mp4;*.m4v,All files:*.*")),
  ["C:/media/single.mov"],
  "A one-file multi-select result must not collapse to an empty list",
);
FileMock.openDialog = () => [
  new FileMock("C:/media/first.mov"),
  new FileMock("C:/media/second.mp4"),
];
assert.deepEqual(
  JSON.parse(context.openFilesDialog("Video files:*.mov;*.mp4;*.m4v,All files:*.*")),
  ["C:/media/first.mov", "C:/media/second.mp4"],
  "A multi-file selection must preserve every selected path",
);
FileMock.openDialog = () => null;
assert.deepEqual(JSON.parse(context.openFilesDialog("All files:*.*")), []);
FolderMock.selectDialog = () => new FolderMock("C:/media/library");
assert.equal(context.openFolderDialog(), "C:/media/library");
FolderMock.selectDialog = () => null;
assert.equal(context.openFolderDialog(), "null");

const bridgeHealth = JSON.parse(context.getBridgeHealth()).__result;
assert.deepEqual(
  bridgeHealth,
  {
    appId: "com.akestudio.flagshipeditor.bridge",
    version: packageVersion,
    hostName: "After Effects",
    hostVersion: "24.6",
  },
  "Bridge health must use documented host data and expose the exact runtime identity",
);

const style = {
  style_name: "test",
  display_name: "Test",
  cut_strategy: {},
  zoom_punch: { enabled: false },
  whip_pan: { enabled: false },
  camera_shake: { enabled: false },
  glitch_effect: { enabled: false },
  color_grading: { enabled: false },
  element_3d: { enabled: false },
  freeze_frame: { enabled: true },
  film_grain: { enabled: true },
};
const params = {
  cutIntensity: 5,
  vfxIntensity: 0,
  colorGrading: 0,
  zoomPunch: false,
  whipPan: false,
  cameraShake: false,
  glitch: false,
  element3d: false,
};
const element3D = { parallaxDepth: 0, autoCamera: false };
const sections = [{ type: "verse", start: 0, end: 12 }];

let result = JSON.parse(context.beginComp(12, "C:/media/song.wav", style, params, element3D, sections, "C:/extension"));
assert.equal(result.__result.started, true);
result = JSON.parse(context.appendCutBatch([
  { beatTime: 0, endTime: 4, clipPath: "C:/media/a.mov", clipName: "a.mov", sectionType: "verse" },
  { beatTime: 4, endTime: 8, clipPath: "C:/media/b.mov", clipName: "b.mov", sectionType: "verse" },
  { beatTime: 8, endTime: 12, clipPath: "C:/media/a.mov", clipName: "a.mov", sectionType: "verse" },
]));
assert.equal(result.__result.added, 3);
result = JSON.parse(context.finishComp());
assert.equal(result.__result.clipsAdded, 3);
assert.ok(!result.__result.warnings.some((warning) => warning.includes("film_grain")),
  "film_grain is implemented and must not be reported as unsupported");
assert.ok(!result.__result.warnings.some((warning) => warning.includes("freeze_frame")),
  "freeze_frame is implemented and must not be reported as unsupported");
assert.ok(!result.__result.warnings.some((warning) => warning.includes("VFX skipped")),
  "Implemented VFX must run against the After Effects API, not fail into a warning");
assert.ok(comps[0].testLayers.slice(1).every((layer) => layer.timeRemapKeys.length === 2),
  "freeze_frame must write the two time-remap keyframes on every clip layer");
assert.equal(comps[0].testLayers.length, 4, "Expected one music layer and three clip layers");
assert.equal(importedPaths.length, 3, "Expected one music import and two unique footage imports");
assert.equal(maxUndoDepth, 1, "The build must open exactly one undo group");
assert.equal(undoDepth, 0, "finishComp must close the undo group it opened");

result = JSON.parse(context.beginComp(4, "C:/media/song.wav", style, params, element3D, sections, "C:/extension"));
assert.equal(result.__result.started, true);
result = JSON.parse(context.appendCutBatch([
  { beatTime: 0, endTime: 4, clipPath: "C:/media/missing.mov", clipName: "missing.mov", sectionType: "verse" },
]));
assert.equal(result.__result.added, 0);
result = JSON.parse(context.finishComp());
assert.match(result.__error, /could not import any selected clips/i);
assert.equal(comps[1].removed, true, "A zero-clip composition must be rolled back");
assert.equal(undoDepth, 0, "A rolled-back build must close its undo group");

context.beginComp(4, "C:/media/song.wav", style, params, element3D, sections, "C:/extension");
JSON.parse(context.abortComp());
assert.equal(undoDepth, 0, "abortComp must close the undo group it opened");

console.log("Compiled After Effects bridge simulation passed (3 layers, 2 unique footage imports, zero-layer rollback, balanced undo groups). ");
