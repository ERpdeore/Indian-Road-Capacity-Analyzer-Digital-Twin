import logging
import math
import numpy as np
from ultralytics import YOLO

# ===== FIX: Absolute imports (no dots) =====
from pothole_rectification import PotholeRectifier
from digital_twin_engine import DigitalTwinEngine

logger = logging.getLogger(__name__)

# ============================================================
# IRC:106-1990 TABLES (FIXED: Added 2-Lane support)
# ============================================================
IRC106_DSV = {
    # ----- 2-Lane roads (ADDED - FIXES BACKEND CRASH) -----
    ("2L-U", "low"): 1400, ("2L-U", "medium"): 1750, ("2L-U", "high"): 2100,
    ("2L-D", "low"): 1600, ("2L-D", "medium"): 2000, ("2L-D", "high"): 2400,

    # ----- 4-Lane roads -----
    ("4L-D", "low"): 3500, ("4L-D", "medium"): 4200, ("4L-D", "high"): 4900,
    ("4L-U", "low"): 2800, ("4L-U", "medium"): 3500, ("4L-U", "high"): 4200,

    # ----- 6-Lane roads -----
    ("6L-D", "low"): 5600, ("6L-D", "medium"): 7000, ("6L-D", "high"): 8400,
    ("6L-U", "low"): 4200, ("6L-U", "medium"): 5600, ("6L-U", "high"): 7000,

    # ----- 8-Lane roads -----
    ("8L-D", "low"): 8400, ("8L-D", "medium"): 10500, ("8L-D", "high"): 12600,
}

# PCU factors from IRC:106-1990 Table 1
PCU_FACTORS = {
    "two_wheeler_low": 0.50, "two_wheeler_high": 0.75,
    "car_jeep_van_low": 1.00, "car_jeep_van_high": 1.00,
    "auto_rickshaw_low": 1.00, "auto_rickshaw_high": 1.20,
    "lcv_low": 1.00, "lcv_high": 1.50,
    "truck_bus_low": 1.50, "truck_bus_high": 3.00,
}

DEFAULT_TRAFFIC_COMPOSITION = {
    "two_wheeler": 0.40, "car_jeep_van": 0.30,
    "auto_rickshaw": 0.10, "lcv": 0.10, "truck_bus": 0.10,
}

# ============================================================
# SIMULATOR (Fallback)
# ============================================================
class PythonSimulator:
    def run(self, reduced_dsv, free_flow_speed, lane_width_m, total_lanes, pothole_severities):
        engine = DigitalTwinEngine()
        result = engine.run_simulation(
            demand_pcu=reduced_dsv,
            free_flow_speed=free_flow_speed,
            jam_density=170,
            duration_sec=60
        )
        return {
            "simulation_type": "python_greenshields",
            "average_speed_kmh": result["steady_state"]["speed_kmh"],
            "density_pcu_km": result["steady_state"]["density_pcu_km"],
            "flow_pcu_hr": result["steady_state"]["flow_pcu_hr"],
            "status": "completed"
        }

# ============================================================
# MAIN ANALYSER
# ============================================================
class RoadAnalyzer:
    def __init__(self, model_path="yolov8n.pt", enable_depth=False):
        self.model = YOLO(model_path)
        self.depth_estimator = PotholeRectifier() if enable_depth else None
        self.enable_depth = enable_depth
        self.simulator = PythonSimulator()
        logger.info("RoadAnalyzer initialised. MiDaS: %s", "ENABLED" if enable_depth else "DISABLED")

    def analyse_image(self, image, total_width_m, carriageway="4L-D", fringe="medium", traffic_composition=None):
        if traffic_composition is None:
            traffic_composition = DEFAULT_TRAFFIC_COMPOSITION

        # YOLO detection
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

        img_w, img_h = image.shape[1], image.shape[0]
        px_per_m = img_w / total_width_m
        if px_per_m <= 0:
            raise ValueError("Invalid pixel calibration")

        # Lane geometry
        parts = carriageway.split('-')
        total_lanes = int(parts[0].replace('L', ''))
        lane_width_m = total_width_m / total_lanes

        lane_blocked_m = [0.0] * total_lanes
        for d in detections:
            x1, y1, x2, y2 = d["bbox"]
            left_m = x1 / px_per_m
            right_m = x2 / px_per_m
            for lane_idx in range(total_lanes):
                lane_left = lane_idx * lane_width_m
                lane_right = (lane_idx + 1) * lane_width_m
                overlap_left = max(left_m, lane_left)
                overlap_right = min(right_m, lane_right)
                if overlap_right > overlap_left:
                    lane_blocked_m[lane_idx] += (overlap_right - overlap_left)

        for i in range(total_lanes):
            lane_blocked_m[i] = min(lane_blocked_m[i], lane_width_m)

        total_blocked_m = sum(lane_blocked_m)
        if total_blocked_m > total_width_m * 0.95:
            total_blocked_m = total_width_m * 0.95

        usable_width_m = total_width_m - total_blocked_m
        width_factor = usable_width_m / total_width_m

        # Pothole severity
        pothole_severities = []
        for d in detections:
            if d["class"] == "pothole":
                x1, y1, x2, y2 = d["bbox"]
                area_px = (x2 - x1) * (y2 - y1)
                area_m2 = area_px / (px_per_m ** 2)
                depth_ratio = None
                if self.enable_depth and self.depth_estimator:
                    depth_ratio = self.depth_estimator.estimate_depth_ratio(d["bbox"], image)
                severity = self._classify_pothole_severity(area_m2, depth_ratio)
                d["severity"] = severity
                pothole_severities.append(severity)

        # Baseline DSV
        base_dsv = IRC106_DSV.get((carriageway, fringe))
        if base_dsv is None:
            raise ValueError(f"Unsupported carriageway/fringe: {carriageway}/{fringe}")

        reduced_dsv = base_dsv * width_factor
        reduced_dsv = min(reduced_dsv, base_dsv)

        # Simulator
        vf = self._get_free_flow_speed(carriageway)
        sim_result = self.simulator.run(
            reduced_dsv, vf, lane_width_m, total_lanes, pothole_severities
        )

        return {
            "base_dsv_pcu_hr": base_dsv,
            "reduced_dsv_pcu_hr": reduced_dsv,
            "capacity_loss_percent": (1 - width_factor) * 100,
            "blocked_width_m": total_blocked_m,
            "usable_width_m": usable_width_m,
            "width_factor": width_factor,
            "lane_blocked_m": lane_blocked_m,
            "lane_width_m": lane_width_m,
            "pothole_severities": pothole_severities,
            "detections": detections,
            "simulation": sim_result,
            "traffic_composition_used": traffic_composition,
        }

    def _classify_pothole_severity(self, area_m2, depth_ratio=None):
        if depth_ratio is not None and depth_ratio > 0:
            if depth_ratio < 1.1:
                return "shallow"
            elif depth_ratio < 1.3:
                return "moderate"
            else:
                return "deep"
        else:
            if area_m2 < 0.1:
                return "shallow"
            elif area_m2 < 0.5:
                return "moderate"
            else:
                return "deep"

    def _get_free_flow_speed(self, carriageway):
        if "8L" in carriageway: return 120
        elif "6L" in carriageway: return 100
        elif "4L" in carriageway: return 80
        else: return 60
