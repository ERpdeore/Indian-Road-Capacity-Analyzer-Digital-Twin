"""
speed_challan.py
-----------------
Estimates vehicle speed from road-analyzer video input and packages an
over-speeding evidence record (with plate reading) for the Traffic Dept.

Speed cannot be computed from a single frame — it needs tracking across
frames plus a real-world distance reference. This module uses two
calibration lines drawn across the carriageway at a known real-world
spacing (you already collect `total_width_m` for the capacity
calculation — reuse that plus a surveyed longitudinal distance between
the two lines, typically 10-20m, entered once per camera location).

Method: line-crossing timing (used by real fixed speed-camera systems),
not full homography — far more robust to camera angle than trying to
back out speed from bounding-box size changes.

Pipeline:
  1. Track vehicles frame-to-frame (ByteTrack via ultralytics .track())
  2. Record the frame timestamp each tracked vehicle's centroid crosses
     calibration line A, then line B
  3. speed_kmh = (line_distance_m / elapsed_seconds) * 3.6
  4. If speed_kmh > speed_limit_kmh -> extract plate (reuses
     plate_recognition.read_plate) -> build challan evidence record

Dependencies: ultralytics, opencv-python, numpy
"""

from __future__ import annotations

import cv2
import numpy as np
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from road_analyzer.plate_recognition import read_plate, PlateReading, _save_evidence_crop
# BUG FIX: this used to be a bare `from plate_recognition import ...`, an
# absolute top-level import. Since this file lives inside the
# `road_analyzer` package and app.py always imports things as
# `from road_analyzer.xyz import ...`, Python only ever has the
# `road_analyzer` package on sys.path — never `road_analyzer/` itself as
# a bare importable folder. The old line raised
# `ModuleNotFoundError: No module named 'plate_recognition'` the instant
# anything tried to import speed_challan.py.


@dataclass
class CalibrationLines:
    """Two horizontal (or perpendicular-to-flow) lines in pixel-space,
    plus the real-world distance between them in metres. Set once per
    camera/location during setup — same idea as your existing
    total_width_m / num_lanes config."""
    line_a_y: int
    line_b_y: int
    real_distance_m: float


@dataclass
class SpeedEvidence:
    track_id: int
    speed_kmh: float
    speed_limit_kmh: float
    over_limit_by_kmh: float
    plate_reading: Optional[PlateReading]
    evidence_image_path: str
    timestamp: str
    applicable_section: str = "Motor Vehicles Act 1988, Sec. 183 (Driving at excessive speed)"


class SpeedTracker:
    """Stateful tracker held across a video's frames — instantiate once
    per video job, call update() per frame, read out flagged events at
    the end (or as they occur, for streaming)."""

    def __init__(self, calib: CalibrationLines, fps: float, speed_limit_kmh: float):
        self.calib = calib
        self.fps = fps
        self.speed_limit_kmh = speed_limit_kmh
        self._crossed_a: dict[int, float] = {}   # track_id -> frame_time at line A
        self._flagged: list[SpeedEvidence] = []
        self._done_ids: set[int] = set()

    def update(self, frame: np.ndarray, frame_index: int, tracked_boxes: list[dict],
               evidence_dir: str) -> list[SpeedEvidence]:
        """
        tracked_boxes: output of model.track(frame, persist=True) reshaped to
            [{"track_id": int, "bbox": (x1,y1,x2,y2), "cls": "car"/"truck"/...}, ...]
        Returns any newly-flagged over-speed events this frame.
        """
        frame_time = frame_index / self.fps
        new_flags = []

        for box in tracked_boxes:
            tid = box["track_id"]
            if tid in self._done_ids:
                continue
            x1, y1, x2, y2 = box["bbox"]
            cy = (y1 + y2) / 2

            crossed_a = tid in self._crossed_a
            near_a = abs(cy - self.calib.line_a_y) < 6
            near_b = abs(cy - self.calib.line_b_y) < 6

            if not crossed_a and near_a:
                self._crossed_a[tid] = frame_time

            elif crossed_a and near_b:
                elapsed = frame_time - self._crossed_a[tid]
                if elapsed <= 0:
                    continue
                speed_kmh = (self.calib.real_distance_m / elapsed) * 3.6
                self._done_ids.add(tid)

                if speed_kmh > self.speed_limit_kmh:
                    plate = read_plate(frame, (x1, y1, x2, y2))
                    evidence_path = _save_evidence_crop(frame, (x1, y1, x2, y2),
                                                         evidence_dir, prefix="speed")
                    evt = SpeedEvidence(
                        track_id=tid,
                        speed_kmh=round(speed_kmh, 1),
                        speed_limit_kmh=self.speed_limit_kmh,
                        over_limit_by_kmh=round(speed_kmh - self.speed_limit_kmh, 1),
                        plate_reading=plate,
                        evidence_image_path=evidence_path,
                        timestamp=datetime.utcnow().isoformat(),
                    )
                    self._flagged.append(evt)
                    new_flags.append(evt)

        return new_flags

    @property
    def all_flagged(self) -> list[SpeedEvidence]:
        return self._flagged


def run_speed_analysis(video_path: str, yolo_model, calib: CalibrationLines,
                        speed_limit_kmh: float, evidence_dir: str) -> list[SpeedEvidence]:
    """
    Convenience wrapper matching your existing video-analysis job shape
    (core.py's video path already opens the file frame-by-frame for
    defect detection — call this in the same loop rather than opening
    the video twice).

    yolo_model: the project's already-loaded RoadAnalyzer.model (best.pt).
    This model's class list is ["barricade", "pothole", "illegal_parking",
    "street_vendor", "cart", "garbage", "tree_on_road", "vehicle"] — a
    single generic "vehicle" class (see core.py's apply_vehicle_veto),
    not per-type car/truck/bus classes. We track that class directly.
    """
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    tracker = SpeedTracker(calib, fps, speed_limit_kmh)

    frame_index = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break

        results = yolo_model.track(frame, persist=True, verbose=False, conf=0.40)
        tracked_boxes = []
        if results and results[0].boxes is not None and results[0].boxes.id is not None:
            for box, tid, cls_id in zip(results[0].boxes.xyxy.cpu().numpy(),
                                         results[0].boxes.id.cpu().numpy(),
                                         results[0].boxes.cls.cpu().numpy()):
                cls_name = yolo_model.names[int(cls_id)]
                if cls_name == "vehicle":
                    tracked_boxes.append({
                        "track_id": int(tid),
                        "bbox": tuple(int(v) for v in box),
                        "cls": cls_name,
                    })

        tracker.update(frame, frame_index, tracked_boxes, evidence_dir)
        frame_index += 1

    cap.release()
    return tracker.all_flagged
