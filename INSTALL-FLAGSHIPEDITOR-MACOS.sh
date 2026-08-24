#!/bin/bash
# FlagshipEditor — macOS Installer
# Installs the CEP extension and sets up the Python backend
# Usage: bash INSTALL-FLAGSHIPEDITOR-MACOS.sh

set -e

EXTENSION_ID="com.akestudio.flagshipeditor"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DIST_DIR="$SCRIPT_DIR/dist"
CEP_EXTENSIONS_DIR="$HOME/Library/Application Support/Adobe/CEP/extensions"

echo "========================================="
echo "  FlagshipEditor — macOS Installer"
echo "========================================="
echo ""

# 1. Check AE is installed
AE_FOUND=false
for AE_VERSION in 26 25 24 23 22; do
  AE_PATH="/Applications/Adobe After Effects ${AE_VERSION}/Adobe After Effects ${AE_VERSION}.app"
  if [ -d "$AE_PATH" ]; then
    AE_FOUND=true
    echo "✅ Found: Adobe After Effects ${AE_VERSION}"
  fi
done

if [ "$AE_FOUND" = false ]; then
  echo "⚠️  No Adobe After Effects installation found in /Applications"
  echo "    Install AE 2022+ before using FlagshipEditor."
fi

# 2. Create CEP extensions directory
mkdir -p "$CEP_EXTENSIONS_DIR"
echo "✅ CEP extensions dir: $CEP_EXTENSIONS_DIR"

# 3. Copy extension
if [ -d "$DIST_DIR/cep" ]; then
  EXTENSION_SOURCE="$DIST_DIR/cep"
elif [ -d "$DIST_DIR" ]; then
  EXTENSION_SOURCE="$DIST_DIR"
else
  echo "❌ No dist/ directory found. Run 'npm run build' first."
  exit 1
fi

TARGET_DIR="$CEP_EXTENSIONS_DIR/$EXTENSION_ID"
if [ -d "$TARGET_DIR" ]; then
  echo "⚠️  Existing installation found. Removing old version..."
  rm -rf "$TARGET_DIR"
fi

cp -R "$EXTENSION_SOURCE" "$TARGET_DIR"
echo "✅ Extension installed to: $TARGET_DIR"

# 4. Enable PlayerDebugMode for all CSXS versions
echo ""
echo "Enabling PlayerDebugMode (required for unsigned extensions)..."
for CSXS_VERSION in 12 11 10 9 8; do
  defaults write "com.adobe.CSXS.${CSXS_VERSION}" PlayerDebugMode 1 2>/dev/null || true
done
killall cfprefsd 2>/dev/null || true
echo "✅ PlayerDebugMode enabled for CSXS 8-12"

# 5. Setup Python backend
echo ""
echo "Setting up Python backend..."
ENGINE_DIR="$SCRIPT_DIR/engine"
if [ -d "$ENGINE_DIR" ]; then
  if command -v python3 &>/dev/null; then
    PYTHON_BIN="python3"
  elif [ -f "$SCRIPT_DIR/python/bin/python3" ]; then
    PYTHON_BIN="$SCRIPT_DIR/python/bin/python3"
  else
    echo "⚠️  Python 3 not found. Install Python 3.10+ from python.org"
    PYTHON_BIN=""
  fi

  if [ -n "$PYTHON_BIN" ]; then
    echo "✅ Python: $($PYTHON_BIN --version)"
    
    # Create virtualenv if not present
    if [ ! -d "$ENGINE_DIR/.venv" ]; then
      echo "Creating virtual environment..."
      "$PYTHON_BIN" -m venv "$ENGINE_DIR/.venv"
    fi
    
    # Install dependencies
    if [ -f "$ENGINE_DIR/requirements.txt" ]; then
      echo "Installing Python dependencies..."
      "$ENGINE_DIR/.venv/bin/pip" install -r "$ENGINE_DIR/requirements.txt" --quiet
      echo "✅ Python dependencies installed"
    fi
  fi
else
  echo "⚠️  Engine directory not found at $ENGINE_DIR"
fi

# 6. Check FFmpeg
echo ""
if command -v ffmpeg &>/dev/null; then
  echo "✅ FFmpeg: $(ffmpeg -version 2>&1 | head -1)"
else
  echo "⚠️  FFmpeg not found. Install via: brew install ffmpeg"
fi

if command -v ffprobe &>/dev/null; then
  echo "✅ FFprobe: $(ffprobe -version 2>&1 | head -1)"
else
  echo "⚠️  FFprobe not found. Install via: brew install ffmpeg"
fi

# 7. Done
echo ""
echo "========================================="
echo "  Installation complete!"
echo "========================================="
echo ""
echo "Next steps:"
echo "  1. Restart Adobe After Effects"
echo "  2. Open Window > Extensions > FlagshipEditor"
echo "  3. If the panel is blank, run:"
echo "     defaults write com.adobe.CSXS.12 PlayerDebugMode 1 && killall cfprefsd"
echo ""
echo "To start the Python backend manually:"
echo "  cd $ENGINE_DIR && .venv/bin/python server.py"
echo ""
echo "To uninstall:"
echo "  rm -rf \"$TARGET_DIR\""
echo ""