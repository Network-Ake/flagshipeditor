// VFX Engine — applies visual effects to After Effects layers via ExtendScript.
//
// Two families of effect live here:
//   * per-cut effects, applied to the clip layer that starts on a beat;
//   * comp-wide effects, applied once to a single adjustment layer.
// Grain, letterbox, light leaks, light wrap, VHS and smoke belong to the second
// family: applying them per cut used to create hundreds of duplicate solids.

import {
  AnimationCurve,
  VFXContext,
  addEffect,
  animateEffectValue,
  applyEase,
  clamp,
  combineCurves,
  isThreeDLayer,
  jitter,
  jitterFrames,
  makeCurve,
  readNumber,
  readString,
  reportWarning,
  setEffectValue,
  setLinearInterpolation,
  toNumber,
  transformProperty,
} from "./vfx_utils";

export interface LayerPlan {
  opacityCurves: AnimationCurve[];
  scaleCurves: AnimationCurve[];
  baseScale: number[];
  baseOpacity: number;
  layerIn: number;
  layerOut: number;
}

// ---------------------------------------------------------------------------
// Layer plan — composes properties that more than one preset wants to animate
// ---------------------------------------------------------------------------

export function createLayerPlan(layer: any): LayerPlan {
  var baseScale = [100, 100];
  var baseOpacity = 100;
  var layerIn = 0;
  var layerOut = 0;
  try {
    var scaleProperty = transformProperty(layer, "ADBE Scale");
    if (scaleProperty && scaleProperty.value && scaleProperty.value.length) {
      baseScale = [];
      for (var i = 0; i < scaleProperty.value.length; i++) {
        baseScale.push(toNumber(scaleProperty.value[i], 100));
      }
    }
  } catch (scaleError) {
    baseScale = [100, 100];
  }
  try {
    var opacityProperty = transformProperty(layer, "ADBE Opacity");
    if (opacityProperty) baseOpacity = toNumber(opacityProperty.value, 100);
  } catch (opacityError) {
    baseOpacity = 100;
  }
  try {
    layerIn = toNumber(layer.inPoint, 0);
    layerOut = toNumber(layer.outPoint, 0);
  } catch (timeError) {
    layerIn = 0;
    layerOut = 0;
  }
  return {
    opacityCurves: [],
    scaleCurves: [],
    baseScale: baseScale,
    baseOpacity: baseOpacity,
    layerIn: layerIn,
    layerOut: layerOut,
  };
}

export function commitLayerPlan(layer: any, plan: LayerPlan, context: VFXContext): void {
  if (plan.opacityCurves.length > 0) {
    var opacity = transformProperty(layer, "ADBE Opacity");
    if (!opacity) {
      reportWarning(context, "Opacity animation skipped: the layer has no opacity property");
    } else {
      var opacityTrack = combineCurves(plan.opacityCurves);
      try {
        for (var o = 0; o < opacityTrack.times.length; o++) {
          opacity.setValueAtTime(
            opacityTrack.times[o],
            clamp(plan.baseOpacity * opacityTrack.values[o], 0, 100)
          );
        }
        if (opacityTrack.linear) {
          setLinearInterpolation(opacity);
        } else {
          applyEase(opacity, 45, 45, context, "Opacity");
        }
      } catch (opacityError) {
        reportWarning(context, "Opacity animation failed: " + String(opacityError));
      }
    }
  }

  if (plan.scaleCurves.length > 0) {
    var scale = transformProperty(layer, "ADBE Scale");
    if (!scale) {
      reportWarning(context, "Scale animation skipped: the layer has no scale property");
    } else {
      var dimensions = isThreeDLayer(layer) ? 3 : plan.baseScale.length;
      if (dimensions < 2) dimensions = 2;
      var scaleTrack = combineCurves(plan.scaleCurves);
      try {
        for (var s = 0; s < scaleTrack.times.length; s++) {
          var vector = [];
          for (var d = 0; d < dimensions; d++) {
            var base = d < plan.baseScale.length ? plan.baseScale[d] : plan.baseScale[0];
            vector.push(base * scaleTrack.values[s]);
          }
          scale.setValueAtTime(scaleTrack.times[s], vector);
        }
        if (scaleTrack.linear) {
          setLinearInterpolation(scale);
        } else {
          applyEase(scale, 20, 80, context, "Scale");
        }
      } catch (scaleWriteError) {
        reportWarning(context, "Scale animation failed: " + String(scaleWriteError));
      }
    }
  }
}

function clampToLayer(plan: LayerPlan, time: number): number {
  return clamp(time, plan.layerIn, plan.layerOut);
}

// ---------------------------------------------------------------------------
// Time remapping
// ---------------------------------------------------------------------------

// Time remap VALUES are source time, not comp time. The previous build wrote
// comp time into them, which made every speed effect show the wrong frames.
function resetTimeRemap(layer: any, context: VFXContext, label: string): any {
  var remap: any = null;
  try {
    if (layer.canSetTimeRemapEnabled === false) {
      reportWarning(context, label + " skipped: this layer cannot be time remapped");
      return null;
    }
  } catch (probeError) {
    // canSetTimeRemapEnabled is not exposed on every host; try anyway.
  }
  try {
    layer.timeRemapEnabled = true;
    remap = layer.property("ADBE Time Remapping");
  } catch (enableError) {
    reportWarning(context, label + " skipped: time remapping is unavailable (" + String(enableError) + ")");
    return null;
  }
  if (!remap) {
    reportWarning(context, label + " skipped: time remapping is unavailable");
    return null;
  }
  try {
    for (var key = remap.numKeys; key >= 1; key--) {
      remap.removeKey(key);
    }
  } catch (removeError) {
    // Enabling time remap auto-creates keys; if they cannot be removed the new
    // keyframes still override them at the times that matter.
  }
  return remap;
}

