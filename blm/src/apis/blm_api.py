"""
BLM (Bureau of Land Management) data discovery utilities.

This module provides access to BLM geospatial data for NEPA analysis:
- Land Use Plans (approved RMPs/MFPs) for conformance checks per 43 CFR 1610.5
- Wilderness Areas for special designations screening
- National Monuments and NCAs for land use restrictions
"""

from __future__ import annotations

import logging
from typing import Dict, List

from nepa_mcp_common.arcgis import ArcGISService
from nepa_mcp_common.land_status import designation_details
from src.core.constants import (
    BLM_LAND_USE_PLANS_URL,
    BLM_LAND_USE_PLANS_LAYER_ID,
    BLM_WILDERNESS_AREAS_URL,
    BLM_WILDERNESS_AREAS_LAYER_ID,
    BLM_NATIONAL_MONUMENTS_URL,
    BLM_NATIONAL_MONUMENTS_LAYER_ID,
    SQ_METERS_TO_SQ_MILES,
)

logger = logging.getLogger(__name__)


# =============================================================================
# LAND USE PLANS
# =============================================================================


def get_blm_land_use_plans_in_roi(lat: float, lon: float, buffer_miles: float = 25.0) -> Dict:
    """
    Return BLM approved land use plans intersecting the ROI.

    Args:
        lat: Latitude in decimal degrees (WGS84).
        lon: Longitude in decimal degrees (WGS84).
        buffer_miles: Buffer radius in miles (default 25).

    Returns:
        Dictionary with land use plans and metadata.
    """
    buffer_geom = ArcGISService.create_roi_buffer(lat, lon, buffer_miles)
    plans, warnings = _query_blm_land_use_plans(buffer_geom)

    return {
        "center": {"latitude": lat, "longitude": lon},
        "buffer_miles": buffer_miles,
        "total": len(plans),
        "land_use_plans": plans,
        "warnings": warnings,
    }


def _query_blm_land_use_plans(buffer_geometry: Dict) -> tuple[List[Dict], List[str]]:
    """
    Query BLM land use plans that intersect with the ROI buffer.

    Args:
        buffer_geometry: ESRI JSON polygon geometry (ROI buffer)

    Returns:
        List of land use plans, sorted by plan name.
    """
    plans = []
    try:
        result = ArcGISService.query_features(
            BLM_LAND_USE_PLANS_URL,
            BLM_LAND_USE_PLANS_LAYER_ID,
            buffer_geometry,
            out_fields="LUPName,Status,RODdate,RODyear,AdminSt,NEPAnum,ePLink,Shape__Area",
            timeout=30,
            service_name="BLM land use plans",
        )

        for feature in result.features:
            attrs = feature.get("attributes", {})

            area = attrs.get("Shape__Area")
            try:
                area_sq_mi = float(area) / SQ_METERS_TO_SQ_MILES if area else None
            except (TypeError, ValueError):
                area_sq_mi = None

            plans.append(
                {
                    "plan_name": attrs.get("LUPName", "Unknown"),
                    "status": attrs.get("Status", ""),
                    "rod_date": attrs.get("RODdate", ""),
                    "rod_year": attrs.get("RODyear"),
                    "admin_state": attrs.get("AdminSt", ""),
                    "nepa_number": attrs.get("NEPAnum", ""),
                    "plan_link": attrs.get("ePLink", ""),
                    "area_sq_mi": round(area_sq_mi, 2) if area_sq_mi else None,
                }
            )

    except Exception as e:
        warning = f"BLM land use plans query failed: {e}"
        logger.warning(warning)
        return [], [warning]

    return sorted(plans, key=lambda x: x["plan_name"]), result.warnings


def format_blm_land_use_plans_summary(data: Dict) -> str:
    """
    Format land use plans data as a markdown summary.

    Args:
        data: Data from get_blm_land_use_plans_in_roi()

    Returns:
        Formatted markdown string
    """
    center = data.get("center", {})
    lat = center.get("latitude", 0)
    lon = center.get("longitude", 0)
    buffer_miles = data.get("buffer_miles", 0)
    plans = data.get("land_use_plans", [])

    lines = [
        "BLM Land Use Plans within ROI",
        "",
        f"Location: ({lat}, {lon})",
        f"Buffer: {buffer_miles} miles",
        f"Total Plans: {data.get('total', 0)}",
        "",
    ]

    if plans:
        for plan in plans:
            size = f"{plan['area_sq_mi']:.2f} sq mi" if plan.get("area_sq_mi") else "Area N/A"
            rod_info = f"ROD {plan['rod_year']}" if plan.get("rod_year") else "ROD date N/A"
            lines.append(f"- {plan['plan_name']} ({plan['admin_state']})")
            lines.append(f"  Status: {plan['status']} | {rod_info} | {size}")
            if plan.get("plan_link"):
                lines.append(f"  ePlanning: {plan['plan_link']}")
            lines.append("")
    else:
        lines.append("No BLM land use plans found in the ROI.")
        lines.append("")

    for warning in data.get("warnings", []):
        lines.extend([f"Warning: {warning}", ""])

    lines.append("NEPA Compliance: Review applicable land use plan decisions for conformance per 43 CFR 1610.5.")
    lines.append("A proposed action must conform to applicable land use plans or consider a plan amendment.")

    return "\n".join(lines)


