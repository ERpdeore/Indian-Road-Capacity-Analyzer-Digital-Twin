"""
road_analyzer.app
=================
FastAPI server for the Indian Road Capacity Analyzer.

Capacity method: Indo-HCM 2017 Chapter 5 (see road_analyzer/indo_hcm.py and
road_analyzer/core.py). The digital twin is computed in pure Python by
road_analyzer/digital_twin_engine.py and returned with every analysis.
"""

from __future__ import annotations

import logging
import json
import os
import re
import shutil
import uuid
import io
import zipfile
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, File, Form, UploadFile, HTTPException, BackgroundTasks, Request, Depends
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

from road_analyzer.core import RoadAnalyzer, CLASS_NAMES, OBSTRUCTION_CLASSES, resolve_road_inputs
from road_analyzer import indo_hcm as hcm
from road_analyzer.digital_twin_engine import (
    run_and_store as dt_run_and_store,
    get_latest_twin_data as dt_get_latest_twin_data,
)

from road_analyzer.department_extensions import generate_department_report_pdf
from road_analyzer.pothole_rectification import build_pwd_report_row
from road_analyzer.roadrunner_export import (
    build_single_road_xodr, build_corridor_xodr, build_ideal_road_xodr,
    build_ideal_corridor_xodr, corridor_capacity_summary, get_defect_positions,
)
from road_analyzer.excel_export import export_defects_excel

# ----------------------------------------------------------------
# Paths
# ----------------------------------------------------------------
BASE_DIR    = Path(__file__).resolve().parent
UPLOAD_DIR  = BASE_DIR / "uploads"
RESULTS_DIR = BASE_DIR / "results"
MODELS_DIR  = BASE_DIR / "models"
STATIC_DIR  = BASE_DIR / "static"
# road_analyzer_deploy/matlab_twin — sibling of road_analyzer/, one level
# above this file's own folder. Holds the STATIC (not per-job) MATLAB
# helper scripts that /api/jobs/{job_id}/bundle.zip packages alongside
# each job's generated .xodr/.json files.
MATLAB_TWIN_DIR = BASE_DIR.parent / "matlab_twin"

for d in (UPLOAD_DIR, RESULTS_DIR, MODELS_DIR, STATIC_DIR):
    d.mkdir(parents=True, exist_ok=True)

MODEL_PATH = os.environ.get("ROAD_MODEL_PATH", str(MODELS_DIR / "best.pt"))

app = FastAPI(title="Indian Road Capacity Analyzer", version="3.0")

# The dashboard is served from this same origin, so no CORS is needed by
# default. Set ALLOWED_ORIGINS="https://a.example,https://b.example" only if
# another site must call this API.
_origins = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()]
if _origins:
    app.add_middleware(CORSMiddleware, allow_origins=_origins,
                       allow_methods=["GET", "POST"], allow_headers=["*"])

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


def _parse_iso_date(value: str, field_label: str) -> Optional[date]:
    """
    Parses a plain 'YYYY-MM-DD' string into a date object. Returns None
    for an empty/blank value (caller decides whether that's allowed).
    Raises HTTPException(400) for anything non-empty that isn't a valid
    ISO date — this is a hard validation error, unlike analysis_date's
    old "ignore and fall back to today" behaviour, because a collection
    date silently replaced by today would be actively misleading.
    """
    value = (value or "").strip()
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(400, f"Invalid {field_label} '{value}' — expected YYYY-MM-DD.")


def _normalise_analysis_date(analysis_date: str) -> str:
    """
    Returns a plain 'YYYY-MM-DD' string. The frontend's <input type="date">
    always sends one already, defaulted to today by app.js on page load, but
    this is the backstop for direct API calls that omit it, send it blank,
    or send something malformed — same date shown on screen must be the date
    that lands in the department report PDF, so this is the one place both
    the live UI and the PDF ultimately derive it from when the client didn't
    supply a valid one.
    """
    if analysis_date:
        try:
            return datetime.strptime(analysis_date.strip(), "%Y-%m-%d").strftime("%Y-%m-%d")
        except ValueError:
            logger.warning("Ignoring unparseable analysis_date %r — using today's date instead.", analysis_date)
    return date.today().isoformat()


