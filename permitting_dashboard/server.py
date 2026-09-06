#!/usr/bin/env python3
"""MCP server for public federal permitting projects, reviews, and milestones."""

from __future__ import annotations

import logging
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

from src.apis.permitting_dashboard_api import (
    find_permitting_milestones,
    get_project_permitting_timetable,
    search_permitting_projects,
)
from src.core.constants import MAX_OFFSET, MAX_RESULTS, MAX_TIMETABLE_ROWS, TOOL_TIMEOUT_SECONDS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("permitting-dashboard-mcp-server")
mcp = FastMCP("permitting-dashboard-server")
READ_ONLY_TOOL_ANNOTATIONS = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": True,
}
TextFilter = Annotated[
    str | None, Field(min_length=1, max_length=160, description="Case-insensitive substring; no SQL LIKE wildcards.")
]
States = Annotated[
    list[str] | None,
    Field(min_length=1, max_length=10, description="US state/territory postal codes; primary project location only."),
]
ProjectStatus = Literal["In Progress", "Planned", "Paused", "Complete", "Cancelled", "Class of Action Changed"] | None
MaxResults = Annotated[int, Field(strict=True, ge=1, le=MAX_RESULTS)]
TimetableLimit = Annotated[int, Field(strict=True, ge=1, le=MAX_TIMETABLE_ROWS)]
ResultOffset = Annotated[int, Field(strict=True, ge=0, le=MAX_OFFSET)]
ProjectId = Annotated[str, Field(pattern=r"^[0-9]{1,20}$", description="Exact project ID returned by search.")]
DateFilter = Annotated[
    str | None, Field(pattern=r"^\d{4}-\d{2}-\d{2}$", description="Inclusive YYYY-MM-DD date, relative to UTC today.")
]
Snapshot = Annotated[
    int | None,
    Field(
        strict=True,
        ge=1,
        le=253402300799,
        description="For subsequent pages, pass source.snapshot_updated_at from the first page; a changed snapshot requires restarting.",
    ),
]


@mcp.tool(name="search_permitting_projects", annotations=READ_ONLY_TOOL_ANNOTATIONS, timeout=TOOL_TIMEOUT_SECONDS)
def search_permitting_projects_tool(
    query: TextFilter = None,
    states: States = None,
    sector: TextFilter = None,
    lead_agency: TextFilter = None,
    category: TextFilter = None,
    project_status: ProjectStatus = None,
    max_results: MaxResults = 25,
    result_offset: ResultOffset = 0,
    snapshot_updated_at: Snapshot = None,
) -> dict:
    """Find projects on the federal Permitting Dashboard by name, location, sector, agency, or status.

    Returns canonical project records, exact source labels, source freshness,
    and bounded pagination. query searches project titles; lead_agency also
    searches the lead bureau. Filters are combined with AND. Coverage is only
    dashboard-listed projects, not all development or all required permits.
    """
    return search_permitting_projects(
        query, states, sector, lead_agency, category, project_status, max_results, result_offset, snapshot_updated_at
    )


@mcp.tool(name="get_project_permitting_timetable", annotations=READ_ONLY_TOOL_ANNOTATIONS, timeout=TOOL_TIMEOUT_SECONDS)
def get_project_permitting_timetable_tool(
    project_id: ProjectId,
    max_results: TimetableLimit = 500,
    result_offset: ResultOffset = 0,
    snapshot_updated_at: Snapshot = None,
) -> dict:
    """Retrieve a project's tracked reviews, responsible agencies, milestones, and permitting dates.

    Groups a bounded page of source rows into actions and milestones, retaining
    completed and not-applicable entries. Preserves baseline, target, alternative,
    actual dates and quality warnings. Effective target uses alternative before
    target; summary_scope identifies partial-page versus complete-project counts.
    A completed review does not mean construction approval or all permits secured.
    """
    return get_project_permitting_timetable(project_id, max_results, result_offset, snapshot_updated_at)


@mcp.tool(name="find_permitting_milestones", annotations=READ_ONLY_TOOL_ANNOTATIONS, timeout=TOOL_TIMEOUT_SECONDS)
def find_permitting_milestones_tool(
    mode: Literal["upcoming", "recently_completed", "past_target"] = "upcoming",
    date_from: DateFilter = None,
    date_to: DateFilter = None,
    project_id: ProjectId | None = None,
    states: States = None,
    sector: TextFilter = None,
    agency: TextFilter = None,
    action_type: TextFilter = None,
    project_status: ProjectStatus = None,
    max_results: MaxResults = 25,
    result_offset: ResultOffset = 0,
    snapshot_updated_at: Snapshot = None,
) -> dict:
    """Find upcoming, recently completed, or past-target incomplete permitting milestones.

    Defaults: upcoming today through 30 days ahead; recently_completed previous
    30 days through today; past_target before today. Dates use UTC today and
    inclusive bounds. Pending modes use alternative then target dates and only
    In Progress/Planned projects and actions, with incomplete, applicable milestones
    lacking actual dates. Completed mode uses actual dates and excludes future
    completions. agency filters the action responsible agency; action_type is a
    substring. Past target is an observation, not a finding of agency delay.
    """
    return find_permitting_milestones(
        mode,
        date_from,
        date_to,
        project_id,
        states,
        sector,
        agency,
        action_type,
        project_status,
        max_results,
        result_offset,
        snapshot_updated_at,
    )


if __name__ == "__main__":
    mcp.run(transport="stdio", show_banner=False)