# =============================================================================
# WILDERNESS AREAS
# =============================================================================


def get_blm_wilderness_areas_in_roi(lat: float, lon: float, buffer_miles: float = 25.0) -> Dict:
    """
    Return BLM designated wilderness areas intersecting the ROI.

    Args:
        lat: Latitude in decimal degrees (WGS84).
        lon: Longitude in decimal degrees (WGS84).
        buffer_miles: Buffer radius in miles (default 25).

    Returns:
        Dictionary with wilderness areas and metadata.
    """
    buffer_geom = ArcGISService.create_roi_buffer(lat, lon, buffer_miles)
    wilderness, warnings = _query_blm_wilderness_areas(buffer_geom)

    return {
        "center": {"latitude": lat, "longitude": lon},
        "buffer_miles": buffer_miles,
        "total": len(wilderness),
        "wilderness_areas": wilderness,
        "warnings": warnings,
    }


def _query_blm_wilderness_areas(buffer_geometry: Dict) -> tuple[List[Dict], List[str]]:
    """
    Query BLM wilderness areas that intersect with the ROI buffer.

    Args:
        buffer_geometry: ESRI JSON polygon geometry (ROI buffer)

    Returns:
        List of wilderness areas, sorted by name.
    """
    wilderness = []
    try:
        result = ArcGISService.query_features(
            BLM_WILDERNESS_AREAS_URL,
            BLM_WILDERNESS_AREAS_LAYER_ID,
            buffer_geometry,
            out_fields="NLCS_NAME,NLCS_ID,ADMIN_ST,DESIG_DATE,CASEFILE_NO,Shape__Area",
            timeout=30,
            service_name="BLM wilderness areas",
        )

        for feature in result.features:
            attrs = feature.get("attributes", {})

            area = attrs.get("Shape__Area")
            try:
                area_sq_mi = float(area) / SQ_METERS_TO_SQ_MILES if area else None
            except (TypeError, ValueError):
                area_sq_mi = None

            # Handle designation date (milliseconds since epoch)
            desig_date = attrs.get("DESIG_DATE")
            desig_date_str = None
            if desig_date:
                try:
                    from datetime import datetime

                    desig_date_str = datetime.fromtimestamp(desig_date / 1000).strftime("%Y-%m-%d")
                except (TypeError, ValueError, OSError):
                    desig_date_str = str(desig_date)

            wilderness.append(
                {
                    "name": attrs.get("NLCS_NAME", "Unknown"),
                    "nlcs_id": attrs.get("NLCS_ID", ""),
                    "admin_state": attrs.get("ADMIN_ST", ""),
                    "designation_date": desig_date_str,
                    "casefile_number": attrs.get("CASEFILE_NO", ""),
                    "area_sq_mi": round(area_sq_mi, 2) if area_sq_mi else None,
                }
            )

    except Exception as e:
        warning = f"BLM wilderness areas query failed: {e}"
        logger.warning(warning)
        return [], [warning]

    return sorted(wilderness, key=lambda x: x["name"]), result.warnings


def format_blm_wilderness_summary(data: Dict) -> str:
    """
    Format wilderness areas data as a markdown summary.

    Args:
        data: Data from get_blm_wilderness_areas_in_roi()

    Returns:
        Formatted markdown string
    """
    center = data.get("center", {})
    lat = center.get("latitude", 0)
    lon = center.get("longitude", 0)
    buffer_miles = data.get("buffer_miles", 0)
    wilderness = data.get("wilderness_areas", [])

    lines = [
        "BLM Wilderness Areas within ROI",
        "",
        f"Location: ({lat}, {lon})",
        f"Buffer: {buffer_miles} miles",
        f"Total Wilderness Areas: {data.get('total', 0)}",
        "",
    ]

    if wilderness:
        for area in wilderness:
            size = f"{area['area_sq_mi']:.2f} sq mi" if area.get("area_sq_mi") else "Area N/A"
            desig = f"Designated {area['designation_date']}" if area.get("designation_date") else "Designation date N/A"
            lines.append(f"- {area['name']} ({area['admin_state']})")
            lines.append(f"  {desig} | {size}")
            if area.get("nlcs_id"):
                lines.append(f"  NLCS ID: {area['nlcs_id']}")
            lines.append("")
    else:
        lines.append("No BLM wilderness areas found in the ROI.")
        lines.append("")

    for warning in data.get("warnings", []):
        lines.extend([f"Warning: {warning}", ""])

    lines.append("NEPA Compliance: Wilderness areas are protected under the Wilderness Act of 1964.")
    lines.append("Activities that may impair wilderness character require additional NEPA review.")
    lines.append("Consult with BLM for permitted activities within wilderness boundaries.")

    return "\n".join(lines)


# =============================================================================
# NATIONAL MONUMENTS AND NCAs
# =============================================================================


