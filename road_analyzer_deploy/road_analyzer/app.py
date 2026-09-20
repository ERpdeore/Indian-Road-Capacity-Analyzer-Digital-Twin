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
import json
import os
import re
import shutil
import uuid
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, File, Form, UploadFile, HTTPException, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
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

# Digital Twin — pure-Python Greenshields engine (see digital_twin_engine.py
# for why this replaced the old MATLAB-subprocess bridge). Always available,
# since it's plain Python with no external dependency — no more "bridge not
# found" fallback path needed.
from road_analyzer.digital_twin_engine import (
    run_and_store as dt_run_and_store,
    get_twin_status as dt_get_twin_status,
    get_latest_twin_data as dt_get_latest_twin_data,
)
_DT_ENABLED = True
logger.info("Digital Twin engine loaded (pure-Python Greenshields model).")

from road_analyzer.department_extensions import generate_department_report_pdf
from road_analyzer.pothole_rectification import build_pwd_report_row
from road_analyzer.roadrunner_export import (
    build_single_road_xodr, build_corridor_xodr, build_ideal_road_xodr,
    build_ideal_corridor_xodr, corridor_capacity_summary,
)

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


def _unique_dest(job_dir: Path, filename: str) -> Path:
    """
    Resolve a destination path inside job_dir that can't collide with a
    file already written for this job. Batch uploads (site photos taken
    on a phone) very often share a filename like 'IMG_0001.jpg' across
    different photos — without this, the second upload silently overwrites
    the first on disk before analysis runs, and one image's result is
    lost with no error shown anywhere.
    """
    safe_name = _safe_filename(filename)
    dest = job_dir / safe_name
    if not dest.exists():
        return dest
    stem, suffix = Path(safe_name).stem, Path(safe_name).suffix
    n = 2
    while True:
        candidate = job_dir / f"{stem}__{n}{suffix}"
        if not candidate.exists():
            return candidate
        n += 1


