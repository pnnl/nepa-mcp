"""
EPA ACRES (Assessment, Cleanup and Redevelopment Exchange System) Brownfields utilities.

This module queries the EPA Envirofacts facility-points ArcGIS MapServer to
identify Brownfields properties reported to ACRES within a Region of Interest.
ACRES captures grantee-reported data from EPA Brownfields grant programs, so it
is not a complete inventory of brownfields or contaminated sites, and a record
is not a determination that land is available or suitable for development.

Data source: EPA Envirofacts Brownfields ArcGIS layer
  https://geopub.epa.gov/ArcGIS/rest/services/EMEF/efpoints/MapServer/5
"""

from __future__ import annotations

import logging
import math
from collections import Counter
from typing import Dict

from nepa_mcp_common.arcgis import ArcGISService
from nepa_mcp_common.validation import validate_coordinates
from src.core.constants import ACRES_BROWNFIELDS_LAYER_ID, ACRES_SERVICE_URL

logger = logging.getLogger(__name__)

# Fields to request from the ACRES Brownfields ArcGIS layer
_OUT_FIELDS = (
    "registry_id,primary_name,location_address,city_name,county_name,state_code,"
    "epa_region,postal_code,latitude,longitude,pgm_sys_id,facility_url"
)

# Cap each result page so dense metro ROIs stay readable. Callers can retrieve
# later records with ``result_offset`` instead of losing them from the response.
MAX_PAGE_SIZE = 100
MAX_RESULT_OFFSET = ArcGISService.DEFAULT_MAX_FEATURES - 1

# Keep the complete request budget below the MCP tool's 60-second timeout:
# GeometryServer (20s) + two EPA attempts (12s each) + retry backoff.
ACRES_QUERY_TIMEOUT_SECONDS = 12
ACRES_QUERY_MAX_ATTEMPTS = 2


