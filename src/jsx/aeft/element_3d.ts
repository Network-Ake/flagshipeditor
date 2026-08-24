// Element 3D Bridge — Create 3D solid and camera for Element 3D workflow

export function createElement3DSolid(comp: any, config: any): void {
  // Create the 3D solid
  var solidName = config.solid_name || "FlagshipEditor_3D_Solid";
  var solid = comp.layers.addSolid([0, 0, 0], solidName, comp.width, comp.height, comp.pixelAspect);
  solid.threeDLayer = true;
  solid.moveToEnd();

  // Create 3D camera if none exists
  var hasCamera = false;
  for (var i = 1; i <= comp.numLayers; i++) {
    if (comp.layer(i) instanceof CameraLayer) {
      hasCamera = true;
      break;
    }
  }
  if (!hasCamera && config.auto_camera !== false) {
    var camera = comp.layers.addCamera("FlagshipEditor_Camera", [comp.width / 2, comp.height / 2]);
    camera.property("ADBE Camera Options Group").property("ADBE Camera Zoom").setValue(2000);

    // Apply parallax if configured
    if (config.parallax_depth) {
      var position = camera.property("ADBE Transform Group").property("ADBE Position");
      position.expression = "wiggle(0.5, " + (config.parallax_depth * 100) + ")";
    }
  }

  // Add marker to indicate where to add Element 3D
  comp.markerProperty.setValueAtTime(
    0,
    new MarkerValue("Add Element 3D effect to: " + solidName)
  );
}
