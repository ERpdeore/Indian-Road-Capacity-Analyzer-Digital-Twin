"""
RoadRunner / OpenDRIVE export
==============================
Generates real ASAM OpenDRIVE (.xodr) files from your capacity-analysis
results, using the `scenariogeneration` library (not hand-rolled XML —
that library is maintained against the actual OpenDRIVE spec, which
matters because a malformed .xodr fails silently or partially in
RoadRunner and is miserable to debug).

RoadRunner imports .xodr natively (File > Import > ASAM OpenDRIVE) and
builds the 3D road mesh from it directly — no manual road-drawing step,
and no need to guess asset (.fbx) paths for defect props, since OpenDRIVE
road <object> types (obstacle, barrier, parkingSpace, tree, ...) are a
built-in vocabulary RoadRunner already understands on import.

HONEST LIMITS — read this before trusting the output:
  * Every road segment generated here is a STRAIGHT LINE. Your analysis
    pipeline works from single photos (cross-sections), which carry zero
    information about real curvature or elevation. If your actual road
    curves, this export will not reflect that — only RoadRunner-side
    manual editing, or feeding this real GPS/survey data, would fix that.
  * A single photo also carries no information about how far apart
    detected defects are ALONG the road (see core.py: left_m/right_m is
    a defect's position ACROSS the road's width, not along its length).
    Defects from one photo are therefore spread across a small window
    at the segment's midpoint purely so they don't visually overlap —
    that spacing is cosmetic, not measured. Lateral position (which
    lane / how far from the edge) IS accurate, since that's what the
    photo actually captures.
  * The corridor export (multiple photos chained together) uses each
    photo's `chainage_m` — the real surveyed distance you enter per
    upload — to order segments and, where you provided it, to size the
    gap between them. Photos with no/zero chainage fall back to a fixed
    default spacing, in upload order.
"""

from __future__ import annotations
from scenariogeneration import xodr

# Default straight-segment length when no better distance is known
# (single-photo export, or corridor segments with no usable chainage gap).
DEFAULT_SEGMENT_LENGTH_M = 40.0
MIN_SEGMENT_LENGTH_M     = 10.0  # floor, so a road never degenerates to ~0m

# Map your defect classes to OpenDRIVE's built-in object vocabulary.
# These are NOT asset file paths — RoadRunner interprets these types
# itself on import, so there is nothing here to "go find in your Asset
# Library" the way the old MATLAB-script approach required.
_OBJECT_TYPE_MAP = {
    "pothole":         (xodr.ObjectType.obstacle, 0.8, 0.8, 0.05),
    "barricade":       (xodr.ObjectType.barrier,  1.5, 0.3, 1.0),
    "illegal_parking": (xodr.ObjectType.parkingSpace, 2.0, 4.5, 0.0),
    "street_vendor":   (xodr.ObjectType.obstacle, 1.5, 1.5, 1.8),
    "garbage":         (xodr.ObjectType.obstacle, 1.0, 1.0, 0.5),
    "tree":            (xodr.ObjectType.tree,     1.0, 1.0, 4.0),
}
_DEFAULT_OBJECT = (xodr.ObjectType.obstacle, 1.0, 1.0, 0.5)


def _serialize(odr) -> str:
    """odr.write_xml() requires a real filesystem path (no file-like
    objects), so round-trip through a temp file rather than hand-rolling
    XML serialization ourselves."""
    import tempfile, os
    fd, path = tempfile.mkstemp(suffix=".xodr")
    os.close(fd)
    try:
        odr.write_xml(path)
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    finally:
        os.remove(path)


def _lane_split(num_lanes: int) -> tuple[int, int]:
    """Split total lane count into (left, right) for a two-way road."""
    num_lanes = max(1, int(num_lanes))
    left  = (num_lanes + 1) // 2
    right = num_lanes - left
    return left, max(right, 0)


def _flatten_defects(per_defect: dict) -> list[dict]:
    """Pull {type, lateral_m, width_m} out of core.py's per_defect shape."""
    rows = []
    for cls, entry in (per_defect or {}).items():
        for det in entry.get("detections", []):
            if det.get("left_m") is None or det.get("right_m") is None:
                continue
            rows.append({
                "type":     cls,
                "lateral_m": (det["left_m"] + det["right_m"]) / 2,
                "width_m":   det["right_m"] - det["left_m"],
            })
    return rows


def _add_defect_objects(road, defects: list[dict], total_width_m: float,
                         segment_length_m: float) -> None:
    """Place each defect as an OpenDRIVE road <object>, spread across a
    small window at the segment's midpoint (see module docstring for why
    the spread is cosmetic, not measured)."""
    n = len(defects)
    if n == 0:
        return
    spread_m = min(segment_length_m * 0.3, 2.0 * n)  # keep it inside the segment
    start_s  = max(segment_length_m / 2 - spread_m / 2, 1.0)
    step_s   = (spread_m / max(n - 1, 1)) if n > 1 else 0.0

    for i, d in enumerate(defects):
        obj_type, w, length, h = _OBJECT_TYPE_MAP.get(d["type"], _DEFAULT_OBJECT)
        t_offset = d["lateral_m"] - total_width_m / 2  # centerline-relative
        s_pos    = start_s + i * step_s
        obj = xodr.Object(
            s=round(s_pos, 2),
            t=round(t_offset, 2),
            Type=obj_type,
            name=d["type"],
            width=max(w, d["width_m"], 0.1),
            length=length,
            height=h,
        )
        road.add_object(obj)