def get_epa_acres_properties_in_roi(lat: float, lon: float, buffer_miles: float = 25.0) -> Dict:
    """
    Return ACRES Brownfields property records intersecting the ROI.

    Queries the Brownfields layer of the EPA Envirofacts facility-points
    MapServer. Each record is an identifiable property reported to ACRES through
    EPA Brownfields grant programs, with its FRS registry ID, ACRES property ID,
    and EPA Cleanups in my Community source URL.

    Args:
        lat: Latitude in decimal degrees (WGS84).
        lon: Longitude in decimal degrees (WGS84).
        buffer_miles: Buffer radius in miles (default 25).

    Returns:
        Dictionary with:
            - center: {latitude, longitude}
            - buffer_miles: float
            - total: int
            - properties: list of property dicts
            - counts_by_state: counts across all usable returned records
            - warnings: list of upstream warnings
            - truncated: bool (upstream feature cap reached; results are partial)
            - partial: bool (upstream cap reached or malformed features skipped)
            - data_unavailable: bool (only present when buffering or querying failed)
            - error: str (only present when buffering or querying failed)
    """
    lat, lon, buffer_miles = validate_coordinates(lat, lon, buffer_miles)

    base = {"center": {"latitude": lat, "longitude": lon}, "buffer_miles": buffer_miles}

    try:
        buffer_geom = ArcGISService.create_roi_buffer(lat, lon, buffer_miles)
    except Exception as e:
        logger.error("ArcGIS buffer creation failed: %s", e)
        return {
            **base,
            "total": 0,
            "properties": [],
            "counts_by_state": {},
            "warnings": [],
            "truncated": False,
            "partial": False,
            "data_unavailable": True,
            "error": "ArcGIS GeometryServer was unavailable for this request.",
        }

    try:
        result = ArcGISService.query_features(
            ACRES_SERVICE_URL,
            ACRES_BROWNFIELDS_LAYER_ID,
            buffer_geom,
            out_fields=_OUT_FIELDS,
            timeout=ACRES_QUERY_TIMEOUT_SECONDS,
            max_attempts=ACRES_QUERY_MAX_ATTEMPTS,
            service_name="EPA ACRES Brownfields layer",
        )
    except Exception as e:
        logger.error("EPA ACRES Brownfields layer query failed: %s", e)
        # A failed upstream query is NOT a valid no-hit screen — flag it
        # explicitly so a consumer that ignores warnings cannot mistake an
        # outage for "no Brownfields properties found".
        return {
            **base,
            "total": 0,
            "properties": [],
            "counts_by_state": {},
            "warnings": ["EPA ACRES Brownfields layer query failed; results are unavailable, not a no-hit finding."],
            "truncated": False,
            "partial": False,
            "data_unavailable": True,
            "error": "EPA ACRES Brownfields data were unavailable for this request.",
        }

    properties = []
    warnings = list(result.warnings)
    if not isinstance(result.features, list):
        return {
            **base,
            "total": 0,
            "properties": [],
            "counts_by_state": {},
            "warnings": [*warnings, "EPA ACRES returned malformed feature data; results are unavailable."],
            "truncated": result.truncated,
            "partial": True,
            "data_unavailable": True,
            "error": "EPA ACRES returned malformed feature data.",
        }

    skipped_features = 0
    for feature in result.features:
        if not isinstance(feature, dict):
            skipped_features += 1
            continue
        attrs = feature.get("attributes")
        if not isinstance(attrs, dict) or not any(
            attrs.get(field) for field in ("registry_id", "pgm_sys_id", "primary_name")
        ):
            skipped_features += 1
            continue

        property_latitude = _coerce_coordinate(attrs.get("latitude"), minimum=-90, maximum=90)
        property_longitude = _coerce_coordinate(attrs.get("longitude"), minimum=-180, maximum=180)
        distance_miles = None
        if property_latitude is not None and property_longitude is not None:
            distance_miles = round(_distance_miles(lat, lon, property_latitude, property_longitude), 3)

        properties.append(
            {
                "name": _coerce_text(attrs.get("primary_name"), default="Unknown"),
                "address": _coerce_text(attrs.get("location_address")),
                "city": _coerce_text(attrs.get("city_name")),
                "county": _coerce_text(attrs.get("county_name")),
                "state": _coerce_text(attrs.get("state_code")),
                "zip": _coerce_text(attrs.get("postal_code")),
                "epa_region": _coerce_text(attrs.get("epa_region")),
                "frs_registry_id": _coerce_text(attrs.get("registry_id")),
                "acres_property_id": _coerce_text(attrs.get("pgm_sys_id")),
                "latitude": property_latitude,
                "longitude": property_longitude,
                "distance_miles": distance_miles,
                "facility_url": _coerce_text(attrs.get("facility_url")),
            }
        )

    if skipped_features:
        warnings.append(
            f"EPA ACRES skipped {skipped_features} malformed or unidentifiable feature"
            f"{'s' if skipped_features != 1 else ''}; returned records are partial."
        )

    properties.sort(
        key=lambda p: (
            p["distance_miles"] is None,
            p["distance_miles"] if p["distance_miles"] is not None else math.inf,
            p["state"].casefold(),
            p["city"].casefold(),
            p["name"].casefold(),
            p["acres_property_id"],
        )
    )
    counts_by_state = dict(sorted(Counter((prop["state"] or "Unknown") for prop in properties).items()))

    if skipped_features and not properties:
        return {
            **base,
            "total": 0,
            "properties": [],
            "counts_by_state": {},
            "warnings": warnings,
            "truncated": result.truncated,
            "partial": True,
            "data_unavailable": True,
            "error": "EPA ACRES returned no usable property records.",
        }

    return {
        **base,
        "total": len(properties),
        "properties": properties,
        "counts_by_state": counts_by_state,
        "warnings": warnings,
        "truncated": result.truncated,
        "partial": result.truncated or bool(skipped_features),
        "skipped_features": skipped_features,
    }


def _coerce_text(value, *, default: str = "") -> str:
    """Return a stripped string while preserving useful numeric identifiers."""
    if value is None:
        return default
    text = str(value).strip()
    return text or default


def _coerce_coordinate(value, *, minimum: float, maximum: float) -> float | None:
    """Return an attribute coordinate as a float, or None when absent or invalid."""
    try:
        coordinate = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(coordinate) or not minimum <= coordinate <= maximum:
        return None
    return coordinate


def _distance_miles(lat_a: float, lon_a: float, lat_b: float, lon_b: float) -> float:
    """Return great-circle distance between two WGS84 points in statute miles."""
    lat_a_rad = math.radians(lat_a)
    lat_b_rad = math.radians(lat_b)
    delta_lat = math.radians(lat_b - lat_a)
    delta_lon = math.radians(lon_b - lon_a)
    haversine = math.sin(delta_lat / 2) ** 2 + math.cos(lat_a_rad) * math.cos(lat_b_rad) * math.sin(delta_lon / 2) ** 2
    return 3958.7613 * 2 * math.asin(min(1.0, math.sqrt(haversine)))