function sourceDuration(layer: any, fallback: number): number {
  try {
    if (layer.source && layer.source.duration) {
      var duration = toNumber(layer.source.duration, fallback);
      if (duration > 0) return duration;
    }
  } catch (e) {
    // Fall through to the caller's estimate.
  }
  return fallback;
}

function layerTimes(layer: any): { start: number; inPoint: number; outPoint: number } {
  return {
    start: toNumber(layer.startTime, 0),
    inPoint: toNumber(layer.inPoint, 0),
    outPoint: toNumber(layer.outPoint, 0),
  };
}

// ---------------------------------------------------------------------------
// Per-cut effects
// ---------------------------------------------------------------------------

export function applyZoomPunch(
  config: any,
  beatTime: number,
  context: VFXContext,
  plan: LayerPlan
): void {
  var fps = context.fps;
  var target = readNumber(config, ["scale_target", "target_scale"], 140);
  var framesIn = readNumber(config, ["scale_duration_frames", "punch_in_frames"], 4);
  var framesOut = readNumber(config, ["ease_out_frames", "release_frames"], 10);
  var variation = clamp(readNumber(config, ["randomness", "variation"], 0.1), 0, 0.5);

  var punchFactor = jitter(context, target / 100, variation);
  if (punchFactor <= 0) punchFactor = target / 100;
  var durationIn = jitterFrames(context, framesIn, 2) / fps;
  var durationOut = jitterFrames(context, framesOut, 2) / fps;

  var start = clampToLayer(plan, beatTime);
  var peak = clampToLayer(plan, beatTime + durationIn);
  var release = clampToLayer(plan, beatTime + durationIn + durationOut);
  if (release <= start) return;

  plan.scaleCurves.push(
    makeCurve(
      [
        { time: start, value: 1 },
        { time: peak, value: punchFactor },
        { time: release, value: 1 },
      ],
      false
    )
  );
}

export function applySlowPushIn(config: any, plan: LayerPlan): void {
  var startScale = readNumber(config, ["scale_start"], 100);
  var endScale = readNumber(config, ["scale_end", "target_scale"], 110);
  if (plan.layerOut <= plan.layerIn) return;
  plan.scaleCurves.push(
    makeCurve(
      [
        { time: plan.layerIn, value: startScale / 100 },
        { time: plan.layerOut, value: endScale / 100 },
      ],
      true
    )
  );
}

export function applyBeatFlash(
  config: any,
  beatTime: number,
  context: VFXContext,
  plan: LayerPlan
): void {
  var fps = context.fps;
  var peak = clamp(readNumber(config, ["opacity_peak", "peak_opacity"], 60), 0, 100) / 100;
  var frames = Math.max(1, readNumber(config, ["duration_frames"], 2));
  var start = clampToLayer(plan, beatTime);
  var dip = clampToLayer(plan, beatTime + frames / (2 * fps));
  var end = clampToLayer(plan, beatTime + frames / fps);
  if (end <= start) return;
  plan.opacityCurves.push(
    makeCurve(
      [
        { time: start, value: 1 },
        { time: dip, value: peak },
        { time: end, value: 1 },
      ],
      true
    )
  );
}

export function applyStrobe(
  config: any,
  beatTime: number,
  context: VFXContext,
  plan: LayerPlan
): void {
  var fps = context.fps;
  var frequency = clamp(readNumber(config, ["frequency_hz"], 12), 1, fps / 2);
  var peak = clamp(readNumber(config, ["opacity_peak"], 100), 0, 100) / 100;
  var floorValue = clamp(readNumber(config, ["opacity_floor"], 0), 0, 100) / 100;
  var cycles = Math.max(1, Math.round(readNumber(config, ["cycles"], 3)));
  var halfPeriod = 1 / (frequency * 2);

  var points = [];
  var time = beatTime;
  for (var cycle = 0; cycle < cycles; cycle++) {
    points.push({ time: clampToLayer(plan, time), value: peak });
    time += halfPeriod;
    points.push({ time: clampToLayer(plan, time), value: floorValue });
    time += halfPeriod;
  }
  points.push({ time: clampToLayer(plan, time), value: 1 });
  if (points[points.length - 1].time <= points[0].time) return;
  plan.opacityCurves.push(makeCurve(points, true));
}

// A picture flash is a white frame punched over the cut, not the clip fading
// in from nothing (which is what the previous implementation actually did).
// One solid carries every flash: creating a fresh solid per cut used to grow
// the comp by one layer per flashed beat.
var FLASH_LAYER_NAME = "FlagshipEditor_Flash";

function findOrCreateFlashSolid(context: VFXContext): any {
  var comp = context.comp;
  var flash: any = null;
  try {
    flash = comp.layers.byName(FLASH_LAYER_NAME);
  } catch (findError) {
    flash = null;
  }
  if (flash) return flash;
  try {
    flash = comp.layers.addSolid([1, 1, 1], FLASH_LAYER_NAME, comp.width, comp.height, comp.pixelAspect, comp.duration);
    flash.startTime = 0;
    flash.inPoint = 0;
    flash.outPoint = comp.duration;
    flash.blendingMode = BlendingMode.ADD;
  } catch (createError) {
    reportWarning(context, "Picture flash skipped: " + String(createError));
    return null;
  }
  // Invisible except during a keyed flash; the first keyframe would otherwise
  // hold its peak value across everything before the first flashed beat.
  var opacity = transformProperty(flash, "ADBE Opacity");
  if (opacity) {
    try {
      opacity.setValue(0);
    } catch (baselineError) {
      reportWarning(context, "Picture flash baseline opacity failed: " + String(baselineError));
    }
  }
  return flash;
}

