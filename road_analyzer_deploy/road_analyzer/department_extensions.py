"""
department_extensions.py
--------------------------
Generates a department-routed PDF report from an analyse_image() result.

Previously the only machine-readable export was a flat CSV
(`{stem}_roadrunner.csv`, written by core.py's analyse_image) that was
never actually exposed to the frontend for download, and wasn't grouped by
which civic department is actually responsible for acting on each finding.

This module replaces that workflow: it groups detected obstructions by the
department that would realistically handle them (Public Works for potholes/
barricades, Traffic Police for illegal parking, the Municipal Corporation's
encroachment and solid-waste desks for vendors/carts/garbage, and the
garden/tree department for roadside trees), and produces one clean PDF you
can hand to -- or email -- each department directly, instead of a raw CSV
they'd have to interpret themselves.
"""

from datetime import datetime
from pathlib import Path
from typing import Optional

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable,
)

# ----------------------------------------------------------------
# Defect class -> responsible department mapping
# ----------------------------------------------------------------
# Kept separate from core.py's CLASS_NAMES so this file can be edited by
# whoever owns department routing (e.g. if your city's department names
# differ) without touching the detection/capacity-calculation code at all.
DEPARTMENT_MAP = {
    "pothole": {
        "department": "Public Works Department (PWD) - Roads Division",
        "reason": "Carriageway surface defect requiring pothole repair / resurfacing.",
    },
    "barricade": {
        "department": "Public Works Department (PWD) - Roads Division",
        "reason": "Unauthorised or unremoved barricade obstructing the carriageway.",
    },
    "illegal_parking": {
        "department": "Traffic Police Department",
        "reason": "Vehicle parked in violation of Motor Vehicles Act, obstructing traffic flow.",
    },
    "street_vendor": {
        "department": "Municipal Corporation - Encroachment Removal Cell",
        "reason": "Vending encroaching on carriageway width, relevant to the Street Vendors "
                  "(Protection of Livelihood and Regulation of Street Vending) Act, 2014.",
    },
    "cart": {
        "department": "Municipal Corporation - Encroachment Removal Cell",
        "reason": "Stationary handcart/vending cart encroaching on carriageway width.",
    },
    "garbage": {
        "department": "Municipal Corporation - Solid Waste Management Department",
        "reason": "Garbage accumulation obstructing carriageway / roadside drainage.",
    },
}

DEFAULT_DEPARTMENT = {
    "department": "Public Works Department (PWD) - Roads Division",
    "reason": "Obstruction affecting carriageway capacity.",
}


def _format_survey_date(analysis_date: Optional[str]) -> str:
    """'2026-09-23' -> '23 Sep 2026'. Falls back to today's date if missing
    or unparseable, so the report never prints a blank or a raw ISO string."""
    if analysis_date:
        try:
            return datetime.strptime(analysis_date.strip(), "%Y-%m-%d").strftime("%d %b %Y")
        except ValueError:
            pass
    return datetime.now().strftime("%d %b %Y")


def _styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="ReportTitle", parent=styles["Title"], fontSize=18, spaceAfter=4,
    ))
    styles.add(ParagraphStyle(
        name="ReportSubtitle", parent=styles["Normal"], fontSize=10,
        textColor=colors.HexColor("#555555"), spaceAfter=14,
    ))
    styles.add(ParagraphStyle(
        name="DeptHeading", parent=styles["Heading2"], fontSize=13,
        textColor=colors.HexColor("#1e3a5f"), spaceBefore=18, spaceAfter=6,
    ))
    styles.add(ParagraphStyle(
        name="DeptReason", parent=styles["Normal"], fontSize=9,
        textColor=colors.HexColor("#555555"), spaceAfter=8,
    ))
    styles.add(ParagraphStyle(
        name="Cell", parent=styles["Normal"], fontSize=8.5, leading=11,
    ))
    styles.add(ParagraphStyle(
        name="CellHeader", parent=styles["Normal"], fontSize=8.5, leading=11,
        textColor=colors.white, fontName="Helvetica-Bold",
    ))
    return styles


def _severity_color(severity: str) -> colors.Color:
    return {
        "critical": colors.HexColor("#dc2626"),
        "severe":   colors.HexColor("#ea580c"),
        "moderate": colors.HexColor("#d97706"),
        "urgent":   colors.HexColor("#dc2626"),
        "routine":  colors.HexColor("#d97706"),
        "monitor":  colors.HexColor("#65a30d"),
        "minor":    colors.HexColor("#65a30d"),
    }.get((severity or "").lower(), colors.HexColor("#475569"))


