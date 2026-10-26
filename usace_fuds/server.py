"""Read-only FUDS property, restoration, mapped response-area, and program office research."""

import json
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
from src.apis import fuds_api as api

mcp = FastMCP("usace-fuds-server")
READ_ONLY = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True}
Latitude = Annotated[float, Field(ge=-90, le=90, description="Latitude in WGS84 decimal degrees, -90 to 90.")]
Longitude = Annotated[float, Field(ge=-180, le=180, description="Longitude in WGS84 decimal degrees, -180 to 180.")]
Buffer = Annotated[float, Field(ge=0.1, le=100, description="Geodesic buffer in miles, 0.1 to 100.")]
PageSize = Annotated[int, Field(ge=1, le=100, description="Maximum returned records per page, 1 to 100.")]
Offset = Annotated[
    int, Field(ge=0, le=100000, description="Nonnegative result offset; compare fingerprints between pages.")
]


@mcp.tool(annotations=READ_ONLY, timeout=90)
def get_usace_fuds_properties_in_roi(
    latitude: Latitude,
    longitude: Longitude,
    buffer_miles: Buffer = 25.0,
    max_results: PageSize = 100,
    result_offset: Offset = 0,
) -> str:
    """Find published FUDS property points and intersecting polygons; deduplicate before pagination."""
    return json.dumps(
        api.get_usace_fuds_properties_in_roi(latitude, longitude, buffer_miles, max_results, result_offset),
        ensure_ascii=False,
    )


@mcp.tool(annotations=READ_ONLY, timeout=90)
def get_usace_fuds_property(
    property_number: Annotated[str, Field(description="Public FUDS property number, such as A04MS0002.")],
) -> str:
    """Retrieve FUDS property records by public number, preserving source conflicts and boundary coverage."""
    return json.dumps(api.get_usace_fuds_property(property_number), ensure_ascii=False)


@mcp.tool(annotations=READ_ONLY, timeout=90)
def get_usace_fuds_projects(
    property_number: Annotated[str, Field(description="Public FUDS property number, such as A04MS0002.")],
    max_results: PageSize = 100,
    result_offset: Offset = 0,
) -> str:
    """List FUDS restoration projects by property key, preserving dates, costs, and priority context."""
    return json.dumps(api.get_usace_fuds_projects(property_number, max_results, result_offset), ensure_ascii=False)


@mcp.tool(annotations=READ_ONLY, timeout=90)
def get_usace_fuds_munitions_response_sites_in_roi(
    latitude: Latitude,
    longitude: Longitude,
    buffer_miles: Buffer = 25.0,
    max_results: PageSize = 100,
    result_offset: Offset = 0,
) -> str:
    """Find mapped FUDS munitions response areas; polygons are research leads, not individual hazard locations."""
    return json.dumps(
        api.get_usace_fuds_munitions_response_sites_in_roi(
            latitude, longitude, buffer_miles, max_results, result_offset
        ),
        ensure_ascii=False,
    )


@mcp.tool(annotations=READ_ONLY, timeout=90)
def get_usace_fuds_program_district(
    property_number: Annotated[
        str | None, Field(description="Public FUDS property number, such as A04MS0002; exclusive of coordinates.")
    ] = None,
    latitude: Annotated[
        float | None,
        Field(ge=-90, le=90, description="Optional latitude in WGS84 degrees, -90 to 90; use with longitude only."),
    ] = None,
    longitude: Annotated[
        float | None,
        Field(ge=-180, le=180, description="Optional longitude in WGS84 degrees, -180 to 180; use with latitude only."),
    ] = None,
) -> str:
    """Resolve a recorded property assignment or coordinate matches in FUDS program districts."""
    return json.dumps(api.get_usace_fuds_program_district(property_number, latitude, longitude), ensure_ascii=False)


if __name__ == "__main__":
    mcp.run(transport="stdio", show_banner=False)
