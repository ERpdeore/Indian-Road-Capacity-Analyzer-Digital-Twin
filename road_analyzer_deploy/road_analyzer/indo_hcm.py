"""
road_analyzer.indo_hcm
======================
Urban mid-block capacity values from Indo-HCM 2017 (CSIR-CRRI),
Chapter 5 "Urban Roads". Every number the capacity calculation uses
lives in THIS file, with the table it comes from.

Indo-HCM method (Section 5.4, Fig. 5.2):
    C = C0 x F_OP x F_BS x F_AC                          (Eq. 5.5)
    C0    base capacity of a base section                (Table 5.4)
          or, for divided roads, lane capacity from the
          operating speed of cars                        (Eq. 5.4, Table 5.5)
    F_OP  on-street parking                              (Tables 5.9, 5.10)
    F_BS  bus stops                                      (Table 5.11)
    F_AC  access points                                  (Table 5.12)
    DSV   at LOS-C = 0.70 C                              (Table 5.4)
    LOS   from V/C (and % of FFS)                        (Tables 5.6, 5.7)
    PCU   dynamic PCU medians                            (Tables 5.2, 5.3)
          or Stream Equivalency Factor Se                (Eq. 5.2, 5.3)

Indo-HCM covers two-lane undivided and 4/6/8/10-lane divided urban roads
only (Section 5.1.2). It has no separate one-way road class and no factor
for potholes, vendors, garbage or barricades. This project adds two
labelled extensions:
    F_W  usable-width factor for physical encroachments
    F_P  pothole factor: assumed speed reduction converted to capacity
         with Eq. 5.4
"""

from __future__ import annotations

from typing import Dict, Optional

SOURCE_NOTE = "Indo-HCM 2017 (CSIR-CRRI), Chapter 5 Urban Roads"

# Section 5.1.2: 3.5 m lanes, 0.25 m kerb shyness on either edge.
STANDARD_LANE_WIDTH_M = 3.5
SHY_DISTANCE_M = 0.25

# ----------------------------------------------------------------
# Table 5.4: capacity of base sections. One analysis unit each:
# undivided = both directions; divided = one direction.
# Reference widths include 0.25 m shyness each edge (Section 5.1.2).
# ----------------------------------------------------------------
ROAD_TYPES: Dict[str, dict] = {
    "undivided_2lane": {
        "label": "Two-lane undivided (both directions)",
        "lanes": 2, "divided": False, "basis": "both directions",
        "ref_width_m": 7.5, "base_capacity_pcu_h": 2400, "lane_capacity_pcu_h": 1200,
        "dsv_pcu_h": 1680,
    },
    "divided_4lane": {
        "label": "Four-lane divided — one direction (2 lanes)",
        "lanes": 2, "divided": True, "basis": "one direction",
        "ref_width_m": 7.5, "base_capacity_pcu_h": 2700, "lane_capacity_pcu_h": 1350,
        "dsv_pcu_h": 1890,
    },
    "divided_6lane": {
        "label": "Six-lane divided — one direction (3 lanes)",
        "lanes": 3, "divided": True, "basis": "one direction",
        "ref_width_m": 11.0, "base_capacity_pcu_h": 4200, "lane_capacity_pcu_h": 1400,
        "dsv_pcu_h": 2940,
    },
    "divided_8lane": {
        "label": "Eight-lane divided — one direction (4 lanes)",
        "lanes": 4, "divided": True, "basis": "one direction",
        "ref_width_m": 14.5, "base_capacity_pcu_h": 6800, "lane_capacity_pcu_h": 1700,
        "dsv_pcu_h": 4760,
        "note": "Table 5.4 value applies where signal spacing is 1-3 km (Section 5.4.4.2).",
    },
    "divided_10lane": {
        "label": "Ten-lane divided — one direction (5 lanes)",
        "lanes": 5, "divided": True, "basis": "one direction",
        "ref_width_m": 18.0, "base_capacity_pcu_h": 10000, "lane_capacity_pcu_h": 2000,
        "dsv_pcu_h": 7000,
        "note": "Table 5.4 value applies where signal spacing is 1-3 km (Section 5.4.4.2).",
    },
}

