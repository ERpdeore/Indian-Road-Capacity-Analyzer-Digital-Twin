import logging
import math
import numpy as np
from ultralytics import YOLO
from .pothole_rectification import PotholeRectifier
from .digital_twin_engine import DigitalTwinEngine

logger = logging.getLogger(__name__)

# ==================== IRC:106-1990 TABLES ====================
# Table 2: Design Service Volume (PCU/hr) for urban roads
IRC106_DSV = {
    ("4L-D", "low"): 3500,
    ("4L-D", "medium"): 4200,
    ("4L-D", "high"): 4900,
    ("4L-U", "low"): 2800,
    ("4L-U", "medium"): 3500,
    ("4L-U", "high"): 4200,
    ("6L-D", "low"): 5600,
    ("6L-D", "medium"): 7000,
    ("6L-D", "high"): 8400,
    ("6L-U", "low"): 4200,
    ("6L-U", "medium"): 5600,
    ("6L-U", "high"): 7000,
    ("8L-D", "low"): 8400,
    ("8L-D", "medium"): 10500,
    ("8L-D", "high"): 12600,
}

# PCU factors from IRC:106-1990 Table 1
PCU_FACTORS = {
    "two_wheeler_low": 0.50,
    "two_wheeler_high": 0.75,
    "car_jeep_van_low": 1.00,
    "car_jeep_van_high": 1.00,
    "auto_rickshaw_low": 1.00,
    "auto_rickshaw_high": 1.20,
    "lcv_low": 1.00,
    "lcv_high": 1.50,
    "truck_bus_low": 1.50,
    "truck_bus_high": 3.00,
}

# ==================== MODELLING ASSUMPTIONS ====================
# NOT from IRC – explicitly flagged for calibration
DEFAULT_TRAFFIC_COMPOSITION = {
    "two_wheeler": 0.40,
    "car_jeep_van": 0.30,
    "auto_rickshaw": 0.10,
    "lcv": 0.10,
    "truck_bus": 0.10,
}  # ASSUMPTION – requires field survey

# ==================== IRC:SP:83-2018 POTHOLES ====================
POTHOLE_SEVERITY_THRESHOLDS = {
    "depth_mm": {
        "shallow": 25,    # <25 mm
        "moderate": 50,   # 25–50 mm
        "deep": 50,       # >50 mm
    },
    "area_m2": {
        "shallow": 0.1,
        "moderate": 0.5,
    }
}  # Source: IRC:SP:83-2018, Table 3.1

# ==================== MAIN ANALYSER CLASS ====================

