"""
road_analyzer.core
==================
Shared analysis engine for the Road Efficiency / Capacity-Loss project.

This module contains ALL the domain logic that used to live inline in the
Colab notebook (Cell 8 of final_year_project_code_v2_IRC.ipynb):

  - IRC:106-1990 Table 2  (Design Service Volume)
  - IRC:64-1990  Table 5  (width-reduction factor)
  - IRC:106-1990 Table 1  (PCU factors)
  - Defect -> IRC/IS action mapping with severity tiers
  - Vehicle-veto post-processing (fixes auto-rickshaw -> vendor/cart confusion)
  - Per-class confidence thresholds
  - The single-image analysis function `analyse_road_complete`
  - NEW: batch-mode helper `analyse_batch`
  - NEW: video-mode helper `analyse_video`

It has NO dependency on Google Colab. Both the notebook and the FastAPI
app import this module, so the IRC logic only exists in one place.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2

# ultralytics is imported lazily inside RoadAnalyzer so that importing this
# module for, e.g., unit-testing the IRC math does not require a GPU or
# even a downloaded model.


# ================================================================
# IRC:106-1990, Table 2 — Design Service Volume (PCU/hr)
# ================================================================
IRC106_DSV = {
    "2lane_oneway":    {"arterial": 2400, "sub_arterial": 1900, "collector": 1400},
    "2lane_twoway":    {"arterial": 1500, "sub_arterial": 1200, "collector":  900},
    "3lane_oneway":    {"arterial": 3600, "sub_arterial": 2900, "collector": 2200},
    "4lane_undivided": {"arterial": 3000, "sub_arterial": 2400, "collector": 1800},
    "4lane_divided":   {"arterial": 3600, "sub_arterial": 2900, "collector": None},
    "6lane_undivided": {"arterial": 4800, "sub_arterial": 3800, "collector": None},
    "6lane_divided":   {"arterial": 5400, "sub_arterial": 4300, "collector": None},
    "8lane_divided":   {"arterial": 7200, "sub_arterial": None, "collector": None},
}

FRINGE_CONDITION_DESC = {
    "arterial":     "No frontage access, no standing vehicles, very little cross traffic",
    "sub_arterial": "Frontage development, side roads, bus stops, no standing vehicles",
    "collector":    "Free frontage access, parked vehicles, bus stops, heavy cross traffic",
}

# ---- IRC:64-1990, Table 5 — Capacity reduction for substandard lane/shoulder width
IRC64_WIDTH_REDUCTION = [
    (1.8, {3.50: 1.00, 3.25: 0.92, 3.00: 0.84}),
    (1.2, {3.50: 0.92, 3.25: 0.85, 3.00: 0.77}),
    (0.6, {3.50: 0.81, 3.25: 0.75, 3.00: 0.68}),
    (0.0, {3.50: 0.70, 3.25: 0.64, 3.00: 0.58}),
]

IRC106_PCU = {
    "low":  {"two_wheeler": 0.5,  "car": 1.0, "auto_rickshaw": 1.2, "lcv": 1.4,
             "truck_bus": 2.2, "cycle": 0.4, "cycle_rickshaw": 1.5, "hand_cart": 2.0},
    "high": {"two_wheeler": 0.75, "car": 1.0, "auto_rickshaw": 2.0, "lcv": 2.0,
             "truck_bus": 3.7, "cycle": 0.5, "cycle_rickshaw": 2.0, "hand_cart": 3.0},
}

IRC_ACTION_RULES = {
    "pothole": {
        "code_ref": "IRC:37-2018 (Flexible Pavement Design), IRC:SP:83 (Pothole Repair Manual)",
        "tiers": [
            (0, 5, "MONITOR", "Log in pavement condition register; schedule at next routine maintenance cycle."),
            (5, 15, "ROUTINE", "Patch with hot-mix/cold-mix asphalt per IRC:SP:83 within 7 days; barricade until repaired."),
            (15, 100, "URGENT", "Emergency cold-mix patching within 24 hours per IRC:SP:83; place warning signage immediately."),
        ],
    },
    "illegal_parking": {
        "code_ref": "Motor Vehicles Act 1988 Sec.122, IRC:67-2012 (Road Signs)",
        "tiers": [
            (0, 5, "MONITOR", "Repaint No-Parking markings as per IRC:35/IRC:67."),
            (5, 15, "ROUTINE", "Deploy traffic wardens at peak hours; install No-Parking signage."),
            (15, 100, "URGENT", "Immediate towing enforcement under MV Act Sec.122; install bollards along the stretch."),
        ],
    },
    "street_vendor": {
        "code_ref": "Street Vendors (Protection of Livelihood) Act, 2014",
        "tiers": [
            (0, 5, "MONITOR", "Record vendor density for Town Vending Committee (TVC) review."),
            (5, 15, "ROUTINE", "Coordinate with TVC to relocate to designated vending zones."),
            (15, 100, "URGENT", "Immediate relocation drive with municipal hawking squad in coordination with TVC."),
        ],
    },
    "cart": {
        "code_ref": "Street Vendors Act 2014; municipal bye-laws on loading/unloading zones",
        "tiers": [
            (0, 5, "MONITOR", "Monitor cart movement patterns; no immediate action."),
            (5, 15, "ROUTINE", "Restrict cart movement to designated off-peak hours/zones."),
            (15, 100, "URGENT", "Immediate removal from carriageway; designate alternate loading bay."),
        ],
    },
    "garbage": {
        "code_ref": "Solid Waste Management Rules, 2016 (MoEFCC)",
        "tiers": [
            (0, 5, "MONITOR", "Schedule clearance at next municipal collection round."),
            (5, 15, "ROUTINE", "Request priority clearance within 48 hours under SWM Rules 2016."),
            (15, 100, "URGENT", "Immediate clearance; install community dustbin to prevent recurrence."),
        ],
    },
    "barricade": {
        "code_ref": "IRC:SP:55-2014 (Work Zone Traffic Management), IRC:67-2012",
        "tiers": [
            (0, 5, "MONITOR", "Verify active permitted work zone with valid signage per IRC:SP:55."),
            (5, 15, "ROUTINE", "Reduce barricaded width to IRC:SP:55 minimum; ensure diversion signage."),
            (15, 100, "URGENT", "Coordinate with executing agency to remove/relocate immediately; install advance warning per IRC:67."),
        ],
    },
    "tree_on_road": {
        "code_ref": "IRC:SP:55-2014; Tree Authority / municipal tree-cutting bye-laws",
        "tiers": [
            (0, 5, "MONITOR", "Inspect for active growth/encroachment; log for tree authority review."),
            (5, 15, "ROUTINE", "Request municipal tree authority for pruning/trimming within 7 days."),
            (15, 100, "URGENT", "Immediate removal/pruning by tree authority with traffic diversion signage."),
        ],
    },
    "vehicle": {
        "code_ref": "N/A — moving traffic, not an obstruction",
        "tiers": [(0, 100, "NONE", "Moving vehicle detected; no corrective action required.")],
    },
}

LOS_ACTION_GUIDANCE = {
    "A": "Free flow. No intervention required; continue routine monitoring.",
    "B": "Stable flow. Continue routine maintenance per IRC:SP:19 manual.",
    "C": "Design-level flow (IRC:106 design LOS). Schedule routine-tier actions within the normal maintenance cycle.",
    "D": "Approaching unstable flow. Prioritise routine/urgent actions; re-survey within 2 weeks.",
    "E": "At/near capacity — unstable. Treat urgent-tier actions as priority works; involve traffic authority.",
    "F": "Breakdown / forced flow. Immediate multi-agency intervention (traffic police, municipal corporation, PWD).",
}

CONF_THRESHOLDS = {
    "barricade": 0.45,
    "pothole": 0.45,
    "illegal_parking": 0.50,
    "street_vendor": 0.65,
    "cart": 0.65,
    "garbage": 0.45,
    "tree_on_road": 0.50,
    "vehicle": 0.40,
}
DEFAULT_CONF = 0.45

CLASS_NAMES = [
    "barricade", "pothole", "illegal_parking", "street_vendor",
    "cart", "garbage", "vehicle",
]


# ================================================================
# Pure helper functions (IRC lookups, geometry)
# ================================================================

def iou(boxA: Tuple[float, float, float, float],
        boxB: Tuple[float, float, float, float]) -> float:
    """IoU between two boxes in (x1,y1,x2,y2) format."""
    xA = max(boxA[0], boxB[0]); yA = max(boxA[1], boxB[1])
    xB = min(boxA[2], boxB[2]); yB = min(boxA[3], boxB[3])
    inter = max(0, xB - xA) * max(0, yB - yA)
    if inter == 0:
        return 0.0
    areaA = (boxA[2] - boxA[0]) * (boxA[3] - boxA[1])
    areaB = (boxB[2] - boxB[0]) * (boxB[3] - boxB[1])
    return inter / float(areaA + areaB - inter)


def apply_vehicle_veto(detections: List[dict],
                        veto_classes=("street_vendor", "cart"),
                        iou_threshold: float = 0.40) -> Tuple[List[dict], int]:
    """Drop vendor/cart boxes that overlap a vehicle box (rickshaw fix)."""
    vehicle_boxes = [d["xyxy"] for d in detections if d["cls_name"] == "vehicle"]
    kept, vetoed = [], 0
    for d in detections:
        if d["cls_name"] in veto_classes and vehicle_boxes:
            max_iou = max(iou(d["xyxy"], vb) for vb in vehicle_boxes)
            if max_iou >= iou_threshold:
                vetoed += 1
                continue
        kept.append(d)
    return kept, vetoed


def get_irc106_dsv(carriageway_key: str, fringe_condition: str) -> float:
    row = IRC106_DSV.get(carriageway_key)
    if row is None:
        raise ValueError(f"Unknown carriageway type: {carriageway_key}")
    val = row.get(fringe_condition)
    if val is None:
        raise ValueError(
            f"IRC:106 Table 2 does not define a design service volume "
            f"for '{carriageway_key}' under '{fringe_condition}' fringe "
            f"conditions — pick a different combination.")
    return val


def get_irc64_width_factor(lane_width_m: float, usable_shoulder_m: float) -> float:
    """IRC:64-1990 Table 5 lookup, linearly interpolated across lane-width columns."""
    row = IRC64_WIDTH_REDUCTION[-1][1]
    for min_shoulder, factors in IRC64_WIDTH_REDUCTION:
        if usable_shoulder_m >= min_shoulder:
            row = factors
            break
    cols = sorted(row.keys())
    if lane_width_m <= cols[0]:
        return row[cols[0]]
    if lane_width_m >= cols[-1]:
        return row[cols[-1]]
    for i in range(len(cols) - 1):
        lo, hi = cols[i], cols[i + 1]
        if lo <= lane_width_m <= hi:
            f_lo, f_hi = row[lo], row[hi]
            t = (lane_width_m - lo) / (hi - lo)
            return f_lo + t * (f_hi - f_lo)
    return row[cols[0]]


def get_los_irc(volume_to_capacity_ratio: float) -> Tuple[str, str]:
    r = volume_to_capacity_ratio
    if r < 0.35: return "A", "Free Flow"
    elif r < 0.50: return "B", "Stable Flow"
    elif r < 0.70: return "C", "Stable Flow (IRC Design LOS)"
    elif r < 0.85: return "D", "Approaching Unstable"
    elif r < 1.00: return "E", "At/Near Capacity"
    else: return "F", "Forced / Breakdown Flow"


def get_irc_action(defect_name: str, loss_pct_this: float) -> dict:
    rule = IRC_ACTION_RULES.get(defect_name)
    if rule is None:
        return {"code_ref": "N/A", "severity": "INVESTIGATE",
                "action": "No standard action mapped — flag for manual inspection."}
    for lo, hi, severity, action in rule["tiers"]:
        if lo <= loss_pct_this < hi:
            return {"code_ref": rule["code_ref"], "severity": severity, "action": action}
    lo, hi, severity, action = rule["tiers"][-1]
    return {"code_ref": rule["code_ref"], "severity": severity, "action": action}


@dataclass
class RoadConfig:
    total_width_m: float
    num_lanes: int
    carriageway_key: str
    fringe_condition: str
    usable_shoulder_m: float
    heavy_traffic_regime: str = "high"

    def as_dict(self) -> dict:
        return {
            "total_width_m": self.total_width_m,
            "num_lanes": self.num_lanes,
            "carriageway_key": self.carriageway_key,
            "fringe_condition": self.fringe_condition,
            "usable_shoulder_m": self.usable_shoulder_m,
            "heavy_traffic_regime": self.heavy_traffic_regime,
        }


# ================================================================
# RoadAnalyzer — loads the YOLO model once, reused across calls.
# This is the key change that makes batch / video / FastAPI usage
# efficient: the old notebook code re-instantiated YOLO(model_path)
# inside the loop, which reloads weights from disk every single time.
# ================================================================
class RoadAnalyzer:
    def __init__(self, model_path: str):
        from ultralytics import YOLO  # lazy import
        self.model_path = str(model_path)
        self.model = YOLO(self.model_path)

    # ---- low-level: run detection + veto on a single image array ----
    def _detect(self, image_path: str) -> Tuple[List[dict], int]:
        pred = self.model.predict(str(image_path), conf=0.25, verbose=False)[0]
        boxes = pred.boxes
        raw_detections = []
        if boxes is not None and len(boxes) > 0:
            for box in boxes:
                cls_id = int(box.cls[0])
                conf = float(box.conf[0])
                cls_name = self.model.names[cls_id]
                threshold = CONF_THRESHOLDS.get(cls_name, DEFAULT_CONF)
                if conf < threshold:
                    continue
                x1, y1, x2, y2 = [float(v) for v in box.xyxy[0]]
                raw_detections.append({
                    "cls_name": cls_name, "conf": conf, "xyxy": (x1, y1, x2, y2),
                })
        return apply_vehicle_veto(raw_detections)

    # ---- main entry point: single image, full IRC capacity report ----
    def analyse_image(self, image_path: str, road_config: dict,
                       save_outputs: bool = True,
                       output_dir: Optional[str] = None) -> dict:
        img = cv2.imread(str(image_path))
        if img is None:
            raise ValueError(f"Cannot read image: {image_path}")
        img_h, img_w = img.shape[:2]

        total_width_m = road_config["total_width_m"]
        num_lanes = road_config["num_lanes"]
        carriageway_key = road_config["carriageway_key"]
        fringe = road_config["fringe_condition"]
        shoulder_m = road_config["usable_shoulder_m"]

        px_per_m = img_w / total_width_m
        lane_w = total_width_m / num_lanes

        dsv_total = get_irc106_dsv(carriageway_key, fringe)
        width_factor_orig = get_irc64_width_factor(lane_w, shoulder_m)
        orig_cap = dsv_total * width_factor_orig

        detections, vetoed_count = self._detect(image_path)

        defect_data: Dict[str, dict] = {}
        total_blocked = 0.0
        roadrunner_export = []

        for d in detections:
            cls_name = d["cls_name"]
            if cls_name == "vehicle":
                continue
            x1, y1, x2, y2 = d["xyxy"]
            bw_px, bh_px = x2 - x1, y2 - y1
            real_w_m = bw_px / px_per_m
            real_h_m = bh_px / px_per_m
            pos_x_m = x1 / px_per_m
            pos_y_m = y1 / px_per_m

            blocked_m = min(real_w_m, lane_w)
            total_blocked += blocked_m

            if cls_name not in defect_data:
                defect_data[cls_name] = {"count": 0, "blocked_m": 0.0, "detections": []}
            defect_data[cls_name]["count"] += 1
            defect_data[cls_name]["blocked_m"] += blocked_m
            defect_data[cls_name]["detections"].append({
                "conf": round(d["conf"], 2), "width_m": round(real_w_m, 2),
                "height_m": round(real_h_m, 2),
                "pos_x_m": round(pos_x_m, 2), "pos_y_m": round(pos_y_m, 2),
            })
            roadrunner_export.append({
                "defect_type": cls_name, "pos_x_m": round(pos_x_m, 3),
                "pos_y_m": round(pos_y_m, 3), "width_m": round(real_w_m, 3),
                "height_m": round(real_h_m, 3), "conf": round(d["conf"], 3),
            })

        total_blocked = min(total_blocked, total_width_m)
        effective_width = max(total_width_m - total_blocked, 0.5)
        eff_lane_w = effective_width / num_lanes
        eff_shoulder_m = max(shoulder_m - 0, 0)

        width_factor_red = get_irc64_width_factor(eff_lane_w, eff_shoulder_m)
        red_cap = dsv_total * width_factor_red
        red_cap = min(red_cap, orig_cap)
        assert effective_width > 0, "Effective width computed as <= 0 — check inputs."

        cap_loss = orig_cap - red_cap
        cap_loss_pct = (cap_loss / orig_cap) * 100 if orig_cap > 0 else 0.0
        vc_ratio = cap_loss_pct / 100.0
        los, los_desc = get_los_irc(vc_ratio)
        los_action = LOS_ACTION_GUIDANCE.get(los, "")

        per_defect_results = {}
        for dname, dinfo in defect_data.items():
            blocked_this = min(dinfo["blocked_m"], total_width_m)
            eff_w_this = max(total_width_m - blocked_this, 0.5)
            wf_this = get_irc64_width_factor(eff_w_this / num_lanes, eff_shoulder_m)
            cap_this = min(dsv_total * wf_this, orig_cap)
            loss_this = orig_cap - cap_this
            loss_pct_this = (loss_this / orig_cap) * 100 if orig_cap > 0 else 0.0
            irc = get_irc_action(dname, loss_pct_this)
            per_defect_results[dname] = {
                "count": dinfo["count"],
                "blocked_m": round(dinfo["blocked_m"], 2),
                "capacity_loss_pcu": round(loss_this, 1),
                "capacity_loss_pct": round(loss_pct_this, 1),
                "severity": irc["severity"],
                "code_ref": irc["code_ref"],
                "action": irc["action"],
            }

        final_result = {
            "image": Path(image_path).name,
            "image_size_px": {"width": img_w, "height": img_h},
            "road_config": road_config,
            "irc_basis": {
                "design_service_volume_pcu_hr": dsv_total,
                "carriageway_key": carriageway_key,
                "fringe_condition": fringe,
                "fringe_condition_desc": FRINGE_CONDITION_DESC.get(fringe, ""),
                "source": "IRC:106-1990 Table 2 (urban DSV), IRC:64-1990 Table 5 (width reduction)",
            },
            "original_capacity_pcu_hr": round(orig_cap, 1),
            "reduced_capacity_pcu_hr": round(red_cap, 1),
            "capacity_loss_pcu_hr": round(cap_loss, 1),
            "capacity_loss_pct": round(cap_loss_pct, 1),
            "level_of_service": los,
            "level_of_service_desc": los_desc,
            "los_action": los_action,
            "effective_width_m": round(effective_width, 2),
            "vehicle_veto_suppressed": vetoed_count,
            "per_defect": per_defect_results,
            "roadrunner_obstacles": roadrunner_export,
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
                f.write("defect_type,pos_x_m,pos_y_m,width_m,height_m,conf\n")
                for obs in roadrunner_export:
                    f.write(f"{obs['defect_type']},{obs['pos_x_m']},{obs['pos_y_m']},"
                            f"{obs['width_m']},{obs['height_m']},{obs['conf']}\n")
            final_result["_json_path"] = str(json_path)
            final_result["_csv_path"] = str(csv_path)

        return final_result

    def annotated_frame(self, image_path: str):
        """Return a BGR numpy array with YOLO boxes drawn (for previews/video)."""
        results = self.model.predict(source=str(image_path), conf=0.25,
                                      save=False, verbose=False)
        return results[0].plot()

    # ============================================================
    # NEW — BATCH MODE
    # ============================================================
    def analyse_batch(self, image_paths: List[str], road_config: dict,
                       output_dir: str) -> dict:
        """
        Run analyse_image() over many images that all share the same
        road_config (e.g. a folder of photos taken along the same
        stretch of road), and produce one combined summary on top of
        the per-image JSON files.
        """
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        per_image_results = []
        errors = []
        for img_path in image_paths:
            try:
                result = self.analyse_image(
                    img_path, road_config, save_outputs=True, output_dir=str(out_dir)
                )
                per_image_results.append(result)
            except Exception as e:
                errors.append({"image": Path(img_path).name, "error": str(e)})

        summary = self._summarise(per_image_results)
        summary["mode"] = "batch"
        summary["num_images"] = len(image_paths)
        summary["num_succeeded"] = len(per_image_results)
        summary["errors"] = errors
        summary["per_image"] = [
            {
                "image": r["image"],
                "capacity_loss_pct": r["capacity_loss_pct"],
                "level_of_service": r["level_of_service"],
                "defects_found": list(r["per_defect"].keys()),
            }
            for r in per_image_results
        ]

        summary_path = out_dir / "batch_summary.json"
        with open(summary_path, "w") as f:
            json.dump(summary, f, indent=2)
        summary["_json_path"] = str(summary_path)
        return summary

    # ============================================================
    # NEW — VIDEO MODE
    # ============================================================
    def analyse_video(self, video_path: str, road_config: dict,
                       output_dir: str, sample_every_sec: float = 1.0,
                       track_iou_threshold: float = 0.5,
                       max_frames: Optional[int] = None) -> dict:
        """
        Sample a road video at `sample_every_sec` intervals, run the
        full IRC capacity analysis on each sampled frame, and track
        defects across consecutive sampled frames (simple greedy IoU
        matching, same trick as apply_vehicle_veto) so a pothole that
        is visible across many frames is reported ONCE in the
        aggregated summary instead of being double / triple counted.

        Returns an aggregated report: worst-observed capacity loss,
        the unique defect instances found across the whole clip, and
        a frame-by-frame breakdown (saved alongside per-frame JSONs).
        """
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        frames_dir = out_dir / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)

        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            raise ValueError(f"Cannot open video: {video_path}")

        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        frame_interval = max(1, int(round(fps * sample_every_sec)))

        frame_idx = 0
        sampled_idx = 0
        frame_results = []
        # tracked_defects: list of {"cls_name", "last_box", "first_seen_sec",
        #                           "last_seen_sec", "max_blocked_m", "hits"}
        tracked_defects: List[dict] = []

        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if frame_idx % frame_interval != 0:
                frame_idx += 1
                continue

            timestamp_sec = frame_idx / fps
            frame_path = frames_dir / f"frame_{sampled_idx:05d}.jpg"
            cv2.imwrite(str(frame_path), frame)

            try:
                result = self.analyse_image(
                    str(frame_path), road_config,
                    save_outputs=True, output_dir=str(out_dir)
                )
            except Exception as e:
                frame_idx += 1
                sampled_idx += 1
                if max_frames and sampled_idx >= max_frames:
                    break
                continue

            result["timestamp_sec"] = round(timestamp_sec, 2)
            result["frame_index"] = frame_idx
            frame_results.append(result)

            # ---- cross-frame tracking (greedy IoU match per class) ----
            self._update_tracks(tracked_defects, result, timestamp_sec,
                                 track_iou_threshold)

            frame_idx += 1
            sampled_idx += 1
            if max_frames and sampled_idx >= max_frames:
                break

        cap.release()

        unique_defects = [
            {
                "cls_name": t["cls_name"],
                "first_seen_sec": round(t["first_seen_sec"], 2),
                "last_seen_sec": round(t["last_seen_sec"], 2),
                "times_seen": t["hits"],
                "max_blocked_m": round(t["max_blocked_m"], 2),
            }
            for t in tracked_defects
        ]

        summary = self._summarise(frame_results)
        summary["mode"] = "video"
        summary["video"] = Path(video_path).name
        summary["fps"] = round(fps, 2)
        summary["total_frames_in_video"] = total_frames
        summary["sampled_every_sec"] = sample_every_sec
        summary["frames_analysed"] = len(frame_results)
        summary["unique_defect_instances"] = unique_defects
        summary["unique_defect_count"] = len(unique_defects)
        summary["frame_by_frame"] = [
            {
                "frame_index": r["frame_index"],
                "timestamp_sec": r["timestamp_sec"],
                "capacity_loss_pct": r["capacity_loss_pct"],
                "level_of_service": r["level_of_service"],
            }
            for r in frame_results
        ]

        summary_path = out_dir / "video_summary.json"
        with open(summary_path, "w") as f:
            json.dump(summary, f, indent=2)
        summary["_json_path"] = str(summary_path)
        return summary

    @staticmethod
    def _update_tracks(tracked_defects: List[dict], frame_result: dict,
                        timestamp_sec: float, iou_threshold: float) -> None:
        """
        Greedy per-class IoU matching between this frame's detections
        and existing tracks. Boxes are reconstructed in pixel space
        from the metre-based roadrunner export using the frame's own
        px_per_m, since that's what's available post-analysis.
        """
        img_w = frame_result["image_size_px"]["width"]
        total_width_m = frame_result["road_config"]["total_width_m"]
        px_per_m = img_w / total_width_m

        this_frame_boxes = []
        for obs in frame_result["roadrunner_obstacles"]:
            x1 = obs["pos_x_m"] * px_per_m
            y1 = obs["pos_y_m"] * px_per_m
            x2 = x1 + obs["width_m"] * px_per_m
            y2 = y1 + obs["height_m"] * px_per_m
            this_frame_boxes.append({
                "cls_name": obs["defect_type"],
                "xyxy": (x1, y1, x2, y2),
                "width_m": obs["width_m"],
            })

        matched_track_ids = set()
        for box in this_frame_boxes:
            best_track = None
            best_iou = 0.0
            for i, t in enumerate(tracked_defects):
                if i in matched_track_ids:
                    continue
                if t["cls_name"] != box["cls_name"]:
                    continue
                score = iou(t["last_box"], box["xyxy"])
                if score > best_iou:
                    best_iou = score
                    best_track = i
            if best_track is not None and best_iou >= iou_threshold:
                t = tracked_defects[best_track]
                t["last_box"] = box["xyxy"]
                t["last_seen_sec"] = timestamp_sec
                t["hits"] += 1
                t["max_blocked_m"] = max(t["max_blocked_m"], box["width_m"])
                matched_track_ids.add(best_track)
            else:
                tracked_defects.append({
                    "cls_name": box["cls_name"],
                    "last_box": box["xyxy"],
                    "first_seen_sec": timestamp_sec,
                    "last_seen_sec": timestamp_sec,
                    "hits": 1,
                    "max_blocked_m": box["width_m"],
                })

    @staticmethod
    def _summarise(results: List[dict]) -> dict:
        if not results:
            return {
                "worst_capacity_loss_pct": None,
                "worst_level_of_service": None,
                "avg_capacity_loss_pct": None,
            }
        losses = [r["capacity_loss_pct"] for r in results]
        worst_idx = max(range(len(results)), key=lambda i: losses[i])
        return {
            "worst_capacity_loss_pct": results[worst_idx]["capacity_loss_pct"],
            "worst_level_of_service": results[worst_idx]["level_of_service"],
            "worst_image_or_frame": results[worst_idx]["image"],
            "avg_capacity_loss_pct": round(sum(losses) / len(losses), 1),
        }