export function applyPictureFlash(
  layer: any,
  config: any,
  beatTime: number,
  context: VFXContext
): void {
  var comp = context.comp;
  if (!comp) return;
  var fps = context.fps;
  var frames = Math.max(1, readNumber(config, ["duration_frames"], 2));
  var peak = clamp(readNumber(config, ["opacity_peak"], 90), 0, 100);
  var duration = frames / fps;
  var flash = findOrCreateFlashSolid(context);
  if (!flash) return;
  try {
    // Keep the shared solid above the newest cut layer so every flash renders
    // over the footage it belongs to.
    flash.moveBefore(layer);
  } catch (moveError) {
    reportWarning(context, "Picture flash could not be restacked: " + String(moveError));
  }
  var opacity = transformProperty(flash, "ADBE Opacity");
  if (!opacity) {
    reportWarning(context, "Picture flash skipped: the flash layer has no opacity property");
    return;
  }
  try {
    // A zero key one frame ahead pins the shared solid dark between flashes.
    var rampStart = beatTime - 1 / fps;
    if (rampStart > 0) opacity.setValueAtTime(rampStart, 0);
    opacity.setValueAtTime(beatTime, peak);
    opacity.setValueAtTime(beatTime + duration, 0);
    setLinearInterpolation(opacity);
  } catch (animateError) {
    reportWarning(context, "Picture flash could not be animated: " + String(animateError));
  }
}

export function applySmoothTransitions(
  config: any,
  context: VFXContext,
  plan: LayerPlan
): void {
  var fps = context.fps;
  var frames = Math.max(1, readNumber(config, ["fade_frames", "duration_frames"], 4));
  var fade = frames / fps;
  var span = plan.layerOut - plan.layerIn;
  if (span <= 0) return;
  // Never let the two fades cross on a very short cut.
  if (fade * 2 > span) fade = span / 2;
  plan.opacityCurves.push(
    makeCurve(
      [
        { time: plan.layerIn, value: 0 },
        { time: plan.layerIn + fade, value: 1 },
        { time: plan.layerOut - fade, value: 1 },
        { time: plan.layerOut, value: 0 },
      ],
      false
    )
  );
}

// Keyframed shake with exponential decay. The old wiggle() expression ran for
// the whole layer and re-evaluated on every frame of every clip.
export function applyCameraShake(
  layer: any,
  config: any,
  beatTime: number,
  context: VFXContext
): void {
  var fps = context.fps;
  var amplitude = readNumber(config, ["displacement_px", "amplitude_px"], 12);
  var frequency = clamp(readNumber(config, ["frequency_hz"], 25), 1, fps);
  var decay = clamp(readNumber(config, ["decay_factor"], 0.85), 0.1, 0.999);
  var durationFrames = readNumber(config, ["duration_frames"], Math.round(fps * 0.5));
  var steps = clamp(Math.round(durationFrames * (frequency / fps)), 4, 40);

  var position = transformProperty(layer, "ADBE Position");
  if (!position) {
    reportWarning(context, "Camera shake skipped: the layer has no position property");
    return;
  }

  var origin: number[];
  try {
    var raw = position.valueAtTime(beatTime, false);
    origin = [];
    for (var i = 0; i < raw.length; i++) origin.push(toNumber(raw[i], 0));
  } catch (readError) {
    reportWarning(context, "Camera shake skipped: position could not be read (" + String(readError) + ")");
    return;
  }

  var interval = durationFrames / fps / steps;
  try {
    position.setValueAtTime(beatTime, origin);
    var current = amplitude;
    for (var step = 1; step <= steps; step++) {
      var offset = [];
      for (var axis = 0; axis < origin.length; axis++) {
        // Leave depth alone so a 3D layer does not drift out of focus.
        var magnitude = axis < 2 ? current : current * 0.2;
        offset.push(origin[axis] + (context.random() * 2 - 1) * magnitude);
      }
      position.setValueAtTime(beatTime + interval * step, offset);
      current *= decay;
    }
    position.setValueAtTime(beatTime + interval * (steps + 1), origin);
    setLinearInterpolation(position);
  } catch (writeError) {
    reportWarning(context, "Camera shake failed: " + String(writeError));
  }
}

export function applyWhipPan(
  layer: any,
  config: any,
  beatTime: number,
  context: VFXContext
): void {
  var fps = context.fps;
  var displacement = readNumber(config, ["displacement_px"], 2000);
  var rotationAmount = readNumber(config, ["rotation_degrees"], 15);
  var frames = Math.max(1, readNumber(config, ["duration_frames"], 5));
  var duration = frames / fps;

  var direction = 1;
  if (config && (config.direction === 1 || config.direction === -1)) {
    direction = config.direction;
  } else {
    direction = context.random() > 0.5 ? 1 : -1;
  }

  var position = transformProperty(layer, "ADBE Position");
  if (!position) {
    reportWarning(context, "Whip pan skipped: the layer has no position property");
    return;
  }

  var origin: number[];
  try {
    var raw = position.valueAtTime(beatTime, false);
    origin = [];
    for (var i = 0; i < raw.length; i++) origin.push(toNumber(raw[i], 0));
  } catch (readError) {
    reportWarning(context, "Whip pan skipped: position could not be read (" + String(readError) + ")");
    return;
  }

  try {
    var entry = [];
    for (var axis = 0; axis < origin.length; axis++) {
      entry.push(axis === 0 ? origin[0] - displacement * direction : origin[axis]);
    }
    position.setValueAtTime(beatTime, entry);
    position.setValueAtTime(beatTime + duration, origin);
    applyEase(position, 10, 85, context, "Whip pan position");
  } catch (positionError) {
    reportWarning(context, "Whip pan position failed: " + String(positionError));
  }

  var rotation = transformProperty(layer, "ADBE Rotate Z");
  if (rotation) {
    try {
      rotation.setValueAtTime(beatTime, rotationAmount * direction);
      rotation.setValueAtTime(beatTime + duration / 2, -rotationAmount * 0.3 * direction);
      rotation.setValueAtTime(beatTime + duration, 0);
      applyEase(rotation, 10, 85, context, "Whip pan rotation");
    } catch (rotationError) {
      reportWarning(context, "Whip pan rotation failed: " + String(rotationError));
    }
  }

  try {
    layer.motionBlur = true;
    if (context.comp) context.comp.motionBlur = true;
  } catch (blurError) {
    reportWarning(context, "Whip pan motion blur could not be enabled: " + String(blurError));
  }
}

