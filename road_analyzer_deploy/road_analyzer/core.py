"""
road_analyzer.core
==================
Detection + capacity engine for the Indian Road Capacity Analyzer.

Two capacities are always reported, never mixed:

  1. Indo-HCM capacity   C_HCM = C0 x F_OP x F_BS x F_AC        (Eq. 5.5)
        road_analyzer/indo_hcm.py — only what the manual provides.
  2. Extended capacity   C_EXT = C_HCM x F_W x F_R
        road_analyzer/extensions.py — project factors for obstructions
        Indo-HCM does not cover (vendors, carts, garbage, barricades,
        potholes) and optional roughness. Must be validated in the field.

Each detected object feeds exactly one factor:
    illegal_parking                          -> F_OP (Indo-HCM Tables 5.9/5.10)
    street_vendor, cart, garbage, barricade,
    pothole                                  -> F_W  (usable width)
    vehicle                                  -> none (only vetoes vendor/cart boxes)

LOS (Tables 5.6/5.7) needs V/C, so it is reported only when an observed
volume is entered.

Geometry assumption: the photo looks ALONG the road with both carriageway
edges at the image borders, so lateral position = x-pixel x width / image
width. Perspective is not corrected; obstruction widths are estimates.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2

from road_analyzer import indo_hcm as hcm
from road_analyzer import extensions as ext

logger = logging.getLogger("road_analyzer.core")

try:
    import psutil
    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False


def _log_memory_usage(label: str) -> None:
    if not _HAS_PSUTIL:
        return
    try:
        proc = psutil.Process()
        rss_mb = proc.memory_info().rss / (1024 * 1024)
        vm = psutil.virtual_memory()
        logger.info("%s: process_rss=%.0fMB system_available=%.0fMB/%.0fMB (%.0f%% used)",
                    label, rss_mb, vm.available / 1048576, vm.total / 1048576, vm.percent)
    except Exception:
        pass


# ================================================================
# Classes in models/best.pt (checked against the checkpoint):
#   0 barricade, 1 pothole, 2 illegal_parking, 3 street_vendor,
#   4 cart, 5 garbage, 6 vehicle
# "vehicle" is used only for the vendor/cart veto and is never an
# obstruction. There is no tree class in the trained model.
# ================================================================
CLASS_NAMES = ["barricade", "pothole", "illegal_parking", "street_vendor",
               "cart", "garbage", "vehicle"]
OBSTRUCTION_CLASSES = ["barricade", "pothole", "illegal_parking",
                       "street_vendor", "cart", "garbage"]
WIDTH_CLASSES = ext.WIDTH_CLASSES   # act through F_W

CONF_THRESHOLDS: Dict[str, float] = {
    "barricade":       0.45,
    "pothole":         0.45,
    "illegal_parking": 0.50,
    "street_vendor":   0.65,
    "cart":            0.65,
    "garbage":         0.45,
    "vehicle":         0.40,
}
DEFAULT_CONF = 0.45

# ================================================================
# Maintenance / enforcement actions per defect class.
# Pothole tiers key off IRC:82-2015 size class; the other classes key off
# their own capacity loss using project thresholds (5% / 15%), which are
# NOT taken from any code and are labelled as such in the output.
# ================================================================
LOSS_TIERS = [(0, 5, "MONITOR"), (5, 15, "ROUTINE"), (15, 100.0001, "URGENT")]

IRC_ACTION_RULES: Dict[str, dict] = {
    "pothole": {
        "code_ref": "IRC:82-2015 cl. 7.5.3 (potholes), cl. 5.3 (prompt rectification)",
        "by_size": {
            "small":  ("ROUTINE", "Fill with premix (cold or hot mix) per IRC:82 cl. 7.5.3.5 at the "
                                  "next maintenance round; log in the condition survey."),
            "medium": ("URGENT",  "Cut to regular shape, clean, tack coat and fill with premix per "
                                  "IRC:82 cl. 7.5.3.5. Distress affecting riding quality should be "
                                  "rectified straightaway (cl. 5.3)."),
            "large":  ("URGENT",  "Rectify straightaway (IRC:82 cl. 5.3). Check whether the cavity "
                                  "extends into the base course; if so repair the base before "
                                  "surfacing. Barricade and sign the location per IRC:SP:55."),
        },
    },
    "illegal_parking": {
        "code_ref": "Motor Vehicles Act 1988 s.122; IRC:67 (signs), IRC:35 (markings)",
        "tiers": {
            "MONITOR": "Repaint No-Parking markings and check signage.",
            "ROUTINE": "Peak-hour enforcement by traffic wardens; install No-Parking signs.",
            "URGENT":  "Towing enforcement under MV Act s.122; consider bollards on the stretch.",
        },
    },
    "street_vendor": {
        "code_ref": "Street Vendors (Protection of Livelihood and Regulation of Street Vending) Act, 2014",
        "tiers": {
            "MONITOR": "Record vendor occupancy for Town Vending Committee review.",
            "ROUTINE": "Refer to the Town Vending Committee for relocation to a vending zone.",
            "URGENT":  "Relocation drive coordinated with the Town Vending Committee.",
        },
    },
    "cart": {
        "code_ref": "Street Vendors Act, 2014; municipal bye-laws on loading/unloading",
        "tiers": {
            "MONITOR": "Monitor; no action from this survey alone.",
            "ROUTINE": "Restrict carts to designated zones / off-peak hours.",
            "URGENT":  "Remove from carriageway; designate an off-street loading bay.",
        },
    },
    "garbage": {
        "code_ref": "Solid Waste Management Rules, 2016",
        "tiers": {
            "MONITOR": "Schedule clearance in the next collection round.",
            "ROUTINE": "Request priority clearance from the SWM department.",
            "URGENT":  "Immediate clearance; provide a collection point to stop recurrence.",
        },
    },
    "barricade": {
        "code_ref": "IRC:SP:55-2014 (traffic management in work zones)",
        "tiers": {
            "MONITOR": "Verify the work zone is permitted and signed per IRC:SP:55.",
            "ROUTINE": "Reduce barricaded width to the minimum needed; add diversion signs.",
            "URGENT":  "Coordinate with the executing agency to remove/relocate the barricade.",
        },
    },
}

# Overall capacity-loss bands: project reporting thresholds, not from a code.
OVERALL_CAPACITY_LOSS_GUIDANCE = [
    (0,   10,       "Minor",       "Low capacity loss. Continue routine monitoring."),
    (10,  25,       "Moderate",    "Noticeable loss. Schedule the per-defect actions."),
    (25,  50,       "Significant", "Significant loss. Prioritise urgent-tier defects; re-survey."),
    (50,  75,       "Severe",      "Over half the capacity lost. Escalate to traffic/municipal authority."),
    (75,  100.0001, "Critical",    "Road operating at a fraction of capacity. Multi-agency action needed."),
]


# ================================================================
# Pure helpers
# ================================================================
def iou(boxA: Tuple[float, float, float, float],
        boxB: Tuple[float, float, float, float]) -> float:
    xA = max(boxA[0], boxB[0]); yA = max(boxA[1], boxB[1])
    xB = min(boxA[2], boxB[2]); yB = min(boxA[3], boxB[3])
    inter = max(0.0, xB - xA) * max(0.0, yB - yA)
    if inter == 0.0:
        return 0.0
    areaA = (boxA[2] - boxA[0]) * (boxA[3] - boxA[1])
    areaB = (boxB[2] - boxB[0]) * (boxB[3] - boxB[1])
    denom = areaA + areaB - inter
    return inter / denom if denom > 0 else 0.0


def apply_vehicle_veto(detections: List[dict],
                       veto_classes: Tuple[str, ...] = ("street_vendor", "cart"),
                       iou_threshold: float = 0.40) -> Tuple[List[dict], int]:
    """Drop vendor/cart boxes that heavily overlap a vehicle box
    (auto-rickshaws are often misread as carts/vendors)."""
    vehicle_boxes = [d["xyxy"] for d in detections if d["cls_name"] == "vehicle"]
    kept, vetoed = [], 0
    for d in detections:
        if d["cls_name"] in veto_classes and vehicle_boxes:
            if max(iou(d["xyxy"], vb) for vb in vehicle_boxes) >= iou_threshold:
                vetoed += 1
                continue
        kept.append(d)
    return kept, vetoed


def tier_from_loss(loss_pct: float) -> str:
    for lo, hi, tier in LOSS_TIERS:
        if lo <= loss_pct < hi:
            return tier
    return LOSS_TIERS[-1][2]


def get_overall_guidance(capacity_loss_pct: float) -> dict:
    pct = max(0.0, float(capacity_loss_pct))
    for lo, hi, band, action in OVERALL_CAPACITY_LOSS_GUIDANCE:
        if lo <= pct < hi:
            return {"band": band, "action": action, "basis": "project reporting thresholds"}
    _, _, band, action = OVERALL_CAPACITY_LOSS_GUIDANCE[-1]
    return {"band": band, "action": action, "basis": "project reporting thresholds"}


def get_irc_action(defect_name: str, loss_pct: float, size_class: Optional[str] = None) -> dict:
    rule = IRC_ACTION_RULES.get(defect_name)
    if rule is None:
        return {"code_ref": "N/A", "severity": "INVESTIGATE",
                "action": "No standard action mapped — flag for manual inspection.",
                "severity_basis": "unmapped class"}
    if "by_size" in rule:
        sev, action = rule["by_size"].get(size_class or "small", rule["by_size"]["small"])
        return {"code_ref": rule["code_ref"], "severity": sev, "action": action,
                "severity_basis": f"IRC:82 size class ({size_class or 'small'}, width-only proxy)"}
    tier = tier_from_loss(loss_pct)
    return {"code_ref": rule["code_ref"], "severity": tier, "action": rule["tiers"][tier],
            "severity_basis": "capacity-loss project thresholds (5% / 15%)"}


# ================================================================
# Road configuration -> capacity inputs
# ================================================================
def _opt(v) -> Optional[float]:
    return float(v) if v not in (None, "", 0, 0.0) else None


def resolve_road_inputs(road_config: dict) -> dict:
    """Validate a road_config dict and resolve every capacity input."""
    road_type = road_config.get("road_type")
    if road_type not in hcm.ROAD_TYPES:
        raise ValueError(f"Unknown road_type '{road_type}'. Valid: {list(hcm.ROAD_TYPES)}")
    width = float(road_config.get("total_width_m") or 0)
    if width <= 0:
        raise ValueError("total_width_m must be > 0")
    rt = hcm.ROAD_TYPES[road_type]
    width_method = road_config.get("width_method") or "proportional"
    if width_method not in ext.WIDTH_METHODS:
        raise ValueError(f"Unknown width_method '{width_method}'. Valid: {list(ext.WIDTH_METHODS)}")
    for name in hcm.FACTOR_TABLES:
        hcm.factor(name, road_config.get(name))          # raises on unknown keys

    notes: List[str] = []
    w = hcm.check_road_width(road_type, width)
    if w:
        notes.append(w)

    measured = _opt(road_config.get("operating_speed_kmh"))
    base = hcm.base_capacity(road_type, measured)
    notes += base["notes"]

    # Speed used by the twin and the roughness factor: the measured
    # operating speed (also on undivided roads, where it does not set C0),
    # else the speed Eq. 5.4 associates with the Table 5.4 lane capacity
    # (clamped to the 40-80 km/h validity range).
    if measured:
        v_ref, v_src = measured, "measured operating speed (base section)"
    else:
        lo, hi = hcm.SPEED_MODEL_RANGE_KMH
        v_ref = min(max(hcm.operating_speed_from_lane_capacity(rt["lane_capacity_pcu_h"]), lo), hi)
        v_src = "implied by Table 5.4 lane capacity through Eq. 5.4 (not measured)"

    return {
        "road_type": road_type, "road": rt, "total_width_m": width, "lanes": rt["lanes"],
        "divided": rt["divided"], "base": base, "c0": base["c0_pcu_h"],
        "v_ref": v_ref, "v_ref_source": v_src,
        "parking": road_config.get("on_street_parking") or "none",
        "bus_stop": road_config.get("bus_stop") or "none",
        "access_points": road_config.get("access_points") or "none",
        "iri": _opt(road_config.get("iri_m_per_km")),
        "width_method": width_method,
        "observed_volume": _opt(road_config.get("observed_volume_pcu_h")),
        "notes": notes,
    }


def compute_capacity(inputs: dict, width_intervals: List[Tuple[float, float]],
                     parking_detected: bool) -> dict:
    """Indo-HCM capacity, then the extended capacity. Pure function."""
    c0 = inputs["c0"]
    notes = []
    parking = inputs["parking"]
    if parking_detected and parking == "none":
        parking = "len_lt25"
        notes.append("Parking was detected but its intensity was not surveyed; the mildest Indo-HCM "
                     "class (Table 5.9, < 25% of length, 0.70) is assumed. Measure it on site.")
    hcm_cap = hcm.actual_capacity(c0, parking, inputs["bus_stop"], inputs["access_points"])
    c_hcm = hcm_cap["c_pcu_h"]

    fw = ext.width_factor(width_intervals, inputs["total_width_m"], c0, inputs["divided"],
                          inputs["width_method"])
    fr = ext.roughness_factor(inputs["iri"], inputs["v_ref"])
    for n in (fw.get("note"), fr.get("note")):
        if n:
            notes.append(n)
    c_ext = c_hcm * fw["F_W"] * fr["F_R"]

    out = {
        "c0": c0, "c_hcm": c_hcm, "c_ext": c_ext,
        "hcm_factors": hcm_cap["factors"], "ext_factors": {"F_W": fw["F_W"], "F_R": fr["F_R"]},
        "parking_class_used": parking, "width": fw, "roughness": fr, "notes": notes,
    }
    v = inputs["observed_volume"]
    if v is not None:
        d = inputs["divided"]
        out["los"] = {"observed_volume_pcu_h": v,
                      "vc_base": v / c0, "los_base": hcm.los_from_vc(v / c0, d),
                      "vc_hcm": v / c_hcm, "los_hcm": hcm.los_from_vc(v / c_hcm, d),
                      "vc_ext": v / c_ext if c_ext > 0 else None,   # None = fully blocked
                      "los_ext": hcm.los_from_vc(v / c_ext, d) if c_ext > 0 else "F",
                      "table": "5.7" if d else "5.6"}
    return out


# ================================================================
# RoadAnalyzer — YOLO model loaded once, reused across requests
# ================================================================
class RoadAnalyzer:
    def __init__(self, model_path: str, enable_depth: bool = False):
        # MiDaS relative depth is optional and slow on CPU; it only refines
        # the pothole size class, it never produces a depth in mm.
        from ultralytics import YOLO
        self.model_path = str(model_path)
        self.model = YOLO(self.model_path)
        self._call_count = 0
        self.enable_depth = enable_depth
        self._depth_estimator: Optional["PotholeDepthEstimator"] = None
        names = set(self.model.names.values()) if isinstance(self.model.names, dict) else set(self.model.names)
        missing = set(CLASS_NAMES) - names
        if missing:
            logger.warning("Model is missing expected classes: %s", sorted(missing))
        logger.info("RoadAnalyzer: model loaded from %s (classes=%s)", self.model_path, sorted(names))

    def _get_depth_estimator(self) -> "PotholeDepthEstimator":
        if self._depth_estimator is None:
            self._depth_estimator = PotholeDepthEstimator()
        return self._depth_estimator

    def _detect(self, image_bgr, image_label: str = "") -> Tuple[List[dict], int]:
        self._call_count += 1
        pred = self.model.predict(image_bgr, conf=0.25, verbose=False,
                                  imgsz=640, device="cpu", half=False)[0]
        boxes = pred.boxes
        raw = []
        if boxes is not None:
            for box in boxes:
                cls_name = self.model.names[int(box.cls[0])]
                conf = float(box.conf[0])
                if conf < CONF_THRESHOLDS.get(cls_name, DEFAULT_CONF):
                    continue
                raw.append({"cls_name": cls_name, "conf": conf,
                            "xyxy": tuple(float(v) for v in box.xyxy[0])})
        kept, vetoed = apply_vehicle_veto(raw)
        logger.info("detect: call#%d image=%s kept=%d vetoed=%d",
                    self._call_count, image_label, len(kept), vetoed)
        return kept, vetoed

    # ----------------------------------------------------------
    # Single image
    # ----------------------------------------------------------
    def analyse_image(self, image_path: str, road_config: dict,
                      save_outputs: bool = True, output_dir: Optional[str] = None) -> dict:
        _log_memory_usage(f"analyse_image start ({Path(image_path).name})")
        img = cv2.imread(str(image_path))
        if img is None:
            raise ValueError(f"Cannot read image: {image_path}")
        MAX_EDGE = 1600  # YOLO runs at 640 px; larger inputs only cost CPU
        h0, w0 = img.shape[:2]
        if max(h0, w0) > MAX_EDGE:
            sc = MAX_EDGE / max(h0, w0)
            img = cv2.resize(img, (int(w0 * sc), int(h0 * sc)), interpolation=cv2.INTER_AREA)
        img_h, img_w = img.shape[:2]

        inputs = resolve_road_inputs(road_config)
        W = inputs["total_width_m"]
        px_per_m = img_w / W
        detections, vetoed = self._detect(img, Path(image_path).name)

        midas: Dict[int, dict] = {}
        p_idx = [i for i, d in enumerate(detections) if d["cls_name"] == "pothole"]
        if p_idx and self.enable_depth:
            try:
                midas = dict(zip(p_idx, self._get_depth_estimator().estimate_batch(
                    img, [detections[i]["xyxy"] for i in p_idx])))
            except Exception as e:
                logger.warning("MiDaS failed (%s) — width-only pothole class.", e)

        rank = {"small": 0, "medium": 1, "large": 2}
        width_intervals: List[Tuple[float, float]] = []
        defect_data: Dict[str, dict] = {}
        rr_export = []
        worst_pothole: Optional[str] = None
        for idx, d in enumerate(detections):
            name = d["cls_name"]
            if name not in OBSTRUCTION_CLASSES:
                continue
            x1, y1, x2, y2 = d["xyxy"]
            l_m, r_m = max(0.0, x1 / px_per_m), min(W, x2 / px_per_m)
            if r_m <= l_m:
                continue
            w_m = r_m - l_m
            rec = {"conf": round(d["conf"], 2), "width_m": round(w_m, 2), "left_m": round(l_m, 2),
                   "right_m": round(r_m, 2), "bbox_px": [round(v, 1) for v in d["xyxy"]]}
            if name in WIDTH_CLASSES:
                width_intervals.append((l_m, r_m))
            if name == "pothole":
                pc = ext.pothole_size_class(w_m)
                if idx in midas:
                    rec["relative_depth_score"] = midas[idx]["relative_depth_score"]
                    if rank.get(midas[idx]["size_class"], -1) > rank[pc]:
                        pc = midas[idx]["size_class"]
                rec["size_class"] = pc
                if worst_pothole is None or rank[pc] > rank[worst_pothole]:
                    worst_pothole = pc
            e = defect_data.setdefault(name, {"count": 0, "intervals": [], "detections": []})
            e["count"] += 1
            e["intervals"].append((l_m, r_m))
            e["detections"].append(rec)
            rr_export.append({"defect_type": name, "left_m": round(l_m, 3), "right_m": round(r_m, 3),
                              "width_m": round(w_m, 3), "conf": round(d["conf"], 3),
                              "bbox_px": [round(v, 1) for v in d["xyxy"]]})

        cap = compute_capacity(inputs, width_intervals, "illegal_parking" in defect_data)
        c0, c_hcm, c_ext = cap["c0"], cap["c_hcm"], cap["c_ext"]

        # Per class: the factor that class alone would produce.
        per_defect: dict = {}
        for name, info in defect_data.items():
            if name in WIDTH_CLASSES:
                fw = ext.width_factor(info["intervals"], W, c0, inputs["divided"], inputs["width_method"])
                factor, blocked = fw["F_W"], fw["blocked_with_shy_m"]
                mech, basis = "F_W usable width (project extension)", "extension"
            elif name == "illegal_parking":
                factor = hcm.PARKING_FACTORS[cap["parking_class_used"]]["factor"]
                blocked = min(ext.union_length(info["intervals"]), W)
                mech = f"F_OP Indo-HCM Table {hcm.PARKING_FACTORS[cap['parking_class_used']]['table']}"
                basis = "Indo-HCM"
            else:
                factor, blocked, mech, basis = 1.0, 0.0, "none", "-"
            loss = (1 - factor) * 100
            irc = get_irc_action(name, loss, worst_pothole if name == "pothole" else None)
            per_defect[name] = {
                "count": info["count"], "blocked_m": round(blocked, 2), "factor": round(factor, 3),
                "mechanism": mech, "factor_basis": basis,
                "capacity_loss_pcu": round(c0 * (1 - factor), 1), "capacity_loss_pct": round(loss, 1),
                "severity": irc["severity"], "severity_basis": irc["severity_basis"],
                "code_ref": irc["code_ref"], "action": irc["action"], "detections": info["detections"],
            }
            if name == "pothole":
                cls = [x["size_class"] for x in info["detections"]]
                per_defect[name]["size_summary"] = {
                    "worst_size_class": worst_pothole,
                    "counts": {k: cls.count(k) for k in ("small", "medium", "large")},
                    "classification": "IRC:82-2015 cl. 7.5.3.4 width thresholds (depth not measured); "
                                      "used for repair priority only",
                }

        rt = inputs["road"]
        f_all = {**cap["hcm_factors"], **cap["ext_factors"]}
        fstr = lambda fs: " x ".join(f"{k} {v:.3f}" for k, v in fs.items())
        avg_pcu = ext.avg_pcu_per_vehicle(inputs["road_type"])
        result = {
            "image": Path(image_path).name,
            "image_size_px": {"width": img_w, "height": img_h},
            "road_config": {**road_config, "num_lanes": inputs["lanes"]},
            "capacity_basis": {
                "standard": hcm.SOURCE,
                "road_type": inputs["road_type"], "road_type_label": rt["label"],
                "direction_basis": rt["basis"], "divided": rt["divided"],
                "base_capacity_method": inputs["base"]["method"],
                "base_capacity_detail": inputs["base"]["detail"],
                "operating_speed_kmh": round(inputs["v_ref"], 1),
                "operating_speed_source": inputs["v_ref_source"],
                "width_method": cap["width"]["method"],
                "warnings": inputs["notes"] + cap["notes"],
            },
            "capacity_calculation": {
                "base_capacity_pcu_h": round(c0, 1),
                "indo_hcm_factors": {k: round(v, 3) for k, v in cap["hcm_factors"].items()},
                "extension_factors": {k: round(v, 3) for k, v in cap["ext_factors"].items()},
                "factors": {k: round(v, 3) for k, v in f_all.items()},
                "parking_class_used": cap["parking_class_used"],
                "roughness": {k: (round(v, 3) if isinstance(v, float) else v)
                              for k, v in cap["roughness"].items()},
                "worst_pothole_size": worst_pothole,
                "total_width_m": round(W, 2),
                "obstruction_width_m": round(cap["width"]["obstruction_width_m"], 2),
                "blocked_incl_shy_m": round(cap["width"]["blocked_with_shy_m"], 2),
                "effective_width_m": round(cap["width"]["usable_width_m"], 2),
                "formula_indo_hcm": f"C_HCM = {c0:.0f} x {fstr(cap['hcm_factors'])} = {c_hcm:.0f} PCU/h (Eq. 5.5)",
                "formula": f"C = {c_hcm:.0f} x {fstr(cap['ext_factors'])} = {c_ext:.0f} PCU/h (with extensions)",
            },
            "base_capacity_pcu_h": round(c0, 1),
            "indo_hcm_capacity_pcu_h": round(c_hcm, 1),
            "reduced_capacity_pcu_h": round(c_ext, 1),
            "capacity_loss_pcu_h": round(c0 - c_ext, 1),
            "capacity_loss_pct": round((c0 - c_ext) / c0 * 100, 1),
            "indo_hcm_loss_pct": round((c0 - c_hcm) / c0 * 100, 1),
            "dsv_los_c_ideal_pcu_h": round(c0 * hcm.DSV_VC_RATIO, 0),
            "dsv_los_c_reduced_pcu_h": round(c_ext * hcm.DSV_VC_RATIO, 0),
            "indicative_vehicles": {
                "avg_pcu_per_vehicle": round(avg_pcu, 3),
                "base_capacity_veh_h": round(c0 / avg_pcu, 0),
                "reduced_capacity_veh_h": round(c_ext / avg_pcu, 0),
                "note": "ASSUMED traffic mix (extensions.ASSUMED_COMPOSITION) with Indo-HCM Table 5.3 "
                        "PCUs. Replace with a classified count.",
            },
            "level_of_service": ({k: (round(v, 3) if isinstance(v, float) else v)
                                  for k, v in cap["los"].items()} if "los" in cap else None),
            "operating_speed_kmh": round(inputs["v_ref"], 1),
            "overall_guidance": get_overall_guidance((c0 - c_ext) / c0 * 100),
            "effective_width_m": round(cap["width"]["usable_width_m"], 2),
            "vehicle_veto_suppressed": vetoed,
            "per_defect": per_defect,
            "roadrunner_obstacles": rr_export,
        }
        if save_outputs:
            out_dir = Path(output_dir) if output_dir else Path(image_path).parent
            out_dir.mkdir(parents=True, exist_ok=True)
            stem = Path(image_path).stem
            jp = out_dir / f"{stem}_analysis.json"
            jp.write_text(json.dumps(result, indent=2))
            cp = out_dir / f"{stem}_roadrunner.csv"
            with open(cp, "w") as fh:
                fh.write("defect_type,left_m,right_m,width_m,conf\n")
                for o in rr_export:
                    fh.write(f"{o['defect_type']},{o['left_m']},{o['right_m']},{o['width_m']},{o['conf']}\n")
            result["_json_path"], result["_csv_path"] = str(jp), str(cp)
        return result

    def annotated_frame(self, image_path: str):
        img = cv2.imread(str(image_path))
        if img is None:
            raise ValueError(f"Cannot read image: {image_path}")
        return self.model.predict(img, conf=0.25, verbose=False, imgsz=640,
                                  device="cpu", half=False)[0].plot()

    # ----------------------------------------------------------
    # Batch
    # ----------------------------------------------------------
    def analyse_batch(self, image_paths: List[str], road_config: dict, output_dir: str) -> dict:
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        results, errors = [], []
        for p in image_paths:
            try:
                results.append(self.analyse_image(p, road_config, True, str(out_dir)))
            except Exception as e:
                errors.append({"image": Path(p).name, "error": str(e)})
        summary = self._summarise(results)
        summary.update({
            "mode": "batch", "road_config": road_config,
            "num_images": len(image_paths), "num_succeeded": len(results), "errors": errors,
            "per_image": [{"image": r["image"], "capacity_loss_pct": r["capacity_loss_pct"],
                           "reduced_capacity_pcu_h": r["reduced_capacity_pcu_h"],
                           "defects_found": list(r["per_defect"].keys())} for r in results],
        })
        path = out_dir / "batch_summary.json"
        path.write_text(json.dumps(summary, indent=2))
        summary["_json_path"] = str(path)
        summary["_per_image_full"] = results
        return summary

    # ----------------------------------------------------------
    # Video
    # ----------------------------------------------------------
    def analyse_video(self, video_path: str, road_config: dict, output_dir: str,
                      sample_every_sec: float = 1.0, track_iou_threshold: float = 0.3,
                      max_frames: Optional[int] = None) -> dict:
        """Samples frames and analyses each as a cross-section. Valid for a
        FIXED camera; with a moving camera every frame is a different
        location and the per-frame numbers must be read as a chainage series."""
        out_dir = Path(output_dir)
        frames_dir = out_dir / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            raise ValueError(f"Cannot open video: {video_path}")
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        interval = max(1, int(round(fps * sample_every_sec)))
        frame_idx = sampled = 0
        frames: List[dict] = []
        tracks: List[dict] = []
        try:
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                if frame_idx % interval == 0:
                    t = frame_idx / fps
                    fp = frames_dir / f"frame_{sampled:05d}.jpg"
                    try:
                        cv2.imwrite(str(fp), frame)
                        r = self.analyse_image(str(fp), road_config, True, str(out_dir))
                        r["timestamp_sec"] = round(t, 2)
                        r["frame_index"] = frame_idx
                        frames.append(r)
                        self._update_tracks(tracks, r, t, track_iou_threshold)
                    except Exception as e:
                        logger.warning("Video frame %d failed: %s", frame_idx, e)
                    sampled += 1
                    if max_frames and sampled >= max_frames:
                        break
                frame_idx += 1
        finally:
            cap.release()

        unique = [{"cls_name": t["cls_name"], "first_seen_sec": round(t["first"], 2),
                   "last_seen_sec": round(t["last"], 2), "times_seen": t["hits"],
                   "max_width_m": round(t["max_w"], 2)} for t in tracks]
        summary = self._summarise(frames)
        summary.update({
            "mode": "video", "road_config": road_config, "video": Path(video_path).name,
            "fps": round(fps, 2), "total_frames_in_video": total_frames,
            "sampled_every_sec": sample_every_sec, "frames_analysed": len(frames),
            "unique_defect_instances": unique, "unique_defect_count": len(unique),
            "frame_by_frame": [{"frame_index": r["frame_index"], "timestamp_sec": r["timestamp_sec"],
                                "capacity_loss_pct": r["capacity_loss_pct"]} for r in frames],
        })
        path = out_dir / "video_summary.json"
        path.write_text(json.dumps(summary, indent=2))
        summary["_json_path"] = str(path)
        summary["_frame_results_full"] = frames
        return summary

    @staticmethod
    def _update_tracks(tracks, frame_result, t, iou_threshold):
        """Greedy IoU tracking on the real pixel boxes (not full-height strips,
        which merged every same-class defect at a similar lateral position)."""
        matched = set()
        for obs in frame_result["roadrunner_obstacles"]:
            box = tuple(obs["bbox_px"])
            best, best_s = None, 0.0
            for i, tr in enumerate(tracks):
                if i in matched or tr["cls_name"] != obs["defect_type"]:
                    continue
                s = iou(tr["box"], box)
                if s > best_s:
                    best, best_s = i, s
            if best is not None and best_s >= iou_threshold:
                tr = tracks[best]
                tr.update(box=box, last=t, hits=tr["hits"] + 1, max_w=max(tr["max_w"], obs["width_m"]))
                matched.add(best)
            else:
                tracks.append({"cls_name": obs["defect_type"], "box": box, "first": t, "last": t,
                               "hits": 1, "max_w": obs["width_m"]})

    @staticmethod
    def _summarise(results: List[dict]) -> dict:
        if not results:
            return {"worst_capacity_loss_pct": None, "worst_image_or_frame": None,
                    "median_capacity_loss_pct": None, "bottleneck_capacity_pcu_h": None}
        losses = sorted(r["capacity_loss_pct"] for r in results)
        worst = max(results, key=lambda r: r["capacity_loss_pct"])
        n = len(losses)
        median = losses[n // 2] if n % 2 else (losses[n // 2 - 1] + losses[n // 2]) / 2
        # A stretch is limited by its weakest section, so the bottleneck
        # (minimum) capacity is the governing figure; the median is reported
        # only as a description of how widespread the loss is.
        return {
            "worst_capacity_loss_pct": worst["capacity_loss_pct"],
            "worst_image_or_frame": worst["image"],
            "median_capacity_loss_pct": round(median, 1),
            "bottleneck_capacity_pcu_h": worst["reduced_capacity_pcu_h"],
        }


# ================================================================
# Optional MiDaS relative depth (refines pothole size class only)
# ================================================================
MIDAS_SIZE_BANDS = [(0.15, "small"), (0.35, "medium"), (float("inf"), "large")]


def classify_relative_depth(score: float) -> dict:
    score = max(0.0, float(score))
    for upper, cls in MIDAS_SIZE_BANDS:
        if score < upper:
            return {"size_class": cls, "relative_depth_score": round(score, 3)}
    return {"size_class": "large", "relative_depth_score": round(score, 3)}


class PotholeDepthEstimator:
    """Monocular RELATIVE depth: unitless, scale-free. Never converted to mm."""
    MARGIN_RATIO = 0.35

    def __init__(self, device: str = "cpu"):
        self.device = device
        self._model = None
        self._transform = None

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        import torch.hub as hub
        self._model = hub.load("intel-isl/MiDaS", "MiDaS_small", trust_repo=True)
        self._model.to(self.device).eval()
        self._transform = hub.load("intel-isl/MiDaS", "transforms", trust_repo=True).small_transform

    def estimate_batch(self, image_bgr, boxes_xyxy) -> List[dict]:
        import torch
        self._ensure_loaded()
        rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
        with torch.no_grad():
            pred = self._model(self._transform(rgb).to(self.device))
            pred = torch.nn.functional.interpolate(pred.unsqueeze(1), size=rgb.shape[:2],
                                                   mode="bicubic", align_corners=False).squeeze()
        depth = pred.cpu().numpy()
        return [self._score_box(depth, b, image_bgr.shape[:2]) for b in boxes_xyxy]

    def _score_box(self, depth_map, box_xyxy, image_hw) -> dict:
        import numpy as np
        h, w = image_hw
        x1, y1, x2, y2 = [int(round(v)) for v in box_xyxy]
        x1, y1, x2, y2 = max(0, x1), max(0, y1), min(w, x2), min(h, y2)
        if x2 <= x1 or y2 <= y1:
            return {"size_class": "small", "relative_depth_score": 0.0}
        mx = max(2, int((x2 - x1) * self.MARGIN_RATIO))
        my = max(2, int((y2 - y1) * self.MARGIN_RATIO))
        rx1, ry1, rx2, ry2 = max(0, x1 - mx), max(0, y1 - my), min(w, x2 + mx), min(h, y2 + my)
        inside = depth_map[y1:y2, x1:x2]
        outer = depth_map[ry1:ry2, rx1:rx2]
        mask = np.ones_like(outer, dtype=bool)
        mask[y1 - ry1:y2 - ry1, x1 - rx1:x2 - rx1] = False
        ring = outer[mask]
        if ring.size < 10 or inside.size == 0:
            return {"size_class": "small", "relative_depth_score": 0.0}
        dip = float(np.percentile(ring, 10)) - float(np.percentile(inside, 10))
        scale = float(np.std(ring)) or 1.0
        return classify_relative_depth(max(0.0, dip / (scale * 4.0)))
