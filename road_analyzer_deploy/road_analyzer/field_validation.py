"""
road_analyzer.field_validation
==============================
Field capacity from a video survey and comparison with the dashboard.
Methods A and B follow Indo-HCM 2017 Chapter 5 (Annexures 5C-5E); method C
is a standard traffic-flow method not given in the manual.

Survey (Annex 5C/5D)
--------------------
* Trap of 50-75 m on a straight mid-block (5.3), boundaries marked before
  filming, camera covering the trap.
* For every vehicle: type, time entering and leaving the trap
  -> travel time t; speed = D / t.
* Classified counts in 5-minute periods (Annex 5D).

Three ways to field capacity
----------------------------
A. Operating speed (5.4.5, Eq. 5.4) — divided roads; needs a period
   light enough for >= 100 cars to have headway > 8 s:
       85th percentile speed of free cars (headway > 8 s), >= 100 cars
       C = (20.11 V + 210.8) x lanes
B. Speed-flow fit (Annex 5E.4, Greenshields) — the method Indo-HCM used for
   Table 5.4. Needs 5-min periods covering low AND high flows:
       q = 12 x (5-min PCU),  v = space-mean speed (Eq. 5E.2),  k = q / v
       fit v = v_f - (v_f / k_j) k  ->  C = v_f k_j / 4
C. Queue discharge (standard traffic-flow method, NOT from Indo-HCM) —
   counts PAST an obstruction while a queue stands behind it equal that
   section's capacity: C = mean(12 x 5-min PCU in queue).
Volume counted without a queue is demand, not capacity, and is used only
for V/C and LOS.

CSV formats (templates in docs/field_templates/)
------------------------------------------------
vehicles.csv : vehicle_type, t_entry_s, t_exit_s     (video clock, seconds)
"""

from __future__ import annotations

import csv
import math
from collections import defaultdict
from typing import Dict, List, Optional, Sequence

from road_analyzer import indo_hcm as hcm

TRAP_RANGE_M = (50.0, 75.0)       # Section 5.3 (Annex 5C used 60-75 m)
INTERVAL_S = 300                  # 5-minute periods (Annex 5D/5E.1)


# ------------------------------------------------------------------
# Loading and per-vehicle speeds
# ------------------------------------------------------------------
def load_vehicles(path: str) -> List[dict]:
    rows = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            vt = r["vehicle_type"].strip().lower()
            if vt not in hcm.VEHICLE_TYPES:
                raise ValueError(f"Unknown vehicle_type '{vt}'. Use one of {hcm.VEHICLE_TYPES}")
            t_in, t_out = float(r["t_entry_s"]), float(r["t_exit_s"])
            if t_out <= t_in:
                raise ValueError(f"t_exit_s must be after t_entry_s (row {r})")
            rows.append({"type": vt, "t_in": t_in, "t_out": t_out})
    rows.sort(key=lambda x: x["t_in"])
    return rows


def add_speeds_and_headways(vehicles: List[dict], trap_m: float) -> List[dict]:
    """Speed over the trap and time headway at the trap entry line to the
    vehicle ahead (any type), in entry order."""
    prev = None
    for v in vehicles:
        v["travel_time_s"] = v["t_out"] - v["t_in"]
        v["speed_kmh"] = trap_m / v["travel_time_s"] * 3.6
        v["headway_s"] = (v["t_in"] - prev) if prev is not None else None
        prev = v["t_in"]

    return vehicles


# ------------------------------------------------------------------
# A. Operating speed -> Eq. 5.4
# ------------------------------------------------------------------
def capacity_from_operating_speed(vehicles: List[dict], road_type: str) -> dict:
    rt = hcm.ROAD_TYPES[road_type]
    cars = [v for v in vehicles if v["type"] == "car"]
    op = hcm.operating_speed([c["speed_kmh"] for c in cars], [c["headway_s"] for c in cars])
    out = {"method": "A: operating speed + Eq. 5.4", **op}
    if op["operating_speed_kmh"] is None:
        out["capacity_pcu_h"] = None
        return out
    if not rt["divided"]:
        out["capacity_pcu_h"] = None
        out["warning"] = ("Eq. 5.4 applies to divided roads only; use method B for a two-lane "
                          "undivided road.")
        return out
    out["lane_capacity_pcu_h"] = hcm.lane_capacity_from_operating_speed(op["operating_speed_kmh"])
    out["capacity_pcu_h"] = out["lane_capacity_pcu_h"] * rt["lanes"]
    return out


