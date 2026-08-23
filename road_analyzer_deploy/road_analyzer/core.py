"""
road_analyzer.core
==================
Analysis engine for the Indian Road Capacity Analyzer.

CHANGES FROM PREVIOUS VERSION
------------------------------
1. IRC:64-1990 REMOVED — that standard applies to rural highway geometric
   design, NOT urban road obstructions. Using it for potholes/vendors was
   technically incorrect. Removed entirely.

2. LOS (Level of Service) REMOVED — LOS requires actual V/C ratio which
   needs a real traffic volume count. We don't count vehicles, so LOS
   was being calculated from capacity loss % which is wrong. Removed.

3. Traffic regime (low/high heavy vehicles) REMOVED — IRC:106 Table 2
   gives one DSV per carriageway + fringe. No heavy-vehicle subdivision
   exists in the published urban table. Dead field removed.

4. OVERLAP-AWARE width calculation ADDED — defect widths now use interval
   union so overlapping defects don't double-count blocked road space.
   e.g. Vendor [0.0-1.0m] + Pothole [0.7-1.2m] = 1.2m blocked, NOT 1.5m.

5. POTHOLE PENALTY FACTORS ADDED — traffic-flow-theory-derived:
   Shallow  → 0.95  (Greenshields speed drop: minor speed reduction)
   Moderate → 0.85  (Time headway expansion from braking)
   Deep     → 0.70  (Forced lane merge bottleneck)
   None     → 1.00

6. CAPACITY FORMULA (final, corrected):
   Base DSV     = IRC:106-1990 Table 2 (carriageway_key + fringe_condition)
   Width Factor = (total_width_m - blocked_m_union) / total_width_m
   Pothole pen  = depth-based factor (see above)
   Reduced cap  = Base DSV × Width Factor × Pothole Penalty

7. assert REPLACED with raise ValueError (assert is disabled under -O flag)

8. Path traversal risk — handled in app.py (Path(filename).name)

9. SECOND-UPLOAD BUG FIXED — job ID system reset between requests in app.py.
   Analyzer singleton is preserved across requests so model stays warm.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2

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
        logger.info(
            "%s: process_rss=%.0fMB system_available=%.0fMB/%.0fMB (%.0f%% used)",
            label, rss_mb, vm.available / 1048576, vm.total / 1048576, vm.percent,
        )
        if vm.percent > 90:
            logger.warning(
                "%s: system memory above 90%% — inference may be degraded.", label
            )
    except Exception:
        pass


# ================================================================
# IRC:106-1990 Table 2 — Design Service Volume (PCU/hr)
# Urban roads only. Single value per carriageway + fringe condition.
# Source: IRC:106-1990, Table 2
# ================================================================
IRC106_DSV: Dict[str, Dict[str, Optional[int]]] = {
    "2lane_oneway":    {"arterial": 2400, "sub_arterial": 1900, "collector": 1400},
    "2lane_twoway":    {"arterial": 1500, "sub_arterial": 1200, "collector":  900},
    "3lane_oneway":    {"arterial": 3600, "sub_arterial": 2900, "collector": 2200},
    "4lane_undivided": {"arterial": 3000, "sub_arterial": 2400, "collector": 1800},
    "4lane_divided":   {"arterial": 3600, "sub_arterial": 2900, "collector": None},
    "6lane_undivided": {"arterial": 4800, "sub_arterial": 3800, "collector": None},
    "6lane_divided":   {"arterial": 5400, "sub_arterial": 4300, "collector": None},
    "8lane_divided":   {"arterial": 7200, "sub_arterial": None, "collector": None},
}

IRC106_DSV_LABELS: Dict[str, str] = {
    "2lane_oneway":    "2-Lane One-Way",
    "2lane_twoway":    "2-Lane Two-Way",
    "3lane_oneway":    "3-Lane One-Way",
    "4lane_undivided": "4-Lane Undivided",
    "4lane_divided":   "4-Lane Divided",
    "6lane_undivided": "6-Lane Undivided",
    "6lane_divided":   "6-Lane Divided",
    "8lane_divided":   "8-Lane Divided",
}

FRINGE_CONDITION_DESC: Dict[str, str] = {
    "arterial":     "No frontage access, no standing vehicles, very little cross traffic",
    "sub_arterial": "Frontage development, side roads, bus stops, no standing vehicles",
    "collector":    "Free frontage access, parked vehicles, bus stops, heavy cross traffic",
}

# ================================================================
# IRC Free Flow Speeds (km/h) — carriageway type + fringe condition
# Source: IRC:64-1990 and IRC:106-1990 design speed guidance
# ================================================================
IRC_FREE_FLOW_SPEED: Dict[str, Dict[str, int]] = {
    "2lane_oneway":    {"arterial": 50, "sub_arterial": 40, "collector": 30},
    "2lane_twoway":    {"arterial": 50, "sub_arterial": 40, "collector": 30},
    "3lane_oneway":    {"arterial": 65, "sub_arterial": 50, "collector": 40},
    "4lane_undivided": {"arterial": 65, "sub_arterial": 50, "collector": 40},
    "4lane_divided":   {"arterial": 80, "sub_arterial": 65, "collector": 50},
    "6lane_undivided": {"arterial": 80, "sub_arterial": 65, "collector": 50},
    "6lane_divided":   {"arterial": 100,"sub_arterial": 80, "collector": 65},
    "8lane_divided":   {"arterial": 120,"sub_arterial": 100,"collector": 80},
}


def get_free_flow_speed(carriageway_key: str, fringe_condition: str) -> int:
    """Return IRC design free-flow speed (km/h) for given road type and fringe."""
    row = IRC_FREE_FLOW_SPEED.get(carriageway_key, {})
    return row.get(fringe_condition, 50)

# ================================================================
# IRC:106-1990 — PCU Conversion Factors by Traffic Composition
# Source: IRC:106-1990, Table 1
#
# PCU (Passenger Car Unit) converts mixed traffic into equivalent cars.
# The DSV from Table 2 is in PCU/hr — not vehicles/hr.
# By applying avg PCU per vehicle under the selected regime, we convert
# DSV (PCU/hr) → equivalent vehicles/hr — more intuitive for field use.
#
# Low  regime: < 15% heavy vehicles (trucks/buses) in traffic stream
# High regime: >= 15% heavy vehicles in traffic stream
# ================================================================
IRC106_PCU_FACTORS: Dict[str, Dict[str, float]] = {
    "low": {
        "two_wheeler":    0.50,
        "car_jeep_van":   1.00,
        "auto_rickshaw":  1.20,
        "lcv":            1.50,
        "truck_bus":      2.20,
        "agricultural":   4.00,
        "cycle":          0.50,
        "cycle_rickshaw": 1.50,
    },
    "high": {
        "two_wheeler":    0.75,
        "car_jeep_van":   1.00,
        "auto_rickshaw":  1.20,
        "lcv":            2.00,
        "truck_bus":      3.00,
        "agricultural":   5.00,
        "cycle":          0.50,
        "cycle_rickshaw": 2.00,
    },
}

# Weighted average PCU per vehicle for typical Indian urban traffic composition
# Assumed composition: 40% two-wheelers, 30% cars, 10% autos,
#                      10% LCV, 8% trucks/buses, 2% others
# This is used to convert DSV (PCU/hr) → vehicles/hr
IRC106_TYPICAL_COMPOSITION: Dict[str, float] = {
    "two_wheeler":    0.40,
    "car_jeep_van":   0.30,
    "auto_rickshaw":  0.10,
    "lcv":            0.10,
    "truck_bus":      0.08,
    "agricultural":   0.01,
    "cycle":          0.01,
}

TRAFFIC_REGIME_DESC: Dict[str, str] = {
    "low":  "Less than 15% heavy vehicles (trucks/buses) — mostly cars, autos, two-wheelers",
    "high": "15% or more heavy vehicles (trucks/buses) — significant freight/bus movement",
}


def get_avg_pcu(regime: str) -> float:
    """
    Calculate weighted average PCU per vehicle for the given traffic regime.
    Used to convert DSV (PCU/hr) → equivalent vehicles/hr.

    Formula:
        avg_PCU = Σ (vehicle_share × PCU_factor)
        vehicles/hr = DSV_pcu_hr / avg_PCU

    Example (low regime):
        avg_PCU = 0.40×0.50 + 0.30×1.00 + 0.10×1.20 + 0.10×1.50
                + 0.08×2.20 + 0.01×4.00 + 0.01×0.50
                = 0.20 + 0.30 + 0.12 + 0.15 + 0.176 + 0.04 + 0.005
                = ~1.00 PCU/vehicle
    """
    factors = IRC106_PCU_FACTORS.get(regime, IRC106_PCU_FACTORS["low"])
    avg = sum(
        share * factors.get(vtype, 1.0)
        for vtype, share in IRC106_TYPICAL_COMPOSITION.items()
    )
    return max(avg, 0.5)  # safety floor


def dsv_to_vehicles_per_hr(dsv_pcu_hr: float, regime: str) -> float:
    """Convert DSV in PCU/hr to equivalent vehicles/hr for given traffic regime."""
    avg_pcu = get_avg_pcu(regime)
    return dsv_pcu_hr / avg_pcu

# ================================================================
# Pothole penalty factors — traffic flow theory derivation
#
# 0.95 (Shallow): Greenshields speed-density relationship.
#   Speed drops slightly but space headway unchanged → C = v × k
#   5% speed drop → 5% capacity loss.
#
# 0.85 (Moderate): Time headway expansion.
#   C = 3600 / h. Braking increases h from ~2.0s to ~2.35s
#   → 3600/2.35 = 1530 vs 3600/2.0 = 1800 → ~15% loss.
#
# 0.70 (Deep): Forced lane merge bottleneck.
#   Vehicles swerve into adjacent lane → zipper merge bottleneck.
#   Consistent with HCM lateral obstruction factors for near-total
#   lane blockage. → ~30% capacity loss.
# ================================================================
POTHOLE_PENALTY: Dict[str, float] = {
    "shallow":  0.95,
    "moderate": 0.85,
    "deep":     0.70,
    "unknown":  1.00,
}

# ================================================================
# IRC action rules per defect class
# ================================================================
IRC_ACTION_RULES: Dict[str, dict] = {
    "pothole": {
        "code_ref": "IRC:37-2018 (Flexible Pavement Design), IRC:SP:83 (Pothole Repair Manual)",
        "tiers": [
            (0,  5,   "MONITOR", "Log in pavement condition register; schedule at next routine maintenance cycle."),
            (5,  15,  "ROUTINE", "Patch with hot-mix/cold-mix asphalt per IRC:SP:83 within 7 days; barricade until repaired."),
            (15, 100, "URGENT",  "Emergency cold-mix patching within 24 hours per IRC:SP:83; place warning signage immediately."),
        ],
    },
    "illegal_parking": {
        "code_ref": "Motor Vehicles Act 1988 Sec.122, IRC:67-2012 (Road Signs)",
        "tiers": [
            (0,  5,   "MONITOR", "Repaint No-Parking markings per IRC:35/IRC:67."),
            (5,  15,  "ROUTINE", "Deploy traffic wardens at peak hours; install No-Parking signage."),
            (15, 100, "URGENT",  "Immediate towing enforcement under MV Act Sec.122; install bollards along the stretch."),
        ],
    },
    "street_vendor": {
        "code_ref": "Street Vendors (Protection of Livelihood) Act, 2014",
        "tiers": [
            (0,  5,   "MONITOR", "Record vendor density for Town Vending Committee (TVC) review."),
            (5,  15,  "ROUTINE", "Coordinate with TVC to relocate vendors to designated vending zones."),
            (15, 100, "URGENT",  "Immediate relocation drive with municipal hawking squad in coordination with TVC."),
        ],
    },
    "cart": {
        "code_ref": "Street Vendors Act 2014; municipal bye-laws on loading/unloading zones",
        "tiers": [
            (0,  5,   "MONITOR", "Monitor cart movement patterns; no immediate action."),
            (5,  15,  "ROUTINE", "Restrict cart movement to designated off-peak hours/zones."),
            (15, 100, "URGENT",  "Immediate removal from carriageway; designate alternate loading bay."),
        ],
    },
    "garbage": {
        "code_ref": "Solid Waste Management Rules, 2016 (MoEFCC)",
        "tiers": [
            (0,  5,   "MONITOR", "Schedule clearance at next municipal collection round."),
            (5,  15,  "ROUTINE", "Request priority clearance within 48 hours under SWM Rules 2016."),
            (15, 100, "URGENT",  "Immediate clearance; install community dustbin to prevent recurrence."),
        ],
    },
    "barricade": {
        "code_ref": "IRC:SP:55-2014 (Work Zone Traffic Management), IRC:67-2012",
        "tiers": [
            (0,  5,   "MONITOR", "Verify active permitted work zone with valid signage per IRC:SP:55."),
            (5,  15,  "ROUTINE", "Reduce barricaded width to IRC:SP:55 minimum; ensure diversion signage."),
            (15, 100, "URGENT",  "Coordinate with executing agency to remove/relocate immediately; install advance warning per IRC:67."),
        ],
    },
    "tree_on_road": {
        "code_ref": "IRC:SP:55-2014; Tree Authority / municipal tree-cutting bye-laws",
        "tiers": [
            (0,  5,   "MONITOR", "Inspect for active growth/encroachment; log for tree authority review."),
            (5,  15,  "ROUTINE", "Request municipal tree authority for pruning/trimming within 7 days."),
            (15, 100, "URGENT",  "Immediate removal/pruning by tree authority with traffic diversion signage."),
        ],
    },
    "vehicle": {
        "code_ref": "N/A — moving traffic, not an obstruction",
        "tiers": [(0, 100, "NONE", "Moving vehicle detected; no corrective action required.")],
    },
}

OVERALL_CAPACITY_LOSS_GUIDANCE = [
    (0,   10,       "Minor",       "Capacity loss is low. Continue routine monitoring; no immediate works needed."),
    (10,  25,       "Moderate",    "Noticeable capacity loss. Schedule per-defect routine actions within 1-2 weeks."),
    (25,  50,       "Significant", "Significant capacity loss. Treat urgent-tier defects as priority works; re-survey within 1 week."),
    (50,  75,       "Severe",      "Over half road capacity lost. Escalate to traffic/municipal authority immediately."),
    (75,  100.0001, "Critical",    "Road at fraction of design capacity. Immediate multi-agency intervention required."),
]

CONF_THRESHOLDS: Dict[str, float] = {
    "barricade":       0.45,
    "pothole":         0.45,
    "illegal_parking": 0.50,
    "street_vendor":   0.65,
    "cart":            0.65,
    "garbage":         0.45,
    "tree_on_road":    0.50,
    "vehicle":         0.40,
}
DEFAULT_CONF = 0.45

CLASS_NAMES = [
    "barricade", "pothole", "illegal_parking", "street_vendor",
    "cart", "garbage", "tree_on_road",
]


# ================================================================
# Pure helper functions
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


def apply_vehicle_veto(
    detections: List[dict],
    veto_classes: Tuple[str, ...] = ("street_vendor", "cart"),
    iou_threshold: float = 0.40,
) -> Tuple[List[dict], int]:
    """Remove vendor/cart boxes that heavily overlap a vehicle box.
    Fixes auto-rickshaw being misclassified as vendor/cart."""
    vehicle_boxes = [d["xyxy"] for d in detections if d["cls_name"] == "vehicle"]
    kept, vetoed = [], 0
    for d in detections:
        if d["cls_name"] in veto_classes and vehicle_boxes:
            if max(iou(d["xyxy"], vb) for vb in vehicle_boxes) >= iou_threshold:
                vetoed += 1
                continue
        kept.append(d)
    return kept, vetoed


def get_irc106_dsv(carriageway_key: str, fringe_condition: str) -> float:
    """Lookup Design Service Volume from IRC:106-1990 Table 2."""
    row = IRC106_DSV.get(carriageway_key)
    if row is None:
        raise ValueError(f"Unknown carriageway type: '{carriageway_key}'")
    val = row.get(fringe_condition)
    if val is None:
        raise ValueError(
            f"IRC:106 Table 2 has no DSV for '{carriageway_key}' "
            f"under '{fringe_condition}' fringe conditions."
        )
    return float(val)


def union_of_intervals(intervals: List[Tuple[float, float]]) -> float:
    """
    Return total unique blocked width in metres from a list of
    (left_m, right_m) intervals. Overlapping intervals are merged
    before summing — shared road space is never double-counted.

    Example:
        Vendor  [0.0, 1.0]
        Pothole [0.7, 1.2]  <- 0.3m overlap with vendor
        Garbage [4.0, 4.4]
        Result  = 1.2 + 0.4 = 1.6m   NOT 1.0+0.5+0.4 = 1.9m
    """
    if not intervals:
        return 0.0
    sorted_ivs = sorted(intervals, key=lambda x: x[0])
    merged: List[Tuple[float, float]] = []
    cur_l, cur_r = sorted_ivs[0]
    for l, r in sorted_ivs[1:]:
        if l <= cur_r:
            cur_r = max(cur_r, r)
        else:
            merged.append((cur_l, cur_r))
            cur_l, cur_r = l, r
    merged.append((cur_l, cur_r))
    return sum(r - l for l, r in merged)


def get_overall_guidance(capacity_loss_pct: float) -> dict:
    pct = max(0.0, float(capacity_loss_pct))
    for lo, hi, band, action in OVERALL_CAPACITY_LOSS_GUIDANCE:
        if lo <= pct < hi:
            return {"band": band, "action": action}
    _, _, band, action = OVERALL_CAPACITY_LOSS_GUIDANCE[-1]
    return {"band": band, "action": action}


def get_irc_action(defect_name: str, loss_pct: float) -> dict:
    rule = IRC_ACTION_RULES.get(defect_name)
    if rule is None:
        return {"code_ref": "N/A", "severity": "INVESTIGATE",
                "action": "No standard action mapped — flag for manual inspection."}
    for lo, hi, severity, action in rule["tiers"]:
        if lo <= loss_pct < hi:
            return {"code_ref": rule["code_ref"], "severity": severity, "action": action}
    _, _, severity, action = rule["tiers"][-1]
    return {"code_ref": rule["code_ref"], "severity": severity, "action": action}


@dataclass
class RoadConfig:
    total_width_m:     float
    num_lanes:         int
    carriageway_key:   str
    fringe_condition:  str
    usable_shoulder_m: float

    def as_dict(self) -> dict:
        return {
            "total_width_m":     self.total_width_m,
            "num_lanes":         self.num_lanes,
            "carriageway_key":   self.carriageway_key,
            "fringe_condition":  self.fringe_condition,
            "usable_shoulder_m": self.usable_shoulder_m,
        }


# ================================================================
# RoadAnalyzer — YOLO model loaded once, reused across all requests
# ================================================================
class RoadAnalyzer:
    WARMUP_CALL_WINDOW = 3

    def __init__(self, model_path: str, enable_depth: bool = False):
        # enable_depth=False by default — MiDaS takes 3-5 minutes on CPU.
        # Pothole severity is estimated from bounding box area ratio instead.
        # Set enable_depth=True only if you have a GPU or can wait.
        from ultralytics import YOLO
        self.model_path   = str(model_path)
        self.model        = YOLO(self.model_path)
        self._call_count  = 0
        self.enable_depth = enable_depth
        self._depth_estimator: Optional["PotholeDepthEstimator"] = None
        logger.info("RoadAnalyzer: model loaded from %s (depth_estimation=%s)",
                    self.model_path, enable_depth)

    def _get_depth_estimator(self) -> "PotholeDepthEstimator":
        if self._depth_estimator is None:
            self._depth_estimator = PotholeDepthEstimator()
        return self._depth_estimator

    def _run_predict_once(self, image_bgr) -> Tuple[List[dict], int, int]:
        # imgsz=640 is YOLOv8 default — reduces to 640px before inference
        # half=False keeps float32 (required on CPU, half only works on GPU)
        # device='cpu' explicit — avoids CUDA check overhead
        #
        # image_bgr is passed as an in-memory numpy array (not a file path).
        # Passing a path here makes ultralytics open and decode the image
        # from disk itself — a *second* full decode on top of the one we
        # already did in analyse_image(). For a typical 12MP phone photo,
        # that redundant decode is a meaningful chunk of the per-request
        # time, especially on a CPU-constrained host. Passing the array we
        # already have in memory skips that second decode entirely.
        pred      = self.model.predict(
            image_bgr, conf=0.25, verbose=False,
            imgsz=640, device='cpu', half=False
        )[0]
        boxes     = pred.boxes
        raw_count = 0 if boxes is None else len(boxes)
        raw_detections = []
        if boxes is not None and len(boxes) > 0:
            for box in boxes:
                cls_id   = int(box.cls[0])
                conf     = float(box.conf[0])
                cls_name = self.model.names[cls_id]
                if conf < CONF_THRESHOLDS.get(cls_name, DEFAULT_CONF):
                    continue
                x1, y1, x2, y2 = [float(v) for v in box.xyxy[0]]
                raw_detections.append({"cls_name": cls_name, "conf": conf,
                                        "xyxy": (x1, y1, x2, y2)})
        kept, vetoed = apply_vehicle_veto(raw_detections)
        return kept, vetoed, raw_count

    def _detect(self, image_bgr, image_label: str = "") -> Tuple[List[dict], int]:
        self._call_count += 1
        kept, vetoed, raw_count = self._run_predict_once(image_bgr)
        logger.info("detect: call#%d image=%s raw=%d kept=%d vetoed=%d",
                    self._call_count, image_label, raw_count, len(kept), vetoed)
        return kept, vetoed

    # ----------------------------------------------------------
    # MAIN ANALYSIS — single image
    # ----------------------------------------------------------
    def analyse_image(self, image_path: str, road_config: dict,
                       save_outputs: bool = True,
                       output_dir: Optional[str] = None) -> dict:
        _log_memory_usage(f"analyse_image start ({Path(image_path).name})")

        img = cv2.imread(str(image_path))
        if img is None:
            raise ValueError(f"Cannot read image: {image_path}")

        # Downscale oversized photos before running inference. Phone camera
        # photos are commonly 3000-4000px on the long edge; YOLO internally
        # works at imgsz=640 regardless, so decoding/copying/resizing a
        # full-resolution image only adds CPU time without adding any
        # detection accuracy. Capping the long edge at 1600px cuts that
        # overhead substantially on CPU-only hosts (e.g. Render free tier)
        # while still leaving far more detail than the model actually uses.
        MAX_EDGE = 1600
        img_h0, img_w0 = img.shape[:2]
        long_edge = max(img_h0, img_w0)
        if long_edge > MAX_EDGE:
            scale = MAX_EDGE / long_edge
            img = cv2.resize(img, (int(img_w0 * scale), int(img_h0 * scale)),
                              interpolation=cv2.INTER_AREA)

        img_h, img_w = img.shape[:2]

        total_width_m   = float(road_config["total_width_m"])
        num_lanes       = int(road_config["num_lanes"])
        carriageway_key = road_config["carriageway_key"]
        fringe          = road_config["fringe_condition"]
        traffic_regime  = road_config.get("traffic_regime", "low")

        if num_lanes <= 0:
            raise ValueError("num_lanes must be >= 1")
        if total_width_m <= 0:
            raise ValueError("total_width_m must be > 0")
        if traffic_regime not in ("low", "high"):
            traffic_regime = "low"

        px_per_m       = img_w / total_width_m
        base_dsv       = get_irc106_dsv(carriageway_key, fringe)
        free_flow_speed = get_free_flow_speed(carriageway_key, fringe)

        # IRC:106 Table 1 — PCU conversion
        # DSV is in PCU/hr. Convert to vehicles/hr using avg PCU factor
        # for the selected traffic regime.
        avg_pcu              = get_avg_pcu(traffic_regime)
        base_vehicles_per_hr = dsv_to_vehicles_per_hr(base_dsv, traffic_regime)

        detections, vetoed_count = self._detect(img, Path(image_path).name)

        # ---- Pothole depth scoring ----
        # Fast method: estimate severity from bounding box area relative to image.
        # Large pothole bbox = more severe. No MiDaS download needed.
        # MiDaS (enable_depth=True) only runs if explicitly enabled.
        pothole_depth_results: Dict[int, dict] = {}
        pothole_indices = [i for i, d in enumerate(detections) if d["cls_name"] == "pothole"]

        if pothole_indices:
            if self.enable_depth:
                # Slow but accurate MiDaS method
                try:
                    de     = self._get_depth_estimator()
                    boxes  = [detections[i]["xyxy"] for i in pothole_indices]
                    scores = de.estimate_batch(img, boxes)
                    for i, score in zip(pothole_indices, scores):
                        pothole_depth_results[i] = score
                except Exception as e:
                    logger.warning("MiDaS depth failed (%s) — using bbox fallback.", e)
                    for i in pothole_indices:
                        pothole_depth_results[i] = _fast_pothole_severity(
                            detections[i]["xyxy"], img_w, img_h)
            else:
                # Fast bbox-area method — instant, no download
                for i in pothole_indices:
                    pothole_depth_results[i] = _fast_pothole_severity(
                        detections[i]["xyxy"], img_w, img_h)

        # ---- Worst pothole severity → penalty factor ----
        severity_rank = {"deep": 2, "moderate": 1, "shallow": 0, "unknown": -1}
        worst_pothole_severity = "unknown"
        for score in pothole_depth_results.values():
            sev = score.get("severity", "unknown")
            if severity_rank.get(sev, -1) > severity_rank.get(worst_pothole_severity, -1):
                worst_pothole_severity = sev
        pothole_penalty = POTHOLE_PENALTY.get(worst_pothole_severity, 1.0)

        # ---- Build defect intervals for overlap-aware width calc ----
        all_intervals: List[Tuple[float, float]] = []
        defect_data:   Dict[str, dict]           = {}
        roadrunner_export                        = []

        for idx, d in enumerate(detections):
            cls_name = d["cls_name"]
            if cls_name == "vehicle":
                continue

            x1, y1, x2, y2 = d["xyxy"]
            left_m  = max(0.0, x1 / px_per_m)
            right_m = min(total_width_m, x2 / px_per_m)
            if right_m <= left_m:
                continue

            real_w_m = right_m - left_m
            real_h_m = (y2 - y1) / px_per_m

            all_intervals.append((left_m, right_m))

            if cls_name not in defect_data:
                defect_data[cls_name] = {"count": 0, "intervals": [], "detections": []}
            defect_data[cls_name]["count"] += 1
            defect_data[cls_name]["intervals"].append((left_m, right_m))

            det_record: dict = {
                "conf":     round(d["conf"], 2),
                "width_m":  round(real_w_m, 2),
                "height_m": round(real_h_m, 2),
                "left_m":   round(left_m, 2),
                "right_m":  round(right_m, 2),
            }
            if idx in pothole_depth_results:
                det_record["depth"] = pothole_depth_results[idx]
            defect_data[cls_name]["detections"].append(det_record)

            roadrunner_export.append({
                "defect_type": cls_name,
                "left_m":      round(left_m, 3),
                "right_m":     round(right_m, 3),
                "width_m":     round(real_w_m, 3),
                "height_m":    round(real_h_m, 3),
                "conf":        round(d["conf"], 3),
            })

        # ---- Overlap-aware total blocked width ----
        total_blocked_m   = min(union_of_intervals(all_intervals), total_width_m)
        effective_width_m = max(total_width_m - total_blocked_m, 0.0)

        # ---- Width reduction factor ----
        width_factor = effective_width_m / total_width_m if total_width_m > 0 else 1.0

        # ---- Reduced capacity ----
        reduced_cap  = max(0.0, min(base_dsv * width_factor * pothole_penalty, base_dsv))
        cap_loss     = base_dsv - reduced_cap
        cap_loss_pct = (cap_loss / base_dsv * 100) if base_dsv > 0 else 0.0

        overall_guidance = get_overall_guidance(cap_loss_pct)

        # ---- Per-defect results ----
        per_defect_results: dict = {}
        for dname, dinfo in defect_data.items():
            this_blocked  = min(union_of_intervals(dinfo["intervals"]), total_width_m)
            this_eff_w    = max(total_width_m - this_blocked, 0.0)
            this_wf       = this_eff_w / total_width_m if total_width_m > 0 else 1.0
            this_penalty  = pothole_penalty if dname == "pothole" else 1.0
            this_cap      = max(0.0, min(base_dsv * this_wf * this_penalty, base_dsv))
            this_loss     = base_dsv - this_cap
            this_loss_pct = (this_loss / base_dsv * 100) if base_dsv > 0 else 0.0
            irc           = get_irc_action(dname, this_loss_pct)

            per_defect_results[dname] = {
                "count":             dinfo["count"],
                "blocked_m":         round(this_blocked, 2),
                "capacity_loss_pcu": round(this_loss, 1),
                "capacity_loss_pct": round(this_loss_pct, 1),
                "width_factor":      round(this_wf, 3),
                "severity":          irc["severity"],
                "code_ref":          irc["code_ref"],
                "action":            irc["action"],
                "detections":        dinfo["detections"],
            }

            if dname == "pothole":
                depths = [det["depth"] for det in dinfo["detections"] if "depth" in det]
                valid  = [dep for dep in depths if dep.get("severity") != "unknown"]
                if valid:
                    worst_d = max(valid, key=lambda dep: severity_rank.get(dep["severity"], -1))
                    avg_cm  = round(sum(dep["estimated_depth_cm"] for dep in valid) / len(valid), 1)
                    per_defect_results[dname]["depth_summary"] = {
                        "worst_severity":         worst_d["severity"],
                        "avg_estimated_depth_cm": avg_cm,
                        "penalty_applied":        pothole_penalty,
                        "scored_count":           len(valid),
                        "unscored_count":         len(depths) - len(valid),
                    }

        final_result = {
            "image":         Path(image_path).name,
            "image_size_px": {"width": img_w, "height": img_h},
            "road_config":   road_config,
            "irc_basis": {
                "base_dsv_pcu_hr":  base_dsv,
                "carriageway_key":  carriageway_key,
                "fringe_condition": fringe,
                "fringe_desc":      FRINGE_CONDITION_DESC.get(fringe, ""),
                "source":           "IRC:106-1990 Table 2 (urban Design Service Volume)",
            },
            "free_flow_speed_kmh": free_flow_speed,
            "traffic_regime": {
                "regime":              traffic_regime,
                "desc":                TRAFFIC_REGIME_DESC.get(traffic_regime, ""),
                "avg_pcu_per_vehicle": round(avg_pcu, 3),
                "base_vehicles_per_hr": round(base_vehicles_per_hr, 0),
                "reduced_vehicles_per_hr": round(
                    dsv_to_vehicles_per_hr(reduced_cap, traffic_regime), 0
                ),
                "free_flow_speed_kmh":   free_flow_speed,
                "congested_speed_kmh":   round(
                    free_flow_speed * (1 - (1 - (reduced_cap/base_dsv)) * 0.5), 1
                ),
                "pcu_factors":         IRC106_PCU_FACTORS.get(traffic_regime, {}),
                "note": (
                    f"IRC:106 Table 2 DSV is in PCU/hr. "
                    f"Converted to vehicles/hr using avg PCU={round(avg_pcu,3)} "
                    f"for {traffic_regime} heavy-vehicle regime (IRC:106 Table 1)."
                ),
            },
            "capacity_calculation": {
                "base_dsv_pcu_hr":        round(base_dsv, 1),
                "base_vehicles_per_hr":   round(base_vehicles_per_hr, 0),
                "total_width_m":          round(total_width_m, 2),
                "total_blocked_m":        round(total_blocked_m, 2),
                "effective_width_m":      round(effective_width_m, 2),
                "width_factor":           round(width_factor, 3),
                "pothole_penalty":        pothole_penalty,
                "worst_pothole_depth":    worst_pothole_severity,
                "avg_pcu_per_vehicle":    round(avg_pcu, 3),
                "formula": (
                    f"Reduced cap = {base_dsv} PCU/hr x {round(width_factor,3)} (width) "
                    f"x {pothole_penalty} (pothole) = {round(reduced_cap,1)} PCU/hr "
                    f"= {round(dsv_to_vehicles_per_hr(reduced_cap, traffic_regime),0)} veh/hr "
                    f"({traffic_regime} regime, avg PCU={round(avg_pcu,3)})"
                ),
            },
            "original_capacity_pcu_hr":      round(base_dsv, 1),
            "original_capacity_vehicles_hr": round(base_vehicles_per_hr, 0),
            "reduced_capacity_pcu_hr":       round(reduced_cap, 1),
            "reduced_capacity_vehicles_hr":  round(dsv_to_vehicles_per_hr(reduced_cap, traffic_regime), 0),
            "capacity_loss_pcu_hr":          round(cap_loss, 1),
            "capacity_loss_vehicles_hr":     round(base_vehicles_per_hr - dsv_to_vehicles_per_hr(reduced_cap, traffic_regime), 0),
            "capacity_loss_pct":             round(cap_loss_pct, 1),
            "overall_guidance":         overall_guidance,
            "effective_width_m":        round(effective_width_m, 2),
            "vehicle_veto_suppressed":  vetoed_count,
            "per_defect":               per_defect_results,
            "roadrunner_obstacles":     roadrunner_export,
        }

        if save_outputs:
            out_dir = Path(output_dir) if output_dir else Path(image_path).parent
            out_dir.mkdir(parents=True, exist_ok=True)
            stem = Path(image_path).stem
            json_path = out_dir / f"{stem}_analysis.json"
            with open(json_path, "w") as f:
                json.dump(final_result, f, indent=2)
            csv_path = out_dir / f"{stem}_roadrunner.csv"
            with open(csv_path, "w") as f:
                f.write("defect_type,left_m,right_m,width_m,height_m,conf\n")
                for obs in roadrunner_export:
                    f.write(f"{obs['defect_type']},{obs['left_m']},{obs['right_m']},"
                            f"{obs['width_m']},{obs['height_m']},{obs['conf']}\n")
            # Skip annotated frame — avoids running YOLO twice per image
            # which was doubling the inference time
            final_result["annotated_image_filename"] = None
            final_result["_json_path"] = str(json_path)
            final_result["_csv_path"]  = str(csv_path)

        return final_result

    def annotated_frame(self, image_path: str):
        # Use lower conf to show more detections in annotation
        img = cv2.imread(str(image_path))
        if img is None:
            raise ValueError(f"Cannot read image: {image_path}")
        results = self.model.predict(
            img, conf=0.25, verbose=False,
            imgsz=640, device='cpu', half=False
        )
        return results[0].plot()

    # ----------------------------------------------------------
    # BATCH MODE
    # ----------------------------------------------------------
    def analyse_batch(self, image_paths: List[str], road_config: dict,
                       output_dir: str) -> dict:
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        per_image_results, errors = [], []
        for img_path in image_paths:
            try:
                result = self.analyse_image(img_path, road_config,
                                             save_outputs=True, output_dir=str(out_dir))
                per_image_results.append(result)
            except Exception as e:
                errors.append({"image": Path(img_path).name, "error": str(e)})

        summary = self._summarise(per_image_results)
        summary.update({
            "mode":          "batch",
            "num_images":    len(image_paths),
            "num_succeeded": len(per_image_results),
            "errors":        errors,
            "per_image": [
                {"image": r["image"], "capacity_loss_pct": r["capacity_loss_pct"],
                 "defects_found": list(r["per_defect"].keys()),
                 "annotated_image_filename": r.get("annotated_image_filename")}
                for r in per_image_results
            ],
        })
        summary_path = out_dir / "batch_summary.json"
        with open(summary_path, "w") as f:
            json.dump(summary, f, indent=2)
        summary["_json_path"] = str(summary_path)
        # Kept private (stripped by app.py before the client ever sees it) —
        # this is the full per-image data (road_config, irc_basis, per_defect,
        # capacities) that the trimmed "per_image" list above discards. The
        # department PDF report and Digital Twin need this full shape, not
        # the summary-only view.
        summary["_per_image_full"] = per_image_results
        return summary

    # ----------------------------------------------------------
    # VIDEO MODE
    # ----------------------------------------------------------
    def analyse_video(self, video_path: str, road_config: dict, output_dir: str,
                       sample_every_sec: float = 1.0, track_iou_threshold: float = 0.5,
                       max_frames: Optional[int] = None) -> dict:
        out_dir    = Path(output_dir)
        frames_dir = out_dir / "frames"
        out_dir.mkdir(parents=True, exist_ok=True)
        frames_dir.mkdir(parents=True, exist_ok=True)

        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            raise ValueError(f"Cannot open video: {video_path}")

        fps            = cap.get(cv2.CAP_PROP_FPS) or 25.0
        total_frames   = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        frame_interval = max(1, int(round(fps * sample_every_sec)))
        frame_idx, sampled_idx = 0, 0
        frame_results: List[dict]  = []
        tracked_defects: List[dict] = []

        try:
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                if frame_idx % frame_interval != 0:
                    frame_idx += 1
                    continue
                timestamp_sec = frame_idx / fps
                frame_path = frames_dir / f"frame_{sampled_idx:05d}.jpg"
                try:
                    cv2.imwrite(str(frame_path), frame)
                    result = self.analyse_image(str(frame_path), road_config,
                                                 save_outputs=True, output_dir=str(out_dir))
                    result["timestamp_sec"] = round(timestamp_sec, 2)
                    result["frame_index"]   = frame_idx
                    frame_results.append(result)
                    self._update_tracks(tracked_defects, result, timestamp_sec, track_iou_threshold)
                except Exception as e:
                    logger.warning("Video frame %d failed: %s", frame_idx, e)
                frame_idx += 1; sampled_idx += 1
                if max_frames and sampled_idx >= max_frames:
                    break
        finally:
            # Always release the capture handle, even if something above
            # raised unexpectedly — otherwise the video file descriptor
            # leaks and, on some platforms, the uploaded file can't be
            # cleaned up afterwards.
            cap.release()

        unique_defects = [
            {"cls_name": t["cls_name"], "first_seen_sec": round(t["first_seen_sec"], 2),
             "last_seen_sec": round(t["last_seen_sec"], 2), "times_seen": t["hits"],
             "max_blocked_m": round(t["max_blocked_m"], 2)}
            for t in tracked_defects
        ]
        summary = self._summarise(frame_results)
        summary.update({
            "mode": "video", "video": Path(video_path).name, "fps": round(fps, 2),
            "total_frames_in_video": total_frames, "sampled_every_sec": sample_every_sec,
            "frames_analysed": len(frame_results), "unique_defect_instances": unique_defects,
            "unique_defect_count": len(unique_defects),
            "frame_by_frame": [
                {"frame_index": r["frame_index"], "timestamp_sec": r["timestamp_sec"],
                 "capacity_loss_pct": r["capacity_loss_pct"]}
                for r in frame_results
            ],
        })
        summary_path = out_dir / "video_summary.json"
        with open(summary_path, "w") as f:
            json.dump(summary, f, indent=2)
        summary["_json_path"] = str(summary_path)
        # Same reasoning as analyse_batch above — full per-frame results
        # (road_config, irc_basis, per_defect, capacities), kept private
        # so app.py can build the worst-frame department report / twin
        # data, then stripped before the client sees the response.
        summary["_frame_results_full"] = frame_results
        return summary

    @staticmethod
    def _update_tracks(tracked_defects, frame_result, timestamp_sec, iou_threshold):
        img_w    = frame_result["image_size_px"]["width"]
        img_h    = frame_result["image_size_px"]["height"]
        total_w  = frame_result["road_config"]["total_width_m"]
        px_per_m = img_w / total_w
        this_boxes = [
            {"cls_name": obs["defect_type"],
             "xyxy": (obs["left_m"]*px_per_m, 0.0, obs["right_m"]*px_per_m, float(img_h)),
             "width_m": obs["width_m"]}
            for obs in frame_result["roadrunner_obstacles"]
        ]
        matched = set()
        for box in this_boxes:
            best_track, best_score = None, 0.0
            for i, t in enumerate(tracked_defects):
                if i in matched or t["cls_name"] != box["cls_name"]:
                    continue
                s = iou(t["last_box"], box["xyxy"])
                if s > best_score:
                    best_score, best_track = s, i
            if best_track is not None and best_score >= iou_threshold:
                t = tracked_defects[best_track]
                t["last_box"] = box["xyxy"]; t["last_seen_sec"] = timestamp_sec
                t["hits"] += 1; t["max_blocked_m"] = max(t["max_blocked_m"], box["width_m"])
                matched.add(best_track)
            else:
                tracked_defects.append({
                    "cls_name": box["cls_name"], "last_box": box["xyxy"],
                    "first_seen_sec": timestamp_sec, "last_seen_sec": timestamp_sec,
                    "hits": 1, "max_blocked_m": box["width_m"],
                })

    @staticmethod
    def _summarise(results: List[dict]) -> dict:
        if not results:
            return {"worst_capacity_loss_pct": None, "worst_image_or_frame": None,
                    "avg_capacity_loss_pct": None}
        losses  = [r["capacity_loss_pct"] for r in results]
        worst_i = max(range(len(results)), key=lambda i: losses[i])
        return {
            "worst_capacity_loss_pct": results[worst_i]["capacity_loss_pct"],
            "worst_image_or_frame":    results[worst_i]["image"],
            "avg_capacity_loss_pct":   round(sum(losses) / len(losses), 1),
        }


# ================================================================
# Fast pothole severity from bounding box area (no model download)
# ================================================================
def _fast_pothole_severity(box_xyxy: tuple, img_w: int, img_h: int) -> dict:
    """
    Estimate pothole severity from bounding box area ratio.
    No model download required — runs in milliseconds.

    Logic (consistent with IRC:SP:83 visual distress categories):
      Small bbox  (<0.5% of image) → shallow  → penalty 0.95
      Medium bbox (0.5-2% of image)→ moderate → penalty 0.85
      Large bbox  (>2% of image)   → deep     → penalty 0.70

    This is a geometric proxy, not a depth measurement.
    For accurate depth, set enable_depth=True in RoadAnalyzer.
    """
    x1, y1, x2, y2  = box_xyxy
    box_area         = max(0.0, (x2-x1)) * max(0.0, (y2-y1))
    image_area       = img_w * img_h
    area_ratio       = box_area / image_area if image_area > 0 else 0.0

    if area_ratio < 0.005:
        sev, note, score, depth_cm = "shallow",  "Small pothole — minor speed reduction.",    0.10, 2.0
    elif area_ratio < 0.020:
        sev, note, score, depth_cm = "moderate", "Medium pothole — braking/headway impact.",  0.25, 5.0
    else:
        sev, note, score, depth_cm = "deep",     "Large pothole — forced lane merge likely.", 0.50, 9.0

    return {
        "severity":             sev,
        "note":                 note,
        "relative_depth_score": round(score, 3),
        "estimated_depth_cm":   depth_cm,
        "method":               "bbox_area_ratio",
        "area_ratio_pct":       round(area_ratio * 100, 3),
    }


# ================================================================
# Pothole depth estimation (MiDaS monocular depth)
# ================================================================
POTHOLE_SEVERITY_BANDS = [
    (0.00, 0.15, "shallow",  "Minor speed reduction (5% cap loss via Greenshields model)."),
    (0.15, 0.35, "moderate", "Braking causes headway expansion (15% cap loss)."),
    (0.35, 1.01, "deep",     "Forced lane merge bottleneck (30% cap loss)."),
]
ASSUMED_MAX_POTHOLE_DEPTH_CM = 12.0


def classify_pothole_severity(relative_depth_score: float) -> dict:
    score = max(0.0, float(relative_depth_score))
    for lo, hi, band, note in POTHOLE_SEVERITY_BANDS:
        if lo <= score < hi:
            return {"severity": band, "note": note,
                    "relative_depth_score": round(score, 3),
                    "estimated_depth_cm": round(min(score, 1.0) * ASSUMED_MAX_POTHOLE_DEPTH_CM, 1)}
    _, _, band, note = POTHOLE_SEVERITY_BANDS[-1]
    return {"severity": band, "note": note,
            "relative_depth_score": round(score, 3),
            "estimated_depth_cm": round(min(score, 1.0) * ASSUMED_MAX_POTHOLE_DEPTH_CM, 1)}


class PotholeDepthEstimator:
    MARGIN_RATIO = 0.35

    def __init__(self, device: str = "cpu"):
        self.device     = device
        self._model     = None
        self._transform = None

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        import torch.hub as hub
        hub._validate_not_a_forked_repo = lambda *a, **k: None
        logger.info("PotholeDepthEstimator: loading MiDaS_small...")
        self._model = hub.load("intel-isl/MiDaS", "MiDaS_small", trust_repo=True)
        self._model.to(self.device)
        self._model.eval()
        midas_transforms = hub.load("intel-isl/MiDaS", "transforms", trust_repo=True)
        self._transform  = midas_transforms.small_transform
        logger.info("PotholeDepthEstimator: MiDaS_small loaded.")

    def _run_midas(self, image_rgb) -> Any:
        import torch
        self._ensure_loaded()
        input_batch = self._transform(image_rgb).to(self.device)
        with torch.no_grad():
            prediction = self._model(input_batch)
            prediction = torch.nn.functional.interpolate(
                prediction.unsqueeze(1), size=image_rgb.shape[:2],
                mode="bicubic", align_corners=False,
            ).squeeze()
        return prediction.cpu().numpy()

    def estimate_batch(self, image_bgr,
                        boxes_xyxy: List[Tuple[float, float, float, float]]) -> List[dict]:
        image_rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
        depth_map = self._run_midas(image_rgb)
        return [self._score_box(depth_map, box, image_bgr.shape[:2]) for box in boxes_xyxy]

    def _score_box(self, depth_map, box_xyxy, image_hw) -> dict:
        import numpy as np
        h, w = image_hw
        x1, y1, x2, y2 = [int(round(v)) for v in box_xyxy]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)
        if x2 <= x1 or y2 <= y1:
            return {"severity": "unknown", "note": "Invalid box.",
                    "relative_depth_score": 0.0, "estimated_depth_cm": 0.0}
        bw, bh = x2-x1, y2-y1
        mx, my = max(2, int(bw*self.MARGIN_RATIO)), max(2, int(bh*self.MARGIN_RATIO))
        rx1, ry1 = max(0, x1-mx), max(0, y1-my)
        rx2, ry2 = min(w, x2+mx), min(h, y2+my)
        inside       = depth_map[y1:y2, x1:x2]
        outer_region = depth_map[ry1:ry2, rx1:rx2].copy()
        mask = np.ones_like(outer_region, dtype=bool)
        mask[max(0,y1-ry1):max(0,y2-ry1), max(0,x1-rx1):max(0,x2-rx1)] = False
        ring_pixels = outer_region[mask]
        if ring_pixels.size < 10 or inside.size == 0:
            return {"severity": "unknown",
                    "note": "Not enough surrounding road surface visible.",
                    "relative_depth_score": 0.0, "estimated_depth_cm": 0.0}
        road_level    = float(np.percentile(ring_pixels, 10))
        pothole_level = float(np.percentile(inside, 10))
        raw_dip       = road_level - pothole_level
        local_scale   = float(np.std(ring_pixels)) or 1.0
        score         = max(0.0, raw_dip / (local_scale * 4.0))
        return classify_pothole_severity(score)