# DSV at LOS-C: Table 5.4 values are 0.70 x capacity for every row.
DSV_VC_RATIO = 0.70

# ----------------------------------------------------------------
# Operating speed = 85th percentile free speed of cars, >= 100 cars
# (Section 5.4.6). Indo-HCM gives no default by functional class; the
# defaults below are PROJECT ASSUMPTIONS used only when no speed survey
# exists, and C0 then comes from Table 5.4, not from Eq. 5.4.
# ----------------------------------------------------------------
FUNCTIONAL_CLASSES: Dict[str, dict] = {
    "arterial":     {"label": "Arterial",     "operating_speed_kmh": 50},
    "sub_arterial": {"label": "Sub-arterial", "operating_speed_kmh": 40},
    "collector":    {"label": "Collector",    "operating_speed_kmh": 30},
}

# Eq. 5.4 (divided roads, base sections): C_lane = 20.11 V + 210.8
SPEED_MODEL_A = 20.11
SPEED_MODEL_B = 210.8
SPEED_MODEL_RANGE_KMH = (40.0, 80.0)   # validity stated under Eq. 5.4


def lane_capacity_from_speed(v_kmh: float) -> float:
    return SPEED_MODEL_A * float(v_kmh) + SPEED_MODEL_B


# ----------------------------------------------------------------
# Side-friction adjustment factors (Section 5.4.7)
# Table 5.9 applies to long-term parking (few manoeuvres),
# Table 5.10 to short-term parking (intense manoeuvres).
# ----------------------------------------------------------------
PARKING_FACTORS: Dict[str, dict] = {
    "none":       {"label": "No on-street parking", "factor": 1.00},
    "len_lt25":   {"label": "Long-term, < 25% of segment length (T5.9)", "factor": 0.70},
    "len_25_50":  {"label": "Long-term, 25 – 50% of length (T5.9)", "factor": 0.65},
    "len_gt50":   {"label": "Long-term, > 50% of length (T5.9)", "factor": 0.40},
    "man_le500":  {"label": "Short-term, ≤ 500 manoeuvres/km/h (T5.10)", "factor": 0.65},
    "man_gt500":  {"label": "Short-term, > 500 manoeuvres/km/h (T5.10)", "factor": 0.40},
}
PARKING_WHEN_DETECTED = "len_lt25"   # mildest class, used if parking is seen but not declared

BUS_STOP_FACTORS: Dict[str, dict] = {       # Table 5.11
    "none":          {"label": "No bus stop on segment", "factor": 1.00},
    "kerbside_low":  {"label": "Kerbside stop, ≤ 30 buses/h", "factor": 0.80},
    "kerbside_high": {"label": "Kerbside stop, > 30 buses/h", "factor": 0.60},
    "bay_low":       {"label": "Bus bay, ≤ 30 buses/h", "factor": 0.90},
    "bay_high":      {"label": "Bus bay, > 30 buses/h", "factor": 0.80},
}
ACCESS_FACTORS: Dict[str, dict] = {         # Table 5.12, total entry + exit per hour
    "none":    {"label": "No access points", "factor": 1.00},
    "lt200":   {"label": "< 200 veh/h entering + leaving", "factor": 0.90},
    "200_500": {"label": "200 – 500 veh/h", "factor": 0.80},
    "gt500":   {"label": "> 500 veh/h", "factor": 0.70},
}

# ----------------------------------------------------------------
# Dynamic PCU medians. Table 5.2 = planning; Table 5.3 = evaluation of
# existing roads by width. Keyed by road type; Table 5.3 has no value for
# some vehicles on wide roads ('-'), there the Table 5.2 divided median is used.
# ----------------------------------------------------------------
_PCU_T52_DIVIDED = {"two_wheeler": 0.22, "auto_rickshaw": 0.90, "car": 1.00, "bus": 4.60,
                    "mini_bus": 2.07, "lcv": 2.38, "truck_2_3_axle": 3.90, "truck_multi_axle": 5.90,
                    "tractor_trailer": 5.40, "bicycle": 0.42, "cycle_rickshaw": 2.04}
