#!/usr/bin/env python3
"""
MCP Server for EPA Superfund site research

Provides read-only research tools over EPA's NPL status points, total-site,
operable-unit, and institutional-control boundary layers, FRS SEMS interests,
Envirofacts SEMS site and contaminant tables, and EPA Federal Register
documents. EPA's robots-disallowed site-profile and search pages are never
fetched; tools link to them for a person to open.
"""

import logging
import re
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

from src.apis.superfund_api import (
    format_cleanup_actions,
    format_contaminants,
    format_documents,
    format_institutional_controls,
    format_operable_units,
    format_public_notices,
    format_roi_results,
    format_search_results,
    format_site,
    get_epa_superfund_cleanup_actions,
    get_epa_superfund_contaminants,
    get_epa_superfund_documents,
    get_epa_superfund_institutional_controls,
    get_epa_superfund_operable_units,
    get_epa_superfund_public_notices,
    get_epa_superfund_site,
    get_epa_superfund_sites_in_roi,
    search_epa_superfund_sites,
)
from src.core.normalization import DOCUMENT_TYPES
from src.core.sources import MAX_PAGE_SIZE, MAX_RESULT_OFFSET, NPL_STATUS_VALUES, TOOL_TIMEOUT_SECONDS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("epa-superfund-mcp-server")

mcp = FastMCP("epa-superfund-server")

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
    Field(
        ge=MIN_DISTANCE_MILES,
        le=MAX_DISTANCE_MILES,
        description="Buffer distance in miles, valid range 0.1 to 100.0.",
    ),
]
MaxResults = Annotated[
    int,
    Field(ge=1, le=MAX_PAGE_SIZE, description="Maximum records in this response, valid range 1 to 100 (default: 100)."),
]
ResultOffset = Annotated[
    int,
    Field(
        ge=0,
        le=MAX_RESULT_OFFSET,
        description="Zero-based offset into this tool's ordered list, 0 to 9999 (default: 0).",
    ),
]
ResultFingerprint = Annotated[
    str | None,
    Field(
        pattern=r"^[0-9a-f]{64}$",
        description="Reuse the previous response's result fingerprint with the same filters; changed evidence requires restarting pagination.",
    ),
]
EPA_ID_FIELD = Field(
    min_length=12,
    max_length=12,
    pattern=r"^[A-Za-z]{2}[A-Za-z0-9]{10}$",
    description="EPA site identifier (SEMS EPA ID), for example NJD063157150.",
)
EpaId = Annotated[str, EPA_ID_FIELD]
OptionalEpaId = Annotated[str | None, EPA_ID_FIELD]
SemsId = Annotated[
    str | None,
    Field(pattern=r"^\d{1,7}$", description="SEMS numeric site id as a string, e.g. 0200397; leading zeros are kept."),
]
FrsRegistryId = Annotated[
    str | None,
    Field(pattern=r"^\d{12}$", description="12-digit EPA FRS registry identifier for a SEMS facility interest."),
]
Query = Annotated[
    str | None,
    Field(min_length=2, max_length=100, description="Case-insensitive substring of a site name, city, or county."),
]
State = Annotated[
    str | None,
    Field(min_length=2, max_length=2, description="US state or territory postal code, for example NJ."),
]
NplStatus = Annotated[
    Literal[NPL_STATUS_VALUES] | None,
    Field(description="Normalized NPL listing status; records without a published status never match."),
]
InventoryScope = Annotated[
    Literal["npl_and_mapped", "sems_candidates"],
    Field(
        description=(
            "npl_and_mapped: NPL status points and total-site boundaries. sems_candidates: also FRS SEMS interests "
            "and the SEMS site table (broader, includes unresolved candidates)."
        )
    ),
]
OperableUnit = Annotated[
    str | None,
    Field(pattern=r"^\d{1,2}$", description="Operable-unit id as published, e.g. 01; 00 is the sitewide grouping."),
]
Media = Annotated[
    str | None,
    Field(
        min_length=2, max_length=40, description="SEMS media name, e.g. Groundwater, Soil, or Sediment (exact match)."
    ),
]
DocumentQuery = Annotated[
    str | None,
    Field(min_length=2, max_length=100, description="Case-insensitive substring filter over fetched document titles."),
]
DocumentType = Annotated[
    Literal[DOCUMENT_TYPES] | None,
    Field(
        description="Document category inferred from the published title, e.g. record_of_decision or five_year_review."
    ),
]
PublishedDate = Annotated[
    str | None,
    Field(
        pattern=r"^\d{4}-\d{2}-\d{2}$", description="Keep notices published or due on or after this YYYY-MM-DD date."
    ),
]


