(function (thisObj) {// ----- EXTENDSCRIPT INCLUDES ------ //// JSON2 polyfill for ExtendScript (ES3)
// Standard json2.js by Douglas Crockford
// Bundled by Bolt CEP — included via @include directive

/* eslint-disable */
var JSON;
if (!JSON) {
  JSON = {};
}
(function () {
  "use strict";
  function f(n) {
    return n < 10 ? "0" + n : n;
  }
  if (typeof Date.prototype.toJSON !== "function") {
    Date.prototype.toJSON = function () {
      return isFinite(this.valueOf())
        ? this.getUTCFullYear() +
            "-" +
            f(this.getUTCMonth() + 1) +
            "-" +
            f(this.getUTCDate()) +
            "T" +
            f(this.getUTCHours()) +
            ":" +
            f(this.getUTCMinutes()) +
            ":" +
            f(this.getUTCSeconds()) +
            "Z"
        : null;
    };
    String.prototype.toJSON =
      Number.prototype.toJSON =
      Boolean.prototype.toJSON =
        function () {
          return this.valueOf();
        };
  }
  var cx, escapable, gap, indent, meta, rep;
  function quote(string) {
    escapable.lastIndex = 0;
    return escapable.test(string)
      ? '"' +
          string.replace(escapable, function (a) {
            var c = meta[a];
            return typeof c === "string"
              ? c
              : "\\u" + ("0000" + a.charCodeAt(0).toString(16)).slice(-4);
          }) +
          '"'
      : '"' + string + '"';
  }
  function str(key, holder) {
    var i,
      k,
      v,
      length,
      mind = gap,
      partial,
      value = holder[key];
    if (value && typeof value === "object" && typeof value.toJSON === "function") {
      value = value.toJSON(key);
    }
    if (typeof rep === "function") {
      value = rep.call(holder, key, value);
    }
    switch (typeof value) {
      case "string":
        return quote(value);
      case "number":
        return isFinite(value) ? String(value) : "null";
      case "boolean":
      case "null":
        return String(value);
      case "object":
        if (!value) {
          return "null";
        }
        gap += indent;
        partial = [];
        if (Object.prototype.toString.apply(value) === "[object Array]") {
          length = value.length;
          for (i = 0; i < length; i += 1) {
            partial[i] = str(i, value) || "null";
          }
          v =
            partial.length === 0
              ? "[]"
              : gap
              ? "[\n" + gap + partial.join(",\n" + gap) + "\n" + mind + "]"
              : "[" + partial.join(",") + "]";
          gap = mind;
          return v;
        }
        if (rep && typeof rep === "object") {
          length = rep.length;
          for (i = 0; i < length; i += 1) {
            if (typeof rep[i] === "string") {
              k = rep[i];
              v = str(k, value);
              if (v) {
                partial.push(quote(k) + (gap ? ": " : ":") + v);
              }
            }
          }
        } else {
          for (k in value) {
            if (Object.prototype.hasOwnProperty.call(value, k)) {
              v = str(k, value);
              if (v) {
                partial.push(quote(k) + (gap ? ": " : ":") + v);
              }
            }
          }
        }
        v =
          partial.length === 0
            ? "{}"
            : gap
            ? "{\n" + gap + partial.join(",\n" + gap) + "\n" + mind + "}"
            : "{" + partial.join(",") + "}";
        gap = mind;
        return v;
    }
  }
  if (typeof JSON.stringify !== "function") {
    escapable = /[\\\"\x00-\x1f\x7f-\x9f\u00ad\u0600-\u0604\u070f\u17b4\u17b5\u200c-\u200f\u2028-\u202f\u2060-\u206f\ufeff\ufff0-\uffff]/g;
    meta = {
      "\b": "\\b",
      "\t": "\\t",
      "\n": "\\n",
      "\f": "\\f",
      "\r": "\\r",
      '"': '\\"',
      "\\": "\\\\",
    };
    JSON.stringify = function (value, replacer, space) {
      var i;
      gap = "";
      indent = "";
      if (typeof space === "number") {
        for (i = 0; i < space; i += 1) {
          indent += " ";
        }
      } else if (typeof space === "string") {
        indent = space;
      }
      rep = replacer;
      if (
        replacer &&
        typeof replacer !== "function" &&
        (typeof replacer !== "object" || typeof replacer.length !== "number")
      ) {
        throw new Error("JSON.stringify");
      }
      return str("", { "": value });
    };
  }
  if (typeof JSON.parse !== "function") {
    JSON.parse = function (text, reviver) {
      var j;
      function walk(holder, key) {
        var k,
          v,
          value = holder[key];
        if (value && typeof value === "object") {
          for (k in value) {
            if (Object.prototype.hasOwnProperty.call(value, k)) {
              v = walk(value, k);
              if (v !== undefined) {
                value[k] = v;
              } else {
                delete value[k];
              }
            }
          }
        }
        return reviver.call(holder, key, value);
      }
      text = String(text);
      cx = /[\u0000\u00ad\u0600-\u0604\u070f\u17b4\u17b5\u200c-\u200f\u2028-\u202f\u2060-\u206f\ufeff\ufff0-\uffff]/g;
      cx.lastIndex = 0;
      if (cx.test(text)) {
        text = text.replace(cx, function (a) {
          return "\\u" + ("0000" + a.charCodeAt(0).toString(16)).slice(-4);
        });
      }
      if (/^[\],:{}\s]*$/.test(text.replace(/\\(?:["\\\/bfnrt]|u[0-9a-fA-F]{4})/g, "@").replace(/"[^"\\\n\r]*"|true|false|null|-?\d+(?:\.\d*)?(?:[eE][+\-]?\d+)?/g, "]").replace(/(?:^|:|,)(?:\s*\[)+/g, ""))) {
        j = eval("(" + text + ")");
        return typeof reviver === "function" ? walk({ "": j }, "") : j;
      }
      throw new SyntaxError("JSON.parse");
    };
  }
})();// ---------------------------------- //// ----- EXTENDSCRIPT PONYFILLS -----// ---------------------------------- //(function () {
  'use strict';

  // Shared ES3-safe helpers for the After Effects VFX engine.
  // Every After Effects DOM call funnels through here so that a failure is
  // reported as a warning instead of silently producing an unedited layer.

  function reportWarning(context, message) {
    if (!context || !context.warnings) return;
    for (var i = 0; i < context.warnings.length; i++) {
      if (context.warnings[i] === message) return;
    }
    context.warnings.push(message);
  }

  // Deterministic 32-bit LCG so a given seed always rebuilds the same edit.
  function makeRandom(seed) {
    var state = Math.floor(seed) % 2147483647;
    if (state <= 0) state += 2147483646;
    return function () {
      state = state * 16807 % 2147483647;
      return (state - 1) / 2147483646;
    };
  }
  function toNumber(value, fallback) {
    var parsed = typeof value === "number" ? value : parseFloat(value);
    if (typeof parsed !== "number" || isNaN(parsed) || !isFinite(parsed)) return fallback;
    return parsed;
  }

  // Style presets use several spellings for the same idea (`slow_factor` vs
  // `speed_factor`, `bar_height_pct` vs `aspect_ratio`). Read the first key that
  // is actually present rather than silently falling back to a default.
  function readNumber(config, names, fallback) {
    if (!config) return fallback;
    for (var i = 0; i < names.length; i++) {
      var raw = config[names[i]];
      if (raw !== undefined && raw !== null && raw !== "") {
        return toNumber(raw, fallback);
      }
    }
    return fallback;
  }
  function readString(config, names, fallback) {
    if (!config) return fallback;
    for (var i = 0; i < names.length; i++) {
      var raw = config[names[i]];
      if (raw !== undefined && raw !== null && raw !== "") return String(raw);
    }
    return fallback;
  }
  function clamp(value, minimum, maximum) {
    if (value < minimum) return minimum;
    if (value > maximum) return maximum;
    return value;
  }

  // Vary a value by +/- ratio so repeated cuts do not look mechanically identical.
  function jitter(context, base, ratio) {
    if (ratio <= 0) return base;
    return base * (1 - ratio + context.random() * ratio * 2);
  }
  function jitterFrames(context, base, spread) {
    return Math.max(1, Math.round(base + (context.random() * 2 - 1) * spread));
  }
  function isThreeDLayer(layer) {
    try {
      return layer.threeDLayer === true;
    } catch (e) {
      return false;
    }
  }
  function transformGroup(layer) {
    try {
      return layer.property("ADBE Transform Group");
    } catch (e) {
      return null;
    }
  }
  function transformProperty(layer, matchName) {
    var group = transformGroup(layer);
    if (!group) return null;
    try {
      return group.property(matchName);
    } catch (e) {
      return null;
    }
  }
  function effectParade(layer) {
    try {
      return layer.property("ADBE Effect Parade");
    } catch (e) {
      return null;
    }
  }

  // Try each candidate match name in turn. After Effects renames effects between
  // versions, so a single hard-coded name is the most common cause of a preset
  // silently doing nothing.
  function addEffect(layer, matchNames, label, context) {
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
  function resolveEffectProperty(effect, keys) {
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
  function setEffectValue(effect, keys, value, label, context) {
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
  function animateEffectValue(effect, keys, times, values, label, context) {
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
  function dimensionCount(property) {
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
  function applyEase(property, inInfluence, outInfluence, context, label) {
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
        property.setInterpolationTypeAtKey(key, KeyframeInterpolationType.BEZIER, KeyframeInterpolationType.BEZIER);
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
  function setLinearInterpolation(property) {
    if (!property) return;
    try {
      for (var key = 1; key <= property.numKeys; key++) {
        property.setInterpolationTypeAtKey(key, KeyframeInterpolationType.LINEAR, KeyframeInterpolationType.LINEAR);
      }
    } catch (e) {
      // Interpolation type is cosmetic; the keyframe values are already written.
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

  function makeCurve(points, linear) {
    return {
      points: points,
      linear: linear
    };
  }
  function sampleCurve(curve, time) {
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
  function sortedUniqueTimes(curves) {
    var times = [];
    for (var i = 0; i < curves.length; i++) {
      for (var j = 0; j < curves[i].points.length; j++) {
        times.push(curves[i].points[j].time);
      }
    }
    times.sort(function (left, right) {
      return left - right;
    });
    var unique = [];
    for (var k = 0; k < times.length; k++) {
      if (k === 0 || times[k] - unique[unique.length - 1] > 1e-6) unique.push(times[k]);
    }
    return unique;
  }
  function combineCurves(curves) {
    var times = sortedUniqueTimes(curves);
    var values = [];
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
    return {
      times: times,
      values: values,
      linear: linear
    };
  }

  // VFX Engine — applies visual effects to After Effects layers via ExtendScript.
  //
  // Two families of effect live here:
  //   * per-cut effects, applied to the clip layer that starts on a beat;
  //   * comp-wide effects, applied once to a single adjustment layer.
  // Grain, letterbox, light leaks, light wrap, VHS and smoke belong to the second
  // family: applying them per cut used to create hundreds of duplicate solids.

  // ---------------------------------------------------------------------------
  // Layer plan — composes properties that more than one preset wants to animate
  // ---------------------------------------------------------------------------

  function createLayerPlan(layer) {
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
      layerOut: layerOut
    };
  }
  function commitLayerPlan(layer, plan, context) {
    if (plan.opacityCurves.length > 0) {
      var opacity = transformProperty(layer, "ADBE Opacity");
      if (!opacity) {
        reportWarning(context, "Opacity animation skipped: the layer has no opacity property");
      } else {
        var opacityTrack = combineCurves(plan.opacityCurves);
        try {
          for (var o = 0; o < opacityTrack.times.length; o++) {
            opacity.setValueAtTime(opacityTrack.times[o], clamp(plan.baseOpacity * opacityTrack.values[o], 0, 100));
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
  function clampToLayer(plan, time) {
    return clamp(time, plan.layerIn, plan.layerOut);
  }

  // ---------------------------------------------------------------------------
  // Time remapping
  // ---------------------------------------------------------------------------

  // Time remap VALUES are source time, not comp time. The previous build wrote
  // comp time into them, which made every speed effect show the wrong frames.
  function resetTimeRemap(layer, context, label) {
    var remap = null;
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
  function sourceDuration(layer, fallback) {
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
  function layerTimes(layer) {
    return {
      start: toNumber(layer.startTime, 0),
      inPoint: toNumber(layer.inPoint, 0),
      outPoint: toNumber(layer.outPoint, 0)
    };
  }

  // ---------------------------------------------------------------------------
  // Per-cut effects
  // ---------------------------------------------------------------------------

  function applyZoomPunch(config, beatTime, context, plan) {
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
    plan.scaleCurves.push(makeCurve([{
      time: start,
      value: 1
    }, {
      time: peak,
      value: punchFactor
    }, {
      time: release,
      value: 1
    }], false));
  }
  function applySlowPushIn(config, plan) {
    var startScale = readNumber(config, ["scale_start"], 100);
    var endScale = readNumber(config, ["scale_end", "target_scale"], 110);
    if (plan.layerOut <= plan.layerIn) return;
    plan.scaleCurves.push(makeCurve([{
      time: plan.layerIn,
      value: startScale / 100
    }, {
      time: plan.layerOut,
      value: endScale / 100
    }], true));
  }
  function applyBeatFlash(config, beatTime, context, plan) {
    var fps = context.fps;
    var peak = clamp(readNumber(config, ["opacity_peak", "peak_opacity"], 60), 0, 100) / 100;
    var frames = Math.max(1, readNumber(config, ["duration_frames"], 2));
    var start = clampToLayer(plan, beatTime);
    var dip = clampToLayer(plan, beatTime + frames / (2 * fps));
    var end = clampToLayer(plan, beatTime + frames / fps);
    if (end <= start) return;
    plan.opacityCurves.push(makeCurve([{
      time: start,
      value: 1
    }, {
      time: dip,
      value: peak
    }, {
      time: end,
      value: 1
    }], true));
  }
  function applyStrobe(config, beatTime, context, plan) {
    var fps = context.fps;
    var frequency = clamp(readNumber(config, ["frequency_hz"], 12), 1, fps / 2);
    var peak = clamp(readNumber(config, ["opacity_peak"], 100), 0, 100) / 100;
    var floorValue = clamp(readNumber(config, ["opacity_floor"], 0), 0, 100) / 100;
    var cycles = Math.max(1, Math.round(readNumber(config, ["cycles"], 3)));
    var halfPeriod = 1 / (frequency * 2);
    var points = [];
    var time = beatTime;
    for (var cycle = 0; cycle < cycles; cycle++) {
      points.push({
        time: clampToLayer(plan, time),
        value: peak
      });
      time += halfPeriod;
      points.push({
        time: clampToLayer(plan, time),
        value: floorValue
      });
      time += halfPeriod;
    }
    points.push({
      time: clampToLayer(plan, time),
      value: 1
    });
    if (points[points.length - 1].time <= points[0].time) return;
    plan.opacityCurves.push(makeCurve(points, true));
  }

  // A picture flash is a white frame punched over the cut, not the clip fading
  // in from nothing (which is what the previous implementation actually did).
  // One solid carries every flash: creating a fresh solid per cut used to grow
  // the comp by one layer per flashed beat.
  var FLASH_LAYER_NAME = "FlagshipEditor_Flash";
  function findOrCreateFlashSolid(context) {
    var comp = context.comp;
    var flash = null;
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
  function applyPictureFlash(layer, config, beatTime, context) {
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
  function applySmoothTransitions(config, context, plan) {
    var fps = context.fps;
    var frames = Math.max(1, readNumber(config, ["fade_frames", "duration_frames"], 4));
    var fade = frames / fps;
    var span = plan.layerOut - plan.layerIn;
    if (span <= 0) return;
    // Never let the two fades cross on a very short cut.
    if (fade * 2 > span) fade = span / 2;
    plan.opacityCurves.push(makeCurve([{
      time: plan.layerIn,
      value: 0
    }, {
      time: plan.layerIn + fade,
      value: 1
    }, {
      time: plan.layerOut - fade,
      value: 1
    }, {
      time: plan.layerOut,
      value: 0
    }], false));
  }

  // Keyframed shake with exponential decay. The old wiggle() expression ran for
  // the whole layer and re-evaluated on every frame of every clip.
  function applyCameraShake(layer, config, beatTime, context) {
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
    var origin;
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
  function applyWhipPan(layer, config, beatTime, context) {
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
    var origin;
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
  function countChannelGhosts(comp) {
    var count = 0;
    try {
      for (var index = 1; index <= comp.numLayers; index++) {
        var name = String(comp.layer(index).name);
        for (var s = 0; s < CHANNEL_GHOST_SUFFIXES.length; s++) {
          var suffix = CHANNEL_GHOST_SUFFIXES[s];
          if (name.length >= suffix.length && name.substring(name.length - suffix.length) === suffix) {
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
  function addChannelGhost(layer, context, channel, suffix) {
    var comp = context.comp;
    var ghost = null;
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
  function applyRGBSplit(layer, config, beatTime, context) {
    if (!context.comp) return;
    if (countChannelGhosts(context.comp) >= MAX_CHANNEL_GHOST_LAYERS) {
      reportWarning(context, "RGB split capped: the comp already holds " + MAX_CHANNEL_GHOST_LAYERS + " channel layers; later cuts skip the split");
      return;
    }
    var offset = readNumber(config, ["displacement_px", "offset_px"], 4);
    var red = addChannelGhost(layer, context, "red", CHANNEL_GHOST_SUFFIXES[0]);
    var blue = addChannelGhost(layer, context, "blue", CHANNEL_GHOST_SUFFIXES[1]);
    var ghosts = [{
      layer: red,
      sign: 1
    }, {
      layer: blue,
      sign: -1
    }];
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
  function applyGlitch(layer, config, beatTime, context) {
    var fps = context.fps;
    var frames = Math.max(1, readNumber(config, ["duration_frames"], 3));
    var duration = frames / fps;
    var maxOffset = readNumber(config, ["displacement_px"], 15);
    var jittered = maxOffset * (0.7 + context.random() * 0.6);

    // Chromatic tear on the cut.
    applyRGBSplit(layer, {
      displacement_px: jittered
    }, beatTime, context);

    // Turbulent Displace is self-contained. Displacement Map needs a source layer
    // and silently does nothing without one, which is why the old glitch was
    // invisible.
    var displace = addEffect(layer, ["ADBE Turbulent Displace", "ADBE Wave Warp"], "Glitch displacement", context);
    if (!displace) return;
    var amount = animateEffectValue(displace, ["ADBE Turbulent Displace-0002", 2], [beatTime, beatTime + duration], [jittered, 0], "Glitch displacement amount", context);
    setLinearInterpolation(amount);
    setEffectValue(displace, ["ADBE Turbulent Displace-0003", 3], Math.max(2, jittered), "Glitch displacement size", context);
    var evolution = animateEffectValue(displace, ["ADBE Turbulent Displace-0006", 6], [beatTime, beatTime + duration], [0, 360], "Glitch displacement evolution", context);
    setLinearInterpolation(evolution);
  }
  function applySpeedRamp(layer, config, beatTime, context) {
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
    var sourceAtRampEnd = clamp(sourceAtRampStart + (rampEnd - rampStart) * ((rateIn + rateOut) / 2), 0, duration);
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
  function applySlowMo(layer, config, beatTime, context) {
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
    var sourceAtRampEnd = clamp(sourceAtSlowStart + (rampEnd - slowStart) * ((1 + rate) / 2), 0, duration);
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
  function applyFreezeFrame(layer, config, beatTime, context) {
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
  function applyFaceMask(layer, config, beatTime, context) {
    var fps = context.fps;
    var radius = readNumber(config, ["blur_radius", "intensity"], 40);
    var fadeFrames = Math.max(1, readNumber(config, ["fade_out_frames"], 10));
    var mosaic = addEffect(layer, ["ADBE Mosaic"], "Face mask", context);
    if (!mosaic) return;
    var blocks = clamp(Math.round(200 - radius * 2), 6, 200);
    var horizontal = animateEffectValue(mosaic, ["ADBE Mosaic-0001", 1], [beatTime, beatTime + fadeFrames / fps], [blocks, 200], "Face mask horizontal blocks", context);
    applyEase(horizontal, 30, 60, context, "Face mask");
    var vertical = animateEffectValue(mosaic, ["ADBE Mosaic-0002", 2], [beatTime, beatTime + fadeFrames / fps], [blocks, 200], "Face mask vertical blocks", context);
    applyEase(vertical, 30, 60, context, "Face mask");
  }
  function applyDepthBlur(layer, config, beatTime, context) {
    var fps = context.fps;
    var radius = readNumber(config, ["blur_radius"], 30);
    var fadeFrames = Math.max(1, readNumber(config, ["fade_frames"], 15));
    var blur = addEffect(layer, ["ADBE Camera Lens Blur", "ADBE Gaussian Blur 2", "ADBE Gaussian Blur"], "Depth blur", context);
    if (!blur) return;
    var amount = animateEffectValue(blur, ["ADBE Camera Lens Blur-0001", "ADBE Gaussian Blur 2-0001", "ADBE Gaussian Blur-0001", 1], [beatTime, beatTime + fadeFrames / fps], [radius, 0], "Depth blur radius", context);
    applyEase(amount, 20, 70, context, "Depth blur");
  }
  function applySelectiveColor(layer, config, beatTime, context) {
    var fps = context.fps;
    var boost = readNumber(config, ["saturation_boost"], 25);
    var desaturateRest = readNumber(config, ["desaturate_rest"], 0);
    var fadeFrames = Math.max(1, readNumber(config, ["fade_frames"], 10));
    var hueSat = addEffect(layer, ["ADBE HUE SATURATION", "ADBE Hue/Saturation"], "Selective color", context);
    if (!hueSat) return;
    // Master Saturation is parameter 4 (1 Channel Control, 2 Channel Range,
    // 3 Master Hue, 4 Master Saturation, 5 Master Lightness).
    var saturation = animateEffectValue(hueSat, ["ADBE HUE SATURATION-0004", 4], [beatTime, beatTime + fadeFrames / fps], [boost, desaturateRest], "Selective color saturation", context);
    applyEase(saturation, 30, 60, context, "Selective color");
    var hueShift = readNumber(config, ["hue_shift"], 0);
    if (hueShift !== 0) {
      var hue = animateEffectValue(hueSat, ["ADBE HUE SATURATION-0003", 3], [beatTime, beatTime + fadeFrames / fps], [hueShift, 0], "Selective color hue", context);
      applyEase(hue, 30, 60, context, "Selective color");
    }
  }
  function applyMaskTransition(layer, config, beatTime, context) {
    var fps = context.fps;
    var frames = Math.max(1, readNumber(config, ["duration_frames", "wipe_frames"], 5));
    var angle = readNumber(config, ["angle_degrees"], 90);
    var feather = readNumber(config, ["feather"], 12);
    var wipe = addEffect(layer, ["ADBE Linear Wipe"], "Mask transition", context);
    if (!wipe) return;
    // Transition Completion 100 hides the layer, so a reveal runs 100 -> 0.
    var completion = animateEffectValue(wipe, ["ADBE Linear Wipe-0001", 1], [beatTime, beatTime + frames / fps], [100, 0], "Mask transition completion", context);
    setLinearInterpolation(completion);
    setEffectValue(wipe, ["ADBE Linear Wipe-0002", 2], angle, "Mask transition angle", context);
    setEffectValue(wipe, ["ADBE Linear Wipe-0003", 3], feather, "Mask transition feather", context);
  }

  // ---------------------------------------------------------------------------
  // Comp-wide effects — created once on a shared adjustment layer
  // ---------------------------------------------------------------------------

  function addAdjustmentLayer(context, name) {
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
  function applyFilmGrain(config, context) {
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
  function applyVHSOverlay(config, context) {
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
  function applyLetterbox(config, context) {
    var comp = context.comp;
    if (!comp) return;
    var aspect = readNumber(config, ["aspect_ratio"], 2.39);
    var barPercent = readNumber(config, ["bar_height_pct"], 0);
    var barHeight;
    if (barPercent > 0) {
      barHeight = Math.round(comp.height * barPercent / 100);
    } else {
      var visibleHeight = comp.width / (aspect > 0 ? aspect : 2.39);
      barHeight = Math.round(Math.max(0, (comp.height - visibleHeight) / 2));
    }
    if (barHeight < 1) return;
    var colorValue = readString(config, ["bars_color"], "black") === "black" ? 0 : 1;
    var color = [colorValue, colorValue, colorValue];
    var bars = [{
      name: "FlagshipEditor_LetterboxTop",
      y: barHeight / 2
    }, {
      name: "FlagshipEditor_LetterboxBottom",
      y: comp.height - barHeight / 2
    }];
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
  function applyLightLeaks(config, context) {
    var comp = context.comp;
    if (!comp) return;
    var opacity = clamp(readNumber(config, ["opacity"], 45), 0, 100);
    // frequency is leaks per minute; one leak pulse is roughly 1.5s.
    var frequency = clamp(readNumber(config, ["frequency"], 6), 1, 60);
    var interval = 60 / frequency;
    var pulse = Math.min(1.5, interval * 0.6);
    var leak = null;
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
  function applyLightWrap(config, context) {
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
  function applySmokeFog(config, context) {
    var comp = context.comp;
    if (!comp) return;
    var opacity = clamp(readNumber(config, ["opacity"], 25), 0, 100);
    var density = clamp(readNumber(config, ["density"], 50), 0, 100);
    var tint = readString(config, ["color"], "grey");
    var base = tint === "white" ? 0.9 : tint === "black" ? 0.1 : 0.55;
    var fog = null;
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
    var evolution = animateEffectValue(noise, ["ADBE Fractal Noise-0010", 10], [0, comp.duration], [0, 360 * Math.max(1, comp.duration / 20)], "Smoke evolution", context);
    setLinearInterpolation(evolution);
  }

  // Color Grading — applies LUTs and colour correction through adjustment layers.

  var LUT_LAYER_PREFIX = "FlagshipEditor_LUT";
  var LUMETRI_MATCH_NAMES = ["ADBE Lumetri Color", "ADBE Lumetri Color 2", "ADBE Lumetri"];
  function applyColorGrading(comp, sections, config, context) {
    if (!config || config.enabled === false) return;
    var opacity = clamp(readNumber(config, ["opacity"], 100), 0, 100);
    var applied = 0;
    if (config.section_luts) {
      for (var i = 0; i < sections.length; i++) {
        var section = sections[i];
        var lutName = config.section_luts[section.type];
        if (!lutName) continue;
        var sectionLayer = createLUTAdjustmentLayer(comp, toNumber(section.start, 0), toNumber(section.end, 0) - toNumber(section.start, 0), String(lutName), opacity, config.extension_root, LUT_LAYER_PREFIX + "_" + String(section.type).toUpperCase(), context);
        if (sectionLayer) {
          applyColorParams(sectionLayer, config.params, context);
          applied++;
        }
      }
    }
    if (config.global_lut) {
      var globalLayer = createLUTAdjustmentLayer(comp, 0, toNumber(comp.duration, 0), String(config.global_lut), opacity, config.extension_root, LUT_LAYER_PREFIX + "_GLOBAL", context);
      if (globalLayer) {
        applyColorParams(globalLayer, config.params, context);
        applied++;
      }
    }
    if (applied === 0 && (config.global_lut || config.section_luts)) {
      reportWarning(context, "Colour grading produced no graded layers");
    }
  }
  function findLUTFile(extensionRoot, lutName) {
    // Folder() resolves the platform separators for us, so the same code works
    // for C:\... on Windows and /Users/... on macOS.
    var lutsFolder = new Folder(extensionRoot + "/luts");
    var candidate = new File(lutsFolder.fsName + "/" + lutName);
    if (candidate.exists) return candidate;
    var flat = new File(extensionRoot + "/luts/" + lutName);
    if (flat.exists) return flat;
    return null;
  }
  function createLUTAdjustmentLayer(comp, startTime, duration, lutName, opacity, extensionRoot, layerName, context) {
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
    var solid = null;
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
  function addLumetri(layer, lutName, context) {
    var parade = null;
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
  function setLUTPath(lumetri, lutFile, lutName, context) {
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
  function removeLayer(layer, context) {
    try {
      layer.remove();
    } catch (removeError) {
      reportWarning(context, "An unused grading layer could not be removed: " + String(removeError));
    }
  }

  // Temperature, contrast and saturation are written to the LUT layer this call
  // created, never to whatever happens to sit at the top of the comp.
  function applyColorParams(layer, params, context) {
    if (!params) return;
    var parade = null;
    try {
      parade = layer.property("ADBE Effect Parade");
    } catch (paradeError) {
      reportWarning(context, "Colour parameters skipped: " + String(paradeError));
      return;
    }
    if (!parade) return;
    var lumetri = null;
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
  function setLumetriParam(lumetri, keys, value, label, context) {
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

  // Element 3D bridge — detects Video Copilot Element 3D and sets up the scene.

  var ELEMENT_MATCH_NAMES = ["VideoCopilot Element", "Video Copilot Element 3D", "ADBE Element"];

  // Cached so a build with many sections probes the host only once.
  var detectedMatchName = null;
  var detectionRan = false;
  function detectElement3D(comp) {
    if (detectionRan) return detectedMatchName;
    detectionRan = true;
    detectedMatchName = null;
    var probe = null;
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
  function resetElement3DDetection() {
    detectionRan = false;
    detectedMatchName = null;
  }
  function createElement3DSolid(comp, config, context) {
    var matchName = detectElement3D(comp);
    if (!matchName) {
      reportWarning(context, "Element 3D is not installed; the 3D solid and camera were skipped");
      return;
    }
    var solidName = readString(config, ["solid_name"], "FlagshipEditor_3D_Solid");
    var solid = null;
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
  function createParallaxCamera(comp, config, context) {
    for (var i = 1; i <= comp.numLayers; i++) {
      try {
        if (comp.layer(i) instanceof CameraLayer) return;
      } catch (layerError) {
        // A layer that cannot be inspected is not a camera we created.
      }
    }
    var camera = null;
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
      position.expression = "var base = value;\n" + "var amp = " + amplitude + ";\n" + "[base[0] + Math.sin(time * 0.5) * amp, base[1] + Math.cos(time * 0.35) * amp * 0.4, base[2] + Math.sin(time * 0.5) * amp];";
    } catch (expressionError) {
      reportWarning(context, "3D parallax expression could not be applied: " + String(expressionError));
    }
  }

  function _typeof(o) { "@babel/helpers - typeof"; return _typeof = "function" == typeof Symbol && "symbol" == typeof Symbol.iterator ? function (o) { return typeof o; } : function (o) { return o && "function" == typeof Symbol && o.constructor === Symbol && o !== Symbol.prototype ? "symbol" : typeof o; }, _typeof(o); }
  // Effects animated on the clip layer that starts on the beat.
  var PER_CUT_EFFECTS = ["zoom_punch", "camera_shake", "whip_pan", "glitch_effect", "speed_ramp", "freeze_frame", "face_mask", "slow_mo", "beat_flash", "depth_blur", "smooth_transitions", "mask_transition", "picture_flash", "selective_color", "slow_push_in", "rgb_split", "strobe"];

  // Effects that belong to the whole edit. Building these per cut is what used to
  // leave hundreds of duplicate solids in the project.
  var COMP_WIDE_EFFECTS = ["smoke_fog", "light_leaks", "vhs_overlay", "film_grain", "letterbox", "light_wrap"];
  var MAX_CUTS_PER_BATCH = 30;
  var activeBuild = null;
  function isArray(value) {
    return Object.prototype.toString.call(value) === "[object Array]";
  }
  function beginComp(duration, audioPath, runtimeStyle, params, element3D, sections, extensionPath, mediaProfile, tempo) {
    var comp = null;
    var clipsFolder = null;
    var audioItem = null;
    try {
      if (activeBuild) cleanupActiveBuild();
      resetElement3DDetection();
      var project = app.project;
      if (!project) return JSON.stringify({
        __error: "No After Effects project is open"
      });
      if (!isFinite(duration) || duration <= 0) {
        return JSON.stringify({
          __error: "The analyzed music duration is invalid"
        });
      }
      var audioFile = new File(audioPath);
      if (!audioFile.exists) {
        return JSON.stringify({
          __error: "Music file is missing: " + audioPath
        });
      }
      var profile = resolveCompProfile(project, mediaProfile);
      app.beginUndoGroup("FlagshipEditor Build");
      comp = project.items.addComp("FlagshipEditor_Edit", profile.width, profile.height, 1, duration, profile.fps);
      clipsFolder = project.items.addFolder("FlagshipEditor_Clips");
      audioItem = importFile(audioPath);
      if (!audioItem) throw new Error("After Effects could not import the music file");
      var audioLayer = comp.layers.add(audioItem);
      audioLayer.name = "MUSIC";
      var safeParams = normalizeParameters(params);
      var configuredStyle = applyParameterOverrides(runtimeStyle, safeParams, element3D);
      if (configuredStyle.color_grading) {
        configuredStyle.color_grading.extension_root = extensionPath;
      }
      activeBuild = {
        comp: comp,
        clipsFolder: clipsFolder,
        audioItem: audioItem,
        styleConfig: configuredStyle,
        sections: sections || [],
        footagePaths: [],
        footageItems: [],
        added: 0,
        warnings: [],
        context: {
          comp: comp,
          fps: profile.fps,
          tempo: toNumber(tempo, 0),
          warnings: [],
          random: makeRandom(safeParams.seed)
        }
      };
      activeBuild.context.warnings = activeBuild.warnings;
      warnUnimplementedEffects(configuredStyle, activeBuild.warnings);
      return JSON.stringify({
        __result: {
          started: true,
          compName: comp.name,
          width: profile.width,
          height: profile.height,
          fps: profile.fps
        }
      });
    } catch (e) {
      removeProjectItem(comp);
      removeProjectItem(clipsFolder);
      removeProjectItem(audioItem);
      endUndoGroupSafely();
      activeBuild = null;
      return JSON.stringify({
        __error: String(e)
      });
    }
  }
  function appendCutBatch(cuts) {
    try {
      if (!activeBuild || !activeBuild.comp) {
        return JSON.stringify({
          __error: "No FlagshipEditor composition build is active"
        });
      }
      if (!isArray(cuts)) {
        return JSON.stringify({
          __error: "appendCutBatch expects an array of cuts"
        });
      }
      if (cuts.length > MAX_CUTS_PER_BATCH) {
        return JSON.stringify({
          __error: "A cut batch is limited to " + MAX_CUTS_PER_BATCH + " clips; received " + cuts.length
        });
      }
      var added = 0;
      var skipped = 0;
      for (var i = 0; i < cuts.length; i++) {
        var cut = cuts[i];
        if (!cut || !cut.clipPath || cut.endTime <= cut.beatTime) {
          activeBuild.warnings.push("Cut skipped: " + (cut && cut.clipName ? cut.clipName : "unnamed") + " has no usable time range");
          skipped++;
          continue;
        }
        var clipItem = getOrImportFootage(cut.clipPath);
        if (!clipItem) {
          activeBuild.warnings.push("Missing clip: " + cut.clipPath);
          skipped++;
          continue;
        }
        // AE evaluates an un-remapped footage layer at `compTime - startTime`.
        // Moving startTime back by sourceStart therefore makes the selected
        // best-moment frame land exactly on the cut's beatTime. Time-remap VFX
        // use the same relationship (`inPoint - startTime`) as their source-time
        // origin, so speed ramps, slow motion and freeze frames inherit the
        // selected offset instead of resetting to source time zero.
        var clipDuration = Math.max(0, toNumber(clipItem.duration, 0));
        var sourceStart = Math.max(0, toNumber(cut.sourceStart, 0));
        if (clipDuration > 0) sourceStart = Math.min(sourceStart, clipDuration);
        var fallbackSourceEnd = clipDuration > 0 ? clipDuration : sourceStart + (cut.endTime - cut.beatTime);
        var sourceEnd = Math.max(sourceStart, toNumber(cut.sourceEnd, fallbackSourceEnd));
        if (clipDuration > 0) sourceEnd = Math.min(sourceEnd, clipDuration);
        if (sourceEnd <= sourceStart) {
          activeBuild.warnings.push("Cut skipped: " + cut.clipName + " has no usable selected source window");
          skipped++;
          continue;
        }
        if (sourceEnd - sourceStart + 0.001 < cut.endTime - cut.beatTime) {
          activeBuild.warnings.push("Selected source window is shorter than the timeline slot for " + cut.clipName + "; After Effects will preserve the target slot and may hold the final source frame");
        }
        var clipLayer = activeBuild.comp.layers.add(clipItem);
        clipLayer.startTime = cut.beatTime - sourceStart;
        clipLayer.inPoint = cut.beatTime;
        clipLayer.outPoint = Math.min(cut.endTime, activeBuild.comp.duration);
        clipLayer.name = cut.clipName + " [" + cut.sectionType + "]";
        clipLayer.comment = cutTag(cut.beatTime, cut.sectionType);
        try {
          applyVFXToLayer(clipLayer, activeBuild.styleConfig, cut.sectionType, cut.beatTime, activeBuild.context);
        } catch (vfxError) {
          activeBuild.warnings.push("VFX skipped on " + cut.clipName + ": " + String(vfxError));
        }
        added++;
        activeBuild.added++;
      }
      return JSON.stringify({
        __result: {
          added: added,
          skipped: skipped,
          totalAdded: activeBuild.added
        }
      });
    } catch (e) {
      return JSON.stringify({
        __error: String(e)
      });
    }
  }
  function finishComp() {
    try {
      if (!activeBuild || !activeBuild.comp) {
        return JSON.stringify({
          __error: "No FlagshipEditor composition build is active"
        });
      }
      if (activeBuild.added < 1) {
        cleanupActiveBuild();
        return JSON.stringify({
          __error: "After Effects could not import any selected clips"
        });
      }
      var build = activeBuild;
      applyCompWideVFX(build.styleConfig, build.context);
      if (build.styleConfig.color_grading) {
        applyColorGrading(build.comp, build.sections, build.styleConfig.color_grading, build.context);
      }
      if (build.styleConfig.element_3d && build.styleConfig.element_3d.enabled) {
        try {
          createElement3DSolid(build.comp, build.styleConfig.element_3d, build.context);
        } catch (elementError) {
          build.warnings.push("3D setup skipped: " + String(elementError));
        }
      }
      writeSectionMarkers(build.comp, build.sections, build.warnings);
      try {
        build.comp.openInViewer();
      } catch (viewerError) {
        build.warnings.push("The comp was built but could not be opened: " + String(viewerError));
      }
      var result = {
        message: "Comp created: " + build.comp.name,
        clipsAdded: build.added,
        warnings: uniqueWarningStrings(build.warnings)
      };
      activeBuild = null;
      endUndoGroupSafely();
      return JSON.stringify({
        __result: result
      });
    } catch (e) {
      endUndoGroupSafely();
      return JSON.stringify({
        __error: String(e)
      });
    }
  }
  function abortComp() {
    cleanupActiveBuild();
    return JSON.stringify({
      __result: {
        aborted: true
      }
    });
  }
  function writeSectionMarkers(comp, sections, warnings) {
    if (!sections || !sections.length) return;
    var written = [];
    for (var i = 0; i < sections.length; i++) {
      var section = sections[i];
      var start = toNumber(section.start, -1);
      if (start < 0 || start > comp.duration) continue;
      var duplicate = false;
      for (var j = 0; j < written.length; j++) {
        if (Math.abs(written[j] - start) < 0.001) duplicate = true;
      }
      if (duplicate) continue;
      try {
        comp.markerProperty.setValueAtTime(start, new MarkerValue(String(section.type).toUpperCase()));
        written.push(start);
      } catch (markerError) {
        warnings.push("Section marker skipped at " + start.toFixed(2) + "s: " + String(markerError));
      }
    }
  }

  // Detect the edit format from the analysed media first: the Python engine
  // already probed every clip, which is more reliable than guessing from
  // whichever item happens to sit first in the project panel.
  // Snap fractional frame rates (59.94, 29.97, 23.976) to their integer
  // counterparts so the comp runs at a clean fps and audio stays sample-
  // accurate. 59.94 → 60, 29.97 → 30, 23.976 → 24.
  function snapFps(value) {
    if (value <= 0) return 30;
    var rounded = Math.round(value);
    // Only snap when within 0.15 of the integer (59.94 → 60, not 58 → 60).
    if (Math.abs(value - rounded) < 0.15) return rounded;
    return rounded;
  }
  function resolveCompProfile(project, mediaProfile) {
    var width = 1920;
    var height = 1080;
    var fps = 30;
    if (mediaProfile) {
      var profileWidth = toNumber(mediaProfile.width, 0);
      var profileHeight = toNumber(mediaProfile.height, 0);
      var profileFps = toNumber(mediaProfile.fps, 0);
      if (profileWidth > 0 && profileHeight > 0) {
        width = Math.round(profileWidth);
        height = Math.round(profileHeight);
      }
      if (profileFps > 0) fps = snapFps(profileFps);
      if (profileWidth > 0 && profileHeight > 0 && profileFps > 0) {
        return {
          width: width,
          height: height,
          fps: fps
        };
      }
    }
    var scanned = scanProjectForFootageProfile(project);
    if (scanned) {
      if (scanned.width > 0 && scanned.height > 0 && !(mediaProfile && toNumber(mediaProfile.width, 0) > 0)) {
        width = scanned.width;
        height = scanned.height;
      }
      if (scanned.fps > 0 && !(mediaProfile && toNumber(mediaProfile.fps, 0) > 0)) {
        fps = snapFps(scanned.fps);
      }
    }
    return {
      width: width,
      height: height,
      fps: fps
    };
  }
  function scanProjectForFootageProfile(project) {
    var total = 0;
    try {
      total = toNumber(project.numItems, 0);
    } catch (countError) {
      return null;
    }
    if (total < 1) return null;
    for (var i = 1; i <= total; i++) {
      try {
        var item = project.item(i);
        if (!item || !item.hasVideo) continue;
        var itemWidth = toNumber(item.width, 0);
        var itemHeight = toNumber(item.height, 0);
        var itemFps = toNumber(item.frameRate, 0);
        if (itemWidth > 0 && itemHeight > 0 && itemFps > 0) {
          return {
            width: Math.round(itemWidth),
            height: Math.round(itemHeight),
            fps: itemFps
          };
        }
      } catch (itemError) {
        // A project item that cannot be inspected is simply not a candidate.
      }
    }
    return null;
  }
  function getOrImportFootage(path) {
    for (var i = 0; i < activeBuild.footagePaths.length; i++) {
      if (activeBuild.footagePaths[i] === path) return activeBuild.footageItems[i];
    }
    var item = importFile(path);
    if (!item) return null;
    try {
      item.parentFolder = activeBuild.clipsFolder;
    } catch (folderError) {
      activeBuild.warnings.push("Clip could not be filed into the clips folder: " + path);
    }
    activeBuild.footagePaths.push(path);
    activeBuild.footageItems.push(item);
    return item;
  }
  function cleanupActiveBuild() {
    if (!activeBuild) return;
    removeProjectItem(activeBuild.comp);
    for (var i = activeBuild.footageItems.length - 1; i >= 0; i--) {
      removeProjectItem(activeBuild.footageItems[i]);
    }
    removeProjectItem(activeBuild.audioItem);
    removeProjectItem(activeBuild.clipsFolder);
    activeBuild = null;
    endUndoGroupSafely();
  }
  function endUndoGroupSafely() {
    try {
      app.endUndoGroup();
    } catch (undoErr) {}
  }
  function removeProjectItem(item) {
    if (!item) return;
    try {
      item.remove();
    } catch (e) {}
  }
  function uniqueWarningStrings(values) {
    var result = [];
    for (var i = 0; i < values.length; i++) {
      var found = false;
      for (var j = 0; j < result.length; j++) {
        if (result[j] === values[i]) found = true;
      }
      if (!found) result.push(values[i]);
    }
    return result;
  }
  function swapCut(beatTime, sectionType, clipPath, clipName, endTime, sourceStart, sourceEnd) {
    try {
      var comp = findGeneratedComp();
      if (!comp) return JSON.stringify({
        __result: {
          updated: 0,
          message: "Generated comp not found"
        }
      });
      var layer = findCutLayer(comp, beatTime, sectionType);
      if (!layer) return JSON.stringify({
        __result: {
          updated: 0,
          message: "Cut layer not found"
        }
      });
      var rawSourceStart = Math.max(0, toNumber(sourceStart, 0));
      var rawSourceEnd = toNumber(sourceEnd, 0);
      if (rawSourceEnd <= rawSourceStart) {
        return JSON.stringify({
          __error: "Replacement clip has no usable selected source window"
        });
      }
      var existingFootage = findProjectFootage(clipPath);
      var footage = findOrImportProjectFootage(clipPath);
      if (!footage) return JSON.stringify({
        __result: {
          updated: 0,
          message: "Replacement file is missing"
        }
      });
      var footageDuration = Math.max(0, toNumber(footage.duration, 0));
      var selectedSourceStart = rawSourceStart;
      if (footageDuration > 0) selectedSourceStart = Math.min(selectedSourceStart, footageDuration);
      var selectedSourceEnd = Math.max(selectedSourceStart, rawSourceEnd);
      if (footageDuration > 0) selectedSourceEnd = Math.min(selectedSourceEnd, footageDuration);
      if (selectedSourceEnd <= selectedSourceStart) {
        if (!existingFootage) removeProjectItem(footage);
        return JSON.stringify({
          __error: "Replacement clip has no usable selected source window"
        });
      }
      app.beginUndoGroup("FlagshipEditor Swap Cut");
      try {
        layer.replaceSource(footage, false);
        layer.startTime = beatTime - selectedSourceStart;
        layer.inPoint = beatTime;
        if (endTime > beatTime) layer.outPoint = Math.min(endTime, comp.duration);
        retargetTimeRemapSourceOffset(layer, selectedSourceStart, footageDuration);
        layer.name = clipName + " [" + sectionType + "]";
      } finally {
        endUndoGroupSafely();
      }
      var sourceWarning = selectedSourceEnd - selectedSourceStart + 0.001 < endTime - beatTime ? "Selected source window is shorter than the timeline slot; the target slot was preserved" : "";
      return JSON.stringify({
        __result: {
          updated: 1,
          message: sourceWarning
        }
      });
    } catch (e) {
      endUndoGroupSafely();
      return JSON.stringify({
        __error: String(e)
      });
    }
  }
  function replaceSectionCuts(sectionType, decisions) {
    try {
      var comp = findGeneratedComp();
      if (!comp) return JSON.stringify({
        __result: {
          updated: 0,
          message: "Generated comp not found"
        }
      });
      if (!isArray(decisions)) {
        return JSON.stringify({
          __error: "replaceSectionCuts expects an array of cut decisions"
        });
      }
      var updated = 0;
      var missing = 0;
      app.beginUndoGroup("FlagshipEditor Replace Section");
      try {
        for (var i = 0; i < decisions.length; i++) {
          var decision = decisions[i];
          var layer = findCutLayer(comp, decision.beatTime, sectionType);
          if (!layer) {
            missing++;
            continue;
          }
          var rawReplacementSourceStart = Math.max(0, toNumber(decision.sourceStart, 0));
          var rawReplacementSourceEnd = toNumber(decision.sourceEnd, 0);
          if (rawReplacementSourceEnd <= rawReplacementSourceStart) {
            missing++;
            continue;
          }
          var existingReplacementFootage = findProjectFootage(decision.clipPath);
          var footage = findOrImportProjectFootage(decision.clipPath);
          if (!footage) {
            missing++;
            continue;
          }
          var footageDuration = Math.max(0, toNumber(footage.duration, 0));
          var replacementSourceStart = rawReplacementSourceStart;
          if (footageDuration > 0) {
            replacementSourceStart = Math.min(replacementSourceStart, footageDuration);
          }
          var replacementSourceEnd = Math.max(replacementSourceStart, rawReplacementSourceEnd);
          if (footageDuration > 0) {
            replacementSourceEnd = Math.min(replacementSourceEnd, footageDuration);
          }
          if (replacementSourceEnd <= replacementSourceStart) {
            if (!existingReplacementFootage) removeProjectItem(footage);
            missing++;
            continue;
          }
          layer.replaceSource(footage, false);
          layer.startTime = decision.beatTime - replacementSourceStart;
          layer.inPoint = decision.beatTime;
          if (decision.endTime > decision.beatTime) {
            layer.outPoint = Math.min(decision.endTime, comp.duration);
          }
          retargetTimeRemapSourceOffset(layer, replacementSourceStart, footageDuration);
          layer.name = decision.clipName + " [" + sectionType + "]";
          updated++;
        }
      } finally {
        endUndoGroupSafely();
      }
      return JSON.stringify({
        __result: {
          updated: updated,
          missing: missing
        }
      });
    } catch (e) {
      endUndoGroupSafely();
      return JSON.stringify({
        __error: String(e)
      });
    }
  }
  function normalizeParameters(params) {
    var source = params || {};
    return {
      cutIntensity: toNumber(source.cutIntensity, 5),
      vfxIntensity: toNumber(source.vfxIntensity, 5),
      colorGrading: toNumber(source.colorGrading, 5),
      seed: toNumber(source.seed, 1),
      effects: source.effects || {}
    };
  }
  function applyParameterOverrides(style, params, element3D) {
    var vfxEnabled = params.vfxIntensity > 0;
    var allEffects = PER_CUT_EFFECTS.concat(COMP_WIDE_EFFECTS);
    for (var i = 0; i < allEffects.length; i++) {
      var key = allEffects[i];
      if (!style[key]) continue;
      var override = params.effects[key];
      if (override === true || override === false) {
        style[key].enabled = override && vfxEnabled;
      } else {
        style[key].enabled = style[key].enabled === true && vfxEnabled;
      }
    }
    if (style.color_grading) {
      style.color_grading.enabled = params.colorGrading > 0;
      style.color_grading.opacity = Math.max(0, Math.min(100, params.colorGrading * 10));
    }
    style.element_3d = style.element_3d || {};
    var element3DOverride = params.effects.element_3d;
    style.element_3d.enabled = element3DOverride === true || element3DOverride !== false && style.element_3d.enabled === true;
    if (element3D) {
      style.element_3d.auto_camera = element3D.autoCamera !== false;
      style.element_3d.parallax_depth = toNumber(element3D.parallaxDepth, 0);
    }
    return style;
  }
  function cutTag(beatTime, sectionType) {
    return "FlagshipEditorCut|" + sectionType + "|" + beatTime.toFixed(4);
  }

  // Replacing the footage does not reset AE's existing Time Remap keys. Shift
  // their source-time values as a group so manual swaps, reorders and section
  // regeneration preserve the speed/slow/freeze pattern while moving its first
  // rendered frame to the newly selected best-moment offset.
  function retargetTimeRemapSourceOffset(layer, selectedSourceStart, footageDuration) {
    if (!layer || layer.timeRemapEnabled !== true) return;
    var remap = layer.property("ADBE Time Remapping");
    if (!remap || remap.numKeys < 1) return;
    var currentSourceAtIn = toNumber(remap.valueAtTime(layer.inPoint, false), selectedSourceStart);
    var delta = selectedSourceStart - currentSourceAtIn;
    if (Math.abs(delta) < 0.000001) return;
    var keyTimes = [];
    var shiftedValues = [];
    for (var i = 1; i <= remap.numKeys; i++) {
      keyTimes.push(remap.keyTime(i));
      var shifted = toNumber(remap.keyValue(i), 0) + delta;
      shiftedValues.push(footageDuration > 0 ? Math.max(0, Math.min(footageDuration, shifted)) : Math.max(0, shifted));
    }
    for (var keyIndex = 0; keyIndex < keyTimes.length; keyIndex++) {
      remap.setValueAtTime(keyTimes[keyIndex], shiftedValues[keyIndex]);
    }
  }
  function findGeneratedComp() {
    var project = app.project;
    if (!project) return null;
    for (var i = project.numItems; i >= 1; i--) {
      var item = project.item(i);
      if (item && item.name === "FlagshipEditor_Edit" && item instanceof CompItem) return item;
    }
    return null;
  }
  function findCutLayer(comp, beatTime, sectionType) {
    var expected = cutTag(beatTime, sectionType);
    var prefix = "FlagshipEditorCut|" + sectionType + "|";
    for (var i = 1; i <= comp.numLayers; i++) {
      var layer = comp.layer(i);
      if (layer.comment === expected) return layer;
      if (layer.comment && String(layer.comment).substring(0, prefix.length) === prefix) {
        var taggedBeat = parseFloat(String(layer.comment).substring(prefix.length));
        if (!isNaN(taggedBeat) && Math.abs(taggedBeat - beatTime) < 0.05) return layer;
      }
    }
    return null;
  }
  function importFile(path) {
    var file = new File(path);
    if (!file.exists) return null;
    var importOptions = new ImportOptions(file);
    return app.project.importFile(importOptions);
  }
  function normalizeMediaPath(path) {
    return String(path || "").replace(/\\/g, "/").toLowerCase();
  }
  function findProjectFootage(path) {
    var project = app.project;
    var expected = normalizeMediaPath(path);
    if (project && typeof project.numItems === "number") {
      for (var i = 1; i <= project.numItems; i++) {
        var item = project.item(i);
        try {
          if (item && item.file && normalizeMediaPath(item.file.fsName) === expected) {
            return item;
          }
        } catch (e) {}
      }
    }
    return null;
  }
  function findOrImportProjectFootage(path) {
    var project = app.project;
    var existing = findProjectFootage(path);
    if (existing) return existing;
    var imported = importFile(path);
    if (!imported || !project || typeof project.numItems !== "number") return imported;
    for (var folderIndex = project.numItems; folderIndex >= 1; folderIndex--) {
      var folder = project.item(folderIndex);
      if (folder && folder.name === "FlagshipEditor_Clips") {
        try {
          imported.parentFolder = folder;
        } catch (e) {}
        break;
      }
    }
    return imported;
  }
  function arrayContains(values, expected) {
    for (var i = 0; i < values.length; i++) {
      if (values[i] === expected) return true;
    }
    return false;
  }

  // A style preset can name an effect this build has no routine for — a newer
  // preset opened by an older install. Nothing would apply it, so say so rather
  // than letting the user believe the preset ran in full.
  function warnUnimplementedEffects(style, warnings) {
    if (!style) return;
    var routed = PER_CUT_EFFECTS.concat(COMP_WIDE_EFFECTS);
    routed.push("color_grading");
    routed.push("element_3d");
    for (var key in style) {
      if (!Object.prototype.hasOwnProperty.call(style, key)) continue;
      var config = style[key];
      if (!config || _typeof(config) !== "object" || config.enabled !== true) continue;
      if (arrayContains(routed, key)) continue;
      var message = "Style effect is not implemented and was skipped: " + key;
      if (!arrayContains(warnings, message)) warnings.push(message);
    }
  }
  function isEffectActive(style, effectName, sectionType) {
    var config = style[effectName];
    if (!config || config.enabled !== true) return false;
    var sections = config.sections;
    if (!sections || typeof sections.length !== "number" || sections.length === 0) return true;
    return arrayContains(sections, sectionType);
  }
  function applyVFXToLayer(layer, style, sectionType, beatTime, context) {
    var plan = createLayerPlan(layer);

    // Whole-layer moves are queued first so the beat-synced bursts multiply on
    // top of them rather than overwriting them.
    if (isEffectActive(style, "slow_push_in", sectionType)) {
      applySlowPushIn(style.slow_push_in, plan);
    }
    if (isEffectActive(style, "smooth_transitions", sectionType)) {
      applySmoothTransitions(style.smooth_transitions, context, plan);
    }
    if (isEffectActive(style, "zoom_punch", sectionType)) {
      applyZoomPunch(style.zoom_punch, beatTime, context, plan);
    }
    if (isEffectActive(style, "beat_flash", sectionType)) {
      applyBeatFlash(style.beat_flash, beatTime, context, plan);
    }
    if (isEffectActive(style, "strobe", sectionType)) {
      applyStrobe(style.strobe, beatTime, context, plan);
    }
    commitLayerPlan(layer, plan, context);
    if (isEffectActive(style, "camera_shake", sectionType)) {
      applyCameraShake(layer, style.camera_shake, beatTime, context);
    }
    if (isEffectActive(style, "whip_pan", sectionType)) {
      applyWhipPan(layer, style.whip_pan, beatTime, context);
    }
    if (isEffectActive(style, "glitch_effect", sectionType)) {
      applyGlitch(layer, style.glitch_effect, beatTime, context);
    } else if (isEffectActive(style, "rgb_split", sectionType)) {
      // The glitch already lays down a chromatic tear; doing both doubles the
      // layer count for no visible gain.
      applyRGBSplit(layer, style.rgb_split, beatTime, context);
    }
    if (isEffectActive(style, "speed_ramp", sectionType)) {
      applySpeedRamp(layer, style.speed_ramp, beatTime, context);
    } else if (isEffectActive(style, "slow_mo", sectionType)) {
      applySlowMo(layer, style.slow_mo, beatTime, context);
    } else if (isEffectActive(style, "freeze_frame", sectionType)) {
      applyFreezeFrame(layer, style.freeze_frame, beatTime, context);
    }
    if (isEffectActive(style, "face_mask", sectionType)) {
      applyFaceMask(layer, style.face_mask, beatTime, context);
    }
    if (isEffectActive(style, "depth_blur", sectionType)) {
      applyDepthBlur(layer, style.depth_blur, beatTime, context);
    }
    if (isEffectActive(style, "selective_color", sectionType)) {
      applySelectiveColor(layer, style.selective_color, beatTime, context);
    }
    if (isEffectActive(style, "mask_transition", sectionType)) {
      applyMaskTransition(layer, style.mask_transition, beatTime, context);
    }
    if (isEffectActive(style, "picture_flash", sectionType)) {
      applyPictureFlash(layer, style.picture_flash, beatTime, context);
    }
  }
  function applyCompWideVFX(style, context) {
    if (style.smoke_fog && style.smoke_fog.enabled === true) {
      applySmokeFog(style.smoke_fog, context);
    }
    if (style.light_leaks && style.light_leaks.enabled === true) {
      applyLightLeaks(style.light_leaks, context);
    }
    if (style.vhs_overlay && style.vhs_overlay.enabled === true) {
      applyVHSOverlay(style.vhs_overlay, context);
    }
    if (style.light_wrap && style.light_wrap.enabled === true) {
      applyLightWrap(style.light_wrap, context);
    }
    if (style.film_grain && style.film_grain.enabled === true) {
      applyFilmGrain(style.film_grain, context);
    }
    // Letterbox is added last so its bars sit above every other overlay.
    if (style.letterbox && style.letterbox.enabled === true) {
      applyLetterbox(style.letterbox, context);
    }
  }

  // Reports which style effects this build will actually act on, so the panel can
  // show the user what a preset is doing instead of guessing.
  function describeStyleCoverage(style) {
    try {
      var active = [];
      var inactive = [];
      var all = PER_CUT_EFFECTS.concat(COMP_WIDE_EFFECTS);
      for (var i = 0; i < all.length; i++) {
        var config = style ? style[all[i]] : null;
        if (config && config.enabled === true) {
          active.push(all[i]);
        } else if (config) {
          inactive.push(all[i]);
        }
      }
      if (style && style.element_3d && style.element_3d.enabled === true) active.push("element_3d");
      return JSON.stringify({
        __result: {
          active: active,
          inactive: inactive,
          total: all.length + 1
        }
      });
    } catch (e) {
      return JSON.stringify({
        __error: String(e)
      });
    }
  }
  function getBuildWarnings() {
    if (!activeBuild) return JSON.stringify({
      __result: {
        warnings: []
      }
    });
    return JSON.stringify({
      __result: {
        warnings: uniqueWarningStrings(activeBuild.warnings)
      }
    });
  }

  // Surfaced for the panel's 3D tab so the user sees whether the plugin is there
  // before they generate an edit that silently skips it.
  function probeElement3D() {
    var project = app.project;
    if (!project) {
      return JSON.stringify({
        __error: "No After Effects project is open"
      });
    }
    var probeComp = null;
    try {
      probeComp = project.items.addComp("FlagshipEditor_ElementProbe", 16, 16, 1, 0.1, 24);
      resetElement3DDetection();
      var matchName = detectElement3D(probeComp);
      return JSON.stringify({
        __result: {
          installed: matchName !== null,
          matchName: matchName
        }
      });
    } catch (e) {
      return JSON.stringify({
        __error: String(e)
      });
    } finally {
      removeProjectItem(probeComp);
      resetElement3DDetection();
    }
  }

  // FlagshipEditor — ExtendScript Entry Point
  // This file is compiled to ES3 and loaded by After Effects.


  // Rollup wraps this file in an IIFE. Explicitly publish the bridge functions on
  // the ExtendScript global object so CEP's evalScript can call them by name.

  thisObj.beginComp = beginComp;
  thisObj.appendCutBatch = appendCutBatch;
  thisObj.finishComp = finishComp;
  thisObj.abortComp = abortComp;
  thisObj.swapCut = swapCut;
  thisObj.replaceSectionCuts = replaceSectionCuts;
  thisObj.describeStyleCoverage = describeStyleCoverage;
  thisObj.getBuildWarnings = getBuildWarnings;
  thisObj.probeElement3D = probeElement3D;
  thisObj.getBridgeHealth = function () {
    return JSON.stringify({
      __result: {
        appId: "com.akestudio.flagshipeditor.bridge",
        version: "3.0.0",
        hostName: "After Effects",
        hostVersion: app.version
      }
    });
  };

  // $.fileName names this file only while After Effects is loading it. Inside a
  // function reached through evalScript it names the host executable instead,
  // which is how the backend search ended up probing
  // C:\Program Files\Adobe\Adobe After Effects 2026. Capture it once, at load
  // time, and only trust it when it really is a script file.
  var FLAGSHIP_SCRIPT_PATH = function () {
    try {
      var name = String($.fileName);
      return /\.(js|jsx|jsxbin)$/i.test(name) ? name : "";
    } catch (e) {
      return "";
    }
  }();

  // The panel is laid out as <extension>/jsx/index.js, so its root is the folder
  // above jsx/. Returns null rather than a wrong guess when $.fileName was no help.
  function flagshipEditorExtensionRoot() {
    try {
      if (!FLAGSHIP_SCRIPT_PATH) return null;
      var jsxFolder = new File(FLAGSHIP_SCRIPT_PATH).parent;
      if (!jsxFolder) return null;
      return jsxFolder.parent ? jsxFolder.parent : jsxFolder;
    } catch (e) {
      return null;
    }
  }

  // The panel needs the on-disk extension root to resolve the bundled LUTs.
  thisObj.getExtensionRoot = function () {
    try {
      var root = flagshipEditorExtensionRoot();
      return JSON.stringify({
        __result: {
          root: root ? root.fsName : ""
        }
      });
    } catch (e) {
      return JSON.stringify({
        __error: String(e)
      });
    }
  };
  thisObj.openFileDialog = function (filter) {
    try {
      var file = File.openDialog("Select a file", filter, false);
      if (!file) return JSON.stringify({
        __result: null
      });
      return JSON.stringify({
        __result: file.fsName
      });
    } catch (e) {
      return JSON.stringify({
        __error: "File dialog failed: " + String(e)
      });
    }
  };
  thisObj.openFilesDialog = function (filter) {
    try {
      var files = File.openDialog("Select files", filter, true);
      if (!files) return JSON.stringify({
        __result: []
      });
      var paths = [];
      // ExtendScript may return a File object even when multiSelect is true.
      // File.length is the byte size, so detect a single file by fsName instead.
      if (files.fsName) {
        paths.push(files.fsName);
        return JSON.stringify({
          __result: paths
        });
      }
      for (var i = 0; i < files.length; i++) {
        paths.push(files[i].fsName);
      }
      return JSON.stringify({
        __result: paths
      });
    } catch (e) {
      return JSON.stringify({
        __error: "File dialog failed: " + String(e)
      });
    }
  };
  thisObj.openFolderDialog = function () {
    try {
      var folder = Folder.selectDialog("Select a media folder");
      if (!folder) return JSON.stringify({
        __result: null
      });
      return JSON.stringify({
        __result: folder.fsName
      });
    } catch (e) {
      return JSON.stringify({
        __error: "Folder dialog failed: " + String(e)
      });
    }
  };

  // Starting the backend is the one job the panel cannot do itself: CEP runs
  // without Node, so the only process launcher available is ExtendScript's
  // `system.callSystem`. Every branch detaches immediately — the panel polls
  // /health rather than blocking After Effects on a synchronous shell call.

  var FLAGSHIP_EXTENSION_ID = "com.akestudio.flagshipeditor";
  var FLAGSHIP_LAUNCHER = "Start-FlagshipEditor-Backend";
  var FLAGSHIP_IS_WINDOWS = /Windows/.test(String($.os));

  // Appends a path unless an equivalent one is already listed. Trailing
  // separators are trimmed so the "looked in" list in the error stays readable.
  function flagshipEditorPush(list, seen, path) {
    if (!path) return;
    if (FLAGSHIP_IS_WINDOWS) path = path.replace(/\//g, "\\");
    while (path.length > 3) {
      var last = path.charAt(path.length - 1);
      if (last !== "\\" && last !== "/") break;
      path = path.substring(0, path.length - 1);
    }
    var key = path.toLowerCase();
    if (seen[key]) return;
    seen[key] = 1;
    list.push(path);
  }

  // The numeric runs in a path's last segment ("...\\2.0.0" -> [2, 0, 0]), for
  // version-aware folder ordering. A folder without digits yields [] and sorts
  // oldest.
  function flagshipEditorVersionParts(path) {
    var name = path.replace(/[\\\/]+$/, "");
    var cut = name.lastIndexOf("\\");
    var slash = name.lastIndexOf("/");
    if (slash > cut) cut = slash;
    if (cut !== -1) name = name.substring(cut + 1);
    var runs = name.match(/\d+/g);
    var parts = [];
    if (runs) {
      for (var i = 0; i < runs.length; i++) {
        parts[parts.length] = parseInt(runs[i], 10);
      }
    }
    return parts;
  }

  // Every directory a FlagshipEditor *install* can occupy, newest layout first:
  // v2.0.0's MSI is per-machine under Program Files, v0.1.x's .cmd installer was
  // per-user under LOCALAPPDATA, and a dev build runs out of the checkout itself.
  function flagshipEditorInstallRoots() {
    var roots = [];
    var seen = {};
    var i;

    // ProgramW6432 is the 64-bit tree even when the host process is 32-bit.
    var programFiles = FLAGSHIP_IS_WINDOWS ? [$.getenv("ProgramW6432"), $.getenv("ProgramFiles"), "C:\\Program Files"] : [];
    for (i = 0; i < programFiles.length; i++) {
      if (programFiles[i]) flagshipEditorPush(roots, seen, programFiles[i] + "\\FlagshipEditor");
    }
    var localAppData = FLAGSHIP_IS_WINDOWS ? $.getenv("LOCALAPPDATA") : null;
    if (localAppData) {
      var installRoot = new Folder(localAppData + "\\ake-studio\\FlagshipEditor");
      if (installRoot.exists) {
        var entries = installRoot.getFiles();
        var versions = [];
        for (i = 0; i < entries.length; i++) {
          if (entries[i] instanceof Folder) versions.push(entries[i].fsName);
        }
        // Newest install first, so an upgrade wins over a leftover build. The
        // entries are full fsName paths, so only the last path segment is
        // compared, and its digit runs are compared numerically: a plain string
        // sort put 1.10.0 before 1.9.0. ES3-safe — ExtendScript has no
        // Array.prototype.map.
        versions.sort(function (a, b) {
          var aParts = flagshipEditorVersionParts(a);
          var bParts = flagshipEditorVersionParts(b);
          var length = aParts.length > bParts.length ? aParts.length : bParts.length;
          for (var part = 0; part < length; part++) {
            var aValue = part < aParts.length ? aParts[part] : 0;
            var bValue = part < bParts.length ? bParts[part] : 0;
            if (aValue !== bValue) return aValue - bValue;
          }
          return a < b ? -1 : a > b ? 1 : 0;
        });
        for (var v = versions.length - 1; v >= 0; v--) flagshipEditorPush(roots, seen, versions[v]);
        flagshipEditorPush(roots, seen, installRoot.fsName);
      }
    }

    // A dev build has engine/ a few levels above dist/cep; on macOS this is the
    // only branch that ever matches.
    var folder = flagshipEditorExtensionRoot();
    for (var depth = 0; depth < 4 && folder; depth++) {
      flagshipEditorPush(roots, seen, folder.fsName);
      folder = folder.parent;
    }
    return roots;
  }

  // The installers also drop a one-line bridge, Start-FlagshipEditor-Backend.cmd,
  // next to the panel itself; it reads InstallDir out of HKLM and hands off to the
  // real launcher. These extension folders are spelled out because $.fileName
  // cannot be relied on to find them from inside an evalScript call.
  function flagshipEditorPanelRoots() {
    var roots = [];
    var seen = {};
    var root = flagshipEditorExtensionRoot();
    if (root) flagshipEditorPush(roots, seen, root.fsName);

    // v2.0.0 MSI, system-wide. After Effects only scans the 32-bit Common Files
    // tree for shared CEP extensions, which is where the package puts the panel.
    var common = FLAGSHIP_IS_WINDOWS ? $.getenv("CommonProgramFiles(x86)") || $.getenv("CommonProgramFiles") : null;
    if (common) {
      flagshipEditorPush(roots, seen, common + "\\Adobe\\CEP\\extensions\\" + FLAGSHIP_EXTENSION_ID);
    }
    // v0.1.x .cmd installer, per-user.
    var appData = FLAGSHIP_IS_WINDOWS ? $.getenv("APPDATA") : null;
    if (appData) {
      flagshipEditorPush(roots, seen, appData + "\\Adobe\\CEP\\extensions\\" + FLAGSHIP_EXTENSION_ID);
    }
    return roots;
  }

  // HKLM\Software\ake-studio\FlagshipEditor\InstallDir is written by the MSI from
  // a 64-bit component. It is the only thing that can find an install the user
  // moved off Program Files, but reading it costs a synchronous `reg query`, so
  // it is asked for only once every well-known location has already missed.
  var FLAGSHIP_REGISTRY_ROOT = null;
  function flagshipEditorRegistryRoots() {
    if (FLAGSHIP_REGISTRY_ROOT === null) {
      FLAGSHIP_REGISTRY_ROOT = "";
      try {
        var out = String(system.callSystem('cmd.exe /c reg query "HKLM\\Software\\ake-studio\\FlagshipEditor" /v InstallDir /reg:64 2>nul'));
        // reg prints "    InstallDir    REG_SZ    C:\Program Files\FlagshipEditor\".
        var at = out.indexOf("REG_SZ");
        if (at !== -1) {
          var value = out.substring(at + 6);
          var end = value.search(/[\r\n]/);
          if (end !== -1) value = value.substring(0, end);
          FLAGSHIP_REGISTRY_ROOT = value.replace(/^\s+/, "").replace(/\s+$/, "");
        }
      } catch (e) {
        FLAGSHIP_REGISTRY_ROOT = "";
      }
    }
    var roots = [];
    var seen = {};
    flagshipEditorPush(roots, seen, FLAGSHIP_REGISTRY_ROOT);
    return roots;
  }

  // A launcher comes in either flavour: the MSI ships the windowless .vbs, while
  // the older installer and the CEP bridge ship .cmd.
  function flagshipEditorLaunchersIn(roots) {
    var candidates = [];
    var seen = {};
    for (var i = 0; i < roots.length; i++) {
      flagshipEditorPush(candidates, seen, roots[i] + "\\" + FLAGSHIP_LAUNCHER + ".vbs");
      flagshipEditorPush(candidates, seen, roots[i] + "\\" + FLAGSHIP_LAUNCHER + ".cmd");
      flagshipEditorPush(candidates, seen, roots[i] + "\\scripts\\" + FLAGSHIP_LAUNCHER + ".cmd");
    }
    return candidates;
  }
  function flagshipEditorServersIn(roots) {
    var candidates = [];
    var seen = {};
    // The VBS launcher exports this, so a backend already started by hand keeps
    // pointing the panel at the same engine.
    var override = $.getenv("FLAGSHIPEDITOR_ENGINE");
    if (override) flagshipEditorPush(candidates, seen, override + "/server.py");
    for (var i = 0; i < roots.length; i++) {
      flagshipEditorPush(candidates, seen, roots[i] + "/engine/server.py");
    }
    return candidates;
  }

  // wscript runs a .vbs with no console of its own; a .cmd goes straight to the
  // shell. `start` detaches either way, so After Effects is never held up.
  function flagshipEditorLaunch(path) {
    var isVbs = path.length > 4 && path.substring(path.length - 4).toLowerCase() === ".vbs";
    if (isVbs) {
      system.callSystem('cmd.exe /c start "FlagshipEditor Backend" /min wscript.exe //nologo "' + path + '"');
    } else {
      system.callSystem('cmd.exe /c start "FlagshipEditor Backend" /min "' + path + '"');
    }
  }
  thisObj.startBackend = function () {
    try {
      var isWindows = FLAGSHIP_IS_WINDOWS;
      var attempted = [];
      var attemptedSeen = {};
      var i;

      // Two passes over the same search. The first only touches paths that are
      // free to test; the second prepends whatever the registry names, and runs
      // only when the first found nothing.
      for (var pass = 0; pass < 2; pass++) {
        var extra = pass === 0 ? [] : flagshipEditorRegistryRoots();
        if (pass === 1 && !extra.length) break;
        var installRoots = extra.concat(flagshipEditorInstallRoots());
        if (isWindows) {
          var launchers = flagshipEditorLaunchersIn(installRoots.concat(flagshipEditorPanelRoots()));
          for (i = 0; i < launchers.length; i++) {
            flagshipEditorPush(attempted, attemptedSeen, launchers[i]);
            if (!new File(launchers[i]).exists) continue;
            flagshipEditorLaunch(launchers[i]);
            return JSON.stringify({
              __result: {
                launched: true,
                launcher: launchers[i]
              }
            });
          }
        }

        // Windows falls through to here when the installer's launcher is gone but
        // the engine folder survived; macOS always uses this branch.
        var scripts = flagshipEditorServersIn(installRoots);
        for (i = 0; i < scripts.length; i++) {
          flagshipEditorPush(attempted, attemptedSeen, scripts[i]);
          var scriptFile = new File(scripts[i]);
          if (!scriptFile.exists) continue;
          var engineFolder = scriptFile.parent.fsName;
          if (isWindows) {
            system.callSystem('cmd.exe /c start "FlagshipEditor Backend" /min cmd /c "cd /d ""' + engineFolder + '"" && python server.py"');
          } else {
            system.callSystem("/bin/sh -c \"cd '" + engineFolder + "' && nohup python3 server.py >/dev/null 2>&1 &\"");
          }
          return JSON.stringify({
            __result: {
              launched: true,
              launcher: scripts[i]
            }
          });
        }
      }
      return JSON.stringify({
        __error: "The FlagshipEditor backend could not be found. Run the installer again. Looked in: " + attempted.join(", ")
      });
    } catch (e) {
      return JSON.stringify({
        __error: "The backend could not be started: " + String(e)
      });
    }
  };

})();
})(this);