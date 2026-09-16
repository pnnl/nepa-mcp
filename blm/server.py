#!/usr/bin/env python3
"""
MCP Server for BLM (Bureau of Land Management) Data

Provides access to:
- BLM Land Use Plans (approved RMPs/MFPs) for conformance checks
- BLM Wilderness Areas for special designations screening
- BLM National Monuments and NCAs for land use restrictions
"""

import logging
import sys
from pathlib import Path
from typing import Annotated, Literal

# Add the server directory to path for local imports
SERVER_DIR = Path(__file__).resolve().parent
REPO_DIR = SERVER_DIR.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))
if (REPO_DIR / "nepa_mcp_common").exists() and str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

from pydantic import Field

from fastmcp import FastMCP

from src.apis.blm_api import (
    get_blm_land_use_plans_in_roi,
    get_blm_wilderness_areas_in_roi,
    get_blm_national_monuments_in_roi,
    format_blm_land_use_plans_summary,
    format_blm_wilderness_summary,
    format_blm_monuments_summary,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("blm-mcp-server")

mcp = FastMCP("blm-server")

READ_ONLY_TOOL_ANNOTATIONS = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": True,
}
MIN_DISTANCE_MILES = 0.1
MAX_DISTANCE_MILES = 100.0

Latitude = Annotated[
    float,
    Field(
        ge=-90,
        le=90,
        description="Latitude in decimal degrees (WGS84), valid range -90 to 90.",
    ),
]
Longitude = Annotated[
    float,
    Field(
        ge=-180,
        le=180,
        description="Longitude in decimal degrees (WGS84), valid range -180 to 180.",
    ),
]
BufferMiles = Annotated[
    float,
    Field(
        ge=MIN_DISTANCE_MILES,
        le=MAX_DISTANCE_MILES,
        description="Buffer distance in miles, valid range 0.1 to 100.0.",
    ),
]


def _validate_geo_inputs(
    latitude: Latitude,
    longitude: Longitude,
    distance_miles: float,
) -> tuple[float, float, float]:
    """Validate common geospatial tool arguments before upstream calls."""
    try:
        lat = float(latitude)
        lon = float(longitude)
        distance = float(distance_miles)
    except (TypeError, ValueError) as exc:
        raise ValueError("latitude, longitude, and distance arguments must be numeric") from exc

    if not -90 <= lat <= 90:
        raise ValueError(f"latitude must be between -90 and 90, got {latitude}")
    if not -180 <= lon <= 180:
        raise ValueError(f"longitude must be between -180 and 180, got {longitude}")
    if not MIN_DISTANCE_MILES <= distance <= MAX_DISTANCE_MILES:
        raise ValueError(
            f"buffer_miles must be between {MIN_DISTANCE_MILES} and {MAX_DISTANCE_MILES} miles, got {distance_miles}"
        )

    return lat, lon, distance


@mcp.tool(name="get_blm_land_use_plans_in_roi", annotations=READ_ONLY_TOOL_ANNOTATIONS, timeout=60.0)
def get_blm_land_use_plans_in_roi_tool(
    latitude: Latitude, longitude: Longitude, buffer_miles: BufferMiles = 25.0
) -> str:
    """Identify BLM approved land use plans intersecting the ROI.

    Returns land use plans (RMPs, MFPs) with plan name, status, ROD date,
    and ePlanning links. Essential for conformance checks per 43 CFR 1610.5.

    Args:
        latitude: Latitude in decimal degrees (WGS84), valid range -90 to 90.
        longitude: Longitude in decimal degrees (WGS84), valid range -180 to 180.
        buffer_miles: Buffer distance in miles, valid range 0.1 to 100.0 (default: 25).

    Returns:
        Markdown summary of BLM land use plans found within the ROI.
    """
    latitude, longitude, buffer_miles = _validate_geo_inputs(latitude, longitude, buffer_miles)
    logger.info("Querying BLM land use plans for (%s, %s) with buffer %s mi", latitude, longitude, buffer_miles)
    result = get_blm_land_use_plans_in_roi(latitude, longitude, buffer_miles)
    return format_blm_land_use_plans_summary(result)


@mcp.tool(name="get_blm_wilderness_areas_in_roi", annotations=READ_ONLY_TOOL_ANNOTATIONS, timeout=60.0)
def get_blm_wilderness_areas_in_roi_tool(
    latitude: Latitude, longitude: Longitude, buffer_miles: BufferMiles = 25.0
) -> str:
    """Identify BLM designated wilderness areas intersecting the ROI.

    Returns wilderness areas protected under the Wilderness Act of 1964.
    Important for BLM Extraordinary Circumstances screening.

    Args:
        latitude: Latitude in decimal degrees (WGS84), valid range -90 to 90.
        longitude: Longitude in decimal degrees (WGS84), valid range -180 to 180.
        buffer_miles: Buffer distance in miles, valid range 0.1 to 100.0 (default: 25).

    Returns:
        Markdown summary of BLM wilderness areas found within the ROI.
    """
    latitude, longitude, buffer_miles = _validate_geo_inputs(latitude, longitude, buffer_miles)
    logger.info("Querying BLM wilderness areas for (%s, %s) with buffer %s mi", latitude, longitude, buffer_miles)
    result = get_blm_wilderness_areas_in_roi(latitude, longitude, buffer_miles)
    return format_blm_wilderness_summary(result)


@mcp.tool(name="get_blm_national_monuments_in_roi", annotations=READ_ONLY_TOOL_ANNOTATIONS, timeout=60.0)
def get_blm_national_monuments_in_roi_tool(
    latitude: Latitude,
    longitude: Longitude,
    buffer_miles: BufferMiles = 25.0,
    designation_type: Annotated[
        Literal["all", "national_conservation_area", "national_monument"],
        Field(description="Filter the shared BLM service; all retains unclassified and other designations."),
    ] = "all",
) -> str:
    """Identify BLM National Monuments and NCAs intersecting the ROI.

    Returns National Monuments and National Conservation Areas (NCAs).
    These special designations have management restrictions and may trigger
    BLM Extraordinary Circumstances screening.

    Select national_conservation_area for a distinct NCA result. Missing source
    codes remain unclassified unless a cited identifier match establishes type.

    Args:
        latitude: Latitude in decimal degrees (WGS84), valid range -90 to 90.
        longitude: Longitude in decimal degrees (WGS84), valid range -180 to 180.
        buffer_miles: Buffer distance in miles, valid range 0.1 to 100.0 (default: 25).

    Returns:
        Markdown summary of BLM National Monuments and NCAs found within the ROI.
    """
    latitude, longitude, buffer_miles = _validate_geo_inputs(latitude, longitude, buffer_miles)
    logger.info("Querying BLM national monuments for (%s, %s) with buffer %s mi", latitude, longitude, buffer_miles)
    result = get_blm_national_monuments_in_roi(latitude, longitude, buffer_miles, designation_type=designation_type)
    return format_blm_monuments_summary(result)


if __name__ == "__main__":
    mcp.run(transport="stdio", show_banner=False)
