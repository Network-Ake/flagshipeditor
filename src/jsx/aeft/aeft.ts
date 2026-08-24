// After Effects specific ExtendScript functions
// Type-safe, compiled to ES3 via Bolt CEP

import { applyZoomPunch, applyCameraShake, applyWhipPan, applyGlitch, applySpeedRamp, applyFreezeFrame, applyFaceMask, applySmokeFog, applySlowMo, applyBeatFlash, applyLightLeaks, applyVHSOverlay, applyFilmGrain, applyLetterbox, applyDepthBlur, applySmoothTransitions, applyMaskTransition, applyPictureFlash, applySelectiveColor, applySlowPushIn, applyRGBSplit, applyStrobe, applyLightWrap } from "./vfx_engine";
import { applyColorGrading } from "./color_grading";
import { createElement3DSolid } from "./element_3d";

interface BeatData {
  tempo: number;
  beats: number[];
  downbeats: number[];
  sections: { type: string; start: number; end: number }[];
  energy: number[];
  bass_onsets: number[];
  hihat_onsets: number[];
  key: string;
  mode: string;
  duration: number;
}

interface ClipData {
  path: string;
  name: string;
  duration: number;
  scene_type: string;
  has_face: boolean;
  brightness: number;
  motion_intensity: number;
}

interface StyleConfig {
  style_name: string;
  display_name: string;
  cut_strategy: { [section: string]: any };
  zoom_punch?: any;
  whip_pan?: any;
  text_overlays?: any;
  color_grading?: any;
  camera_shake?: any;
  glitch_effect?: any;
  element_3d?: any;
  face_mask?: any;
  [key: string]: any;
}

interface EditingParameters {
  cutIntensity: number;
  vfxIntensity: number;
  colorGrading: number;
  zoomPunch: boolean;
  whipPan: boolean;
  cameraShake: boolean;
  glitch: boolean;
  element3d: boolean;
}

interface Element3DSettings {
  parallaxDepth: number;
  autoCamera: boolean;
}

interface CutDecision {
  beatTime: number;
  clipPath: string;
  clipName: string;
  sectionType: string;
}

interface TimelineCut extends CutDecision {
  endTime: number;
}

var activeBuild: any = null;