// Chromatic aberration built from two channel-isolated duplicates screened over
// the original. The original keeps its own blending mode: forcing it to Screen
// used to wash out everything beneath it.
var CHANNEL_GHOST_SUFFIXES = [" [RGB-R]", " [RGB-B]"];
// Two ghost layers per treated cut; beyond this the comp is already carrying
// more duplicate footage layers than After Effects previews comfortably, so
// further cuts keep the displacement part of the effect and skip the split.
var MAX_CHANNEL_GHOST_LAYERS = 40;

function countChannelGhosts(comp: any): number {
  var count = 0;
  try {
    for (var index = 1; index <= comp.numLayers; index++) {
      var name = String(comp.layer(index).name);
      for (var s = 0; s < CHANNEL_GHOST_SUFFIXES.length; s++) {
        var suffix = CHANNEL_GHOST_SUFFIXES[s];
        if (
          name.length >= suffix.length &&
          name.substring(name.length - suffix.length) === suffix
        ) {
          count++;
          break;
        }
      }
    }
  } catch (countError) {
    // A partially built comp still gets an answer; the cap is best-effort.
  }
  return count;
}

function addChannelGhost(
  layer: any,
  context: VFXContext,
  channel: "red" | "blue",
  suffix: string
): any {
  var comp = context.comp;
  var ghost: any = null;
  try {
    ghost = comp.layers.add(layer.source);
    ghost.startTime = layer.startTime;
    ghost.inPoint = layer.inPoint;
    ghost.outPoint = layer.outPoint;
    ghost.name = layer.name + suffix;
    ghost.blendingMode = BlendingMode.ADD;
    ghost.moveBefore(layer);
  } catch (createError) {
    reportWarning(context, "RGB split skipped: the channel layer could not be created (" + String(createError) + ")");
    return null;
  }
  var shift = addEffect(ghost, ["ADBE Shift Channels"], "RGB split", context);
  if (!shift) {
    try {
      ghost.remove();
    } catch (removeError) {
      reportWarning(context, "RGB split left an unused layer: " + String(removeError));
    }
    return null;
  }
  // Shift Channels parameters are Alpha(1), Red(2), Green(3), Blue(4).
  // Source enum: 9 = Full On, 10 = Full Off.
  var FULL_OFF = 10;
  var TAKE_RED = 2;
  var TAKE_GREEN = 3;
  var TAKE_BLUE = 4;
  var ok = true;
  if (channel === "red") {
    ok = setEffectValue(shift, ["ADBE Shift Channels-0002", 2], TAKE_RED, "RGB split red channel", context) && ok;
    ok = setEffectValue(shift, ["ADBE Shift Channels-0003", 3], FULL_OFF, "RGB split green channel", context) && ok;
    ok = setEffectValue(shift, ["ADBE Shift Channels-0004", 4], FULL_OFF, "RGB split blue channel", context) && ok;
  } else {
    ok = setEffectValue(shift, ["ADBE Shift Channels-0002", 2], FULL_OFF, "RGB split red channel", context) && ok;
    ok = setEffectValue(shift, ["ADBE Shift Channels-0003", 3], FULL_OFF, "RGB split green channel", context) && ok;
    ok = setEffectValue(shift, ["ADBE Shift Channels-0004", 4], TAKE_BLUE, "RGB split blue channel", context) && ok;
  }
  if (!ok) {
    reportWarning(context, "RGB split channel isolation is incomplete on this After Effects build");
  }
  return ghost;
}

export function applyRGBSplit(
  layer: any,
  config: any,
  beatTime: number,
  context: VFXContext
): void {
  if (!context.comp) return;
  if (countChannelGhosts(context.comp) >= MAX_CHANNEL_GHOST_LAYERS) {
    reportWarning(
      context,
      "RGB split capped: the comp already holds " + MAX_CHANNEL_GHOST_LAYERS + " channel layers; later cuts skip the split"
    );
    return;
  }
  var offset = readNumber(config, ["displacement_px", "offset_px"], 4);
  var red = addChannelGhost(layer, context, "red", CHANNEL_GHOST_SUFFIXES[0]);
  var blue = addChannelGhost(layer, context, "blue", CHANNEL_GHOST_SUFFIXES[1]);
  var ghosts = [
    { layer: red, sign: 1 },
    { layer: blue, sign: -1 },
  ];
  for (var i = 0; i < ghosts.length; i++) {
    var ghost = ghosts[i].layer;
    if (!ghost) continue;
    var position = transformProperty(ghost, "ADBE Position");
    if (!position) {
      reportWarning(context, "RGB split offset skipped: the channel layer has no position property");
      continue;
    }
    try {
      var origin = position.value;
      var shifted = [];
      for (var axis = 0; axis < origin.length; axis++) {
        shifted.push(axis === 0 ? toNumber(origin[0], 0) + offset * ghosts[i].sign : toNumber(origin[axis], 0));
      }
      position.setValue(shifted);
    } catch (offsetError) {
      reportWarning(context, "RGB split offset failed: " + String(offsetError));
    }
  }
}

