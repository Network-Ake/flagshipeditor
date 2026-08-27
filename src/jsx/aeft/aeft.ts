// After Effects bridge — builds the generated composition from cut decisions.
// Compiled to ES3 via Bolt CEP, so this file stays on `var` and plain functions.

import {
  LayerPlan,
  applyBeatFlash,
  applyCameraShake,
  applyDepthBlur,
  applyFaceMask,
  applyFilmGrain,
  applyFreezeFrame,
  applyGlitch,
  applyLetterbox,
  applyLightLeaks,
  applyLightWrap,
  applyMaskTransition,
  applyPictureFlash,
  applyRGBSplit,
  applySelectiveColor,
  applySlowMo,
  applySlowPushIn,
  applySmokeFog,
  applySmoothTransitions,
  applySpeedRamp,
  applyStrobe,
  applyVHSOverlay,
  applyWhipPan,
  applyZoomPunch,
  commitLayerPlan,
  createLayerPlan,
} from "./vfx_engine";
import { VFXContext, makeRandom, toNumber } from "./vfx_utils";
import { applyColorGrading } from "./color_grading";
import { createElement3DSolid, detectElement3D, resetElement3DDetection } from "./element_3d";

interface StyleConfig {
  style_name: string;
  display_name: string;
  cut_strategy: { [section: string]: any };
  color_grading?: any;
  element_3d?: any;
  [key: string]: any;
}

interface EditingParameters {
  cutIntensity: number;
  vfxIntensity: number;
  colorGrading: number;
  seed: number;
  effects: { [effectName: string]: boolean };
}

interface Element3DSettings {
  parallaxDepth: number;
  autoCamera: boolean;
}

interface MediaProfile {
  width: number;
  height: number;
  fps: number;
}

interface SectionSpan {
  type: string;
  start: number;
  end: number;
}

interface CutDecision {
  beatTime: number;
  endTime: number;
  sourceStart: number;
  sourceEnd: number;
  clipPath: string;
  clipName: string;
  sectionType: string;
}

interface TimelineCut extends CutDecision {
  endTime: number;
  sourceStart: number;
  sourceEnd: number;
}

// Effects animated on the clip layer that starts on the beat.
var PER_CUT_EFFECTS = [
  "zoom_punch",
  "camera_shake",
  "whip_pan",
  "glitch_effect",
  "speed_ramp",
  "freeze_frame",
  "face_mask",
  "slow_mo",
  "beat_flash",
  "depth_blur",
  "smooth_transitions",
  "mask_transition",
  "picture_flash",
  "selective_color",
  "slow_push_in",
  "rgb_split",
  "strobe",
];

// Effects that belong to the whole edit. Building these per cut is what used to
// leave hundreds of duplicate solids in the project.
var COMP_WIDE_EFFECTS = [
  "smoke_fog",
  "light_leaks",
  "vhs_overlay",
  "film_grain",
  "letterbox",
  "light_wrap",
];

var MAX_CUTS_PER_BATCH = 30;

var activeBuild: any = null;

function isArray(value: any): boolean {
  return Object.prototype.toString.call(value) === "[object Array]";
}

export function beginComp(
  duration: number,
  audioPath: string,
  runtimeStyle: StyleConfig,
  params: EditingParameters,
  element3D: Element3DSettings,
  sections: SectionSpan[],
  extensionPath: string,
  mediaProfile: MediaProfile,
  tempo: number
): string {
  var comp: any = null;
  var clipsFolder: any = null;
  var audioItem: any = null;
  try {
    if (activeBuild) cleanupActiveBuild();
    resetElement3DDetection();
    var project = app.project;
    if (!project) return JSON.stringify({ __error: "No After Effects project is open" });
    if (!isFinite(duration) || duration <= 0) {
      return JSON.stringify({ __error: "The analyzed music duration is invalid" });
    }
    var audioFile = new File(audioPath);
    if (!audioFile.exists) {
      return JSON.stringify({ __error: "Music file is missing: " + audioPath });
    }

    var profile = resolveCompProfile(project, mediaProfile);

    app.beginUndoGroup("FlagshipEditor Build");
    comp = project.items.addComp(
      "FlagshipEditor_Edit",
      profile.width,
      profile.height,
      1,
      duration,
      profile.fps
    );
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
        random: makeRandom(safeParams.seed),
      } as VFXContext,
    };
    activeBuild.context.warnings = activeBuild.warnings;
    warnUnimplementedEffects(configuredStyle, activeBuild.warnings);

    return JSON.stringify({
      __result: {
        started: true,
        compName: comp.name,
        width: profile.width,
        height: profile.height,
        fps: profile.fps,
      },
    });
  } catch (e) {
    removeProjectItem(comp);
    removeProjectItem(clipsFolder);
    removeProjectItem(audioItem);
    endUndoGroupSafely();
    activeBuild = null;
    return JSON.stringify({ __error: String(e) });
  }
}

