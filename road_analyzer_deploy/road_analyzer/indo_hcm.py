"""
road_analyzer.indo_hcm
======================
Urban mid-block capacity tables and adjustment factors following the
Indo-HCM (CSIR-CRRI, 2017) Chapter 5 framework for urban roads.

Every number the capacity calculation uses lives in THIS file, so it can be
checked line-by-line against the printed manual.

Source of the numbers
---------------------
Indo-HCM 2017 is a paid publication. The values below are taken from the
IRC:106 (2022) draft "Guidelines for Capacity of Urban Roads in Plain
Terrain", which carries the Indo-HCM urban methodology into IRC form
(same operating-speed model, same multiplicative side-friction factors,
same V/C-based LOS, and cites CSIR-CRRI 2017 for the LOS thresholds).
Table references below are to that draft. BEFORE SUBMISSION, cross-check
each table against Indo-HCM 2017 Chapter 5 (Sections 5.4.4 - 5.4.7) and
correct any value that differs - the code reads only from this module.

Method (draft Eq. 6, Indo-HCM 5.4.7):
    C = C0 x F_OP x F_BS x F_AC x F_PD
    C0   base capacity for base (ideal) sections
    F_OP on-street parking, F_BS bus stops,
    F_AC access points,     F_PD mid-block pedestrian crossings

Two things this project adds on top, both explicit and labelled:
    F_W  effective-width factor for physical encroachments
         (vendors, carts, garbage, barricades) - capacity taken as
         proportional to usable carriageway width, the usual
         assumption for lane-less mixed traffic.
    F_P  pothole factor - potholes do not appear in Indo-HCM. They are
         modelled as an operating-speed reduction, and the Indo-HCM
         lane-capacity/operating-speed model (draft Eq. 5) converts that
         speed drop into a capacity drop. The speed reductions per size
         class are PROJECT ASSUMPTIONS (POTHOLE_SPEED_REDUCTION) to be
         replaced with field-measured values.
"""

from __future__ import annotations

from typing import Dict, Optional

SOURCE_NOTE = (
    "Indo-HCM 2017 Ch.5 urban framework; values as tabulated in IRC:106 (2022 draft) "
    "Tables 4, 5, 8, 9, 12-16 and Eq. 5-6"
)

# Indo-HCM 5.1.2: standard lane 3.5 m, 0.25 m kerb "shyness" each edge.
STANDARD_LANE_WIDTH_M = 3.5
SHY_DISTANCE_M = 0.25

# ----------------------------------------------------------------
# Base capacity, base sections (draft Table 5).
# Each entry describes ONE analysis unit = the carriageway in the photo:
#   - undivided roads: both directions together
#   - divided roads:   one direction (one carriageway)
# A one-way street is analysed as one direction of a divided road with
# the same number of lanes (stated assumption - no separate one-way row).
# ----------------------------------------------------------------
ROAD_TYPES: Dict[str, dict] = {
    "undivided_2lane": {
        "label": "2-lane undivided (two-way)",
        "lanes": 2, "divided": False, "basis": "both directions",
        "ref_width_m": 7.0, "base_capacity_pcu_h": 2200, "lane_capacity_pcu_h": 1100,
    },
    "undivided_4lane": {
        "label": "4-lane undivided (two-way)",
        "lanes": 4, "divided": False, "basis": "both directions",
        "ref_width_m": 14.0, "base_capacity_pcu_h": 5000, "lane_capacity_pcu_h": 1250,
        "note": "IRC:106 (2022 draft) row; Indo-HCM Ch.5 base sections cover 2-lane "
                "undivided and 4-10 lane divided only.",
    },
    "divided_2lane_dir": {
        "label": "4-lane divided — one carriageway (2 lanes, one direction)",
        "lanes": 2, "divided": True, "basis": "one direction",
        "ref_width_m": 7.0, "base_capacity_pcu_h": 3400, "lane_capacity_pcu_h": 1700,
    },
    "divided_3lane_dir": {
        "label": "6-lane divided — one carriageway (3 lanes, one direction)",
        "lanes": 3, "divided": True, "basis": "one direction",
        "ref_width_m": 10.5, "base_capacity_pcu_h": 5100, "lane_capacity_pcu_h": 1700,
    },
    "divided_4lane_dir": {
        "label": "8-lane divided — one carriageway (4 lanes, one direction)",
        "lanes": 4, "divided": True, "basis": "one direction",
        "ref_width_m": 14.0, "base_capacity_pcu_h": 6800, "lane_capacity_pcu_h": 1700,
    },
}

