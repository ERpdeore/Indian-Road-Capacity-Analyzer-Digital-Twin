"""
road_analyzer.extensions
========================
PROJECT EXTENSIONS to Indo-HCM 2017 Chapter 5.

Indo-HCM's urban method (Eq. 5.5) only covers on-street parking, bus stops
and access points. It has no factor for street vendors, carts, garbage,
barricades or potholes, and no roughness adjustment for urban roads. The
factors below fill that gap. They are built from Indo-HCM concepts, but
they are NOT Indo-HCM factors and must be reported and validated as the
project's own contribution (see field_validation.py).

    C_extended = C_IndoHCM x F_W x F_R

F_W  effective-width factor   — physical obstructions on the carriageway:
                                vendors, carts, garbage, barricades, potholes.
F_R  roughness factor         — optional, only when IRI is measured.

Parked vehicles are deliberately NOT in F_W: their effect is Indo-HCM's
F_OP (Tables 5.9/5.10), which already includes the width they occupy.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from road_analyzer import indo_hcm as hcm

# Obstructions that act through usable width. Potholes are included:
# in lane-less mixed traffic most vehicles steer around a pothole, so its
# footprint plus shy distance is lost to through traffic.
WIDTH_CLASSES = ("barricade", "street_vendor", "cart", "garbage", "pothole")

# Drivers keep the same clearance from an obstruction as from a kerb
# (Indo-HCM 5.1.2 kerb shyness, 0.25 m). Adopted assumption.
OBSTRUCTION_SHY_M = hcm.KERB_SHYNESS_M

# Capacity per metre of carriageway width implied by Indo-HCM Table 5.4
# between four-lane (7.5 m, 2700 PCU/h/dir) and six-lane (11.0 m,
# 4200 PCU/h/dir) divided roads: 1500 / 3.5 = 428.6 PCU/h per metre.
# 8- and 10-lane rows are excluded because they carry the 1-3 km signal
# spacing condition and are not comparable.
TABLE_5_4_SLOPE_PCU_PER_M = (4200 - 2700) / (11.0 - 7.5)

WIDTH_METHODS = {
    "proportional": "Usable width / total width (capacity proportional to width)",
    "table_slope":  "Loss = blocked width x 428.6 PCU/h/m (slope of Indo-HCM Table 5.4, divided roads)",
}


def union_length(intervals: List[Tuple[float, float]]) -> float:
    if not intervals:
        return 0.0
    ivs = sorted(intervals)
    total, cl, cr = 0.0, ivs[0][0], ivs[0][1]
    for l, r in ivs[1:]:
        if l <= cr:
            cr = max(cr, r)
        else:
            total += cr - cl
            cl, cr = l, r
    return total + (cr - cl)


def with_shy_distance(intervals: List[Tuple[float, float]], width_m: float,
                      shy_m: float = OBSTRUCTION_SHY_M) -> List[Tuple[float, float]]:
    """Widen each obstruction by the shy distance on both sides, clipped to
    the carriageway."""
    return [(max(0.0, l - shy_m), min(width_m, r + shy_m)) for l, r in intervals]


def effective_width(intervals: List[Tuple[float, float]], width_m: float,
                    shy_m: float = OBSTRUCTION_SHY_M) -> float:
    """Width actually usable by moving traffic. Indo-HCM 5.1.2 keeps a 0.25 m
    shy band at each kerb even on a clear road, so the clear-road effective
    width is W - 2 x 0.25. An obstruction removes its own width plus a shy
    band on each side; where it touches the kerb its shy band overlaps the
    kerb band and is not counted twice."""
    bands = [(0.0, min(shy_m, width_m)), (max(0.0, width_m - shy_m), width_m)]
    return max(width_m - union_length(bands + with_shy_distance(intervals, width_m, shy_m)), 0.0)


def width_factor(intervals: List[Tuple[float, float]], width_m: float, c_base: float,
                 divided: bool, method: str = "proportional") -> dict:
    """F_W for obstructions occupying [left, right] intervals (metres across
    the carriageway). Overlaps are merged, so shared space is never counted
    twice.
        proportional: F_W = effective width with obstructions / clear effective width
        table_slope : F_W = (C0 - lost effective width x 428.6) / C0"""
    clear = effective_width([], width_m)
    usable = effective_width(intervals, width_m)
    lost = max(clear - usable, 0.0)
    blocked_raw = min(union_length(intervals), width_m)
    if method == "table_slope" and divided:
        f = max(0.0, (c_base - lost * TABLE_5_4_SLOPE_PCU_PER_M) / c_base) if c_base > 0 else 1.0
        used = "table_slope"
    else:
        f = usable / clear if clear > 0 else 1.0
        used = "proportional"
    note = None
    if method == "table_slope" and not divided:
        note = "Table-slope method needs two divided rows of Table 5.4; proportional used for undivided."
    if intervals and usable < hcm.LANE_WIDTH_M:
        note = (note + " " if note else "") + (
            f"Usable width {usable:.2f} m is below one 3.5 m lane: the section is near blockage "
            f"and the factor is outside any calibrated range.")
    return {"F_W": f, "method": used, "obstruction_width_m": blocked_raw,
            "blocked_with_shy_m": lost, "usable_width_m": usable,
            "clear_effective_width_m": clear, "note": note}


# ------------------------------------------------------------------
# Roughness (optional). Indo-HCM Chapter 5 has no roughness model; the
# speed-roughness relation of Chapter 2 (Eq. 2.15, two-lane interurban,
# V_OS = 104 - 6.8 IRI) is borrowed in RELATIVE form, referenced to the
# base-section roughness limit IRI < 3 (Table 5B.1), and converted to
# capacity with Eq. 5.4.
#   r   = (104 - 6.8 IRI) / (104 - 6.8 x 3)      (IRI > 3, else r = 1)
#   F_R = C_lane(r x V) / C_lane(V)
# Assumptions to state: (1) an interurban speed-roughness slope applies to
# urban roads in relative form; (2) Eq. 5.4 is used outside base conditions.
# IRI is a section average (>= 100 m); one isolated pothole barely moves it.
# ------------------------------------------------------------------
BASE_IRI_LIMIT = 3.0


# Chapter 2 roads have their own capacity-roughness equations, used in the
# same relative form (CHOICE: referenced to IRI 3, as above):
#   single lane       C = 945 - 25 IRI    (Eq. 2.20)
#   intermediate lane C = 2956 - 199 IRI  (Eq. 2.19), speed V = 91 - 6.7 IRI (Eq. 2.16)
CH2_ROUGHNESS = {
    "single_lane":       {"cap": (945.0, 25.0), "eq": "Eq. 2.20", "speed": None},
    "intermediate_lane": {"cap": (2956.0, 199.0), "eq": "Eq. 2.19", "speed": (91.0, 6.7)},
}


def roughness_factor(iri_m_per_km: Optional[float], operating_speed_kmh: float,
                     road_type: Optional[str] = None) -> dict:
    if not iri_m_per_km or iri_m_per_km <= BASE_IRI_LIMIT:
        return {"F_R": 1.0, "speed_ratio": 1.0, "applied": False}
    if road_type in CH2_ROUGHNESS:
        m = CH2_ROUGHNESS[road_type]
        a, b = m["cap"]
        f = max(a - b * iri_m_per_km, 0.0) / (a - b * BASE_IRI_LIMIT)
        if m["speed"]:
            sa, sb = m["speed"]
            r = max(sa - sb * iri_m_per_km, 0.1 * sa) / (sa - sb * BASE_IRI_LIMIT)
        else:
            r = f   # CHOICE: no single-lane speed-roughness equation; speed scaled like capacity
        return {"F_R": f, "speed_ratio": r, "applied": True,
                "reduced_speed_kmh": operating_speed_kmh * r,
                "source": f"Indo-HCM {m['eq']} relative to IRI {BASE_IRI_LIMIT:g}", "note": None}
    r = (104 - 6.8 * iri_m_per_km) / (104 - 6.8 * BASE_IRI_LIMIT)
    r = max(r, 0.1)
    v0 = operating_speed_kmh
    f = hcm.lane_capacity_from_operating_speed(v0 * r) / hcm.lane_capacity_from_operating_speed(v0)
    note = None
    if v0 * r < hcm.SPEED_MODEL_RANGE_KMH[0]:
        note = (f"Reduced speed {v0 * r:.1f} km/h is below the 40 km/h validity of Eq. 5.4; "
                f"F_R is an extrapolation.")
    return {"F_R": f, "speed_ratio": r, "applied": True, "reduced_speed_kmh": v0 * r, "note": note}


# ------------------------------------------------------------------
# Pothole size (maintenance only — does not change capacity directly)
# IRC:82-2015 cl. 7.5.3.4 widths; depth cannot be measured from a photo.
# ------------------------------------------------------------------
def pothole_size_class(width_m: float) -> str:
    return "small" if width_m <= 0.20 else ("medium" if width_m <= 0.50 else "large")


# ------------------------------------------------------------------
# Indicative vehicles/h (display only). ASSUMED urban mix; capacity logic
# is entirely in PCU/h. Replace with the site's classified count.
# ------------------------------------------------------------------
ASSUMED_COMPOSITION = {"two_wheeler": 0.55, "car": 0.25, "auto": 0.10, "bus": 0.03,
                       "lcv": 0.04, "tat": 0.02, "bicycle": 0.01}


def avg_pcu_per_vehicle(road_type: str) -> float:
    pcu = hcm.pcu_values(road_type)
    return sum(s * pcu.get(k, 1.0) for k, s in ASSUMED_COMPOSITION.items()) / sum(ASSUMED_COMPOSITION.values())