# ------------------------------------------------------------------
# 5-minute periods: PCU flow and space-mean speed
# ------------------------------------------------------------------
def five_minute_periods(vehicles: List[dict], road_type: str, trap_m: float,
                        pcu_method: str = "table") -> List[dict]:
    """pcu_method: 'table' (Table 5.3 medians) or 'se' (Eq. 5.2/5.3)."""
    if not vehicles:
        return []
    t0 = vehicles[0]["t_in"]
    t_end = vehicles[-1]["t_in"]
    bins: Dict[int, List[dict]] = defaultdict(list)
    for v in vehicles:
        bins[int((v["t_in"] - t0) // INTERVAL_S)].append(v)
    # Drop a final period the data does not fully cover: scaling a partial
    # 5-min count by 12 would create a false low-flow point.
    last = max(bins)
    if t0 + (last + 1) * INTERVAL_S > t_end + 1e-9 and len(bins) > 1:
        bins.pop(last)
    divided = hcm.ROAD_TYPES[road_type]["divided"]
    out = []
    for i in sorted(bins):
        vs = bins[i]
        counts = defaultdict(int)
        for v in vs:
            counts[v["type"]] += 1
        veh_h = {k: n * 3600 / INTERVAL_S for k, n in counts.items()}
        if pcu_method == "se":
            shares, n = hcm.se_shares(veh_h)
            q = hcm.stream_equivalency_factor(divided, shares, n) * n
        else:
            q = hcm.flow_pcu(veh_h, road_type)["flow_pcu_h"]
        sms = hcm.space_mean_speed(trap_m, [v["travel_time_s"] for v in vs])
        out.append({"period": i, "start_s": t0 + i * INTERVAL_S, "vehicles": len(vs),
                    "flow_pcu_h": q, "sms_kmh": sms, "density_pcu_km": q / sms})
    return out


# ------------------------------------------------------------------
# B. Greenshields speed-flow (Annex 5E.4)
# ------------------------------------------------------------------
def greenshields_fit(periods: List[dict]) -> dict:
    """Least squares v = a + b k on (density, SMS); v_f = a, k_j = -a/b,
    capacity = v_f k_j / 4 at critical speed v_f / 2."""
    ks = [p["density_pcu_km"] for p in periods]
    vs = [p["sms_kmh"] for p in periods]
    n = len(ks)
    if n < 6:
        return {"method": "B: Greenshields", "capacity_pcu_h": None,
                "warning": f"Only {n} five-minute periods; a speed-flow fit needs many more, "
                           f"covering low and high flows."}
    mk, mv = sum(ks) / n, sum(vs) / n
    sxx = sum((k - mk) ** 2 for k in ks)
    sxy = sum((k - mk) * (v - mv) for k, v in zip(ks, vs))
    if sxx == 0:
        return {"method": "B: Greenshields", "capacity_pcu_h": None, "warning": "No spread in density."}
    b = sxy / sxx
    a = mv - b * mk
    ss_tot = sum((v - mv) ** 2 for v in vs)
    ss_res = sum((v - (a + b * k)) ** 2 for k, v in zip(ks, vs))
    r2 = 1 - ss_res / ss_tot if ss_tot else 0.0
    out = {"method": "B: Greenshields", "free_speed_kmh": a, "slope": b, "r2": r2, "periods": n}
    if b >= 0:
        out.update(capacity_pcu_h=None, warning="Speed does not fall with density in this data; "
                   "flows never approached capacity, so capacity cannot be identified.")
        return out
    kj = -a / b
    cap = a * kj / 4
    q_max = max(p["flow_pcu_h"] for p in periods)
    out.update(jam_density_pcu_km=kj, critical_speed_kmh=a / 2, capacity_pcu_h=cap,
               max_observed_flow_pcu_h=q_max)
    if q_max < 0.6 * cap:
        out["warning"] = (f"Highest observed flow is {q_max:.0f} PCU/h, only "
                          f"{q_max / cap * 100:.0f}% of the fitted capacity: the estimate is a long "
                          f"extrapolation and weak.")
    if r2 < 0.5:
        out["warning"] = (out.get("warning", "") + f" R² = {r2:.2f} is low.").strip()
    return out


# ------------------------------------------------------------------
# C. Queue discharge
# ------------------------------------------------------------------
def capacity_from_queue_discharge(periods_in_queue: List[dict]) -> dict:
    """Pass ONLY the 5-min periods during which a queue stood upstream of
    the counting line the whole time."""
    if not periods_in_queue:
        return {"method": "C: queue discharge", "capacity_pcu_h": None, "warning": "No queued periods."}
    q = [p["flow_pcu_h"] for p in periods_in_queue]
    m = sum(q) / len(q)
    sd = (sum((x - m) ** 2 for x in q) / (len(q) - 1)) ** 0.5 if len(q) > 1 else 0.0
    return {"method": "C: queue discharge", "capacity_pcu_h": m, "sd_pcu_h": sd, "periods": len(q)}


# ------------------------------------------------------------------
# Comparison with the dashboard
# ------------------------------------------------------------------
def capacity_loss_pct(c_clear: float, c_obstructed: float) -> float:
    return (c_clear - c_obstructed) / c_clear * 100


def error_metrics(predicted: Sequence[float], observed: Sequence[float]) -> dict:
    """MAPE, RMSE and mean signed error (bias = predicted - observed)."""
    pairs = [(p, o) for p, o in zip(predicted, observed) if o not in (0, None) and p is not None]
    if not pairs:
        raise ValueError("No valid predicted/observed pairs.")
    n = len(pairs)
    err = [p - o for p, o in pairs]
    return {"n": n,
            "mape_pct": sum(abs(e) / abs(o) for e, (_, o) in zip(err, pairs)) / n * 100,
            "rmse": (sum(e * e for e in err) / n) ** 0.5,
            "bias": sum(err) / n,
            "note": "n < 10 sites is a pilot validation, not a calibration." if n < 10 else None}


def analyse_site(vehicles_csv: str, trap_m: float, road_type: str, pcu_method: str = "table") -> dict:
    """Everything a single survey video gives: operating speed + Eq. 5.4
    capacity, 5-min PCU flows, Greenshields capacity, and peak flow."""
    warnings = []
    if trap_m <= 0:
        raise ValueError("trap_m must be > 0.")
    if not (TRAP_RANGE_M[0] <= trap_m <= TRAP_RANGE_M[1]):
        warnings.append(f"Trap length {trap_m:g} m is outside the 50-75 m used by Indo-HCM (5.3).")
    v = add_speeds_and_headways(load_vehicles(vehicles_csv), trap_m)
    periods = five_minute_periods(v, road_type, trap_m, pcu_method)
    return {"road_type": road_type, "trap_m": trap_m, "vehicles": len(v), "warnings": warnings,
            "method_A": capacity_from_operating_speed(v, road_type),
            "method_B": greenshields_fit(periods),
            "peak_5min_flow_pcu_h": max((p["flow_pcu_h"] for p in periods), default=None),
            "periods": periods}


if __name__ == "__main__":   # python -m road_analyzer.field_validation vehicles.csv 60 divided_4lane
    import json
    import sys
    if len(sys.argv) < 4:
        print(__doc__)
        sys.exit(1)
    res = analyse_site(sys.argv[1], float(sys.argv[2]), sys.argv[3],
                       sys.argv[4] if len(sys.argv) > 4 else "table")
    res.pop("periods")
    print(json.dumps(res, indent=2, default=lambda x: round(x, 2) if isinstance(x, float) else str(x)))
