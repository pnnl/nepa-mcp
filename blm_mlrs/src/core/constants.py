"""Verified public BLM MLRS/NLSDB ArcGIS service definitions."""

from __future__ import annotations

BLM_NLSDB_ROOT = "https://gis.blm.gov/nlsdb/rest/services"
BLM_MLRS_RESEARCH_MAP_URL = "https://mlrs.blm.gov/s/research-map"
BLM_MLRS_REPORTS_URL = "https://reports.blm.gov/reports/mlrs"

MLRS_ROW_URL = f"{BLM_NLSDB_ROOT}/HUB/BLM_Natl_MLRS_LUA_ROW/FeatureServer"
MLRS_LEASES_PERMITS_EASEMENTS_URL = f"{BLM_NLSDB_ROOT}/HUB/BLM_Natl_MLRS_LUA_Leases_Permits_Esmts/FeatureServer"
MLRS_LOCATABLE_PLANS_URL = f"{BLM_NLSDB_ROOT}/HUB/BLM_Natl_MLRS_Locatable_Plans_Of_Operations/FeatureServer"
MLRS_LOCATABLE_NOTICES_URL = f"{BLM_NLSDB_ROOT}/HUB/BLM_Natl_MLRS_Locatable_Notices/FeatureServer"
MLRS_GEOTHERMAL_LEASES_URL = f"{BLM_NLSDB_ROOT}/HUB/BLM_Natl_MLRS_Geothermal_Leases/FeatureServer"
MLRS_OIL_GAS_LEASES_URL = f"{BLM_NLSDB_ROOT}/HUB/BLM_Natl_MLRS_Oil_and_Gas_Leases/FeatureServer"

HUB_LAYER_ID = 0

COMMON_CASE_FIELDS = (
    "OBJECTID",
    "CSE_NR",
    "LEG_CSE_NR",
    "BLM_PROD",
    "CSE_TYPE_NR",
    "CSE_DISP",
    "CSE_DISP_DT",
    "CMMDTY",
    "ADMIN_STATE",
    "GEO_STATE",
    "RCRD_ACRS",
    "SRC",
    "QLTY",
    "Created",
    "Modified",
)

LAND_USE_FIELDS = COMMON_CASE_FIELDS + (
    "CSE_JURIS_DESC",
    "CSE_WIDTH",
    "CSE_LGTH",
)

OPERATIONS_FIELDS = COMMON_CASE_FIELDS + (
    "EFF_DT",
    "EXP_DT",
    "PRDCNG",
    "SALE_DT",
)

ENERGY_LEASE_FIELDS = (
    "OBJECTID",
    "CSE_NR",
    "LEG_CSE_NR",
    "BLM_PROD",
    "CSE_TYPE_NR",
    "CSE_DISP",
    "CMMDTY",
    "FRMTN",
    "EFF_DT",
    "EXP_DT",
    "PRDCNG",
    "SALE_DT",
    "ADMIN_STATE",
    "GEO_STATE",
    "RCRD_ACRS",
    "SRC",
    "QLTY",
    "Created",
    "Modified",
)

AUTHORIZATION_DISPOSITIONS = ("Authorized", "Pending", "Interim", "Closed")
OPERATIONS_DISPOSITIONS = ("Authorized", "Pending")
DEFAULT_OPEN_DISPOSITIONS = ("Authorized", "Pending", "Interim")
LAND_USE_FAMILIES = ("all", "right_of_way", "lease_permit_easement")
LOCATABLE_OPERATION_FAMILIES = ("all", "plan_of_operations", "notice")
ENERGY_LEASE_FAMILIES = ("all", "geothermal", "oil_and_gas")
LAND_USE_PRODUCT_CATEGORIES = (
    "all",
    "transmission",
    "solar_wind",
    "pipeline",
    "road",
    "communications",
    "other",
)

SOURCE_CRS = "EPSG:4269 (NAD83)"
OUTPUT_CRS = "EPSG:4326 (WGS84)"

MAX_RESULTS_PER_SOURCE = 100
MAX_RESULT_OFFSET = 9_999
# One bounded retry absorbs intermittent BLM read/connect failures. The
# FastMCP deadline covers the worst multi-disposition path without permitting
# unbounded retries against the public service.
QUERY_TIMEOUT_SECONDS = 12
QUERY_MAX_ATTEMPTS = 2
TOOL_TIMEOUT_SECONDS = 150.0
