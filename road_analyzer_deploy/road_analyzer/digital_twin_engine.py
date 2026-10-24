"""
road_analyzer.digital_twin_engine
=================================
Macroscopic digital twin of the surveyed section: ideal road vs the same
road with the detected obstructions, under the same traffic demand.

Model
-----
1. Fundamental diagram (Greenshields, q = k v, v = v_f (1 - k/k_j)) for
   each state, calibrated so its maximum flow equals the Indo-HCM capacity
   computed in core.py:
       ideal  : v_f = operating speed,            q_max = C0  -> k_j = 4 C0 / v_f
       defect : v_f' = v_f (1 - pothole reduction), q_max = C  -> k_j' = 4 C / v_f'
2. Demand q: the observed volume if the user entered one, otherwise the
   LOS-C design service volume of the ideal road (0.70 C0). The source
   used is always stated in the output.
3. If q <= capacity: the section runs uncongested; speed and density come
   from the uncongested branch of its fundamental diagram.
   If q > capacity: the section is a bottleneck discharging at C.
   Deterministic queueing gives the stored queue n(t) = (q - C) t and the
   LWR shockwave between arriving traffic (q, k_A) and the queue
   (C, k_Q on the congested branch of the upstream diagram) gives the
   physical queue length growth w = (C - q) / (k_Q - k_A).

What this replaces: a 60-second "capacity over time" ramp that started
from zero and approached the IRC value through an arbitrary 12 s lag.
Capacity is a property of the road, not something that builds up over
a minute, so that chart had no physical meaning.
"""

from __future__ import annotations

import math
from typing import Optional

from road_analyzer import indo_hcm as hcm

HORIZON_MIN = 60
STEP_MIN = 2
FD_POINTS = 25

_LATEST = {"twin_data": None}


def _v_uncongested(q: float, vf: float, qmax: float) -> float:
    q = min(max(q, 0.0), qmax)
    return vf * (1 + math.sqrt(max(0.0, 1 - q / qmax))) / 2


def _v_congested(q: float, vf: float, qmax: float) -> float:
    q = min(max(q, 0.0), qmax)
    return vf * (1 - math.sqrt(max(0.0, 1 - q / qmax))) / 2


def _state(name: str, demand: float, cap: float, vf: float, upstream_cap: float,
           upstream_vf: float, lanes: int) -> dict:
    kj = 4 * cap / vf
    out = {"name": name, "capacity_pcu_h": round(cap, 1), "free_flow_speed_kmh": round(vf, 1),
           "jam_density_pcu_km": round(kj, 1), "vc_ratio": round(demand / cap, 3) if cap else None}
    if demand <= cap:
        v = _v_uncongested(demand, vf, cap)
        k = demand / v if v > 0 else 0.0
        out.update(state="uncongested", section_speed_kmh=round(v, 1),
                   section_density_pcu_km=round(k, 1),
                   section_density_pcu_km_lane=round(k / lanes, 1),
                   upstream_speed_kmh=round(_v_uncongested(demand, upstream_vf, upstream_cap), 1),
                   queue_growth_pcu_h=0.0, shockwave_kmh=0.0)
        return out
    # Bottleneck: discharges at capacity, queue builds upstream.
    v_cap = vf / 2
    k_A = demand / _v_uncongested(min(demand, upstream_cap), upstream_vf, upstream_cap)
    v_Q = _v_congested(cap, upstream_vf, upstream_cap)
    k_Q = cap / v_Q if v_Q > 0 else 4 * upstream_cap / upstream_vf
    w = (cap - demand) / (k_Q - k_A) if k_Q > k_A else 0.0  # km/h, negative = moves upstream
    out.update(state="queue forming upstream", section_speed_kmh=round(v_cap, 1),
               section_density_pcu_km=round(cap / v_cap, 1),
               section_density_pcu_km_lane=round(cap / v_cap / lanes, 1),
               upstream_speed_kmh=round(v_Q, 1),
               upstream_queue_density_pcu_km_lane=round(k_Q / lanes, 1),
               queue_growth_pcu_h=round(demand - cap, 1), shockwave_kmh=round(w, 2))
    return out


