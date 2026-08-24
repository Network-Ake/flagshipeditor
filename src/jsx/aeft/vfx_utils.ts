// Shared ES3-safe helpers for the After Effects VFX engine.
// Every After Effects DOM call funnels through here so that a failure is
// reported as a warning instead of silently producing an unedited layer.

export interface VFXContext {
  comp: any;
  fps: number;
  tempo: number;
  warnings: string[];
  random: () => number;
}

export function reportWarning(context: VFXContext, message: string): void {
  if (!context || !context.warnings) return;
  for (var i = 0; i < context.warnings.length; i++) {
    if (context.warnings[i] === message) return;
  }
  context.warnings.push(message);
}

// Deterministic 32-bit LCG so a given seed always rebuilds the same edit.
export function makeRandom(seed: number): () => number {
  var state = Math.floor(seed) % 2147483647;
  if (state <= 0) state += 2147483646;
  return function () {
    state = (state * 16807) % 2147483647;
    return (state - 1) / 2147483646;
  };
}

export function toNumber(value: any, fallback: number): number {
  var parsed = typeof value === "number" ? value : parseFloat(value);
  if (typeof parsed !== "number" || isNaN(parsed) || !isFinite(parsed)) return fallback;
  return parsed;
}

// Style presets use several spellings for the same idea (`slow_factor` vs
// `speed_factor`, `bar_height_pct` vs `aspect_ratio`). Read the first key that
// is actually present rather than silently falling back to a default.
export function readNumber(config: any, names: string[], fallback: number): number {
  if (!config) return fallback;
  for (var i = 0; i < names.length; i++) {
    var raw = config[names[i]];
    if (raw !== undefined && raw !== null && raw !== "") {
      return toNumber(raw, fallback);
    }
  }
  return fallback;
}

export function readString(config: any, names: string[], fallback: string): string {
  if (!config) return fallback;
  for (var i = 0; i < names.length; i++) {
    var raw = config[names[i]];
    if (raw !== undefined && raw !== null && raw !== "") return String(raw);
  }
  return fallback;
}

export function readBoolean(config: any, names: string[], fallback: boolean): boolean {
  if (!config) return fallback;
  for (var i = 0; i < names.length; i++) {
    var raw = config[names[i]];
    if (raw === true || raw === false) return raw;
    if (raw === "true") return true;
    if (raw === "false") return false;
  }
  return fallback;
}

export function clamp(value: number, minimum: number, maximum: number): number {
  if (value < minimum) return minimum;
  if (value > maximum) return maximum;
  return value;
}

// Vary a value by +/- ratio so repeated cuts do not look mechanically identical.
export function jitter(context: VFXContext, base: number, ratio: number): number {
  if (ratio <= 0) return base;
  return base * (1 - ratio + context.random() * ratio * 2);
}

export function jitterFrames(context: VFXContext, base: number, spread: number): number {
  if (spread <= 0) return base;
  return Math.max(1, Math.round(base + (context.random() * 2 - 1) * spread));
}

export function isThreeDLayer(layer: any): boolean {
  try {
    return layer.threeDLayer === true;
  } catch (e) {
    return false;
  }
}

export function transformGroup(layer: any): any {
  try {
    return layer.property("ADBE Transform Group");
  } catch (e) {
    return null;
  }
}

export function transformProperty(layer: any, matchName: string): any {
  var group = transformGroup(layer);
  if (!group) return null;
  try {
    return group.property(matchName);
  } catch (e) {
    return null;
  }
}

export function effectParade(layer: any): any {
  try {
    return layer.property("ADBE Effect Parade");
  } catch (e) {
    return null;
  }
}

// Try each candidate match name in turn. After Effects renames effects between
// versions, so a single hard-coded name is the most common cause of a preset
// silently doing nothing.
export function addEffect(
  layer: any,
  matchNames: string[],
  label: string,
  context: VFXContext
): any {
  var parade = effectParade(layer);
  if (!parade) {
    reportWarning(context, label + " skipped: the layer has no effect parade");
    return null;
  }
  for (var i = 0; i < matchNames.length; i++) {
    try {
      if (parade.canAddProperty && !parade.canAddProperty(matchNames[i])) continue;
    } catch (probeError) {
      // canAddProperty is unavailable on some hosts; fall through to addProperty.
    }
    try {
      var effect = parade.addProperty(matchNames[i]);
      if (effect) return effect;
    } catch (addError) {
      // Try the next candidate name.
    }
  }
  reportWarning(context, label + " skipped: this After Effects build has no matching effect");
  return null;
}

function resolveEffectProperty(effect: any, keys: any[]): any {
  for (var i = 0; i < keys.length; i++) {
    try {
      var property = effect.property(keys[i]);
      if (property) return property;
    } catch (e) {
      // Try the next candidate key.
    }
  }
  return null;
}

export function setEffectValue(
  effect: any,
  keys: any[],
  value: any,
  label: string,
  context: VFXContext
): boolean {
  if (!effect) return false;
  var property = resolveEffectProperty(effect, keys);
  if (!property) {
    reportWarning(context, label + " skipped: parameter is unavailable in this After Effects build");
    return false;
  }
  try {
    property.setValue(value);
    return true;
  } catch (e) {
    reportWarning(context, label + " could not be set: " + String(e));
    return false;
  }
}

