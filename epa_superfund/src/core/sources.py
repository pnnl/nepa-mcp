"""Verified EPA Superfund source manifest, identifiers, vocabularies, and access policy.

Every URL, field name, coded value, and spatial reference below was checked
against the live services on 2026-10-21. The six ArcGIS layers (including the Superfund
Sites in Reuse points), the two Envirofacts DMAP SEMS tables, and the Federal Register API are different source
universes; none is a substitute for another.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

# =============================================================================
# ARCGIS LAYERS
# =============================================================================

ARCGIS_ROOT = "https://services.arcgis.com/cJ9YHowT8TU7DUyn/arcgis/rest/services"


@dataclass(frozen=True)
class LayerSpec:
    key: str
    label: str
    url: str
    oid_field: str
    epa_id_field: str
    name_field: str
    native_wkid: int
    out_fields: tuple[str, ...]
    layer_id: int = 0

    @property
    def layer_url(self) -> str:
        return f"{self.url}/{self.layer_id}"


_BOUNDARY_FIELDS = (
    "OBJECTID",
    "EPA_ID",
    "SITE_NAME",
    "REGION_CODE",
    "EPA_PROGRAM",
    "SITE_FEATURE_CLASS",
    "SITE_FEATURE_TYPE",
    "SITE_FEATURE_NAME",
    "SITE_FEATURE_DESCRIPTION",
    "NPL_STATUS_CODE",
    "FEDERAL_FACILITY_DETER_CODE",
    "LAST_CHANGE_DATE",
    "ORIGINAL_CREATION_DATE",
    "SITE_FEATURE_SOURCE",
    "CITY_NAME",
    "COUNTY",
    "STATE_CODE",
    "URL_ALIAS_TXT",
    "FEATURE_INFO_URL",
    "FEATURE_INFO_URL_DESC",
    "GIS_AREA",
    "GIS_AREA_UNITS",
)

# The point layer's OBJECTID is null for every record; its real OID is ObjectId2.
NPL_POINTS = LayerSpec(
    key="npl_points",
    label="EPA NPL sites with status information (points)",
    url=f"{ARCGIS_ROOT}/Superfund_National_Priorities_List_%28NPL%29_Sites_with_Status_Information/FeatureServer",
    oid_field="ObjectId2",
    epa_id_field="Site_EPA_ID",
    name_field="Site_Name",
    native_wkid=3857,
    out_fields=(
        "ObjectId2",
        "Site_Name",
        "Site_EPA_ID",
        "SEMS_ID",
        "Region_ID",
        "State",
        "City",
        "County",
        "Status",
        "Latitude",
        "Longitude",
        "Proposed_Date",
        "Listing_Date",
        "Construction_Completion_Date",
        "Construction_Completion_Number",
        "NOID_Date",
        "Deletion_Date",
        "Site_Listing_Narrative",
        "Site_Progress_Profile",
        "Notice_of_Data_Availability",
        "Proposed_FR_Notice",
        "Final_FR_Notice",
        "Deletion_FR_Notice",
        "NOID_FR_Notice",
        "Restoration_FR_Notice_Jumper_Page",
        "Site_has_had_a_Partial_Deletion",
    ),
)
SITE_BOUNDARIES = LayerSpec(
    key="site_boundaries",
    label="EPA Superfund total-site boundaries",
    url=f"{ARCGIS_ROOT}/FAC_Superfund_Site_Boundaries_EPA_Public/FeatureServer",
    oid_field="OBJECTID",
    epa_id_field="EPA_ID",
    name_field="SITE_NAME",
    native_wkid=4326,
    out_fields=_BOUNDARY_FIELDS,
)
OU_BOUNDARIES = LayerSpec(
    key="ou_boundaries",
    label="EPA Superfund operable-unit boundaries",
    url=f"{ARCGIS_ROOT}/FAC_Superfund_Operable_Unit_Boundaries_EPA_Public/FeatureServer",
    oid_field="OBJECTID",
    epa_id_field="EPA_ID",
    name_field="SITE_NAME",
    native_wkid=4326,
    out_fields=_BOUNDARY_FIELDS,
)
IC_BOUNDARIES = LayerSpec(
    key="ic_boundaries",
    label="EPA Superfund institutional-control boundaries",
    url=f"{ARCGIS_ROOT}/FAC_Superfund_Institutional_Control_Boundaries_EPA_Public/FeatureServer",
    oid_field="OBJECTID",
    epa_id_field="EPA_ID",
    name_field="SITE_NAME",
    native_wkid=4326,
    out_fields=_BOUNDARY_FIELDS,
)
# FRS reports NAD83 (wkid 4269); LATITUDE83/LONGITUDE83 are never relabeled WGS84.
FRS_SEMS = LayerSpec(
    key="frs_sems",
    label="EPA FRS SEMS facility-interest points",
    url=f"{ARCGIS_ROOT}/FRS_INTERESTS_SEMS/FeatureServer",
    oid_field="OBJECTID",
    epa_id_field="PGM_SYS_ID",
    name_field="PRIMARY_NAME",
    native_wkid=4269,
    out_fields=(
        "OBJECTID",
        "REGISTRY_ID",
        "PRIMARY_NAME",
        "CITY_NAME",
        "COUNTY_NAME",
        "STATE_CODE",
        "LATITUDE83",
        "LONGITUDE83",
        "PGM_SYS_ID",
        "PGM_SYS_ACRNM",
        "INTEREST_TYPE",
        "ACTIVE_STATUS",
        "FED_FACILITY_CODE",
        "UPDATE_DATE",
        "FAC_URL",
    ),
)

# EPA's Superfund Redevelopment Program map of sites in reuse; points keyed by the numeric SEMS site id.
REUSE_POINTS = LayerSpec(
    key="sites_in_reuse",
    label="EPA Superfund Sites in Reuse (map points)",
    url=f"{ARCGIS_ROOT}/Superfund_Sites_In_Reuse/FeatureServer",
    oid_field="FID",
    epa_id_field="Site_ID",
    name_field="Site_Name",
    native_wkid=4326,
    out_fields=("FID", "Site_ID", "Site_Name", "City", "State", "Snapshot"),
)

# Published coded-value domains (labels stripped of the source's trailing spaces).
NPL_STATUS_CODE_LABELS = {
    "A": "Site is Part of NPL Site",
    "D": "Deleted from the Final NPL",
    "F": "Currently on the Final NPL",
    "N": "Not on the NPL",
    "O": "Not Valid Site or Incident",
    "P": "Proposed for NPL",
    "R": "Removed from Proposed",
    "S": "Pre-proposal Site",
    "W": "Withdrawn",
}
FEDERAL_FACILITY_LABELS = {"Y": "Federal Facility", "N": "Not a Federal Facility", "D": "Status Undetermined"}
# The total-site domain omits classes that occur in the data (3, 51, 52).
SITE_FEATURE_CLASS_LABELS = {
    0: "Continued Use/Reuse",
    2: "Extent of Contamination",
    4: "Operable Unit",
    5: "Site Boundary",
}
EPA_PROGRAM_DOMAIN = frozenset(
    {
        "Superfund Remedial",
        "Superfund Removal",
        "Superfund Emergency Response",
        "Superfund Site Assessment",
        "RCRA Corrective Action",
    }
)

# Normalized listing-status vocabulary. Raw source values are always retained.
NPL_STATUS_VALUES = (
    "final",
    "proposed",
    "deleted",
    "part_of_npl_site",
    "not_on_npl",
    "removed_from_proposed",
    "pre_proposal",
    "withdrawn",
    "not_valid_site",
)
CODE_STATUS = {
    "F": "final",
    "P": "proposed",
    "D": "deleted",
    "A": "part_of_npl_site",
    "N": "not_on_npl",
    "R": "removed_from_proposed",
    "S": "pre_proposal",
    "W": "withdrawn",
    "O": "not_valid_site",
}
POINT_STATUS_TEXT = {"npl site": "final", "proposed npl site": "proposed", "deleted npl site": "deleted"}
FRS_STATUS_TEXT = {
    "currently on the final npl": "final",
    "proposed for npl": "proposed",
    "deleted from the final npl": "deleted",
    "site is part of npl site": "part_of_npl_site",
    "not on the npl": "not_on_npl",
    "removed from proposed npl": "removed_from_proposed",
    "withdrawn from the final npl": "withdrawn",
}

# The point layer stores full state names; the other sources use postal codes.
STATE_NAMES = {
    "AL": "Alabama",
    "AK": "Alaska",
    "AS": "American Samoa",
    "AZ": "Arizona",
    "AR": "Arkansas",
    "CA": "California",
    "CO": "Colorado",
    "CT": "Connecticut",
    "DE": "Delaware",
    "DC": "District of Columbia",
    "FM": "Federated States of Micronesia",
    "FL": "Florida",
    "GA": "Georgia",
    "GU": "Guam",
    "HI": "Hawaii",
    "ID": "Idaho",
    "IL": "Illinois",
    "IN": "Indiana",
    "IA": "Iowa",
    "KS": "Kansas",
    "KY": "Kentucky",
    "LA": "Louisiana",
    "ME": "Maine",
    "MD": "Maryland",
    "MA": "Massachusetts",
    "MI": "Michigan",
    "MN": "Minnesota",
    "MS": "Mississippi",
    "MO": "Missouri",
    "MT": "Montana",
    "NE": "Nebraska",
    "NV": "Nevada",
    "NH": "New Hampshire",
    "NJ": "New Jersey",
    "NM": "New Mexico",
    "NY": "New York",
    "NC": "North Carolina",
    "ND": "North Dakota",
    "MP": "Commonwealth of Northern Marianas",
    "OH": "Ohio",
    "OK": "Oklahoma",
    "OR": "Oregon",
    "PA": "Pennsylvania",
    "PR": "Puerto Rico",
    "RI": "Rhode Island",
    "SC": "South Carolina",
    "SD": "South Dakota",
    "TN": "Tennessee",
    "TX": "Texas",
    "UT": "Utah",
    "VT": "Vermont",
    "VI": "Virgin Islands",
    "VA": "Virginia",
    "WA": "Washington",
    "WV": "West Virginia",
    "WI": "Wisconsin",
    "WY": "Wyoming",
    "MH": "Marshall Islands",
    "PW": "Palau",
    "UM": "U.S. Minor Outlying Islands",
}
STATE_CODES_BY_NAME = {name.casefold(): code for code, name in STATE_NAMES.items()}

# =============================================================================
# ENVIROFACTS DMAP (SEMS TABLES)
# =============================================================================

DMAP_BASE = "https://data.epa.gov/efservice"
DMAP_SITE_TABLE = "sems.envirofacts_site"
DMAP_CONTAMINANTS_TABLE = "sems.envirofacts_contaminants"
DMAP_SITE_FIELDS = (
    "site_id",
    "epa_id",
    "name",
    "archived_ind",
    "archived_date",
    "city_name",
    "county_name",
    "fk_ref_state_code",
    "fk_ref_region_code",
    "federal_facility_ind",
    "npl_status_code",
    "npl_status_name",
    "non_npl_status_code",
    "non_npl_status_name",
    "non_npl_status_date",
    "saa_agreement_site_ind",
    "primary_latitude_decimal_val",
    "primary_longitude_decimal_val",
)
DMAP_CONTAMINANT_FIELDS = (
    "fk_site_id",
    "preferred_contaminant_name",
    "media_name",
    "operable_unit_num",
    "action_name",
    "type_code",
    "seq",
)
# DMAP's path grammar rejects these characters even when percent-encoded; the
# `like` operator's `@` wildcard stands in for them.
DMAP_UNSAFE_CHARACTERS = frozenset("'&+/")
DMAP_SEARCH_ROWS = 500
DMAP_CONTAMINANT_ROWS = 5000
CONTAMINANT_UNAVAILABLE_FIELDS = (
    "CAS number",
    "concentration",
    "sampling date",
    "decision-document accession",
    "row update date",
)

# =============================================================================
# FEDERAL REGISTER AND ACCESS POLICY
# =============================================================================

# The Federal Register API documents automated use (the cfr server uses it too).
FEDERAL_REGISTER_URL = "https://www.federalregister.gov/api/v1/documents.json"
FEDERAL_REGISTER_FIELDS = (
    "title",
    "action",
    "type",
    "abstract",
    "publication_date",
    "comments_close_on",
    "document_number",
    "docket_ids",
    "html_url",
)
FEDERAL_REGISTER_MAX_RESULTS = 50
# Every request identifies this client; repeated identical reads within one research session are served
# from a short in-process cache so a site dossier does not re-fetch the same records.
HEADERS = {"User-Agent": "nepa-mcp-epa-superfund/1.0 (+https://github.com/pnnl/nepa-mcp)"}
CACHE_SECONDS = 600

# EPA's site-profile host (cumulis.epa.gov) publishes `User-agent: *` / `Disallow: /`, and www.epa.gov
# disallows its notice and news-release search pages. This server never fetches them; it only links to
# official pages for a person to open.
NOT_RETRIEVED_NOTE = (
    "EPA's detailed site-profile pages (cleanup schedules, profile operable units, document collections, "
    "participation notices) are not retrieved because EPA's robots.txt disallows automated access; open the "
    "site's EPA profile link in a browser."
)


# =============================================================================
# LIMITS AND TIME BUDGET
# =============================================================================

MAX_PAGE_SIZE = 100
MAX_RESULT_OFFSET = 9999
# National totals are ~1,840 points and ~2,100 boundary features; FRS has ~14,000 points.
# Select IDs first, then fetch bounded batches under the tool budget.
ARCGIS_ID_BATCH_SIZE = 500
ROI_MAX_FEATURES = 4_000
LOOKUP_MAX_FEATURES = 2_000
SEARCH_MAX_FEATURES = 2_000
TOOL_TIMEOUT_SECONDS = 90.0
ARCGIS_TIMEOUT_SECONDS = 12
ARCGIS_MAX_ATTEMPTS = 2
# A short connect timeout lets requests fall back from an unreachable IPv6 address quickly.
CONNECT_TIMEOUT_SECONDS = 5
DMAP_TIMEOUT_SECONDS = 20
FEDERAL_REGISTER_TIMEOUT_SECONDS = 15
BUDGET_SECONDS = 80.0


class Budget:
    """Wall-clock budget that keeps a multi-source tool call under its MCP timeout."""

    def __init__(self, seconds: float = BUDGET_SECONDS):
        self._deadline = time.monotonic() + seconds

    def remaining(self) -> float:
        return self._deadline - time.monotonic()

    def allows(self, request_seconds: float) -> bool:
        return self.remaining() >= request_seconds + 1

    def timeout(self, nominal: float, requests: int = 1) -> float:
        """Per-request timeout that cannot outlast the budget across ``requests`` sequential attempts."""
        return max(1.0, min(nominal, (self.remaining() - 1) / requests))
