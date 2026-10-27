"""Verified USACE FUDS layer contract (checked 2026-10-23)."""

BASE = "https://geospatial.sec.usace.army.mil/server/rest/services/Military/FUDS_Data/MapServer"
PROGRAM_URL = "https://www.usace.army.mil/Missions/Environmental/Formerly-Used-Defense-Sites/FUDS-GIS/"
PROPERTY_FIELDS = (
    "OBJECTID",
    "DODFUDSPROPERTYIDPK",
    "FUDSUNIQUEPROPERTYNUMBER",
    "FUDSINSTALLATIONID",
    "FEATURENAME",
    "CLOSESTCITY",
    "COUNTY",
    "STATE",
    "ELIGIBILITY",
    "STATUS",
    "STATUSCODE",
    "USACEDISTRICT",
    "USACEDIVISION",
    "FISCALYEAR",
    "EMSMGMTACTIONPLANLINK",
    "LATITUDE",
    "LONGITUDE",
)
FIELDS = {
    1: PROPERTY_FIELDS + ("HAS_PROJECTS",),
    4: PROPERTY_FIELDS + ("HASPROJECTS", "SITEELIGIBILITY", "NOFURTHERACTION", "PROJECTREQUIRED"),
    2: (
        "OBJECTID",
        "DODFUDSPROPERTYIDFK",
        "FUDSPROPERTYID",
        "FUDSINSTALLATIONID",
        "FUDSSITEID",
        "PROJECTNUMBER",
        "ENVRESTORATIONSITEIDFK",
        "ENVRESTORATIONPROJECTNAME",
        "ENVRESTORATIONCATEGORY",
        "DERPPROGRAM",
        "PROJECTSTATUS",
        "REMEDYINPLACEDATE",
        "RESPONSECOMPLETEDATE",
        "SITECLOSEOUTDATE",
        "COSTTOCOMPLETE",
        "RISKVALUEMRSPP",
        "PROJECTREFERENCEAREA",
        "PROJECTREFERENCEAREAUOM",
        "EMSMGMTACTIONPLANLINK",
    ),
    3: (
        "OBJECTID",
        "FUDSPROPERTYID",
        "FUDSSITEID",
        "FUDSINSTALLATIONID",
        "ENVIRONMENTALRESTORATIONSIIDPK",
        "ENVRESTORATIONSITEMRAIDFK",
        "PROJECTNUMBER",
        "FEATURENAME",
        "OFFICIALSITENAME",
        "DERPPROGRAM",
        "PROJECTCATEGORY",
        "PROJECTSTATUS",
        "RELATIVEPRIORITY",
        "FISCALYEAR",
        "USACEDISTRICT",
        "USACEDIVISION",
        "STATEORTERRITORYNAME",
    ),
    9: ("OBJECTID", "DIST", "MIL_DIST", "DIV", "MIL_DIV", "OFFICE", "PAO_PHONE", "WEB", "CITY", "STATE"),
}
LABELS = {
    1: "FUDS Property Points",
    2: "FUDS Project Point",
    3: "FUDS Munitions Response Site",
    4: "FUDS Property Polygon",
    9: "FUDS Program District Boundaries",
}
CAP = 2500
BATCH = 250
NOTE = "FUDS records are research leads, not findings about contamination, completed cleanup, safety, ownership, land availability, development suitability, or NEPA compliance. A FUDS eligibility label of Categorical Exclusion is not a NEPA determination. Point coverage and mapped polygon coverage differ; empty mapped results do not exclude unmapped properties or hazards."