export function animateEffectValue(
  effect: any,
  keys: any[],
  times: number[],
  values: any[],
  label: string,
  context: VFXContext
): any {
  if (!effect) return null;
  var property = resolveEffectProperty(effect, keys);
  if (!property) {
    reportWarning(context, label + " skipped: parameter is unavailable in this After Effects build");
    return null;
  }
  try {
    for (var i = 0; i < times.length; i++) {
      property.setValueAtTime(times[i], values[i]);
    }
    return property;
  } catch (e) {
    reportWarning(context, label + " could not be animated: " + String(e));
    return null;
  }
}

function dimensionCount(property: any): number {
  try {
    var value = property.value;
    if (value && typeof value.length === "number") return value.length;
  } catch (e) {
    // Fall through to the scalar default.
  }
  return 1;
}

// Bezier interpolation alone still reads as linear; the temporal ease is what
// makes a zoom punch feel like a punch.
export function applyEase(
  property: any,
  inInfluence: number,
  outInfluence: number,
  context: VFXContext,
  label: string
): void {
  if (!property) return;
  var dimensions = dimensionCount(property);
  var totalKeys = 0;
  try {
    totalKeys = property.numKeys;
  } catch (e) {
    return;
  }
  for (var key = 1; key <= totalKeys; key++) {
    try {
      property.setInterpolationTypeAtKey(
        key,
        KeyframeInterpolationType.BEZIER,
        KeyframeInterpolationType.BEZIER
      );
    } catch (interpolationError) {
      reportWarning(context, label + " ease skipped: " + String(interpolationError));
      return;
    }
    try {
      var easeIn = [];
      var easeOut = [];
      for (var d = 0; d < dimensions; d++) {
        easeIn.push(new KeyframeEase(0, clamp(inInfluence, 0.1, 100)));
        easeOut.push(new KeyframeEase(0, clamp(outInfluence, 0.1, 100)));
      }
      property.setTemporalEaseAtKey(key, easeIn, easeOut);
    } catch (easeError) {
      reportWarning(context, label + " ease skipped: " + String(easeError));
      return;
    }
  }
}

export function setLinearInterpolation(property: any): void {
  if (!property) return;
  try {
    for (var key = 1; key <= property.numKeys; key++) {
      property.setInterpolationTypeAtKey(
        key,
        KeyframeInterpolationType.LINEAR,
        KeyframeInterpolationType.LINEAR
      );
    }
  } catch (e) {
    // Interpolation type is cosmetic; the keyframe values are already written.
  }
}

export function setHoldInterpolation(property: any, key: number): void {
  if (!property) return;
  try {
    property.setInterpolationTypeAtKey(
      key,
      KeyframeInterpolationType.HOLD,
      KeyframeInterpolationType.HOLD
    );
  } catch (e) {
    // A missing HOLD constant only softens the freeze; it does not break it.
  }
}

// ---------------------------------------------------------------------------
// Multiplicative curves
//
// Several presets animate the same property (opacity is claimed by beat flash,
// strobe, picture flash and smooth transitions; scale by zoom punch and slow
// push-in). Writing them one after another means the last one silently wins, so
// each effect contributes a normalised curve and the layer commits the product.
// ---------------------------------------------------------------------------

export interface CurvePoint {
  time: number;
  value: number;
}

export interface AnimationCurve {
  points: CurvePoint[];
  linear: boolean;
}

export function makeCurve(points: CurvePoint[], linear: boolean): AnimationCurve {
  return { points: points, linear: linear };
}

export function sampleCurve(curve: AnimationCurve, time: number): number {
  var points = curve.points;
  if (points.length === 0) return 1;
  if (time <= points[0].time) return points[0].value;
  var last = points[points.length - 1];
  if (time >= last.time) return last.value;
  for (var i = 1; i < points.length; i++) {
    if (time <= points[i].time) {
      var previous = points[i - 1];
      var current = points[i];
      var span = current.time - previous.time;
      if (span <= 0) return current.value;
      var ratio = (time - previous.time) / span;
      return previous.value + (current.value - previous.value) * ratio;
    }
  }
  return last.value;
}

function sortedUniqueTimes(curves: AnimationCurve[]): number[] {
  var times: number[] = [];
  for (var i = 0; i < curves.length; i++) {
    for (var j = 0; j < curves[i].points.length; j++) {
      times.push(curves[i].points[j].time);
    }
  }
  times.sort(function (left, right) {
    return left - right;
  });
  var unique: number[] = [];
  for (var k = 0; k < times.length; k++) {
    if (k === 0 || times[k] - unique[unique.length - 1] > 1e-6) unique.push(times[k]);
  }
  return unique;
}

export function combineCurves(curves: AnimationCurve[]): { times: number[]; values: number[]; linear: boolean } {
  var times = sortedUniqueTimes(curves);
  var values: number[] = [];
  var linear = false;
  for (var i = 0; i < curves.length; i++) {
    if (curves[i].linear) linear = true;
  }
  for (var t = 0; t < times.length; t++) {
    var product = 1;
    for (var c = 0; c < curves.length; c++) {
      product *= sampleCurve(curves[c], times[t]);
    }
    values.push(product);
  }
  return { times: times, values: values, linear: linear };
}