PCU_FACTORS: Dict[str, Dict[str, float]] = {
    "undivided_2lane": {"two_wheeler": 0.20, "auto_rickshaw": 0.73, "car": 1.00, "bus": 3.77,
                        "mini_bus": 1.80, "lcv": 2.30, "truck_2_3_axle": 3.70,
                        "tractor_trailer": 4.50, "bicycle": 0.39, "cycle_rickshaw": 1.80},
    "divided_4lane": {"two_wheeler": 0.20, "auto_rickshaw": 0.80, "car": 1.00, "bus": 4.58,
                      "mini_bus": 2.10, "lcv": 2.30, "truck_2_3_axle": 3.80, "truck_multi_axle": 5.10,
                      "tractor_trailer": 5.38, "bicycle": 0.39, "cycle_rickshaw": 2.04},
    "divided_6lane": {"two_wheeler": 0.21, "auto_rickshaw": 0.83, "car": 1.00, "bus": 4.60,
                      "mini_bus": 2.16, "lcv": 2.30, "truck_2_3_axle": 3.90, "truck_multi_axle": 5.90,
                      "tractor_trailer": 5.47, "bicycle": 0.46, "cycle_rickshaw": 2.04},
    "divided_8lane": {"two_wheeler": 0.24, "auto_rickshaw": 0.96, "car": 1.00, "bus": 4.60,
                      "mini_bus": 2.16, "lcv": 2.38, "truck_2_3_axle": 3.90, "truck_multi_axle": 5.90,
                      "tractor_trailer": 5.88},
    "divided_10lane": {"two_wheeler": 0.24, "auto_rickshaw": 0.96, "car": 1.00, "bus": 4.60,
                       "mini_bus": 2.61, "lcv": 2.38, "truck_2_3_axle": 3.90, "truck_multi_axle": 5.90},
}

# ASSUMED composition, used ONLY for the indicative veh/h figure. All
# capacity logic is in PCU/h. Replace with a classified count.
DEFAULT_COMPOSITION: Dict[str, float] = {
    "two_wheeler": 0.55, "car": 0.25, "auto_rickshaw": 0.10,
    "bus": 0.03, "lcv": 0.04, "truck_2_3_axle": 0.02, "bicycle": 0.01,
}


def avg_pcu_per_vehicle(road_type: str, composition: Optional[Dict[str, float]] = None) -> float:
    comp = composition or DEFAULT_COMPOSITION
    table = {**_PCU_T52_DIVIDED, **PCU_FACTORS[road_type]} if road_type != "undivided_2lane" \
        else PCU_FACTORS[road_type]
    total = sum(comp.values()) or 1.0
    return sum(share * table.get(v, 1.0) for v, share in comp.items()) / total


def stream_equivalency_factor(divided: bool, shares: Dict[str, float], total_veh_h: float) -> float:
    """Eq. 5.2 (divided) / 5.3 (undivided). shares are fractions (0-1):
    tw, auto, lcv (LCV + mini bus), bus, hv (2/3-axle, multi-axle, tractor-trailer),
    nmt (bicycle + cycle rickshaw). Returns Se; flow_PCU = Se x N."""
    g = lambda k: float(shares.get(k, 0.0))
    if divided:
        return (1 - 0.77 * g("tw") - 0.28 * g("auto") + 0.53 * g("lcv") + 2.60 * g("bus")
                + 1.83 * g("hv") - 0.66 * g("nmt") + 12.71 / total_veh_h)
    return (1 - 0.85 * g("tw") - 0.31 * g("auto") + 0.60 * g("lcv") + 3.09 * g("bus")
            + 1.06 * g("hv") - 1.30 * g("nmt") - 1.29 / total_veh_h)