def _road_config_from_form(
    total_width_m:    float,
    num_lanes:        int,
    carriageway_key:  str,
    fringe_condition: str,
    usable_shoulder_m: float,
    traffic_regime:   str = "low",
    chainage_m:       float = 0.0,
) -> dict:
    if carriageway_key not in IRC106_DSV:
        raise HTTPException(400, f"Unknown carriageway_key '{carriageway_key}'. "
                                  f"Valid: {list(IRC106_DSV.keys())}")
    if fringe_condition not in FRINGE_CONDITION_DESC:
        raise HTTPException(400, f"Unknown fringe_condition '{fringe_condition}'. "
                                  f"Valid: {list(FRINGE_CONDITION_DESC.keys())}")
    # IRC:106 Table 2 doesn't define a DSV for every carriageway/fringe pair
    # (e.g. an 8-lane divided carriageway has no "collector" row). Catching
    # that here — before any file is uploaded or a job/background task is
    # started — means a bad combination fails fast with a clear message
    # instead of surfacing later as a wasted upload or a failed batch/video
    # job. This is the same table the frontend uses to grey out invalid
    # fringe options, so this is a backstop, not a duplicate of that UX.
    if IRC106_DSV[carriageway_key].get(fringe_condition) is None:
        valid_fringes = [f for f, v in IRC106_DSV[carriageway_key].items() if v is not None]
        raise HTTPException(
            400,
            f"IRC:106 Table 2 has no Design Service Volume for "
            f"'{carriageway_key}' under '{fringe_condition}' fringe conditions. "
            f"Valid fringe conditions for this carriageway type: {valid_fringes}",
        )
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
        "chainage_m":       float(chainage_m),
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
    chainage_m:        float = Form(0.0),
):
    road_config = _road_config_from_form(
        total_width_m, num_lanes, carriageway_key,
        fringe_condition, usable_shoulder_m, traffic_regime, chainage_m,
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

    # Pothole rectification recommendation — pure lookup over data
    # analyse_image() already computed (severity, depth, capacity loss).
    # Only runs when a pothole was actually detected; every other
    # per_defect entry and every other field in `result` is untouched.
    if "pothole" in result.get("per_defect", {}):
        try:
            result["per_defect"]["pothole"]["rectification"] = build_pwd_report_row(
                result["per_defect"]["pothole"], location=safe_name
            )
        except Exception as e:
            logger.warning("Pothole rectification lookup failed: %s", e)

    # Department-routed PDF report — replaces the old CSV export, which
    # was written to disk but never exposed through any download route.
    # Generated synchronously here (a single-image report takes well
    # under a second with reportlab) and saved into the same job_dir as
    # the image and JSON, so /api/jobs/{job_id}/department-report.pdf
    # can serve it straight off disk.
    try:
        pdf_path = job_dir / f"{Path(dest).stem}_department_report.pdf"
        generate_department_report_pdf(result, str(pdf_path), site_label=safe_name)
        result["department_report_available"] = True
    except Exception as e:
        logger.warning("Department PDF report generation failed: %s", e)
        result["department_report_available"] = False

    # RoadRunner OpenDRIVE (.xodr) export — a straight road segment sized
    # to this photo's measured width/lanes, with detected defects placed
    # as road objects. Saved to disk the same way as the PDF report so
    # /api/jobs/{job_id}/roadrunner.xodr can serve it without re-running
    # analysis. See roadrunner_export.py for the honest limits on what
    # this can and can't know from a single photo.
    try:
        xodr_path = job_dir / f"{Path(dest).stem}_roadrunner.xodr"
        xodr_path.write_text(build_single_road_xodr(result), encoding="utf-8")
        result["roadrunner_xodr_available"] = True
    except Exception as e:
        logger.warning("RoadRunner .xodr export failed: %s", e)
        result["roadrunner_xodr_available"] = False

    # IDEAL version of the same road (same width/lanes, defects removed)
    # -- generated alongside the non-ideal one so both are ready to go
    # the instant analysis finishes, with no extra wait during the demo.
    try:
        ideal_xodr_path = job_dir / f"{Path(dest).stem}_roadrunner_ideal.xodr"
        ideal_xodr_path.write_text(build_ideal_road_xodr(result), encoding="utf-8")
        result["roadrunner_ideal_xodr_available"] = True
    except Exception as e:
        logger.warning("RoadRunner ideal .xodr export failed: %s", e)
        result["roadrunner_ideal_xodr_available"] = False

    # Capacity numbers sidecar -- a small JSON file next to the two .xodr
    # files, carrying the real ideal-vs-reduced capacity (vehicles/hr)
    # this job already calculated. The RoadRunner/MATLAB side reads this
    # to decide how many vehicles to actually show in each 3D simulation,
    # so the visual traffic density reflects your real IRC-based numbers
    # instead of an arbitrary fixed vehicle count.
    try:
        capacity_path = job_dir / f"{Path(dest).stem}_roadrunner_capacity.json"
        capacity_path.write_text(json.dumps({
            "original_capacity_vehicles_hr": result.get("original_capacity_vehicles_hr"),
            "reduced_capacity_vehicles_hr": result.get("reduced_capacity_vehicles_hr"),
            "capacity_loss_pct": result.get("capacity_loss_pct"),
            # Real Greenshields-model speeds (km/h) from this same analysis --
            # free_flow_speed_kmh is the ideal-road speed, congested_speed_kmh
            # is what the road actually supports with its detected defects.
            # These drive actual vehicle speed in the RoadRunner simulation,
            # not just vehicle count.
            "free_flow_speed_kmh": result.get("free_flow_speed_kmh"),
            "congested_speed_kmh": (result.get("traffic_regime") or {}).get("congested_speed_kmh"),
        }), encoding="utf-8")
    except Exception as e:
        logger.warning("RoadRunner capacity sidecar export failed: %s", e)

    # Generate Digital Twin data — pure-Python Greenshields model, runs
    # synchronously in milliseconds (no MATLAB, no subprocess, no waiting).
    # We still report "running" then let the frontend's existing poll hit
    # "done" on its very first check, so the JS twin-panel code (built for
    # an async MATLAB job) needs zero changes to work with this.
    if _DT_ENABLED:
        try:
            dt_run_and_store(result)
            result["digital_twin_status"] = "running"
        except Exception as e:
            logger.warning("Digital twin generation failed: %s", e)
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
        per_image_full = summary.pop("_per_image_full", [])

        # Department PDF + Digital Twin for batch: built from the single
        # worst-case photo in the batch (highest capacity loss %), since
        # that result already has the full road_config/irc_basis/per_defect
        # shape both features need — the same shape a single-image analysis
        # produces. An appendix table lists every photo's capacity loss so
        # the report is honest about being one batch, not just one photo.
        if per_image_full:
            worst = max(per_image_full, key=lambda r: r.get("capacity_loss_pct", 0))
            try:
                pdf_path = job_dir / "batch_department_report.pdf"
                generate_department_report_pdf(
                    worst, str(pdf_path),
                    site_label=f"Batch of {len(per_image_full)} photos "
                               f"(worst case: {worst.get('image', '-')})",
                    appendix_title="All photos in this batch",
                    appendix_headers=["image", "capacity_loss_pct", "defects_found"],
                    appendix_rows=[
                        {"image": r.get("image", "-"),
                         "capacity_loss_pct": f"{r.get('capacity_loss_pct', 0)}%",
                         "defects_found": ", ".join(r.get("per_defect", {}).keys()) or "none"}
                        for r in per_image_full
                    ],
                )
                summary["department_report_available"] = True
            except Exception as e:
                logger.warning("Batch department PDF generation failed: %s", e)
                summary["department_report_available"] = False

            if _DT_ENABLED:
                try:
                    dt_run_and_store(worst)
                except Exception as e:
                    logger.warning("Batch digital twin generation failed: %s", e)

        summary["job_id"] = job_id
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
        dest = _unique_dest(job_dir, f.filename)
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
        frame_results_full = summary.pop("_frame_results_full", [])

        # Department PDF + Digital Twin for video: built from the single
        # worst-case sampled frame (highest capacity loss %) for the same
        # reason as batch mode above. The appendix lists every unique
        # tracked defect instance across the whole video (not just the
        # worst frame), using the same deduplicated tracking data already
        # computed by analyse_video — so a pothole seen in 40 frames is
        # reported once, not 40 times.
        if frame_results_full:
            worst = max(frame_results_full, key=lambda r: r.get("capacity_loss_pct", 0))
            unique_defects = summary.get("unique_defect_instances", [])
            try:
                pdf_path = job_dir / "video_department_report.pdf"
                generate_department_report_pdf(
                    worst, str(pdf_path),
                    site_label=f"Video: {summary.get('video', '-')} "
                               f"(worst frame at {worst.get('timestamp_sec', '-')}s)",
                    appendix_title="Unique defect instances tracked across the full video",
                    appendix_headers=["cls_name", "times_seen", "first_seen_sec",
                                       "last_seen_sec", "max_blocked_m"],
                    appendix_rows=unique_defects,
                )
                summary["department_report_available"] = True
            except Exception as e:
                logger.warning("Video department PDF generation failed: %s", e)
                summary["department_report_available"] = False

            if _DT_ENABLED:
                try:
                    dt_run_and_store(worst)
                except Exception as e:
                    logger.warning("Video digital twin generation failed: %s", e)

        summary["job_id"] = job_id
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


@app.get("/api/jobs/{job_id}/department-report.pdf")
def get_department_report(job_id: str):
    # job_id is normally our own uuid-based identifier (see _new_job), but
    # since it comes straight from the URL, validate it before building a
    # filesystem path from it — otherwise a crafted job_id like
    # "../../etc" could be used to walk outside RESULTS_DIR.
    if not re.fullmatch(r"[A-Za-z0-9_\-]+", job_id):
        raise HTTPException(400, "Invalid job_id.")
    job_dir = RESULTS_DIR / job_id
    if not job_dir.is_dir():
        raise HTTPException(404, f"Unknown job_id '{job_id}'.")
    pdfs = sorted(job_dir.glob("*_department_report.pdf"))
    if not pdfs:
        raise HTTPException(404, "No department report was generated for this job.")
    return FileResponse(
        str(pdfs[0]),
        media_type="application/pdf",
        filename=pdfs[0].name,
    )


@app.get("/api/jobs/{job_id}/roadrunner.xodr")
def get_roadrunner_xodr(job_id: str):
    # Same validation and disk-lookup pattern as the PDF report above.
    if not re.fullmatch(r"[A-Za-z0-9_\-]+", job_id):
        raise HTTPException(400, "Invalid job_id.")
    job_dir = RESULTS_DIR / job_id
    if not job_dir.is_dir():
        raise HTTPException(404, f"Unknown job_id '{job_id}'.")
    xodrs = sorted(job_dir.glob("*_roadrunner.xodr"))
    if not xodrs:
        raise HTTPException(404, "No RoadRunner export was generated for this job.")
    return FileResponse(
        str(xodrs[0]),
        media_type="application/xml",
        filename=xodrs[0].name,
    )


@app.get("/api/jobs/{job_id}/roadrunner-capacity.json")
def get_roadrunner_capacity_json(job_id: str):
    if not re.fullmatch(r"[A-Za-z0-9_\-]+", job_id):
        raise HTTPException(400, "Invalid job_id.")
    job_dir = RESULTS_DIR / job_id
    if not job_dir.is_dir():
        raise HTTPException(404, f"Unknown job_id '{job_id}'.")
    jsons = sorted(job_dir.glob("*_roadrunner_capacity.json"))
    if not jsons:
        raise HTTPException(404, "No capacity data was generated for this job.")
    return FileResponse(
        str(jsons[0]),
        media_type="application/json",
        filename=jsons[0].name,
    )


@app.get("/api/jobs/{job_id}/roadrunner-ideal.xodr")
def get_roadrunner_ideal_xodr(job_id: str):
    if not re.fullmatch(r"[A-Za-z0-9_\-]+", job_id):
        raise HTTPException(400, "Invalid job_id.")
    job_dir = RESULTS_DIR / job_id
    if not job_dir.is_dir():
        raise HTTPException(404, f"Unknown job_id '{job_id}'.")
    xodrs = sorted(job_dir.glob("*_roadrunner_ideal.xodr"))
    if not xodrs:
        raise HTTPException(404, "No ideal RoadRunner export was generated for this job.")
    return FileResponse(
        str(xodrs[0]),
        media_type="application/xml",
        filename=xodrs[0].name,
    )


@app.post("/api/export/roadrunner-corridor.xodr")
async def export_roadrunner_corridor(request: Request):
    # Takes a JSON body of {"results": [<result dict>, ...]} — the same
    # result objects /api/analyze/image already returned to the browser
    # for each photo analysed this session. Built in-memory (not saved
    # to disk, unlike the single-road export above) since a corridor is
    # a one-off combination the user assembles client-side, not tied to
    # any single job_id.
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Request body must be JSON: {\"results\": [...]}")
    results = body.get("results")
    if not isinstance(results, list) or not results:
        raise HTTPException(400, "Provide a non-empty 'results' list of prior analysis results.")
    try:
        xodr_text = build_corridor_xodr(results)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.error("Corridor .xodr build failed: %s", e, exc_info=True)
        raise HTTPException(500, f"Could not build corridor export: {e}")
    return Response(
        content=xodr_text,
        media_type="application/xml",
        headers={"Content-Disposition": 'attachment; filename="roadrunner_corridor.xodr"'},
    )


@app.post("/api/export/roadrunner-corridor-ideal.xodr")
async def export_roadrunner_corridor_ideal(request: Request):
    # Same input contract as the real corridor export above: {"results": [...]}
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Request body must be JSON: {\"results\": [...]}")
    results = body.get("results")
    if not isinstance(results, list) or not results:
        raise HTTPException(400, "Provide a non-empty 'results' list of prior analysis results.")
    try:
        xodr_text = build_ideal_corridor_xodr(results)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.error("Ideal corridor .xodr build failed: %s", e, exc_info=True)
        raise HTTPException(500, f"Could not build ideal corridor export: {e}")
    return Response(
        content=xodr_text,
        media_type="application/xml",
        headers={"Content-Disposition": 'attachment; filename="roadrunner_corridor_ideal.xodr"'},
    )


@app.post("/api/export/roadrunner-corridor-capacity.json")
async def export_roadrunner_corridor_capacity(request: Request):
    # Combines each photo's already-calculated capacity numbers into one
    # summary for the whole corridor (weakest-segment rule -- see
    # corridor_capacity_summary's docstring). This is what the RoadRunner
    # automation reads to decide vehicle count/speed for a corridor demo.
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Request body must be JSON: {\"results\": [...]}")
    results = body.get("results")
    if not isinstance(results, list) or not results:
        raise HTTPException(400, "Provide a non-empty 'results' list of prior analysis results.")
    try:
        summary = corridor_capacity_summary(results)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return Response(
        content=json.dumps(summary),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="roadrunner_corridor_capacity.json"'},
    )


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
        raise HTTPException(503, "Digital Twin engine not available on this server.")
    return dt_get_twin_status()


@app.get("/api/digital-twin/latest")
def digital_twin_latest():
    if not _DT_ENABLED:
        raise HTTPException(503, "Digital Twin engine not available on this server.")
    data = dt_get_latest_twin_data()
    if data is None:
        raise HTTPException(404, "No digital twin simulation has been run yet.")
    return data
