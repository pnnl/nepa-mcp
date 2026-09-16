"""Cited screening interpretations shared by BLM, PAD-US, and Map Composer.

This is a bounded set of verified rules, not a national withdrawal inventory.
Source attributes remain intact; no missing feature establishes legal availability.
"""

BLM_NLCS_ROOT = "https://services1.arcgis.com/KbxwQRRfWyEYLgp4/arcgis/rest/services"
WSA_LAYER = f"{BLM_NLCS_ROOT}/BLM_Natl_NLCS_Wilderness_Study_Areas_Polygons/FeatureServer/3"
WILDERNESS_LAYER = f"{BLM_NLCS_ROOT}/BLM_Natl_NLCS_Wilderness_Areas_Polygons/FeatureServer/2"
NCA_LAYER = f"{BLM_NLCS_ROOT}/BLM_Natl_NLCS_National_Monuments_National_Conservation_Areas_Polygons/FeatureServer/0"
PADUS_DESIGNATIONS_LAYER = "https://edits.nationalmap.gov/arcgis/rest/services/PAD-US/PAD_US_gaz_combined/MapServer/0"
GEOTHERMAL_LAYER = "https://gis.blm.gov/nlsdb/rest/services/HUB/BLM_Natl_MLRS_Geothermal_Leases/FeatureServer/0"
NDAA_2023 = "https://www.govinfo.gov/content/pkg/PLAW-117publ263/html/PLAW-117publ263.htm"
NUMUNAA_STATUTE = "https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title16-section460hhhh"
WILDERNESS_LEASING_RULE = "https://www.ecfr.gov/current/title-43/section-3201.11#p-3201.11(h)"
BLM_DESIGNATION_GUIDANCE = (
    "Use BLM agency data and controlling legal records for BLM designations. PAD-US is supplementary "
    "screening data. Dataset edit dates are not feature decision dates. No GIS match is not land clearance."
)


def designation_details(attrs):
    """Classify published codes, with a cited exception for the verified null-code NCA."""
    code = attrs.get("sma_code")
    kind = {
        "BLM_NCA": "national_conservation_area",
        "BLM_NM": "national_monument",
        "BLM_MON": "national_monument",
    }.get(code, "unclassified")
    basis = "source sma_code" if kind != "unclassified" else "Source designation type not classified"
    authority = None
    # BLM's national service has a null sma_code for this unit (verified 2026-09-12).
    if attrs.get("NLCS_ID") == "NLCS000607":
        kind = "national_conservation_area"
        basis = "Verified BLM NLCS_ID and 16 USC 460hhhh; source code may be missing"
        authority = NUMUNAA_STATUTE
    return {
        "designation_type": kind,
        "classification_basis": basis,
        "classification_authority": authority,
        "geothermal_leasing_rule": (
            "Public land within Numunaa Nobe NCA is withdrawn from geothermal leasing, subject to valid "
            "existing rights (16 USC 460hhhh(6)); paragraph (9) creates no buffer zone."
            if authority
            else "Not evaluated; review the designation's statute and applicable management plan"
        ),
    }


def padus_conflict(attrs):
    """Flag only the three specifically documented BLM WSA conflicts, never infer from absence."""
    if attrs.get("Mang_Name") != "BLM" or attrs.get("Des_Tp") != "WSA":
        return {}
    name = str(attrs.get("Unit_Nm") or "").strip().casefold()
    known = {
        "clan alpine mountains wilderness study area": (
            "128,362 acres designated Clan Alpine Mountains Wilderness; remaining former WSA lands released "
            "from WSA management. The former WSA polygon does not define the new Wilderness boundary."
        ),
        "stillwater range wilderness study area": "Released from WSA management; other restrictions may apply.",
        "job peak wilderness study area": "Released from WSA management; other restrictions may apply.",
    }
    if name not in known:
        return {}
    return {
        "designation_conflict": "Conflicting or potentially outdated screening record",
        "conflict_explanation": known[name],
        "conflict_authority": NDAA_2023,
        "conflict_provisions": "Pub. L. 117-263 sections 2905(b) and 2906",
        "agency_designation_source": WSA_LAYER,
        "conflict_verified_on": "2026-09-12",
    }
