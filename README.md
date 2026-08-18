# FlagshipEditor™

AI music video editor plugin for After Effects. Auto-cuts to beat, applies VFX, color grading, and 3D setup based on style presets.

## Quick Start

```bash
# Install dependencies
yarn install

# Dev mode (HMR in AE)
yarn dev

# Build
yarn build

# Package ZXP
yarn zxp
```

## Python Backend

```bash
cd engine
pip install -r requirements.txt
python server.py
```

Server runs on `http://127.0.0.1:18791`

## Structure

```
flagshipeditor/
├── src/
│   ├── js/main/          # React UI (panel)
│   │   ├── App.tsx       # Main app
│   │   ├── components/   # UI components
│   │   └── lib/          # Bolt bridge, Python bridge, styles
│   ├── js/settings/      # Settings panel
│   └── jsx/              # ExtendScript (compiled to ES3)
│       ├── aeft/         # After Effects functions
│       │   ├── aeft.ts          # Comp builder
│       │   ├── vfx_engine.ts    # Zoom, shake, whip pan, glitch
│       │   ├── color_grading.ts # LUT application
│       │   └── element_3d.ts    # Element 3D solid + camera
│       └── lib/json2.js  # JSON polyfill for ES3
├── engine/               # Python backend
│   ├── server.py         # FastAPI server
│   ├── beat_analysis.py  # librosa beat/section/key detection
│   └── clip_analysis.py  # OpenCV clip classification
├── styles/               # Style presets (JSON)
│   ├── cmd_command_drill.json
│   ├── lyrical_lemonade.json
│   ├── ninetive.json
│   ├── jack_rottier.json
│   ├── worldwide_films.json
│   └── custom.json
├── luts/                 # LUT files (.cube)
├── CSXS/manifest.xml     # CEP 12 manifest
├── cep.config.ts         # Bolt CEP config
├── package.json
└── tsconfig.json
```

## Styles

| Style | Description |
|-------|-------------|
| CMD COMMAND — UK Drill | Dark cold grading, 3D env, face mask, glitch on 808, drill speed cuts |
| Lyrical Lemonade | Zoom punches, whip pans, kinetic text, vibrant grading, VHS overlays |
| Ninetive | Smooth speed ramps, clean zoom, depth blur, selective color |
| Jack Rottier | Cinematic, letterbox 2.39:1, film grain, light wrap, slow push-in |
| World Wide Films | Trap/drill high-energy, aggressive cuts, RGB split, strobe, mask transitions |
| Custom | User-defined base |

## Requirements

- Node.js 20+
- Python 3.10+
- After Effects 2024+ (CEP 12)
- FFmpeg / FFprobe
- librosa, opencv-python, scikit-learn

## Users

Built for Issandre & HeliMAn. ProRes 422 native. Windows 11 + macOS.

## License

MIT — ake-studio