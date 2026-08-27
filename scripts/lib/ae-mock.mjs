// A recording mock of the After Effects scripting DOM.
//
// The point is that keyframes, effect parameters and layer ordering are all
// readable after a build, so the bridge tests can assert what the ExtendScript
// actually did rather than only that it did not throw.

export class MockProperty {
  constructor(name, initialValue, owner) {
    this.name = name;
    this.value = initialValue;
    this.owner = owner;
    this.keys = [];
    this.expression = "";
    this.interpolation = [];
    this.eases = [];
  }

  get numKeys() {
    return this.keys.length;
  }

  setValue(value) {
    this.value = value;
  }

  valueAtTime(time) {
    if (this.keys.length === 0) return this.value;
    let best = this.keys[0];
    for (const key of this.keys) {
      if (key.time <= time) best = key;
    }
    return best.value;
  }

  setValueAtTime(time, value) {
    if (!Number.isFinite(time)) {
      throw new Error(`${this.name}: keyframe time must be finite, received ${time}`);
    }
    const existing = this.keys.findIndex((key) => Math.abs(key.time - time) < 1e-9);
    if (existing >= 0) {
      this.keys[existing].value = value;
    } else {
      this.keys.push({ time, value });
      this.keys.sort((left, right) => left.time - right.time);
    }
    this.value = value;
  }

  removeKey(index) {
    if (index < 1 || index > this.keys.length) {
      throw new Error(`${this.name}: removeKey index ${index} is out of range`);
    }
    this.keys.splice(index - 1, 1);
  }

  keyTime(index) {
    return this.keys[index - 1].time;
  }

  keyValue(index) {
    return this.keys[index - 1].value;
  }

  setInterpolationTypeAtKey(index, inType, outType) {
    if (index < 1 || index > this.keys.length) {
      throw new Error(`${this.name}: setInterpolationTypeAtKey index ${index} is out of range`);
    }
    this.interpolation[index - 1] = { inType, outType };
  }

  setTemporalEaseAtKey(index, easeIn, easeOut) {
    if (index < 1 || index > this.keys.length) {
      throw new Error(`${this.name}: setTemporalEaseAtKey index ${index} is out of range`);
    }
    const dimensions = Array.isArray(this.value) ? this.value.length : 1;
    if (easeIn.length !== dimensions) {
      throw new Error(
        `${this.name}: temporal ease needs ${dimensions} value(s), received ${easeIn.length}`
      );
    }
    this.eases[index - 1] = { easeIn, easeOut };
  }
}

// Effect parameter layouts, indexed from 1 exactly as After Effects exposes
// them. An effect that is not listed here is treated as not installed, which is
// how the tests exercise the graceful-degradation paths.
const EFFECT_PARAMETERS = {
  "ADBE Shift Channels": ["Take Alpha From", "Take Red From", "Take Green From", "Take Blue From"],
  "ADBE Turbulent Displace": ["Displacement", "Amount", "Size", "Offset", "Complexity", "Evolution"],
  "ADBE Mosaic": ["Horizontal Blocks", "Vertical Blocks", "Sharp Colors"],
  "ADBE Camera Lens Blur": ["Blur Radius", "Iris Properties", "Blur Map"],
  "ADBE HUE SATURATION": [
    "Channel Control",
    "Channel Range",
    "Master Hue",
    "Master Saturation",
    "Master Lightness",
    "Colorize",
  ],
  "ADBE Linear Wipe": ["Transition Completion", "Wipe Angle", "Feather"],
  "ADBE Noise": ["Amount of Noise", "Use Color Noise", "Clip Result Values"],
  "ADBE Wave Warp": [
    "Wave Type",
    "Wave Height",
    "Wave Width",
    "Direction",
    "Wave Speed",
    "Pinning",
    "Phase",
    "Antialiasing",
  ],
  "ADBE Fractal Noise": [
    "Fractal Type",
    "Noise Type",
    "Invert",
    "Contrast",
    "Brightness",
    "Overflow",
    "Transform",
    "Complexity",
    "Sub Settings",
    "Evolution",
    "Evolution Options",
    "Opacity",
    "Blending Mode",
  ],
  "ADBE Glo2": [
    "Glow Based On",
    "Glow Threshold",
    "Glow Radius",
    "Glow Intensity",
    "Composite Original",
  ],
  "ADBE Gaussian Blur 2": ["Blurriness", "Blur Dimensions", "Repeat Edge Pixels"],
  "ADBE Ramp": ["Start of Ramp", "Start Color", "End of Ramp", "End Color", "Ramp Shape"],
  "ADBE Lumetri Color": [
    "Input LUT",
    "HDR White",
    "Auto Color",
    "Auto Contrast",
    "Auto Exposure",
    "White Balance",
    "Temperature",
    "Tint",
    "Exposure",
    "Contrast",
    "Saturation",
  ],
};

