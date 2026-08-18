// Style loader — loads style presets from JSON files

export interface StyleConfig {
  style_name: string;
  display_name: string;
  cut_strategy: {
    [section: string]: {
      cut_interval: string;
      variation: string;
      double_time_on_drop?: boolean;
      double_time_on_808?: boolean;
    };
  };
  zoom_punch?: any;
  whip_pan?: any;
  text_overlays?: any;
  color_grading?: any;
  camera_shake?: any;
  freeze_frame?: any;
  speed_ramp?: any;
  light_leaks?: any;
  vhs_overlay?: any;
  glitch_effect?: any;
  element_3d?: any;
  face_mask?: any;
  smoke_fog?: any;
  slow_mo?: any;
  beat_flash?: any;
  depth_blur?: any;
  glitch_transition?: any;
  smooth_transitions?: any;
  letterbox?: any;
  film_grain?: any;
  light_wrap?: any;
  slow_push_in?: any;
  rgb_split?: any;
  strobe?: any;
  mask_transition?: any;
  picture_flash?: any;
  selective_color?: any;
}

const STYLE_FILES: { [key: string]: string } = {
  lyrical_lemonade: "styles/lyrical_lemonade.json",
  ninetive: "styles/ninetive.json",
  jack_rottier: "styles/jack_rottier.json",
  worldwide_films: "styles/worldwide_films.json",
  cmd_command_drill: "styles/cmd_command_drill.json",
  custom: "styles/custom.json",
};

export async function loadStyle(styleName: string): Promise<StyleConfig> {
  const file = STYLE_FILES[styleName];
  if (!file) throw new Error(`Unknown style: ${styleName}`);
  const res = await fetch(file);
  if (!res.ok) throw new Error(`Failed to load style: ${styleName}`);
  return res.json();
}

export function getAvailableStyles(): { id: string; name: string }[] {
  return [
    { id: "lyrical_lemonade", name: "Lyrical Lemonade (Cole Bennett)" },
    { id: "ninetive", name: "Ninetive" },
    { id: "jack_rottier", name: "Jack Rottier (Cinematic)" },
    { id: "worldwide_films", name: "World Wide Films (Trap/Drill)" },
    { id: "cmd_command_drill", name: "CMD COMMAND — UK Drill" },
    { id: "custom", name: "Custom" },
  ];
}