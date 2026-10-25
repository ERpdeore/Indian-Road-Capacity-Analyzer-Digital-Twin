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
       ideal  : v_f = operating speed,                 q_max = C0 -> k_j = 4 C0 / v_f
       defect : v_f' = v_f x roughness speed ratio,  q_max = C  -> k_j' = 4 C / v_f'
   Indo-HCM itself uses Greenshields for its speed-flow capacities (Annex 5E.4).
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
    if qmax <= 0:
        return 0.0
    q = min(max(q, 0.0), qmax)
    return vf * (1 + math.sqrt(max(0.0, 1 - q / qmax))) / 2


def _v_congested(q: float, vf: float, qmax: float) -> float:
    if qmax <= 0:
        return 0.0
    q = min(max(q, 0.0), qmax)
    return vf * (1 - math.sqrt(max(0.0, 1 - q / qmax))) / 2


def _state(name: str, arrival: float, cap: float, vf: float, upstream_cap: float,
           upstream_vf: float, lanes: int) -> dict:
    """arrival <= upstream_cap always (the road upstream cannot deliver more
    than its own capacity)."""
    out = {"name": name, "capacity_pcu_h": round(cap, 1), "free_flow_speed_kmh": round(vf, 1),
           "jam_density_pcu_km": round(4 * cap / vf, 1) if vf > 0 else None,
           "vc_ratio": round(arrival / cap, 3) if cap > 0 else None}
    if cap > 0 and arrival <= cap:
        v = _v_uncongested(arrival, vf, cap)
        k = arrival / v if v > 0 else 0.0
        out.update(state="uncongested", section_speed_kmh=round(v, 1),
                   section_density_pcu_km=round(k, 1),
                   section_density_pcu_km_lane=round(k / lanes, 1),
                   upstream_speed_kmh=round(_v_uncongested(arrival, upstream_vf, upstream_cap), 1),
                   queue_growth_pcu_h=0.0, shockwave_kmh=0.0)
        return out
    # Bottleneck: discharges at C (0 if fully blocked); queue builds upstream.
    # Arriving traffic: uncongested branch of the upstream diagram at q_A.
    # Queue: congested branch of the upstream diagram at q = C.
    # Shockwave (LWR): w = (C - q_A) / (k_Q - k_A), negative = tail moves upstream.
    k_A = arrival / _v_uncongested(arrival, upstream_vf, upstream_cap)
    v_Q = _v_congested(cap, upstream_vf, upstream_cap)
    k_Q = cap / v_Q if v_Q > 0 else 4 * upstream_cap / upstream_vf   # jam density when C = 0
    w = (cap - arrival) / (k_Q - k_A)
    v_sec = vf / 2 if cap > 0 else 0.0
    out.update(state="queue forming upstream" if cap > 0 else "fully blocked",
               section_speed_kmh=round(v_sec, 1),
               section_density_pcu_km=round(cap / v_sec, 1) if v_sec > 0 else None,
               section_density_pcu_km_lane=round(cap / v_sec / lanes, 1) if v_sec > 0 else None,
               upstream_speed_kmh=round(v_Q, 1),
               upstream_queue_density_pcu_km_lane=round(k_Q / lanes, 1),
               queue_growth_pcu_h=round(arrival - cap, 1), shockwave_kmh=round(w, 2))
    return out


def generate_twin_data(result: dict) -> dict:
    c0 = float(result["base_capacity_pcu_h"])
    c = max(0.0, float(result["reduced_capacity_pcu_h"]))
    basis = result.get("capacity_basis") or {}
    v0 = float(basis.get("operating_speed_kmh") or result.get("operating_speed_kmh") or 50.0)
    lanes = int((result.get("road_config") or {}).get("num_lanes") or 2)
    rough = (result.get("capacity_calculation") or {}).get("roughness") or {}
    speed_ratio = float(rough.get("speed_ratio") or 1.0)   # < 1 only when IRI was measured
    vf_def = v0 * speed_ratio

    los = result.get("level_of_service") or {}
    if los.get("observed_volume_pcu_h"):
        demand, demand_src = float(los["observed_volume_pcu_h"]), "observed volume entered by user"
    else:
        demand = c0 * hcm.DSV_VC_RATIO
        demand_src = "ASSUMED: design service volume of the ideal road (0.70 x C0, Table 5.4)"

    warnings = []
    arrival = demand
    if demand > c0:
        arrival = c0
        warnings.append(f"Entered volume {demand:.0f} PCU/h exceeds the Indo-HCM base capacity "
                        f"{c0:.0f} PCU/h. Either the count is on a different direction basis, or the "
                        f"site carries more than Table 5.4 assumes (measure the operating speed). "
                        f"The twin caps arriving flow at C0.")
    if c <= 0:
        warnings.append("Usable width is zero: the section is fully blocked in this model.")
    ideal = _state("ideal", arrival, c0, v0, c0, v0, lanes)
    defect = _state("defect", arrival, c, vf_def, c0, v0, lanes)

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
        cap = st["capacity_pcu_h"]
        st["queue_after_horizon_pcu"] = round(g * T, 1)
        st["queue_length_after_horizon_m"] = round(abs(st["shockwave_kmh"]) * T * 1000, 1)
        # Deterministic queue: a vehicle arriving at t waits (q_A - C) t / C;
        # mean over arrivals in [0, T] = (q_A - C) T / (2 C).
        if g <= 0:
            st["mean_queue_delay_min"] = 0.0
        elif cap > 0:
            st["mean_queue_delay_min"] = round(g * T / (2 * cap) * 60, 1)
        else:
            st["mean_queue_delay_min"] = None    # nothing is discharged

    def fd(cap, vf):
        if cap <= 0:
            return {"flow_pcu_h": [0.0], "speed_kmh": [0.0]}
        flows = [cap * i / (FD_POINTS - 1) for i in range(FD_POINTS)]
        return {"flow_pcu_h": [round(q, 1) for q in flows],
                "speed_kmh": [round(_v_uncongested(q, vf, cap), 2) for q in flows]}

    return {
        "engine": "python-macroscopic (Greenshields FD + deterministic queue + LWR shockwave)",
        "demand_pcu_h": round(demand, 1),
        "arrival_pcu_h": round(arrival, 1),
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
            "Greenshields single-regime fundamental diagram, calibrated to Indo-HCM capacity "
            "(the model Indo-HCM Annex 5E.4 uses).",
            "Constant demand over the horizon; no diversion to other routes.",
            (f"Free-flow speed on the current road reduced to {speed_ratio*100:.0f}% by measured roughness "
             f"(extensions.roughness_factor)." if speed_ratio < 1 else
             "Obstructions reduce capacity through width; free-flow speed is unchanged (no IRI measured)."),
            f"Operating speed {v0:.1f} km/h: {basis.get('operating_speed_source', '')}.",
            demand_src,
        ],
    }


def run_and_store(result: dict) -> dict:
    twin = generate_twin_data(result)
    _LATEST["twin_data"] = twin
    return twin


def get_latest_twin_data() -> Optional[dict]:
    return _LATEST["twin_data"]
