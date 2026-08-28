import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";

import { createHostContext, expectError, unwrap } from "./lib/ae-mock.mjs";

const root = process.cwd();
const packageVersion = JSON.parse(fs.readFileSync(path.join(root, "package.json"), "utf8")).version;
const bundlePath = path.join(root, "dist", "cep", "jsx", "index.js");
const source = fs.readFileSync(bundlePath, "utf8");

function loadBridge(options) {
  const host = createHostContext(options);
  vm.createContext(host.context);
  vm.runInContext(source, host.context, { filename: bundlePath });
  return host;
}

const SECTIONS = [
  { type: "intro", start: 0, end: 4 },
  { type: "verse", start: 4, end: 8 },
  { type: "drop", start: 8, end: 12 },
];

const MEDIA_PROFILE = { width: 2160, height: 3840, fps: 23.976 };

function baseParams(overrides = {}) {
  return {
    cutIntensity: 7,
    vfxIntensity: 8,
    colorGrading: 6,
    seed: 42,
    effects: {},
    ...overrides,
  };
}

function fullStyle() {
  return {
    style_name: "test",
    display_name: "Test",
    cut_strategy: {},
    zoom_punch: { enabled: true, scale_target: 140, scale_duration_frames: 4, ease_out_frames: 10 },
    slow_push_in: { enabled: true, scale_start: 100, scale_end: 112 },
    smooth_transitions: { enabled: true, fade_frames: 3 },
    beat_flash: { enabled: true, opacity_peak: 55, duration_frames: 3 },
    camera_shake: { enabled: true, frequency_hz: 25, displacement_px: 14, decay_factor: 0.8 },
    whip_pan: { enabled: true, displacement_px: 1600, duration_frames: 5 },
    glitch_effect: { enabled: true, duration_frames: 3, displacement_px: 15 },
    speed_ramp: { enabled: true, speed_in: 100, speed_out: 220, ramp_duration_beats: 2 },
    // speed_ramp, slow_mo and freeze_frame all drive time remapping, so the
    // bridge picks one per cut; all three still have to be routed.
    slow_mo: { enabled: true, speed_factor: 0.4, ramp_in_frames: 3 },
    freeze_frame: { enabled: true, duration_frames: 6, ease_frames: 2 },
    rgb_split: { enabled: true, displacement_px: 5 },
    strobe: { enabled: true, frequency_hz: 12, opacity_peak: 100, cycles: 3 },
    picture_flash: { enabled: true, duration_frames: 2, opacity_peak: 85 },
    face_mask: { enabled: true, blur_radius: 40 },
    depth_blur: { enabled: true, blur_radius: 30, fade_frames: 12 },
    selective_color: { enabled: true, saturation_boost: 30, desaturate_rest: -10 },
    mask_transition: { enabled: true, duration_frames: 6 },
    film_grain: { enabled: true, intensity: 6 },
    letterbox: { enabled: true, aspect_ratio: 2.39, bars_color: "black" },
    light_wrap: { enabled: true, intensity: 40, threshold: 70 },
    light_leaks: { enabled: true, opacity: 40, frequency: 12 },
    vhs_overlay: { enabled: true, opacity: 35 },
    smoke_fog: { enabled: true, opacity: 20, density: 60, color: "grey" },
    color_grading: {
      global_lut: "test.cube",
      params: { temperature_k: 4500, contrast: 20, saturation: -15 },
      section_luts: {},
    },
    element_3d: { enabled: true, solid_name: "FlagshipEditor_3D_Solid", parallax_depth: 0.4 },
  };
}

function cuts() {
  return [
    { beatTime: 0, endTime: 4, sourceStart: 1, sourceEnd: 5, clipPath: "C:/media/a.mov", clipName: "a.mov", sectionType: "intro" },
    { beatTime: 4, endTime: 8, sourceStart: 2, sourceEnd: 6, clipPath: "C:/media/b.mov", clipName: "b.mov", sectionType: "verse" },
    { beatTime: 8, endTime: 12, sourceStart: 3, sourceEnd: 7, clipPath: "C:/media/a.mov", clipName: "a.mov", sectionType: "drop" },
  ];
}

// --- Bridge surface ---------------------------------------------------------
{
  const { context } = loadBridge();
  for (const name of [
    "getBridgeHealth",
    "getExtensionRoot",
    "beginComp",
    "appendCutBatch",
    "finishComp",
    "abortComp",
    "swapCut",
    "replaceSectionCuts",
    "describeStyleCoverage",
    "getBuildWarnings",
    "probeElement3D",
    "openFileDialog",
    "openFilesDialog",
    "openFolderDialog",
  ]) {
    assert.equal(typeof context[name], "function", `Missing compiled AE bridge function: ${name}`);
  }

  const bridgeHealth = unwrap(context.getBridgeHealth(), "getBridgeHealth");
  assert.deepEqual(bridgeHealth, {
    appId: "com.akestudio.flagshipeditor.bridge",
    version: packageVersion,
    hostName: "After Effects",
    hostVersion: "24.6",
  });
}