# Design Service Volume is set at LOS-C (draft Table 5 note) -> V/C = 0.70.
DSV_VC_RATIO = 0.70

# ----------------------------------------------------------------
# Operating speed (85th percentile free-flow speed of standard cars).
# Draft Table 3 defaults when the user has not measured it on site.
# ----------------------------------------------------------------
FUNCTIONAL_CLASSES: Dict[str, dict] = {
    "arterial":     {"label": "Arterial",     "operating_speed_kmh": 50},
    "sub_arterial": {"label": "Sub-arterial", "operating_speed_kmh": 40},
    "collector":    {"label": "Collector",    "operating_speed_kmh": 30},
}

# Draft Eq. 5 (divided urban roads, base sections):
#   C_lane = 20.11 * V_operating + 210.8   [PCU/h/lane], V in km/h
SPEED_MODEL_A = 20.11
SPEED_MODEL_B = 210.8
SPEED_MODEL_RANGE_KMH = (40.0, 60.0)   # range tabulated for urban roads (draft Table 7)


def lane_capacity_from_speed(v_kmh: float) -> float:
    return SPEED_MODEL_A * float(v_kmh) + SPEED_MODEL_B


# ----------------------------------------------------------------
# Side-friction adjustment factors (draft Tables 12-16)
# ----------------------------------------------------------------
PARKING_FACTORS: Dict[str, dict] = {   # share of segment length with on-street parking
    "none":  {"label": "No on-street parking", "factor": 1.00},
    "lt25":  {"label": "< 25% of segment length", "factor": 0.70},
    "25_50": {"label": "25 – 50% of segment length", "factor": 0.65},
    "gt50":  {"label": "> 50% of segment length", "factor": 0.40},
}
BUS_STOP_FACTORS: Dict[str, dict] = {
    "none":          {"label": "No bus stop on segment", "factor": 1.00},
    "kerbside_low":  {"label": "Kerbside stop, ≤ 30 buses/h", "factor": 0.80},
    "kerbside_high": {"label": "Kerbside stop, > 30 buses/h", "factor": 0.60},
    "bay_low":       {"label": "Bus bay, ≤ 30 buses/h", "factor": 0.90},
    "bay_high":      {"label": "Bus bay, > 30 buses/h", "factor": 0.80},
}
ACCESS_FACTORS: Dict[str, dict] = {    # entry + exit flow at access points
    "none":    {"label": "No access points", "factor": 1.00},
    "lt200":   {"label": "< 200 veh/h entering/leaving", "factor": 0.90},
    "200_500": {"label": "200 – 500 veh/h", "factor": 0.80},
    "gt500":   {"label": "> 500 veh/h", "factor": 0.70},
}
PEDESTRIAN_FACTORS: Dict[str, dict] = {  # mid-block crossing pedestrians per hour
    "none":      {"label": "No mid-block crossing", "factor": 1.00},
    "lt250":     {"label": "< 250 ped/h", "factor": 0.90},
    "250_500":   {"label": "250 – 500 ped/h", "factor": 0.78},
    "500_1000":  {"label": "500 – 1000 ped/h", "factor": 0.72},
    "1000_1500": {"label": "1000 – 1500 ped/h", "factor": 0.68},
}

# ----------------------------------------------------------------
# PCU equivalents for urban roads (draft Table 4)
# ----------------------------------------------------------------
PCU_FACTORS: Dict[str, Dict[str, float]] = {
    "undivided": {
        "two_wheeler": 0.25, "auto_rickshaw": 1.00, "car": 1.00, "bus": 4.00,
        "lcv": 1.80, "truck": 4.00, "bicycle": 0.39, "cycle_rickshaw": 1.80,
    },
    "divided": {
        "two_wheeler": 0.40, "auto_rickshaw": 0.90, "car": 1.00, "bus": 3.50,
        "lcv": 1.60, "truck": 3.50, "bicycle": 0.42, "cycle_rickshaw": 2.04,
    },
}

