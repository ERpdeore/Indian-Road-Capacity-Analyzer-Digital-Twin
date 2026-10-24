"""
road_analyzer.indo_hcm
======================
Indo-HCM 2017 (CSIR-CRRI), Chapter 5 "Urban Roads" — and nothing else.

Every constant below carries the table / equation / section it comes from.
Nothing in this module is a project assumption; the project's own
extensions live in road_analyzer/extensions.py.

Scope (Section 5.1)
-------------------
* Urban road SEGMENTS: mid-block between controlled intersections, signals
  at least 1 km apart.
* Road types: two-lane undivided, and 4/6/8/10-lane divided (5.1.2).
  No one-way, no 4-lane undivided, no intersections (Chapter 6 covers those).
* Plain terrain only (Table 5B.1; no rolling/mountainous sections studied).

Method (Fig. 5.2)
-----------------
1. Flow in PCU/h      — dynamic PCU medians (Tables 5.2, 5.3), dynamic PCU
                         from speeds (Eq. 5E.4), or Se (Eq. 5.1-5.3)
2. Base capacity C0   — Table 5.4, or Eq. 5.4 from the operating speed of
                         cars measured on a BASE section (divided roads only)
3. Actual capacity    — C = C0 x F_OP x F_BS x F_AC            (Eq. 5.5)
4. LOS                — V/C and % of FFS bands (Tables 5.6, 5.7)
5. Design Service Volume = capacity at LOS-C = 0.70 C          (Table 5.4)

Advantages: calibrated on 68 sections in 10 Indian metro cities with mixed,
lane-less traffic; needs only width + side-friction description, or a car
free-speed survey.
Limitations (read before citing):
* Values are national medians; Table 5.1 shows small samples (2 base
  sections for two-lane undivided, 3 for ten-lane).
* 8- and 10-lane values only apply where signal spacing is 1-3 km (5.4.4.2).
* Eq. 5.4 is valid for base sections, divided roads, 40-80 km/h only.
* Side friction is limited to on-street parking, bus stops and access
  points; there are no factors for vendors, encroachment, potholes,
  pedestrians, roughness or work zones on urban roads.
* Known misprints in the printed manual (checked against its own data):
  Example 5.5.1 dynamic-PCU total is printed as 3153 PCU/h but its column
  sums to ~3214; several examples cite the wrong table numbers; 5.4.7.1
  refers to "Table 5.8/5.9" for parking where Tables 5.9/5.10 are meant.
"""

from __future__ import annotations

import math
from typing import Dict, Iterable, List, Optional, Sequence

SOURCE = "Indo-HCM 2017 (CSIR-CRRI), Chapter 5 Urban Roads"

# ------------------------------------------------------------------
# Section 5.1.2 — geometry
# ------------------------------------------------------------------
LANE_WIDTH_M = 3.5
KERB_SHYNESS_M = 0.25           # on either edge of the carriageway
PAVED_WIDTH_TOLERANCE_M = 0.5   # Table 5B.1 note

