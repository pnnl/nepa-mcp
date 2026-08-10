"""
PADUS (Protected Areas Database of the United States) protected-area utilities.

This module provides access to USGS PAD-US protected area ownership and management
records. PAD-US is not a cadastral ownership source and should not be treated as
complete private land ownership coverage.

API Documentation: https://www.usgs.gov/programs/gap-analysis-project/science/pad-us-data-overview
"""

from __future__ import annotations

from typing import Dict

from nepa_mcp_common.arcgis import ArcGISService

# PADUS 4.1 MapServer endpoints (National Map)
PADUS_BASE_URL = "https://edits.nationalmap.gov/arcgis/rest/services/PAD-US/PAD_US_4_1/MapServer"
PADUS_FEE_LAYER = 0  # PADUS4_1Fee layer


def get_padus_in_roi(lat: float, lon: float, buffer_miles: float = 25.0) -> Dict:
    """
    Query PADUS protected-area ownership records within a Region of Interest.

    Args:
        lat: Latitude in decimal degrees (WGS84)
        lon: Longitude in decimal degrees (WGS84)
        buffer_miles: Buffer radius in miles (default 25)

    Returns:
        Dictionary containing:
        - center: Query center point
        - buffer_miles: Buffer distance
        - total_records: Number of PAD-US records found
        - records: List of protected-area ownership/management records
    """
    buffer_geom = ArcGISService.create_roi_buffer(lat, lon, buffer_miles)

    result = ArcGISService.query_features(
        PADUS_BASE_URL,
        PADUS_FEE_LAYER,
        buffer_geom,
        out_fields="Own_Type,Own_Name,Mang_Type,Mang_Name,Des_Tp,Unit_Nm,State_Nm,GIS_Acres,GAP_Sts,IUCN_Cat,Date_Est",
        timeout=30,
        service_name="USGS PAD-US Fee layer",
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

        record = {
            "owner_type": attrs.get("Own_Type", "Unknown"),
            "owner_name": attrs.get("Own_Name", "Unknown"),
            "manager_type": attrs.get("Mang_Type", ""),
            "manager_name": attrs.get("Mang_Name", ""),
            "designation_type": attrs.get("Des_Tp", ""),
            "unit_name": attrs.get("Unit_Nm", ""),
            "state": attrs.get("State_Nm", ""),
            "gis_acres": round(gis_acres, 2),
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

    # Calculate total acreage by owner type
    acreage_summary = {}
    for owner_type, owner_records in by_owner_type.items():
        total_acres = sum(p["gis_acres"] for p in owner_records)
        acreage_summary[owner_type] = {"count": len(owner_records), "acres": round(total_acres, 2)}

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

    for owner_type in sorted(acreage_summary.keys()):
        count = acreage_summary[owner_type]["count"]
        acres = acreage_summary[owner_type]["acres"]
        lines.append(f"  {owner_type}: {count} records, {acres:,.0f} acres")

    # Top 10 records by acreage
    if records:
        lines.extend(["", "Top 10 Largest Records by Mapped Acres:"])

        records_by_size = sorted(records, key=lambda x: x["gis_acres"], reverse=True)[:10]

        for i, record in enumerate(records_by_size, 1):
            name = record["unit_name"] or record["owner_name"]
            acres = record["gis_acres"]
            owner = record["owner_type"]
            lines.append(f"  {i}. {name} ({owner}) - {acres:,.0f} acres")

    lines.extend(
        [
            "",
            "Data Source: USGS Protected Areas Database (PAD-US) v4.1",
            "Note: PAD-US is protected-area screening data, not comprehensive cadastral land ownership.",
        ]
    )

    return "\n".join(lines)