# ASSUMED composition, used ONLY to show an indicative vehicles/h figure next
# to PCU/h. Replace with your classified count for the site. All capacity
# logic is in PCU/h and does not depend on this.
DEFAULT_COMPOSITION: Dict[str, float] = {
    "two_wheeler": 0.55, "car": 0.25, "auto_rickshaw": 0.10,
    "bus": 0.03, "lcv": 0.04, "truck": 0.02, "bicycle": 0.01,
}


def avg_pcu_per_vehicle(divided: bool, composition: Optional[Dict[str, float]] = None) -> float:
    comp = composition or DEFAULT_COMPOSITION
    table = PCU_FACTORS["divided" if divided else "undivided"]
    total = sum(comp.values()) or 1.0
    return sum(share * table.get(v, 1.0) for v, share in comp.items()) / total


# ----------------------------------------------------------------
# LOS from V/C (draft Tables 8 and 9; thresholds cited to CSIR-CRRI 2017)
# Upper bound of each band.
# ----------------------------------------------------------------
LOS_VC_BANDS = {
    "undivided": [("A", 0.35), ("B", 0.55), ("C", 0.70), ("D", 0.85), ("E", 1.00)],
    "divided":   [("A", 0.30), ("B", 0.45), ("C", 0.70), ("D", 0.85), ("E", 1.00)],
}


def los_from_vc(vc: float, divided: bool) -> str:
    for letter, upper in LOS_VC_BANDS["divided" if divided else "undivided"]:
        if vc <= upper:
            return letter
    return "F"


# ----------------------------------------------------------------
# Potholes (project extension - not part of Indo-HCM)
# Size class follows IRC:82-2015 cl. 7.5.3.4 (small ~200 mm wide/25 mm deep,
# medium 25-50 mm deep/500 mm wide, large > 50 mm deep). A photo gives width
# only, so the class here is a WIDTH-ONLY proxy; depth is not measured.
# ----------------------------------------------------------------
POTHOLE_WIDTH_CLASSES = [  # (upper width bound in m, class)
    (0.20, "small"),
    (0.50, "medium"),
    (float("inf"), "large"),
]

# Fractional operating-speed reduction caused by the worst pothole on the
# section. PROJECT ASSUMPTION - calibrate with spot-speed data at
# pothole and control sections, then edit these three numbers.
POTHOLE_SPEED_REDUCTION: Dict[str, float] = {
    "small": 0.05,
    "medium": 0.10,
    "large": 0.20,
}


def pothole_class_from_width(width_m: float) -> str:
    for upper, cls in POTHOLE_WIDTH_CLASSES:
        if width_m <= upper:
            return cls
    return "large"


def pothole_capacity_factor(size_class: Optional[str], operating_speed_kmh: float) -> float:
    """Capacity ratio after the pothole-induced speed drop, via draft Eq. 5."""
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
      - no measured speed: draft Table 5 base capacity
      - measured operating speed on a DIVIDED road: draft Eq. 5 x lanes
        (the site-specific Indo-HCM route). Undivided roads have no speed
        model in the draft, so they always use Table 5.
    """
    rt = ROAD_TYPES[road_type]
    if operating_speed_kmh and rt["divided"]:
        lo, hi = SPEED_MODEL_RANGE_KMH
        lane_c = lane_capacity_from_speed(operating_speed_kmh)
        warn = None
        if not (lo <= operating_speed_kmh <= hi):
            warn = (f"Operating speed {operating_speed_kmh:g} km/h is outside the "
                    f"{lo:g}-{hi:g} km/h range of the urban speed model; result is an extrapolation.")
        return {
            "c0_pcu_h": lane_c * rt["lanes"],
            "lane_capacity_pcu_h": lane_c,
            "method": f"Eq. 5: C_lane = {SPEED_MODEL_A} x {operating_speed_kmh:g} + {SPEED_MODEL_B} "
                      f"= {lane_c:.0f} PCU/h/lane x {rt['lanes']} lanes",
            "warning": warn,
        }
    return {
        "c0_pcu_h": float(rt["base_capacity_pcu_h"]),
        "lane_capacity_pcu_h": float(rt["lane_capacity_pcu_h"]),
        "method": f"Table 5 base capacity for {rt['label']}",
        "warning": None,
    }