export function applyGlitch(
  layer: any,
  config: any,
  beatTime: number,
  context: VFXContext
): void {
  var fps = context.fps;
  var frames = Math.max(1, readNumber(config, ["duration_frames"], 3));
  var duration = frames / fps;
  var maxOffset = readNumber(config, ["displacement_px"], 15);
  var jittered = maxOffset * (0.7 + context.random() * 0.6);

  // Chromatic tear on the cut.
  applyRGBSplit(layer, { displacement_px: jittered }, beatTime, context);

  // Turbulent Displace is self-contained. Displacement Map needs a source layer
  // and silently does nothing without one, which is why the old glitch was
  // invisible.
  var displace = addEffect(
    layer,
    ["ADBE Turbulent Displace", "ADBE Wave Warp"],
    "Glitch displacement",
    context
  );
  if (!displace) return;
  var amount = animateEffectValue(
    displace,
    ["ADBE Turbulent Displace-0002", 2],
    [beatTime, beatTime + duration],
    [jittered, 0],
    "Glitch displacement amount",
    context
  );
  setLinearInterpolation(amount);
  setEffectValue(displace, ["ADBE Turbulent Displace-0003", 3], Math.max(2, jittered), "Glitch displacement size", context);
  var evolution = animateEffectValue(
    displace,
    ["ADBE Turbulent Displace-0006", 6],
    [beatTime, beatTime + duration],
    [0, 360],
    "Glitch displacement evolution",
    context
  );
  setLinearInterpolation(evolution);
}

export function applySpeedRamp(
  layer: any,
  config: any,
  beatTime: number,
  context: VFXContext
): void {
  var times = layerTimes(layer);
  var span = times.outPoint - times.inPoint;
  if (span <= 0) return;

  var rateIn = clamp(readNumber(config, ["speed_in"], 100), 1, 2000) / 100;
  var rateOut = clamp(readNumber(config, ["speed_out"], 200), 1, 2000) / 100;
  // ramp_duration_beats is musical time, so it needs the tempo, not the frame
  // rate. Fall back to an explicit seconds value when tempo is unknown.
  var beatsPerMinute = readNumber(config, ["tempo_bpm"], context.tempo || 0);
  var rampSeconds = readNumber(config, ["ramp_duration_seconds"], 0);
  if (rampSeconds <= 0) {
    var beats = readNumber(config, ["ramp_duration_beats"], 2);
    rampSeconds = beatsPerMinute > 0 ? beats * (60 / beatsPerMinute) : beats * 0.5;
  }

  var remap = resetTimeRemap(layer, context, "Speed ramp");
  if (!remap) return;

  var duration = sourceDuration(layer, span);
  var rampStart = clamp(beatTime, times.inPoint, times.outPoint);
  var rampEnd = clamp(rampStart + rampSeconds, rampStart, times.outPoint);

  var sourceAtIn = clamp(times.inPoint - times.start, 0, duration);
  var sourceAtRampStart = clamp(sourceAtIn + (rampStart - times.inPoint) * rateIn, 0, duration);
  var sourceAtRampEnd = clamp(
    sourceAtRampStart + (rampEnd - rampStart) * ((rateIn + rateOut) / 2),
    0,
    duration
  );
  var sourceAtOut = clamp(sourceAtRampEnd + (times.outPoint - rampEnd) * rateOut, 0, duration);

  try {
    remap.setValueAtTime(times.inPoint, sourceAtIn);
    if (rampStart > times.inPoint) remap.setValueAtTime(rampStart, sourceAtRampStart);
    if (rampEnd > rampStart) remap.setValueAtTime(rampEnd, sourceAtRampEnd);
    if (times.outPoint > rampEnd) remap.setValueAtTime(times.outPoint, sourceAtOut);
    applyEase(remap, 33, 33, context, "Speed ramp");
  } catch (writeError) {
    reportWarning(context, "Speed ramp failed: " + String(writeError));
  }
}

export function applySlowMo(
  layer: any,
  config: any,
  beatTime: number,
  context: VFXContext
): void {
  var times = layerTimes(layer);
  var span = times.outPoint - times.inPoint;
  if (span <= 0) return;

  var rate = clamp(readNumber(config, ["speed_factor", "slow_factor"], 0.4), 0.05, 1);
  var rampFrames = Math.max(1, readNumber(config, ["ramp_in_frames"], 3));
  var rampSeconds = rampFrames / context.fps;

  var remap = resetTimeRemap(layer, context, "Slow motion");
  if (!remap) return;

  var duration = sourceDuration(layer, span);
  var slowStart = clamp(beatTime, times.inPoint, times.outPoint);
  var rampEnd = clamp(slowStart + rampSeconds, slowStart, times.outPoint);

  var sourceAtIn = clamp(times.inPoint - times.start, 0, duration);
  var sourceAtSlowStart = clamp(sourceAtIn + (slowStart - times.inPoint), 0, duration);
  var sourceAtRampEnd = clamp(
    sourceAtSlowStart + (rampEnd - slowStart) * ((1 + rate) / 2),
    0,
    duration
  );
  var sourceAtOut = clamp(sourceAtRampEnd + (times.outPoint - rampEnd) * rate, 0, duration);

  try {
    remap.setValueAtTime(times.inPoint, sourceAtIn);
    if (slowStart > times.inPoint) remap.setValueAtTime(slowStart, sourceAtSlowStart);
    if (rampEnd > slowStart) remap.setValueAtTime(rampEnd, sourceAtRampEnd);
    if (times.outPoint > rampEnd) remap.setValueAtTime(times.outPoint, sourceAtOut);
    applyEase(remap, 40, 40, context, "Slow motion");
  } catch (writeError) {
    reportWarning(context, "Slow motion failed: " + String(writeError));
  }
}

