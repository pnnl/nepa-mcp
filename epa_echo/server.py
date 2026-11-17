#!/usr/bin/env python3
"""EPA ECHO facility and ICIS research server."""

import sys
from pathlib import Path
from typing import Annotated, Literal

SERVER_DIR = Path(__file__).resolve().parent
for directory in (SERVER_DIR.parent, SERVER_DIR):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from fastmcp import FastMCP
from pydantic import Field
from nepa_mcp_common.epa_records import render
from src.apis import echo_api as api

mcp = FastMCP("epa-echo-server")
READ_ONLY = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True}
Limit = Annotated[int, Field(ge=1, le=100, description="Maximum records per page (1–100).")]
Offset = Annotated[int, Field(ge=0, le=9999, description="Zero-based record offset, from 0 through 9999.")]
Day = Annotated[
    str,
    Field(
        pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$",
        description="Monitoring period end date boundary, inclusive, in YYYY-MM-DD format.",
    ),
]
Section = Literal["all", "permits", "inspections", "compliance", "quarters", "notices", "actions", "cases"]


@mcp.tool(annotations=READ_ONLY, timeout=60.0)
def search_epa_echo_facilities(
    name: Annotated[
        str | None, Field(min_length=2, max_length=120, description="Facility name or substring; use with state.")
    ] = None,
    state: Annotated[
        str | None, Field(description="Two-letter US state or territory abbreviation for a name search.")
    ] = None,
    latitude: Annotated[
        float | None, Field(ge=-90, le=90, description="WGS84 latitude, -90 to 90 degrees, for a radius search.")
    ] = None,
    longitude: Annotated[
        float | None, Field(ge=-180, le=180, description="WGS84 longitude, -180 to 180 degrees, for a radius search.")
    ] = None,
    radius_miles: Annotated[
        float, Field(ge=0.1, le=100, description="Radius around coordinates in miles (0.1 to 100).")
    ] = 25.0,
    max_results: Limit = 25,
    page_number: Annotated[
        int,
        Field(ge=1, le=10000, description="One-based EPA result page; retain the same page size and search filters."),
    ] = 1,
) -> str:
    """Find regulated facilities by name and state or by distance from project coordinates."""
    return render(api.search(name, state, latitude, longitude, radius_miles, max_results, page_number))


@mcp.tool(annotations=READ_ONLY, timeout=60.0)
def get_epa_echo_facility_report(
    frs_id: Annotated[
        str, Field(pattern=r"^[0-9]{12}$", description="Twelve-digit FRS registry ID from facility search.")
    ],
    section: Annotated[Section, Field(description="Report section; cases includes the ICIS case numbers.")] = "all",
    max_results: Limit = 25,
    result_offset: Offset = 0,
) -> str:
    """Retrieve permits, inspections, quarterly compliance history, and enforcement records for an FRS facility."""
    return render(api.report(frs_id, section, max_results, result_offset))


@mcp.tool(annotations=READ_ONLY, timeout=60.0)
def get_epa_echo_discharge_reports(
    permit_id: Annotated[str, Field(pattern=r"^[A-Z0-9]{9}$", description="Nine-character NPDES permit ID.")],
    start_date: Day,
    end_date: Day,
    outfall: Annotated[
        str | None, Field(description="Optional three-character permitted feature or outfall identifier.")
    ] = None,
    parameter_code: Annotated[
        str | None, Field(description="Optional five-digit EPA pollutant parameter code.")
    ] = None,
    max_results: Limit = 25,
    result_offset: Offset = 0,
) -> str:
    """Retrieve discharge reports, limits, units, no-discharge codes, and reported violations for one NPDES permit."""
    return render(api.discharges(permit_id, start_date, end_date, outfall, parameter_code, max_results, result_offset))


@mcp.tool(annotations=READ_ONLY, timeout=60.0)
def get_epa_echo_civil_case(
    case_number: Annotated[
        str, Field(description="EPA ICIS civil case number from the facility report, e.g. 03-2022-0102.")
    ],
    max_results: Limit = 25,
    result_offset: Offset = 0,
) -> str:
    """Retrieve an ICIS civil enforcement case, statutes, dated actions, and EPA-reported penalties."""
    return render(api.civil_case(case_number, max_results, result_offset))


if __name__ == "__main__":
    mcp.run(transport="stdio", show_banner=False)
