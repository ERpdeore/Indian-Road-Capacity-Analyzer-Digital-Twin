"""
footpath_pedestrian.py
------------------------
Municipal Department module: detects pedestrians and determines whether
they are (a) walking on the carriageway because no footpath exists, or
(b) forced onto the carriageway because an existing footpath is
encroached (parked vehicles / vendors / carts sitting on it).

Two things this module needs that core.py doesn't currently track:

1. A pedestrian detector. Your custom best.pt is trained on 7
   defect classes and won't reliably detect people. Cheapest fix:
   run a second, generic pretrained YOLOv8n (COCO weights, class
   'person') on the same frame — small model, fast on CPU, no
   retraining needed. Swap for a class added to best.pt later if you
   want a single-pass model.

2. A footpath ROI. This can't be inferred from a single photo without
   either a segmentation model or camera calibration. Simplest
   reliable approach for a capstone: a one-time per-camera/location
   setup step where an operator marks the footpath polygon(s) in the
   frame (stored alongside that location's config, same idea as your
   existing total_width_m / num_lanes per-request config). No footpath
   polygon on file for a location = treated as "no footpath present".

Dependencies: ultralytics, opencv-python, numpy, shapely
    pip install shapely
"""

from __future__ import annotations

import numpy as np
from dataclasses import dataclass
from typing import Optional
from shapely.geometry import Polygon, box as shapely_box

PEDESTRIAN_MODEL_NAME = "yolov8n.pt"   # generic COCO weights, class 15... check id for 'person'
ENCROACHMENT_IOU_THRESHOLD = 0.15      # obstruction footprint overlapping footpath ROI


@dataclass
class FootpathFinding:
    finding_type: str              # "no_footpath_pedestrians_on_carriageway"
                                    # | "footpath_encroached"
                                    # | "footpath_clear"
    location: str
    pedestrian_count_on_carriageway: int
    encroaching_defect_classes: list[str]
    recommendation: str
    irc_reference: str
    legal_reference: str = ""


_pedestrian_model = None


def _get_pedestrian_model():
    global _pedestrian_model
    if _pedestrian_model is None:
        from ultralytics import YOLO
        _pedestrian_model = YOLO(PEDESTRIAN_MODEL_NAME)
    return _pedestrian_model


def detect_pedestrians(frame: np.ndarray) -> list[tuple[int, int, int, int]]:
    model = _get_pedestrian_model()
    results = model(frame, verbose=False)
    boxes = []
    if results and results[0].boxes is not None:
        for b, cls_id in zip(results[0].boxes.xyxy.cpu().numpy(),
                              results[0].boxes.cls.cpu().numpy()):
            if model.names[int(cls_id)] == "person":
                boxes.append(tuple(int(v) for v in b))
    return boxes


def analyze_footpath(frame: np.ndarray,
                      other_defects: list[dict],
                      footpath_polygon_px: Optional[list[tuple[int, int]]],
                      carriageway_polygon_px: list[tuple[int, int]],
                      location: str) -> FootpathFinding:
    """
    other_defects: core.py's raw detections for this frame, filtered to
        classes {"illegal_parking", "street_vendor", "cart", "garbage",
        "barricade"} — each item shaped {"bbox": [x1,y1,x2,y2], "class": str}
    footpath_polygon_px: operator-marked footpath ROI for this camera/
        location, or None if no footpath exists there
    carriageway_polygon_px: the drivable-road ROI for this camera/location
        (needed to tell "pedestrian on road" from "pedestrian on private land")
    """
    pedestrian_boxes = detect_pedestrians(frame)
    carriageway_poly = Polygon(carriageway_polygon_px)

    peds_on_carriageway = 0
    for (x1, y1, x2, y2) in pedestrian_boxes:
        foot_point_x = (x1 + x2) / 2
        foot_point_y = y2  # feet, not centroid — where they're actually standing
        if carriageway_poly.contains(Polygon([(foot_point_x - 1, foot_point_y - 1),
                                               (foot_point_x + 1, foot_point_y - 1),
                                               (foot_point_x + 1, foot_point_y + 1),
                                               (foot_point_x - 1, foot_point_y + 1)])):
            peds_on_carriageway += 1

    # Case 1: no footpath on file for this location at all
    if not footpath_polygon_px:
        if peds_on_carriageway > 0:
            return FootpathFinding(
                finding_type="no_footpath_pedestrians_on_carriageway",
                location=location,
                pedestrian_count_on_carriageway=peds_on_carriageway,
                encroaching_defect_classes=[],
                recommendation=(f"{peds_on_carriageway} pedestrian(s) observed walking on "
                                 "the carriageway with no footpath present at this location. "
                                 "Recommend footpath/walkway construction along this stretch."),
                irc_reference="IRC:103-2012 (Guidelines for Pedestrian Facilities), "
                               "IRC:SP:44 (Highway Safety Code — pedestrian provisions)",
            )
        return FootpathFinding(
            finding_type="footpath_clear",
            location=location,
            pedestrian_count_on_carriageway=0,
            encroaching_defect_classes=[],
            recommendation="No footpath on file and no pedestrians observed on carriageway "
                            "in this frame — monitor, no action needed from this frame alone.",
            irc_reference="",
        )

    # Case 2: footpath exists — check for encroachment by other detected defects
    footpath_poly = Polygon(footpath_polygon_px)
    encroaching_classes = []
    for defect in other_defects:
        dbox = shapely_box(*defect["bbox"])
        if footpath_poly.intersection(dbox).area / dbox.area > ENCROACHMENT_IOU_THRESHOLD:
            encroaching_classes.append(defect["class"])

    if encroaching_classes:
        return FootpathFinding(
            finding_type="footpath_encroached",
            location=location,
            pedestrian_count_on_carriageway=peds_on_carriageway,
            encroaching_defect_classes=sorted(set(encroaching_classes)),
            recommendation=(f"Footpath present but occupied by: {', '.join(sorted(set(encroaching_classes)))}. "
                             f"{peds_on_carriageway} pedestrian(s) consequently forced onto the "
                             "carriageway. Recommend clearance action and, if recurring, physical "
                             "deterrents (bollards / raised kerb) to prevent re-encroachment."),
            irc_reference="IRC:103-2012 (footpath design/protection)",
            legal_reference="Street Vendors (Protection of Livelihood and Regulation of Street "
                             "Vending) Act, 2014 (if street_vendor/cart) — Motor Vehicles Act "
                             "1988 Sec. 122 (if illegal_parking on footpath)",
        )

    return FootpathFinding(
        finding_type="footpath_clear",
        location=location,
        pedestrian_count_on_carriageway=peds_on_carriageway,
        encroaching_defect_classes=[],
        recommendation="Footpath present and clear." if peds_on_carriageway == 0 else
                        (f"Footpath present and clear, but {peds_on_carriageway} pedestrian(s) "
                         "still observed on the carriageway — verify footpath accessibility "
                         "(ramps, continuity, obstructions outside this frame)."),
        irc_reference="IRC:103-2012" if peds_on_carriageway > 0 else "",
    )