// --- File dialogs -----------------------------------------------------------
{
  const { context, FileMock, FolderMock } = loadBridge();
  FileMock.openDialog = (_prompt, _filter, multiSelect) => {
    if (!multiSelect) return null;
    const single = new FileMock("C:/media/single.mov");
    single.length = 987654;
    return single;
  };
  assert.deepEqual(
    JSON.parse(context.openFilesDialog("Video files:*.mov,All files:*.*")),
    { __result: ["C:/media/single.mov"] },
    "A one-file multi-select result must not collapse to an empty list",
  );
  FileMock.openDialog = () => [new FileMock("C:/media/first.mov"), new FileMock("C:/media/second.mp4")];
  assert.deepEqual(JSON.parse(context.openFilesDialog("All files:*.*")), {
    __result: ["C:/media/first.mov", "C:/media/second.mp4"],
  });
  FileMock.openDialog = () => null;
  assert.deepEqual(JSON.parse(context.openFilesDialog("All files:*.*")), { __result: [] });
  FolderMock.selectDialog = () => new FolderMock("C:/media/library");
  assert.deepEqual(JSON.parse(context.openFolderDialog()), { __result: "C:/media/library" });
  FolderMock.selectDialog = () => null;
  assert.deepEqual(JSON.parse(context.openFolderDialog()), { __result: null });
}

