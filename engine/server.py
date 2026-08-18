"""
FlagshipEditor — Python Backend Server
Local FastAPI server that handles beat analysis and clip classification.
Runs on localhost:18791
"""

import os
import sys
import json
import subprocess
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

# Import analysis modules (graceful degradation if deps not installed)
sys.path.insert(0, str(Path(__file__).parent))

LIBROSA_AVAILABLE = False
OPENCV_AVAILABLE = False

try:
    from beat_analysis import analyze_track
    LIBROSA_AVAILABLE = True
except ImportError:
    pass

try:
    from clip_analysis import classify_clip
    OPENCV_AVAILABLE = True
except ImportError:
    pass

app = FastAPI(title="FlagshipEditor Backend", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class BeatRequest(BaseModel):
    audioPath: str


class ClipRequest(BaseModel):
    videoPath: str


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "version": "0.1.0",
        "librosa": LIBROSA_AVAILABLE,
        "opencv": OPENCV_AVAILABLE,
    }


@app.post("/analyze-beat")
async def analyze_beat(req: BeatRequest):
    if not LIBROSA_AVAILABLE:
        raise HTTPException(status_code=503, detail="librosa not installed. Run: pip install librosa scikit-learn")
    try:
        result = analyze_track(req.audioPath)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/analyze-clip")
async def analyze_clip_endpoint(req: ClipRequest):
    if not OPENCV_AVAILABLE:
        raise HTTPException(status_code=503, detail="opencv not installed. Run: pip install opencv-python")
    try:
        result = classify_clip(req.videoPath)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/start")
async def start_server():
    return {"status": "already running"}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=18791, log_level="info")