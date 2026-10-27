"""Read-only DoW BRAC research; coverage and access are explicit per source adapter."""

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
from src.apis import (
    installations_api,
    spatial_api,
    documents_api,
    conveyances_api,
    notices_api,
    environmental_sites_api,
    controls_api,
    offers_api,
)

mcp = FastMCP("dow-brac-server")
READ_ONLY = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True}
Identity = Annotated[
    str, Field(description="Source-namespaced local installation ID returned by search; not a government-wide BRAC ID.")
]
PageSize = Annotated[int, Field(ge=1, le=100, description="Maximum records per independent result page, 1–100.")]
Offset = Annotated[
    int,
    Field(
        ge=0,
        le=100000,
        description="Nonnegative result offset; compare fingerprints and restart if source records change.",
    ),
]
Latitude = Annotated[float, Field(ge=-90, le=90, description="Latitude in WGS84 decimal degrees, -90 to 90.")]
Longitude = Annotated[float, Field(ge=-180, le=180, description="Longitude in WGS84 decimal degrees, -180 to 180.")]
Buffer = Annotated[float, Field(ge=0.1, le=100, description="Geodesic buffer in miles, 0.1 to 100.")]


@mcp.tool(annotations=READ_ONLY, timeout=120)
def search_brac_installations(
    query: Annotated[
        str | None,
        Field(description="Installation-name substring within the supported registry; one term or filter is required."),
    ] = None,
    component: Annotated[
        str | None,
        Field(
            description="Supported components: army, navy, marine_corps, air_force; current source coverage differs."
        ),
    ] = None,
    state: Annotated[str | None, Field(description="US state or territory postal code.")] = None,
    brac_round: Annotated[
        int | None, Field(description="Explicit documented action round: 1988, 1991, 1993, 1995, or 2005.")
    ] = None,
    max_results: PageSize = 100,
    result_offset: Offset = 0,
) -> str:
    """Search source-scoped BRAC installation candidates and published actions without requiring geometry."""
    return json.dumps(
        installations_api.search_brac_installations(query, component, state, brac_round, max_results, result_offset)
    )


@mcp.tool(annotations=READ_ONLY, timeout=120)
def get_brac_installation(installation_id: Identity) -> str:
    """Retrieve a BRAC source identity, action evidence, official links, and per-source access limitations."""
    return json.dumps(installations_api.get_brac_installation(installation_id))


@mcp.tool(annotations=READ_ONLY, timeout=120)
def get_brac_installations_in_roi(
    latitude: Latitude,
    longitude: Longitude,
    buffer_miles: Buffer = 25.0,
    include_historical_boundaries: Annotated[
        bool, Field(description="Explicit opt-in to 2010/NTAD2014 historical military-base polygon candidates.")
    ] = False,
    max_results: PageSize = 100,
    result_offset: Offset = 0,
) -> str:
    """Find EPA FRS BRAC-interest points and opt-in historical polygon intersections as unresolved candidates."""
    return json.dumps(
        spatial_api.get_brac_installations_in_roi(
            latitude, longitude, buffer_miles, include_historical_boundaries, max_results, result_offset
        )
    )


@mcp.tool(annotations=READ_ONLY, timeout=120)
def get_brac_documents(
    installation_id: Identity,
    query: Annotated[
        str | None, Field(description="Title search over the fetched supported index, not full document contents.")
    ] = None,
    document_type: Annotated[
        str | None,
        Field(
            description="Only unresolved index-title categories are currently verified; titles do not establish NEPA/remedy scope."
        ),
    ] = None,
    max_results: PageSize = 100,
    result_offset: Offset = 0,
) -> str:
    """List independently paginated official BRAC document links with metadata-only review status."""
    return json.dumps(
        documents_api.get_brac_documents(installation_id, query, document_type, max_results, result_offset)
    )


@mcp.tool(annotations=READ_ONLY, timeout=120)
def get_brac_conveyance_records(
    installation_id: Identity, max_results: PageSize = 100, result_offset: Offset = 0
) -> str:
    """Retrieve published installation conveyance summaries without inferring executed parcel transfers."""
    return json.dumps(conveyances_api.get_brac_conveyance_records(installation_id, max_results, result_offset))


@mcp.tool(annotations=READ_ONLY, timeout=120)
def get_brac_public_notices(
    installation_id: Identity,
    published_on_or_after: Annotated[
        str | None,
        Field(description="YYYY-MM-DD publication lower bound; undated entries remain explicitly unresolved."),
    ] = None,
    max_results: PageSize = 100,
    result_offset: Offset = 0,
) -> str:
    """Retrieve notice-index candidates; unknown dates never become an open participation finding."""
    return json.dumps(
        notices_api.get_brac_public_notices(installation_id, published_on_or_after, max_results, result_offset)
    )


@mcp.tool(annotations=READ_ONLY, timeout=120)
def get_brac_environmental_sites(
    installation_id: Identity, max_results: PageSize = 100, result_offset: Offset = 0
) -> str:
    """Retrieve explicit installation-scoped IR-site/OU index-group candidates with coverage warnings."""
    return json.dumps(environmental_sites_api.get_brac_environmental_sites(installation_id, max_results, result_offset))


@mcp.tool(annotations=READ_ONLY, timeout=240)
def get_brac_land_use_controls(
    installation_id: Identity,
    site_id: Annotated[
        str | None,
        Field(
            description="Optional source-scoped site ID; requires a verified instrument crosswalk, otherwise reports unsupported."
        ),
    ] = None,
    parcel_id: Annotated[
        str | None, Field(description="Optional published parcel ID; never inferred from a similar name or boundary.")
    ] = None,
    max_results: PageSize = 100,
    result_offset: Offset = 0,
) -> str:
    """Retrieve indexed control-document candidates and bounded PDF evidence with unresolved legal effect."""
    return json.dumps(
        controls_api.get_brac_land_use_controls(installation_id, site_id, parcel_id, max_results, result_offset)
    )


@mcp.tool(annotations=READ_ONLY, timeout=120)
def get_brac_property_offers(
    installation_id: Identity,
    include_historical: Annotated[
        bool, Field(description="Request historical offer evidence; unavailable auction-state adapters stay explicit.")
    ] = False,
    max_results: PageSize = 100,
    result_offset: Offset = 0,
) -> str:
    """Retrieve source-reported Army disposal plans through explicit crosswalks; do not infer open auctions."""
    return json.dumps(
        offers_api.get_brac_property_offers(installation_id, include_historical, max_results, result_offset)
    )


if __name__ == "__main__":
    mcp.run(transport="stdio", show_banner=False)