// --- Full build with every effect enabled -----------------------------------
{
  const { context, project, undo } = loadBridge();
  const begun = unwrap(
    context.beginComp(12, "C:/media/song.wav", fullStyle(), baseParams(), { parallaxDepth: 0.4, autoCamera: true }, SECTIONS, "C:/extension", MEDIA_PROFILE, 140),
    "beginComp",
  );
  assert.equal(begun.started, true);
  assert.equal(begun.width, 2160, "Comp width must come from the analysed media profile");
  assert.equal(begun.height, 3840, "Comp height must come from the analysed media profile");
  assert.equal(begun.fps, 24, "Comp frame rate must snap 23.976 to 24");

  const appended = unwrap(context.appendCutBatch(cuts()), "appendCutBatch");
  assert.equal(appended.added, 3);
  assert.equal(appended.skipped, 0);

  const finished = unwrap(context.finishComp(), "finishComp");
  assert.equal(finished.clipsAdded, 3);
  assert.equal(undo.depth, 0, "finishComp must close its undo group");
  assert.equal(undo.maxDepth, 1, "The build must open exactly one undo group");

  const comp = project.comps[0];
  assert.equal(comp.openedInViewer, true);
  assert.equal(project.importedPaths.length, 3, "One music import plus two unique footage imports");

  const clipLayers = comp.layerList.filter((layer) => /FlagshipEditorCut\|/.test(layer.comment));
  assert.equal(clipLayers.length, 3, "Every cut must produce exactly one tagged clip layer");

  // Scale composition: slow push-in and zoom punch must both survive.
  const scale = clipLayers[0].transform("ADBE Scale");
  assert.ok(scale, "The clip layer must have an animated scale property");
  assert.ok(scale.numKeys >= 4, `Composed scale needs the push-in and punch keys, saw ${scale.numKeys}`);
  const peak = Math.max(...scale.keys.map((key) => key.value[0]));
  assert.ok(peak > 115, `Zoom punch must exceed the slow push-in ramp, peaked at ${peak}`);
  const ends = scale.keys[scale.keys.length - 1].value[0];
  assert.ok(ends > 100 && ends < 130, `Scale must land on the push-in target, landed on ${ends}`);
  for (const key of scale.keys) {
    assert.ok(
      Number.isFinite(key.value[0]) && key.value[0] > 0,
      `Scale keyframe must be a positive number, saw ${key.value[0]}`,
    );
  }

  // Opacity composition: smooth transitions plus the beat flash dip.
  const opacity = clipLayers[0].transform("ADBE Opacity");
  assert.ok(opacity && opacity.numKeys >= 4, "Opacity must carry the fade and the flash");
  assert.equal(opacity.keys[0].value, 0, "Smooth transitions must start the cut at zero opacity");
  const dip = Math.min(...opacity.keys.filter((key) => key.time > 0.1).map((key) => key.value));
  assert.ok(dip < 100, "The beat flash must dip the opacity");
  for (const key of opacity.keys) {
    assert.ok(key.value >= 0 && key.value <= 100, `Opacity out of range: ${key.value}`);
  }

  // Camera shake must be keyframed and decaying, never an expression.
  const position = clipLayers[0].transform("ADBE Position");
  assert.ok(position.numKeys > 5, "Camera shake must write keyframes");
  assert.equal(position.expression, "", "Camera shake must not fall back to a wiggle expression");
  const origin = 960;
  const firstSwing = Math.abs(position.keys[1].value[0] - origin);
  const lastSwing = Math.abs(position.keys[position.numKeys - 2].value[0] - origin);
  assert.ok(lastSwing < firstSwing, "Camera shake amplitude must decay over the burst");

  // Time remap values are source time, so they must stay inside the source.
  const remapped = clipLayers.filter((layer) => layer.timeRemap);
  assert.ok(remapped.length > 0, "Speed ramp must enable time remapping");
  for (const layer of remapped) {
    const cut = cuts().find((entry) => layer.comment === `FlagshipEditorCut|${entry.sectionType}|${entry.beatTime.toFixed(4)}`);
    assert.ok(cut, `Time-remapped layer has an unknown cut tag: ${layer.comment}`);
    assert.equal(
      layer.startTime,
      cut.beatTime - cut.sourceStart,
      "AE layer startTime must place sourceStart exactly at the cut beat",
    );
    assert.equal(
      layer.timeRemap.keys[0].value,
      cut.sourceStart,
      "Time-remap VFX must begin from the selected best-moment source offset",
    );
    for (const key of layer.timeRemap.keys) {
      assert.ok(
        key.value >= 0 && key.value <= layer.source.duration + 1e-6,
        `Time remap value ${key.value} is outside the source duration ${layer.source.duration}`,
      );
    }
  }

  // Glitch: chromatic ghosts plus an animated self-displacement.
  const ghosts = comp.layerList.filter((layer) => /\[RGB-[RB]\]$/.test(layer.name));
  assert.equal(ghosts.length, 6, "Each of the three cuts must produce a red and a blue ghost");
  for (const ghost of ghosts) {
    const shift = ghost.effects.property("ADBE Shift Channels");
    assert.ok(shift, "Each ghost needs a Shift Channels effect");
    assert.equal(shift.get("Take Green From"), 10, "Green must be forced to Full Off on a ghost");
    assert.equal(ghost.blendingMode, 5002, "Ghost layers must add over the original");
  }
  for (const layer of clipLayers) {
    assert.equal(layer.blendingMode, 1, "The original clip must keep its normal blending mode");
    const displace = layer.effects.property("ADBE Turbulent Displace");
    assert.ok(displace, "Glitch must use a self-contained displacement effect");
    const amountKeys = displace.keysOf("Amount");
    assert.equal(amountKeys.length, 2, "Glitch displacement must be time bounded");
    assert.equal(amountKeys[1].value, 0, "Glitch displacement must resolve back to zero");
  }

  // Linear Wipe reveals the layer, so completion runs 100 -> 0.
  const wipe = clipLayers[0].effects.property("ADBE Linear Wipe");
  const wipeKeys = wipe.keysOf("Transition Completion");
  assert.equal(wipeKeys[0].value, 100);
  assert.equal(wipeKeys[wipeKeys.length - 1].value, 0, "A mask transition must reveal, not erase");

  // Hue/Saturation must drive Master Saturation, not the Channel Control menu.
  const hueSat = clipLayers[0].effects.property("ADBE HUE SATURATION");
  assert.equal(hueSat.keysOf("Channel Control").length, 0, "Channel Control is a menu, not an animation target");
  assert.ok(hueSat.keysOf("Master Saturation").length > 0, "Selective colour must animate Master Saturation");

  // Comp-wide effects: exactly one of each, never one per cut.
  assert.equal(comp.layersNamed("FlagshipEditor_Grain").length, 1, "Film grain must be a single adjustment layer");
  assert.equal(comp.layersNamed("FlagshipEditor_VHS").length, 1);
  assert.equal(comp.layersNamed("FlagshipEditor_LightWrap").length, 1);
  assert.equal(comp.layersNamed("FlagshipEditor_LightLeak").length, 1);
  assert.equal(comp.layersNamed("FlagshipEditor_Smoke").length, 1);
  assert.equal(comp.layersNamed("FlagshipEditor_Letterbox").length, 2, "Letterbox is one bar top and bottom");
  for (const name of ["FlagshipEditor_Grain", "FlagshipEditor_VHS", "FlagshipEditor_LightWrap"]) {
    assert.equal(comp.layerByName(name).adjustmentLayer, true, `${name} must be an adjustment layer`);
  }

  // Picture flash: one shared solid keyframed per beat, never one solid per cut.
  const flashLayers = comp.layersNamed("FlagshipEditor_Flash");
  assert.equal(flashLayers.length, 1, "Every picture flash must reuse one shared solid");
  const flashOpacity = flashLayers[0].transform("ADBE Opacity");
  const flashPeaks = flashOpacity.keys.filter((key) => key.value === 85);
  assert.equal(flashPeaks.length, 3, "Each of the three cuts must keyframe its own flash");
  for (const key of flashOpacity.keys) {
    assert.ok(key.value === 0 || key.value === 85, `Unexpected flash key value ${key.value}`);
  }
  for (const beat of [4, 8]) {
    assert.ok(
      flashOpacity.keys.some((key) => key.value === 0 && Math.abs(key.time - (beat - 1 / 24)) < 1e-6),
      `The shared flash must hold zero opacity until one frame before the beat at ${beat}s`,
    );
  }

  const grain = comp.layerByName("FlagshipEditor_Grain").effects.property("ADBE Noise");
  assert.equal(grain.get("Use Color Noise"), false, "Film grain is monochrome");
  assert.equal(grain.get("Amount of Noise"), 6);

  const vhsWarp = comp.layerByName("FlagshipEditor_VHS").effects.property("ADBE Wave Warp");
  assert.equal(vhsWarp.get("Wave Height"), 3, "Wave Warp height is parameter 2, not the wave type menu");
  assert.equal(vhsWarp.get("Wave Type"), undefined, "Wave Warp must not overwrite the wave type menu");

  const fog = comp.layerByName("FlagshipEditor_Smoke").effects.property("ADBE Fractal Noise");
  assert.ok(fog.get("Contrast") > 0, "Fractal Noise contrast is parameter 4");
  assert.equal(fog.get("Fractal Type"), undefined, "Fractal Noise must not overwrite the fractal type menu");
  assert.ok(fog.keysOf("Evolution").length === 2, "Fractal Noise evolution is parameter 10");

  // Colour grading must be a real adjustment layer, not an opaque white solid.
  const lut = comp.layerByName("FlagshipEditor_LUT_GLOBAL");
  assert.ok(lut, "A global LUT must produce a grading layer");
  assert.equal(lut.adjustmentLayer, true, "A LUT layer that is not an adjustment layer hides the edit");
  const lumetri = lut.effects.property("ADBE Lumetri Color");
  assert.ok(lumetri, "The grading layer must carry Lumetri Color");
  assert.match(String(lumetri.get("Input LUT")), /test\.cube$/);
  assert.equal(lumetri.get("Temperature"), 4500, "Colour params must land on the LUT layer");
  assert.equal(lumetri.get("Contrast"), 20);
  assert.equal(lumetri.get("Saturation"), -15);

  // Section markers, deduplicated by time.
  assert.deepEqual(
    comp.markers.map((marker) => marker.comment),
    ["INTRO", "VERSE", "DROP"],
  );

  // Element 3D is absent from this host, so it must warn instead of leaving a
  // black solid the user has to hunt down.
  assert.ok(
    finished.warnings.some((warning) => /Element 3D is not installed/.test(warning)),
    `Expected a missing-Element-3D warning, saw: ${JSON.stringify(finished.warnings)}`,
  );
  assert.equal(comp.layerByName("FlagshipEditor_3D_Solid"), null, "No 3D solid without the plugin");
  assert.equal(
    finished.warnings.some((warning) => /VFX skipped/.test(warning)),
    false,
    `Implemented VFX must not fail into a warning: ${JSON.stringify(finished.warnings)}`,
  );
}