def _group_by_department(per_defect: dict) -> dict:
    """Group core.py's per_defect results by responsible department."""
    grouped: dict = {}
    for dname, dinfo in (per_defect or {}).items():
        route = DEPARTMENT_MAP.get(dname, DEFAULT_DEPARTMENT)
        dept = route["department"]
        grouped.setdefault(dept, {"reason": route["reason"], "defects": []})
        grouped[dept]["defects"].append((dname, dinfo))
    return grouped


def generate_department_report_pdf(result: dict, output_path: str,
                                    site_label: Optional[str] = None,
                                    appendix_title: Optional[str] = None,
                                    appendix_rows: Optional[list] = None,
                                    appendix_headers: Optional[list] = None) -> str:
    """
    Build a department-routed PDF report from a single analyse_image()
    result dict and write it to output_path. Returns output_path.

    appendix_title / appendix_headers / appendix_rows are optional and let
    a caller (batch or video mode) append an extra context table after the
    department sections — e.g. per-image capacity loss across a batch, or
    unique tracked defect instances across a video — without changing how
    the main department tables are built. The main tables always describe
    a single representative result (the worst-case image/frame); the
    appendix is what tells the reader that this is one photo out of many.
    """
    styles = _styles()
    story = []

    road_config = result.get("road_config", {}) or {}
    basis       = result.get("capacity_basis", {}) or {}
    calc        = result.get("capacity_calculation", {}) or {}
    generated_at = datetime.now().strftime("%d %b %Y, %I:%M %p")

    # Date the site photo/video was actually analysed (set by the operator
    # on the dashboard, defaulting to today) — distinct from generated_at
    # above, which is just when this PDF file happened to be rendered.
    # This is the date that belongs on a department report: "survey date",
    # not "PDF render timestamp".
    survey_date = _format_survey_date(road_config.get("analysis_date"))

    # ---- Header ----
    story.append(Paragraph("Road Capacity Obstruction Report", styles["ReportTitle"]))
    story.append(Paragraph(
        f"Date of analysis: <b>{survey_date}</b> &middot; Site: {site_label or result.get('image', '-')} "
        f"&middot; Indo-HCM 2017 (urban roads) basis &middot; Report generated {generated_at}",
        styles["ReportSubtitle"],
    ))
    story.append(HRFlowable(width="100%", color=colors.HexColor("#cbd5e1"), thickness=1))
    story.append(Spacer(1, 10))

    # ---- Site / capacity summary table ----
    guidance = result.get("overall_guidance", "-")
    if isinstance(guidance, dict):
        guidance = f"{guidance.get('band', '-')} — {guidance.get('action', '-')}"

    los = result.get("level_of_service")
    factors = calc.get("factors") or {}
    summary_rows = [
        ["Date of data collection", _format_survey_date(road_config.get("data_collection_date"))],
        ["Date of analysis", survey_date],
        ["Road type", f"{basis.get('road_type_label', '-')} — capacity basis: {basis.get('direction_basis', '-')}"],
        ["Carriageway width (measured)", f"{road_config.get('total_width_m', '-')} m"],
        ["Operating speed", (f"{basis['operating_speed_kmh']} km/h ({basis.get('operating_speed_source', '-')})"
                             if basis.get("operating_speed_kmh") else "Not measured — enter the measured operating speed")],
        ["Base capacity C0", f"{result.get('base_capacity_pcu_h', '-')} PCU/h — {basis.get('base_capacity_detail', '')}"],
        ["Indo-HCM factors (Eq. 5.5)", ", ".join(f"{k} = {v}" for k, v in (calc.get("indo_hcm_factors") or {}).items()) or "-"],
        ["Indo-HCM capacity", f"{result.get('indo_hcm_capacity_pcu_h', '-')} PCU/h"],
        ["Project extension factors", ", ".join(f"{k} = {v}" for k, v in (calc.get("extension_factors") or {}).items()) or "-"],
        ["Capacity incl. extensions", f"{result.get('reduced_capacity_pcu_h', '-')} PCU/h"],
        ["Capacity loss", f"{result.get('capacity_loss_pct', '-')}%"],
        ["Service volume at LOS-C (0.70 C)",
         f"{result.get('dsv_los_c_ideal_pcu_h', '-')} → {result.get('dsv_los_c_reduced_pcu_h', '-')} PCU/h"],
        ["Level of service",
         (f"V = {los['observed_volume_pcu_h']} PCU/h (Table {los['table']}): base LOS {los['los_base']}, "
          f"Indo-HCM LOS {los['los_hcm']}, with extensions LOS {los['los_ext']}") if los else
         "Not computed — no traffic volume was entered (LOS needs V/C)."],
        ["Overall guidance", str(guidance)],
    ]
    summary_table = Table(
        [[Paragraph(f"<b>{k}</b>", styles["Cell"]), Paragraph(str(v), styles["Cell"])]
         for k, v in summary_rows],
        colWidths=[65 * mm, 105 * mm],
    )
    summary_table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f1f5f9")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(summary_table)
    story.append(Spacer(1, 6))

    per_defect = result.get("per_defect", {}) or {}
    if not per_defect:
        story.append(Spacer(1, 14))
        story.append(Paragraph(
            "No obstructions were detected in this analysis - no department action required.",
            styles["Normal"],
        ))
        _append_appendix(story, styles, appendix_title, appendix_headers, appendix_rows)
        _build(story, output_path)
        return output_path

    grouped = _group_by_department(per_defect)

    # ---- One section per department ----
    for dept, info in sorted(grouped.items()):
        story.append(Paragraph(dept, styles["DeptHeading"]))
        story.append(Paragraph(info["reason"], styles["DeptReason"]))

        header = [
            Paragraph("Defect", styles["CellHeader"]),
            Paragraph("Count", styles["CellHeader"]),
            Paragraph("Width / mechanism", styles["CellHeader"]),
            Paragraph("Capacity loss", styles["CellHeader"]),
            Paragraph("Severity", styles["CellHeader"]),
            Paragraph("IRC code ref / action", styles["CellHeader"]),
        ]
        rows = [header]
        for dname, dinfo in info["defects"]:
            rows.append([
                Paragraph(dname.replace("_", " ").title(), styles["Cell"]),
                Paragraph(str(dinfo.get("count", "-")), styles["Cell"]),
                Paragraph(f"{dinfo.get('blocked_m', '-')} m<br/>{dinfo.get('mechanism', '')}", styles["Cell"]),
                Paragraph(f"{dinfo.get('capacity_loss_pct', '-')}%", styles["Cell"]),
                Paragraph(str(dinfo.get("severity", "-")).title(), styles["Cell"]),
                Paragraph(
                    f"<b>{dinfo.get('code_ref', '-')}</b><br/>{dinfo.get('action', '-')}",
                    styles["Cell"],
                ),
            ])

        t = Table(rows, colWidths=[26*mm, 14*mm, 22*mm, 22*mm, 20*mm, 56*mm], repeatRows=1)
        style_cmds = [
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#e2e8f0")),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e3a5f")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ]
        for i, (dname, dinfo) in enumerate(info["defects"], start=1):
            style_cmds.append(("TEXTCOLOR", (4, i), (4, i), _severity_color(dinfo.get("severity"))))
        t.setStyle(TableStyle(style_cmds))
        story.append(t)
        story.append(Spacer(1, 4))

    story.append(Spacer(1, 16))
    story.append(HRFlowable(width="100%", color=colors.HexColor("#cbd5e1"), thickness=1))
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        "Generated automatically from an Indo-HCM 2017 (urban roads) capacity analysis of a "
        "single cross-section photo. Obstruction widths are image-based estimates and pothole "
        "size is a width-only proxy; verify on site before dispatching crews.",
        styles["ReportSubtitle"],
    ))

    _append_appendix(story, styles, appendix_title, appendix_headers, appendix_rows)
    _build(story, output_path)
    return output_path


def _append_appendix(story: list, styles, appendix_title: Optional[str],
                      appendix_headers: Optional[list], appendix_rows: Optional[list]) -> None:
    """Optional extra table for batch/video context — see docstring above."""
    if not appendix_rows:
        return
    story.append(Spacer(1, 14))
    story.append(Paragraph(appendix_title or "Additional context", styles["DeptHeading"]))
    headers = appendix_headers or list(appendix_rows[0].keys())
    table_rows = [[Paragraph(str(h), styles["CellHeader"]) for h in headers]]
    for row in appendix_rows:
        table_rows.append([Paragraph(str(row.get(h, "-")), styles["Cell"]) for h in headers])
    col_width = (170 * mm) / len(headers)
    t = Table(table_rows, colWidths=[col_width] * len(headers), repeatRows=1)
    t.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#e2e8f0")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e3a5f")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
    ]))
    story.append(t)


def _build(story: list, output_path: str) -> None:
    doc = SimpleDocTemplate(
        output_path, pagesize=A4,
        topMargin=18 * mm, bottomMargin=16 * mm,
        leftMargin=16 * mm, rightMargin=16 * mm,
        title="Road Capacity Obstruction Report",
    )
    doc.build(story)