def _validate_dates(data_collection_date: str, analysis_date: str) -> tuple[str, str]:
    """
    Validates and normalises both date fields together:
      - data_collection_date is REQUIRED and cannot be in the future --
        today and any earlier date are allowed, so a photo taken and
        analysed the same day works.
      - analysis_date defaults to today when omitted/blank (same behaviour
        as before), but is rejected if it's in the future.
      - analysis_date cannot be earlier than data_collection_date — you
        can't analyse data before it was collected.
    Returns the two normalised 'YYYY-MM-DD' strings.
    """
    collection_dt = _parse_iso_date(data_collection_date, "data_collection_date")
    if collection_dt is None:
        raise HTTPException(400, "data_collection_date is required.")
    if collection_dt > date.today():
        raise HTTPException(400, "data_collection_date cannot be in the future.")

    analysis_str = _normalise_analysis_date(analysis_date)
    analysis_dt  = datetime.strptime(analysis_str, "%Y-%m-%d").date()
    if analysis_dt > date.today():
        raise HTTPException(400, "analysis_date cannot be in the future.")
    if analysis_dt < collection_dt:
        raise HTTPException(400, "analysis_date cannot be before data_collection_date.")

    return collection_dt.isoformat(), analysis_str


def _opt_float(value: Optional[str], label: str) -> Optional[float]:
    """Optional numeric form fields arrive as '' when left blank."""
    if value is None or str(value).strip() == "":
        return None
    try:
        v = float(value)
    except ValueError:
        raise HTTPException(400, f"{label} must be a number.")
    if v <= 0:
        raise HTTPException(400, f"{label} must be > 0 when given.")
    return v


def road_form(
    total_width_m:        float = Form(...),
    road_type:            str   = Form(...),
    functional_class:     str   = Form("arterial"),
    operating_speed_kmh:  Optional[str] = Form(None),
    observed_volume_pcu_h: Optional[str] = Form(None),
    on_street_parking:    str   = Form("none"),
    bus_stop:             str   = Form("none"),
    access_points:        str   = Form("none"),
    chainage_m:           float = Form(0.0),
    analysis_date:        str   = Form(""),
    data_collection_date: str   = Form(...),
) -> dict:
    """Shared road-parameter form for every analysis endpoint. Validates
    everything (including Indo-HCM option keys) before any upload is saved."""
    collection_str, analysis_str = _validate_dates(data_collection_date, analysis_date)
    cfg = {
        "total_width_m": float(total_width_m),
        "road_type": road_type,
        "functional_class": functional_class,
        "operating_speed_kmh": _opt_float(operating_speed_kmh, "operating_speed_kmh"),
        "observed_volume_pcu_h": _opt_float(observed_volume_pcu_h, "observed_volume_pcu_h"),
        "on_street_parking": on_street_parking,
        "bus_stop": bus_stop,
        "access_points": access_points,
        "chainage_m": float(chainage_m),
        "analysis_date": analysis_str,
        "data_collection_date": collection_str,
    }
    try:
        resolved = resolve_road_inputs(cfg)
    except ValueError as e:
        raise HTTPException(400, str(e))
    cfg["num_lanes"] = resolved["lanes"]
    return cfg


def _new_job(prefix: str) -> tuple[str, Path]:
    job_id  = f"{prefix}_{uuid.uuid4().hex[:10]}"
    job_dir = RESULTS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    return job_id, job_dir


def _twin(result: dict) -> Optional[dict]:
    try:
        return dt_run_and_store(result)
    except Exception as e:
        logger.warning("Digital twin generation failed: %s", e)
        return None


def _capacity_sidecar(result: dict, twin: Optional[dict]) -> dict:
    """Numbers the MATLAB / RoadRunner scripts read. Capacities are in PCU/h;
    vehicle placement uses the twin's densities and speeds, not capacity."""
    cap_calc = result.get("capacity_calculation") or {}
    iv = result.get("indicative_vehicles") or {}
    return {
        "units": "PCU/h unless stated",
        "base_capacity_pcu_h": result.get("base_capacity_pcu_h"),
        "reduced_capacity_pcu_h": result.get("reduced_capacity_pcu_h"),
        "capacity_loss_pct": result.get("capacity_loss_pct"),
        "operating_speed_kmh": result.get("operating_speed_kmh"),
        "avg_pcu_per_vehicle": iv.get("avg_pcu_per_vehicle"),
        "factors": cap_calc.get("factors"),
        "total_width_m": cap_calc.get("total_width_m"),
        "blocked_incl_shy_m": cap_calc.get("blocked_incl_shy_m"),
        "num_lanes": (result.get("road_config") or {}).get("num_lanes"),
        "divided": (result.get("capacity_basis") or {}).get("divided"),
        "defects_found": list((result.get("per_defect") or {}).keys()),
        # Lateral position across the carriageway is measured; along-road
        # position cannot be measured from one photo and is not included.
        "defect_positions": get_defect_positions(result),
        "twin": None if twin is None else {
            "demand_pcu_h": twin["demand_pcu_h"],
            "demand_source": twin["demand_source"],
            "ideal": twin["ideal"],
            "defect": twin["defect"],
        },
    }