// --- Selected source offset survives every time-remap mode -----------------
{
  const selectedCut = {
    beatTime: 1,
    endTime: 3,
    sourceStart: 2.5,
    sourceEnd: 4.5,
    clipPath: "C:/media/source-offset.mov",
    clipName: "source-offset.mov",
    sectionType: "verse",
  };
  for (const activeMode of ["speed_ramp", "slow_mo", "freeze_frame"]) {
    const { context, project } = loadBridge();
    const style = fullStyle();
    style.speed_ramp.enabled = activeMode === "speed_ramp";
    style.slow_mo.enabled = activeMode === "slow_mo";
    style.freeze_frame.enabled = activeMode === "freeze_frame";
    unwrap(
      context.beginComp(4, "C:/media/song.wav", style, baseParams(), {}, SECTIONS, "C:/extension", MEDIA_PROFILE, 140),
      "beginComp",
    );
    unwrap(context.appendCutBatch([selectedCut]), "appendCutBatch");
    unwrap(context.finishComp(), "finishComp");
    const layer = project.comps[0].layerList.find((entry) => /FlagshipEditorCut\|/.test(entry.comment));
    assert.ok(layer && layer.timeRemap, `${activeMode} must time-remap the selected cut`);
    assert.equal(
      layer.startTime,
      selectedCut.beatTime - selectedCut.sourceStart,
      `${activeMode} must retain the selected source offset in AE layer time`,
    );
    assert.equal(
      layer.timeRemap.keys[0].time,
      selectedCut.beatTime,
      `${activeMode} must key the selected source frame at the cut in-point`,
    );
    assert.equal(
      layer.timeRemap.keys[0].value,
      selectedCut.sourceStart,
      `${activeMode} must start at sourceStart, never source time zero`,
    );
  }
}

