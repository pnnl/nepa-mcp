"""
PADUS (Protected Areas Database of the United States) protected-area utilities.

This module provides access to USGS PAD-US protected-area records, covering fee
ownership, designations, easements, marine, and proclamation boundaries. PAD-US is
not a cadastral ownership source and should not be treated as complete private land
ownership coverage.

API Documentation: https://www.usgs.gov/programs/gap-analysis-project/science/pad-us-data-overview
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Any, Dict, Mapping

import requests
from shapely import make_valid
from shapely.errors import GEOSException
from shapely.geometry import MultiPolygon, Polygon

from nepa_mcp_common.arcgis import ArcGISFeatureQueryResult, ArcGISService
from nepa_mcp_common.spatial import AreaUnit, clipped_union_area_from_esri_geometries

# PADUS 4.1 MapServer endpoints (National Map)
PADUS_BASE_URL = "https://edits.nationalmap.gov/arcgis/rest/services/PAD-US/PAD_US_gaz_combined/MapServer"
PADUS_COMBINED_LAYER = 0  # PADUS4_1Combined layer: Fee, Designation, Easement, Marine, Proclamation

# Retained for callers that still reference the fee-only service.
PADUS_FEE_BASE_URL = "https://edits.nationalmap.gov/arcgis/rest/services/PAD-US/PAD_US_4_1/MapServer"
PADUS_FEE_LAYER = 0  # PADUS4_1Fee layer

PADUS_OUT_FIELDS = (
    "Category,Own_Type,Own_Name,Mang_Type,Mang_Name,Des_Tp,Unit_Nm,State_Nm,GIS_Acres,GAP_Sts,IUCN_Cat,Date_Est"
)
# Keep the two possible upstream calls plus local clipping inside the MCP
# tool's 60-second timeout. ArcGIS simplification is in WGS84 degrees here;
# 0.0001 degrees is about 11 meters of latitude.
PADUS_QUERY_TIMEOUT = (5.0, 15.0)
PADUS_FALLBACK_TIMEOUT = (5.0, 10.0)
PADUS_MAX_FEATURES = 2_000
PADUS_MAX_ALLOWABLE_OFFSET_DEGREES = 0.0001
PADUS_MAX_TOTAL_RINGS = 20_000
PADUS_MAX_TOTAL_VERTICES = 250_000

PADUS_OWNER_TYPE_LABELS = {
    "DESG": "Designation",
    "DIST": "Regional Agency Special District",
    "FED": "Federal",
    "JNT": "Joint",
    "LOC": "Local Government",
    "NGO": "Non-Governmental Organization",
    "PVT": "Private",
    "STAT": "State",
    "TERR": "Territorial",
    "TRIB": "American Indian Lands",
    "UNK": "Unknown",
}


def _compact_area_warnings(warnings: tuple[str, ...], limit: int = 3) -> list[str]:
    """Keep geometry diagnostics useful without emitting one warning per feature."""
    if len(warnings) <= limit:
        return list(warnings)
    return [*warnings[:limit], f"{len(warnings) - limit} additional geometry warnings omitted."]


def _unavailable_result(lat: float, lon: float, buffer_miles: float, warnings: list[str]) -> Dict:
    """Build a response that distinguishes upstream failure from zero matches."""
    return {
        "center": {"latitude": lat, "longitude": lon},
        "buffer_miles": buffer_miles,
        "total_records": None,
        "parsed_records": 0,
        "records": [],
        "records_complete": False,
        "area_by_owner_type": {},
        "roi_area_status": "unavailable",
        "query_status": "unavailable",
        "warnings": warnings,
    }


def _text_or_default(value: Any, default: str = "") -> str:
    """Normalize nullable or malformed ArcGIS text fields for stable sorting."""
    if value is None:
        return default
    text = str(value).strip()
    return text or default


def _optional_nonnegative_float(value: Any) -> float | None:
    """Parse a source value without conflating missing or invalid data with zero."""
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) and parsed >= 0 else None


def _has_polygon_area(ring: Any) -> bool:
    """Return whether a simplified ring has usable polygonal area."""
    if not isinstance(ring, (list, tuple)) or len(ring) < 3:
        return False
    try:
        points = [(float(coordinate[0]), float(coordinate[1])) for coordinate in ring]
    except (IndexError, TypeError, ValueError, OverflowError):
        return True
    if any(not math.isfinite(value) for point in points for value in point):
        return True

    first = points[0]
    second = next((point for point in points[1:] if point != first), None)
    if second is None:
        return False
    non_collinear = any(
        not math.isclose(
            (second[0] - first[0]) * (point[1] - first[1]) - (second[1] - first[1]) * (point[0] - first[0]),
            0.0,
            abs_tol=1e-15,
        )
        for point in points[2:]
    )
    if not non_collinear:
        return False

    try:
        polygon = Polygon(points)
        if polygon.is_valid:
            return not polygon.is_empty and polygon.area > 0
        repaired = make_valid(polygon)
    except (GEOSException, ValueError):
        return True
    if isinstance(repaired, Polygon):
        return not repaired.is_empty and repaired.area > 0
    if isinstance(repaired, MultiPolygon):
        return any(not part.is_empty and part.area > 0 for part in repaired.geoms)
    return any(
        isinstance(part, Polygon) and not part.is_empty and part.area > 0 for part in getattr(repaired, "geoms", ())
    )


def _remove_collapsed_rings(geometry: Any) -> tuple[Any, int]:
    """Drop only non-polygon rings introduced by ArcGIS response simplification."""
    if not isinstance(geometry, Mapping):
        return geometry, 0
    rings = geometry.get("rings")
    if not isinstance(rings, list):
        return geometry, 0
    retained = [ring for ring in rings if _has_polygon_area(ring)]
    dropped = len(rings) - len(retained)
    if not dropped:
        return geometry, 0
    if not retained:
        return None, dropped
    return {**geometry, "rings": retained}, dropped


def _geometry_complexity(geometry: Any) -> tuple[int, int]:
    """Return ring and coordinate counts without attempting geometry repair."""
    if not isinstance(geometry, Mapping) or not isinstance(geometry.get("rings"), list):
        return 0, 0
    rings = geometry["rings"]
    return len(rings), sum(len(ring) for ring in rings if isinstance(ring, (list, tuple)))


def _query_padus(
    buffer_geom: Mapping[str, Any],
) -> tuple[ArcGISFeatureQueryResult | None, bool, str, list[str]]:
    """Return a bounded PAD-US query and whether polygon geometry is available."""
    query_kwargs = {
        "out_fields": PADUS_OUT_FIELDS,
        "page_size": PADUS_MAX_FEATURES,
        "max_features": PADUS_MAX_FEATURES,
        "max_attempts": 1,
        "strict_features": True,
        "service_name": "USGS PAD-US Combined layer",
    }
    try:
        result = ArcGISService.query_features(
            PADUS_BASE_URL,
            PADUS_COMBINED_LAYER,
            dict(buffer_geom),
            return_geometry=True,
            out_sr=4326,
            timeout=PADUS_QUERY_TIMEOUT,
            extra_params={
                "maxAllowableOffset": PADUS_MAX_ALLOWABLE_OFFSET_DEGREES,
                "geometryPrecision": 5,
            },
            **query_kwargs,
        )
        if not isinstance(result.features, list):
            raise RuntimeError("USGS PAD-US Combined layer returned a missing or null features list")
        return result, True, "complete", []
    except (RuntimeError, requests.RequestException) as geometry_error:
        geometry_warning = (
            "PAD-US polygon geometry could not be retrieved within the response budget; "
            f"ROI acreage is unavailable ({geometry_error})."
        )

    try:
        result = ArcGISService.query_features(
            PADUS_BASE_URL,
            PADUS_COMBINED_LAYER,
            dict(buffer_geom),
            return_geometry=False,
            timeout=PADUS_FALLBACK_TIMEOUT,
            **query_kwargs,
        )
        if not isinstance(result.features, list):
            raise RuntimeError("USGS PAD-US Combined layer returned a missing or null features list")
    except (RuntimeError, requests.RequestException) as fallback_error:
        return (
            None,
            False,
            "unavailable",
            [
                geometry_warning,
                f"PAD-US records are temporarily unavailable ({fallback_error}).",
            ],
        )

    return result, False, "degraded", [geometry_warning]


def get_padus_in_roi(lat: float, lon: float, buffer_miles: float = 25.0) -> Dict:
    """
    Query PADUS protected-area records within a Region of Interest.

    Uses the PAD-US Combined layer, which carries designation records such as
    Wilderness Study Areas, National Conservation Areas, and designated Wilderness
    alongside fee ownership. Designation status carries management standards that
    fee ownership alone does not express.

    Args:
        lat: Latitude in decimal degrees (WGS84)
        lon: Longitude in decimal degrees (WGS84)
        buffer_miles: Buffer radius in miles (default 25)

    Returns:
        Dictionary containing:
        - center: Query center point
        - buffer_miles: Buffer distance
        - total_records: Number of PAD-US records found
        - records: List of protected-area ownership, management, and designation records
        - area_by_owner_type: Unioned acreage within the ROI for each owner type
    """
    try:
        buffer_geom = ArcGISService.create_roi_buffer(lat, lon, buffer_miles)
    except (RuntimeError, TypeError, ValueError) as buffer_error:
        return _unavailable_result(
            lat,
            lon,
            buffer_miles,
            [f"The ROI buffer could not be created; PAD-US records and acreage are unavailable ({buffer_error})."],
        )

    result, geometry_available, query_status, query_warnings = _query_padus(buffer_geom)
    if result is None:
        return _unavailable_result(lat, lon, buffer_miles, query_warnings)

    records = []
    geometries_by_owner_type = defaultdict(list)
    collapsed_rings_by_owner_type = defaultdict(int)
    source_acres_by_owner_type = defaultdict(float)
    missing_source_acres_by_owner_type = defaultdict(int)
    total_ring_count = 0
    total_vertex_count = 0
    skipped_feature_count = 0
    warnings = [*query_warnings, *result.warnings]
    for index, feature in enumerate(result.features):
        if not isinstance(feature, Mapping):
            warnings.append(f"PAD-US feature {index} was malformed and was skipped.")
            skipped_feature_count += 1
            continue
        attrs = feature.get("attributes")
        if not isinstance(attrs, Mapping):
            warnings.append(f"PAD-US feature {index} had malformed attributes; defaults were used.")
            attrs = {}

        gis_acres = _optional_nonnegative_float(attrs.get("GIS_Acres"))
        category = _text_or_default(attrs.get("Category"), "Unknown")
        owner_type = _text_or_default(attrs.get("Own_Type"), "Unknown")
        source_gis_acres = round(gis_acres, 2) if gis_acres is not None else None
        record = {
            "category": category,
            "owner_type": owner_type,
            "owner_name": _text_or_default(attrs.get("Own_Name"), "Unknown"),
            "manager_type": _text_or_default(attrs.get("Mang_Type")),
            "manager_name": _text_or_default(attrs.get("Mang_Name")),
            "designation_type": _text_or_default(attrs.get("Des_Tp")),
            "unit_name": _text_or_default(attrs.get("Unit_Nm")),
            "state": _text_or_default(attrs.get("State_Nm")),
            # Preserve the upstream feature-area attribute for callers that use
            # it, but do not present it as area within the ROI.
            "gis_acres": source_gis_acres,
            "source_gis_acres": source_gis_acres,
            "source_gis_acres_available": source_gis_acres is not None,
            "gap_status": _text_or_default(attrs.get("GAP_Sts")),
            "iucn_category": _text_or_default(attrs.get("IUCN_Cat")),
            "date_established": _text_or_default(attrs.get("Date_Est")),
        }
        records.append(record)

        geometry = feature.get("geometry") if geometry_available else None
        geometry, collapsed_ring_count = _remove_collapsed_rings(geometry)
        collapsed_rings_by_owner_type[owner_type] += collapsed_ring_count
        ring_count, vertex_count = _geometry_complexity(geometry)
        total_ring_count += ring_count
        total_vertex_count += vertex_count
        owner_geometries = geometries_by_owner_type[owner_type]
        if geometry is not None or collapsed_ring_count == 0:
            owner_geometries.append(geometry)
        if source_gis_acres is None:
            missing_source_acres_by_owner_type[owner_type] += 1
        else:
            source_acres_by_owner_type[owner_type] += source_gis_acres

    complexity_exceeded = total_ring_count > PADUS_MAX_TOTAL_RINGS or total_vertex_count > PADUS_MAX_TOTAL_VERTICES
    area_by_owner_type = {}
    for owner_type, geometries in geometries_by_owner_type.items():
        if result.truncated:
            area_warnings = [
                "ArcGIS truncated the matching records; complete area within the ROI cannot be calculated."
            ]
            area_complete = False
            area_status = "incomplete_query"
            acres_within_roi = None
        elif complexity_exceeded:
            area_warnings = [
                "Returned geometry exceeds the bounded clipping limit "
                f"({total_ring_count:,} rings, {total_vertex_count:,} vertices); "
                "complete area within the ROI is unavailable."
            ]
            area_complete = False
            area_status = "complexity_limit"
            acres_within_roi = None
        elif geometry_available and any(geometry for geometry in geometries):
            area_result = clipped_union_area_from_esri_geometries(geometries, buffer_geom)
            area_warnings = _compact_area_warnings(area_result.warnings)
            collapsed_ring_count = collapsed_rings_by_owner_type[owner_type]
            if collapsed_ring_count:
                noun = "ring" if collapsed_ring_count == 1 else "rings"
                area_warnings.append(
                    f"{collapsed_ring_count} collapsed or non-polygon {noun} created by response simplification "
                    "were omitted from the approximate acreage."
                )
            area_complete = area_result.complete
            area_status = area_result.status.value
            acres_within_roi = area_result.area(AreaUnit.ACRES, rounded_digits=2) if area_complete else None
            if not area_complete:
                area_warnings.append(
                    "One or more feature geometries could not be processed; complete area within the ROI is unavailable."
                )
        else:
            area_warnings = ["No feature polygon geometries were returned; area within the ROI is unavailable."]
            area_complete = False
            area_status = "no_geometry"
            acres_within_roi = None

        missing_source_acres = missing_source_acres_by_owner_type[owner_type]
        area_by_owner_type[owner_type] = {
            "acres_within_roi": acres_within_roi,
            "source_feature_acres": (
                round(source_acres_by_owner_type[owner_type], 2) if missing_source_acres == 0 else None
            ),
            "source_feature_acres_complete": missing_source_acres == 0,
            "source_feature_acres_missing_records": missing_source_acres,
            "area_status": area_status,
            "area_complete": area_complete,
            "area_warnings": area_warnings,
        }

    if skipped_feature_count:
        query_status = "degraded"
        warnings.append(
            f"{skipped_feature_count} malformed PAD-US "
            f"{'feature was' if skipped_feature_count == 1 else 'features were'} skipped; records are incomplete."
        )

    records_sorted = sorted(records, key=lambda x: (x["owner_type"], x["owner_name"], x["unit_name"]))
    records_complete = not result.truncated and skipped_feature_count == 0

    return {
        "center": {"latitude": lat, "longitude": lon},
        "buffer_miles": buffer_miles,
        "total_records": len(result.features),
        "parsed_records": len(records_sorted),
        "records": records_sorted,
        "records_complete": records_complete,
        "area_by_owner_type": area_by_owner_type,
        "roi_area_status": "complete"
        if geometry_available
        and records_complete
        and all(area["area_complete"] for area in area_by_owner_type.values())
        else "unavailable",
        "query_status": query_status,
        "warnings": warnings,
    }


def format_padus_summary(padus_data: Dict) -> str:
    """
    Format PADUS data into a human-readable summary.

    Args:
        padus_data: Dictionary returned from get_padus_in_roi()

    Returns:
        Formatted text summary
    """
    lat = padus_data["center"]["latitude"]
    lon = padus_data["center"]["longitude"]
    buffer = padus_data["buffer_miles"]
    total = padus_data["total_records"]
    records = padus_data.get("records", [])
    area_by_owner_type = padus_data.get("area_by_owner_type", {})

    # Group by owner type
    by_owner_type = {}
    for record in records:
        owner_type = record["owner_type"]
        if owner_type not in by_owner_type:
            by_owner_type[owner_type] = []
        by_owner_type[owner_type].append(record)

    if total is None:
        total_text = "unavailable"
    elif padus_data.get("records_complete", True):
        total_text = f"{total}"
    else:
        total_text = f"at least {total:,} (partial response)"

    # Build summary text
    lines = [
        f"Location: ({lat}, {lon})",
        f"Buffer: {buffer} miles",
        f"Total PAD-US Records: {total_text}",
        "",
        "PAD-US Protected-Area Records by Owner Type:",
    ]

    for warning in padus_data.get("warnings", []):
        lines.extend([f"Warning: {warning}", ""])

    for owner_type in sorted(by_owner_type):
        count = len(by_owner_type[owner_type])
        record_label = "record" if count == 1 else "records"
        owner_label = PADUS_OWNER_TYPE_LABELS.get(owner_type, owner_type)
        area = area_by_owner_type.get(owner_type, {})
        acres_within_roi = area.get("acres_within_roi")
        if acres_within_roi is None:
            lines.append(f"  {owner_label} ({owner_type}): {count} {record_label}; area within ROI unavailable")
        else:
            lines.append(
                f"  {owner_label} ({owner_type}): {count} {record_label}, "
                f"approximately {acres_within_roi:,.0f} acres within ROI"
            )

        for area_warning in area.get("area_warnings", []):
            lines.append(f"    Area warning: {area_warning}")

    by_category = Counter((record.get("category") or "Unknown") for record in records)
    if by_category:
        lines.extend(["", "PAD-US Records by Category:"])
        for category in sorted(by_category):
            count = by_category[category]
            record_label = "record" if count == 1 else "records"
            lines.append(f"  {category}: {count} {record_label}")

    # Top 10 records by acreage
    if records:
        lines.extend(["", "Top 10 Largest Intersecting Source Features by Full Mapped Acreage (not clipped to ROI):"])

        records_by_size = sorted(
            records,
            key=lambda record: record.get("gis_acres") if record.get("gis_acres") is not None else -1,
            reverse=True,
        )[:10]

        for i, record in enumerate(records_by_size, 1):
            name = record["unit_name"] or record["owner_name"]
            acres = record["gis_acres"]
            owner = record["owner_type"]
            category = record.get("category") or "Unknown"
            if acres is None:
                lines.append(f"  {i}. {name} ({category}; {owner}) - source-feature acreage unavailable")
            else:
                lines.append(f"  {i}. {name} ({category}; {owner}) - {acres:,.0f} source-feature acres")

    lines.extend(
        [
            "",
            "Data Source: USGS Protected Areas Database (PAD-US) v4.1",
            "Note: PAD-US is protected-area screening data, not comprehensive cadastral land ownership.",
            "Note: Source-feature acreage is the full mapped area of each intersecting source feature and may "
            "extend beyond the ROI.",
            "Note: ROI acreage is clipped and unioned within each owner type, but owner types and PAD-US "
            "categories may overlap and are not additive.",
            "Note: ROI acreage is approximate because returned feature geometry is simplified to about 11 meters.",
        ]
    )

    return "\n".join(lines)