def format_epa_acres_summary(
    result: Dict,
    *,
    max_results: int = MAX_PAGE_SIZE,
    result_offset: int = 0,
) -> str:
    """
    Format ACRES query results as a markdown summary for Brownfields screening.

    Args:
        result: Data dict from get_epa_acres_properties_in_roi().

    Returns:
        Formatted markdown string.
    """
    center = result.get("center", {})
    lat = center.get("latitude", 0)
    lon = center.get("longitude", 0)
    buffer_miles = result.get("buffer_miles", 0)
    properties = result.get("properties", [])
    total = result.get("total", 0)
    page_end = min(result_offset + max_results, total)
    page_properties = properties[result_offset:page_end]
    total_label = "Returned ACRES Properties" if result.get("truncated") else "Total ACRES Properties"
    lines = [
        "## EPA ACRES Brownfields Properties",
        "",
        f"**Location:** ({lat}, {lon})",
        f"**Buffer:** {buffer_miles} miles",
        f"**{total_label}:** {total}",
        "",
    ]

    if result.get("data_unavailable"):
        lines += ["> ⚠️ ACRES results are unavailable for this request, not a no-hit finding.", ""]

    if result.get("error"):
        lines += [f"> ⚠️ Error during query: {result['error']}", ""]

    for warning in result.get("warnings", []):
        lines += [f"> Warning: {warning}", ""]

    if not properties:
        # An unavailable result must never render the no-hit sentence: the
        # banner above already labels it, and "No ... properties" would read
        # as a clean screen.
        if not result.get("data_unavailable"):
            lines += [
                "No ACRES Brownfields properties were identified within the ROI buffer.",
                "",
                "> **Screening Note:** ACRES contains only properties reported through EPA",
                "> Brownfields grant programs. An empty result is not evidence that the area",
                "> is free of brownfields or contamination.",
                "",
            ]
    else:
        counts_by_state = result.get("counts_by_state") or dict(
            sorted(Counter((prop.get("state") or "Unknown") for prop in properties).items())
        )
        lines += ["### Properties by State", ""]
        for state, count in counts_by_state.items():
            property_label = "property" if count == 1 else "properties"
            lines.append(f"- **{state}:** {count} {property_label}")
        lines.append("")

        if not page_properties:
            lines += [
                f"No records are available at result_offset={result_offset}. "
                f"This query returned {total} usable properties.",
                "",
            ]
        else:
            lines += [
                f"### Property Details ({result_offset + 1}–{page_end} of {total})",
                "",
            ]

        # Group this page by state for readability.
        by_state: Dict[str, list] = {}
        for prop in page_properties:
            state = prop.get("state") or "Unknown"
            by_state.setdefault(state, []).append(prop)

        for state, state_props in sorted(by_state.items()):
            property_label = "property shown" if len(state_props) == 1 else "properties shown"
            lines += [f"#### {state} ({len(state_props)} {property_label})", ""]
            for prop in state_props:
                lines.append(_format_property_line(prop))
            lines.append("")

        if page_end < total:
            lines += [
                f"More records are available. Call this tool again with result_offset={page_end} "
                f"and max_results={max_results} to continue the nearest-first listing.",
                "",
            ]

        if result.get("truncated"):
            lines += [
                "The returned count is a lower bound because the upstream 10,000-feature safety cap was reached.",
                "",
            ]

    lines += [
        "---",
        "",
        "Data Source: EPA ACRES (Assessment, Cleanup and Redevelopment Exchange System) via the "
        f"EPA Envirofacts Brownfields ArcGIS layer ({ACRES_SERVICE_URL}/{ACRES_BROWNFIELDS_LAYER_ID}).",
        "Note: ACRES contains properties reported through EPA Brownfields grant programs; it is "
        "not a complete inventory of brownfields or contaminated sites.",
        "Note: An ACRES record is not a determination that land is contaminated, available, or "
        "suitable for development. Confirm site conditions through environmental site assessments "
        "and authoritative records.",
    ]

    return "\n".join(lines)


def _format_property_line(prop: Dict) -> str:
    """Render one ACRES property as a single markdown list item."""
    location = ", ".join(filter(None, [prop.get("address"), prop.get("city"), prop.get("county"), prop.get("zip")]))
    identifiers = " / ".join(
        filter(
            None,
            [
                f"FRS Registry ID {prop['frs_registry_id']}" if prop.get("frs_registry_id") else "",
                f"ACRES ID {prop['acres_property_id']}" if prop.get("acres_property_id") else "",
            ],
        )
    )
    coordinates = ""
    if prop.get("latitude") is not None and prop.get("longitude") is not None:
        coordinates = f"({prop['latitude']}, {prop['longitude']})"

    line = f"- **{prop.get('name') or 'Unknown'}**"
    details = " — ".join(filter(None, [location, prop.get("epa_region"), identifiers, coordinates]))
    if details:
        line += f" — {details}"
    if prop.get("facility_url"):
        line += f" — [EPA property record]({prop['facility_url']})"
    if prop.get("distance_miles") is not None:
        line += f" — {prop['distance_miles']:.3f} mi from center"
    return line