# ------------------------------------------------------------------
# Table 5.4 — capacity and DSV of base sections.
# Analysis unit: undivided = both directions; divided = ONE direction.
# paved_width_m: Table 5B.1 paved width (per direction for divided).
# ref_width_m: Section 5.1.2 width incl. 0.25 m shyness each edge.
# ------------------------------------------------------------------
ROAD_TYPES: Dict[str, dict] = {
    "undivided_2lane": {
        "label": "Two-lane undivided", "lanes": 2, "divided": False,
        "basis": "both directions", "paved_width_m": 7.0, "ref_width_m": 7.5,
        "paved_width_range_m": (6.0, 11.0),
        "capacity_pcu_h": 2400, "lane_capacity_pcu_h": 1200, "dsv_pcu_h": 1680,
    },
    "divided_4lane": {
        "label": "Four-lane divided", "lanes": 2, "divided": True,
        "basis": "one direction", "paved_width_m": 7.0, "ref_width_m": 7.5,
        "capacity_pcu_h": 2700, "lane_capacity_pcu_h": 1350, "dsv_pcu_h": 1890,
    },
    "divided_6lane": {
        "label": "Six-lane divided", "lanes": 3, "divided": True,
        "basis": "one direction", "paved_width_m": 10.5, "ref_width_m": 11.0,
        "capacity_pcu_h": 4200, "lane_capacity_pcu_h": 1400, "dsv_pcu_h": 2940,
    },
    "divided_8lane": {
        "label": "Eight-lane divided", "lanes": 4, "divided": True,
        "basis": "one direction", "paved_width_m": 14.0, "ref_width_m": 14.5,
        "capacity_pcu_h": 6800, "lane_capacity_pcu_h": 1700, "dsv_pcu_h": 4760,
        "condition": "Valid only where signal spacing is 1-3 km (Section 5.4.4.2).",
    },
    "divided_10lane": {
        "label": "Ten-lane divided", "lanes": 5, "divided": True,
        "basis": "one direction", "paved_width_m": 17.5, "ref_width_m": 18.0,
        "capacity_pcu_h": 10000, "lane_capacity_pcu_h": 2000, "dsv_pcu_h": 7000,
        "condition": "Valid only where signal spacing is 1-3 km (Section 5.4.4.2).",
    },
}
DSV_VC_RATIO = 0.70   # every row of Table 5.4: DSV / capacity = 0.70 (LOS-C)


def check_road_width(road_type: str, paved_width_m: float) -> Optional[str]:
    """Table 5B.1: paved width per direction (divided) must be within ±0.5 m
    of the class width; undivided paved width 6.0-11 m (study covered > 7.0 m).
    Returns a warning string, or None if the width fits the class."""
    rt = ROAD_TYPES[road_type]
    if rt["divided"]:
        lo = rt["paved_width_m"] - PAVED_WIDTH_TOLERANCE_M
        hi = rt["paved_width_m"] + PAVED_WIDTH_TOLERANCE_M
        if not (lo <= paved_width_m <= hi):
            return (f"Paved width {paved_width_m:g} m per direction is outside {lo:g}-{hi:g} m for a "
                    f"{rt['label'].lower()} road (Table 5B.1). Indo-HCM gives no capacity for "
                    f"intermediate widths; check the road type.")
        return None
    lo, hi = rt["paved_width_range_m"]
    if not (lo <= paved_width_m <= hi):
        return (f"Paved width {paved_width_m:g} m is outside {lo:g}-{hi:g} m for a two-lane "
                f"undivided road (Table 5B.1).")
    if paved_width_m < 7.0:
        return "Indo-HCM studied undivided widths above 7.0 m only (Table 5B.1); result is an extrapolation."
    return None


# ------------------------------------------------------------------
# Eq. 5.4 / Table 5.5 — lane capacity from operating speed
# ------------------------------------------------------------------
SPEED_MODEL_A = 20.11
SPEED_MODEL_B = 210.8
SPEED_MODEL_RANGE_KMH = (40.0, 80.0)
MIN_FREE_CAR_SAMPLE = 100          # Section 5.4.5
FREE_FLOW_HEADWAY_S = 8.0          # Section 5.2.2 / Annex 5E.5


def lane_capacity_from_operating_speed(v_kmh: float) -> float:
    """Eq. 5.4: C_lane = 20.11 V + 210.8  (PCU/h/lane)."""
    return SPEED_MODEL_A * float(v_kmh) + SPEED_MODEL_B


def operating_speed_from_lane_capacity(c_lane: float) -> float:
    """Inverse of Eq. 5.4 (used only to express a Table 5.4 value as the
    operating speed it corresponds to)."""
    return (float(c_lane) - SPEED_MODEL_B) / SPEED_MODEL_A