class RoadAnalyzer:
    def __init__(self, model_path="yolov8n.pt", enable_depth=False):
        self.model = YOLO(model_path)
        self.depth_estimator = PotholeRectifier() if enable_depth else None
        self.enable_depth = enable_depth
        self.digital_twin = DigitalTwinEngine()
        logger.info("RoadAnalyzer initialised. MiDaS depth estimation: %s",
                    "ON" if enable_depth else "OFF (disabled)")

    def analyse_image(self, image, total_width_m, carriageway="4L-D",
                      fringe="medium", traffic_composition=None):
        """
        Main pipeline:
        - Detect objects with YOLO
        - Convert pixel widths to metres (assumes road spans full width)
        - Union overlapping obstructions
        - Compute reduced Design Service Volume
        - Run Greenshields simulation (Digital Model)
        """
        if traffic_composition is None:
            traffic_composition = DEFAULT_TRAFFIC_COMPOSITION

        # 1. YOLO inference
        results = self.model(image, conf=0.25, iou=0.45, imgsz=1600)[0]
        detections = []
        for box in results.boxes:
            x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
            cls = int(box.cls[0])
            conf = float(box.conf[0])
            label = self.model.names[cls]
            detections.append({
                "class": label,
                "bbox": (x1, y1, x2, y2),
                "confidence": conf,
                "width_px": x2 - x1,
            })

        # 2. Pixel‑to‑metre conversion (ASSUMPTION: road fills image width)
        img_w, img_h = image.shape[1], image.shape[0]
        px_per_m = img_w / total_width_m
        if px_per_m <= 0:
            raise ValueError("Invalid pixel‑per‑metre calibration (px_per_m <= 0)")

        # 3. Pothole severity extraction (using area proxy or depth if available)
        potholes = [d for d in detections if d["class"] == "pothole"]
        pothole_severities = []
        for p in potholes:
            x1, y1, x2, y2 = p["bbox"]
            area_px = (x2 - x1) * (y2 - y1)
            area_m2 = area_px / (px_per_m ** 2)
            depth_mm = None
            if self.enable_depth and self.depth_estimator:
                depth_mm = self.depth_estimator.estimate_depth(p["bbox"], image)
            severity = self._classify_pothole_severity(area_m2, depth_mm)
            p["severity"] = severity
            pothole_severities.append(severity)

        # 4. Vehicle‑vendor veto (heuristic to remove duplicate counting)
        detections = self._apply_vendor_veto(detections, iou_threshold=0.40)

        # 5. Compute obstruction widths in metres (union of intervals)
        intervals = []
        for d in detections:
            x1, y1, x2, y2 = d["bbox"]
            left_m = x1 / px_per_m
            right_m = x2 / px_per_m
            intervals.append((left_m, right_m))

        if intervals:
            intervals.sort()
            merged = []
            cur_l, cur_r = intervals[0]
            for l, r in intervals[1:]:
                if l <= cur_r:   # overlap
                    cur_r = max(cur_r, r)
                else:
                    merged.append((cur_l, cur_r))
                    cur_l, cur_r = l, r
            merged.append((cur_l, cur_r))
            blocked_m_union = sum(r - l for l, r in merged)
        else:
            blocked_m_union = 0.0

        # Sanity cap: obstruction cannot exceed road width
        if blocked_m_union >= total_width_m:
            logger.warning("Obstruction width (%.2f m) >= road width (%.2f m). Capping to 95%%.",
                           blocked_m_union, total_width_m)
            blocked_m_union = total_width_m * 0.95

        usable_width_m = total_width_m - blocked_m_union
        width_factor = usable_width_m / total_width_m  # always between 0 and 1

        # 6. Baseline DSV from IRC:106
        base_dsv = IRC106_DSV.get((carriageway, fringe))
        if base_dsv is None:
            raise ValueError(f"Unsupported carriageway/fringe: {carriageway}/{fringe}")

        # 7. Reduced DSV = baseline × width factor (no arbitrary pothole penalties)
        reduced_dsv = base_dsv * width_factor
        reduced_dsv = min(reduced_dsv, base_dsv)  # never exceed baseline

        # 8. Greenshields simulation (Digital Model)
        sim_result = self.digital_twin.run_simulation(
            demand_pcu=reduced_dsv,
            free_flow_speed=self._get_free_flow_speed(carriageway),
            jam_density=170,  # ASSUMPTION – see register
            duration_sec=3600
        )

        # 9. Return structured result
        return {
            "base_dsv_pcu_hr": base_dsv,
            "reduced_dsv_pcu_hr": reduced_dsv,
            "capacity_loss_percent": (1 - width_factor) * 100,
            "blocked_width_m": blocked_m_union,
            "usable_width_m": usable_width_m,
            "width_factor": width_factor,
            "pothole_severities": pothole_severities,
            "detections": detections,
            "simulation": sim_result,
            "traffic_composition_used": traffic_composition,
        }

    def _classify_pothole_severity(self, area_m2, depth_mm=None):
        """Classify severity per IRC:SP:83-2018 (depth preferred) or area proxy."""
        if depth_mm is not None and depth_mm > 0:
            if depth_mm < POTHOLE_SEVERITY_THRESHOLDS["depth_mm"]["shallow"]:
                return "shallow"
            elif depth_mm < POTHOLE_SEVERITY_THRESHOLDS["depth_mm"]["moderate"]:
                return "moderate"
            else:
                return "deep"
        else:
            # Fallback: area-based (LIMITATION – does not measure actual depth)
            if area_m2 < POTHOLE_SEVERITY_THRESHOLDS["area_m2"]["shallow"]:
                return "shallow"
            elif area_m2 < POTHOLE_SEVERITY_THRESHOLDS["area_m2"]["moderate"]:
                return "moderate"
            else:
                return "deep"

    def _apply_vendor_veto(self, detections, iou_threshold=0.40):
        """
        Remove vendor/cart detections that overlap significantly with vehicles.
        This is a heuristic to avoid double‑counting.
        """
        vendor_classes = {"vendor", "cart"}
        vehicle_classes = {"car", "bus", "truck", "motorcycle", "auto-rickshaw"}
        to_remove = set()
        for i, d1 in enumerate(detections):
            if d1["class"] not in vendor_classes:
                continue
            x1a, y1a, x2a, y2a = d1["bbox"]
            area1 = (x2a - x1a) * (y2a - y1a)
            for j, d2 in enumerate(detections):
                if i == j or d2["class"] not in vehicle_classes:
                    continue
                x1b, y1b, x2b, y2b = d2["bbox"]
                # Intersection rectangle
                ix1 = max(x1a, x1b)
                iy1 = max(y1a, y1b)
                ix2 = min(x2a, x2b)
                iy2 = min(y2a, y2b)
                if ix2 > ix1 and iy2 > iy1:
                    inter = (ix2 - ix1) * (iy2 - iy1)
                    area2 = (x2b - x1b) * (y2b - y1b)
                    union = area1 + area2 - inter
                    if union > 0:
                        iou = inter / union
                        if iou >= iou_threshold:
                            to_remove.add(i)
                            break
        return [d for i, d in enumerate(detections) if i not in to_remove]

    def _get_free_flow_speed(self, carriageway):
        """
        Approximate free‑flow speed (km/h) based on IRC:64-1990 design speeds.
        This is an interpretation, not a direct table from IRC:106.
        """
        if "8L" in carriageway:
            return 120
        elif "6L" in carriageway:
            return 100
        elif "4L" in carriageway:
            return 80
        else:
            return 60  # fallback