def _attach_outputs(result: dict, job_dir: Path, stem: str, site_label: str) -> None:
    """Every per-job export, each allowed to fail on its own."""
    if "pothole" in result.get("per_defect", {}):
        try:
            result["per_defect"]["pothole"]["rectification"] = build_pwd_report_row(
                result["per_defect"]["pothole"], location=site_label)
        except Exception as e:
            logger.warning("Pothole rectification lookup failed: %s", e)

    twin = _twin(result)
    result["digital_twin"] = twin

    exports = [
        ("department_report_available", f"{stem}_department_report.pdf",
         lambda p: generate_department_report_pdf(result, str(p), site_label=site_label)),
        ("roadrunner_xodr_available", f"{stem}_roadrunner.xodr",
         lambda p: p.write_text(build_single_road_xodr(result), encoding="utf-8")),
        ("roadrunner_ideal_xodr_available", f"{stem}_roadrunner_ideal.xodr",
         lambda p: p.write_text(build_ideal_road_xodr(result), encoding="utf-8")),
        ("capacity_json_available", f"{stem}_roadrunner_capacity.json",
         lambda p: p.write_text(json.dumps(_capacity_sidecar(result, twin), indent=2), encoding="utf-8")),
        ("defects_excel_available", f"{stem}_defects.xlsx",
         lambda p: export_defects_excel(result, str(p))),
    ]
    for flag, name, fn in exports:
        try:
            fn(job_dir / name)
            result[flag] = True
        except Exception as e:
            logger.warning("Export %s failed: %s", name, e)
            result[flag] = False


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
    def opts(table):
        return [{"key": k, "label": v["label"], "factor": v["factor"]} for k, v in table.items()]
    return {
        "standard": hcm.SOURCE_NOTE,
        "road_types": [
            {"key": k, "label": v["label"], "lanes": v["lanes"], "divided": v["divided"],
             "basis": v["basis"], "ref_width_m": v["ref_width_m"],
             "base_capacity_pcu_h": v["base_capacity_pcu_h"], "note": v.get("note", "")}
            for k, v in hcm.ROAD_TYPES.items()
        ],
        "functional_classes": [
            {"key": k, "label": v["label"], "operating_speed_kmh": v["operating_speed_kmh"]}
            for k, v in hcm.FUNCTIONAL_CLASSES.items()
        ],
        "speed_model": {"a": hcm.SPEED_MODEL_A, "b": hcm.SPEED_MODEL_B,
                        "range_kmh": hcm.SPEED_MODEL_RANGE_KMH},
        "on_street_parking": opts(hcm.PARKING_FACTORS),
        "bus_stop": opts(hcm.BUS_STOP_FACTORS),
        "access_points": opts(hcm.ACCESS_FACTORS),
        "dsv_vc_ratio": hcm.DSV_VC_RATIO,
        "defect_classes": OBSTRUCTION_CLASSES,
        "model_loaded": Path(MODEL_PATH).exists(),
    }


