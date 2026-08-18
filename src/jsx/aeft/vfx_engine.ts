// VFX Engine — Apply visual effects to AE layers via ExtendScript

export function applyZoomPunch(layer: any, config: any, beatTime: number, fps: number): void {
  var transform = layer.property("ADBE Transform Group");
  var scale = transform.property("ADBE Scale");
  var startFrame = Math.round(beatTime * fps);
  var target = config.scale_target || 140;
  var durIn = config.scale_duration_frames || 4;
  var durOut = config.ease_out_frames || 10;

  scale.setValueAtTime(startFrame / fps, [100, 100]);
  scale.setValueAtTime((startFrame + durIn) / fps, [target, target]);
  scale.setValueAtTime((startFrame + durIn + durOut) / fps, [100, 100]);

  // Ease
  try {
    for (var k = 1; k <= scale.numKeys; k++) {
      scale.setInterpolationTypeAtKey(k, KeyframeInterpolationType.BEZIER);
    }
  } catch (e) {}
}

export function applyCameraShake(layer: any, config: any): void {
  var transform = layer.property("ADBE Transform Group");
  var position = transform.property("ADBE Position");
  var freq = config.frequency_hz || 25;
  var amp = config.displacement_px || 12;
  position.expression = "wiggle(" + freq + ", " + amp + ")";
}

export function applyWhipPan(layer: any, config: any, beatTime: number, fps: number): void {
  var transform = layer.property("ADBE Transform Group");
  var position = transform.property("ADBE Position");
  var displacement = config.displacement_px || 2000;
  var dur = config.duration_frames || 5;
  var startFrame = Math.round(beatTime * fps);

  var currentPos = position.valueAtTime(beatTime, false);
  position.setValueAtTime(startFrame / fps, [currentPos[0] - displacement, currentPos[1]]);
  position.setValueAtTime((startFrame + dur) / fps, currentPos);

  // Motion blur
  try {
    var mb = layer.property("ADBE Motion Blur");
    mb.setValue(true);
  } catch (e) {}
}

export function applyGlitch(layer: any, config: any, beatTime: number, fps: number): void {
  var effects = layer.property("ADBE Effect Parade");

  // Displacement Map (self-displacement for glitch)
  try {
    var displacement = effects.addProperty("ADBE Displacement Map");
    displacement.property("ADBE Displacement Map-0001").setValue(15);
    displacement.property("ADBE Displacement Map-0002").setValue(15);
  } catch (e) {}

  // RGB Split via Shift Channels
  try {
    var rgbSplit = effects.addProperty("ADBE Shift Channels");
    rgbSplit.property("ADBE Shift Channels-0001").setValue(2); // Take Red From
    rgbSplit.property("ADBE Shift Channels-0002").setValue(3); // Take Green From
  } catch (e) {}

  // Keyframe the effect intensity on the 808 hit
  var startFrame = Math.round(beatTime * fps);
  var endFrame = startFrame + (config.duration_frames || 3);

  // Animate opacity of the effects
  try {
    var opacity = layer.property("ADBE Transform Group").property("ADBE Opacity");
    opacity.setValueAtTime(startFrame / fps, 100);
    opacity.setValueAtTime(endFrame / fps, 100);
  } catch (e) {}
}

export function applySpeedRamp(layer: any, config: any, beatTime: number, fps: number): void {
  var timeRemap = layer.property("ADBE Time Remapping");
  if (!timeRemap) {
    try {
      layer.timeRemapEnabled = true;
      timeRemap = layer.property("ADBE Time Remapping");
    } catch (e) {
      return;
    }
  }
  var speedIn = config.speed_in || 100;
  var speedOut = config.speed_out || 200;
  var rampDur = (config.ramp_duration_beats || 2) * (60 / 30); // approx

  timeRemap.setValueAtTime(beatTime, beatTime);
  timeRemap.setValueAtTime(beatTime + rampDur, beatTime + (rampDur * speedOut / 100));
}

export function applyFreezeFrame(layer: any, beatTime: number, durationFrames: number): void {
  var timeRemap = layer.property("ADBE Time Remapping");
  if (!timeRemap) {
    try {
      layer.timeRemapEnabled = true;
      timeRemap = layer.property("ADBE Time Remapping");
    } catch (e) {
      return;
    }
  }
  timeRemap.setValueAtTime(beatTime, beatTime);
  timeRemap.setValueAtTime(beatTime + (durationFrames / 30), beatTime);
}