export class MockEffect {
  constructor(matchName) {
    this.matchName = matchName;
    this.parameterNames = EFFECT_PARAMETERS[matchName] || [];
    this.parameters = new Map();
  }

  property(key) {
    let index = -1;
    if (typeof key === "number") {
      index = key - 1;
    } else {
      const suffix = /-(\d{4})$/.exec(key);
      if (suffix) {
        const prefix = key.slice(0, suffix.index);
        if (prefix !== this.matchName) return null;
        index = parseInt(suffix[1], 10) - 1;
      } else {
        index = this.parameterNames.indexOf(key);
      }
    }
    if (index < 0 || index >= this.parameterNames.length) return null;
    const name = this.parameterNames[index];
    if (!this.parameters.has(name)) {
      this.parameters.set(name, new MockProperty(`${this.matchName}/${name}`, 0, this));
    }
    return this.parameters.get(name);
  }

  get(name) {
    const property = this.parameters.get(name);
    return property ? property.value : undefined;
  }

  keysOf(name) {
    const property = this.parameters.get(name);
    return property ? property.keys : [];
  }
}

class MockEffectParade {
  constructor(installedEffects) {
    this.effects = [];
    this.installedEffects = installedEffects;
  }

  canAddProperty(matchName) {
    return this.installedEffects.has(matchName);
  }

  addProperty(matchName) {
    if (!this.installedEffects.has(matchName)) {
      throw new Error(`Effect is not installed: ${matchName}`);
    }
    const effect = new MockEffect(matchName);
    this.effects.push(effect);
    return effect;
  }

  property(matchName) {
    return this.effects.find((effect) => effect.matchName === matchName) || null;
  }

  find(matchName) {
    return this.effects.filter((effect) => effect.matchName === matchName);
  }
}

const TRANSFORM_DEFAULTS = {
  "ADBE Position": () => [960, 540],
  "ADBE Scale": () => [100, 100],
  "ADBE Opacity": () => 100,
  "ADBE Rotate Z": () => 0,
  "ADBE Anchor Point": () => [960, 540],
};

export class MockLayer {
  constructor(comp, source, kind) {
    this.comp = comp;
    this.containingComp = comp;
    this.source = source;
    this.kind = kind;
    this.name = source && source.name ? source.name : kind;
    this.comment = "";
    this.startTime = 0;
    this.inPoint = 0;
    this.outPoint = comp.duration;
    this.enabled = true;
    this.motionBlur = false;
    this.threeDLayer = false;
    this.adjustmentLayer = false;
    this.blendingMode = 1;
    this.timeRemapEnabled = false;
    this.canSetTimeRemapEnabled = kind === "footage";
    this.removed = false;
    this._transform = new Map();
    this._effects = new MockEffectParade(comp.project.installedEffects);
    this._timeRemap = null;
    this._cameraOptions = new Map();
  }

  get effects() {
    return this._effects;
  }

