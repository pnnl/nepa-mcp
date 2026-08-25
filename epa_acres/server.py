#!/usr/bin/env python3
"""
MCP Server for EPA ACRES Brownfields properties

Provides grantee-reported EPA ACRES Brownfields property records for NEPA
screening and contaminated-site redevelopment research.
"""

import logging
import sys
from pathlib import Path
from typing import Annotated

# Add the server directory to path for local imports
SERVER_DIR = Path(__file__).resolve().parent
REPO_DIR = SERVER_DIR.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))
if (REPO_DIR / "nepa_mcp_common").exists() and str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

from pydantic import Field

from fastmcp import FastMCP

from src.apis.acres_api import (
    MAX_PAGE_SIZE,
    MAX_RESULT_OFFSET,
    get_epa_acres_properties_in_roi,
    format_epa_acres_summary,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("epa-acres-mcp-server")

mcp = FastMCP("epa-acres-server")

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
MaxResults = Annotated[
    int,
    Field(
        ge=1,
        le=MAX_PAGE_SIZE,
        description="Maximum property records to return, valid range 1 to 100 (default: 100).",
    ),
]
ResultOffset = Annotated[
    int,
    Field(
        ge=0,
        le=MAX_RESULT_OFFSET,
        description="Zero-based offset into the nearest-first property list, valid range 0 to 9999 (default: 0).",
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


def _validate_result_window(max_results: int, result_offset: int) -> tuple[int, int]:
    """Validate pagination arguments before any upstream calls."""
    try:
        limit = int(max_results)
        offset = int(result_offset)
    except (TypeError, ValueError) as exc:
        raise ValueError("max_results and result_offset must be integers") from exc

    if not 1 <= limit <= MAX_PAGE_SIZE:
        raise ValueError(f"max_results must be between 1 and {MAX_PAGE_SIZE}, got {max_results}")
    if not 0 <= offset <= MAX_RESULT_OFFSET:
        raise ValueError(f"result_offset must be between 0 and {MAX_RESULT_OFFSET}, got {result_offset}")

    return limit, offset


@mcp.tool(name="get_epa_acres_properties_in_roi", annotations=READ_ONLY_TOOL_ANNOTATIONS, timeout=60.0)
def get_epa_acres_properties_in_roi_tool(
    latitude: Latitude,
    longitude: Longitude,
    buffer_miles: BufferMiles = 25.0,
    max_results: MaxResults = MAX_PAGE_SIZE,
    result_offset: ResultOffset = 0,
) -> str:
    """Query EPA ACRES Brownfields property records within a region of interest.

    Returns identifiable Brownfields properties reported to EPA's ACRES system
    through Brownfields grant programs, with property name, location, EPA region,
    FRS registry ID, ACRES property ID, coordinates, and source URL. ACRES is not
    a complete inventory of brownfields or contaminated sites, and a record is
    not a determination that land is available or suitable for development.

    Args:
        latitude: Latitude in decimal degrees (WGS84), valid range -90 to 90.
        longitude: Longitude in decimal degrees (WGS84), valid range -180 to 180.
        buffer_miles: Buffer distance in miles, valid range 0.1 to 100.0 (default: 25).
        max_results: Maximum records in this response, valid range 1 to 100 (default: 100).
        result_offset: Zero-based offset into records sorted nearest-first (default: 0).

    Returns:
        Markdown summary of ACRES Brownfields properties within the ROI.
    """
    latitude, longitude, buffer_miles = _validate_geo_inputs(latitude, longitude, buffer_miles)
    max_results, result_offset = _validate_result_window(max_results, result_offset)
    logger.info("Querying EPA ACRES for (%s, %s) with buffer %s mi", latitude, longitude, buffer_miles)
    result = get_epa_acres_properties_in_roi(latitude, longitude, buffer_miles)
    return format_epa_acres_summary(result, max_results=max_results, result_offset=result_offset)


if __name__ == "__main__":
    mcp.run(transport="stdio", show_banner=False)
