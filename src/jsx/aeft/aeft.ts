// After Effects specific ExtendScript functions
// Type-safe, compiled to ES3 via Bolt CEP

import { applyZoomPunch, applyCameraShake, applyWhipPan, applyGlitch } from "./vfx_engine";
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

export function buildComp(
  beatData: BeatData,
  clips: ClipData[],
  styleName: string,
  audioPath: string
): string {
  try {
    var project = app.project;
    if (!project) return JSON.stringify({ __error: "No project open" });

    // Load style config
    var styleConfig = loadStyleConfig(styleName);

    // Create comp
    var comp = project.items.addComp(
      "FlagshipEditor_Edit",
      1920, 1080,
      1,
      beatData.duration,
      30
    );
    comp.openInViewer();

    // Import and place audio
    var audioItem = importFile(audioPath);
    if (audioItem) {
      var audioLayer = comp.layers.add(audioItem);
      audioLayer.name = "MUSIC";
    }

    // Create clips folder
    var clipsFolder = project.items.addFolder("FlagshipEditor_Clips");

    // Build timeline section by section
    for (var s = 0; s < beatData.sections.length; s++) {
      var section = beatData.sections[s];
      var sectionStyle = styleConfig.cut_strategy[section.type];
      if (!sectionStyle) continue;

      var cutInterval = parseBeatInterval(sectionStyle.cut_interval, beatData.tempo);
      var sectionClips = selectClipsForSection(clips, section, styleConfig);

      var beatsInSection = getBeatsInRange(beatData.beats, section.start, section.end);

      var clipIndex = 0;
      for (var i = 0; i < beatsInSection.length; i++) {
        if (i % cutInterval === 0) {
          var clip = sectionClips[clipIndex % sectionClips.length];
          var clipItem = importFile(clip.path);
          if (clipItem) {
            clipItem.parentFolder = clipsFolder;
            var clipLayer = comp.layers.add(clipItem);
            clipLayer.startTime = beatsInSection[i];
            clipLayer.name = clip.name + " [" + section.type + "]";

            // Apply VFX
            applyVFXToLayer(clipLayer, styleConfig, section.type, beatData, beatsInSection[i]);
          }
          clipIndex++;
        }
      }
    }

    // Apply color grading
    if (styleConfig.color_grading) {
      applyColorGrading(comp, beatData.sections, styleConfig.color_grading);
    }

    // Create Element 3D solid
    if (styleConfig.element_3d && styleConfig.element_3d.enabled) {
      createElement3DSolid(comp, styleConfig.element_3d);
    }

    // Add section markers
    for (var m = 0; m < beatData.sections.length; m++) {
      var sec = beatData.sections[m];
      comp.markerProperty.setValueAtTime(
        sec.start,
        new MarkerValue(sec.type.toUpperCase())
      );
    }

    return JSON.stringify({ __result: "Comp created: " + comp.name });
  } catch (e) {
    return JSON.stringify({ __error: String(e) });
  }
}

function importFile(path: string): any {
  var file = new File(path);
  if (!file.exists) return null;
  var importOptions = new ImportOptions(file);
  return app.project.importFile(importOptions);
}

function loadStyleConfig(styleName: string): StyleConfig {
  // Styles are loaded from the styles/ folder bundled with the extension
  var scriptFile = new File($.fileName);
  var scriptDir = scriptFile.parent;
  var styleFile = new File(scriptDir.absoluteURI + "/styles/" + styleName + ".json");
  if (!styleFile.exists) {
    // Fallback to default
    styleFile = new File(scriptDir.absoluteURI + "/styles/cmd_command_drill.json");
  }
  styleFile.encoding = "UTF-8";
  styleFile.open("r");
  var content = styleFile.read();
  styleFile.close();
  return JSON.parse(content);
}

function parseBeatInterval(interval: string, tempo: number): number {
  var parts = interval.split("_");
  var n = parseInt(parts[0]);
  var unit = parts[1];
  if (unit === "beat") return n;
  return n;
}

function getBeatsInRange(beats: number[], start: number, end: number): number[] {
  var result: number[] = [];
  for (var i = 0; i < beats.length; i++) {
    if (beats[i] >= start && beats[i] < end) {
      result.push(beats[i]);
    }
  }
  return result;
}

function selectClipsForSection(
  clips: ClipData[],
  section: { type: string; start: number; end: number },
  style: StyleConfig
): ClipData[] {
  // Sort clips by relevance to section type
  var preferred: ClipData[] = [];
  var others: ClipData[] = [];

  for (var i = 0; i < clips.length; i++) {
    var clip = clips[i];
    if (section.type === "chorus" || section.type === "drop") {
      if (clip.scene_type === "close_up" || clip.scene_type === "performance") {
        preferred.push(clip);
      } else {
        others.push(clip);
      }
    } else if (section.type === "intro" || section.type === "outro") {
      if (clip.scene_type === "b_roll_static" || clip.scene_type === "b_roll_low_light") {
        preferred.push(clip);
      } else {
        others.push(clip);
      }
    } else {
      if (clip.scene_type === "performance") {
        preferred.push(clip);
      } else {
        others.push(clip);
      }
    }
  }

  return preferred.concat(others);
}

function applyVFXToLayer(
  layer: any,
  style: StyleConfig,
  sectionType: string,
  beatData: BeatData,
  beatTime: number
): void {
  var fps = 30;

  if (style.zoom_punch && style.zoom_punch.enabled) {
    var sections = style.zoom_punch.sections || [];
    if (sections.indexOf(sectionType) !== -1 || sections.length === 0) {
      applyZoomPunch(layer, style.zoom_punch, beatTime, fps);
    }
  }

  if (style.camera_shake) {
    var shakeSections = style.camera_shake.sections || [];
    if (shakeSections.indexOf(sectionType) !== -1 || shakeSections.length === 0) {
      applyCameraShake(layer, style.camera_shake);
    }
  }

  if (style.whip_pan && style.whip_pan.enabled) {
    applyWhipPan(layer, style.whip_pan, beatTime, fps);
  }

  if (style.glitch_effect && style.glitch_effect.enabled) {
    var glitchSections = style.glitch_effect.sections || [];
    if (glitchSections.indexOf(sectionType) !== -1 || glitchSections.length === 0) {
      applyGlitch(layer, style.glitch_effect, beatTime, fps);
    }
  }
}