  property(name) {
    if (name === "ADBE Effect Parade") return this._effects;
    if (name === "ADBE Transform Group") {
      return {
        property: (subName) => {
          if (!TRANSFORM_DEFAULTS[subName]) return null;
          if (this.kind === "camera" && subName === "ADBE Scale") return null;
          if (!this._transform.has(subName)) {
            this._transform.set(
              subName,
              new MockProperty(subName, TRANSFORM_DEFAULTS[subName](), this)
            );
          }
          return this._transform.get(subName);
        },
      };
    }
    if (name === "ADBE Camera Options Group") {
      return {
        property: (subName) => {
          if (!this._cameraOptions.has(subName)) {
            this._cameraOptions.set(subName, new MockProperty(subName, 0, this));
          }
          return this._cameraOptions.get(subName);
        },
      };
    }
    if (name === "ADBE Time Remapping") {
      if (!this.timeRemapEnabled) return null;
      if (!this._timeRemap) {
        // After Effects seeds time remapping with two keyframes.
        this._timeRemap = new MockProperty("ADBE Time Remapping", 0, this);
        const duration = this.source && this.source.duration ? this.source.duration : this.comp.duration;
        this._timeRemap.setValueAtTime(this.inPoint, 0);
        this._timeRemap.setValueAtTime(this.inPoint + duration, duration);
      }
      return this._timeRemap;
    }
    return null;
  }

  transform(name) {
    return this._transform.get(name) || null;
  }

  get timeRemap() {
    return this._timeRemap;
  }

  moveBefore(other) {
    const layers = this.comp.layerList;
    const from = layers.indexOf(this);
    if (from >= 0) layers.splice(from, 1);
    layers.splice(layers.indexOf(other), 0, this);
  }

  moveToBeginning() {
    const layers = this.comp.layerList;
    const from = layers.indexOf(this);
    if (from >= 0) layers.splice(from, 1);
    layers.unshift(this);
  }

  moveToEnd() {
    const layers = this.comp.layerList;
    const from = layers.indexOf(this);
    if (from >= 0) layers.splice(from, 1);
    layers.push(this);
  }

  replaceSource(newSource) {
    this.source = newSource;
  }

  remove() {
    this.removed = true;
    const layers = this.comp.layerList;
    const index = layers.indexOf(this);
    if (index >= 0) layers.splice(index, 1);
  }
}

export class MockCameraLayer extends MockLayer {}

export class MockItem {
  constructor(project, name, options = {}) {
    this.project = project;
    this.name = name;
    this.removed = false;
    this.parentFolder = null;
    Object.assign(this, options);
  }

  remove() {
    this.removed = true;
    const index = this.project.itemList.indexOf(this);
    if (index >= 0) this.project.itemList.splice(index, 1);
  }
}

export class MockComp extends MockItem {
  constructor(project, name, width, height, pixelAspect, duration, frameRate) {
    super(project, name);
    this.width = width;
    this.height = height;
    this.pixelAspect = pixelAspect;
    this.duration = duration;
    this.frameRate = frameRate;
    this.motionBlur = false;
    this.layerList = [];
    this.markers = [];
    this.openedInViewer = false;
    this.markerProperty = {
      setValueAtTime: (time, marker) => {
        this.markers.push({ time, comment: marker.comment });
      },
    };
    const comp = this;
    this.layers = {
      add(source) {
        const layer = new MockLayer(comp, source, "footage");
        layer.outPoint = source && source.duration ? source.duration : comp.duration;
        comp.layerList.unshift(layer);
        return layer;
      },
      addSolid(color, name, width, height, pixelAspect, duration) {
        const layer = new MockLayer(
          comp,
          { name, duration: duration ?? comp.duration, isSolid: true, color },
          "solid"
        );
        layer.name = name;
        layer.outPoint = duration ?? comp.duration;
        comp.layerList.unshift(layer);
        return layer;
      },
      addCamera(name, centerPoint) {
        const layer = new MockCameraLayer(comp, { name, centerPoint }, "camera");
        layer.name = name;
        comp.layerList.unshift(layer);
        return layer;
      },
      byName(name) {
        return comp.layerByName(name);
      },
    };
  }

  get numLayers() {
    return this.layerList.length;
  }

  layer(index) {
    return this.layerList[index - 1];
  }

  layerByName(name) {
    return this.layerList.find((layer) => layer.name === name) || null;
  }

  layersNamed(prefix) {
    return this.layerList.filter((layer) => String(layer.name).indexOf(prefix) === 0);
  }