export function beginComp(
  duration: number,
  audioPath: string,
  runtimeStyle: StyleConfig,
  params: EditingParameters,
  element3D: Element3DSettings,
  sections: { type: string; start: number; end: number }[],
  extensionPath: string
): string {
  var comp: any = null;
  var clipsFolder: any = null;
  var audioItem: any = null;
  try {
    if (activeBuild) cleanupActiveBuild();
    var project = app.project;
    if (!project) return JSON.stringify({ __error: "No After Effects project is open" });
    if (!isFinite(duration) || duration <= 0) {
      return JSON.stringify({ __error: "The analyzed music duration is invalid" });
    }
    var audioFile = new File(audioPath);
    if (!audioFile.exists) {
      return JSON.stringify({ __error: "Music file is missing: " + audioPath });
    }

    var compWidth = 1920;
    var compHeight = 1080;
    var compFps = 30;
    // Detect FPS from the first available footage item, not just audio
    try {
      var firstItem = project.numItems > 0 ? project.item(1) : null;
      if (firstItem && firstItem.frameRate) {
        var detectedFps = firstItem.frameRate;
        if (detectedFps > 0 && isFinite(detectedFps)) compFps = detectedFps;
      }
    } catch (fpsErr) {}
    // Detect resolution from the first footage item if available
    try {
      var firstFootage = project.numItems > 0 ? project.item(1) : null;
      if (firstFootage && firstFootage.width && firstFootage.height) {
        compWidth = firstFootage.width;
        compHeight = firstFootage.height;
      }
    } catch (resErr) {}
    app.beginUndoGroup("FlagshipEditor Build");
    comp = project.items.addComp("FlagshipEditor_Edit", compWidth, compHeight, 1, duration, compFps);
    clipsFolder = project.items.addFolder("FlagshipEditor_Clips");
    audioItem = importFile(audioPath);
    if (!audioItem) throw new Error("After Effects could not import the music file");
    var audioLayer = comp.layers.add(audioItem);
    audioLayer.name = "MUSIC";

    var configuredStyle = applyParameterOverrides(runtimeStyle, params, element3D);
    if (configuredStyle.color_grading) {
      configuredStyle.color_grading.extension_root = extensionPath;
    }
    activeBuild = {
      comp: comp,
      clipsFolder: clipsFolder,
      audioItem: audioItem,
      styleConfig: configuredStyle,
      element3D: element3D,
      sections: sections || [],
      footagePaths: [],
      footageItems: [],
      added: 0,
      warnings: []
    };
    appendUnsupportedEffectWarnings(activeBuild, configuredStyle);
    return JSON.stringify({ __result: { started: true, compName: comp.name } });
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
    var added = 0;
    var skipped = 0;
    for (var i = 0; i < cuts.length; i++) {
      var cut = cuts[i];
      if (!cut || !cut.clipPath || cut.endTime <= cut.beatTime) {
        skipped++;
        continue;
      }
      var clipItem = getOrImportFootage(cut.clipPath);
      if (!clipItem) {
        activeBuild.warnings.push("Missing clip: " + cut.clipPath);
        skipped++;
        continue;
      }
      var clipLayer = activeBuild.comp.layers.add(clipItem);
      clipLayer.startTime = cut.beatTime;
      clipLayer.outPoint = Math.min(cut.endTime, activeBuild.comp.duration);
      clipLayer.name = cut.clipName + " [" + cut.sectionType + "]";
      clipLayer.comment = cutTag(cut.beatTime, cut.sectionType);
      try {
        applyVFXToLayer(clipLayer, activeBuild.styleConfig, cut.sectionType, cut.beatTime);
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
    if (build.styleConfig.color_grading) {
      build.warnings = build.warnings.concat(
        applyColorGrading(build.comp, build.sections, build.styleConfig.color_grading)
      );
    }
    if (build.styleConfig.element_3d && build.styleConfig.element_3d.enabled) {
      try {
        createElement3DSolid(build.comp, build.styleConfig.element_3d);
      } catch (elementError) {
        build.warnings.push("3D setup skipped: " + String(elementError));
      }
    }
    for (var i = 0; i < build.sections.length; i++) {
      var section = build.sections[i];
      build.comp.markerProperty.setValueAtTime(
        section.start,
        new MarkerValue(section.type.toUpperCase())
      );
    }
    build.comp.openInViewer();
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

function getOrImportFootage(path: string): any {
  for (var i = 0; i < activeBuild.footagePaths.length; i++) {
    if (activeBuild.footagePaths[i] === path) return activeBuild.footageItems[i];
  }
  var item = importFile(path);
  if (!item) return null;
  item.parentFolder = activeBuild.clipsFolder;
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
  clipName: string
): string {
  try {
    var comp = findGeneratedComp();
    if (!comp) return JSON.stringify({ __result: { updated: 0, message: "Generated comp not found" } });
    var layer = findCutLayer(comp, beatTime, sectionType);
    if (!layer) return JSON.stringify({ __result: { updated: 0, message: "Cut layer not found" } });
    var footage = findOrImportProjectFootage(clipPath);
    if (!footage) return JSON.stringify({ __result: { updated: 0, message: "Replacement file is missing" } });
    layer.replaceSource(footage, false);
    layer.name = clipName + " [" + sectionType + "]";
    return JSON.stringify({ __result: { updated: 1 } });
  } catch (e) {
    return JSON.stringify({ __error: String(e) });
  }
}

export function replaceSectionCuts(sectionType: string, decisions: CutDecision[]): string {
  try {
    var comp = findGeneratedComp();
    if (!comp) return JSON.stringify({ __result: { updated: 0, message: "Generated comp not found" } });
    var updated = 0;
    for (var i = 0; i < decisions.length; i++) {
      var decision = decisions[i];
      var layer = findCutLayer(comp, decision.beatTime, sectionType);
      if (!layer) continue;
      var footage = findOrImportProjectFootage(decision.clipPath);
      if (!footage) continue;
      layer.replaceSource(footage, false);
      layer.name = decision.clipName + " [" + sectionType + "]";
      updated++;
    }
    return JSON.stringify({ __result: { updated: updated } });
  } catch (e) {
    return JSON.stringify({ __error: String(e) });
  }
}

function applyParameterOverrides(
  style: StyleConfig,
  params: EditingParameters,
  element3D: Element3DSettings
): StyleConfig {
  if (style.zoom_punch) style.zoom_punch.enabled = params.zoomPunch && params.vfxIntensity > 0;
  if (style.whip_pan) style.whip_pan.enabled = params.whipPan && params.vfxIntensity > 0;
  if (style.camera_shake) style.camera_shake.enabled = params.cameraShake && params.vfxIntensity > 0;
  if (style.glitch_effect) style.glitch_effect.enabled = params.glitch && params.vfxIntensity > 0;
  if (style.color_grading) {
    style.color_grading.enabled = params.colorGrading > 0;
    style.color_grading.opacity = params.colorGrading * 10;
  }
  style.element_3d = style.element_3d || {};
  style.element_3d.enabled = params.element3d;
  style.element_3d.auto_camera = element3D.autoCamera;
  style.element_3d.parallax_depth = element3D.parallaxDepth;
  return style;
}

function cutTag(beatTime: number, sectionType: string): string {
  return "FlagshipEditorCut|" + sectionType + "|" + beatTime.toFixed(4);
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

function findOrImportProjectFootage(path: string): any {
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

function applyVFXToLayer(
  layer: any,
  style: StyleConfig,
  sectionType: string,
  beatTime: number
): void {
  var fps = 30;
  try {
    if (layer.containingComp && layer.containingComp.frameRate) {
      fps = layer.containingComp.frameRate;
    }
  } catch (e) {}

  if (style.zoom_punch && style.zoom_punch.enabled) {
    var sections = style.zoom_punch.sections || [];
    if (arrayContains(sections, sectionType) || sections.length === 0) {
      applyZoomPunch(layer, style.zoom_punch, beatTime, fps);
    }
  }

  if (style.camera_shake && style.camera_shake.enabled) {
    var shakeSections = style.camera_shake.sections || [];
    if (arrayContains(shakeSections, sectionType) || shakeSections.length === 0) {
      applyCameraShake(layer, style.camera_shake, beatTime, fps);
    }
  }

  if (style.whip_pan && style.whip_pan.enabled) {
    var whipSections = style.whip_pan.sections || [];
    if (arrayContains(whipSections, sectionType) || whipSections.length === 0) {
      applyWhipPan(layer, style.whip_pan, beatTime, fps);
    }
  }

  if (style.glitch_effect && style.glitch_effect.enabled) {
    var glitchSections = style.glitch_effect.sections || [];
    if (arrayContains(glitchSections, sectionType) || glitchSections.length === 0) {
      applyGlitch(layer, style.glitch_effect, beatTime, fps);
    }
  }

  if (style.speed_ramp && style.speed_ramp.enabled) {
    var speedSections = style.speed_ramp.sections || [];
    if (arrayContains(speedSections, sectionType) || speedSections.length === 0) {
      applySpeedRamp(layer, style.speed_ramp, beatTime, fps);
    }
  }

  if (style.freeze_frame && style.freeze_frame.enabled) {
    var freezeSections = style.freeze_frame.sections || [];
    if (arrayContains(freezeSections, sectionType) || freezeSections.length === 0) {
      var freezeDur = style.freeze_frame.duration_frames || 6;
      applyFreezeFrame(layer, beatTime, freezeDur, fps);
    }
  }

  if (style.face_mask && style.face_mask.enabled) {
    var faceMaskSections = style.face_mask.sections || [];
    if (arrayContains(faceMaskSections, sectionType) || faceMaskSections.length === 0) {
      applyFaceMask(layer, style.face_mask, beatTime, fps);
    }
  }

  if (style.smoke_fog && style.smoke_fog.enabled) {
    var smokeFogSections = style.smoke_fog.sections || [];
    if (arrayContains(smokeFogSections, sectionType) || smokeFogSections.length === 0) {
      applySmokeFog(layer, style.smoke_fog, beatTime, fps);
    }
  }

  if (style.slow_mo && style.slow_mo.enabled) {
    var slowMoSections = style.slow_mo.sections || [];
    if (arrayContains(slowMoSections, sectionType) || slowMoSections.length === 0) {
      applySlowMo(layer, style.slow_mo, beatTime, fps);
    }
  }

  if (style.beat_flash && style.beat_flash.enabled) {
    var beatFlashSections = style.beat_flash.sections || [];
    if (arrayContains(beatFlashSections, sectionType) || beatFlashSections.length === 0) {
      applyBeatFlash(layer, style.beat_flash, beatTime, fps);
    }
  }

  if (style.light_leaks && style.light_leaks.enabled) {
    var lightLeaksSections = style.light_leaks.sections || [];
    if (arrayContains(lightLeaksSections, sectionType) || lightLeaksSections.length === 0) {
      applyLightLeaks(layer, style.light_leaks, beatTime, fps);
    }
  }

  if (style.vhs_overlay && style.vhs_overlay.enabled) {
    var vhsOverlaySections = style.vhs_overlay.sections || [];
    if (arrayContains(vhsOverlaySections, sectionType) || vhsOverlaySections.length === 0) {
      applyVHSOverlay(layer, style.vhs_overlay, beatTime, fps);
    }
  }

  if (style.film_grain && style.film_grain.enabled) {
    var filmGrainSections = style.film_grain.sections || [];
    if (arrayContains(filmGrainSections, sectionType) || filmGrainSections.length === 0) {
      applyFilmGrain(layer, style.film_grain, beatTime, fps);
    }
  }

  if (style.letterbox && style.letterbox.enabled) {
    var letterboxSections = style.letterbox.sections || [];
    if (arrayContains(letterboxSections, sectionType) || letterboxSections.length === 0) {
      applyLetterbox(layer, style.letterbox, beatTime, fps);
    }
  }

  if (style.depth_blur && style.depth_blur.enabled) {
    var depthBlurSections = style.depth_blur.sections || [];
    if (arrayContains(depthBlurSections, sectionType) || depthBlurSections.length === 0) {
      applyDepthBlur(layer, style.depth_blur, beatTime, fps);
    }
  }

  if (style.smooth_transitions && style.smooth_transitions.enabled) {
    var smoothTransitionsSections = style.smooth_transitions.sections || [];
    if (arrayContains(smoothTransitionsSections, sectionType) || smoothTransitionsSections.length === 0) {
      applySmoothTransitions(layer, style.smooth_transitions, beatTime, fps);
    }
  }

  if (style.mask_transition && style.mask_transition.enabled) {
    var maskTransitionSections = style.mask_transition.sections || [];
    if (arrayContains(maskTransitionSections, sectionType) || maskTransitionSections.length === 0) {
      applyMaskTransition(layer, style.mask_transition, beatTime, fps);
    }
  }

  if (style.picture_flash && style.picture_flash.enabled) {
    var pictureFlashSections = style.picture_flash.sections || [];
    if (arrayContains(pictureFlashSections, sectionType) || pictureFlashSections.length === 0) {
      applyPictureFlash(layer, style.picture_flash, beatTime, fps);
    }
  }

  if (style.selective_color && style.selective_color.enabled) {
    var selectiveColorSections = style.selective_color.sections || [];
    if (arrayContains(selectiveColorSections, sectionType) || selectiveColorSections.length === 0) {
      applySelectiveColor(layer, style.selective_color, beatTime, fps);
    }
  }

  if (style.slow_push_in && style.slow_push_in.enabled) {
    var slowPushInSections = style.slow_push_in.sections || [];
    if (arrayContains(slowPushInSections, sectionType) || slowPushInSections.length === 0) {
      applySlowPushIn(layer, style.slow_push_in, beatTime, fps);
    }
  }

  if (style.rgb_split && style.rgb_split.enabled) {
    var rgbSplitSections = style.rgb_split.sections || [];
    if (arrayContains(rgbSplitSections, sectionType) || rgbSplitSections.length === 0) {
      applyRGBSplit(layer, style.rgb_split, beatTime, fps);
    }
  }

  if (style.strobe && style.strobe.enabled) {
    var strobeSections = style.strobe.sections || [];
    if (arrayContains(strobeSections, sectionType) || strobeSections.length === 0) {
      applyStrobe(layer, style.strobe, beatTime, fps);
    }
  }

  if (style.light_wrap && style.light_wrap.enabled) {
    var lightWrapSections = style.light_wrap.sections || [];
    if (arrayContains(lightWrapSections, sectionType) || lightWrapSections.length === 0) {
      applyLightWrap(layer, style.light_wrap, beatTime, fps);
    }
  }
}

function appendUnsupportedEffectWarnings(build: any, style: StyleConfig): void {
  var unsupported: string[] = [];
  for (var i = 0; i < unsupported.length; i++) {
    var effectName = unsupported[i];
    var config = style[effectName];
    if (config && config.enabled === true) {
      build.warnings.push("Style effect is not implemented and was skipped: " + effectName);
    }
  }
}
