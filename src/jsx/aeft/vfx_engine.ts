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

export function applyCameraShake(layer: any, config: any, beatTime?: number, fps?: number): void {
  var transform = layer.property("ADBE Transform Group");
  var position = transform.property("ADBE Position");
  var freq = config.frequency_hz || 25;
  var amp = config.displacement_px || 12;

  // Time-bound the wiggle expression using posterizeTime in an expression
  // If beatTime is provided, apply wiggle only for a short window
  if (beatTime !== undefined && fps !== undefined && config.duration_frames) {
    var startTime = beatTime;
    var endTime = beatTime + (config.duration_frames / (fps || 30));
    // Use expression with conditional time check
    position.expression =
      "var t = time; var start = " + startTime + "; var end = " + endTime +
      "; if (t >= start && t <= end) { wiggle(" + freq + ", " + amp + "); } else { value; }";
  } else {
    // Fallback: apply wiggle with decay using expression
    position.expression =
      "wiggle(" + freq + ", " + amp + ")";
  }
}

export function applyWhipPan(layer: any, config: any, beatTime: number, fps: number): void {
  var transform = layer.property("ADBE Transform Group");
  var position = transform.property("ADBE Position");
  var rotation = transform.property("ADBE Rotate Z");
  var displacement = config.displacement_px || 2000;
  var rotationAmt = config.rotation_degrees || 15;
  var direction = config.direction || 1; // 1 = left-to-right, -1 = right-to-left
  var dur = config.duration_frames || 5;
  var startFrame = Math.round(beatTime * fps);

  // Position animation (horizontal whip)
  var currentPos = position.valueAtTime(beatTime, false);
  position.setValueAtTime(startFrame / fps, [currentPos[0] - displacement * direction, currentPos[1]]);
  position.setValueAtTime((startFrame + dur) / fps, currentPos);

  // Rotation animation (whip pan rotation)
  try {
    rotation.setValueAtTime(startFrame / fps, rotationAmt * direction);
    rotation.setValueAtTime((startFrame + Math.round(dur / 2)) / fps, -rotationAmt * 0.3 * direction);
    rotation.setValueAtTime((startFrame + dur) / fps, 0);
    for (var k = 1; k <= rotation.numKeys; k++) {
      rotation.setInterpolationTypeAtKey(k, KeyframeInterpolationType.BEZIER);
    }
  } catch (e) {}

  // Motion blur
  try {
    layer.motionBlur = true;
    var comp = layer.containingComp;
    if (comp) comp.motionBlur = true;
  } catch (e) {}
}

