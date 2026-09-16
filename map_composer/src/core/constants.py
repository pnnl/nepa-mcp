"""
Shared constants for NEPA environmental analysis.

This module provides centralized constants used across multiple modules
to ensure consistency and eliminate duplication.
"""

# =============================================================================
# UNIT CONVERSIONS
# =============================================================================

# Square meters to square miles conversion factor
SQ_METERS_TO_SQ_MILES = 2589988.11


# =============================================================================
# CENSUS TIGERWEB SERVICES
# =============================================================================

# American Indian/Alaska Native/Native Hawaiian Areas (AIANNHA) service
TIGERWEB_AIANNHA_URL = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/AIANNHA/MapServer"

# Tribal land layer IDs and names
# Layer IDs map to specific tribal land categories in the AIANNHA service
TRIBAL_LAYERS = {
    0: "Alaska Native Regional Corporations",
    1: "Tribal Subdivisions",
    2: "Federal American Indian Reservations",
    3: "Off-Reservation Trust Lands",
    4: "State American Indian Reservations",
    5: "Hawaiian Home Lands",
}


# =============================================================================
# BLM NATIONAL LANDSCAPE CONSERVATION SYSTEM (NLCS) SERVICES
# =============================================================================

# BLM Land Use Plans (Approved) - for conformance checks per 43 CFR 1610.5
BLM_LAND_USE_PLANS_URL = "https://services1.arcgis.com/KbxwQRRfWyEYLgp4/arcgis/rest/services/BLM_Natl_Land_Use_Plans_Approved_2022/FeatureServer"
BLM_LAND_USE_PLANS_LAYER_ID = 1

# BLM Wilderness Areas - designated wilderness under the Wilderness Act
BLM_WILDERNESS_AREAS_URL = "https://services1.arcgis.com/KbxwQRRfWyEYLgp4/arcgis/rest/services/BLM_Natl_NLCS_Wilderness_Areas_Polygons/FeatureServer"
BLM_WILDERNESS_AREAS_LAYER_ID = 2

# BLM National Monuments and National Conservation Areas
BLM_NATIONAL_MONUMENTS_URL = "https://services1.arcgis.com/KbxwQRRfWyEYLgp4/arcgis/rest/services/BLM_Natl_NLCS_National_Monuments_National_Conservation_Areas_Polygons/FeatureServer"
BLM_NATIONAL_MONUMENTS_LAYER_ID = 0

# BLM Managed Lands via PAD-US 4.1 (national coverage, filtered to BLM management)
# Source: USGS Gap Analysis Project Protected Areas Database
BLM_MANAGED_LANDS_URL = "https://edits.nationalmap.gov/arcgis/rest/services/PAD-US/PAD_US_4_1/MapServer"
BLM_MANAGED_LANDS_LAYER_ID = 0  # PADUS4_1Fee layer

# PAD-US 4.1 - Used by both blm_managed_lands and federal_lands layers
PADUS_URL = BLM_MANAGED_LANDS_URL
PADUS_LAYER_ID = BLM_MANAGED_LANDS_LAYER_ID

# BLM Land Use Plans - Revision/Development (plans in progress)
BLM_PLANS_IN_PROGRESS_URL = "https://services1.arcgis.com/KbxwQRRfWyEYLgp4/arcgis/rest/services/BLM_Natl_Revision_Development_Land_Use_Plans/FeatureServer"
BLM_PLANS_IN_PROGRESS_LAYER_ID = 0

# BLM Wilderness Study Areas (NLCS)
BLM_WSA_URL = (
    "https://services1.arcgis.com/KbxwQRRfWyEYLgp4/arcgis/rest/services/"
    "BLM_Natl_NLCS_Wilderness_Study_Areas_Polygons/FeatureServer"
)
BLM_WSA_LAYER_ID = 3

