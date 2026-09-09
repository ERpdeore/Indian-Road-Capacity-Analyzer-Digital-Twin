"""
digital_twin_engine.py
-----------------------
Pure-Python "digital twin" data generator for the web dashboard.

Why this exists
----------------
The dashboard's JS (static/app.js: dtRender / dtDrawCapChart / dtDrawSpdChart /
dtAnimateRoads) already knows how to draw the twin — capacity-over-time charts,
speed-over-time charts, and an animated ideal-road-vs-defect-road comparison.
It was built to be fed by app.py's /api/digital-twin/status endpoint, which in
turn expected a road_analyzer/digital_twin_bridge.py module that would launch
real MATLAB/Simulink (matlab_twin/roadtwin.m) and poll it for results.

That bridge module was never actually added to the repo, and — more
importantly — a cloud host like Render doesn't have a licensed MATLAB
installation available to run headless anyway. Requiring MATLAB locally to
see the twin defeats the point of a web dashboard.

This module produces the same *shape* of result using the same underlying
traffic-flow theory your MATLAB script and core.py already use elsewhere in
this project (Greenshields speed-density model, referenced throughout
core.py's pothole-penalty comments), computed directly in Python from the
numbers analyse_image() already calculated. No MATLAB, no subprocess, no
external service — it runs in milliseconds as part of the normal request.

If you later get a licensed MATLAB instance connected (e.g. via MATLAB
Engine API for Python, or a self-hosted matlab_video_service), you can swap
the call site in app.py back to that bridge without touching the frontend —
the JSON shape returned here is intentionally identical to what dtRender()
expects.
"""

import math
from typing import Optional

# Greenshields jam density (vehicles/PCU per km, per lane) for a typical
# Indian urban arterial. IRC:106 does not itself specify a jam density —
# this is a standard planning-level assumption (commonly 150-200 PCU/km/lane
# in Indian urban traffic studies) and is deliberately conservative (mid-range)
# rather than tuned to any specific corridor.
JAM_DENSITY_PCU_PER_KM_PER_LANE = 170.0

# How many seconds of "simulation" to generate for the dashboard charts.
SIM_DURATION_S = 60
SIM_STEP_S     = 2

# In-memory store for the most recently generated twin (mirrors the simple
# single-slot contract the frontend polling code already expects from
# /api/digital-twin/status and /api/digital-twin/latest).
_LATEST = {"status": "idle", "twin_data": None, "error": None}


def _greenshields_speed(density_pcu_km: float, free_flow_speed_kmh: float,
                         jam_density_pcu_km: float) -> float:
    """Greenshields linear speed-density relationship: v = v_f * (1 - k/k_j)."""
    if jam_density_pcu_km <= 0:
        return free_flow_speed_kmh
    ratio = max(0.0, min(1.0, density_pcu_km / jam_density_pcu_km))
    return free_flow_speed_kmh * (1 - ratio)


def _ramp_to_steady_state(final_value: float, t: float, tau: float = 12.0) -> float:
    """
    First-order ramp-up: value(t) = final * (1 - e^(-t/tau)).
    Models traffic building up to its steady-state flow/speed over the
    simulation window rather than jumping to it instantly — this is what
    gives the dashboard charts their curved "settling in" shape.
    """
    return final_value * (1 - math.exp(-t / tau))


