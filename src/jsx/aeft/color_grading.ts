// Color Grading — Apply LUTs and color correction by section

export function applyColorGrading(comp: any, sections: any[], config: any): string[] {
  var warnings: string[] = [];
  if (config.enabled === false) return warnings;

  // If section LUTs are defined, create adjustment layers per section
  if (config.section_luts) {
    for (var i = 0; i < sections.length; i++) {
      var section = sections[i];
      var lutName = config.section_luts[section.type];
      if (lutName) {
        var sectionWarning = createLUTAdjustmentLayer(
          comp,
          section.start,
          section.end - section.start,
          lutName,
          config.opacity,
          config.extension_root
        );
        if (sectionWarning) warnings.push(sectionWarning);
      }
    }
  }

  // If global LUT, create one adjustment layer for the whole comp
  if (config.global_lut) {
    var globalWarning = createLUTAdjustmentLayer(
      comp,
      0,
      comp.duration,
      config.global_lut,
      config.opacity,
      config.extension_root
    );
    if (globalWarning) warnings.push(globalWarning);

    // Apply additional params if defined
    if (!globalWarning && config.params) {
      applyColorParams(comp, config.params);
    }
  }
  return uniqueStrings(warnings);
}

function createLUTAdjustmentLayer(
  comp: any,
  startTime: number,
  duration: number,
  lutName: string,
  opacity: number,
  extensionRoot: string
): string | null {
  if (!extensionRoot) return "Extension path unavailable; grading skipped: " + lutName;
  // Cross-platform path: use Folder() instead of File() for path construction
  var lutsFolder = new Folder(extensionRoot + "/luts");
  var lutFile = new File(lutsFolder.fsName + "/" + lutName);
  if (!lutFile.exists) {
    return "LUT not bundled; grading skipped: " + lutName;
  }

  var solid = comp.layers.addSolid([1, 1, 1], "LUT: " + lutName, comp.width, comp.height, comp.pixelAspect);
  solid.startTime = startTime;
  solid.outPoint = startTime + duration;
  if (typeof opacity === "number") {
    solid.property("ADBE Transform Group").property("ADBE Opacity").setValue(opacity);
  }

  var effects = solid.property("ADBE Effect Parade");
  try {
    var lumetri = effects.addProperty("ADBE Lumetri Color");
    lumetri.property("ADBE Lumetri Color-0001").setValue(lutFile.fsName);
    return null;
  } catch (e) {
    solid.remove();
    return "Lumetri could not load " + lutName + ": " + String(e);
  }
}

function uniqueStrings(values: string[]): string[] {
  var result: string[] = [];
  for (var i = 0; i < values.length; i++) {
    var found = false;
    for (var j = 0; j < result.length; j++) {
      if (result[j] === values[i]) found = true;
    }
    if (!found) result.push(values[i]);
  }
  return result;
}

function applyColorParams(comp: any, params: any): void {
  // Apply temperature, contrast, saturation etc. to the top adjustment layer
  var topLayer = comp.layer(1);
  if (!topLayer) return;
  var effects = topLayer.property("ADBE Effect Parade");
  try {
    var lumetri = effects.property("ADBE Lumetri Color");
    if (lumetri) {
      if (params.temperature_k !== undefined) {
        lumetri.property("ADBE Lumetri Color-0007").setValue(params.temperature_k);
      }
      if (params.contrast !== undefined) {
        lumetri.property("ADBE Lumetri Color-0010").setValue(params.contrast);
      }
      if (params.saturation !== undefined) {
        lumetri.property("ADBE Lumetri Color-0011").setValue(params.saturation);
      }
    }
  } catch (e) {}
}