def base_capacity(road_type: str, operating_speed_kmh: Optional[float] = None) -> dict:
    """
    C0 for one analysis unit.
      * divided road + operating speed measured on a BASE section
            -> Eq. 5.4 x lanes per direction   (site-specific, preferred by 5.4.5)
      * otherwise -> Table 5.4
    Two-lane undivided roads have no speed model: Table 5.4 only.
    """
    rt = ROAD_TYPES[road_type]
    notes: List[str] = []
    if rt.get("condition"):
        notes.append(rt["condition"])
    if operating_speed_kmh and not rt["divided"]:
        notes.append("Eq. 5.4 applies to divided roads only; Table 5.4 used for two-lane undivided.")
        operating_speed_kmh = None
    if operating_speed_kmh:
        lo, hi = SPEED_MODEL_RANGE_KMH
        if not (lo <= operating_speed_kmh <= hi):
            notes.append(f"Operating speed {operating_speed_kmh:g} km/h is outside the {lo:g}-{hi:g} km/h "
                         f"validity of Eq. 5.4 (extrapolated).")
        lane_c = lane_capacity_from_operating_speed(operating_speed_kmh)
        return {"c0_pcu_h": lane_c * rt["lanes"], "lane_capacity_pcu_h": lane_c,
                "method": "Eq. 5.4", "operating_speed_kmh": float(operating_speed_kmh),
                "detail": f"C_lane = {SPEED_MODEL_A} x {operating_speed_kmh:g} + {SPEED_MODEL_B} = "
                          f"{lane_c:.0f} PCU/h/lane x {rt['lanes']} lanes",
                "notes": notes}
    return {"c0_pcu_h": float(rt["capacity_pcu_h"]), "lane_capacity_pcu_h": float(rt["lane_capacity_pcu_h"]),
            "method": "Table 5.4", "operating_speed_kmh": None,
            "detail": f"Table 5.4, {rt['label']} ({rt['basis']})", "notes": notes}


# ------------------------------------------------------------------
# Eq. 5.5, Tables 5.9-5.12 — side-friction adjustment factors
# ------------------------------------------------------------------
PARKING_FACTORS: Dict[str, dict] = {
    "none":      {"label": "No on-street parking", "factor": 1.00, "table": "-"},
    "len_lt25":  {"label": "Long-term parking, < 25% of segment length", "factor": 0.70, "table": "5.9 Low"},
    "len_25_50": {"label": "Long-term parking, 25–50% of segment length", "factor": 0.65, "table": "5.9 Medium"},
    "len_gt50":  {"label": "Long-term parking, > 50% of segment length", "factor": 0.40, "table": "5.9 Severe"},
    "man_le500": {"label": "Short-term parking, ≤ 500 manoeuvres/km/h", "factor": 0.65, "table": "5.10 Low"},
    "man_gt500": {"label": "Short-term parking, > 500 manoeuvres/km/h", "factor": 0.40, "table": "5.10 High"},
}
BUS_STOP_FACTORS: Dict[str, dict] = {
    "none":          {"label": "No bus stop on segment", "factor": 1.00, "table": "-"},
    "kerbside_low":  {"label": "Kerbside stop, ≤ 30 buses/h", "factor": 0.80, "table": "5.11"},
    "kerbside_high": {"label": "Kerbside stop, > 30 buses/h", "factor": 0.60, "table": "5.11"},
    "bay_low":       {"label": "Bus bay, ≤ 30 buses/h", "factor": 0.90, "table": "5.11"},
    "bay_high":      {"label": "Bus bay, > 30 buses/h", "factor": 0.80, "table": "5.11"},
}
ACCESS_FACTORS: Dict[str, dict] = {
    "none":    {"label": "No access points", "factor": 1.00, "table": "-"},
    "lt200":   {"label": "Access traffic < 200 veh/h (entry + exit)", "factor": 0.90, "table": "5.12 Low"},
    "200_500": {"label": "Access traffic 200–500 veh/h", "factor": 0.80, "table": "5.12 Medium"},
    "gt500":   {"label": "Access traffic > 500 veh/h", "factor": 0.70, "table": "5.12 High"},
}
FACTOR_TABLES = {"on_street_parking": PARKING_FACTORS, "bus_stop": BUS_STOP_FACTORS,
                 "access_points": ACCESS_FACTORS}