# ----------------------------------------------------------------
# SINGLE IMAGE ANALYSIS
# ----------------------------------------------------------------
# Plain `def` on purpose: this handler runs blocking YOLO inference with no
# `await`. FastAPI runs a sync handler in a worker thread; an `async def`
# one would run on the event loop and freeze every other request
# (health check, job polling) for the whole inference.
@app.post("/api/analyze/image")
def analyze_image(
    file:        UploadFile = File(...),
    road_config: dict = Depends(road_form),
):
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

    result.pop("_json_path", None)
    result.pop("_csv_path", None)
    result["job_id"] = job_id
    _attach_outputs(result, job_dir, Path(dest).stem, safe_name)
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

        # Make sure data_collection_date/analysis_date are present in the
        # batch summary's road_config regardless of what core.py echoes
        # back — same reasoning as the single-image endpoint above.
        summary.setdefault("road_config", {})
        summary["road_config"]["data_collection_date"] = road_config["data_collection_date"]
        summary["road_config"]["analysis_date"] = road_config["analysis_date"]

        # Department PDF + twin are built from the bottleneck photo (lowest
        # reduced capacity) — a stretch is governed by its weakest section.
        # The appendix lists every photo so the report covers the batch.
        if per_image_full:
            worst = min(per_image_full, key=lambda r: r.get("reduced_capacity_pcu_h", float("inf")))
            try:
                pdf_path = job_dir / "batch_department_report.pdf"
                generate_department_report_pdf(
                    worst, str(pdf_path),
                    site_label=f"Batch of {len(per_image_full)} photos "
                               f"(bottleneck: {worst.get('image', '-')})",
                    appendix_title="All photos in this batch",
                    appendix_headers=["image", "reduced_capacity_pcu_h", "capacity_loss_pct", "defects_found"],
                    appendix_rows=[
                        {"image": r.get("image", "-"),
                         "reduced_capacity_pcu_h": r.get("reduced_capacity_pcu_h", "-"),
                         "capacity_loss_pct": f"{r.get('capacity_loss_pct', 0)}%",
                         "defects_found": ", ".join(r.get("per_defect", {}).keys()) or "none"}
                        for r in per_image_full
                    ],
                )
                summary["department_report_available"] = True
            except Exception as e:
                logger.warning("Batch department PDF generation failed: %s", e)
                summary["department_report_available"] = False

            # Twin of the governing (lowest-capacity) section.
            summary["digital_twin"] = _twin(worst)

        summary["job_id"] = job_id
        JOBS[job_id] = {"status": "done", "result": summary}
        logger.info("Batch job %s done — %d images", job_id, len(image_paths))
    except Exception as e:
        logger.error("Batch job %s failed: %s", job_id, e, exc_info=True)
        JOBS[job_id] = {"status": "error", "error": str(e)}


@app.post("/api/analyze/batch")
async def analyze_batch(
    background_tasks: BackgroundTasks,
    files:            List[UploadFile] = File(...),
    road_config:      dict = Depends(road_form),
):
    if not files:
        raise HTTPException(400, "Upload at least one image.")

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

        # Same reasoning as batch mode: guarantee both date fields are
        # present in the response's road_config.
        summary.setdefault("road_config", {})
        summary["road_config"]["data_collection_date"] = road_config["data_collection_date"]
        summary["road_config"]["analysis_date"] = road_config["analysis_date"]

        # Same bottleneck rule as batch mode. The appendix lists every unique
        # tracked defect instance across the whole video (not just the
        # worst frame), using the same deduplicated tracking data already
        # computed by analyse_video — so a pothole seen in 40 frames is
        # reported once, not 40 times.
        if frame_results_full:
            worst = min(frame_results_full, key=lambda r: r.get("reduced_capacity_pcu_h", float("inf")))
            unique_defects = summary.get("unique_defect_instances", [])
            try:
                pdf_path = job_dir / "video_department_report.pdf"
                generate_department_report_pdf(
                    worst, str(pdf_path),
                    site_label=f"Video: {summary.get('video', '-')} "
                               f"(bottleneck frame at {worst.get('timestamp_sec', '-')}s)",
                    appendix_title="Unique defect instances tracked across the full video",
                    appendix_headers=["cls_name", "times_seen", "first_seen_sec",
                                       "last_seen_sec", "max_width_m"],
                    appendix_rows=unique_defects,
                )
                summary["department_report_available"] = True
            except Exception as e:
                logger.warning("Video department PDF generation failed: %s", e)
                summary["department_report_available"] = False

            # Twin of the governing (lowest-capacity) section.
            summary["digital_twin"] = _twin(worst)

        summary["job_id"] = job_id
        JOBS[job_id] = {"status": "done", "result": summary}
        logger.info("Video job %s done", job_id)
    except Exception as e:
        logger.error("Video job %s failed: %s", job_id, e, exc_info=True)
        JOBS[job_id] = {"status": "error", "error": str(e)}


@app.post("/api/analyze/video")
async def analyze_video(
    background_tasks: BackgroundTasks,
    file:             UploadFile = File(...),
    road_config:      dict = Depends(road_form),
    sample_every_sec: float = Form(1.0),
):
    if not (0.2 <= sample_every_sec <= 30):
        raise HTTPException(400, "sample_every_sec must be between 0.2 and 30.")

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


