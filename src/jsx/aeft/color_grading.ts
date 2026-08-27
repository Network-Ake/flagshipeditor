// Color Grading — applies LUTs and colour correction through adjustment layers.

import { VFXContext, clamp, readNumber, reportWarning, toNumber, transformProperty } from "./vfx_utils";

var LUT_LAYER_PREFIX = "FlagshipEditor_LUT";
var LUMETRI_MATCH_NAMES = ["ADBE Lumetri Color", "ADBE Lumetri Color 2", "ADBE Lumetri"];

export function applyColorGrading(
  comp: any,
  sections: any[],
  config: any,
  context: VFXContext
): void {
  if (!config || config.enabled === false) return;
  var opacity = clamp(readNumber(config, ["opacity"], 100), 0, 100);
  var applied = 0;

  if (config.section_luts) {
    for (var i = 0; i < sections.length; i++) {
      var section = sections[i];
      var lutName = config.section_luts[section.type];
      if (!lutName) continue;
      var sectionLayer = createLUTAdjustmentLayer(
        comp,
        toNumber(section.start, 0),
        toNumber(section.end, 0) - toNumber(section.start, 0),
        String(lutName),
        opacity,
        config.extension_root,
        LUT_LAYER_PREFIX + "_" + String(section.type).toUpperCase(),
        context
      );
      if (sectionLayer) {
        applyColorParams(sectionLayer, config.params, context);
        applied++;
      }
    }
  }

  if (config.global_lut) {
    var globalLayer = createLUTAdjustmentLayer(
      comp,
      0,
      toNumber(comp.duration, 0),
      String(config.global_lut),
      opacity,
      config.extension_root,
      LUT_LAYER_PREFIX + "_GLOBAL",
      context
    );
    if (globalLayer) {
      applyColorParams(globalLayer, config.params, context);
      applied++;
    }
  }

  if (applied === 0 && (config.global_lut || config.section_luts)) {
    reportWarning(context, "Colour grading produced no graded layers");
  }
}

function findLUTFile(extensionRoot: string, lutName: string): any {
  // Folder() resolves the platform separators for us, so the same code works
  // for C:\... on Windows and /Users/... on macOS.
  var lutsFolder = new Folder(extensionRoot + "/luts");
  var candidate = new File(lutsFolder.fsName + "/" + lutName);
  if (candidate.exists) return candidate;
  var flat = new File(extensionRoot + "/luts/" + lutName);
  if (flat.exists) return flat;
  return null;
}

function createLUTAdjustmentLayer(
  comp: any,
  startTime: number,
  duration: number,
  lutName: string,
  opacity: number,
  extensionRoot: string,
  layerName: string,
  context: VFXContext
): any {
  if (!extensionRoot) {
    reportWarning(context, "Extension path unavailable; grading skipped: " + lutName);
    return null;
  }
  if (duration <= 0) return null;
  var lutFile = findLUTFile(extensionRoot, lutName);
  if (!lutFile) {
    reportWarning(context, "LUT not bundled; grading skipped: " + lutName);
    return null;
  }

  var solid: any = null;
  try {
    solid = comp.layers.addSolid([1, 1, 1], layerName, comp.width, comp.height, comp.pixelAspect, comp.duration);
    // Without this the "LUT layer" is an opaque white rectangle covering the
    // whole edit rather than a grade applied to the footage beneath it.
    solid.adjustmentLayer = true;
    solid.startTime = 0;
    solid.inPoint = startTime;
    solid.outPoint = Math.min(startTime + duration, toNumber(comp.duration, startTime + duration));
    solid.moveToBeginning();
  } catch (createError) {
    reportWarning(context, "Grading layer could not be created for " + lutName + ": " + String(createError));
    return null;
  }

  var opacityProperty = transformProperty(solid, "ADBE Opacity");
  if (opacityProperty) {
    try {
      opacityProperty.setValue(opacity);
    } catch (opacityError) {
      reportWarning(context, "Grading opacity could not be set for " + lutName + ": " + String(opacityError));
    }
  }

  var lumetri = addLumetri(solid, lutName, context);
  if (!lumetri) {
    removeLayer(solid, context);
    return null;
  }
  if (!setLUTPath(lumetri, lutFile, lutName, context)) {
    removeLayer(solid, context);
    return null;
  }
  return solid;
}

function addLumetri(layer: any, lutName: string, context: VFXContext): any {
  var parade: any = null;
  try {
    parade = layer.property("ADBE Effect Parade");
  } catch (paradeError) {
    reportWarning(context, "Grading skipped for " + lutName + ": " + String(paradeError));
    return null;
  }
  if (!parade) return null;
  for (var i = 0; i < LUMETRI_MATCH_NAMES.length; i++) {
    try {
      var effect = parade.addProperty(LUMETRI_MATCH_NAMES[i]);
      if (effect) return effect;
    } catch (addError) {
      // Try the next Lumetri match name for this After Effects version.
    }
  }
  reportWarning(context, "Lumetri Color is unavailable in this After Effects build; grading skipped: " + lutName);
  return null;
}

function setLUTPath(lumetri: any, lutFile: any, lutName: string, context: VFXContext): boolean {
  var candidates = ["ADBE Lumetri Color-0001", "ADBE Lumetri Color 2-0001"];
  for (var i = 0; i < candidates.length; i++) {
    try {
      var property = lumetri.property(candidates[i]);
      if (!property) continue;
      property.setValue(lutFile.fsName);
      return true;
    } catch (setError) {
      // Try the next parameter key.
    }
  }
  reportWarning(context, "Lumetri could not load the LUT file: " + lutName);
  return false;
}

function removeLayer(layer: any, context: VFXContext): void {
  try {
    layer.remove();
  } catch (removeError) {
    reportWarning(context, "An unused grading layer could not be removed: " + String(removeError));
  }
}

// Temperature, contrast and saturation are written to the LUT layer this call
// created, never to whatever happens to sit at the top of the comp.
function applyColorParams(layer: any, params: any, context: VFXContext): void {
  if (!params) return;
  var parade: any = null;
  try {
    parade = layer.property("ADBE Effect Parade");
  } catch (paradeError) {
    reportWarning(context, "Colour parameters skipped: " + String(paradeError));
    return;
  }
  if (!parade) return;

  var lumetri: any = null;
  for (var i = 0; i < LUMETRI_MATCH_NAMES.length; i++) {
    try {
      lumetri = parade.property(LUMETRI_MATCH_NAMES[i]);
      if (lumetri) break;
    } catch (lookupError) {
      // Try the next Lumetri match name.
    }
  }
  if (!lumetri) {
    reportWarning(context, "Colour parameters skipped: the grading layer has no Lumetri effect");
    return;
  }

  setLumetriParam(lumetri, ["ADBE Lumetri Color-0007", 7], params.temperature_k, "temperature", context);
  setLumetriParam(lumetri, ["ADBE Lumetri Color-0010", 10], params.contrast, "contrast", context);
  setLumetriParam(lumetri, ["ADBE Lumetri Color-0011", 11], params.saturation, "saturation", context);
}

function setLumetriParam(
  lumetri: any,
  keys: any[],
  value: any,
  label: string,
  context: VFXContext
): void {
  if (value === undefined || value === null) return;
  var numeric = toNumber(value, NaN);
  if (isNaN(numeric)) return;
  for (var i = 0; i < keys.length; i++) {
    try {
      var property = lumetri.property(keys[i]);
      if (!property) continue;
      property.setValue(numeric);
      return;
    } catch (setError) {
      // Try the next parameter key.
    }
  }
  reportWarning(context, "Colour " + label + " is unavailable in this After Effects build");
}