export function appendCutBatch(cuts: TimelineCut[]): string {
  try {
    if (!activeBuild || !activeBuild.comp) {
      return JSON.stringify({ __error: "No FlagshipEditor composition build is active" });
    }
    if (!isArray(cuts)) {
      return JSON.stringify({ __error: "appendCutBatch expects an array of cuts" });
    }
    if (cuts.length > MAX_CUTS_PER_BATCH) {
      return JSON.stringify({
        __error:
          "A cut batch is limited to " + MAX_CUTS_PER_BATCH + " clips; received " + cuts.length,
      });
    }
    var added = 0;
    var skipped = 0;
    for (var i = 0; i < cuts.length; i++) {
      var cut = cuts[i];
      if (!cut || !cut.clipPath || cut.endTime <= cut.beatTime) {
        activeBuild.warnings.push(
          "Cut skipped: " + (cut && cut.clipName ? cut.clipName : "unnamed") + " has no usable time range"
        );
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
      var fallbackSourceEnd = clipDuration > 0
        ? clipDuration
        : sourceStart + (cut.endTime - cut.beatTime);
      var sourceEnd = Math.max(sourceStart, toNumber(cut.sourceEnd, fallbackSourceEnd));
      if (clipDuration > 0) sourceEnd = Math.min(sourceEnd, clipDuration);
      if (sourceEnd <= sourceStart) {
        activeBuild.warnings.push(
          "Cut skipped: " + cut.clipName + " has no usable selected source window"
        );
        skipped++;
        continue;
      }
      if (sourceEnd - sourceStart + 0.001 < cut.endTime - cut.beatTime) {
        activeBuild.warnings.push(
          "Selected source window is shorter than the timeline slot for " + cut.clipName +
          "; After Effects will preserve the target slot and may hold the final source frame"
        );
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
      __result: { added: added, skipped: skipped, totalAdded: activeBuild.added }
    });
  } catch (e) {
    return JSON.stringify({ __error: String(e) });
  }
}

export function finishComp(): string {
  try {
    if (!activeBuild || !activeBuild.comp) {
      return JSON.stringify({ __error: "No FlagshipEditor composition build is active" });
    }
    if (activeBuild.added < 1) {
      cleanupActiveBuild();
      return JSON.stringify({ __error: "After Effects could not import any selected clips" });
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
    return JSON.stringify({ __result: result });
  } catch (e) {
    endUndoGroupSafely();
    return JSON.stringify({ __error: String(e) });
  }
}

export function abortComp(): string {
  cleanupActiveBuild();
  return JSON.stringify({ __result: { aborted: true } });
}

function writeSectionMarkers(comp: any, sections: SectionSpan[], warnings: string[]): void {
  if (!sections || !sections.length) return;
  var written: number[] = [];
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
function snapFps(value: number): number {
  if (value <= 0) return 30;
  var rounded = Math.round(value);
  // Only snap when within 0.15 of the integer (59.94 → 60, not 58 → 60).
  if (Math.abs(value - rounded) < 0.15) return rounded;
  return rounded;
}

function resolveCompProfile(project: any, mediaProfile: MediaProfile): MediaProfile {
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
      return { width: width, height: height, fps: fps };
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
  return { width: width, height: height, fps: fps };
}

function scanProjectForFootageProfile(project: any): MediaProfile | null {
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
        return { width: Math.round(itemWidth), height: Math.round(itemHeight), fps: itemFps };
      }
    } catch (itemError) {
      // A project item that cannot be inspected is simply not a candidate.
    }
  }
  return null;
}

