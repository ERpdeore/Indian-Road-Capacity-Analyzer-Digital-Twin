"""
report_generator.py
---------------------
Single entry point that takes everything the other modules produced for
one analysis job (image/batch/video) and writes out the three
department-facing deliverables. This is the "point 1" layer from the
brief: one detection pass, multiple department-shaped outputs.

Outputs (written under results/<job_id>/):
  traffic_dept/enforcement_recommendations.csv   (+ evidence_images/)
  pwd_dept/pothole_rectification_report.csv
  municipal_dept/footpath_pedestrian_report.csv
  combined_summary.json   (kept for the existing dashboard/API to read)

CSV rather than PDF by default because these need to be importable into
each department's own tracking system / challan software; add a PDF
render pass on top (reportlab) if a given department wants a printable
version — the docx skill in this environment can do a formatted Word
version of any of these on request.
"""

from __future__ import annotations

import csv
import json
import os
from dataclasses import asdict, is_dataclass
from datetime import datetime
from typing import Any


def _to_dict(obj: Any) -> dict:
    if is_dataclass(obj):
        return asdict(obj)
    return obj


def write_traffic_dept_report(job_dir: str,
                               parking_flags: list,
                               vendor_flags: list,
                               speed_flags: list) -> str:
    out_dir = os.path.join(job_dir, "traffic_dept")
    os.makedirs(out_dir, exist_ok=True)
    csv_path = os.path.join(out_dir, "enforcement_recommendations.csv")

    fieldnames = ["violation_type", "location", "timestamp", "plate_text",
                  "plate_confidence", "plate_verification_status", "speed_kmh",
                  "speed_limit_kmh", "applicable_section", "evidence_image_path",
                  "notes", "review_status"]

    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for flag in parking_flags + vendor_flags:
            d = _to_dict(flag)
            plate = d.get("plate_reading") or {}
            writer.writerow({
                "violation_type": d["violation_type"],
                "location": d["location"],
                "timestamp": d["timestamp"],
                "plate_text": plate.get("normalized_text", ""),
                "plate_confidence": plate.get("confidence", ""),
                "plate_verification_status": plate.get("verification_status", "n/a"),
                "speed_kmh": "",
                "speed_limit_kmh": "",
                "applicable_section": d["applicable_section"],
                "evidence_image_path": d["evidence_image_path"],
                "notes": d.get("notes", ""),
                "review_status": "PENDING_OFFICER_VERIFICATION",
            })

        for flag in speed_flags:
            d = _to_dict(flag)
            plate = d.get("plate_reading") or {}
            writer.writerow({
                "violation_type": "overspeeding",
                "location": "",
                "timestamp": d["timestamp"],
                "plate_text": plate.get("normalized_text", ""),
                "plate_confidence": plate.get("confidence", ""),
                "plate_verification_status": plate.get("verification_status", "n/a"),
                "speed_kmh": d["speed_kmh"],
                "speed_limit_kmh": d["speed_limit_kmh"],
                "applicable_section": d["applicable_section"],
                "evidence_image_path": d["evidence_image_path"],
                "notes": f"Over limit by {d['over_limit_by_kmh']} km/h",
                "review_status": "PENDING_OFFICER_VERIFICATION",
            })

    return csv_path


def write_pwd_dept_report(job_dir: str, pothole_rows: list[dict]) -> str:
    out_dir = os.path.join(job_dir, "pwd_dept")
    os.makedirs(out_dir, exist_ok=True)
    csv_path = os.path.join(out_dir, "pothole_rectification_report.csv")

    fieldnames = ["location", "pothole_count", "avg_depth_cm", "capacity_loss_pct",
                  "rectification_category", "method", "materials", "irc_reference",
                  "priority", "work_zone_note", "escalation_note"]

    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in pothole_rows:
            writer.writerow(row)

    return csv_path


def write_municipal_dept_report(job_dir: str, footpath_findings: list) -> str:
    out_dir = os.path.join(job_dir, "municipal_dept")
    os.makedirs(out_dir, exist_ok=True)
    csv_path = os.path.join(out_dir, "footpath_pedestrian_report.csv")

    fieldnames = ["location", "finding_type", "pedestrian_count_on_carriageway",
                  "encroaching_defect_classes", "recommendation", "irc_reference",
                  "legal_reference"]

    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for finding in footpath_findings:
            d = _to_dict(finding)
            d["encroaching_defect_classes"] = ", ".join(d.get("encroaching_defect_classes", []))
            writer.writerow({k: d.get(k, "") for k in fieldnames})

    return csv_path


def write_combined_summary(job_dir: str, capacity_result: dict, meta: dict) -> str:
    """Keeps the existing dashboard/API working — same shape core.py already
    returns, with pointers to the new department files added on top."""
    path = os.path.join(job_dir, "combined_summary.json")
    payload = {
        "generated_at": datetime.utcnow().isoformat(),
        "capacity_analysis": capacity_result,   # unchanged, from core.py
        "department_reports": meta,             # {"traffic": path, "pwd": path, "municipal": path}
    }
    with open(path, "w") as f:
        json.dump(payload, f, indent=2)
    return path