// --- Element 3D present -----------------------------------------------------
{
  const installed = [
    "ADBE Shift Channels",
    "ADBE Turbulent Displace",
    "ADBE Noise",
    "ADBE Lumetri Color",
    "VideoCopilot Element",
  ];
  const { context, project } = loadBridge({ installedEffects: installed });
  const style = fullStyle();
  unwrap(
    context.beginComp(12, "C:/media/song.wav", style, baseParams(), { parallaxDepth: 0.5, autoCamera: true }, SECTIONS, "C:/extension", MEDIA_PROFILE, 140),
    "beginComp",
  );
  unwrap(context.appendCutBatch(cuts()), "appendCutBatch");
  unwrap(context.finishComp(), "finishComp");

  const comp = project.comps[0];
  const solid = comp.layerByName("FlagshipEditor_3D_Solid");
  assert.ok(solid, "The 3D solid must exist when Element 3D is installed");
  assert.equal(solid.threeDLayer, true);
  assert.ok(solid.effects.property("VideoCopilot Element"), "Element 3D must actually be applied");
  const camera = comp.layerByName("FlagshipEditor_Camera");
  assert.ok(camera, "Auto camera must be created");
  assert.equal(
    camera.property("ADBE Camera Options Group").property("ADBE Camera Zoom").value,
    Math.round(2160 * 1.05),
    "Camera zoom must scale with the comp, not sit at a hard-coded 2000",
  );
  const cameraPosition = camera.property("ADBE Transform Group").property("ADBE Position");
  assert.match(cameraPosition.expression, /Math\.sin/, "Parallax must be a controlled drift");
  assert.doesNotMatch(cameraPosition.expression, /wiggle/, "Parallax must not be random wiggle");

  const probe = unwrap(context.probeElement3D(), "probeElement3D");
  assert.equal(probe.installed, true);
  assert.equal(probe.matchName, "VideoCopilot Element");
}

// --- Degraded host: no effects installed at all -----------------------------
{
  const { context, project } = loadBridge({ installedEffects: [] });
  unwrap(
    context.beginComp(12, "C:/media/song.wav", fullStyle(), baseParams(), { parallaxDepth: 0, autoCamera: false }, SECTIONS, "C:/extension", MEDIA_PROFILE, 140),
    "beginComp",
  );
  unwrap(context.appendCutBatch(cuts()), "appendCutBatch");
  const finished = unwrap(context.finishComp(), "finishComp");
  assert.equal(finished.clipsAdded, 3, "A host without effects must still produce the cut timeline");
  assert.ok(finished.warnings.length > 0, "Missing effects must be reported, never swallowed");
  assert.ok(
    finished.warnings.some((warning) => /no matching effect|unavailable/i.test(warning)),
    `Expected an explicit unavailable-effect warning, saw: ${JSON.stringify(finished.warnings)}`,
  );
  const comp = project.comps[0];
  assert.equal(comp.layerByName("FlagshipEditor_LUT_GLOBAL"), null, "A failed grade must not leave a white solid behind");
}

// --- Per-effect toggles from the panel --------------------------------------
{
  const { context, project } = loadBridge();
  const params = baseParams({ effects: { zoom_punch: false, camera_shake: false, film_grain: false } });
  unwrap(
    context.beginComp(12, "C:/media/song.wav", fullStyle(), params, { parallaxDepth: 0, autoCamera: false }, SECTIONS, "C:/extension", MEDIA_PROFILE, 140),
    "beginComp",
  );
  unwrap(context.appendCutBatch(cuts()), "appendCutBatch");
  unwrap(context.finishComp(), "finishComp");
  const comp = project.comps[0];
  const clip = comp.layerList.find((layer) => /FlagshipEditorCut\|/.test(layer.comment));
  const scale = clip.transform("ADBE Scale");
  const peak = Math.max(...scale.keys.map((key) => key.value[0]));
  assert.ok(peak < 120, `Disabling zoom punch must remove the punch, peaked at ${peak}`);
  assert.equal(clip.transform("ADBE Position").numKeys, 2, "Disabling camera shake must leave only the whip pan");
  assert.equal(comp.layersNamed("FlagshipEditor_Grain").length, 0, "Disabling film grain must skip the grain layer");
}