def _validate_geo_inputs(latitude: Latitude, longitude: Longitude, distance_miles: float) -> tuple[float, float, float]:
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


def _validate_result_window(
    max_results: int, result_offset: int, result_fingerprint: str | None = None
) -> tuple[int, int]:
    """Validate pagination arguments before any upstream calls."""
    if isinstance(max_results, bool) or isinstance(result_offset, bool):
        raise ValueError("max_results and result_offset must be integers")
    try:
        limit = int(max_results)
        offset = int(result_offset)
    except (TypeError, ValueError) as exc:
        raise ValueError("max_results and result_offset must be integers") from exc

    if not 1 <= limit <= MAX_PAGE_SIZE:
        raise ValueError(f"max_results must be between 1 and {MAX_PAGE_SIZE}, got {max_results}")
    if not 0 <= offset <= MAX_RESULT_OFFSET:
        raise ValueError(f"result_offset must be between 0 and {MAX_RESULT_OFFSET}, got {result_offset}")
    if result_fingerprint is not None and (
        not isinstance(result_fingerprint, str) or not re.fullmatch(r"[0-9a-f]{64}", result_fingerprint)
    ):
        raise ValueError("result_fingerprint must be a 64-character lowercase SHA-256 fingerprint")

    return limit, offset


def _check_result_fingerprint(result: dict, expected: str | None) -> None:
    if expected is not None and result["result_fingerprint"] != expected:
        raise ValueError(
            "Evidence or source coverage changed. Restart pagination with result_offset=0 and without result_fingerprint; do not combine these pages."
        )


@mcp.tool(name="search_epa_superfund_sites", annotations=READ_ONLY_TOOL_ANNOTATIONS, timeout=TOOL_TIMEOUT_SECONDS)
def search_epa_superfund_sites_tool(
    query: Query = None,
    state: State = None,
    npl_status: NplStatus = None,
    inventory_scope: InventoryScope = "npl_and_mapped",
    max_results: MaxResults = MAX_PAGE_SIZE,
    result_offset: ResultOffset = 0,
    result_fingerprint: ResultFingerprint = None,
) -> str:
    """Search EPA Superfund site records by name, city, county, state, or NPL listing status.

    Requires at least one filter. Returns typed EPA/SEMS identifiers, per-source
    listing status, published dates, profile links, and boundary availability,
    grouped by EPA ID. Records without a published status never satisfy an
    npl_status filter and are reported separately. No geography is required.
    """
    max_results, result_offset = _validate_result_window(max_results, result_offset, result_fingerprint)
    result = search_epa_superfund_sites(query, state, npl_status, inventory_scope)
    _check_result_fingerprint(result, result_fingerprint)
    return format_search_results(result, max_results=max_results, result_offset=result_offset)


