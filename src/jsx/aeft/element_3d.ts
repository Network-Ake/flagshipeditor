// Element 3D bridge — detects Video Copilot Element 3D and sets up the scene.

import { VFXContext, clamp, readNumber, readString, reportWarning, transformProperty } from "./vfx_utils";

var ELEMENT_MATCH_NAMES = ["VideoCopilot Element", "Video Copilot Element 3D", "ADBE Element"];

// Cached so a build with many sections probes the host only once.
var detectedMatchName: string | null = null;
var detectionRan = false;

export function detectElement3D(comp: any): string | null {
  if (detectionRan) return detectedMatchName;
  detectionRan = true;
  detectedMatchName = null;
  var probe: any = null;
  try {
    probe = comp.layers.addSolid([0, 0, 0], "FlagshipEditor_ElementProbe", 4, 4, 1, 0.04);
  } catch (createError) {
    return null;
  }
  try {
    var parade = probe.property("ADBE Effect Parade");
    for (var i = 0; i < ELEMENT_MATCH_NAMES.length; i++) {
      // canAddProperty is unreliable across AE versions — it can return false
      // for third-party effects that are genuinely installed. Always try
      // addProperty and let the throw distinguish installed from absent.
      try {
        var effect = parade.addProperty(ELEMENT_MATCH_NAMES[i]);
        if (effect) {
          detectedMatchName = ELEMENT_MATCH_NAMES[i];
          break;
        }
      } catch (addError) {
        // Element 3D is not installed under this match name.
      }
    }
  } catch (paradeError) {
    detectedMatchName = null;
  }
  try {
    probe.remove();
  } catch (removeError) {
    // The probe solid is 4x4 and 1 frame long; leaving it is harmless.
  }
  return detectedMatchName;
}

export function resetElement3DDetection(): void {
  detectionRan = false;
  detectedMatchName = null;
}

export function createElement3DSolid(comp: any, config: any, context: VFXContext): void {
  var matchName = detectElement3D(comp);
  if (!matchName) {
    reportWarning(
      context,
      "Element 3D is not installed; the 3D solid and camera were skipped"
    );
    return;
  }

  var solidName = readString(config, ["solid_name"], "FlagshipEditor_3D_Solid");
  var solid: any = null;
  try {
    solid = comp.layers.addSolid([0, 0, 0], solidName, comp.width, comp.height, comp.pixelAspect, comp.duration);
    solid.threeDLayer = true;
    solid.startTime = 0;
    solid.inPoint = 0;
    solid.outPoint = comp.duration;
    solid.moveToBeginning();
  } catch (solidError) {
    reportWarning(context, "Element 3D solid could not be created: " + String(solidError));
    return;
  }

  try {
    var parade = solid.property("ADBE Effect Parade");
    var effect = parade.addProperty(matchName);
    if (!effect) throw new Error("the effect could not be added");
  } catch (effectError) {
    reportWarning(context, "Element 3D effect could not be applied: " + String(effectError));
    try {
      solid.remove();
    } catch (removeError) {
      reportWarning(context, "An unused 3D solid was left in the project: " + String(removeError));
    }
    return;
  }

  if (config && config.auto_camera === false) return;
  createParallaxCamera(comp, config, context);
}

function createParallaxCamera(comp: any, config: any, context: VFXContext): void {
  for (var i = 1; i <= comp.numLayers; i++) {
    try {
      if (comp.layer(i) instanceof CameraLayer) return;
    } catch (layerError) {
      // A layer that cannot be inspected is not a camera we created.
    }
  }

  var camera: any = null;
  try {
    camera = comp.layers.addCamera("FlagshipEditor_Camera", [comp.width / 2, comp.height / 2]);
  } catch (cameraError) {
    reportWarning(context, "3D camera could not be created: " + String(cameraError));
    return;
  }

  try {
    var zoom = camera.property("ADBE Camera Options Group").property("ADBE Camera Zoom");
    // Proportional to the comp so the framing holds at any resolution.
    if (zoom) zoom.setValue(comp.width * 1.05);
  } catch (zoomError) {
    reportWarning(context, "3D camera zoom could not be set: " + String(zoomError));
  }

  var depth = clamp(readNumber(config, ["parallax_depth"], 0), 0, 1);
  if (depth <= 0) return;
  var position = transformProperty(camera, "ADBE Position");
  if (!position) {
    reportWarning(context, "3D parallax skipped: the camera has no position property");
    return;
  }
  try {
    // A controlled sinusoidal drift, not wiggle() — the old random jitter read
    // as camera shake rather than parallax.
    var amplitude = depth * 50;
    position.expression =
      "var base = value;\n" +
      "var amp = " + amplitude + ";\n" +
      "[base[0] + Math.sin(time * 0.5) * amp, base[1] + Math.cos(time * 0.35) * amp * 0.4, base[2] + Math.sin(time * 0.5) * amp];";
  } catch (expressionError) {
    reportWarning(context, "3D parallax expression could not be applied: " + String(expressionError));
  }
}
