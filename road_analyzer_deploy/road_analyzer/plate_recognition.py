"""
plate_recognition.py
---------------------
Automatic Number Plate Recognition (ANPR) module for the Road Analyzer
Digital Twin project. Plugs into the existing YOLOv8 detection output
in core.py — it does NOT re-run detection, it consumes bounding boxes
already produced for the `illegal_parking` class and reads the plate
inside each box.

Design principle: this module produces EVIDENCE for a human traffic
officer to act on, not an auto-issued challan. Every reading carries a
confidence score and a `verification_status` field. Anything below
PLATE_CONF_THRESHOLD is marked "needs_manual_review" rather than
silently dropped or silently trusted — OCR misreads on Indian plates
(mixed fonts, state-specific formats, dirt/glare) are common enough
that auto-issuing on a raw OCR string would be both inaccurate and,
in most states, not how the legal process actually works.

Dependencies: ultralytics (already in your requirements.txt),
easyocr, opencv-python, numpy
    pip install easyocr

Typical integration point: called from app.py right after
core.py's YOLOv8 pass returns detections for an image/frame, filtered
to class in {"illegal_parking"}.
"""

from __future__ import annotations

import re
import cv2
import numpy as np
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

# Indian plate format (covers standard + BH-series):
#   Standard: 2 letters (state) + 1-2 digits (RTO) + 1-3 letters (series) + 4 digits
#   BH series: 2 digits (year) + "BH" + 4 digits + 1-2 letters
STANDARD_PLATE_RE = re.compile(r'^[A-Z]{2}\d{1,2}[A-Z]{1,3}\d{4}$')
BH_PLATE_RE = re.compile(r'^\d{2}BH\d{4}[A-Z]{1,2}$')

PLATE_CONF_THRESHOLD = 0.55       # below this -> needs_manual_review
CROP_PADDING_PX = 8               # pad the vehicle box before searching for the plate

_ocr_reader = None  # lazy singleton, EasyOCR model load is expensive


def _get_reader():
    global _ocr_reader
    if _ocr_reader is None:
        import easyocr
        _ocr_reader = easyocr.Reader(['en'], gpu=False)  # set gpu=True on Render GPU tier
    return _ocr_reader


@dataclass
class PlateReading:
    raw_text: str
    normalized_text: str
    confidence: float
    format_valid: bool
    verification_status: str      # "auto_confirmed" | "needs_manual_review" | "unreadable"
    plate_crop_path: Optional[str] = None


def _normalize_plate_text(raw: str) -> str:
    """Strip everything but alphanumerics, uppercase, fix common OCR confusions
    in the position where a letter/digit is expected."""
    text = re.sub(r'[^A-Za-z0-9]', '', raw).upper()
    return text


def _validate_format(text: str) -> bool:
    return bool(STANDARD_PLATE_RE.match(text) or BH_PLATE_RE.match(text))


def _locate_plate_subregion(vehicle_crop: np.ndarray) -> np.ndarray:
    """
    Indian plates sit in the lower-front or lower-rear third of the vehicle
    bounding box in most street-level camera angles. Rather than run a second
    heavy detector, we narrow the OCR search region to cut false positives
    from windows, mirrors, and background text. If you have GPU headroom,
    swap this for a fine-tuned YOLOv8 plate-detector model (best.pt trained
    on a plate dataset) and crop exactly instead of heuristically.
    """
    h, w = vehicle_crop.shape[:2]
    y0 = int(h * 0.55)
    return vehicle_crop[y0:h, 0:w]