// --- vfxIntensity 0 disables every effect -----------------------------------
{
  const { context, project } = loadBridge();
  unwrap(
    context.beginComp(12, "C:/media/song.wav", fullStyle(), baseParams({ vfxIntensity: 0, colorGrading: 0 }), { parallaxDepth: 0, autoCamera: false }, SECTIONS, "C:/extension", MEDIA_PROFILE, 140),
    "beginComp",
  );
  unwrap(context.appendCutBatch(cuts()), "appendCutBatch");
  unwrap(context.finishComp(), "finishComp");
  const comp = project.comps[0];
  assert.equal(comp.layerList.length, 4, "Zero VFX intensity must leave only the music and three cuts");
  for (const cut of cuts()) {
    const layer = comp.layerList.find(
      (entry) => entry.comment === `FlagshipEditorCut|${cut.sectionType}|${cut.beatTime.toFixed(4)}`,
    );
    assert.ok(layer, `Native source-offset test could not find ${cut.clipName}`);
    assert.equal(
      layer.inPoint - layer.startTime,
      cut.sourceStart,
      "An un-remapped AE layer must show sourceStart at its cut in-point",
    );
  }
  assert.equal(comp.layerByName("FlagshipEditor_LUT_GLOBAL"), null);
}

// --- Determinism: the same seed rebuilds the same edit ----------------------
{
  function shakePath(seed) {
    const { context, project } = loadBridge();
    unwrap(
      context.beginComp(12, "C:/media/song.wav", fullStyle(), baseParams({ seed }), { parallaxDepth: 0, autoCamera: false }, SECTIONS, "C:/extension", MEDIA_PROFILE, 140),
      "beginComp",
    );
    unwrap(context.appendCutBatch(cuts()), "appendCutBatch");
    unwrap(context.finishComp(), "finishComp");
    const clip = project.comps[0].layerList.find((layer) => /FlagshipEditorCut\|/.test(layer.comment));
    return JSON.stringify(clip.transform("ADBE Position").keys);
  }
  assert.equal(shakePath(42), shakePath(42), "The same seed must produce the same edit");
  assert.notEqual(shakePath(42), shakePath(99), "A different seed must vary the edit");
}

// --- Failure paths ----------------------------------------------------------
{
  const { context, project, undo } = loadBridge();
  const style = fullStyle();
  unwrap(
    context.beginComp(4, "C:/media/song.wav", style, baseParams(), { parallaxDepth: 0, autoCamera: false }, SECTIONS, "C:/extension", MEDIA_PROFILE, 140),
    "beginComp",
  );
  const appended = unwrap(
    context.appendCutBatch([
      { beatTime: 0, endTime: 4, clipPath: "C:/media/missing.mov", clipName: "missing.mov", sectionType: "verse" },
    ]),
    "appendCutBatch",
  );
  assert.equal(appended.added, 0);
  assert.match(expectError(context.finishComp(), "finishComp"), /could not import any selected clips/i);
  assert.equal(project.comps[0].removed, true, "A zero-clip composition must be rolled back");
  assert.equal(undo.depth, 0, "A rolled-back build must close its undo group");

  assert.match(
    expectError(context.beginComp(12, "C:/media/missing.wav", style, baseParams(), {}, SECTIONS, "C:/extension", MEDIA_PROFILE, 140), "beginComp"),
    /Music file is missing/,
  );
  assert.match(
    expectError(context.beginComp(0, "C:/media/song.wav", style, baseParams(), {}, SECTIONS, "C:/extension", MEDIA_PROFILE, 140), "beginComp"),
    /duration is invalid/,
  );
  assert.match(expectError(context.appendCutBatch([]), "appendCutBatch"), /No FlagshipEditor composition build is active/);

  unwrap(
    context.beginComp(12, "C:/media/song.wav", style, baseParams(), {}, SECTIONS, "C:/extension", MEDIA_PROFILE, 140),
    "beginComp",
  );
  const oversized = [];
  for (let i = 0; i < 31; i++) {
    oversized.push({ beatTime: i * 0.2, endTime: i * 0.2 + 0.2, clipPath: "C:/media/a.mov", clipName: "a.mov", sectionType: "verse" });
  }
  assert.match(expectError(context.appendCutBatch(oversized), "appendCutBatch"), /limited to 30 clips/);
  assert.match(expectError(context.appendCutBatch("not-an-array"), "appendCutBatch"), /expects an array/);
  unwrap(context.abortComp(), "abortComp");
  assert.equal(undo.depth, 0, "abortComp must close the undo group it opened");
}

// --- Comp profile falls back to project footage -----------------------------
{
  const { context } = loadBridge();
  const begun = unwrap(
    context.beginComp(12, "C:/media/song.wav", fullStyle(), baseParams(), {}, SECTIONS, "C:/extension", null, 140),
    "beginComp",
  );
  assert.equal(begun.width, 1920, "Without media or footage the comp falls back to 1080p");
  assert.equal(begun.fps, 30);
  unwrap(context.appendCutBatch(cuts()), "appendCutBatch");
  unwrap(context.finishComp(), "finishComp");

  const second = unwrap(
    context.beginComp(12, "C:/media/song.wav", fullStyle(), baseParams(), {}, SECTIONS, "C:/extension", null, 140),
    "beginComp",
  );
  assert.equal(second.width, 3840, "The second build must detect the footage imported by the first");
  assert.equal(second.height, 2160);
  assert.equal(second.fps, 24);
  unwrap(context.abortComp(), "abortComp");
}