# BLM Rights of Way - NSO Restriction Areas
BLM_ROW_URL = "https://services1.arcgis.com/KbxwQRRfWyEYLgp4/arcgis/rest/services/Rights_of_Way/FeatureServer"
BLM_ROW_NSO_LAYER_ID = 1


# =============================================================================
# =============================================================================
# USFS (U.S. FOREST SERVICE) SERVICES
# =============================================================================

# USFS National Forest System Boundaries
USFS_FORESTS_URL = "https://apps.fs.usda.gov/arcx/rest/services/EDW/EDW_ForestSystemBoundaries_01/MapServer"
USFS_FORESTS_LAYER_ID = 0

# USFS Inventoried Roadless Areas (2001 Roadless Rule, 36 CFR 294)
USFS_ROADLESS_AREAS_URL = (
    "https://apps.fs.usda.gov/arcx/rest/services/EDW/EDW_InventoriedRoadlessAreas2001_01/MapServer"
)
USFS_ROADLESS_AREAS_LAYER_ID = 0


# =============================================================================
# NPS PARK BOUNDARIES
# =============================================================================

# National Park Service Land Resources Division Boundary and Tract Data
NPS_BOUNDARIES_URL = "https://services1.arcgis.com/fBc8EJBxQRMcHlei/arcgis/rest/services/NPS_Land_Resources_Division_Boundary_and_Tract_Data_Service/FeatureServer"
NPS_BOUNDARIES_LAYER_ID = 2


# =============================================================================
# BLM SPECIES/HABITAT AND CONTEXTUAL SERVICES
# =============================================================================

# Greater Sage-Grouse Habitat Management Areas (Feb 2026 ROD)
GRSG_HABITAT_URL = "https://services1.arcgis.com/KbxwQRRfWyEYLgp4/arcgis/rest/services/BLM_Natl_WesternUS_GRSG_ROD_HabitatMgmtAreas_Feb_2026/FeatureServer"
GRSG_HABITAT_LAYER_ID = 0

# Sagebrush Focal Areas v2 (most restricted sage-grouse habitat)
SAGEBRUSH_FOCAL_URL = "https://services1.arcgis.com/KbxwQRRfWyEYLgp4/arcgis/rest/services/BLM_Natl_WesternUS_GRSG_Sagebrush_Focal_Areas_v2/FeatureServer"
SAGEBRUSH_FOCAL_LAYER_ID = 0

# Wild Horse and Burro Herd Management Areas
WILD_HORSE_HMA_URL = "https://services1.arcgis.com/KbxwQRRfWyEYLgp4/arcgis/rest/services/BLM_Natl_Wild_Horse_and_Burro_Heard_Mgmt_Area_Polygons/FeatureServer"
WILD_HORSE_HMA_LAYER_ID = 0

# National Scenic and Historic Trails
NATIONAL_TRAILS_URL = "https://services1.arcgis.com/KbxwQRRfWyEYLgp4/arcgis/rest/services/National_Scenic_and_Historic_Trails_NSHT/FeatureServer"
NATIONAL_TRAILS_LAYER_ID = 0

# NIFC authoritative interagency fire-perimeter history (all years)
FIRE_PERIMETERS_URL = (
    "https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/"
    "InterAgencyFirePerimeterHistory_All_Years_View/FeatureServer"
)
FIRE_PERIMETERS_LAYER_ID = 0

# Land and Water Conservation Fund acquisitions
LWCF_URL = "https://services1.arcgis.com/KbxwQRRfWyEYLgp4/arcgis/rest/services/BLM_Natl_Land_and_Water_Conservation_Fund_LWCF_Polygons/FeatureServer"
LWCF_LAYER_ID = 2

# Western US EIS Boundaries
EIS_BOUNDARIES_URL = (
    "https://services1.arcgis.com/KbxwQRRfWyEYLgp4/arcgis/rest/services/BLM_Natl_WesternUS_EIS_Boundaries/FeatureServer"
)
EIS_BOUNDARIES_LAYER_ID = 1