export function applyGlitch(layer: any, config: any, beatTime: number, fps: number): void {
  var effects = layer.property("ADBE Effect Parade");
  var startFrame = Math.round(beatTime * fps);
  var durFrames = config.duration_frames || 3;
  var endFrame = startFrame + durFrames;
  var maxOffset = config.displacement_px || 15;

  // RGB Split using three duplicated layers with Shift Channels for true chromatic aberration
  try {
    // Red channel only
    var redLayer = layer.containingComp.layers.add(layer.source);
    redLayer.startTime = layer.startTime;
    redLayer.outPoint = layer.outPoint;
    redLayer.enabled = true;
    redLayer.name = layer.name + " [R]";
    var redEffects = redLayer.property("ADBE Effect Parade");
    var redShift = redEffects.addProperty("ADBE Shift Channels");
    redShift.property("ADBE Shift Channels-0001").setValue(2); // Take Red From Red
    redShift.property("ADBE Shift Channels-0002").setValue(4); // Take Green From Full Off
    redShift.property("ADBE Shift Channels-0003").setValue(4); // Take Blue From Full Off
    var redTransform = redLayer.property("ADBE Transform Group");
    var redPos = redTransform.property("ADBE Position");
    redPos.setValueAtTime(startFrame / fps, [maxOffset, 0]);
    redPos.setValueAtTime((startFrame + 1) / fps, [-maxOffset, 0]);
    redPos.setValueAtTime((startFrame + 2) / fps, [maxOffset * 0.5, 0]);
    redPos.setValueAtTime(endFrame / fps, [0, 0]);
    redTransform.property("ADBE Opacity").setValueAtTime(startFrame / fps, 100);
    redTransform.property("ADBE Opacity").setValueAtTime(endFrame / fps, 0);

    // Blue channel only
    var blueLayer = layer.containingComp.layers.add(layer.source);
    blueLayer.startTime = layer.startTime;
    blueLayer.outPoint = layer.outPoint;
    blueLayer.enabled = true;
    blueLayer.name = layer.name + " [B]";
    var blueEffects = blueLayer.property("ADBE Effect Parade");
    var blueShift = blueEffects.addProperty("ADBE Shift Channels");
    blueShift.property("ADBE Shift Channels-0001").setValue(4); // Take Red From Full Off
    blueShift.property("ADBE Shift Channels-0002").setValue(4); // Take Green From Full Off
    blueShift.property("ADBE Shift Channels-0003").setValue(2); // Take Blue From Blue
    var blueTransform = blueLayer.property("ADBE Transform Group");
    var bluePos = blueTransform.property("ADBE Position");
    bluePos.setValueAtTime(startFrame / fps, [-maxOffset, 0]);
    bluePos.setValueAtTime((startFrame + 1) / fps, [maxOffset, 0]);
    bluePos.setValueAtTime((startFrame + 2) / fps, [-maxOffset * 0.5, 0]);
    bluePos.setValueAtTime(endFrame / fps, [0, 0]);
    blueTransform.property("ADBE Opacity").setValueAtTime(startFrame / fps, 100);
    blueTransform.property("ADBE Opacity").setValueAtTime(endFrame / fps, 0);

    // Set blend mode of original to Screen for additive RGB recombination
    layer.blendingMode = BlendingMode.SCREEN;
    redLayer.blendingMode = BlendingMode.SCREEN;
    blueLayer.blendingMode = BlendingMode.SCREEN;
  } catch (e) {}

  // Displacement Map (self-displacement for glitch jitter)
  try {
    var displacement = effects.addProperty("ADBE Displacement Map");
    displacement.property("ADBE Displacement Map-0001").setValue(maxOffset);
    displacement.property("ADBE Displacement Map-0002").setValue(maxOffset);
    // Time-bound the displacement
    displacement.property("ADBE Displacement Map-0001").setValueAtTime(startFrame / fps, maxOffset);
    displacement.property("ADBE Displacement Map-0001").setValueAtTime(endFrame / fps, 0);
    displacement.property("ADBE Displacement Map-0002").setValueAtTime(startFrame / fps, maxOffset);
    displacement.property("ADBE Displacement Map-0002").setValueAtTime(endFrame / fps, 0);
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
  var rampDur = (config.ramp_duration_beats || 2) * (60 / (fps || 30));

  timeRemap.setValueAtTime(beatTime, beatTime);
  timeRemap.setValueAtTime(beatTime + rampDur, beatTime + (rampDur * speedOut / 100));
}

export function applyFreezeFrame(layer: any, beatTime: number, durationFrames: number, fps?: number): void {
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
  timeRemap.setValueAtTime(beatTime + (durationFrames / (fps || 30)), beatTime);
}

// ============ 17 NEW VFX EFFECTS ============

export function applyFaceMask(layer: any, config: any, beatTime: number, fps: number): void {
  var effects = layer.property("ADBE Effect Parade");
  var startFrame = Math.round(beatTime * fps);
  var fadeOutFrames = config.fade_out_frames || 10;
  var intensity = config.intensity || 50;

  try {
    var mosaic = effects.addProperty("ADBE Mosaic");
    mosaic.property("ADBE Mosaic-0001").setValue(intensity); // Horizontal blocks
    mosaic.property("ADBE Mosaic-0002").setValue(intensity); // Vertical blocks
    mosaic.property("ADBE Mosaic-0001").setValueAtTime(startFrame / fps, intensity);
    mosaic.property("ADBE Mosaic-0001").setValueAtTime((startFrame + fadeOutFrames) / fps, 0);
    mosaic.property("ADBE Mosaic-0002").setValueAtTime(startFrame / fps, intensity);
    mosaic.property("ADBE Mosaic-0002").setValueAtTime((startFrame + fadeOutFrames) / fps, 0);
    for (var k = 1; k <= mosaic.property("ADBE Mosaic-0001").numKeys; k++) {
      mosaic.property("ADBE Mosaic-0001").setInterpolationTypeAtKey(k, KeyframeInterpolationType.BEZIER);
    }
  } catch (e) {}
}

export function applySmokeFog(layer: any, config: any, beatTime: number, fps: number): void {
  var effects = layer.property("ADBE Effect Parade");
  var startFrame = Math.round(beatTime * fps);

  try {
    var noise = effects.addProperty("ADBE Fractal Noise");
    noise.property("ADBE Fractal Noise-0001").setValue(200); // Scale
    noise.property("ADBE Fractal Noise-0009").setValue(30); // Opacity
    noise.property("ADBE Fractal Noise-0003").setValue(50); // Contrast (low)
    noise.property("ADBE Fractal Noise-0005").setValue(0); // Brightness (low)
    // Subtle drift via evolution keyframes
    noise.property("ADBE Fractal Noise-0011").setValueAtTime(startFrame / fps, 0);
    noise.property("ADBE Fractal Noise-0011").setValueAtTime((startFrame + 30) / fps, 90); // Evolution drift over 1 sec
    for (var k = 1; k <= noise.property("ADBE Fractal Noise-0011").numKeys; k++) {
      noise.property("ADBE Fractal Noise-0011").setInterpolationTypeAtKey(k, KeyframeInterpolationType.LINEAR);
    }
  } catch (e) {}
}

export function applySlowMo(layer: any, config: any, beatTime: number, fps: number): void {
  var timeRemap = layer.property("ADBE Time Remapping");
  if (!timeRemap) {
    try {
      layer.timeRemapEnabled = true;
      timeRemap = layer.property("ADBE Time Remapping");
    } catch (e) {
      return;
    }
  }
  var slowFactor = config.slow_factor || 0.4;
  var rampInFrames = config.ramp_in_frames || 3;
  var rampOutFrames = config.ramp_out_frames || 8;
  var startFrame = Math.round(beatTime * fps);

  // Slow down to slowFactor over rampInFrames, then ramp back to 100% over rampOutFrames
  timeRemap.setValueAtTime(startFrame / fps, startFrame / fps);
  // At end of slow-in: time moves at slowFactor
  timeRemap.setValueAtTime((startFrame + rampInFrames) / fps, (startFrame + rampInFrames * slowFactor) / fps);
  // At end of slow-out: back to normal speed
  timeRemap.setValueAtTime((startFrame + rampInFrames + rampOutFrames) / fps, (startFrame + rampInFrames * slowFactor + rampOutFrames) / fps);

  try {
    for (var k = 1; k <= timeRemap.numKeys; k++) {
      timeRemap.setInterpolationTypeAtKey(k, KeyframeInterpolationType.BEZIER);
    }
  } catch (e) {}
}

export function applyBeatFlash(layer: any, config: any, beatTime: number, fps: number): void {
  var transform = layer.property("ADBE Transform Group");
  var opacity = transform.property("ADBE Opacity");
  var startFrame = Math.round(beatTime * fps);

  // Quick strobe: 100 -> 60 -> 100 over 2 frames
  opacity.setValueAtTime(startFrame / fps, 100);
  opacity.setValueAtTime((startFrame + 1) / fps, 60);
  opacity.setValueAtTime((startFrame + 2) / fps, 100);

  try {
    for (var k = 1; k <= opacity.numKeys; k++) {
      opacity.setInterpolationTypeAtKey(k, KeyframeInterpolationType.LINEAR);
    }
  } catch (e) {}
}

export function applyLightLeaks(layer: any, config: any, beatTime: number, fps: number): void {
  var comp = layer.containingComp;
  if (!comp) return;
  var startFrame = Math.round(beatTime * fps);
  var durFrames = config.duration_frames || (2 * fps); // 2 seconds default

  try {
    var adjLayer = comp.layers.addSolid([1, 0.5, 0.1], "LightLeak", comp.width, comp.height, comp.pixelAspect, (durFrames + 1) / fps);
    adjLayer.startTime = startFrame / fps;
    adjLayer.blendingMode = BlendingMode.SCREEN;

    var adjEffects = adjLayer.property("ADBE Effect Parade");

    // Optics Compensation for reverse lens distortion
    try {
      var optics = adjEffects.addProperty("ADBE Optics Compensation");
      optics.property("ADBE Optics Compensation-0001").setValue(50); // FOV
      optics.property("ADBE Optics Compensation-0002").setValue(1); // Reverse lens distortion
    } catch (e) {}

    // Gaussian Blur for soft light leak
    try {
      var blur = adjEffects.addProperty("ADBE Gaussian Blur");
      blur.property("ADBE Gaussian Blur-0001").setValue(60); // Blurriness
    } catch (e) {}

    // Opacity fade in/out
    var adjTransform = adjLayer.property("ADBE Transform Group");
    var adjOpacity = adjTransform.property("ADBE Opacity");
    adjOpacity.setValueAtTime(startFrame / fps, 0);
    adjOpacity.setValueAtTime((startFrame + Math.round(fps * 0.3)) / fps, 60); // Fade in
    adjOpacity.setValueAtTime((startFrame + durFrames - Math.round(fps * 0.3)) / fps, 60); // Hold
    adjOpacity.setValueAtTime((startFrame + durFrames) / fps, 0); // Fade out

    for (var k = 1; k <= adjOpacity.numKeys; k++) {
      adjOpacity.setInterpolationTypeAtKey(k, KeyframeInterpolationType.BEZIER);
    }
  } catch (e) {}
}

export function applyVHSOverlay(layer: any, config: any, beatTime: number, fps: number): void {
  var effects = layer.property("ADBE Effect Parade");
  var startFrame = Math.round(beatTime * fps);

  // Wave Warp for VHS jitter
  try {
    var waveWarp = effects.addProperty("ADBE Wave Warp");
    waveWarp.property("ADBE Wave Warp-0001").setValue(2); // Wave height (low amplitude)
    waveWarp.property("ADBE Wave Warp-0002").setValue(10); // Wave width
    // Jitter at beatTime
    waveWarp.property("ADBE Wave Warp-0001").setValueAtTime(startFrame / fps, 5);
    waveWarp.property("ADBE Wave Warp-0001").setValueAtTime((startFrame + 1) / fps, 1);
    waveWarp.property("ADBE Wave Warp-0001").setValueAtTime((startFrame + 2) / fps, 4);
    waveWarp.property("ADBE Wave Warp-0001").setValueAtTime((startFrame + 3) / fps, 2);
  } catch (e) {}

  // Noise for VHS grain
  try {
    var noise = effects.addProperty("ADBE Noise");
    noise.property("ADBE Noise-0001").setValue(8); // Amount of noise
  } catch (e) {}
}

export function applyFilmGrain(layer: any, config: any, beatTime: number, fps: number): void {
  var effects = layer.property("ADBE Effect Parade");
  var amount = config.amount || 5;

  try {
    var noise = effects.addProperty("ADBE Noise");
    noise.property("ADBE Noise-0001").setValue(amount); // Amount of noise (~5%
    // Monochromatic noise
    try {
      noise.property("ADBE Noise-0002").setValue(1); // Monochromatic
    } catch (e) {}
  } catch (e) {}
}

export function applyLetterbox(layer: any, config: any, beatTime: number, fps: number): void {
  var comp = layer.containingComp;
  if (!comp) return;
  var barHeightPct = config.bar_height_pct || 10; // 10% top and bottom
  var barHeight = Math.round(comp.height * barHeightPct / 100);

  try {
    // Top black bar
    var topBar = comp.layers.addSolid([0, 0, 0], "LetterboxTop", comp.width, barHeight, comp.pixelAspect, comp.duration);
    topBar.startTime = 0;
    // Move to top
    var topTransform = topBar.property("ADBE Transform Group");
    var topPos = topTransform.property("ADBE Position");
    topPos.setValue([comp.width / 2, barHeight / 2]);

    // Bottom black bar
    var bottomBar = comp.layers.addSolid([0, 0, 0], "LetterboxBottom", comp.width, barHeight, comp.pixelAspect, comp.duration);
    bottomBar.startTime = 0;
    var bottomTransform = bottomBar.property("ADBE Transform Group");
    var bottomPos = bottomTransform.property("ADBE Position");
    bottomPos.setValue([comp.width / 2, comp.height - barHeight / 2]);

    // Place bars above the layer
    topBar.moveBefore(layer);
    bottomBar.moveBefore(layer);
  } catch (e) {}
}

export function applyDepthBlur(layer: any, config: any, beatTime: number, fps: number): void {
  var effects = layer.property("ADBE Effect Parade");
  var startFrame = Math.round(beatTime * fps);
  var maxBlur = config.blur_radius || 50;
  var fadeFrames = config.fade_frames || 15;

  try {
    var blur = effects.addProperty("ADBE Camera Lens Blur");
    blur.property("ADBE Camera Lens Blur-0001").setValueAtTime(startFrame / fps, maxBlur); // High blur at beat
    blur.property("ADBE Camera Lens Blur-0001").setValueAtTime((startFrame + fadeFrames) / fps, 0); // Animate to 0

    for (var k = 1; k <= blur.property("ADBE Camera Lens Blur-0001").numKeys; k++) {
      blur.property("ADBE Camera Lens Blur-0001").setInterpolationTypeAtKey(k, KeyframeInterpolationType.BEZIER);
    }
  } catch (e) {}
}

export function applySmoothTransitions(layer: any, config: any, beatTime: number, fps: number): void {
  var transform = layer.property("ADBE Transform Group");
  var opacity = transform.property("ADBE Opacity");
  var fadeFrames = config.fade_frames || 4;
  var layerIn = layer.startTime;
  var layerOut = layer.outPoint;

  // Fade in: 0 -> 100 over fadeFrames at layer start
  opacity.setValueAtTime(layerIn, 0);
  opacity.setValueAtTime(layerIn + fadeFrames / fps, 100);

  // Fade out: 100 -> 0 over fadeFrames at layer end
  opacity.setValueAtTime(layerOut - fadeFrames / fps, 100);
  opacity.setValueAtTime(layerOut, 0);

  try {
    for (var k = 1; k <= opacity.numKeys; k++) {
      opacity.setInterpolationTypeAtKey(k, KeyframeInterpolationType.BEZIER);
    }
  } catch (e) {}
}

export function applyMaskTransition(layer: any, config: any, beatTime: number, fps: number): void {
  var effects = layer.property("ADBE Effect Parade");
  var startFrame = Math.round(beatTime * fps);
  var wipeFrames = config.wipe_frames || 5;

  try {
    var wipe = effects.addProperty("ADBE Linear Wipe");
    wipe.property("ADBE Linear Wipe-0001").setValueAtTime(startFrame / fps, 0); // Wipe completion: 0%
    wipe.property("ADBE Linear Wipe-0001").setValueAtTime((startFrame + wipeFrames) / fps, 100); // Wipe completion: 100%
    wipe.property("ADBE Linear Wipe-0002").setValue(90); // Wipe angle
    wipe.property("ADBE Linear Wipe-0003").setValue(0); // Feather

    for (var k = 1; k <= wipe.property("ADBE Linear Wipe-0001").numKeys; k++) {
      wipe.property("ADBE Linear Wipe-0001").setInterpolationTypeAtKey(k, KeyframeInterpolationType.LINEAR);
    }
  } catch (e) {}
}

export function applyPictureFlash(layer: any, config: any, beatTime: number, fps: number): void {
  var transform = layer.property("ADBE Transform Group");
  var opacity = transform.property("ADBE Opacity");
  var startFrame = Math.round(beatTime * fps);

  // White flash for 1 frame: opacity 0 -> 100 at next frame
  opacity.setValueAtTime(startFrame / fps, 0);
  opacity.setValueAtTime((startFrame + 1) / fps, 100);

  try {
    for (var k = 1; k <= opacity.numKeys; k++) {
      opacity.setInterpolationTypeAtKey(k, KeyframeInterpolationType.LINEAR);
    }
  } catch (e) {}
}

export function applySelectiveColor(layer: any, config: any, beatTime: number, fps: number): void {
  var effects = layer.property("ADBE Effect Parade");
  var startFrame = Math.round(beatTime * fps);
  var hueShift = config.hue_shift || 10;
  var fadeFrames = config.fade_frames || 10;

  try {
    var hueSat = effects.addProperty("ADBE Hue/Saturation");
    hueSat.property("ADBE Hue/Saturation-0001").setValueAtTime(startFrame / fps, hueShift); // Hue shift at beat
    hueSat.property("ADBE Hue/Saturation-0001").setValueAtTime((startFrame + fadeFrames) / fps, 0); // Animate back to 0

    for (var k = 1; k <= hueSat.property("ADBE Hue/Saturation-0001").numKeys; k++) {
      hueSat.property("ADBE Hue/Saturation-0001").setInterpolationTypeAtKey(k, KeyframeInterpolationType.BEZIER);
    }
  } catch (e) {}
}

export function applySlowPushIn(layer: any, config: any, beatTime: number, fps: number): void {
  var transform = layer.property("ADBE Transform Group");
  var scale = transform.property("ADBE Scale");
  var targetScale = config.target_scale || 110;
  var layerIn = layer.startTime;
  var layerOut = layer.outPoint;

  // Linear slow push: 100 -> target over entire layer duration
  scale.setValueAtTime(layerIn, [100, 100]);
  scale.setValueAtTime(layerOut, [targetScale, targetScale]);

  try {
    for (var k = 1; k <= scale.numKeys; k++) {
      scale.setInterpolationTypeAtKey(k, KeyframeInterpolationType.LINEAR);
    }
  } catch (e) {}
}

export function applyRGBSplit(layer: any, config: any, beatTime: number, fps: number): void {
  var comp = layer.containingComp;
  if (!comp) return;
  var offset = config.offset_px || 2;

  try {
    // Red channel only
    var redLayer = comp.layers.add(layer.source);
    redLayer.startTime = layer.startTime;
    redLayer.outPoint = layer.outPoint;
    redLayer.enabled = true;
    redLayer.name = layer.name + " [RGB-R]";
    var redEffects = redLayer.property("ADBE Effect Parade");
    var redShift = redEffects.addProperty("ADBE Shift Channels");
    redShift.property("ADBE Shift Channels-0001").setValue(2); // Take Red From Red
    redShift.property("ADBE Shift Channels-0002").setValue(4); // Take Green From Full Off
    redShift.property("ADBE Shift Channels-0003").setValue(4); // Take Blue From Full Off
    var redTransform = redLayer.property("ADBE Transform Group");
    var redPos = redTransform.property("ADBE Position");
    var currentRedPos = redPos.valueAtTime(layer.startTime, false);
    redPos.setValue([currentRedPos[0] + offset, currentRedPos[1]]);
    redLayer.blendingMode = BlendingMode.SCREEN;

    // Blue channel only
    var blueLayer = comp.layers.add(layer.source);
    blueLayer.startTime = layer.startTime;
    blueLayer.outPoint = layer.outPoint;
    blueLayer.enabled = true;
    blueLayer.name = layer.name + " [RGB-B]";
    var blueEffects = blueLayer.property("ADBE Effect Parade");
    var blueShift = blueEffects.addProperty("ADBE Shift Channels");
    blueShift.property("ADBE Shift Channels-0001").setValue(4); // Take Red From Full Off
    blueShift.property("ADBE Shift Channels-0002").setValue(4); // Take Green From Full Off
    blueShift.property("ADBE Shift Channels-0003").setValue(2); // Take Blue From Blue
    var blueTransform = blueLayer.property("ADBE Transform Group");
    var bluePos = blueTransform.property("ADBE Position");
    var currentBluePos = bluePos.valueAtTime(layer.startTime, false);
    bluePos.setValue([currentBluePos[0] - offset, currentBluePos[1]]);
    blueLayer.blendingMode = BlendingMode.SCREEN;

    // Original layer also Screen for additive recombination
    layer.blendingMode = BlendingMode.SCREEN;
  } catch (e) {}
}

export function applyStrobe(layer: any, config: any, beatTime: number, fps: number): void {
  var transform = layer.property("ADBE Transform Group");
  var opacity = transform.property("ADBE Opacity");
  var startFrame = Math.round(beatTime * fps);

  // Strobe: 100, 0, 100, 0, 100 over 5 frames
  opacity.setValueAtTime(startFrame / fps, 100);
  opacity.setValueAtTime((startFrame + 1) / fps, 0);
  opacity.setValueAtTime((startFrame + 2) / fps, 100);
  opacity.setValueAtTime((startFrame + 3) / fps, 0);
  opacity.setValueAtTime((startFrame + 4) / fps, 100);

  try {
    for (var k = 1; k <= opacity.numKeys; k++) {
      opacity.setInterpolationTypeAtKey(k, KeyframeInterpolationType.LINEAR);
    }
  } catch (e) {}
}

export function applyLightWrap(layer: any, config: any, beatTime: number, fps: number): void {
  var effects = layer.property("ADBE Effect Parade");
  var comp = layer.containingComp;
  if (!comp) return;
  var glowThreshold = config.glow_threshold || 80;
  var glowRadius = config.glow_radius || 10;
  var blurAmount = config.blur_amount || 20;

  // Glow on the layer itself
  try {
    var glow = effects.addProperty("ADBE Glow");
    glow.property("ADBE Glow-0001").setValue(glowThreshold); // Glow threshold (high)
    glow.property("ADBE Glow-0002").setValue(glowRadius); // Glow radius (low)
    glow.property("ADBE Glow-0003").setValue(0.5); // Glow intensity
  } catch (e) {}

  // Adjustment layer above with Gaussian Blur, Screen blend
  try {
    var adjLayer = comp.layers.addSolid([1, 1, 1], "LightWrap", comp.width, comp.height, comp.pixelAspect, (layer.outPoint - layer.startTime));
    adjLayer.startTime = layer.startTime;
    adjLayer.blendingMode = BlendingMode.SCREEN;

    var adjEffects = adjLayer.property("ADBE Effect Parade");
    var blur = adjEffects.addProperty("ADBE Gaussian Blur");
    blur.property("ADBE Gaussian Blur-0001").setValue(blurAmount);

    // Place adjustment layer above the target layer
    adjLayer.moveBefore(layer);
  } catch (e) {}
}
