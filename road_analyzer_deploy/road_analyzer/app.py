"""
road_analyzer.app
==================
FastAPI server for the Road Efficiency / Capacity-Loss project.

Run with:
    uvicorn road_analyzer.app:app --reload --port 8000

Then open http://localhost:8000 in a browser.

Endpoints
---------
GET  /                      -> serves the dashboard (static/index.html)
GET  /api/config-options    -> carriageway/fringe/traffic-regime choices for the form
POST /api/analyze/image     -> one image  + road config -> capacity report
POST /api/analyze/batch     -> many images + road config -> batch summary
POST /api/analyze/video     -> one video  + road config -> video summary
GET  /api/jobs/{job_id}     -> poll status/result of a batch or video job
                                (these can take a while, so they run in the
                                background and the frontend polls)
"""

from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, File, Form, UploadFile, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from road_analyzer.core import (
    RoadAnalyzer, IRC106_DSV, FRINGE_CONDITION_DESC, CLASS_NAMES,
)

# ----------------------------------------------------------------
# Paths & app-wide state
# ----------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
RESULTS_DIR = BASE_DIR / "results"
MODELS_DIR = BASE_DIR / "models"
STATIC_DIR = BASE_DIR / "static"

for d in (UPLOAD_DIR, RESULTS_DIR, MODELS_DIR, STATIC_DIR):
    d.mkdir(parents=True, exist_ok=True)

# Path to your trained weights. Override with the ROAD_MODEL_PATH env var,
# e.g.  export ROAD_MODEL_PATH=/path/to/best.pt
MODEL_PATH = os.environ.get("ROAD_MODEL_PATH", str(MODELS_DIR / "best.pt"))