export function applyFreezeFrame(
  layer: any,
  config: any,
  beatTime: number,
  context: VFXContext
): void {
  var times = layerTimes(layer);
  var span = times.outPoint - times.inPoint;
  if (span <= 0) return;

  var frames = Math.max(1, readNumber(config, ["duration_frames"], 6));
  var freezeSeconds = Math.min(frames / context.fps, span * 0.9);
  var easeFrames = Math.max(1, readNumber(config, ["ease_frames"], 2));
  var easeSeconds = Math.min(easeFrames / context.fps, freezeSeconds / 2);

  var remap = resetTimeRemap(layer, context, "Freeze frame");
  if (!remap) return;

  var duration = sourceDuration(layer, span);
  var freezeStart = clamp(beatTime, times.inPoint, times.outPoint - freezeSeconds);
  var freezeEnd = freezeStart + freezeSeconds;

  var sourceAtIn = clamp(times.inPoint - times.start, 0, duration);
  var sourceAtFreeze = clamp(sourceAtIn + (freezeStart - times.inPoint), 0, duration);
  var sourceAtOut = clamp(sourceAtFreeze + (times.outPoint - freezeEnd), 0, duration);

  try {
    remap.setValueAtTime(times.inPoint, sourceAtIn);
    remap.setValueAtTime(freezeStart, sourceAtFreeze);
    remap.setValueAtTime(freezeEnd, sourceAtFreeze);
    if (times.outPoint > freezeEnd) remap.setValueAtTime(times.outPoint, sourceAtOut);
    // Ease the last frames before the freeze and the first frames after it so
    // the clip settles instead of snapping.
    applyEase(remap, easeSeconds > 0 ? 60 : 1, easeSeconds > 0 ? 60 : 1, context, "Freeze frame");
  } catch (writeError) {
    reportWarning(context, "Freeze frame failed: " + String(writeError));
  }
}

export function applyFaceMask(
  layer: any,
  config: any,
  beatTime: number,
  context: VFXContext
): void {
  var fps = context.fps;
  var radius = readNumber(config, ["blur_radius", "intensity"], 40);
  var fadeFrames = Math.max(1, readNumber(config, ["fade_out_frames"], 10));
  var mosaic = addEffect(layer, ["ADBE Mosaic"], "Face mask", context);
  if (!mosaic) return;
  var blocks = clamp(Math.round(200 - radius * 2), 6, 200);
  var horizontal = animateEffectValue(
    mosaic,
    ["ADBE Mosaic-0001", 1],
    [beatTime, beatTime + fadeFrames / fps],
    [blocks, 200],
    "Face mask horizontal blocks",
    context
  );
  applyEase(horizontal, 30, 60, context, "Face mask");
  var vertical = animateEffectValue(
    mosaic,
    ["ADBE Mosaic-0002", 2],
    [beatTime, beatTime + fadeFrames / fps],
    [blocks, 200],
    "Face mask vertical blocks",
    context
  );
  applyEase(vertical, 30, 60, context, "Face mask");
}

export function applyDepthBlur(
  layer: any,
  config: any,
  beatTime: number,
  context: VFXContext
): void {
  var fps = context.fps;
  var radius = readNumber(config, ["blur_radius"], 30);
  var fadeFrames = Math.max(1, readNumber(config, ["fade_frames"], 15));
  var blur = addEffect(
    layer,
    ["ADBE Camera Lens Blur", "ADBE Gaussian Blur 2", "ADBE Gaussian Blur"],
    "Depth blur",
    context
  );
  if (!blur) return;
  var amount = animateEffectValue(
    blur,
    ["ADBE Camera Lens Blur-0001", "ADBE Gaussian Blur 2-0001", "ADBE Gaussian Blur-0001", 1],
    [beatTime, beatTime + fadeFrames / fps],
    [radius, 0],
    "Depth blur radius",
    context
  );
  applyEase(amount, 20, 70, context, "Depth blur");
}

export function applySelectiveColor(
  layer: any,
  config: any,
  beatTime: number,
  context: VFXContext
): void {
  var fps = context.fps;
  var boost = readNumber(config, ["saturation_boost"], 25);
  var desaturateRest = readNumber(config, ["desaturate_rest"], 0);
  var fadeFrames = Math.max(1, readNumber(config, ["fade_frames"], 10));
  var hueSat = addEffect(
    layer,
    ["ADBE HUE SATURATION", "ADBE Hue/Saturation"],
    "Selective color",
    context
  );
  if (!hueSat) return;
  // Master Saturation is parameter 4 (1 Channel Control, 2 Channel Range,
  // 3 Master Hue, 4 Master Saturation, 5 Master Lightness).
  var saturation = animateEffectValue(
    hueSat,
    ["ADBE HUE SATURATION-0004", 4],
    [beatTime, beatTime + fadeFrames / fps],
    [boost, desaturateRest],
    "Selective color saturation",
    context
  );
  applyEase(saturation, 30, 60, context, "Selective color");
  var hueShift = readNumber(config, ["hue_shift"], 0);
  if (hueShift !== 0) {
    var hue = animateEffectValue(
      hueSat,
      ["ADBE HUE SATURATION-0003", 3],
      [beatTime, beatTime + fadeFrames / fps],
      [hueShift, 0],
      "Selective color hue",
      context
    );
    applyEase(hue, 30, 60, context, "Selective color");
  }
}

