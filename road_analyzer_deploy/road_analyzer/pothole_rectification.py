"""
road_analyzer.pothole_rectification
===================================
Repair recommendation for the potholes in per_defect['pothole'].

Code basis: IRC:82-2015, Code of Practice for Maintenance of Bituminous
Road Surfaces.
  cl. 7.5.3.4  pothole size: small (~200 mm wide, 25 mm deep),
               medium (25-50 mm deep, 500 mm wide), large (> 50 mm deep)
  cl. 7.5.3.5  rectification: fill with open- or dense-graded premix —
               cold/hot mix for immediate use, storable cold mix
               (cutback IRC:116 or emulsion IRC:100), ready-made mix, or
               patching-machine cold mix
  cl. 5.3      distress affecting riding quality and traffic flow should
               be rectified straightaway; condition surveys before and
               after the monsoon on urban roads
  Table 5.3    urban roads: potholes > 0.5% of surface area = "poor"

Earlier versions cited IRC:SP:83 for these repairs. IRC:SP:83 covers
CEMENT CONCRETE pavements and does not apply to bituminous potholes.

Size here is inferred from measured WIDTH only (a photo cannot measure
depth), so a "small" pothole may in fact be deeper. Field verification of
depth is required before the repair method is fixed.
"""

from __future__ import annotations

from dataclasses import dataclass

CODE = "IRC:82-2015"


@dataclass
class RectificationMeasure:
    category: str
    method: str
    materials: str
    irc_reference: str
    priority: str
    work_zone_note: str
    escalation_note: str = ""


def recommend_pothole_rectification(worst_size: str, count: int) -> RectificationMeasure:
    work_zone = ("Cone off the patch area and provide advance warning signs during the "
                 "work and until the mix has set (IRC:SP:55-2014).")
    # Many potholes in one frame usually indicate base/subgrade distress
    # rather than isolated surface failure. Threshold is a project heuristic.
    cluster = count >= 5

    if worst_size == "large" or cluster:
        return RectificationMeasure(
            category="Pothole patching with base check",
            method=("Cut the pothole to a regular rectangular shape with vertical sides down to "
                    "sound material. If the cavity extends into the base course, reinstate the "
                    "base first; then apply tack coat and fill with dense-graded premix in layers, "
                    "compacting each layer flush with the surface (IRC:82 cl. 7.5.3.5)."),
            materials="Hot-mix or storable cold mix (emulsion IRC:100 / cutback IRC:116); "
                      "granular base material where the base has failed.",
            irc_reference=f"{CODE} cl. 7.5.3.4-7.5.3.5, cl. 5.3",
            priority="Rectify straightaway (IRC:82 cl. 5.3)",
            work_zone_note=work_zone,
            escalation_note=("Cluster of potholes: assess the stretch structurally (deflection "
                             "survey, IRC:115-2014 FWD or IRC:81-1997 BBD) to decide between "
                             "patching and an overlay designed per IRC:37-2018."
                             if cluster else "Verify depth on site; deep potholes indicate base failure."),
        )
    if worst_size == "medium":
        return RectificationMeasure(
            category="Pothole patching",
            method=("Remove loose material, cut to a regular shape, clean and dry, apply tack coat, "
                    "fill with premix and compact flush with the surrounding surface "
                    "(IRC:82 cl. 7.5.3.5)."),
            materials="Hot or cold premix; storable cold mix per IRC:100 / IRC:116 in wet weather.",
            irc_reference=f"{CODE} cl. 7.5.3.4-7.5.3.5, cl. 5.3",
            priority="Rectify straightaway (IRC:82 cl. 5.3)",
            work_zone_note=work_zone,
        )
    return RectificationMeasure(
        category="Pothole filling",
        method=("Clean out loose material and water, fill with premix and compact with a hand "
                "rammer or plate compactor flush with the surface (IRC:82 cl. 7.5.3.5)."),
        materials="Cold premix, ready-made mix or patching-machine cold mix.",
        irc_reference=f"{CODE} cl. 7.5.3.4-7.5.3.5",
        priority="Next maintenance round; include in the pre/post-monsoon survey (cl. 5.3)",
        work_zone_note=work_zone,
    )


def build_pwd_report_row(pothole_defect_entry: dict, location: str) -> dict:
    summary = pothole_defect_entry.get("size_summary", {}) or {}
    worst = summary.get("worst_size_class") or "small"
    rec = recommend_pothole_rectification(worst, int(pothole_defect_entry.get("count", 1)))
    return {
        "location": location,
        "pothole_count": pothole_defect_entry.get("count"),
        "worst_size_class": worst,
        "size_basis": "width-only proxy for IRC:82 cl. 7.5.3.4 (depth not measured)",
        "capacity_loss_pct": pothole_defect_entry.get("capacity_loss_pct"),
        "rectification_category": rec.category,
        "method": rec.method,
        "materials": rec.materials,
        "irc_reference": rec.irc_reference,
        "priority": rec.priority,
        "work_zone_note": rec.work_zone_note,
        "escalation_note": rec.escalation_note,
    }