@mcp.tool(name="get_epa_superfund_sites_in_roi", annotations=READ_ONLY_TOOL_ANNOTATIONS, timeout=TOOL_TIMEOUT_SECONDS)
def get_epa_superfund_sites_in_roi_tool(
    latitude: Latitude,
    longitude: Longitude,
    buffer_miles: BufferMiles = 25.0,
    inventory_scope: InventoryScope = "npl_and_mapped",
    max_results: MaxResults = MAX_PAGE_SIZE,
    result_offset: ResultOffset = 0,
    result_fingerprint: ResultFingerprint = None,
) -> str:
    """Find Superfund sites whose NPL status point or total-site polygon intersects a region of interest.

    Combines NPL status points with total-site boundaries (and FRS SEMS interests
    in sems_candidates scope), groups features by EPA ID before paging, reports
    point/polygon match basis, and lists sites nearest-first.

    Args:
        latitude: Latitude in decimal degrees (WGS84), valid range -90 to 90.
        longitude: Longitude in decimal degrees (WGS84), valid range -180 to 180.
        buffer_miles: Buffer distance in miles, valid range 0.1 to 100.0 (default: 25).
    """
    latitude, longitude, buffer_miles = _validate_geo_inputs(latitude, longitude, buffer_miles)
    max_results, result_offset = _validate_result_window(max_results, result_offset, result_fingerprint)
    logger.info("Querying EPA Superfund sites for (%s, %s) with buffer %s mi", latitude, longitude, buffer_miles)
    result = get_epa_superfund_sites_in_roi(latitude, longitude, buffer_miles, inventory_scope)
    _check_result_fingerprint(result, result_fingerprint)
    return format_roi_results(result, max_results=max_results, result_offset=result_offset)


@mcp.tool(name="get_epa_superfund_site", annotations=READ_ONLY_TOOL_ANNOTATIONS, timeout=TOOL_TIMEOUT_SECONDS)
def get_epa_superfund_site_tool(
    epa_id: OptionalEpaId = None,
    sems_id: SemsId = None,
    frs_registry_id: FrsRegistryId = None,
) -> str:
    """Retrieve one Superfund site's identity, per-source listing status, milestones, and mapped evidence.

    Accepts exactly one identifier. Resolves EPA ID and SEMS site id only through
    published crosswalks, keeps FRS registry identity separate, and reports
    partial deletion, federal-facility, archive, non-NPL, and SAA indicators as published.
    """
    result = get_epa_superfund_site(epa_id, sems_id, frs_registry_id)
    return format_site(result)


@mcp.tool(name="get_epa_superfund_operable_units", annotations=READ_ONLY_TOOL_ANNOTATIONS, timeout=TOOL_TIMEOUT_SECONDS)
def get_epa_superfund_operable_units_tool(
    epa_id: EpaId,
    max_results: MaxResults = MAX_PAGE_SIZE,
    result_offset: ResultOffset = 0,
    result_fingerprint: ResultFingerprint = None,
) -> str:
    """List a Superfund site's operable units from SEMS decision records and the OU map layer.

    SEMS decision records list OUs with recorded RODs, amendments, or ESDs
    (no geometry); mapped features keep raw feature types such as deleted-area
    boundaries. OU numbers suggested by feature names are unverified candidates.
    """
    max_results, result_offset = _validate_result_window(max_results, result_offset, result_fingerprint)
    result = get_epa_superfund_operable_units(epa_id)
    _check_result_fingerprint(result, result_fingerprint)
    return format_operable_units(result, max_results=max_results, result_offset=result_offset)


@mcp.tool(
    name="get_epa_superfund_institutional_controls",
    annotations=READ_ONLY_TOOL_ANNOTATIONS,
    timeout=TOOL_TIMEOUT_SECONDS,
)
def get_epa_superfund_institutional_controls_tool(
    epa_id: EpaId,
    max_results: MaxResults = MAX_PAGE_SIZE,
    result_offset: ResultOffset = 0,
    result_fingerprint: ResultFingerprint = None,
) -> str:
    """List a Superfund site's mapped institutional-control boundary records, paged independently.

    Returns raw feature class/type, names, descriptions, dates, published area,
    and feature links. Mapped areas are not executed legal instruments, and an
    empty layer is not evidence that no controls apply.
    """
    max_results, result_offset = _validate_result_window(max_results, result_offset, result_fingerprint)
    result = get_epa_superfund_institutional_controls(epa_id)
    _check_result_fingerprint(result, result_fingerprint)
    return format_institutional_controls(result, max_results=max_results, result_offset=result_offset)


