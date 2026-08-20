"""
road_analyzer.digital_twin_bridge
==================================
This file did not exist anywhere in the repo. app.py has always tried
to `from road_analyzer.digital_twin_bridge import (...)`, that import
has always failed, and app.py silently catches the ImportError and
sets `_DT_ENABLED = False` — which is why every /api/digital-twin/*
endpoint has always returned "unavailable" and the dashboard's Digital
Twin panel has never had anything to show. This module is the fix.

It launches MATLAB in the background (non-blocking — the FastAPI
request returns immediately) to run matlab_twin/run_digital_twin.m,
then polls the status/output JSON files that script writes.

Configuration (matches what your README already documents):
  MATLAB_EXE   env var — full path to matlab.exe / matlab binary.
               If unset, MATLAB features are disabled but the rest
               of the app keeps working, exactly as your README says.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
from pathlib import Path
from typing import Optional

logger = logging.getLogger("road_analyzer.digital_twin_bridge")

BASE_DIR       = Path(__file__).resolve().parent.parent   # road_analyzer_deploy/
MATLAB_TWIN_DIR = BASE_DIR / "matlab_twin"
STATUS_PATH    = MATLAB_TWIN_DIR / "dt_status.json"
OUTPUT_PATH    = MATLAB_TWIN_DIR / "dt_output.json"

MATLAB_EXE = os.environ.get("MATLAB_EXE", "")

# Guards against overlapping simulation runs
_lock = threading.Lock()
_running = False


def _matlab_available() -> bool:
    return bool(MATLAB_EXE) and Path(MATLAB_EXE).exists()


def _run_matlab(json_path: str) -> None:
    global _running
    try:
        if not _matlab_available():
            logger.warning(
                "MATLAB_EXE not set or not found (%r) — Digital Twin simulation skipped. "
                "Set the MATLAB_EXE environment variable to your matlab executable path.",
                MATLAB_EXE,
            )
            _write_status("unavailable", "MATLAB_EXE not configured on this server.")
            return

        # jsondecode/paths on Windows need escaped backslashes inside the
        # single-quoted MATLAB string — replace \ with \\ before quoting.
        safe_path = json_path.replace("\\", "\\\\").replace("'", "''")
        matlab_cmd = f"run_digital_twin('{safe_path}')"

        cmd = [MATLAB_EXE, "-batch", matlab_cmd]
        logger.info("Launching MATLAB Digital Twin simulation: %s", " ".join(cmd))

        proc = subprocess.run(
            cmd,
            cwd=str(MATLAB_TWIN_DIR),
            capture_output=True,
            text=True,
            timeout=300,   # 5 min safety cap — sim itself only models 60s of traffic
        )
        if proc.returncode != 0:
            logger.error("MATLAB run failed (exit %s): %s", proc.returncode, proc.stderr[-2000:])
            _write_status("error", proc.stderr[-2000:] or "MATLAB exited with a non-zero code.")
        else:
            logger.info("MATLAB Digital Twin simulation finished.")

    except subprocess.TimeoutExpired:
        logger.error("MATLAB Digital Twin simulation timed out.")
        _write_status("error", "Simulation timed out after 300s.")
    except Exception as e:
        logger.error("Digital Twin simulation crashed: %s", e, exc_info=True)
        _write_status("error", str(e))
    finally:
        with _lock:
            _running = False


def _write_status(status: str, error: str = "") -> None:
    MATLAB_TWIN_DIR.mkdir(parents=True, exist_ok=True)
    try:
        STATUS_PATH.write_text(json.dumps({"status": status, "error": error}))
    except Exception as e:
        logger.warning("Could not write dt_status.json: %s", e)


def trigger_matlab_simulation(json_path: str) -> None:
    """Called by app.py right after core.py writes an *_analysis.json file.
    Non-blocking: kicks MATLAB off in a background thread and returns
    immediately so the HTTP response isn't held up by a multi-minute sim."""
    global _running
    with _lock:
        if _running:
            logger.info("A Digital Twin simulation is already running — skipping new trigger.")
            return
        _running = True

    thread = threading.Thread(target=_run_matlab, args=(json_path,), daemon=True)
    thread.start()


def get_twin_status() -> dict:
    """Polled every 2.5s by static/app.js's dtPoll(). IMPORTANT: the shape
    returned here must exactly match what app.js's dtPoll()/dtRender()
    expect: {"status": "done", "twin_data": {...}} on success, where
    twin_data has a "summary" object plus top-level time-series arrays
    (see dtRender/dtDrawCapChart/dtDrawSpdChart in static/app.js and the
    matching output written by matlab_twin/run_digital_twin.m)."""
    with _lock:
        running_now = _running
    if running_now:
        return {"status": "running"}

    if STATUS_PATH.exists():
        try:
            file_status = json.loads(STATUS_PATH.read_text())
        except Exception:
            file_status = {"status": "idle"}
    else:
        file_status = {"status": "idle"}

    if file_status.get("status") == "complete" and OUTPUT_PATH.exists():
        twin_data = get_latest_twin_data()
        if twin_data is not None:
            return {"status": "done", "twin_data": twin_data}

    if file_status.get("status") == "error":
        return {"status": "error", "error": file_status.get("error", "")}

    return {"status": file_status.get("status", "idle")}


def get_latest_twin_data() -> Optional[dict]:
    """Polled by GET /api/digital-twin/latest. Returns None if no
    simulation has completed yet (app.py turns that into a 404)."""
    if not OUTPUT_PATH.exists():
        return None
    try:
        return json.loads(OUTPUT_PATH.read_text())
    except Exception as e:
        logger.warning("dt_output.json exists but couldn't be parsed: %s", e)
        return None