function getOrImportFootage(path: string): any {
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

function cleanupActiveBuild(): void {
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

function endUndoGroupSafely(): void {
  try { app.endUndoGroup(); } catch (undoErr) {}
}

function removeProjectItem(item: any): void {
  if (!item) return;
  try { item.remove(); } catch (e) {}
}

function uniqueWarningStrings(values: string[]): string[] {
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

export function swapCut(
  beatTime: number,
  sectionType: string,
  clipPath: string,
  clipName: string,
  endTime: number,
  sourceStart: number,
  sourceEnd: number
): string {
  try {
    var comp = findGeneratedComp();
    if (!comp) return JSON.stringify({ __result: { updated: 0, message: "Generated comp not found" } });
    var layer = findCutLayer(comp, beatTime, sectionType);
    if (!layer) return JSON.stringify({ __result: { updated: 0, message: "Cut layer not found" } });
    var rawSourceStart = Math.max(0, toNumber(sourceStart, 0));
    var rawSourceEnd = toNumber(sourceEnd, 0);
    if (rawSourceEnd <= rawSourceStart) {
      return JSON.stringify({ __error: "Replacement clip has no usable selected source window" });
    }
    var existingFootage = findProjectFootage(clipPath);
    var footage = findOrImportProjectFootage(clipPath);
    if (!footage) return JSON.stringify({ __result: { updated: 0, message: "Replacement file is missing" } });
    var footageDuration = Math.max(0, toNumber(footage.duration, 0));
    var selectedSourceStart = rawSourceStart;
    if (footageDuration > 0) selectedSourceStart = Math.min(selectedSourceStart, footageDuration);
    var selectedSourceEnd = Math.max(
      selectedSourceStart,
      rawSourceEnd
    );
    if (footageDuration > 0) selectedSourceEnd = Math.min(selectedSourceEnd, footageDuration);
    if (selectedSourceEnd <= selectedSourceStart) {
      if (!existingFootage) removeProjectItem(footage);
      return JSON.stringify({ __error: "Replacement clip has no usable selected source window" });
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
    var sourceWarning = selectedSourceEnd - selectedSourceStart + 0.001 < endTime - beatTime
      ? "Selected source window is shorter than the timeline slot; the target slot was preserved"
      : "";
    return JSON.stringify({ __result: { updated: 1, message: sourceWarning } });
  } catch (e) {
    endUndoGroupSafely();
    return JSON.stringify({ __error: String(e) });
  }
}

export function replaceSectionCuts(sectionType: string, decisions: CutDecision[]): string {
  try {
    var comp = findGeneratedComp();
    if (!comp) return JSON.stringify({ __result: { updated: 0, message: "Generated comp not found" } });
    if (!isArray(decisions)) {
      return JSON.stringify({ __error: "replaceSectionCuts expects an array of cut decisions" });
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
        var replacementSourceEnd = Math.max(
          replacementSourceStart,
          rawReplacementSourceEnd
        );
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
    return JSON.stringify({ __result: { updated: updated, missing: missing } });
  } catch (e) {
    endUndoGroupSafely();
    return JSON.stringify({ __error: String(e) });
  }
}

function normalizeParameters(params: EditingParameters): EditingParameters {
  var source: any = params || {};
  return {
    cutIntensity: toNumber(source.cutIntensity, 5),
    vfxIntensity: toNumber(source.vfxIntensity, 5),
    colorGrading: toNumber(source.colorGrading, 5),
    seed: toNumber(source.seed, 1),
    effects: source.effects || {},
  };
}

function applyParameterOverrides(
  style: StyleConfig,
  params: EditingParameters,
  element3D: Element3DSettings
): StyleConfig {
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
  style.element_3d.enabled =
    element3DOverride === true || (element3DOverride !== false && style.element_3d.enabled === true);
  if (element3D) {
    style.element_3d.auto_camera = element3D.autoCamera !== false;
    style.element_3d.parallax_depth = toNumber(element3D.parallaxDepth, 0);
  }
  return style;
}

function cutTag(beatTime: number, sectionType: string): string {
  return "FlagshipEditorCut|" + sectionType + "|" + beatTime.toFixed(4);
}

// Replacing the footage does not reset AE's existing Time Remap keys. Shift
// their source-time values as a group so manual swaps, reorders and section
// regeneration preserve the speed/slow/freeze pattern while moving its first
// rendered frame to the newly selected best-moment offset.
function retargetTimeRemapSourceOffset(
  layer: any,
  selectedSourceStart: number,
  footageDuration: number
): void {
  if (!layer || layer.timeRemapEnabled !== true) return;
  var remap = layer.property("ADBE Time Remapping");
  if (!remap || remap.numKeys < 1) return;
  var currentSourceAtIn = toNumber(remap.valueAtTime(layer.inPoint, false), selectedSourceStart);
  var delta = selectedSourceStart - currentSourceAtIn;
  if (Math.abs(delta) < 0.000001) return;
  var keyTimes: number[] = [];
  var shiftedValues: number[] = [];
  for (var i = 1; i <= remap.numKeys; i++) {
    keyTimes.push(remap.keyTime(i));
    var shifted = toNumber(remap.keyValue(i), 0) + delta;
    shiftedValues.push(
      footageDuration > 0 ? Math.max(0, Math.min(footageDuration, shifted)) : Math.max(0, shifted)
    );
  }
  for (var keyIndex = 0; keyIndex < keyTimes.length; keyIndex++) {
    remap.setValueAtTime(keyTimes[keyIndex], shiftedValues[keyIndex]);
  }
}

function findGeneratedComp(): any {
  var project = app.project;
  if (!project) return null;
  for (var i = project.numItems; i >= 1; i--) {
    var item = project.item(i);
    if (item && item.name === "FlagshipEditor_Edit" && item instanceof CompItem) return item;
  }
  return null;
}

function findCutLayer(comp: any, beatTime: number, sectionType: string): any {
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

function importFile(path: string): any {
  var file = new File(path);
  if (!file.exists) return null;
  var importOptions = new ImportOptions(file);
  return app.project.importFile(importOptions);
}

function normalizeMediaPath(path: string): string {
  return String(path || "").replace(/\\/g, "/").toLowerCase();
}

function findProjectFootage(path: string): any {
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

function findOrImportProjectFootage(path: string): any {
  var project = app.project;
  var existing = findProjectFootage(path);
  if (existing) return existing;
  var imported = importFile(path);
  if (!imported || !project || typeof project.numItems !== "number") return imported;
  for (var folderIndex = project.numItems; folderIndex >= 1; folderIndex--) {
    var folder = project.item(folderIndex);
    if (folder && folder.name === "FlagshipEditor_Clips") {
      try { imported.parentFolder = folder; } catch (e) {}
      break;
    }
  }
  return imported;
}

function arrayContains(values: any[], expected: any): boolean {
  for (var i = 0; i < values.length; i++) {
    if (values[i] === expected) return true;
  }
  return false;
}

// A style preset can name an effect this build has no routine for — a newer
// preset opened by an older install. Nothing would apply it, so say so rather
// than letting the user believe the preset ran in full.
function warnUnimplementedEffects(style: StyleConfig, warnings: string[]): void {
  if (!style) return;
  var routed = PER_CUT_EFFECTS.concat(COMP_WIDE_EFFECTS);
  routed.push("color_grading");
  routed.push("element_3d");
  for (var key in style) {
    if (!Object.prototype.hasOwnProperty.call(style, key)) continue;
    var config = style[key];
    if (!config || typeof config !== "object" || config.enabled !== true) continue;
    if (arrayContains(routed, key)) continue;
    var message = "Style effect is not implemented and was skipped: " + key;
    if (!arrayContains(warnings, message)) warnings.push(message);
  }
}

function isEffectActive(style: StyleConfig, effectName: string, sectionType: string): boolean {
  var config = style[effectName];
  if (!config || config.enabled !== true) return false;
  var sections = config.sections;
  if (!sections || typeof sections.length !== "number" || sections.length === 0) return true;
  return arrayContains(sections, sectionType);
}

function applyVFXToLayer(
  layer: any,
  style: StyleConfig,
  sectionType: string,
  beatTime: number,
  context: VFXContext
): void {
  var plan: LayerPlan = createLayerPlan(layer);

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

function applyCompWideVFX(style: StyleConfig, context: VFXContext): void {
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
export function describeStyleCoverage(style: StyleConfig): string {
  try {
    var active: string[] = [];
    var inactive: string[] = [];
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
    return JSON.stringify({ __result: { active: active, inactive: inactive, total: all.length + 1 } });
  } catch (e) {
    return JSON.stringify({ __error: String(e) });
  }
}

export function getBuildWarnings(): string {
  if (!activeBuild) return JSON.stringify({ __result: { warnings: [] } });
  return JSON.stringify({ __result: { warnings: uniqueWarningStrings(activeBuild.warnings) } });
}

// Surfaced for the panel's 3D tab so the user sees whether the plugin is there
// before they generate an edit that silently skips it.
export function probeElement3D(): string {
  var project = app.project;
  if (!project) {
    return JSON.stringify({ __error: "No After Effects project is open" });
  }
  var probeComp: any = null;
  try {
    probeComp = project.items.addComp("FlagshipEditor_ElementProbe", 16, 16, 1, 0.1, 24);
    resetElement3DDetection();
    var matchName = detectElement3D(probeComp);
    return JSON.stringify({ __result: { installed: matchName !== null, matchName: matchName } });
  } catch (e) {
    return JSON.stringify({ __error: String(e) });
  } finally {
    removeProjectItem(probeComp);
    resetElement3DDetection();
  }
}
