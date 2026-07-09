"""
digital_twin_bridge.py
======================
Python ↔ MATLAB bridge for the Road Capacity Digital Twin.

What this module does
---------------------
1. After a FastAPI analysis completes, call `trigger_matlab_simulation(json_path)`
   which invokes MATLAB in the background and runs run_digital_twin.m
2. FastAPI then serves the digital-twin output via  GET /api/digital-twin/latest
3. The dashboard polls that endpoint and renders the twin panels.

How MATLAB is called
--------------------
MATLAB is started with:
    matlab -batch "run_digital_twin('path/to/result.json')"

This requires MATLAB R2024a+ to be on the system PATH.
Set the env var MATLAB_EXE if it is installed in a non-standard location,
e.g.:
    export MATLAB_EXE="/usr/local/MATLAB/R2026a/bin/matlab"

On Windows:
    set MATLAB_EXE=C:\\Program Files\\MATLAB\\R2026a\\bin\\matlab.exe
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("road_analyzer.digital_twin_bridge")

# ----------------------------------------------------------------
# Paths
# ----------------------------------------------------------------
_HERE          = Path(__file__).resolve().parent          # road_analyzer/
_MATLAB_DIR    = _HERE.parent.parent / "matlab_twin"      # repo root / matlab_twin/
_DT_OUTPUT     = _MATLAB_DIR / "dt_output.json"
_MATLAB_EXE    = os.environ.get("MATLAB_EXE", "matlab")  # override via env var

# ----------------------------------------------------------------
# In-memory state (keeps track of the last simulation)
# ----------------------------------------------------------------
_state = {
    "status":      "idle",      # idle | running | done | error
    "source_json": None,
    "error":       None,
    "started_at":  None,
    "finished_at": None,
}
_state_lock = threading.Lock()


# ================================================================
# Public API used by app.py
# ================================================================

def trigger_matlab_simulation(analysis_json_path: str) -> None:
    """
    Fire-and-forget: launch MATLAB in a background thread.
    Returns immediately; poll `get_twin_status()` for progress.
    """
    t = threading.Thread(
        target=_run_matlab,
        args=(analysis_json_path,),
        daemon=True,
        name="matlab-twin",
    )
    t.start()
    logger.info("[DT Bridge] MATLAB simulation thread started for: %s",
                analysis_json_path)


def get_twin_status() -> dict:
    """Return current simulation status + latest output if available."""
    with _state_lock:
        status_copy = dict(_state)

    result = {"status": status_copy["status"]}

    if status_copy["status"] == "error":
        result["error"] = status_copy["error"]

    if status_copy["status"] == "done" and _DT_OUTPUT.exists():
        try:
            with open(_DT_OUTPUT) as f:
                result["twin_data"] = json.load(f)
        except Exception as e:
            result["error"] = f"Could not read dt_output.json: {e}"
            result["status"] = "error"

    result["source_json"]  = status_copy["source_json"]
    result["started_at"]   = status_copy["started_at"]
    result["finished_at"]  = status_copy["finished_at"]
    return result


def get_latest_twin_data() -> Optional[dict]:
    """Return the most recent dt_output.json content, or None."""
    if _DT_OUTPUT.exists():
        try:
            with open(_DT_OUTPUT) as f:
                return json.load(f)
        except Exception:
            return None
    return None


# ================================================================
# Internal
# ================================================================

def _run_matlab(analysis_json_path: str) -> None:
    with _state_lock:
        _state["status"]      = "running"
        _state["source_json"] = analysis_json_path
        _state["error"]       = None
        _state["started_at"]  = time.strftime("%Y-%m-%dT%H:%M:%S")
        _state["finished_at"] = None

    matlab_script_dir = str(_MATLAB_DIR)

    # MATLAB -batch runs a function non-interactively and exits
    # The run_digital_twin.m must be on MATLAB's path — we cd into
    # the matlab_twin/ folder so MATLAB finds it automatically.
    cmd = [
        _MATLAB_EXE,
        "-batch",
        f"cd('{matlab_script_dir}'); run_digital_twin('{analysis_json_path}')",
        "-nojvm",        # faster startup (no desktop)
        "-nodisplay",    # headless
    ]

    logger.info("[DT Bridge] Running: %s", " ".join(cmd))

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,   # 5-minute timeout
        )
        if proc.returncode != 0:
            err = proc.stderr or proc.stdout or "MATLAB exited non-zero"
            logger.error("[DT Bridge] MATLAB failed:\n%s", err)
            with _state_lock:
                _state["status"]      = "error"
                _state["error"]       = err[:2000]  # cap
                _state["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        else:
            logger.info("[DT Bridge] MATLAB simulation finished successfully.")
            logger.debug("[DT Bridge] MATLAB stdout:\n%s", proc.stdout)
            with _state_lock:
                _state["status"]      = "done"
                _state["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")

    except subprocess.TimeoutExpired:
        logger.error("[DT Bridge] MATLAB simulation timed out after 300s.")
        with _state_lock:
            _state["status"]      = "error"
            _state["error"]       = "MATLAB simulation timed out (>300 s)."
            _state["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")

    except FileNotFoundError:
        msg = (
            f"MATLAB executable not found at '{_MATLAB_EXE}'. "
            f"Set the MATLAB_EXE environment variable to the full path of matlab.exe / matlab."
        )
        logger.error("[DT Bridge] %s", msg)
        with _state_lock:
            _state["status"]      = "error"
            _state["error"]       = msg
            _state["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