def parking_class_by_length(occupied_m: float, segment_m: float) -> str:
    """Table 5.9 (long-term parking): share of segment length occupied."""
    pct = occupied_m / segment_m * 100
    return "len_lt25" if pct < 25 else ("len_25_50" if pct <= 50 else "len_gt50")


def parking_class_by_manoeuvres(manoeuvres_per_h: float, segment_km: float) -> str:
    """Table 5.10 (short-term parking): park-in and park-out each count as one."""
    return "man_le500" if manoeuvres_per_h / segment_km <= 500 else "man_gt500"


def factor(table_name: str, key: Optional[str]) -> float:
    table = FACTOR_TABLES[table_name]
    key = key or "none"
    if key not in table:
        raise ValueError(f"Unknown {table_name} option '{key}'. Valid: {list(table)}")
    return float(table[key]["factor"])


def actual_capacity(c0: float, parking: str = "none", bus_stop: str = "none",
                    access_points: str = "none") -> dict:
    """Eq. 5.5: C = C0 x F_OP x F_BS x F_AC."""
    f = {"F_OP": factor("on_street_parking", parking), "F_BS": factor("bus_stop", bus_stop),
         "F_AC": factor("access_points", access_points)}
    return {"c_pcu_h": c0 * f["F_OP"] * f["F_BS"] * f["F_AC"], "factors": f}


# ------------------------------------------------------------------
# PCU — Table 5.2 (planning), Table 5.3 (evaluation of existing roads)
# ------------------------------------------------------------------
VEHICLE_TYPES = ["two_wheeler", "auto", "car", "bus", "mini_bus", "lcv", "tat", "mat",
                 "tractor_trailer", "bicycle", "cycle_rickshaw"]

PCU_TABLE_5_2 = {   # median values; None = insufficient sample ('-')
    "undivided": {"two_wheeler": 0.20, "auto": 0.73, "car": 1.00, "bus": 3.77, "mini_bus": 1.80,
                  "lcv": 2.30, "tat": 3.70, "mat": None, "tractor_trailer": 4.50,
                  "bicycle": 0.39, "cycle_rickshaw": 1.80},
    "divided":   {"two_wheeler": 0.22, "auto": 0.90, "car": 1.00, "bus": 4.60, "mini_bus": 2.07,
                  "lcv": 2.38, "tat": 3.90, "mat": 5.90, "tractor_trailer": 5.40,
                  "bicycle": 0.42, "cycle_rickshaw": 2.04},
}
PCU_TABLE_5_3 = {   # median values by road width; None = '-'
    "undivided_2lane": {"two_wheeler": 0.20, "auto": 0.73, "car": 1.00, "bus": 3.77, "mini_bus": 1.80,
                        "lcv": 2.30, "tat": 3.70, "mat": None, "tractor_trailer": 4.50,
                        "bicycle": 0.39, "cycle_rickshaw": 1.80},
    "divided_4lane":   {"two_wheeler": 0.20, "auto": 0.80, "car": 1.00, "bus": 4.58, "mini_bus": 2.10,
                        "lcv": 2.30, "tat": 3.80, "mat": 5.10, "tractor_trailer": 5.38,
                        "bicycle": 0.39, "cycle_rickshaw": 2.04},
    "divided_6lane":   {"two_wheeler": 0.21, "auto": 0.83, "car": 1.00, "bus": 4.60, "mini_bus": 2.16,
                        "lcv": 2.30, "tat": 3.90, "mat": 5.90, "tractor_trailer": 5.47,
                        "bicycle": 0.46, "cycle_rickshaw": 2.04},
    "divided_8lane":   {"two_wheeler": 0.24, "auto": 0.96, "car": 1.00, "bus": 4.60, "mini_bus": 2.16,
                        "lcv": 2.38, "tat": 3.90, "mat": 5.90, "tractor_trailer": 5.88,
                        "bicycle": None, "cycle_rickshaw": None},
    "divided_10lane":  {"two_wheeler": 0.24, "auto": 0.96, "car": 1.00, "bus": 4.60, "mini_bus": 2.61,
                        "lcv": 2.38, "tat": 3.90, "mat": 5.90, "tractor_trailer": None,
                        "bicycle": None, "cycle_rickshaw": None},
}