@app.get("/api/jobs/{job_id}/defects.xlsx")
def get_defects_excel(job_id: str):
    if not re.fullmatch(r"[A-Za-z0-9_\-]+", job_id):
        raise HTTPException(400, "Invalid job_id.")
    job_dir = RESULTS_DIR / job_id
    if not job_dir.is_dir():
        raise HTTPException(404, f"Unknown job_id '{job_id}'.")
    xlsxs = sorted(job_dir.glob("*_defects.xlsx"))
    if not xlsxs:
        raise HTTPException(404, "No defect Excel log was generated for this job.")
    return FileResponse(
        str(xlsxs[0]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=xlsxs[0].name,
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


# Static (not per-job) files bundle.zip pulls from matlab_twin/ alongside
# whatever the job actually generated. Listed by filename, not glob,
# since these are fixed helper scripts, not per-job output.
_BUNDLE_STATIC_FILES = [
    "auto_import_roadrunner.m",
    "add_vehicles_ideal.m",
    "add_vehicles_nonideal.m",
    "run_ideal_digital_twin.bat",
    "run_nonideal_digital_twin.bat",
]


@app.get("/api/jobs/{job_id}/bundle.zip")
def get_digital_twin_bundle(job_id: str):
    """Everything the 'Digital Twin Bundle' button on the dashboard
    promises: this job's ideal .xodr, non-ideal .xodr and capacity JSON,
    plus the static matlab_twin/ scripts and .bat launchers needed to
    actually run them in RoadRunner. Previously this route didn't exist
    at all — the frontend linked to it, but nothing on the backend
    served it, so every click 404'd."""
    if not re.fullmatch(r"[A-Za-z0-9_\-]+", job_id):
        raise HTTPException(400, "Invalid job_id.")
    job_dir = RESULTS_DIR / job_id
    if not job_dir.is_dir():
        raise HTTPException(404, f"Unknown job_id '{job_id}'.")

    # Per-job generated files — include whichever actually exist; each
    # was generated independently (and independently allowed to fail)
    # by the analyze endpoint, so don't require all three.
    job_patterns = [
        "*_roadrunner.xodr",
        "*_roadrunner_ideal.xodr",
        "*_roadrunner_capacity.json",
    ]
    job_files: list[Path] = []
    for pat in job_patterns:
        job_files.extend(sorted(job_dir.glob(pat)))

    if not job_files:
        raise HTTPException(
            404,
            "No RoadRunner export was generated for this job yet — analyse "
            "an image first, then download the bundle.",
        )

    missing_static = [
        name for name in _BUNDLE_STATIC_FILES
        if not (MATLAB_TWIN_DIR / name).is_file()
    ]
    if missing_static:
        logger.warning(
            "bundle.zip: matlab_twin/ is missing %s — packaging job files "
            "without them.", missing_static)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in job_files:
            zf.write(f, arcname=f.name)
        for name in _BUNDLE_STATIC_FILES:
            src = MATLAB_TWIN_DIR / name
            if src.is_file():
                zf.write(src, arcname=name)
        zf.writestr(
            "HOW_TO_USE.txt",
            "1. Extract this zip anywhere on your machine.\n"
            "2. Set the MATLAB_EXE environment variable to your matlab.exe "
            "path (see the .bat files for the default location they try "
            "first).\n"
            "3. Double-click run_ideal_digital_twin.bat to open the "
            "defect-free version of this road in RoadRunner.\n"
            "4. Double-click run_nonideal_digital_twin.bat to open the "
            "version with the detected defects placed on it.\n"
            "5. Both scripts read the matching .xodr/.json in this same "
            "folder automatically — keep everything together.\n",
        )
    buf.seek(0)

    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{job_id}_digital_twin_bundle.zip"'
        },
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
    return {"status": "ok", "model_loaded": Path(MODEL_PATH).exists(), "model_path": MODEL_PATH}


# ----------------------------------------------------------------
# Digital Twin — returned inline with every analysis ("digital_twin");
# this endpoint only re-serves the most recent one.
# ----------------------------------------------------------------
@app.get("/api/digital-twin/latest")
def digital_twin_latest():
    data = dt_get_latest_twin_data()
    if data is None:
        raise HTTPException(404, "No digital twin has been generated yet.")
    return data