// --- Swap and section replace ----------------------------------------------
{
  const { context, project } = loadBridge();
  unwrap(
    context.beginComp(12, "C:/media/song.wav", fullStyle(), baseParams(), {}, SECTIONS, "C:/extension", MEDIA_PROFILE, 140),
    "beginComp",
  );
  unwrap(context.appendCutBatch(cuts()), "appendCutBatch");
  unwrap(context.finishComp(), "finishComp");

  const swapped = unwrap(
    context.swapCut(4, "verse", "C:/media/c.mov", "c.mov", 8, 1.25, 5.25),
    "swapCut",
  );
  assert.equal(swapped.updated, 1);
  const comp = project.comps[0];
  const swappedLayer = comp.layerList.find((layer) => layer.name === "c.mov [verse]");
  assert.ok(swappedLayer, "The swapped layer must be renamed");
  assert.equal(
    swappedLayer.inPoint - swappedLayer.startTime,
    1.25,
    "A manual swap must adopt the alternative clip's selected source offset",
  );
  assert.equal(
    swappedLayer.timeRemap.valueAtTime(swappedLayer.inPoint),
    1.25,
    "A manual swap must retarget existing time-remap values to the alternative source offset",
  );

  const reordered = unwrap(
    context.swapCut(4, "verse", "C:/media/a.mov", "a.mov", 8, 3, 7),
    "swapCut reorder path",
  );
  assert.equal(reordered.updated, 1);
  assert.equal(
    swappedLayer.inPoint - swappedLayer.startTime,
    3,
    "The reorder path must move the selected source offset with the clip assignment",
  );
  assert.equal(
    swappedLayer.timeRemap.valueAtTime(swappedLayer.inPoint),
    3,
    "The reorder path must shift existing time-remap values with the clip assignment",
  );
  const sourceBeforeInvalidSwap = swappedLayer.source;
  const nameBeforeInvalidSwap = swappedLayer.name;
  const itemCountBeforeInvalidSwap = project.numItems;
  assert.match(
    expectError(
      context.swapCut(4, "verse", "C:/media/invalid.mov", "invalid.mov", 8, 9, 8),
      "swapCut invalid source window",
    ),
    /no usable selected source window/,
  );
  assert.equal(
    swappedLayer.source,
    sourceBeforeInvalidSwap,
    "An invalid manual swap must not mutate the AE layer source",
  );
  assert.equal(swappedLayer.name, nameBeforeInvalidSwap);
  assert.equal(
    project.numItems,
    itemCountBeforeInvalidSwap,
    "An invalid manual swap must not leave orphan footage in the AE project",
  );

  const missing = unwrap(
    context.swapCut(99, "verse", "C:/media/c.mov", "c.mov", 100, 0, 1),
    "swapCut",
  );
  assert.equal(missing.updated, 0);

  const replaced = unwrap(
    context.replaceSectionCuts("drop", [{
      beatTime: 8,
      endTime: 12,
      sourceStart: 1.5,
      sourceEnd: 5.5,
      clipPath: "C:/media/d.mov",
      clipName: "d.mov",
      sectionType: "drop",
    }]),
    "replaceSectionCuts",
  );
  assert.equal(replaced.updated, 1);
  const regeneratedLayer = comp.layerList.find((layer) => layer.name === "d.mov [drop]");
  assert.equal(
    regeneratedLayer.inPoint - regeneratedLayer.startTime,
    1.5,
    "Section regeneration must apply the replacement cut's selected source offset",
  );
  assert.equal(
    regeneratedLayer.timeRemap.valueAtTime(regeneratedLayer.inPoint),
    1.5,
    "Section regeneration must retarget existing time-remap values to sourceStart",
  );
  const sourceBeforeInvalidRegeneration = regeneratedLayer.source;
  const nameBeforeInvalidRegeneration = regeneratedLayer.name;
  const itemCountBeforeInvalidRegeneration = project.numItems;
  const invalidRegeneration = unwrap(
    context.replaceSectionCuts("drop", [{
      beatTime: 8,
      endTime: 12,
      sourceStart: 20,
      sourceEnd: 30,
      clipPath: "C:/media/invalid-regeneration.mov",
      clipName: "invalid-regeneration.mov",
      sectionType: "drop",
    }]),
    "replaceSectionCuts invalid source window",
  );
  assert.equal(invalidRegeneration.updated, 0);
  assert.equal(invalidRegeneration.missing, 1);
  assert.equal(
    regeneratedLayer.source,
    sourceBeforeInvalidRegeneration,
    "An invalid section replacement must not mutate the AE layer source",
  );
  assert.equal(regeneratedLayer.name, nameBeforeInvalidRegeneration);
  assert.equal(
    project.numItems,
    itemCountBeforeInvalidRegeneration,
    "A clamped-invalid regeneration must clean up newly imported orphan footage",
  );
  assert.match(expectError(context.replaceSectionCuts("drop", null), "replaceSectionCuts"), /expects an array/);
}