export function applyMaskTransition(
  layer: any,
  config: any,
  beatTime: number,
  context: VFXContext
): void {
  var fps = context.fps;
  var frames = Math.max(1, readNumber(config, ["duration_frames", "wipe_frames"], 5));
  var angle = readNumber(config, ["angle_degrees"], 90);
  var feather = readNumber(config, ["feather"], 12);
  var wipe = addEffect(layer, ["ADBE Linear Wipe"], "Mask transition", context);
  if (!wipe) return;
  // Transition Completion 100 hides the layer, so a reveal runs 100 -> 0.
  var completion = animateEffectValue(
    wipe,
    ["ADBE Linear Wipe-0001", 1],
    [beatTime, beatTime + frames / fps],
    [100, 0],
    "Mask transition completion",
    context
  );
  setLinearInterpolation(completion);
  setEffectValue(wipe, ["ADBE Linear Wipe-0002", 2], angle, "Mask transition angle", context);
  setEffectValue(wipe, ["ADBE Linear Wipe-0003", 3], feather, "Mask transition feather", context);
}

// ---------------------------------------------------------------------------
// Comp-wide effects — created once on a shared adjustment layer
// ---------------------------------------------------------------------------

function addAdjustmentLayer(context: VFXContext, name: string): any {
  var comp = context.comp;
  try {
    var solid = comp.layers.addSolid([1, 1, 1], name, comp.width, comp.height, comp.pixelAspect, comp.duration);
    solid.adjustmentLayer = true;
    solid.startTime = 0;
    solid.inPoint = 0;
    solid.outPoint = comp.duration;
    solid.moveToBeginning();
    return solid;
  } catch (e) {
    reportWarning(context, name + " skipped: the adjustment layer could not be created (" + String(e) + ")");
    return null;
  }
}

export function applyFilmGrain(config: any, context: VFXContext): void {
  var amount = clamp(readNumber(config, ["intensity", "amount"], 5), 0, 100);
  var adjustment = addAdjustmentLayer(context, "FlagshipEditor_Grain");
  if (!adjustment) return;
  var noise = addEffect(adjustment, ["ADBE Noise"], "Film grain", context);
  if (!noise) return;
  setEffectValue(noise, ["ADBE Noise-0001", 1], amount, "Film grain amount", context);
  // Parameter 2 is "Use Color Noise"; film grain is monochrome.
  setEffectValue(noise, ["ADBE Noise-0002", 2], false, "Film grain color mode", context);
  setEffectValue(noise, ["ADBE Noise-0003", 3], true, "Film grain clipping", context);
}

export function applyVHSOverlay(config: any, context: VFXContext): void {
  var opacity = clamp(readNumber(config, ["opacity"], 40), 0, 100);
  var adjustment = addAdjustmentLayer(context, "FlagshipEditor_VHS");
  if (!adjustment) return;
  var opacityProperty = transformProperty(adjustment, "ADBE Opacity");
  if (opacityProperty) {
    try {
      opacityProperty.setValue(opacity);
    } catch (opacityError) {
      reportWarning(context, "VHS overlay opacity could not be set: " + String(opacityError));
    }
  }
  var waveWarp = addEffect(adjustment, ["ADBE Wave Warp"], "VHS overlay", context);
  if (waveWarp) {
    // 1 Wave Type, 2 Wave Height, 3 Wave Width, 5 Wave Speed.
    setEffectValue(waveWarp, ["ADBE Wave Warp-0002", 2], 3, "VHS wave height", context);
    setEffectValue(waveWarp, ["ADBE Wave Warp-0003", 3], 120, "VHS wave width", context);
    setEffectValue(waveWarp, ["ADBE Wave Warp-0005", 5], 0.4, "VHS wave speed", context);
  }
  var noise = addEffect(adjustment, ["ADBE Noise"], "VHS grain", context);
  if (noise) {
    setEffectValue(noise, ["ADBE Noise-0001", 1], 8, "VHS grain amount", context);
    setEffectValue(noise, ["ADBE Noise-0002", 2], true, "VHS grain color mode", context);
  }
}

export function applyLetterbox(config: any, context: VFXContext): void {
  var comp = context.comp;
  if (!comp) return;
  var aspect = readNumber(config, ["aspect_ratio"], 2.39);
  var barPercent = readNumber(config, ["bar_height_pct"], 0);
  var barHeight: number;
  if (barPercent > 0) {
    barHeight = Math.round((comp.height * barPercent) / 100);
  } else {
    var visibleHeight = comp.width / (aspect > 0 ? aspect : 2.39);
    barHeight = Math.round(Math.max(0, (comp.height - visibleHeight) / 2));
  }
  if (barHeight < 1) return;

  var colorValue = readString(config, ["bars_color"], "black") === "black" ? 0 : 1;
  var color = [colorValue, colorValue, colorValue];
  var bars = [
    { name: "FlagshipEditor_LetterboxTop", y: barHeight / 2 },
    { name: "FlagshipEditor_LetterboxBottom", y: comp.height - barHeight / 2 },
  ];
  for (var i = 0; i < bars.length; i++) {
    try {
      var bar = comp.layers.addSolid(color, bars[i].name, comp.width, barHeight, comp.pixelAspect, comp.duration);
      bar.startTime = 0;
      bar.inPoint = 0;
      bar.outPoint = comp.duration;
      bar.moveToBeginning();
      var position = transformProperty(bar, "ADBE Position");
      if (position) position.setValue([comp.width / 2, bars[i].y]);
    } catch (barError) {
      reportWarning(context, "Letterbox bar skipped: " + String(barError));
    }
  }
}