# ----------------------------------------------------------------
# LOS (Tables 5.6 and 5.7): upper V/C bound and lower %FFS bound per band
# ----------------------------------------------------------------
LOS_TABLES = {
    "undivided": [("A", 0.35, 89), ("B", 0.55, 55), ("C", 0.70, 21),
                  ("D", 0.85, 12), ("E", 1.00, 6)],
    "divided":   [("A", 0.15, 84), ("B", 0.45, 76), ("C", 0.75, 59),
                  ("D", 0.85, 41), ("E", 1.00, 22)],
}


def los_from_vc(vc: float, divided: bool) -> str:
    for letter, upper, _ in LOS_TABLES["divided" if divided else "undivided"]:
        if vc <= upper:
            return letter
    return "F"


def los_from_speed_ratio(pct_ffs: float, divided: bool) -> str:
    for letter, _, lower in LOS_TABLES["divided" if divided else "undivided"]:
        if pct_ffs >= lower:
            return letter
    return "F"


# ----------------------------------------------------------------
# Potholes (PROJECT EXTENSION — not in Indo-HCM)
# Size class follows IRC:82-2015 cl. 7.5.3.4 widths (200 / 500 mm);
# depth is not measured from a photo.
# ----------------------------------------------------------------
POTHOLE_WIDTH_CLASSES = [(0.20, "small"), (0.50, "medium"), (float("inf"), "large")]

# Fractional operating-speed drop caused by the worst pothole. ASSUMED —
# replace with spot-speed data from pothole vs clean sections.
POTHOLE_SPEED_REDUCTION: Dict[str, float] = {"small": 0.05, "medium": 0.10, "large": 0.20}


def pothole_class_from_width(width_m: float) -> str:
    for upper, cls in POTHOLE_WIDTH_CLASSES:
        if width_m <= upper:
            return cls
    return "large"


def pothole_capacity_factor(size_class: Optional[str], operating_speed_kmh: float) -> float:
    """Capacity ratio after the pothole-induced speed drop, via Eq. 5.4."""
    if not size_class or size_class not in POTHOLE_SPEED_REDUCTION:
        return 1.0
    v0 = float(operating_speed_kmh)
    v1 = v0 * (1.0 - POTHOLE_SPEED_REDUCTION[size_class])
    return lane_capacity_from_speed(v1) / lane_capacity_from_speed(v0)


def lookup_factor(table: Dict[str, dict], key: Optional[str], name: str) -> float:
    key = key or "none"
    if key not in table:
        raise ValueError(f"Unknown {name} option '{key}'. Valid: {list(table)}")
    return float(table[key]["factor"])


def base_capacity(road_type: str, operating_speed_kmh: Optional[float]) -> dict:
    """
    C0 for the analysis unit.
      - measured operating speed on a DIVIDED road: Eq. 5.4 x lanes
        (site-specific; the manual's preferred route for divided roads)
      - otherwise: Table 5.4 base capacity
    """
    rt = ROAD_TYPES[road_type]
    if operating_speed_kmh and rt["divided"]:
        lo, hi = SPEED_MODEL_RANGE_KMH
        lane_c = lane_capacity_from_speed(operating_speed_kmh)
        warn = None
        if not (lo <= operating_speed_kmh <= hi):
            warn = (f"Operating speed {operating_speed_kmh:g} km/h is outside the {lo:g}-{hi:g} km/h "
                    f"validity of Indo-HCM Eq. 5.4; result is an extrapolation.")
        return {
            "c0_pcu_h": lane_c * rt["lanes"],
            "lane_capacity_pcu_h": lane_c,
            "method": f"Indo-HCM Eq. 5.4: C_lane = {SPEED_MODEL_A} x {operating_speed_kmh:g} + "
                      f"{SPEED_MODEL_B} = {lane_c:.0f} PCU/h/lane x {rt['lanes']} lanes",
            "warning": warn,
        }
    return {
        "c0_pcu_h": float(rt["base_capacity_pcu_h"]),
        "lane_capacity_pcu_h": float(rt["lane_capacity_pcu_h"]),
        "method": f"Indo-HCM Table 5.4 base capacity, {rt['label']}",
        "warning": rt.get("note"),
    }
