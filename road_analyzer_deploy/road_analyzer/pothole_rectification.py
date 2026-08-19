"""
pothole_rectification.py
--------------------------
Extends the existing per_defect['pothole'] output (which already gives
severity, code_ref, count, and depth_summary from core.py's MiDaS pass)
with a specific rectification measure, material spec, work-zone safety
requirement, and priority timeline, keyed off severity + scale of the
defect. This is a pure lookup/classification layer — no new detection
model needed, it reads fields core.py already computes.

Reference standards used:
  IRC:SP:83-2019   — Guidelines for Maintenance of Bituminous Roads (pothole repair procedures)
  IRC:37-2018       — Guidelines for the Design of Flexible Pavements
  IRC:81-1997       — Guidelines for Strengthening of Flexible Pavements Using
                       Benkelman Beam Deflection (overlay design)
  IRC:SP:55-2014    — Guidelines on Traffic Management in Work Zones
  IRC:67-2012 / IRC:35 — Road signs / markings for work-zone signage

Caveat carried through to output: these are standard-practice
recommendations based on visual/depth-estimate severity, not a
substitute for a site engineer's inspection before major structural
work is authorized.
"""

from __future__ import annotations
from dataclasses import dataclass


@dataclass
class RectificationMeasure:
    category: str                 # "Skin Patch" | "HMA Patch" | "Full-Depth Repair" | "Structural Overlay Review"
    method: str
    materials: str
    irc_reference: str
    priority: str                 # "Routine (30 days)" | "Urgent (7 days)" | "Emergency (48 hr)"
    work_zone_note: str
    escalation_note: str = ""


def recommend_pothole_rectification(worst_severity: str, avg_depth_cm: float,
                                     count: int, capacity_loss_pct: float) -> RectificationMeasure:
    """
    worst_severity: "shallow" | "moderate" | "deep"   (from core.py's MiDaS classifier)
    avg_depth_cm: from depth_summary.avg_estimated_depth_cm
    count: number of potholes detected in this image/segment
    capacity_loss_pct: from the pothole entry in per_defect
    """

    # Cluster/structural-failure escalation: many potholes in one frame,
    # or severe capacity loss, signals base/subgrade failure rather than
    # isolated surface distress -> escalate regardless of single-defect depth.
    is_cluster_failure = count >= 5 or capacity_loss_pct >= 25.0

    if is_cluster_failure or (worst_severity == "deep" and avg_depth_cm > 8.0):
        return RectificationMeasure(
            category="Full-Depth Repair / Structural Overlay Review",
            method=("Full-depth patch: saw-cut to regular shape, remove failed layers down "
                    "to sound base, reconstruct with granular sub-base (GSB) + Wet Mix "
                    "Macadam (WMM) base + Dense Bituminous Macadam (DBM) + Bituminous "
                    "Concrete (BC) surfacing, compacted in layers. Where failure is "
                    "clustered over a stretch, commission a Benkelman Beam / FWD "
                    "deflection survey before deciding patch-vs-overlay."),
            materials="GSB, WMM, DBM, BC per IRC:37-2018 layer thickness design for the "
                      "site's traffic (MSA) and subgrade CBR.",
            irc_reference="IRC:SP:83-2019 (Sec. 6, deep/structural pothole repair), "
                           "IRC:37-2018 (pavement layer design), IRC:81-1997 (if overlay "
                           "over a wider stretch is indicated by the deflection survey)",
            priority="Emergency (48 hr) — safety hazard; deep failure or cluster indicates "
                     "active base distress",
            work_zone_note="Full lane/road closure with barricading, diversion signage, "
                            "and flagmen per IRC:SP:55-2014; retro-reflective cones "
                            "IRC:67-2012.",
            escalation_note="Recommend PWD structural engineer site visit — this pattern "
                             "is beyond routine maintenance scope.",
        )

    if worst_severity == "moderate" or (worst_severity == "deep" and avg_depth_cm <= 8.0):
        return RectificationMeasure(
            category="Hot-Mix Asphalt (HMA) Patch",
            method=("Square/rectangular saw-cut around the pothole with vertical edges, "
                    "clean and dry the base, apply tack coat, place hot-mix asphalt (DBM "
                    "or BC as per depth) in compacted layers not exceeding 50mm each, "
                    "compact with a plate/roller flush to the surrounding surface."),
            materials="Tack coat (bitumen emulsion RS-1) + DBM/BC hot-mix, per IRC:SP:83 "
                      "Table on patch-depth vs mix selection.",
            irc_reference="IRC:SP:83-2019 (Sec. 5, moderate pothole HMA patching), "
                           "IRC:37-2018 Cl. 6.5",
            priority="Urgent (7 days)",
            work_zone_note="Lane closure with cones and warning signage per IRC:SP:55-2014 "
                            "during patching and compaction curing.",
        )

    # shallow
    return RectificationMeasure(
        category="Skin Patch / Surface Treatment",
        method=("Clean loose debris and water from the pothole, apply cold-mix premix "
                "carpet or slurry seal, compact by hand tamper/plate compactor flush "
                "with surrounding surface. Suitable for isolated shallow surface "
                "distress only."),
        materials="Cold-mix premix (bitumen emulsion + aggregate) or micro-surfacing "
                   "slurry seal.",
        irc_reference="IRC:SP:83-2019 (Sec. 4.2, shallow pothole skin patching)",
        priority="Routine (30 days)",
        work_zone_note="Short-duration single-lane caution signage sufficient "
                        "(IRC:67-2012); no full closure typically needed.",
    )


def build_pwd_report_row(pothole_defect_entry: dict, location: str) -> dict:
    """
    pothole_defect_entry: the per_defect['pothole'] dict from core.py's
        existing output, e.g.
        {
          "count": 2, "blocked_m": 1.4, "capacity_loss_pct": 12.5,
          "severity": "ROUTINE", "code_ref": "IRC:37-2018, IRC:SP:83",
          "action": "...",
          "depth_summary": {"worst_severity": "moderate", "avg_estimated_depth_cm": 3.2}
        }
    """
    depth = pothole_defect_entry.get("depth_summary", {})
    rec = recommend_pothole_rectification(
        worst_severity=depth.get("worst_severity", "shallow"),
        avg_depth_cm=depth.get("avg_estimated_depth_cm", 0.0),
        count=pothole_defect_entry.get("count", 1),
        capacity_loss_pct=pothole_defect_entry.get("capacity_loss_pct", 0.0),
    )
    return {
        "location": location,
        "pothole_count": pothole_defect_entry.get("count"),
        "avg_depth_cm": depth.get("avg_estimated_depth_cm"),
        "capacity_loss_pct": pothole_defect_entry.get("capacity_loss_pct"),
        "rectification_category": rec.category,
        "method": rec.method,
        "materials": rec.materials,
        "irc_reference": rec.irc_reference,
        "priority": rec.priority,
        "work_zone_note": rec.work_zone_note,
        "escalation_note": rec.escalation_note,
    }