def get_blm_national_monuments_in_roi(
    lat: float, lon: float, buffer_miles: float = 25.0, *, designation_type: str = "all"
) -> Dict:
    """
    Return BLM National Monuments and NCAs intersecting the ROI.

    Args:
        lat: Latitude in decimal degrees (WGS84).
        lon: Longitude in decimal degrees (WGS84).
        buffer_miles: Buffer radius in miles (default 25).

    Returns:
        Dictionary with monuments/NCAs and metadata.
    """
    if designation_type not in ("all", "national_conservation_area", "national_monument"):
        raise ValueError("Unsupported designation_type")
    buffer_geom = ArcGISService.create_roi_buffer(lat, lon, buffer_miles)
    monuments, warnings = _query_blm_national_monuments(buffer_geom)
    if designation_type != "all":
        unknown = sum(item["designation_type"] == "unclassified" for item in monuments)
        if unknown:
            warnings = list(warnings) + [
                f"{unknown} unclassified source records excluded; classification is incomplete."
            ]
        monuments = [item for item in monuments if item["designation_type"] == designation_type]

    return {
        "center": {"latitude": lat, "longitude": lon},
        "buffer_miles": buffer_miles,
        "total": len(monuments),
        "national_monuments": monuments,
        "designation_filter": designation_type,
        "national_conservation_areas": [
            item for item in monuments if item["designation_type"] == "national_conservation_area"
        ],
        "warnings": warnings,
    }


def _query_blm_national_monuments(buffer_geometry: Dict) -> tuple[List[Dict], List[str]]:
    """
    Query BLM National Monuments and NCAs that intersect with the ROI buffer.

    Args:
        buffer_geometry: ESRI JSON polygon geometry (ROI buffer)

    Returns:
        List of monuments/NCAs, sorted by name.
    """
    monuments = []
    try:
        result = ArcGISService.query_features(
            BLM_NATIONAL_MONUMENTS_URL,
            BLM_NATIONAL_MONUMENTS_LAYER_ID,
            buffer_geometry,
            out_fields="NCA_NAME,NLCS_ID,STATE_ADMN,STATE_GEOG,sma_code,Shape__Area",
            timeout=30,
            service_name="BLM national monuments and conservation areas",
        )

        for feature in result.features:
            attrs = feature.get("attributes", {})

            area = attrs.get("Shape__Area")
            try:
                area_sq_mi = float(area) / SQ_METERS_TO_SQ_MILES if area else None
            except (TypeError, ValueError):
                area_sq_mi = None

            monuments.append(
                {
                    "name": attrs.get("NCA_NAME", "Unknown"),
                    "nlcs_id": attrs.get("NLCS_ID", ""),
                    "admin_state": attrs.get("STATE_ADMN", ""),
                    "geographic_state": attrs.get("STATE_GEOG", ""),
                    "sma_code": attrs.get("sma_code", ""),
                    **designation_details(attrs),
                    "area_sq_mi": round(area_sq_mi, 2) if area_sq_mi else None,
                }
            )

    except Exception as e:
        warning = f"BLM national monuments query failed: {e}"
        logger.warning(warning)
        return [], [warning]

    return sorted(monuments, key=lambda x: x["name"]), result.warnings


def format_blm_monuments_summary(data: Dict) -> str:
    """
    Format national monuments/NCAs data as a markdown summary.

    Args:
        data: Data from get_blm_national_monuments_in_roi()

    Returns:
        Formatted markdown string
    """
    center = data.get("center", {})
    lat = center.get("latitude", 0)
    lon = center.get("longitude", 0)
    buffer_miles = data.get("buffer_miles", 0)
    monuments = data.get("national_monuments", [])

    lines = [
        "BLM National Monuments and NCAs within ROI",
        "",
        f"Location: ({lat}, {lon})",
        f"Buffer: {buffer_miles} miles",
        f"Total Designations: {data.get('total', 0)}",
        "",
    ]

    if monuments:
        for mon in monuments:
            size = f"{mon['area_sq_mi']:.2f} sq mi" if mon.get("area_sq_mi") else "Area N/A"
            state_info = mon.get("admin_state") or mon.get("geographic_state") or "N/A"
            lines.append(f"- {mon['name']} ({state_info})")
            lines.append(f"  Designation: {mon.get('designation_type', 'unclassified')}")
            if mon.get("classification_authority"):
                lines.append(f"  Authority: {mon['classification_authority']}")
                lines.append(f"  {mon['geothermal_leasing_rule']}")
            lines.append(f"  {size}")
            if mon.get("nlcs_id"):
                lines.append(f"  NLCS ID: {mon['nlcs_id']}")
            lines.append("")
    else:
        lines.append("No BLM National Monuments or NCAs found in the ROI.")
        lines.append("")

    for warning in data.get("warnings", []):
        lines.extend([f"Warning: {warning}", ""])

    lines.append("NEPA Compliance: National Monuments and NCAs have management restrictions.")
    lines.append("Review applicable proclamations and management plans for permitted activities.")
    lines.append("These areas may trigger BLM Extraordinary Circumstances screening.")
    lines.append("Buffer intersection does not establish footprint containment; no protective buffer is inferred.")

    return "\n".join(lines)