@mcp.tool(name="get_epa_superfund_documents", annotations=READ_ONLY_TOOL_ANNOTATIONS, timeout=TOOL_TIMEOUT_SECONDS)
def get_epa_superfund_documents_tool(
    epa_id: EpaId,
    query: DocumentQuery = None,
    document_type: DocumentType = None,
    max_results: MaxResults = MAX_PAGE_SIZE,
    result_offset: ResultOffset = 0,
    result_fingerprint: ResultFingerprint = None,
) -> str:
    """List official Superfund site document references: NPL notices, SEMS decisions, and Federal Register documents.

    Returns titles, dates, categories, identifiers, and official links with the
    basis for each site association. Document contents are not read, and
    filters apply to titles only.
    """
    max_results, result_offset = _validate_result_window(max_results, result_offset, result_fingerprint)
    result = get_epa_superfund_documents(epa_id, query, document_type)
    _check_result_fingerprint(result, result_fingerprint)
    return format_documents(result, max_results=max_results, result_offset=result_offset)


@mcp.tool(
    name="get_epa_superfund_cleanup_actions", annotations=READ_ONLY_TOOL_ANNOTATIONS, timeout=TOOL_TIMEOUT_SECONDS
)
def get_epa_superfund_cleanup_actions_tool(
    epa_id: EpaId,
    operable_unit: OperableUnit = None,
    max_results: MaxResults = MAX_PAGE_SIZE,
    result_offset: ResultOffset = 0,
    result_fingerprint: ResultFingerprint = None,
) -> str:
    """Retrieve a Superfund site's NPL milestones, recorded decision documents by OU, and Federal Register actions.

    Dated NPL milestones and Federal Register actions naming the site, plus
    undated SEMS decision records per OU. EPA's detailed cleanup schedule is not
    retrieved because EPA's robots.txt disallows automated access to it.
    """
    max_results, result_offset = _validate_result_window(max_results, result_offset, result_fingerprint)
    result = get_epa_superfund_cleanup_actions(epa_id, operable_unit)
    _check_result_fingerprint(result, result_fingerprint)
    return format_cleanup_actions(result, max_results=max_results, result_offset=result_offset)


@mcp.tool(name="get_epa_superfund_contaminants", annotations=READ_ONLY_TOOL_ANNOTATIONS, timeout=TOOL_TIMEOUT_SECONDS)
def get_epa_superfund_contaminants_tool(
    epa_id: EpaId,
    operable_unit: OperableUnit = None,
    media: Media = None,
    max_results: MaxResults = MAX_PAGE_SIZE,
    result_offset: ResultOffset = 0,
    result_fingerprint: ResultFingerprint = None,
) -> str:
    """List a Superfund site's published contaminant, media, OU, and decision-document associations.

    Joins the Envirofacts SEMS site table to its contaminants table on the
    explicit site_id/fk_site_id key. Rows are associations, not concentrations,
    sampling results, exposure findings, or a complete contaminant list.
    """
    max_results, result_offset = _validate_result_window(max_results, result_offset, result_fingerprint)
    result = get_epa_superfund_contaminants(epa_id, operable_unit, media)
    _check_result_fingerprint(result, result_fingerprint)
    return format_contaminants(result, max_results=max_results, result_offset=result_offset)


@mcp.tool(name="get_epa_superfund_public_notices", annotations=READ_ONLY_TOOL_ANNOTATIONS, timeout=TOOL_TIMEOUT_SECONDS)
def get_epa_superfund_public_notices_tool(
    epa_id: EpaId,
    published_on_or_after: PublishedDate = None,
    max_results: MaxResults = MAX_PAGE_SIZE,
    result_offset: ResultOffset = 0,
    result_fingerprint: ResultFingerprint = None,
) -> str:
    """Retrieve Federal Register notices naming a Superfund site, with comment close dates and dockets.

    Covers NPL listings, deletions, partial deletions, and settlements with
    their published close dates and an as-of status; none are derived. Local
    and web-only EPA announcements are not covered.
    """
    max_results, result_offset = _validate_result_window(max_results, result_offset, result_fingerprint)
    result = get_epa_superfund_public_notices(epa_id, published_on_or_after)
    _check_result_fingerprint(result, result_fingerprint)
    return format_public_notices(result, max_results=max_results, result_offset=result_offset)


if __name__ == "__main__":
    mcp.run(transport="stdio", show_banner=False)