# Table 5A.1 plan areas (m^2); car = weighted small+big car area (5.4.2)
PLAN_AREA_M2 = {"two_wheeler": 1.20, "auto": 4.48, "car": 6.19, "bus": 24.54, "mini_bus": 14.58,
                "lcv": 12.81, "tat": 17.63, "mat": 29.52, "tractor_trailer": 16.28,
                "bicycle": 0.86, "cycle_rickshaw": 3.09}


def pcu_values(road_type: str, purpose: str = "evaluation") -> Dict[str, float]:
    """Median PCUs. purpose='evaluation' (existing road) -> Table 5.3;
    'planning' -> Table 5.2. Where Table 5.3 has '-', the Table 5.2 median for
    the same divided/undivided class is used and flagged."""
    divided = ROAD_TYPES[road_type]["divided"]
    t52 = PCU_TABLE_5_2["divided" if divided else "undivided"]
    if purpose == "planning":
        return {k: v for k, v in t52.items() if v is not None}
    out = {}
    for k, v in PCU_TABLE_5_3[road_type].items():
        if v is not None:
            out[k] = v
        elif t52.get(k) is not None:
            out[k] = t52[k]
    return out


def flow_pcu(counts_veh_h: Dict[str, float], road_type: str, purpose: str = "evaluation") -> dict:
    """Flow in PCU/h from classified flow in veh/h using median PCUs."""
    pcu = pcu_values(road_type, purpose)
    unknown = [k for k in counts_veh_h if k not in pcu]
    if unknown:
        raise ValueError(f"No Indo-HCM PCU for {unknown} on {road_type}. Valid: {sorted(pcu)}")
    return {"flow_pcu_h": sum(n * pcu[k] for k, n in counts_veh_h.items()),
            "pcu_used": {k: pcu[k] for k in counts_veh_h}, "table": "5.3" if purpose == "evaluation" else "5.2"}


def dynamic_pcu(v_subject_kmh: float, v_car_kmh: float, vehicle: str) -> float:
    """Eq. 5E.4: PCU_i = (V_c / V_i) / (A_c / A_i)  i.e. (V_c/V_i) x (A_i/A_c).
    The printed form '(Vi/Vc)/(Ai/Ac)' is the reciprocal of the dynamic PCU of
    Chandra and Sikdar (2000) that the manual cites; a slower or larger
    vehicle must get a HIGHER PCU (5.4.2), which only this form gives.
    Speeds are harmonic means for the same 5-min period."""
    return (v_car_kmh / v_subject_kmh) * (PLAN_AREA_M2[vehicle] / PLAN_AREA_M2["car"])


def stream_equivalency_factor(divided: bool, shares: Dict[str, float], total_veh_h: float) -> float:
    """Eq. 5.2 (divided) / 5.3 (undivided); flow_PCU = Se x N (Eq. 5.1).
    shares are FRACTIONS of N (Example 5.5.1 uses 0.360 for 36%):
      tw, auto, lcv (LCV + mini bus), bus, hv (TAT + MAT + tractor-trailer),
      nmt (bicycle + cycle rickshaw)."""
    g = lambda k: float(shares.get(k, 0.0))
    if divided:
        return (1 - 0.77 * g("tw") - 0.28 * g("auto") + 0.53 * g("lcv") + 2.60 * g("bus")
                + 1.83 * g("hv") - 0.66 * g("nmt") + 12.71 / total_veh_h)
    return (1 - 0.85 * g("tw") - 0.31 * g("auto") + 0.60 * g("lcv") + 3.09 * g("bus")
            + 1.06 * g("hv") - 1.30 * g("nmt") - 1.29 / total_veh_h)