export function applyLightLeaks(config: any, context: VFXContext): void {
  var comp = context.comp;
  if (!comp) return;
  var opacity = clamp(readNumber(config, ["opacity"], 45), 0, 100);
  // frequency is leaks per minute; one leak pulse is roughly 1.5s.
  var frequency = clamp(readNumber(config, ["frequency"], 6), 1, 60);
  var interval = 60 / frequency;
  var pulse = Math.min(1.5, interval * 0.6);

  var leak: any = null;
  try {
    leak = comp.layers.addSolid([1, 0.55, 0.2], "FlagshipEditor_LightLeak", comp.width, comp.height, comp.pixelAspect, comp.duration);
    leak.startTime = 0;
    leak.inPoint = 0;
    leak.outPoint = comp.duration;
    leak.blendingMode = BlendingMode.SCREEN;
    leak.moveToBeginning();
  } catch (createError) {
    reportWarning(context, "Light leaks skipped: " + String(createError));
    return;
  }

  var ramp = addEffect(leak, ["ADBE Ramp"], "Light leak gradient", context);
  if (ramp) {
    setEffectValue(ramp, ["ADBE Ramp-0001", 1], [0, comp.height / 2], "Light leak start", context);
    setEffectValue(ramp, ["ADBE Ramp-0003", 3], [comp.width, comp.height / 2], "Light leak end", context);
  }
  var blur = addEffect(leak, ["ADBE Gaussian Blur 2", "ADBE Gaussian Blur"], "Light leak blur", context);
  if (blur) {
    setEffectValue(blur, ["ADBE Gaussian Blur 2-0001", "ADBE Gaussian Blur-0001", 1], 120, "Light leak blur radius", context);
  }

  var opacityProperty = transformProperty(leak, "ADBE Opacity");
  if (!opacityProperty) {
    reportWarning(context, "Light leaks skipped: the leak layer has no opacity property");
    return;
  }
  try {
    var time = 0;
    var guard = 0;
    while (time < comp.duration && guard < 400) {
      opacityProperty.setValueAtTime(time, 0);
      opacityProperty.setValueAtTime(Math.min(comp.duration, time + pulse / 2), opacity);
      opacityProperty.setValueAtTime(Math.min(comp.duration, time + pulse), 0);
      time += interval;
      guard++;
    }
    applyEase(opacityProperty, 50, 50, context, "Light leaks");
  } catch (animateError) {
    reportWarning(context, "Light leaks could not be animated: " + String(animateError));
  }
}

export function applyLightWrap(config: any, context: VFXContext): void {
  var threshold = clamp(readNumber(config, ["threshold"], 70), 0, 100);
  var intensity = clamp(readNumber(config, ["intensity"], 40), 0, 100);
  var adjustment = addAdjustmentLayer(context, "FlagshipEditor_LightWrap");
  if (!adjustment) return;
  var glow = addEffect(adjustment, ["ADBE Glo2", "ADBE Glow"], "Light wrap", context);
  if (!glow) return;
  // 2 Glow Threshold, 3 Glow Radius, 4 Glow Intensity.
  setEffectValue(glow, ["ADBE Glo2-0002", 2], threshold, "Light wrap threshold", context);
  setEffectValue(glow, ["ADBE Glo2-0003", 3], 25, "Light wrap radius", context);
  setEffectValue(glow, ["ADBE Glo2-0004", 4], intensity / 50, "Light wrap intensity", context);
}

export function applySmokeFog(config: any, context: VFXContext): void {
  var comp = context.comp;
  if (!comp) return;
  var opacity = clamp(readNumber(config, ["opacity"], 25), 0, 100);
  var density = clamp(readNumber(config, ["density"], 50), 0, 100);
  var tint = readString(config, ["color"], "grey");
  var base = tint === "white" ? 0.9 : tint === "black" ? 0.1 : 0.55;

  var fog: any = null;
  try {
    fog = comp.layers.addSolid([base, base, base], "FlagshipEditor_Smoke", comp.width, comp.height, comp.pixelAspect, comp.duration);
    fog.startTime = 0;
    fog.inPoint = 0;
    fog.outPoint = comp.duration;
    fog.blendingMode = BlendingMode.SCREEN;
    fog.moveToBeginning();
    var opacityProperty = transformProperty(fog, "ADBE Opacity");
    if (opacityProperty) opacityProperty.setValue(opacity);
  } catch (createError) {
    reportWarning(context, "Smoke and fog skipped: " + String(createError));
    return;
  }

  var noise = addEffect(fog, ["ADBE Fractal Noise"], "Smoke and fog", context);
  if (!noise) return;
  // 4 Contrast, 5 Brightness, 10 Evolution, 12 Opacity.
  setEffectValue(noise, ["ADBE Fractal Noise-0004", 4], 40 + density, "Smoke contrast", context);
  setEffectValue(noise, ["ADBE Fractal Noise-0005", 5], -20, "Smoke brightness", context);
  setEffectValue(noise, ["ADBE Fractal Noise-0012", 12], 100, "Smoke noise opacity", context);
  var evolution = animateEffectValue(
    noise,
    ["ADBE Fractal Noise-0010", 10],
    [0, comp.duration],
    [0, 360 * Math.max(1, comp.duration / 20)],
    "Smoke evolution",
    context
  );
  setLinearInterpolation(evolution);
}