def build_single_road_xodr(result: dict, segment_length_m: float = DEFAULT_SEGMENT_LENGTH_M) -> str:
    """One straight road segment from a single image-analysis result,
    with its detected defects placed as OpenDRIVE road objects."""
    cfg = result.get("road_config", {}) or {}
    total_width_m = float(cfg.get("total_width_m", 7.0))
    num_lanes     = int(cfg.get("num_lanes", 2))
    lane_width    = total_width_m / max(num_lanes, 1)

    left_lanes, right_lanes = _lane_split(num_lanes)

    road = xodr.create_road(
        xodr.Line(segment_length_m),
        id=0,
        left_lanes=left_lanes,
        right_lanes=right_lanes,
        lane_width=round(lane_width, 3),
    )

    defects = _flatten_defects(result.get("per_defect", {}))
    _add_defect_objects(road, defects, total_width_m, segment_length_m)

    odr = xodr.OpenDrive(cfg.get("image") or "road_analyzer_export")
    odr.add_road(road)
    odr.adjust_roads_and_lanes()

    return _serialize(odr)


def build_corridor_xodr(results: list[dict]) -> str:
    """Multiple image-analysis results chained end-to-end into one
    continuous corridor, ordered by chainage_m. Each segment's own
    measured width/lane count is preserved — width can genuinely change
    from one segment to the next if your on-site measurements did."""
    if not results:
        raise ValueError("No completed analyses to build a corridor from.")

    # Sort by chainage; results with no chainage (0.0 default) sort first
    # and keep their relative upload order (stable sort).
    ordered = sorted(
        results,
        key=lambda r: float((r.get("road_config") or {}).get("chainage_m", 0.0)),
    )

    odr = xodr.OpenDrive("road_analyzer_corridor")
    roads = []

    for idx, result in enumerate(ordered):
        cfg = result.get("road_config", {}) or {}
        total_width_m = float(cfg.get("total_width_m", 7.0))
        num_lanes     = int(cfg.get("num_lanes", 2))
        lane_width    = total_width_m / max(num_lanes, 1)
        left_lanes, right_lanes = _lane_split(num_lanes)

        # Segment length: gap to the NEXT segment's chainage, if known and
        # sane; otherwise fall back to the default spacing.
        this_ch = float(cfg.get("chainage_m", 0.0))
        if idx + 1 < len(ordered):
            next_ch = float((ordered[idx + 1].get("road_config") or {}).get("chainage_m", 0.0))
            gap = next_ch - this_ch
            seg_len = gap if gap >= MIN_SEGMENT_LENGTH_M else DEFAULT_SEGMENT_LENGTH_M
        else:
            seg_len = DEFAULT_SEGMENT_LENGTH_M

        road = xodr.create_road(
            xodr.Line(seg_len),
            id=idx,
            left_lanes=left_lanes,
            right_lanes=right_lanes,
            lane_width=round(lane_width, 3),
        )
        defects = _flatten_defects(result.get("per_defect", {}))
        _add_defect_objects(road, defects, total_width_m, seg_len)
        roads.append(road)

    # Chain them end-to-end in SPACE only. We declare predecessor/
    # successor links so adjust_startpoints() knows the connectivity
    # order, but deliberately use adjust_startpoints() rather than
    # adjust_roads_and_lanes() — the latter also tries to link lane-IDs
    # between segments, which requires matching lane counts. Your
    # segments can legitimately have different lane counts (the road
    # really did have 2 lanes at one photo and 3 at another); forcing a
    # fake lane match would misrepresent your measurements.
    for i, road in enumerate(roads):
        if i > 0:
            road.add_predecessor(xodr.ElementType.road, roads[i - 1].id, xodr.ContactPoint.end)
        if i < len(roads) - 1:
            road.add_successor(xodr.ElementType.road, roads[i + 1].id, xodr.ContactPoint.start)
        odr.add_road(road)

    odr.adjust_startpoints()

    return _serialize(odr)


def build_ideal_road_xodr(result: dict, segment_length_m: float = DEFAULT_SEGMENT_LENGTH_M) -> str:
    """Same road geometry (width, lane count) as build_single_road_xodr,
    but with every detected defect stripped out -- this is the IDEAL
    (unobstructed) version of the same road, for an ideal-vs-non-ideal
    side-by-side comparison in RoadRunner."""
    ideal_result = dict(result)
    ideal_result["per_defect"] = {}
    return build_single_road_xodr(ideal_result, segment_length_m=segment_length_m)