app = FastAPI(title="Road Efficiency Analyzer", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory job tracker for the long-running batch/video endpoints.
# Fine for a single-process student/demo deployment; swap for Redis/DB
# if this ever needs to run multi-worker.
JOBS: dict = {}

_analyzer: Optional[RoadAnalyzer] = None


def get_analyzer() -> RoadAnalyzer:
    global _analyzer
    if _analyzer is None:
        if not Path(MODEL_PATH).exists():
            raise HTTPException(
                status_code=503,
                detail=(
                    f"Model weights not found at '{MODEL_PATH}'. "
                    f"Train the model in the notebook, then copy best.pt into "
                    f"road_analyzer/models/, or set the ROAD_MODEL_PATH env var."
                ),
            )
        _analyzer = RoadAnalyzer(MODEL_PATH)
    return _analyzer


# ----------------------------------------------------------------
# Request/response schemas
# ----------------------------------------------------------------
class RoadConfigIn(BaseModel):
    total_width_m: float
    num_lanes: int
    carriageway_key: str
    fringe_condition: str
    usable_shoulder_m: float
    heavy_traffic_regime: str = "high"


def _road_config_from_form(
    total_width_m: float, num_lanes: int, carriageway_key: str,
    fringe_condition: str, usable_shoulder_m: float, heavy_traffic_regime: str,
) -> dict:
    cfg = RoadConfigIn(
        total_width_m=total_width_m, num_lanes=num_lanes,
        carriageway_key=carriageway_key, fringe_condition=fringe_condition,
        usable_shoulder_m=usable_shoulder_m,
        heavy_traffic_regime=heavy_traffic_regime,
    )
    if cfg.carriageway_key not in IRC106_DSV:
        raise HTTPException(400, f"Unknown carriageway_key '{cfg.carriageway_key}'")
    if cfg.fringe_condition not in FRINGE_CONDITION_DESC:
        raise HTTPException(400, f"Unknown fringe_condition '{cfg.fringe_condition}'")
    return cfg.model_dump()


def _new_job_dir(prefix: str) -> tuple[str, Path]:
    job_id = f"{prefix}_{uuid.uuid4().hex[:10]}"
    job_dir = RESULTS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    return job_id, job_dir


# ----------------------------------------------------------------
# Static frontend
# ----------------------------------------------------------------
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def serve_index():
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(404, "Frontend not built yet (static/index.html missing).")
    return FileResponse(str(index_path))


# ----------------------------------------------------------------
# Config metadata (so the frontend form is never out of sync with
# the IRC tables baked into core.py)
# ----------------------------------------------------------------
@app.get("/api/config-options")
def config_options():
    return {
        "carriageway_keys": list(IRC106_DSV.keys()),
        "fringe_conditions": [
            {"key": k, "description": v} for k, v in FRINGE_CONDITION_DESC.items()
        ],
        "heavy_traffic_regimes": [
            {"key": "low", "description": "heavy/auto-rickshaw traffic share < 5%"},
            {"key": "high", "description": "heavy/auto-rickshaw traffic share >= 10% (typical Indian mixed traffic)"},
        ],
        "defect_classes": CLASS_NAMES,
        "model_loaded": Path(MODEL_PATH).exists(),
        "model_path": MODEL_PATH,
    }


# ----------------------------------------------------------------
# SINGLE IMAGE — synchronous, fast enough to return directly
# ----------------------------------------------------------------
@app.post("/api/analyze/image")
async def analyze_image(
    file: UploadFile = File(...),
    total_width_m: float = Form(...),
    num_lanes: int = Form(...),
    carriageway_key: str = Form(...),
    fringe_condition: str = Form(...),
    usable_shoulder_m: float = Form(...),
    heavy_traffic_regime: str = Form("high"),
):
    road_config = _road_config_from_form(
        total_width_m, num_lanes, carriageway_key, fringe_condition,
        usable_shoulder_m, heavy_traffic_regime,
    )

    job_id, job_dir = _new_job_dir("img")
    dest = job_dir / file.filename
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    analyzer = get_analyzer()
    try:
        result = analyzer.analyse_image(str(dest), road_config,
                                         save_outputs=True, output_dir=str(job_dir))
    except Exception as e:
        raise HTTPException(400, f"Analysis failed: {e}")

    result.pop("_json_path", None)
    result.pop("_csv_path", None)
    result["job_id"] = job_id
    return result


# ----------------------------------------------------------------
# BATCH MODE — many images, same road config, runs in background
# ----------------------------------------------------------------
def _run_batch_job(job_id: str, job_dir: Path, image_paths: List[str], road_config: dict):
    try:
        analyzer = get_analyzer()
        summary = analyzer.analyse_batch(image_paths, road_config, output_dir=str(job_dir))
        summary.pop("_json_path", None)
        JOBS[job_id] = {"status": "done", "result": summary}
    except Exception as e:
        JOBS[job_id] = {"status": "error", "error": str(e)}


@app.post("/api/analyze/batch")
async def analyze_batch(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
    total_width_m: float = Form(...),
    num_lanes: int = Form(...),
    carriageway_key: str = Form(...),
    fringe_condition: str = Form(...),
    usable_shoulder_m: float = Form(...),
    heavy_traffic_regime: str = Form("high"),
):
    if len(files) == 0:
        raise HTTPException(400, "Upload at least one image.")

    road_config = _road_config_from_form(
        total_width_m, num_lanes, carriageway_key, fringe_condition,
        usable_shoulder_m, heavy_traffic_regime,
    )

    job_id, job_dir = _new_job_dir("batch")
    image_paths = []
    for f in files:
        dest = job_dir / f.filename
        with dest.open("wb") as out:
            shutil.copyfileobj(f.file, out)
        image_paths.append(str(dest))

    JOBS[job_id] = {"status": "running"}
    background_tasks.add_task(_run_batch_job, job_id, job_dir, image_paths, road_config)
    return {"job_id": job_id, "status": "running", "num_images": len(image_paths)}


# ----------------------------------------------------------------
# VIDEO MODE — one video, runs in background (can be slow)
# ----------------------------------------------------------------
def _run_video_job(job_id: str, job_dir: Path, video_path: str, road_config: dict,
                    sample_every_sec: float):
    try:
        analyzer = get_analyzer()
        summary = analyzer.analyse_video(
            video_path, road_config, output_dir=str(job_dir),
            sample_every_sec=sample_every_sec,
        )
        summary.pop("_json_path", None)
        JOBS[job_id] = {"status": "done", "result": summary}
    except Exception as e:
        JOBS[job_id] = {"status": "error", "error": str(e)}


@app.post("/api/analyze/video")
async def analyze_video(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    total_width_m: float = Form(...),
    num_lanes: int = Form(...),
    carriageway_key: str = Form(...),
    fringe_condition: str = Form(...),
    usable_shoulder_m: float = Form(...),
    heavy_traffic_regime: str = Form("high"),
    sample_every_sec: float = Form(1.0),
):
    road_config = _road_config_from_form(
        total_width_m, num_lanes, carriageway_key, fringe_condition,
        usable_shoulder_m, heavy_traffic_regime,
    )

    job_id, job_dir = _new_job_dir("video")
    dest = job_dir / file.filename
    with dest.open("wb") as out:
        shutil.copyfileobj(file.file, out)

    JOBS[job_id] = {"status": "running"}
    background_tasks.add_task(
        _run_video_job, job_id, job_dir, str(dest), road_config, sample_every_sec
    )
    return {"job_id": job_id, "status": "running"}


# ----------------------------------------------------------------
# Job polling (used by batch + video, which run in the background)
# ----------------------------------------------------------------
@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "Unknown job_id.")
    return job


@app.get("/api/health")
def health():
    return {"status": "ok", "model_loaded": Path(MODEL_PATH).exists()}
