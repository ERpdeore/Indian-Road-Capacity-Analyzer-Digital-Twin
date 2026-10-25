"""
road_analyzer.indo_hcm
======================
Indo-HCM 2017 (CSIR-CRRI), Chapter 5 "Urban Roads", plus the single-lane and
intermediate-lane roads of Chapter 2 (the only Indo-HCM source for them).

Every constant below carries the table / equation / section it comes from.
The project's own extensions live in road_analyzer/extensions.py. The only
choices made here (not stated by the manual) are marked "CHOICE:".

Scope (Section 5.1)
-------------------
* Urban road SEGMENTS: mid-block between controlled intersections, signals
  at least 1 km apart.
* Road types: two-lane undivided, and 4/6/8/10-lane divided (5.1.2).
  No one-way, no 4-lane undivided, no intersections (Chapter 6 covers those).
  Indo-HCM has no 4- or 6-lane UNDIVIDED class in any chapter.
* Single-lane and intermediate-lane roads exist only in Chapter 2
  (interurban roads). They are offered here with Chapter 2's own base
  capacity, width factor, speed-capacity equation, roughness equation, PCUs
  and LOS table. ASSUMPTION (stated on every result): interurban values are
  applied to an urban street, and Chapter 5's side-friction factors are
  applied to them although Chapter 2 does not calibrate any.
* Plain terrain only (Table 5B.1; no rolling/mountainous sections studied).

Method (Fig. 5.2)
-----------------
1. Flow in PCU/h      — dynamic PCU medians (Tables 5.2, 5.3), dynamic PCU
                         from speeds (Eq. 5E.4), or Se (Eq. 5.1-5.3)
2. Base capacity C0   — Table 5.4, or Eq. 5.4 from the operating speed of
                         cars measured on a BASE section (divided roads only)
3. Actual capacity    — C = C0 x F_OP x F_BS x F_AC            (Eq. 5.5)
4. LOS                — V/C and % of FFS bands (Tables 5.6, 5.7)
5. Design Service Volume = 0.70 C (every row of Table 5.4, described as
   "computed for LOS-C"). Note: Table 5.7 puts the divided-road LOS-C upper
   limit at V/C 0.75, so 0.70 is the manual's DSV ratio, not the LOS-C limit
   on divided roads; for two-lane undivided (Table 5.6) they coincide.

Advantages: calibrated on 67 sections (Table 5.1: 31 base + 36 non-base) in
10 Indian metro cities with mixed,
lane-less traffic; needs only width + side-friction description, or a car
free-speed survey.
Limitations (read before citing):
* Values are national medians; Table 5.1 shows small samples (2 base
  sections for two-lane undivided, 3 for ten-lane).
* 8- and 10-lane values come from sections with signal spacing of 1-3 km and
  apply "for similar site conditions" (5.4.4.2). The ten-lane lane capacity
  (2000 PCU/h) corresponds to 89 km/h under Eq. 5.4, above its 80 km/h range.
* Eq. 5.4 is valid for base sections, divided roads, 40-80 km/h only.
* Side friction is limited to on-street parking, bus stops and access
  points; there are no factors for vendors, encroachment, potholes,
  pedestrians, roughness or work zones on urban roads.
* Misprints in the printed manual are listed in docs/METHODOLOGY.md section 7
  (Eq. 5E.4 inverted; Examples 5.5.1, 5.5.2 and 5.5.4 arithmetic).
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
        "condition": "Derived from sections with 1-3 km signal spacing; applies to similar "
                     "site conditions (Section 5.4.4.2).",
    },
    "divided_10lane": {
        "label": "Ten-lane divided", "lanes": 5, "divided": True,
        "basis": "one direction", "paved_width_m": 17.5, "ref_width_m": 18.0,
        "capacity_pcu_h": 10000, "lane_capacity_pcu_h": 2000, "dsv_pcu_h": 7000,
        "condition": "Derived from sections with 1-3 km signal spacing; applies to similar "
                     "site conditions (Section 5.4.4.2).",
    },
}
DSV_VC_RATIO = 0.70   # every row of Table 5.4: DSV / capacity = 0.70
for _k, _rt in ROAD_TYPES.items():
    _rt.update(chapter=5, capacity_source="Table 5.4", dsv_vc_ratio=DSV_VC_RATIO,
               los_table="divided" if _rt["divided"] else "undivided",
               los_table_ref="5.7" if _rt["divided"] else "5.6")

# ------------------------------------------------------------------
# Chapter 2 — single-lane and intermediate-lane roads (interurban)
#   2.3.2 / 2.3.3 and base-section rules: single lane 3.75 m, intermediate
#   5.5-6.0 m (base 5.5 m), both carrying two-way traffic.
#   2.10.1: base capacity 800 PCU/h at 50 km/h (single), 2150 PCU/h at
#   75 km/h (intermediate), both directions together.
#   Eq. 2.12 / 2.11: capacity from operating speed of standard cars.
#   Note: Eq. 2.11 at 75 km/h gives 2060, not the 2150 the manual states;
#   the stated base value is used for C0 (docs/METHODOLOGY.md section 7).
#   DSV: Chapter 2 gives DSV for these roads only in PCU/day for two-lane
#   roads. CHOICE: the upper V/C of LOS C in the chapter's own LOS table
#   (Table 2.10: 0.50, Table 2.9: 0.60) is used as the service-volume ratio.
# ------------------------------------------------------------------
CH2_NOTE = ("Indo-HCM gives this road type only in Chapter 2 (interurban roads). Its values are "
            "applied to an urban street as a project assumption.")
ROAD_TYPES.update({
    "single_lane": {
        "label": "Single-lane (Ch. 2)", "lanes": 1, "divided": False,
        "basis": "both directions", "paved_width_m": 3.75, "ref_width_m": 3.75,
        "paved_width_range_m": (3.50, 4.20),
        "capacity_pcu_h": 800, "lane_capacity_pcu_h": 800, "dsv_pcu_h": 400,
        "chapter": 2, "capacity_source": "Section 2.10.1 (800 PCU/h at 50 km/h)",
        "dsv_vc_ratio": 0.50, "los_table": "single", "los_table_ref": "2.10",
        "base_operating_speed_kmh": 50.0,
        "speed_eq": {"a": 12.4, "b": 187.0, "eq": "Eq. 2.12"},
        "condition": CH2_NOTE,
    },
    "intermediate_lane": {
        "label": "Intermediate-lane (Ch. 2)", "lanes": 2, "divided": False,
        "basis": "both directions", "paved_width_m": 5.5, "ref_width_m": 5.5,
        "paved_width_range_m": (5.50, 6.00),
        "capacity_pcu_h": 2150, "lane_capacity_pcu_h": 1075, "dsv_pcu_h": 1290,
        "chapter": 2, "capacity_source": "Section 2.10.1 (2150 PCU/h at 75 km/h)",
        "dsv_vc_ratio": 0.60, "los_table": "intermediate", "los_table_ref": "2.9",
        "base_operating_speed_kmh": 75.0,
        "speed_eq": {"a": 16.4, "b": 830.0, "eq": "Eq. 2.11"},
        "condition": CH2_NOTE,
    },
})

# Table 2.6 — adjustment factor for carriageway width (f_w), both directions
WIDTH_FACTOR_TABLE_2_6 = {
    "single_lane":       [(3.50, 0.76), (3.75, 1.00), (4.00, 1.24), (4.20, 1.43)],
    "intermediate_lane": [(5.50, 1.00), (5.60, 1.03), (5.80, 1.09), (6.00, 1.15)],
}


def carriageway_width_factor(road_type: str, paved_width_m: float) -> dict:
    """Table 2.6 f_w. CHOICE: linear interpolation between printed widths;
    outside the printed range the end value is used (no extrapolation)."""
    rows = WIDTH_FACTOR_TABLE_2_6[road_type]
    w = float(paved_width_m)
    note = None
    if w <= rows[0][0] or w >= rows[-1][0]:
        f = rows[0][1] if w <= rows[0][0] else rows[-1][1]
        if not (rows[0][0] - 1e-9 <= w <= rows[-1][0] + 1e-9):
            note = (f"Width {w:g} m is outside the {rows[0][0]:g}-{rows[-1][0]:g} m of Table 2.6; "
                    f"the end value f_w = {f:.2f} is used.")
    else:
        for (w0, f0), (w1, f1) in zip(rows, rows[1:]):
            if w0 <= w <= w1:
                f = f0 + (f1 - f0) * (w - w0) / (w1 - w0)
                break
    return {"f_w": f, "note": note}


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
    if rt["chapter"] == 2:
        if not (lo <= paved_width_m <= hi):
            return (f"Paved width {paved_width_m:g} m is outside {lo:g}-{hi:g} m for a "
                    f"{rt['label'].split(' (')[0].lower()} road (Table 2.6); check the road type.")
        return None
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


def base_capacity(road_type: str, operating_speed_kmh: Optional[float] = None,
                  paved_width_m: Optional[float] = None) -> dict:
    """
    C0 for one analysis unit.
      * divided road + operating speed measured on a BASE section
            -> Eq. 5.4 x lanes per direction   (site-specific route offered by 5.4.5)
      * otherwise -> Table 5.4
    Two-lane undivided roads have no speed model: Table 5.4 only.
    Chapter 2 roads (single / intermediate lane): Section 2.10.1 value, or
    Eq. 2.12 / 2.11 from a measured operating speed, times the Table 2.6
    carriageway-width factor f_w.
    """
    rt = ROAD_TYPES[road_type]
    notes: List[str] = []
    if rt.get("condition"):
        notes.append(rt["condition"])
    if rt["chapter"] == 2:
        return _base_capacity_ch2(road_type, operating_speed_kmh, paved_width_m, notes)
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


def _base_capacity_ch2(road_type: str, v: Optional[float], width: Optional[float],
                       notes: List[str]) -> dict:
    rt = ROAD_TYPES[road_type]
    w = width if width else rt["paved_width_m"]
    fw = carriageway_width_factor(road_type, w)
    if fw["note"]:
        notes.append(fw["note"])
    if v:
        se = rt["speed_eq"]
        c_std = se["b"] + se["a"] * float(v)
        method = se["eq"]
        detail = (f"{se['eq']}: {se['b']:g} + {se['a']:g} x {v:g} = {c_std:.0f} PCU/h; "
                  f"x f_w {fw['f_w']:.2f} (Table 2.6, {w:g} m)")
    else:
        c_std = float(rt["capacity_pcu_h"])
        method = "Section 2.10.1"
        detail = (f"{rt['capacity_source']} x f_w {fw['f_w']:.2f} (Table 2.6, {w:g} m)")
    c0 = c_std * fw["f_w"]
    return {"c0_pcu_h": c0, "lane_capacity_pcu_h": c0 / rt["lanes"], "method": method,
            "operating_speed_kmh": float(v) if v else None, "f_w_table_2_6": fw["f_w"],
            "detail": detail, "notes": notes}


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
                        "bicycle": 0.39, "cycle_rickshaw": None},   # 1.80 is printed as range, median '-'
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

# Table 2.4 — Chapter 2 medians. Single lane has its own column;
# intermediate lane shares the two-lane column.
# CHOICE: 'car' = standard car 1.00 (big cars 1.60 are not a separate class
# here); mini bus has no Table 2.4 value, so the Table 5.2 undivided median
# 1.80 is used.
PCU_TABLE_2_4 = {
    "single_lane":       {"two_wheeler": 0.25, "auto": 1.20, "car": 1.00, "bus": 4.50, "mini_bus": 1.80,
                          "lcv": 2.70, "tat": 4.80, "mat": 5.00, "tractor_trailer": 7.00,
                          "bicycle": 0.40, "cycle_rickshaw": 2.10},
    "intermediate_lane": {"two_wheeler": 0.30, "auto": 1.20, "car": 1.00, "bus": 4.50, "mini_bus": 1.80,
                          "lcv": 3.00, "tat": 5.00, "mat": 6.00, "tractor_trailer": 7.00,
                          "bicycle": 0.40, "cycle_rickshaw": 2.50},
}

# Table 5A.1 plan areas (m^2); car = weighted small+big car area (5.4.2)
PLAN_AREA_M2 = {"two_wheeler": 1.20, "auto": 4.48, "car": 6.19, "bus": 24.54, "mini_bus": 14.58,
                "lcv": 12.81, "tat": 17.63, "mat": 29.52, "tractor_trailer": 16.28,
                "bicycle": 0.86, "cycle_rickshaw": 3.09}


def pcu_values(road_type: str, purpose: str = "evaluation") -> Dict[str, float]:
    """Median PCUs. purpose='evaluation' (existing road) -> Table 5.3;
    'planning' -> Table 5.2. CHOICE: where Table 5.3 has '-', the Table 5.2
    median for the same divided/undivided class is used (the manual gives no
    rule for this case)."""
    if road_type in PCU_TABLE_2_4:
        return dict(PCU_TABLE_2_4[road_type])
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
            "pcu_used": {k: pcu[k] for k in counts_veh_h},
            "table": "2.4" if road_type in PCU_TABLE_2_4 else ("5.3" if purpose == "evaluation" else "5.2")}


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
# Chapter 2: Table 2.9 (intermediate and two-lane, V/C column) and
# Table 2.10 (single lane). No % of FFS bands (None).
LOS_TABLES = {
    "undivided":    [("A", 0.35, 89), ("B", 0.55, 55), ("C", 0.70, 21), ("D", 0.85, 12), ("E", 1.00, 6)],
    "divided":      [("A", 0.15, 84), ("B", 0.45, 76), ("C", 0.75, 59), ("D", 0.85, 41), ("E", 1.00, 22)],
    "intermediate": [("A", 0.25, None), ("B", 0.45, None), ("C", 0.60, None), ("D", 0.75, None),
                     ("E", 1.00, None)],
    "single":       [("A", 0.15, None), ("B", 0.30, None), ("C", 0.50, None), ("D", 0.80, None),
                     ("E", 1.00, None)],
}
LOS_A_INCLUSIVE = {"single"}   # Table 2.10 prints A as '<= 0.15'; the others as '< limit'


def _los_key(table) -> str:
    if isinstance(table, bool):
        return "divided" if table else "undivided"
    return table


def los_from_vc(vc: float, divided=None, table: Optional[str] = None) -> str:
    """Pass `table` (a LOS_TABLES key) or `divided` (True = Table 5.7,
    False = Table 5.6; a table key is also accepted here). Band edges as printed: A is '< limit' (strict) except Table
    2.10 ('<= 0.15'); B-E include their upper value; F is '> 1.00'.
    CHOICE: printing gaps (e.g. Table 5.6 A < 0.35, B 0.36-0.55) go to the
    better band."""
    key = table or _los_key(divided)
    bands = LOS_TABLES[key]
    if vc < bands[0][1] or (key in LOS_A_INCLUSIVE and vc <= bands[0][1]):
        return "A"
    for letter, upper, _ in bands[1:]:
        if vc <= upper:
            return letter
    return "F"


def los_from_speed(stream_speed_kmh: float, ffs_kmh: float, table) -> str:
    """Stream (space-mean) speed as % of free-flow speed (Chapter 5 tables
    only). A is '> limit' (strict); integer gaps go to the worse band."""
    pct = stream_speed_kmh / ffs_kmh * 100
    key = _los_key(table)
    if LOS_TABLES[key][0][2] is None:
        raise ValueError(f"LOS table '{key}' has no speed bands; use V/C.")
    bands = LOS_TABLES[key]
    if pct > bands[0][2]:
        return "A"
    for letter, _, lower in bands[1:]:
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
    only cars with a finite headway > 8 s to the vehicle ahead are free
    (5.2.2 'time gap ... more than 8 seconds'; 5E.5 'headway'). Needs >= 100
    cars. Returns operating_speed_kmh = None when no free car exists."""
    speeds = list(car_speeds_kmh)
    if headways_s is not None:
        speeds = [v for v, h in zip(car_speeds_kmh, headways_s)
                  if h is not None and math.isfinite(h) and h > FREE_FLOW_HEADWAY_S]
    if not speeds:
        return {"operating_speed_kmh": None, "free_flow_speed_kmh": None, "n_free_cars": 0,
                "warning": "No free-flowing cars (headway > 8 s) in the data; survey at a "
                           "lighter-traffic time to measure operating speed."}
    warn = None
    if len(speeds) < MIN_FREE_CAR_SAMPLE:
        warn = f"Only {len(speeds)} free cars; Indo-HCM requires at least {MIN_FREE_CAR_SAMPLE} (5.4.5)."
    return {"operating_speed_kmh": percentile(speeds, 85), "free_flow_speed_kmh": sum(speeds) / len(speeds),
            "n_free_cars": len(speeds), "warning": warn}
