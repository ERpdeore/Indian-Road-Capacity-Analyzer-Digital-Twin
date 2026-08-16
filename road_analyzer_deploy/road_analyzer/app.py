"""
road_analyzer.app
=================
FastAPI server for the Indian Road Capacity Analyzer.

FIXES IN THIS VERSION
---------------------
- heavy_traffic_regime field removed (unused in IRC:106 Table 2)
- LOS removed from API response
- path traversal fix: Path(file.filename).name
- logger defined before first use
- assert replaced with raise ValueError in core.py
- second-upload "failed" bug fixed: each request gets a fresh job_id
  and the _analyzer singleton is preserved (model stays warm)
- digital twin bridge imported safely (app works without MATLAB)
"""

from __future__ import annotations

import logging
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

# logger MUST be defined before any code that uses it
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("road_analyzer.app")

from road_analyzer.core import (
    RoadAnalyzer, IRC106_DSV, IRC106_DSV_LABELS,
    FRINGE_CONDITION_DESC, TRAFFIC_REGIME_DESC,
    IRC106_PCU_FACTORS, IRC_FREE_FLOW_SPEED,
    get_free_flow_speed, CLASS_NAMES,
)

# Digital Twin bridge — optional, disabled gracefully if MATLAB not installed
try:
    from road_analyzer.digital_twin_bridge import (
        trigger_matlab_simulation,
        get_twin_status,
        get_latest_twin_data,
    )
    _DT_ENABLED = True
    logger.info("Digital Twin bridge loaded successfully.")
except ImportError:
    _DT_ENABLED = False
    logger.warning("digital_twin_bridge not found — /api/digital-twin/* endpoints disabled.")

# ----------------------------------------------------------------
# Paths
# ----------------------------------------------------------------
BASE_DIR    = Path(__file__).resolve().parent
UPLOAD_DIR  = BASE_DIR / "uploads"
RESULTS_DIR = BASE_DIR / "results"
MODELS_DIR  = BASE_DIR / "models"
STATIC_DIR  = BASE_DIR / "static"

for d in (UPLOAD_DIR, RESULTS_DIR, MODELS_DIR, STATIC_DIR):
    d.mkdir(parents=True, exist_ok=True)

MODEL_PATH = os.environ.get("ROAD_MODEL_PATH", str(MODELS_DIR / "best.pt"))

