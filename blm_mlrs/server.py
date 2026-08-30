#!/usr/bin/env python3
"""MCP server for public BLM Mineral & Land Records System case data."""

from __future__ import annotations

import logging
import math
import sys
from pathlib import Path
from typing import Annotated, Literal

SERVER_DIR = Path(__file__).resolve().parent
REPO_DIR = SERVER_DIR.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))
if (REPO_DIR / "nepa_mcp_common").exists() and str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

from fastmcp import FastMCP
from pydantic import Field

from src.apis.blm_mlrs_api import (
    format_energy_leases_summary,
    format_land_use_authorizations_summary,
    format_locatable_operations_summary,
    get_energy_leases_in_roi,
    get_land_use_authorizations_in_roi,
    get_locatable_operations_in_roi,
    validate_result_window,
)
from src.core.constants import MAX_RESULT_OFFSET, MAX_RESULTS_PER_SOURCE, TOOL_TIMEOUT_SECONDS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("blm-mlrs-mcp-server")

mcp = FastMCP("blm-mlrs-server")

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
    Field(ge=-90, le=90, description="Latitude in decimal degrees (WGS84), valid range -90 to 90."),
]
Longitude = Annotated[
    float,
    Field(ge=-180, le=180, description="Longitude in decimal degrees (WGS84), valid range -180 to 180."),
]
BufferMiles = Annotated[
    float,
    Field(ge=0.1, le=100.0, description="Buffer distance in miles, valid range 0.1 to 100.0."),
]
MaxResultsPerSource = Annotated[
    int,
    Field(
        ge=1,
        le=MAX_RESULTS_PER_SOURCE,
        description="Maximum records returned from each source family, valid range 1 to 100.",
    ),
]
ResultOffsetPerSource = Annotated[
    int,
    Field(
        ge=0,
        le=MAX_RESULT_OFFSET,
        description="Zero-based offset applied independently to each source family, valid range 0 to 9999.",
    ),
]
SourceDispositions = Annotated[
    list[Literal["Authorized", "Pending", "Interim", "Closed"]] | None,
    Field(
        description=(
            "Exact BLM source dispositions to include. When supplied, this overrides include_closed. "
            "Allowed values are Authorized, Pending, Interim, and Closed."
        )
    ),
]
OperationsDispositions = Annotated[
    list[Literal["Authorized", "Pending"]] | None,
    Field(description="Exact BLM source dispositions to include: Authorized and/or Pending."),
]
AuthorizationFamily = Annotated[
    Literal["all", "right_of_way", "lease_permit_easement"],
    Field(description="Authorization source family to query."),
]
LandUseProductCategory = Annotated[
    Literal["all", "transmission", "solar_wind", "pipeline", "road", "communications", "other"],
    Field(description="Research category matched against the exact BLM product text."),
]
OperationFamily = Annotated[
    Literal["all", "plan_of_operations", "notice"],
    Field(description="Locatable-operation source family to query."),
]
LeaseFamily = Annotated[
    Literal["all", "geothermal", "oil_and_gas"],
    Field(description="Energy-lease source family to query."),
]
TextFilter = Annotated[
    str | None,
    Field(
        min_length=1,
        max_length=80,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9 &(),.'/_-]{0,79}$",
        description="Case-insensitive text contained in the exact BLM source field.",
    ),
]


def _validate_geo_inputs(latitude: float, longitude: float, buffer_miles: float) -> tuple[float, float, float]:
    try:
        lat = float(latitude)
        lon = float(longitude)
        distance = float(buffer_miles)
    except (TypeError, ValueError) as exc:
        raise ValueError("latitude, longitude, and buffer_miles must be numeric") from exc
    if not all(math.isfinite(value) for value in (lat, lon, distance)):
        raise ValueError("latitude, longitude, and buffer_miles must be finite")
    if not -90 <= lat <= 90:
        raise ValueError(f"latitude must be between -90 and 90, got {latitude}")
    if not -180 <= lon <= 180:
        raise ValueError(f"longitude must be between -180 and 180, got {longitude}")
    if not MIN_DISTANCE_MILES <= distance <= MAX_DISTANCE_MILES:
        raise ValueError(
            f"buffer_miles must be between {MIN_DISTANCE_MILES} and {MAX_DISTANCE_MILES}, got {buffer_miles}"
        )
    return lat, lon, distance


def _validate_pagination(max_results_per_source: int, result_offset_per_source: int) -> tuple[int, int]:
    return validate_result_window(max_results_per_source, result_offset_per_source)