// --- Style coverage report --------------------------------------------------
{
  const { context } = loadBridge();
  const coverage = unwrap(context.describeStyleCoverage(fullStyle()), "describeStyleCoverage");
  assert.equal(coverage.total, 24, "FlagshipEditor ships 24 routed effects");
  assert.ok(coverage.active.indexOf("zoom_punch") >= 0);
  assert.ok(coverage.active.indexOf("element_3d") >= 0);
  assert.equal(coverage.active.length, 24, "Every effect in the full style must be routed");
}

console.log(
  "Compiled After Effects bridge simulation passed (24 routed effects, composed scale/opacity, " +
    "source-time remapping, adjustment-layer grading, Element 3D detection, seeded determinism, rollback).",
);

// --- The engine's transition decision must survive the CEP payload ----------
//
// aeft.ts has always implemented `applyTransitionToLayer`, but the panel's
// `toPayload` rebuilt each cut field by field and never copied `transition`,
// so every dissolve and phrase transition the engine justified from adjacent
// shots arrived in After Effects as a plain hard cut. The bridge was correct
// and the decision was correct; the wire between them dropped it.
{
  const panel = fs.readFileSync(path.join(root, "src", "js", "main", "App.tsx"), "utf8");
  const payloadShape = panel.slice(
    panel.indexOf("interface TimelineCutPayload"),
    panel.indexOf("const TABS"),
  );
  assert.ok(
    /transition\?:\s*\{\s*type:\s*string\s*\}/.test(payloadShape),
    "TimelineCutPayload must declare the transition the AE bridge consumes",
  );
  const toPayloadBody = panel.slice(
    panel.indexOf("function toPayload("),
    panel.indexOf("function toPayload(") + 1200,
  );
  assert.ok(
    /payload\.transition\s*=\s*\{\s*type:\s*cut\.transition\.type\s*\}/.test(toPayloadBody),
    "toPayload must forward the engine's transition type to After Effects",
  );

  // And the bridge has to act on it. A transition-free style isolates the
  // opacity ramp to the transition itself.
  const bareStyle = {
    style_name: "bare",
    display_name: "Bare",
    cut_strategy: {},
    color_grading: { global_lut: "", params: {}, section_luts: {} },
  };
  const dissolveAt = 4;
  const withTransition = [
    { beatTime: 0, endTime: 4, sourceStart: 0, sourceEnd: 4, clipPath: "C:/media/a.mov", clipName: "a.mov", sectionType: "verse" },
    { beatTime: dissolveAt, endTime: 8, sourceStart: 0, sourceEnd: 4, clipPath: "C:/media/b.mov", clipName: "b.mov", sectionType: "verse", transition: { type: "dissolve" } },
  ];
  const hardOnly = withTransition.map((cut) => ({ ...cut, transition: { type: "hard_cut" } }));

  function opacityKeysFor(batch) {
    const { context, project } = loadBridge();
    unwrap(
      context.beginComp(8, "C:/media/song.wav", bareStyle, baseParams(), {}, SECTIONS, "C:/extension", MEDIA_PROFILE, 140),
      "beginComp",
    );
    unwrap(context.appendCutBatch(batch), "appendCutBatch");
    unwrap(context.finishComp(), "finishComp");
    const layer = project.comps[0].layerList
      .filter((item) => /FlagshipEditorCut\|/.test(item.comment))
      .find((item) => item.inPoint === dissolveAt);
    assert.ok(layer, "The second cut must be on the timeline");
    const opacity = layer.transform("ADBE Opacity");
    return opacity ? opacity.keys : [];
  }

  const dissolveKeys = opacityKeysFor(withTransition);
  assert.ok(dissolveKeys.length >= 2, "A dissolve must build an opacity ramp");
  assert.equal(dissolveKeys[0].value, 0, "A dissolve must start the incoming shot transparent");
  assert.equal(
    dissolveKeys[dissolveKeys.length - 1].value,
    100,
    "A dissolve must finish fully opaque",
  );

  assert.equal(
    opacityKeysFor(hardOnly).length,
    0,
    "A hard cut must not animate opacity — transitions are decided, not sprinkled",
  );
}
