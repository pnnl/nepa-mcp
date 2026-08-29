#!/usr/bin/env python3
"""MCP server for USDA-NRCS SSURGO soil-survey screening."""

import logging
import sys
from pathlib import Path
from typing import Annotated

SERVER_DIR = Path(__file__).resolve().parent
REPO_DIR = SERVER_DIR.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))
if (REPO_DIR / "nepa_mcp_common").exists() and str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

from fastmcp import FastMCP
from pydantic import Field

from nepa_mcp_common.validation import validate_coordinates
from src.apis.nrcs_soils_api import (
    format_farmland_classification_summary,
    format_soil_constraints_summary,
    format_soil_mapunits_summary,
    get_farmland_classification_in_roi,
    get_soil_mapunits_in_roi,
    summarize_soil_constraints_for_siting,
)
from src.core.constants import MAX_MAPUNIT_OFFSET, MAX_MAPUNIT_PAGE_SIZE

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nrcs-soils-mcp-server")

mcp = FastMCP("nrcs-soils-server")

READ_ONLY_TOOL_ANNOTATIONS = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": True,
}
MIN_DISTANCE_MILES = 0.1
MAX_DISTANCE_MILES = 10.0
DEFAULT_BUFFER_MILES = 1.0

Latitude = Annotated[
    float,
    Field(ge=-90, le=90, description="Latitude in decimal degrees (WGS84), valid range -90 to 90."),
]
Longitude = Annotated[
    float,
    Field(ge=-180, le=180, description="Longitude in decimal degrees (WGS84), valid range -180 to 180."),
]
BufferMiles = Annotated[
    float,
    Field(
        ge=MIN_DISTANCE_MILES,
        le=MAX_DISTANCE_MILES,
        description="Soil-screening buffer in miles, valid range 0.1 to 10.0.",
    ),
]
MaxResults = Annotated[
    int,
    Field(
        ge=1,
        le=MAX_MAPUNIT_PAGE_SIZE,
        description="Maximum map-unit records to return, valid range 1 to 100 (default: 50).",
    ),
]
ResultOffset = Annotated[
    int,
    Field(
        ge=0,
        le=MAX_MAPUNIT_OFFSET,
        description="Zero-based offset into map units ordered by intersected ROI acreage, valid range 0 to 499.",
    ),
]


def _validate_geo_inputs(latitude: Latitude, longitude: Longitude, buffer_miles: float) -> tuple[float, float, float]:
    return validate_coordinates(
        latitude,
        longitude,
        buffer_miles,
        min_distance_miles=MIN_DISTANCE_MILES,
        max_distance_miles=MAX_DISTANCE_MILES,
    )


def _validate_result_window(max_results: int, result_offset: int) -> tuple[int, int]:
    try:
        limit = int(max_results)
        offset = int(result_offset)
    except (TypeError, ValueError) as exc:
        raise ValueError("max_results and result_offset must be integers") from exc
    if not 1 <= limit <= MAX_MAPUNIT_PAGE_SIZE:
        raise ValueError(f"max_results must be between 1 and {MAX_MAPUNIT_PAGE_SIZE}, got {max_results}")
    if not 0 <= offset <= MAX_MAPUNIT_OFFSET:
        raise ValueError(f"result_offset must be between 0 and {MAX_MAPUNIT_OFFSET}, got {result_offset}")
    return limit, offset


@mcp.tool(name="get_nrcs_ssurgo_mapunits_in_roi", annotations=READ_ONLY_TOOL_ANNOTATIONS, timeout=90.0)
def get_nrcs_ssurgo_mapunits_in_roi_tool(
    latitude: Latitude,
    longitude: Longitude,
    buffer_miles: BufferMiles = DEFAULT_BUFFER_MILES,
    max_results: MaxResults = 50,
    result_offset: ResultOffset = 0,
) -> str:
    """Get USDA-NRCS SSURGO soil map units intersecting a project-area buffer.

    Returns clipped acreage, ROI percentage, map-unit identity, farmland class,
    survey area, and survey version. This is soil-survey screening, not a
    geotechnical investigation or wetland delineation.
    """
    latitude, longitude, buffer_miles = _validate_geo_inputs(latitude, longitude, buffer_miles)
    max_results, result_offset = _validate_result_window(max_results, result_offset)
    logger.info("Querying NRCS SSURGO map units for (%s, %s)", latitude, longitude)
    data = get_soil_mapunits_in_roi(latitude, longitude, buffer_miles)
    return format_soil_mapunits_summary(data, max_results=max_results, result_offset=result_offset)


@mcp.tool(name="analyze_nrcs_ssurgo_soil_constraints", annotations=READ_ONLY_TOOL_ANNOTATIONS, timeout=90.0)
def analyze_nrcs_ssurgo_soil_constraints_tool(
    latitude: Latitude,
    longitude: Longitude,
    buffer_miles: BufferMiles = DEFAULT_BUFFER_MILES,
) -> str:
    """Summarize NRCS SSURGO soil indicators relevant to early siting review.

    Reports component-weighted hydrologic groups and drainage classes, slopes,
    restrictive layers, erosion K factors, and farmland context without a
    composite suitability score. This is not geotechnical advice.
    """
    latitude, longitude, buffer_miles = _validate_geo_inputs(latitude, longitude, buffer_miles)
    logger.info("Analyzing NRCS SSURGO soil constraints for (%s, %s)", latitude, longitude)
    data = summarize_soil_constraints_for_siting(latitude, longitude, buffer_miles)
    return format_soil_constraints_summary(data)


@mcp.tool(name="get_nrcs_ssurgo_farmland_classification_in_roi", annotations=READ_ONLY_TOOL_ANNOTATIONS, timeout=90.0)
def get_nrcs_ssurgo_farmland_classification_in_roi_tool(
    latitude: Latitude,
    longitude: Longitude,
    buffer_miles: BufferMiles = DEFAULT_BUFFER_MILES,
) -> str:
    """Get exact NRCS SSURGO farmland classifications within a project-area buffer.

    Summarizes clipped acreage by the source classification while preserving
    conditional wording. It is not an FPPA applicability or agency decision.
    """
    latitude, longitude, buffer_miles = _validate_geo_inputs(latitude, longitude, buffer_miles)
    logger.info("Querying NRCS SSURGO farmland classes for (%s, %s)", latitude, longitude)
    data = get_farmland_classification_in_roi(latitude, longitude, buffer_miles)
    return format_farmland_classification_summary(data)


if __name__ == "__main__":
    mcp.run(transport="stdio", show_banner=False)