def se_shares(counts_veh_h: Dict[str, float]) -> tuple:
    """Group classified counts into the Se categories. Returns (shares, N)."""
    n = sum(counts_veh_h.values())
    c = lambda *ks: sum(counts_veh_h.get(k, 0) for k in ks) / n
    return ({"tw": c("two_wheeler"), "auto": c("auto"), "lcv": c("lcv", "mini_bus"), "bus": c("bus"),
             "hv": c("tat", "mat", "tractor_trailer"), "nmt": c("bicycle", "cycle_rickshaw")}, n)


# ------------------------------------------------------------------
# LOS — Tables 5.6 (two-lane undivided) and 5.7 (multilane divided)
# (letter, upper V/C, lower % of FFS)
# ------------------------------------------------------------------
LOS_TABLES = {
    "undivided": [("A", 0.35, 89), ("B", 0.55, 55), ("C", 0.70, 21), ("D", 0.85, 12), ("E", 1.00, 6)],
    "divided":   [("A", 0.15, 84), ("B", 0.45, 76), ("C", 0.75, 59), ("D", 0.85, 41), ("E", 1.00, 22)],
}


def los_from_vc(vc: float, divided: bool) -> str:
    for letter, upper, _ in LOS_TABLES["divided" if divided else "undivided"]:
        if vc <= upper:
            return letter
    return "F"


def los_from_speed(stream_speed_kmh: float, ffs_kmh: float, divided: bool) -> str:
    """Stream (space-mean) speed as % of free-flow speed."""
    pct = stream_speed_kmh / ffs_kmh * 100
    for letter, _, lower in LOS_TABLES["divided" if divided else "undivided"]:
        if pct >= lower:
            return letter
    return "F"


# ------------------------------------------------------------------
# Speeds — Section 5.2.2, Annex 5E.1, 5E.5
# ------------------------------------------------------------------
def space_mean_speed(trap_length_m: float, travel_times_s: Sequence[float]) -> float:
    """Eq. 5E.2: SMS = D / mean(t)  (km/h)."""
    return trap_length_m / (sum(travel_times_s) / len(travel_times_s)) * 3.6


def time_mean_speed(trap_length_m: float, travel_times_s: Sequence[float]) -> float:
    """Eq. 5E.1: arithmetic mean of spot speeds (km/h). Not used for analysis."""
    return sum(trap_length_m / t for t in travel_times_s) / len(travel_times_s) * 3.6


def percentile(values: Iterable[float], p: float) -> float:
    """Linear-interpolated percentile (p in 0-100)."""
    xs = sorted(values)
    if not xs:
        raise ValueError("No values.")
    k = (len(xs) - 1) * p / 100
    f, c = math.floor(k), math.ceil(k)
    return xs[f] + (xs[c] - xs[f]) * (k - f)


def operating_speed(car_speeds_kmh: Sequence[float], headways_s: Optional[Sequence[float]] = None) -> dict:
    """85th percentile free speed of cars (5.4.5). If headways are given,
    only cars with headway > 8 s are free (5.2.2). Needs >= 100 cars."""
    speeds = list(car_speeds_kmh)
    if headways_s is not None:
        speeds = [v for v, h in zip(car_speeds_kmh, headways_s) if h > FREE_FLOW_HEADWAY_S]
    warn = None
    if len(speeds) < MIN_FREE_CAR_SAMPLE:
        warn = f"Only {len(speeds)} free cars; Indo-HCM requires at least {MIN_FREE_CAR_SAMPLE} (5.4.6)."
    return {"operating_speed_kmh": percentile(speeds, 85), "free_flow_speed_kmh": sum(speeds) / len(speeds),
            "n_free_cars": len(speeds), "warning": warn}