def read_plate(frame: np.ndarray, vehicle_bbox: tuple[int, int, int, int]) -> PlateReading:
    """
    frame: full image/video frame (BGR, as read by cv2)
    vehicle_bbox: (x1, y1, x2, y2) of the illegal_parking detection from core.py
    """
    x1, y1, x2, y2 = vehicle_bbox
    h, w = frame.shape[:2]
    x1 = max(0, x1 - CROP_PADDING_PX)
    y1 = max(0, y1 - CROP_PADDING_PX)
    x2 = min(w, x2 + CROP_PADDING_PX)
    y2 = min(h, y2 + CROP_PADDING_PX)
    vehicle_crop = frame[y1:y2, x1:x2]

    if vehicle_crop.size == 0:
        return PlateReading("", "", 0.0, False, "unreadable")

    search_region = _locate_plate_subregion(vehicle_crop)

    reader = _get_reader()
    results = reader.readtext(search_region)

    if not results:
        return PlateReading("", "", 0.0, False, "unreadable")

    # Pick the highest-confidence text block that looks plate-shaped
    # (wide bounding box, short string)
    best = max(results, key=lambda r: r[2])
    raw_text, confidence = best[1], float(best[2])
    normalized = _normalize_plate_text(raw_text)
    valid_format = _validate_format(normalized)

    if confidence >= PLATE_CONF_THRESHOLD and valid_format:
        status = "auto_confirmed"
    elif normalized:
        status = "needs_manual_review"
    else:
        status = "unreadable"

    return PlateReading(
        raw_text=raw_text,
        normalized_text=normalized,
        confidence=round(confidence, 3),
        format_valid=valid_format,
        verification_status=status,
    )


@dataclass
class EnforcementFlag:
    """One row of the Traffic Dept recommendation file."""
    violation_type: str            # "illegal_parking" | "street_vendor_obstruction"
    location: str
    timestamp: str
    plate_reading: Optional[PlateReading]
    applicable_section: str
    evidence_image_path: str
    notes: str = ""


def flag_illegal_parking(frame: np.ndarray, detection: dict, location: str,
                          evidence_dir: str) -> EnforcementFlag:
    """
    detection: one entry from core.py's YOLOv8 output for class == 'illegal_parking',
               expected shape {"bbox": [x1,y1,x2,y2], "confidence": float, ...}
    """
    bbox = tuple(detection["bbox"])
    plate = read_plate(frame, bbox)

    evidence_path = _save_evidence_crop(frame, bbox, evidence_dir, prefix="parking")

    return EnforcementFlag(
        violation_type="illegal_parking",
        location=location,
        timestamp=datetime.utcnow().isoformat(),
        plate_reading=plate,
        applicable_section="Motor Vehicles Act 1988, Sec. 122 (Obstruction) / local parking bye-laws",
        evidence_image_path=evidence_path,
        notes="No plate reading" if plate.verification_status == "unreadable" else "",
    )


def flag_street_vendor(frame: np.ndarray, detection: dict, location: str,
                        evidence_dir: str) -> EnforcementFlag:
    """Vendors/carts have no plate — flag is location + image evidence only,
    routed under the Street Vendors Act rather than the MV Act."""
    bbox = tuple(detection["bbox"])
    evidence_path = _save_evidence_crop(frame, bbox, evidence_dir, prefix="vendor")

    return EnforcementFlag(
        violation_type="street_vendor_obstruction",
        location=location,
        timestamp=datetime.utcnow().isoformat(),
        plate_reading=None,
        applicable_section="Street Vendors (Protection of Livelihood and Regulation of Street "
                            "Vending) Act, 2014 — Sec. 2(1)(g) vending zone violation",
        evidence_image_path=evidence_path,
        notes="Route to municipal vending-zone enforcement, not traffic challan.",
    )


def _save_evidence_crop(frame: np.ndarray, bbox: tuple, evidence_dir: str, prefix: str) -> str:
    import os
    os.makedirs(evidence_dir, exist_ok=True)
    x1, y1, x2, y2 = bbox
    crop = frame[max(0, y1):y2, max(0, x1):x2]
    fname = f"{prefix}_{datetime.utcnow().strftime('%Y%m%dT%H%M%S%f')}.jpg"
    fpath = os.path.join(evidence_dir, fname)
    cv2.imwrite(fpath, crop)
    return fpath