  openInViewer() {
    this.openedInViewer = true;
  }
}

export class MockProject {
  constructor(installedEffects) {
    this.itemList = [];
    this.comps = [];
    this.importedPaths = [];
    this.installedEffects = new Set(installedEffects);
    const project = this;
    this.items = {
      addComp(name, width, height, pixelAspect, duration, frameRate) {
        const comp = new MockComp(project, name, width, height, pixelAspect, duration, frameRate);
        project.itemList.push(comp);
        project.comps.push(comp);
        return comp;
      },
      addFolder(name) {
        const folder = new MockItem(project, name, { isFolder: true });
        project.itemList.push(folder);
        return folder;
      },
    };
  }

  get numItems() {
    return this.itemList.length;
  }

  item(index) {
    return this.itemList[index - 1];
  }

  importFile(options) {
    const path = options.file.fsName;
    this.importedPaths.push(path);
    const isAudio = /\.(wav|mp3|aac|m4a)$/i.test(path);
    const item = new MockItem(this, path.split(/[\\/]/).pop(), {
      file: { fsName: path },
      duration: 8,
      hasVideo: !isAudio,
      width: isAudio ? 0 : 3840,
      height: isAudio ? 0 : 2160,
      frameRate: isAudio ? 0 : 23.976,
    });
    this.itemList.push(item);
    return item;
  }
}

export function createHostContext(options = {}) {
  const installedEffects =
    options.installedEffects ||
    Object.keys(EFFECT_PARAMETERS).filter((name) => name !== "ADBE Lumetri Color" || !options.withoutLumetri);
  const project = new MockProject(installedEffects);
  const undo = { depth: 0, maxDepth: 0, groups: [] };
  const existingFiles = new Set(options.existingFiles || []);

  function FileMock(filePath) {
    this.fsName = String(filePath);
    this.exists =
      !String(filePath).includes("missing") &&
      (existingFiles.size === 0 || existingFiles.has(String(filePath)) || !/\.cube$/i.test(filePath));
  }
  FileMock.openDialog = () => null;

  function FolderMock(folderPath) {
    this.fsName = String(folderPath);
    this.parent = null;
  }
  FolderMock.selectDialog = () => null;

  const context = {
    app: {
      version: "24.6",
      project,
      beginUndoGroup(name) {
        undo.depth += 1;
        undo.maxDepth = Math.max(undo.maxDepth, undo.depth);
        undo.groups.push(name);
      },
      endUndoGroup() {
        undo.depth -= 1;
        if (undo.depth < 0) throw new Error("endUndoGroup called without a matching beginUndoGroup");
      },
    },
    File: FileMock,
    Folder: FolderMock,
    ImportOptions: function ImportOptions(file) {
      this.file = file;
    },
    MarkerValue: function MarkerValue(comment) {
      this.comment = comment;
    },
    KeyframeInterpolationType: { LINEAR: 6612, BEZIER: 6613, HOLD: 6614 },
    KeyframeEase: function KeyframeEase(speed, influence) {
      if (!Number.isFinite(influence) || influence < 0.1 || influence > 100) {
        throw new Error(`KeyframeEase influence out of range: ${influence}`);
      }
      this.speed = speed;
      this.influence = influence;
    },
    BlendingMode: { NORMAL: 5012, ADD: 5002, SCREEN: 5017, MULTIPLY: 5013 },
    CompItem: MockComp,
    CameraLayer: MockCameraLayer,
    FootageItem: MockItem,
    $: { fileName: "/Applications/Extensions/FlagshipEditor/jsx/index.js" },
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
    parseFloat,
    parseInt,
  };

  return { context, project, undo, FileMock, FolderMock };
}

export function unwrap(raw, label) {
  const parsed = JSON.parse(raw);
  if (parsed.__error) {
    throw new Error(`${label} returned an error: ${parsed.__error}`);
  }
  return parsed.__result;
}

export function expectError(raw, label) {
  const parsed = JSON.parse(raw);
  if (!parsed.__error) {
    throw new Error(`${label} was expected to fail but returned: ${raw}`);
  }
  return parsed.__error;
}