app = FastAPI(title="Indian Road Capacity Analyzer", version="3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory job store — each request gets a unique job_id
# so second/third uploads never collide with previous results
JOBS: dict = {}

# Singleton analyzer — model loaded ONCE, reused for all requests
# This is the key fix for slow second-upload: previously a new YOLO()
# was created per request, reloading weights from disk every time.
_analyzer: Optional[RoadAnalyzer] = None


def get_analyzer() -> RoadAnalyzer:
    global _analyzer
    if _analyzer is None:
        if not Path(MODEL_PATH).exists():
            raise HTTPException(
                status_code=503,
                detail=(
                    f"Model weights not found at '{MODEL_PATH}'. "
                    f"Copy best.pt into road_analyzer/models/ or "
                    f"set the ROAD_MODEL_PATH environment variable."
                ),
            )
        logger.info("Loading RoadAnalyzer model from %s ...", MODEL_PATH)
        _analyzer = RoadAnalyzer(MODEL_PATH)
        logger.info("RoadAnalyzer ready.")
    return _analyzer


def _safe_filename(filename: str) -> str:
    """Strip directory components — prevents path traversal attacks."""
    return Path(filename).name or "upload"


def _road_config_from_form(
    total_width_m:    float,
    num_lanes:        int,
    carriageway_key:  str,
    fringe_condition: str,
    usable_shoulder_m: float,
    traffic_regime:   str = "low",
) -> dict:
    if carriageway_key not in IRC106_DSV:
        raise HTTPException(400, f"Unknown carriageway_key '{carriageway_key}'. "
                                  f"Valid: {list(IRC106_DSV.keys())}")
    if fringe_condition not in FRINGE_CONDITION_DESC:
        raise HTTPException(400, f"Unknown fringe_condition '{fringe_condition}'. "
                                  f"Valid: {list(FRINGE_CONDITION_DESC.keys())}")
    if traffic_regime not in ("low", "high"):
        traffic_regime = "low"
    if num_lanes <= 0:
        raise HTTPException(400, "num_lanes must be >= 1")
    if total_width_m <= 0:
        raise HTTPException(400, "total_width_m must be > 0")
    return {
        "total_width_m":    float(total_width_m),
        "num_lanes":        int(num_lanes),
        "carriageway_key":  carriageway_key,
        "fringe_condition": fringe_condition,
        "usable_shoulder_m": float(usable_shoulder_m),
        "traffic_regime":   traffic_regime,
    }


def _new_job(prefix: str) -> tuple[str, Path]:
    job_id  = f"{prefix}_{uuid.uuid4().hex[:10]}"
    job_dir = RESULTS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    return job_id, job_dir


# ----------------------------------------------------------------
# Static frontend
# ----------------------------------------------------------------
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.on_event("startup")
async def startup_event():
    """Pre-load the YOLO model at startup so first request is fast."""
    import threading
    def _warm():
        try:
            if Path(MODEL_PATH).exists():
                logger.info("Startup: pre-loading YOLO model...")
                get_analyzer()
                logger.info("Startup: YOLO model ready.")
            else:
                logger.warning("Startup: model not found at %s", MODEL_PATH)
        except Exception as e:
            logger.warning("Startup: model pre-load failed: %s", e)
    threading.Thread(target=_warm, daemon=True).start()


@app.get("/")
def serve_index():
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(404, "Frontend not found — static/index.html is missing.")
    return FileResponse(str(index_path))


# ----------------------------------------------------------------
# Config metadata (populates dropdowns in the frontend)
# ----------------------------------------------------------------
@app.get("/api/config-options")
def config_options():
    carriageway_options = []
    for key, fringe_vals in IRC106_DSV.items():
        available_fringes = [f for f, v in fringe_vals.items() if v is not None]
        carriageway_options.append({
            "key":              key,
            "label":            IRC106_DSV_LABELS.get(key, key),
            "available_fringes": available_fringes,
            "dsv_values":        {f: v for f, v in fringe_vals.items() if v is not None},
        })
    # Add free flow speed to each carriageway option
    for opt in carriageway_options:
        opt["free_flow_speeds"] = IRC_FREE_FLOW_SPEED.get(opt["key"], {})

    return {
        "carriageway_options": carriageway_options,
        "fringe_conditions": [
            {"key": k, "description": v} for k, v in FRINGE_CONDITION_DESC.items()
        ],
        "traffic_regimes": [
            {"key": k, "description": v} for k, v in TRAFFIC_REGIME_DESC.items()
        ],
        "pcu_factors":        IRC106_PCU_FACTORS,
        "free_flow_speeds":   IRC_FREE_FLOW_SPEED,
        "defect_classes":     CLASS_NAMES,
        "model_loaded":       Path(MODEL_PATH).exists(),
    }


# ----------------------------------------------------------------
# SINGLE IMAGE ANALYSIS
# ----------------------------------------------------------------
@app.post("/api/analyze/image")
async def analyze_image(
    file:              UploadFile = File(...),
    total_width_m:     float = Form(...),
    num_lanes:         int   = Form(...),
    carriageway_key:   str   = Form(...),
    fringe_condition:  str   = Form(...),
    usable_shoulder_m: float = Form(...),
    traffic_regime:    str   = Form("low"),
):
    road_config = _road_config_from_form(
        total_width_m, num_lanes, carriageway_key,
        fringe_condition, usable_shoulder_m, traffic_regime,
    )

    # Fresh job_id for EVERY request — this is what fixes the
    # "second upload fails" bug: previously result paths collided.
    job_id, job_dir = _new_job("img")

    safe_name = _safe_filename(file.filename)
    dest = job_dir / safe_name
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    analyzer = get_analyzer()
    try:
        result = analyzer.analyse_image(
            str(dest), road_config, save_outputs=True, output_dir=str(job_dir)
        )
    except Exception as e:
        logger.error("Image analysis failed: %s", e, exc_info=True)
        raise HTTPException(400, f"Analysis failed: {e}")

    json_path = result.pop("_json_path", None)
    result.pop("_csv_path", None)
    result["job_id"] = job_id

    # Trigger MATLAB Digital Twin simulation in background
    if _DT_ENABLED and json_path:
        try:
            trigger_matlab_simulation(str(json_path))
            result["digital_twin_status"] = "running"
        except Exception as e:
            logger.warning("Digital twin trigger failed: %s", e)
            result["digital_twin_status"] = "error"
    else:
        result["digital_twin_status"] = "unavailable"

    return result


# ----------------------------------------------------------------
# BATCH MODE
# ----------------------------------------------------------------
def _run_batch_job(job_id: str, job_dir: Path,
                    image_paths: List[str], road_config: dict):
    try:
        analyzer = get_analyzer()
        summary  = analyzer.analyse_batch(image_paths, road_config, output_dir=str(job_dir))
        summary.pop("_json_path", None)
        JOBS[job_id] = {"status": "done", "result": summary}
        logger.info("Batch job %s done — %d images", job_id, len(image_paths))
    except Exception as e:
        logger.error("Batch job %s failed: %s", job_id, e, exc_info=True)
        JOBS[job_id] = {"status": "error", "error": str(e)}


@app.post("/api/analyze/batch")
async def analyze_batch(
    background_tasks:  BackgroundTasks,
    files:             List[UploadFile] = File(...),
    total_width_m:     float = Form(...),
    num_lanes:         int   = Form(...),
    carriageway_key:   str   = Form(...),
    fringe_condition:  str   = Form(...),
    usable_shoulder_m: float = Form(...),
    traffic_regime:    str   = Form("low"),
):
    if not files:
        raise HTTPException(400, "Upload at least one image.")

    road_config = _road_config_from_form(
        total_width_m, num_lanes, carriageway_key,
        fringe_condition, usable_shoulder_m, traffic_regime,
    )

    job_id, job_dir = _new_job("batch")
    image_paths = []
    for f in files:
        safe_name = _safe_filename(f.filename)
        dest = job_dir / safe_name
        with dest.open("wb") as out:
            shutil.copyfileobj(f.file, out)
        image_paths.append(str(dest))

    JOBS[job_id] = {"status": "running"}
    background_tasks.add_task(_run_batch_job, job_id, job_dir, image_paths, road_config)
    logger.info("Batch job %s started — %d images", job_id, len(image_paths))
    return {"job_id": job_id, "status": "running", "num_images": len(image_paths)}


# ----------------------------------------------------------------
# VIDEO MODE
# ----------------------------------------------------------------
def _run_video_job(job_id: str, job_dir: Path, video_path: str,
                    road_config: dict, sample_every_sec: float):
    try:
        analyzer = get_analyzer()
        summary  = analyzer.analyse_video(
            video_path, road_config,
            output_dir=str(job_dir),
            sample_every_sec=sample_every_sec,
        )
        summary.pop("_json_path", None)
        JOBS[job_id] = {"status": "done", "result": summary}
        logger.info("Video job %s done", job_id)
    except Exception as e:
        logger.error("Video job %s failed: %s", job_id, e, exc_info=True)
        JOBS[job_id] = {"status": "error", "error": str(e)}


@app.post("/api/analyze/video")
async def analyze_video(
    background_tasks:  BackgroundTasks,
    file:              UploadFile = File(...),
    total_width_m:     float = Form(...),
    num_lanes:         int   = Form(...),
    carriageway_key:   str   = Form(...),
    fringe_condition:  str   = Form(...),
    usable_shoulder_m: float = Form(...),
    sample_every_sec:  float = Form(1.0),
    traffic_regime:    str   = Form("low"),
):
    road_config = _road_config_from_form(
        total_width_m, num_lanes, carriageway_key,
        fringe_condition, usable_shoulder_m, traffic_regime,
    )

    job_id, job_dir = _new_job("video")
    safe_name = _safe_filename(file.filename)
    dest = job_dir / safe_name
    with dest.open("wb") as out:
        shutil.copyfileobj(file.file, out)

    JOBS[job_id] = {"status": "running"}
    background_tasks.add_task(
        _run_video_job, job_id, job_dir, str(dest), road_config, sample_every_sec
    )
    logger.info("Video job %s started", job_id)
    return {"job_id": job_id, "status": "running"}


# ----------------------------------------------------------------
# Job status polling
# ----------------------------------------------------------------
@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, f"Unknown job_id '{job_id}'.")
    return job


# ----------------------------------------------------------------
# Health check
# ----------------------------------------------------------------
@app.get("/api/health")
def health():
    return {
        "status":       "ok",
        "model_loaded": Path(MODEL_PATH).exists(),
        "model_path":   MODEL_PATH,
        "dt_enabled":   _DT_ENABLED,
    }


# ----------------------------------------------------------------
# Digital Twin endpoints
# ----------------------------------------------------------------
@app.get("/api/digital-twin/status")
def digital_twin_status():
    if not _DT_ENABLED:
        raise HTTPException(503, "Digital Twin (MATLAB) bridge not available on this server.")
    return get_twin_status()


@app.get("/api/digital-twin/latest")
def digital_twin_latest():
    if not _DT_ENABLED:
        raise HTTPException(503, "Digital Twin (MATLAB) bridge not available on this server.")
    data = get_latest_twin_data()
    if data is None:
        raise HTTPException(404, "No digital twin simulation has been run yet.")
    return data