def generate_twin_data(result: dict) -> dict:
    c0 = float(result["base_capacity_pcu_h"])
    c = float(result["reduced_capacity_pcu_h"])
    basis = result.get("capacity_basis") or {}
    v0 = float(basis.get("operating_speed_kmh") or result.get("operating_speed_kmh") or 50.0)
    lanes = int((result.get("road_config") or {}).get("num_lanes") or 2)
    pothole = (result.get("capacity_calculation") or {}).get("worst_pothole_size")
    r = hcm.POTHOLE_SPEED_REDUCTION.get(pothole, 0.0) if pothole else 0.0
    vf_def = v0 * (1 - r)

    los = result.get("level_of_service") or {}
    if los.get("observed_volume_pcu_h"):
        demand, demand_src = float(los["observed_volume_pcu_h"]), "observed volume entered by user"
    else:
        demand = c0 * hcm.DSV_VC_RATIO
        demand_src = "ASSUMED: LOS-C design service volume of the ideal road (0.70 x C0)"

    warnings = []
    if demand > c0:
        warnings.append("Entered volume exceeds the base capacity C0 — check the count, its "
                        "direction basis (one direction vs both) or the road type.")
    ideal = _state("ideal", demand, c0, v0, c0, v0, lanes)
    defect = _state("defect", demand, c, vf_def, c0, v0, lanes)

    times = list(range(0, HORIZON_MIN + 1, STEP_MIN))
    def series(st):
        g = st["queue_growth_pcu_h"]
        w = abs(st["shockwave_kmh"])
        return ([round(g * t / 60, 1) for t in times], [round(w * t / 60 * 1000, 1) for t in times])
    qi, li = series(ideal)
    qd, ld = series(defect)

    T = HORIZON_MIN / 60
    for st in (ideal, defect):
        g = st["queue_growth_pcu_h"]
        st["queue_after_horizon_pcu"] = round(g * T, 1)
        st["queue_length_after_horizon_m"] = round(abs(st["shockwave_kmh"]) * T * 1000, 1)
        # mean delay of vehicles arriving during the horizon, deterministic queue
        st["mean_queue_delay_min"] = round((g * T / (2 * demand)) * 60, 1) if g > 0 else 0.0

    def fd(cap, vf):
        flows = [cap * i / (FD_POINTS - 1) for i in range(FD_POINTS)]
        return {"flow_pcu_h": [round(q, 1) for q in flows],
                "speed_kmh": [round(_v_uncongested(q, vf, cap), 2) for q in flows]}

    return {
        "engine": "python-macroscopic (Greenshields FD + deterministic queue + LWR shockwave)",
        "demand_pcu_h": round(demand, 1),
        "demand_source": demand_src,
        "horizon_min": HORIZON_MIN,
        "ideal": ideal,
        "defect": defect,
        "capacity_loss_pct": result.get("capacity_loss_pct"),
        "time_min": times,
        "queue_pcu": {"ideal": qi, "defect": qd},
        "queue_length_m": {"ideal": li, "defect": ld},
        "speed_flow": {"ideal": fd(c0, v0), "defect": fd(c, vf_def)},
        "warnings": warnings,
        "assumptions": [
            "Greenshields single-regime fundamental diagram, calibrated to Indo-HCM capacity.",
            "Constant demand over the horizon; no demand diversion to other routes.",
            f"Pothole speed reduction {r*100:.0f}% (project assumption, indo_hcm.POTHOLE_SPEED_REDUCTION).",
            demand_src,
        ],
    }


def run_and_store(result: dict) -> dict:
    twin = generate_twin_data(result)
    _LATEST["twin_data"] = twin
    return twin


def get_latest_twin_data() -> Optional[dict]:
    return _LATEST["twin_data"]
