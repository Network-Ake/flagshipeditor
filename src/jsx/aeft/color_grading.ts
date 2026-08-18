// Color Grading — Apply LUTs and color correction by section

export function applyColorGrading(comp: any, sections: any[], config: any): void {
  // If section LUTs are defined, create adjustment layers per section
  if (config.section_luts) {
    for (var i = 0; i < sections.length; i++) {
      var section = sections[i];
      var lutName = config.section_luts[section.type];
      if (lutName) {
        createLUTAdjustmentLayer(comp, section.start, section.end - section.start, lutName);
      }
    }
  }

  // If global LUT, create one adjustment layer for the whole comp
  if (config.global_lut) {
    createLUTAdjustmentLayer(comp, 0, comp.duration, config.global_lut);

    // Apply additional params if defined
    if (config.params) {
      applyColorParams(comp, config.params);
    }
  }
}

function createLUTAdjustmentLayer(comp: any, startTime: number, duration: number, lutName: string): void {
  var solid = comp.layers.addSolid([1, 1, 1], "LUT: " + lutName, comp.width, comp.height, comp.pixelAspect);
  solid.startTime = startTime;
  solid.outPoint = startTime + duration;

  var effects = solid.property("ADBE Effect Parade");
  try {
    var lumetri = effects.addProperty("ADBE Lumetri Color");
    // Set LUT file path — relative to extension directory
    var scriptFile = new File($.fileName);
    var scriptDir = scriptFile.parent;
    var lutFile = new File(scriptDir.absoluteURI + "/luts/" + lutName);
    if (lutFile.exists) {
      lumetri.property("ADBE Lumetri Color-0001").setValue(lutFile.fsName);
    }
  } catch (e) {}
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