@mcp.tool(
    name="get_blm_mlrs_land_use_authorizations_in_roi",
    annotations=READ_ONLY_TOOL_ANNOTATIONS,
    timeout=TOOL_TIMEOUT_SECONDS,
)
def get_blm_mlrs_land_use_authorizations_in_roi_tool(
    latitude: Latitude,
    longitude: Longitude,
    buffer_miles: BufferMiles = 25.0,
    include_closed: Annotated[
        bool,
        Field(
            description=(
                "Include Closed source dispositions in the default disposition set. Ignored when "
                "source_dispositions is supplied."
            )
        ),
    ] = False,
    source_dispositions: SourceDispositions = None,
    authorization_family: AuthorizationFamily = "all",
    product_category: LandUseProductCategory = "all",
    max_results_per_source: MaxResultsPerSource = 25,
    result_offset_per_source: ResultOffsetPerSource = 0,
) -> str:
    """Screen public BLM MLRS right-of-way, lease, permit, and easement case records.

    Results preserve exact BLM dispositions and provide case serial numbers for
    follow-up. Intersections are legal-description-derived screening records,
    not surveyed footprints, title opinions, or authorization determinations.
    Exact source, disposition, and product filters are available. Pagination is
    applied independently to each source family after complete matching object
    IDs and pre-pagination source counts are retrieved.
    """
    lat, lon, distance = _validate_geo_inputs(latitude, longitude, buffer_miles)
    limit, offset = _validate_pagination(max_results_per_source, result_offset_per_source)
    return format_land_use_authorizations_summary(
        get_land_use_authorizations_in_roi(
            lat,
            lon,
            distance,
            include_closed=include_closed,
            source_dispositions=source_dispositions,
            authorization_family=authorization_family,
            product_category=product_category,
            max_results_per_source=limit,
            result_offset_per_source=offset,
        )
    )


@mcp.tool(
    name="get_blm_mlrs_locatable_operations_in_roi",
    annotations=READ_ONLY_TOOL_ANNOTATIONS,
    timeout=TOOL_TIMEOUT_SECONDS,
)
def get_blm_mlrs_locatable_operations_in_roi_tool(
    latitude: Latitude,
    longitude: Longitude,
    buffer_miles: BufferMiles = 25.0,
    source_dispositions: OperationsDispositions = None,
    operation_family: OperationFamily = "all",
    commodity_filter: TextFilter = None,
    max_results_per_source: MaxResultsPerSource = 25,
    result_offset_per_source: ResultOffsetPerSource = 0,
) -> str:
    """Screen BLM MLRS locatable-mineral plans of operations and notices.

    Plans and notices remain distinct and can be filtered independently. An
    Authorized source disposition or PRDCNG production indicator does not
    establish that operations are underway or that all approvals exist.
    """
    lat, lon, distance = _validate_geo_inputs(latitude, longitude, buffer_miles)
    limit, offset = _validate_pagination(max_results_per_source, result_offset_per_source)
    return format_locatable_operations_summary(
        get_locatable_operations_in_roi(
            lat,
            lon,
            distance,
            source_dispositions=source_dispositions,
            operation_family=operation_family,
            commodity_filter=commodity_filter,
            max_results_per_source=limit,
            result_offset_per_source=offset,
        )
    )


@mcp.tool(
    name="get_blm_mlrs_energy_leases_in_roi",
    annotations=READ_ONLY_TOOL_ANNOTATIONS,
    timeout=TOOL_TIMEOUT_SECONDS,
)
def get_blm_mlrs_energy_leases_in_roi_tool(
    latitude: Latitude,
    longitude: Longitude,
    buffer_miles: BufferMiles = 25.0,
    include_closed: Annotated[
        bool,
        Field(
            description=(
                "Include Closed lease dispositions in the default disposition set. Ignored when "
                "source_dispositions is supplied."
            )
        ),
    ] = False,
    source_dispositions: SourceDispositions = None,
    lease_family: LeaseFamily = "all",
    commodity_filter: TextFilter = None,
    formation_filter: TextFilter = None,
    max_results_per_source: MaxResultsPerSource = 25,
    result_offset_per_source: ResultOffsetPerSource = 0,
) -> str:
    """Screen BLM MLRS geothermal and oil-and-gas lease case records.

    A lease record is a mineral-interest indicator, not approval for drilling,
    exploration, utilization, production, or other ground disturbance. Source
    families, dispositions, commodities, and formations can be filtered.
    """
    lat, lon, distance = _validate_geo_inputs(latitude, longitude, buffer_miles)
    limit, offset = _validate_pagination(max_results_per_source, result_offset_per_source)
    return format_energy_leases_summary(
        get_energy_leases_in_roi(
            lat,
            lon,
            distance,
            include_closed=include_closed,
            source_dispositions=source_dispositions,
            lease_family=lease_family,
            commodity_filter=commodity_filter,
            formation_filter=formation_filter,
            max_results_per_source=limit,
            result_offset_per_source=offset,
        )
    )


if __name__ == "__main__":
    mcp.run(transport="stdio", show_banner=False)