def generate_twin_data(analysis_result: dict) -> dict:
    """
    Build a browser-ready twin_data payload straight from an analyse_image()
    result. Every number here traces back to values already computed by
    core.py's IRC:106-based capacity calculation — this does not introduce
    a second, independent estimate of road capacity, it only re-expresses
    the existing result as a short time series for the dashboard charts.
    """
    free_flow_speed = float(analysis_result.get("free_flow_speed_kmh") or 50.0)
    ideal_cap        = float(analysis_result.get("original_capacity_pcu_hr") or 0.0)
    defect_cap       = float(analysis_result.get("reduced_capacity_pcu_hr") or ideal_cap)
    cap_loss_pct     = float(analysis_result.get("capacity_loss_pct") or 0.0)

    traffic_regime   = analysis_result.get("traffic_regime", {}) or {}
    steady_speed     = float(traffic_regime.get("congested_speed_kmh") or free_flow_speed)

    cap_calc         = analysis_result.get("capacity_calculation", {}) or {}
    num_lanes        = max(1, int((analysis_result.get("road_config") or {}).get("num_lanes", 1)))
    worst_pothole    = cap_calc.get("worst_pothole_depth", "unknown")

    jam_density = JAM_DENSITY_PCU_PER_KM_PER_LANE * num_lanes

    # Density implied by each capacity level under Greenshields (inverse of
    # q = k * v with v = v_f * (1 - k/k_j) → solve for k at the flow closest
    # to the observed capacity, staying on the uncongested branch).
    def density_for_capacity(cap_pcu_hr: float) -> float:
        # q(k) = k * v_f * (1 - k/k_j), maximised at k = k_j/2. We only ever
        # need the uncongested-branch root (k <= k_j/2) since DSV values are
        # design (not breakdown) volumes.
        a = free_flow_speed / jam_density
        b = -free_flow_speed
        c = cap_pcu_hr
        disc = b * b - 4 * a * c
        if a == 0 or disc < 0:
            return jam_density / 4  # fallback: light-traffic density
        k = (-b - math.sqrt(disc)) / (2 * a)
        return max(0.0, min(k, jam_density / 2))

    k_ideal  = density_for_capacity(ideal_cap)
    k_defect = density_for_capacity(defect_cap)

    sim_time, ideal_series, defect_series, speed_series = [], [], [], []
    t = 0.0
    while t <= SIM_DURATION_S:
        k_i_t = _ramp_to_steady_state(k_ideal, t)
        k_d_t = _ramp_to_steady_state(k_defect, t)

        v_i_t = _greenshields_speed(k_i_t, free_flow_speed, jam_density)
        # The speed chart is ramped directly toward `steady_speed` (the
        # same congested-speed figure already computed in core.py and
        # shown in the summary card above the chart) rather than being
        # re-derived from the Greenshields density above. Those two are
        # related but not numerically identical formulas, and having the
        # chart's endpoint disagree with the number printed next to it
        # would look like a bug even though both values are individually
        # correct. Ramping toward the exact reported figure keeps the
        # chart and the summary card visually consistent.
        v_d_t = _ramp_to_steady_state(steady_speed, t) if steady_speed <= free_flow_speed \
                else free_flow_speed

        q_i_t = k_i_t * v_i_t
        q_d_t = k_d_t * v_d_t

        sim_time.append(round(t, 1))
        ideal_series.append(round(q_i_t, 1))
        defect_series.append(round(q_d_t, 1))
        speed_series.append(round(v_d_t, 1))
        t += SIM_STEP_S

    speed_reduction_pct = round(
        max(0.0, (free_flow_speed - steady_speed) / free_flow_speed * 100)
        if free_flow_speed > 0 else 0.0, 1
    )
    pothole_speed_impact_pct = speed_reduction_pct if worst_pothole not in (None, "unknown", "none") else 0.0

    twin_data = {
        "engine": "python-greenshields",  # distinguishes from a real-MATLAB run if that's added later
        "summary": {
            "ideal_capacity_pcu_hr":     round(ideal_cap, 1),
            "defect_capacity_pcu_hr":    round(defect_cap, 1),
            "ideal_volume_design_pcu":   round(ideal_cap, 1),
            "defect_volume_design_pcu":  round(defect_cap, 1),
            "steady_state_speed_kmh":    round(steady_speed, 1),
            "capacity_loss_pct":         round(cap_loss_pct, 1),
            "speed_reduction_pct":       speed_reduction_pct,
            "pothole_speed_impact_pct":  pothole_speed_impact_pct,
        },
        "simulation_time_s":       sim_time,
        "ideal_capacity_pcu_hr":   ideal_series,
        "defect_capacity_pcu_hr":  defect_series,
        "vehicle_speed_kmh":       speed_series,
    }
    return twin_data


def run_and_store(analysis_result: dict) -> dict:
    """Generate twin data and stash it as 'the latest' for the poll endpoints."""
    try:
        twin_data = generate_twin_data(analysis_result)
        _LATEST["status"]    = "done"
        _LATEST["twin_data"] = twin_data
        _LATEST["error"]     = None
        return twin_data
    except Exception as e:  # pragma: no cover - defensive, twin is a bonus view
        _LATEST["status"]    = "error"
        _LATEST["twin_data"] = None
        _LATEST["error"]     = str(e)
        raise


def get_twin_status() -> dict:
    if _LATEST["status"] == "error":
        return {"status": "error", "error": _LATEST["error"]}
    if _LATEST["status"] == "done":
        return {"status": "done", "twin_data": _LATEST["twin_data"]}
    return {"status": "idle"}


def get_latest_twin_data() -> Optional[dict]:
    return _LATEST["twin_data"]
