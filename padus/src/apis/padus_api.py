"""
PADUS (Protected Areas Database of the United States) protected-area utilities.

This module provides access to USGS PAD-US protected-area records, covering fee
ownership, designations, easements, marine, and proclamation boundaries. PAD-US is
not a cadastral ownership source and should not be treated as complete private land
ownership coverage.

API Documentation: https://www.usgs.gov/programs/gap-analysis-project/science/pad-us-data-overview
"""

from __future__ import annotations

from collections import Counter
from typing import Dict

from nepa_mcp_common.arcgis import ArcGISService

# PADUS 4.1 MapServer endpoints (National Map)
PADUS_BASE_URL = "https://edits.nationalmap.gov/arcgis/rest/services/PAD-US/PAD_US_gaz_combined/MapServer"
PADUS_COMBINED_LAYER = 0  # PADUS4_1Combined layer: Fee, Designation, Easement, Marine, Proclamation

# Retained for callers that still reference the fee-only service.
PADUS_FEE_BASE_URL = "https://edits.nationalmap.gov/arcgis/rest/services/PAD-US/PAD_US_4_1/MapServer"
PADUS_FEE_LAYER = 0  # PADUS4_1Fee layer

PADUS_OWNER_TYPE_LABELS = {
    "DESG": "Designation",
    "DIST": "Regional Agency Special District",
    "FED": "Federal",
    "JNT": "Joint",
    "LOC": "Local Government",
    "NGO": "Non-Governmental Organization",
    "PVT": "Private",
    "STAT": "State",
    "TERR": "Territorial",
    "TRIB": "American Indian Lands",
    "UNK": "Unknown",
}


def get_padus_in_roi(lat: float, lon: float, buffer_miles: float = 25.0) -> Dict:
    """
    Query PADUS protected-area records within a Region of Interest.

    Uses the PAD-US Combined layer, which carries designation records such as
    Wilderness Study Areas, National Conservation Areas, and designated Wilderness
    alongside fee ownership. Designation status carries management standards that
    fee ownership alone does not express.

    Args:
        lat: Latitude in decimal degrees (WGS84)
        lon: Longitude in decimal degrees (WGS84)
        buffer_miles: Buffer radius in miles (default 25)

    Returns:
        Dictionary containing:
        - center: Query center point
        - buffer_miles: Buffer distance
        - total_records: Number of PAD-US records found
        - records: List of protected-area ownership, management, and designation records
    """
    buffer_geom = ArcGISService.create_roi_buffer(lat, lon, buffer_miles)

    result = ArcGISService.query_features(
        PADUS_BASE_URL,
        PADUS_COMBINED_LAYER,
        buffer_geom,
        out_fields=(
            "Category,Own_Type,Own_Name,Mang_Type,Mang_Name,Des_Tp,Unit_Nm,State_Nm,GIS_Acres,GAP_Sts,IUCN_Cat,Date_Est"
        ),
        timeout=30,
        service_name="USGS PAD-US Combined layer",
    )

    records = []
    # `or []` guards against a query result whose features are null rather than
    # an empty list, so a null-features response degrades gracefully instead of
    # raising TypeError.
    for feature in result.features or []:
        attrs = feature.get("attributes", {})

        try:
            gis_acres = float(attrs.get("GIS_Acres", 0)) if attrs.get("GIS_Acres") else 0.0
        except (ValueError, TypeError):
            gis_acres = 0.0

        category = attrs.get("Category") or "Unknown"
        owner_type = attrs.get("Own_Type") or "Unknown"
        source_gis_acres = round(gis_acres, 2)
        record = {
            "category": category,
            "owner_type": owner_type,
            "owner_name": attrs.get("Own_Name") or "Unknown",
            "manager_type": attrs.get("Mang_Type", ""),
            "manager_name": attrs.get("Mang_Name", ""),
            "designation_type": attrs.get("Des_Tp", ""),
            "unit_name": attrs.get("Unit_Nm", ""),
            "state": attrs.get("State_Nm", ""),
            # Preserve the upstream feature-area attribute for callers that use
            # it, but do not present it as area within the ROI.
            "gis_acres": source_gis_acres,
            "source_gis_acres": source_gis_acres,
            "gap_status": attrs.get("GAP_Sts", ""),
            "iucn_category": attrs.get("IUCN_Cat", ""),
            "date_established": attrs.get("Date_Est", ""),
        }
        records.append(record)

    records_sorted = sorted(records, key=lambda x: (x["owner_type"], x["owner_name"], x["unit_name"]))

    return {
        "center": {"latitude": lat, "longitude": lon},
        "buffer_miles": buffer_miles,
        "total_records": len(records_sorted),
        "records": records_sorted,
        "warnings": result.warnings,
    }


def format_padus_summary(padus_data: Dict) -> str:
    """
    Format PADUS data into a human-readable summary.

    Args:
        padus_data: Dictionary returned from get_padus_in_roi()

    Returns:
        Formatted text summary
    """
    lat = padus_data["center"]["latitude"]
    lon = padus_data["center"]["longitude"]
    buffer = padus_data["buffer_miles"]
    total = padus_data["total_records"]
    records = padus_data.get("records", [])

    # Group by owner type
    by_owner_type = {}
    for record in records:
        owner_type = record["owner_type"]
        if owner_type not in by_owner_type:
            by_owner_type[owner_type] = []
        by_owner_type[owner_type].append(record)

    # Build summary text
    lines = [
        f"Location: ({lat}, {lon})",
        f"Buffer: {buffer} miles",
        f"Total PAD-US Records: {total}",
        "",
        "PAD-US Protected-Area Records by Owner Type:",
    ]

    for warning in padus_data.get("warnings", []):
        lines.extend([f"Warning: {warning}", ""])

    for owner_type in sorted(by_owner_type):
        count = len(by_owner_type[owner_type])
        record_label = "record" if count == 1 else "records"
        owner_label = PADUS_OWNER_TYPE_LABELS.get(owner_type, owner_type)
        lines.append(f"  {owner_label} ({owner_type}): {count} {record_label}")

    by_category = Counter((record.get("category") or "Unknown") for record in records)
    if by_category:
        lines.extend(["", "PAD-US Records by Category:"])
        for category in sorted(by_category):
            count = by_category[category]
            record_label = "record" if count == 1 else "records"
            lines.append(f"  {category}: {count} {record_label}")

    # Top 10 records by acreage
    if records:
        lines.extend(["", "Top 10 Largest Intersecting Source Features by Full Mapped Acreage (not clipped to ROI):"])

        records_by_size = sorted(records, key=lambda x: x["gis_acres"], reverse=True)[:10]

        for i, record in enumerate(records_by_size, 1):
            name = record["unit_name"] or record["owner_name"]
            acres = record["gis_acres"]
            owner = record["owner_type"]
            category = record.get("category") or "Unknown"
            lines.append(f"  {i}. {name} ({category}; {owner}) - {acres:,.0f} source-feature acres")

    lines.extend(
        [
            "",
            "Data Source: USGS Protected Areas Database (PAD-US) v4.1",
            "Note: PAD-US is protected-area screening data, not comprehensive cadastral land ownership.",
            "Note: Source-feature acreage is the full mapped area of each intersecting source feature and may "
            "extend beyond the ROI.",
            "Note: PAD-US Combined-layer records may overlap within and across categories; source-feature "
            "acreages are not additive and do not represent total land area within the ROI.",
        ]
    )

    return "\n".join(lines)
