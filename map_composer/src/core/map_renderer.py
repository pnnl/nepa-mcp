"""
Map Renderer - Create interactive HTML maps with folium

Generates multi-layer environmental maps with toggleable layer controls,
custom styling, popups, and source attribution.
"""

import copy
import json
import logging
import os
from datetime import datetime, timezone
from html import escape as _html_escape
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse

import folium
from shapely.geometry import mapping, shape

logger = logging.getLogger(__name__)


class _SafeHtml(str):
    """Marker for renderer-generated HTML that has already been escaped."""


def _safe_link(value: Any, label: str) -> _SafeHtml:
    """Render an HTTP(S) link while rejecting executable or malformed schemes."""

    url = str(value).strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return _SafeHtml(_html_escape(url))
    safe_url = _html_escape(url, quote=True)
    safe_label = _html_escape(label)
    return _SafeHtml(f"<a href='{safe_url}' target='_blank' rel='noopener noreferrer'>{safe_label}</a>")


# =============================================================================
# LAYER CONFIGURATION
# =============================================================================
# Centralized configuration for layer styling, display, and popup fields

LAYER_CONFIG = {
    "roi": {
        "name": "Region of Interest",
        "description": "Project location and buffer boundary",
        "color": "#C41E3A",  # Darker red (authoritative)
        "popup_fields": [
            ("Type", "type"),
            ("Buffer", "buffer_miles", lambda v: f"{v} miles" if v else None),
            ("Coordinates", ("center_lat", "center_lon"), lambda lat, lon: f"{lat}, {lon}" if lat and lon else None),
        ],
    },
    "tribal_lands": {
        "name": "Tribal Lands",
        "description": "Indigenous territories and reservations",
        "color": "#5B4636",  # Muted brown (respectful)
        "popup_fields": [
            ("Name", "name"),
            ("Type", "type"),
            ("Area", "area_sq_mi", lambda v: f"{v} sq mi" if v else None),
            ("GEOID", "geoid"),
        ],
    },
    "counties": {
        "name": "Counties",
        "description": "County boundaries and jurisdictions",
        "color": "#003366",  # Navy blue (government standard)
        "popup_fields": [
            ("County", "name"),
            ("State FIPS", "state"),
            ("County FIPS", "fips"),
        ],
        "species_popup": True,  # Special handling for species data
    },
    "critical_habitat": {
        "name": "Critical Habitat",
        "description": "Federally protected species habitat",
        "color": "#16A34A",  # Medium green (protected areas)
        "popup_fields": [
            ("Common Name", "common_name"),
            ("Scientific Name", "scientific_name"),
            ("Status", "status"),
        ],
    },
    "wildlife_refuges": {
        "name": "Wildlife Refuges",
        "description": "National Wildlife Refuge System boundaries",
        "color": "#065F46",  # Dark green (conservation)
        "popup_fields": [
            ("Name", "name"),
            ("Type", "type"),
            ("FWS Region", "fws_region"),
        ],
    },
    "usace_districts": {
        "name": "USACE Districts",
        "description": "Army Corps of Engineers regulatory boundaries",
        "color": "#6B21A8",  # Purple (federal regulatory)
        "popup_fields": [
            ("District", "name"),
            ("Abbreviation", "abbreviation"),
            ("Division", "division_name"),
            ("Division Abbr", "division_abbreviation"),
            ("Phone", "phone"),
            ("Address", "address"),
            ("Website", "website_url", lambda v: _safe_link(v, "District Website") if v else None),
        ],
    },
    "wetland_regions": {
        "name": "Wetland Regions",
        "description": "Regional supplement delineation areas",
        "color": "#059669",  # Emerald green (wetlands)
        "popup_fields": [
            ("Region", "name"),
            ("MLRA", "mlra_name"),
            ("LRR", "lrr_name"),
            ("Document", "supplement_url", lambda v: _safe_link(v, "Regional Supplement") if v else None),
        ],
    },
    "wetland_subregions": {
        "name": "Wetland Subregions",
        "description": "Sub-regional wetland classifications",
        "color": "#10B981",  # Lighter green (subregions)
        "popup_fields": [
            ("Subregion", "name"),
            ("Code", "subregion_code"),
            ("Parent Region", "parent_region"),
        ],
    },
    "nhd_lakes": {
        "name": "Lakes & Ponds",
        "description": "Perennial lakes and ponds (NHD)",
        "color": "#0369A1",  # Deep blue
        "popup_fields": [
            ("Name", "name"),
            ("Type", None, lambda: "Lake/Pond"),
            ("Area", "area_acres", lambda v: f"{v:,.1f} acres" if v else None),
            ("Elevation", "elevation", lambda v: f"{v} ft" if v else None),
            ("FCODE", "fcode"),
        ],
    },
    "nhd_reservoirs": {
        "name": "Reservoirs",
        "description": "Managed water storage (NHD)",
        "color": "#075985",  # Darker blue
        "popup_fields": [
            ("Name", "name"),
            ("Type", None, lambda: "Reservoir"),
            ("Area", "area_acres", lambda v: f"{v:,.1f} acres" if v else None),
            ("Elevation", "elevation", lambda v: f"{v} ft" if v else None),
            ("FCODE", "fcode"),
        ],
    },
    "nhd_estuaries": {
        "name": "Estuaries",
        "description": "Tidal water bodies (NHD)",
        "color": "#0E7490",  # Cyan-blue
        "popup_fields": [
            ("Name", "name"),
            ("Type", None, lambda: "Estuary"),
            ("Area", "area_acres", lambda v: f"{v:,.1f} acres" if v else None),
            ("Elevation", "elevation", lambda v: f"{v} ft" if v else None),
        ],
    },
    "nhd_ice_masses": {
        "name": "Glaciers & Ice",
        "description": "Permanent ice masses (NHD)",
        "color": "#DBEAFE",  # Light blue
        "popup_fields": [
            ("Name", "name"),
            ("Type", None, lambda: "Ice Mass/Glacier"),
            ("Area", "area_acres", lambda v: f"{v:,.1f} acres" if v else None),
            ("Elevation", "elevation", lambda v: f"{v} ft" if v else None),
        ],
    },
    "nhd_perennial_streams": {
        "name": "Perennial Streams",
        "description": "Year-round stream centerlines (NHD)",
        "color": "#38BDF8",  # Bright light blue
        "popup_fields": [
            ("Name", "name"),
            ("Type", None, lambda: "Perennial Stream"),
            ("Length", "length_miles", lambda v: f"{v:,.2f} miles" if v else None),
            ("Flow Direction", "flow_direction"),
            ("Reach Code", "reach_code"),
        ],
    },
    "nhd_stream_areas": {
        "name": "Stream Areas",
        "description": "Perennial river/stream polygons (NHD)",
        "color": "#0EA5E9",  # Medium blue
        "popup_fields": [
            ("Name", "name"),
            ("Type", None, lambda: "River/Stream Area"),
            ("Area", "area_acres", lambda v: f"{v:,.1f} acres" if v else None),
            ("FCODE", "fcode"),
        ],
    },
    "nhd_infrastructure": {
        "name": "Water Infrastructure",
        "description": "Dams, springs, gages, wells, intakes (NHD)",
        "color": "#DC2626",  # Red
        "popup_fields": [
            ("Name", "name"),
            ("Type", "infrastructure_type"),
            ("FTYPE", "ftype"),
            ("FCODE", "fcode"),
            ("Permanent ID", "permanent_id"),
        ],
    },
    "federal_lands": {
        "name": "Federal Protected Lands",
        "description": "Non-BLM federal lands (USFS, NPS, FWS, DOD) via PAD-US",
        "color": "#8B6914",  # Dark goldenrod (federal land)
        "popup_fields": [
            ("Unit Name", "name"),
            ("Owner", "owner_name"),
            ("Manager", "manager_name"),
            ("Designation", "designation_type"),
            ("State", "state"),
            ("Acres", "acres", lambda v: f"{v:,.0f} acres" if v else None),
            ("GAP Status", "gap_status"),
        ],
    },
    "usfs_forests": {
        "name": "National Forests",
        "description": "USFS National Forest System boundaries",
        "color": "#228B22",  # Forest green
        "popup_fields": [
            ("Forest Name", "name"),
            ("Region", "region"),
            ("Acres", "acres", lambda v: f"{v:,.0f} acres" if v else None),
            ("Forest ID", "forest_id"),
        ],
    },
    "usfs_roadless_areas": {
        "name": "Inventoried Roadless Areas",
        "description": "2001 Roadless Rule protected areas (36 CFR 294)",
        "color": "#2D5F2D",  # Dark forest green
        "popup_fields": [
            ("Name", "name"),
            ("Category", "category"),
            ("Acres", "acres", lambda v: f"{v:,.0f} acres" if v else None),
            ("National Forest", "forest"),
            ("State", "state"),
        ],
    },
    "nps_boundaries": {
        "name": "National Park Service",
        "description": "NPS unit boundaries (parks, monuments, historic sites)",
        "color": "#4A7C59",  # NPS arrowhead green
        "popup_fields": [
            ("Unit Name", "name"),
            ("Unit Code", "unit_code"),
            ("Unit Type", "unit_type"),
            ("State", "state"),
            ("NPS Region", "region"),
            ("GNIS ID", "gnis_id"),
        ],
    },
    "blm_managed_lands": {
        "name": "BLM Managed Lands",
        "description": "BLM-managed protected lands (PAD-US Fee; not cadastral or mineral ownership)",
        "color": "#D97706",  # Amber (federal land management)
        "popup_fields": [
            ("Unit Name", "name"),
            ("Owner", "owner_name"),
            ("Manager", "manager_name"),
            ("Designation", "designation_type"),
            ("State", "state"),
            ("Acres", "acres", lambda v: f"{v:,.0f} acres" if v else None),
            ("GAP Status", "gap_status"),
        ],
    },
    "blm_land_use_plans": {
        "name": "BLM Land Use Plans",
        "description": "Approved Resource Management Plans (RMPs)",
        "color": "#B45309",  # Dark amber (planning)
        "popup_fields": [
            ("Plan Name", "name"),
            ("Status", "status"),
            ("ROD Date", "rod_date"),
            ("ROD Year", "rod_year"),
            ("Admin State", "admin_state"),
            ("NEPA Number", "nepa_number"),
            ("Map Type", "map_type"),
            ("ePlanning", "eplan_link", lambda v: _safe_link(v, "View in ePlanning") if v else None),
        ],
    },
    "blm_plans_in_progress": {
        "name": "BLM Plans In Progress",
        "description": "Land use plans under revision or development",
        "color": "#F59E0B",  # Yellow-amber (in progress)
        "popup_fields": [
            ("Plan Name", "name"),
            ("Status", "status"),
            ("ROD Date", "rod_date"),
            ("Admin State", "admin_state"),
            ("NEPA Number", "nepa_number"),
            ("Map Type", "map_type"),
            ("ePlanning", "eplan_link", lambda v: _safe_link(v, "View in ePlanning") if v else None),
        ],
    },
    "blm_wilderness_study_areas": {
        "name": "Wilderness Study Areas",
        "description": "BLM WSAs pending Congressional action",
        "color": "#7C3AED",  # Violet (restricted/protected)
        "popup_fields": [
            ("Name", "name"),
            ("NLCS ID", "nlcs_id"),
            ("Casefile", "casefile"),
            ("Recommendation", "recommendation"),
            ("ROD Date", "rod_date"),
            ("Admin State", "admin_state"),
            ("WSA Type", "wsa_type"),
            ("Suitability", "suitability"),
            ("Wilderness Values", "wilderness_values"),
        ],
    },
    "blm_national_monuments": {
        "name": "National Monuments & NCAs",
        "description": "BLM National Monuments and Conservation Areas",
        "color": "#9333EA",  # Purple (designated areas)
        "popup_fields": [
            ("Name", "name"),
            ("Designation", "designation"),
            ("SMA Code", "sma_code"),
            ("Admin State", "admin_state"),
            ("Geographic State", "geographic_state"),
            ("NLCS ID", "nlcs_id"),
        ],
    },
    "blm_rights_of_way": {
        "name": "BLM Rights of Way",
        "description": "NSO restriction areas and major ROW corridors",
        "color": "#EA580C",  # Orange-red (infrastructure/restrictions)
        "popup_fields": [
            ("Name", "name"),
            ("Restriction Type", "restriction_type"),
        ],
    },
    "grsg_habitat": {
        "name": "Sage-Grouse Habitat",
        "description": "Greater Sage-Grouse Habitat Mgmt Areas (2026 ROD)",
        "color": "#84CC16",  # Lime green (sage habitat)
        "popup_fields": [
            ("Name", "name"),
            ("Habitat Type", "habitat_type"),
            ("Source", "source"),
            ("Acres", "acres", lambda v: f"{v:,.0f} acres" if v else None),
        ],
    },
    "sagebrush_focal_areas": {
        "name": "Sagebrush Focal Areas",
        "description": "Most restricted sage-grouse habitat (mineral withdrawal)",
        "color": "#65A30D",  # Dark lime (highest protection)
        "popup_fields": [
            ("Name", "name"),
            ("Subsurface Withdrawal", "subsurface_withdrawal"),
            ("Surface Mgmt Agency", "surface_management_agency"),
        ],
    },
    "wild_horse_hma": {
        "name": "Wild Horse & Burro HMAs",
        "description": "Herd Management Areas for wild horses and burros",
        "color": "#A16207",  # Dark amber/brown (range)
        "popup_fields": [
            ("Name", "name"),
            ("HMA ID", "hma_id"),
            ("State", "admin_state"),
            ("Herd Type", "herd_type"),
            ("BLM Acres", "blm_acres", lambda v: f"{v:,.0f} acres" if v else None),
        ],
    },
    "national_trails": {
        "name": "National Scenic/Historic Trails",
        "description": "Congressionally designated trail corridors",
        "color": "#B91C1C",  # Dark red (trails)
        "popup_fields": [
            ("Trail Name", "name"),
            ("Display Name", "display_name"),
        ],
    },
    "fire_perimeters": {
        "name": "Fire Perimeters",
        "description": "NIFC interagency fire-perimeter history",
        "color": "#F97316",  # Orange (fire)
        "popup_fields": [
            ("Fire Name", "name"),
            ("Year", "year"),
            ("Category", "category"),
            ("Acres", "acres", lambda v: f"{v:,.0f} acres" if v else None),
            ("Agency", "agency"),
            ("Source", "source"),
        ],
    },
    "lwcf_lands": {
        "name": "LWCF Lands",
        "description": "Land & Water Conservation Fund parcels (Section 6(f))",
        "color": "#047857",  # Emerald (conservation)
        "popup_fields": [
            ("Project", "name"),
            ("State", "state"),
            ("Purpose", "purpose"),
            ("Fund Year", "fund_year"),
            ("Acres", "acres", lambda v: f"{v:,.1f} acres" if v else None),
            ("County", "county"),
            ("Agency", "agency"),
        ],
    },
    "eis_boundaries": {
        "name": "EIS Boundaries",
        "description": "BLM Western US EIS planning area boundaries",
        "color": "#64748B",  # Slate gray (planning)
        "popup_fields": [
            ("EIS Name", "name"),
            ("Acres", "acres", lambda v: f"{v:,.0f} acres" if v else None),
        ],
    },
}

LAND_BOUNDARY_LAYERS = {
    "blm_wilderness_study_areas",
    "blm_national_monuments",
}
for layer_id in LAND_BOUNDARY_LAYERS:
    LAYER_CONFIG[layer_id]["popup_fields"].extend(
        [
            ("Designation Type", "designation_type"),
            ("Classification Basis", "classification_basis"),
            ("Relationship Target", "relation_target"),
            ("Mapped Relationship", "project_relation"),
            ("Leasing Rule", "geothermal_leasing_rule"),
            ("Rule Authority", "leasing_authority"),
            ("Classification Authority", "classification_authority"),
            ("Screening Note", "screening_note"),
            ("Boundary Note", "boundary_note"),
            ("Source", "source_url"),
            ("Retrieved", "retrieved_at"),
        ]
    )

# Layer rendering order (bottom to top)
LAYER_ORDER = [
    "eis_boundaries",
    "federal_lands",
    "usfs_forests",
    "blm_managed_lands",
    "blm_land_use_plans",
    "blm_plans_in_progress",
    "blm_rights_of_way",
    "fire_perimeters",
    "grsg_habitat",
    "sagebrush_focal_areas",
    "wild_horse_hma",
    "counties",
    "usace_districts",
    "wetland_regions",
    "wetland_subregions",
    "nhd_stream_areas",
    "nhd_lakes",
    "nhd_reservoirs",
    "nhd_estuaries",
    "nhd_ice_masses",
    "nhd_perennial_streams",
    "nhd_infrastructure",
    "lwcf_lands",
    "usfs_roadless_areas",
    "blm_wilderness_study_areas",
    "blm_national_monuments",
    "national_trails",
    "nps_boundaries",
    "critical_habitat",
    "wildlife_refuges",
    "tribal_lands",
    "roi",
]


# =============================================================================
# POPUP GENERATION
# =============================================================================


def _get_field_value(properties: Dict, field_spec: Any, formatter: Callable = None) -> Optional[str]:
    """
    Extract and format a field value from properties.

    Args:
        properties: Feature properties dictionary
        field_spec: Field name string, tuple of field names, or None
        formatter: Optional formatting function

    Returns:
        Formatted value string or None
    """
    if field_spec is None:
        # Static value from formatter (trusted: formatters emit HTML intentionally)
        return formatter() if formatter else None

    if isinstance(field_spec, tuple):
        # Multiple fields (e.g., lat, lon)
        values = [properties.get(f) for f in field_spec]
        if all(v is not None for v in values):
            if not formatter:
                return _html_escape(str(values))
            try:
                formatted = formatter(*values)
            except (TypeError, ValueError):
                return _html_escape(", ".join(str(value) for value in values))
            if formatted is None:
                return None
            if isinstance(formatted, _SafeHtml):
                return str(formatted)
            return _html_escape(str(formatted))
        return None

    # Single field
    value = properties.get(field_spec)
    if value is None or str(value) in ("N/A", "None", ""):
        return None

    if formatter:
        try:
            formatted = formatter(value)
        except (TypeError, ValueError):
            return _html_escape(str(value))
        if formatted is None:
            return None
        if isinstance(formatted, _SafeHtml):
            return str(formatted)
        return _html_escape(str(formatted))
    # Untrusted upstream value - HTML-escape before it reaches the popup template.
    return _html_escape(str(value))


def _build_species_popup_html(properties: Dict) -> str:
    """Build HTML for species data in county popups."""
    try:
        species_count = int(properties.get("species_count", 0))
    except (TypeError, ValueError):
        species_count = 0
    if species_count <= 0:
        if "species_count" in properties:
            return """<tr style='border-bottom: 1px solid #E5E7EB;'>
                <td style='padding: 8px 4px; color: #6B7280; font-weight: 500; width: 40%;'>Threatened & Endangered Species</td>
                <td style='padding: 8px 4px; color: #111827;'>None found (2015-present)</td>
            </tr>"""
        return ""

    html = f"""<tr style='border-bottom: 1px solid #E5E7EB;'>
        <td style='padding: 8px 4px; color: #6B7280; font-weight: 500; width: 40%;'>Threatened & Endangered Species</td>
        <td style='padding: 8px 4px; color: #111827;'><b>{species_count} species found</b></td>
    </tr>"""

    species_list = properties.get("species_list", [])
    if species_list:
        display_count = min(10, len(species_list))
        html += f"""<tr style='border-bottom: 1px solid #E5E7EB;'>
            <td colspan='2' style='padding: 12px 4px 4px 4px; color: #111827; font-weight: 600;'>
                Top {display_count} Species:
            </td>
        </tr>"""

        status_colors = {
            "CRITICALLY_ENDANGERED": "#7F1D1D",
            "ENDANGERED": "#991B1B",
            "VULNERABLE": "#EA580C",
            "NEAR_THREATENED": "#CA8A04",
        }

        for species in species_list[:display_count]:
            sci_name = _html_escape(str(species.get("scientific_name", "Unknown")))
            common = _html_escape(str(species.get("common_name", "")))
            status = str(species.get("threat_status", ""))
            safe_status = _html_escape(status.replace("_", " ").title())
            try:
                obs_count = int(species.get("observation_count", 0))
            except (TypeError, ValueError):
                obs_count = 0

            display_name = f"<i>{sci_name}</i>"
            if common:
                display_name = f"{common} ({display_name})"

            status_color = status_colors.get(status, "#6B7280")

            html += f"""<tr style='border-bottom: 1px solid #F3F4F6;'>
                <td colspan='2' style='padding: 6px 4px 6px 12px; color: #374151; font-size: 11px; line-height: 1.4;'>
                    <span style='color: {status_color}; font-weight: 600;'>●</span> {display_name}
                    <br/>
                    <span style='color: #9CA3AF; font-size: 10px; margin-left: 12px;'>
                        {safe_status} • {obs_count} obs
                    </span>
                </td>
            </tr>"""

        if len(species_list) > display_count:
            remaining = len(species_list) - display_count
            html += f"""<tr>
                <td colspan='2' style='padding: 6px 4px; color: #6B7280; font-size: 11px; font-style: italic;'>
                    + {remaining} more species...
                </td>
            </tr>"""

        try:
            total_obs = int(properties.get("total_observations", 0))
        except (TypeError, ValueError):
            total_obs = 0
        html += f"""<tr style='border-top: 2px solid #E5E7EB;'>
            <td colspan='2' style='padding: 8px 4px 4px 4px; color: #6B7280; font-size: 11px;'>
                Data: GBIF (2015-present) • {total_obs} total observations
            </td>
        </tr>"""

    return html


def create_layer_popup(properties: Dict, layer_type: str) -> str:
    """
    Create professional HTML popup content for a feature.

    Args:
        properties: Feature properties dictionary
        layer_type: Type of layer (roi, tribal_lands, etc.)

    Returns:
        HTML string for popup
    """
    config = LAYER_CONFIG.get(layer_type, {})
    layer_color = config.get("color", "#003366")
    layer_name = config.get("name", layer_type)

    html = """<div style='
        font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif;
        font-size: 13px;
        min-width: 260px;
        max-width: 400px;
        color: #1F2937;
    '>"""

    html += f"""<div style='
        background: {_html_escape(str(layer_color), quote=True)};
        color: white;
        padding: 10px 12px;
        margin: -10px -10px 12px -10px;
        border-radius: 4px 4px 0 0;
        font-weight: 600;
        font-size: 14px;
        letter-spacing: 0.3px;
    '>{_html_escape(str(layer_name))}</div>"""

    html += "<table style='width: 100%; border-collapse: collapse;'>"

    # Add configured fields
    popup_fields = config.get("popup_fields", [])
    for field_def in popup_fields:
        if len(field_def) == 2:
            label, field_spec = field_def
            formatter = None
        else:
            label, field_spec, formatter = field_def

        value = _get_field_value(properties, field_spec, formatter)
        if value:
            html += f"""<tr style='border-bottom: 1px solid #E5E7EB;'>
                <td style='padding: 8px 4px; color: #6B7280; font-weight: 500; width: 40%;'>{_html_escape(str(label))}</td>
                <td style='padding: 8px 4px; color: #111827;'>{value}</td>
            </tr>"""

    # Add species data for counties if enabled
    if config.get("species_popup") and "species_count" in properties:
        html += _build_species_popup_html(properties)

    # Fallback for unknown layer types - show all properties
    if not popup_fields:
        for key, value in properties.items():
            if key not in ("layer", "centroid_lat", "centroid_lon") and value:
                label = _html_escape(key.replace("_", " ").title())
                safe_value = _html_escape(str(value))
                html += f"""<tr style='border-bottom: 1px solid #E5E7EB;'>
                    <td style='padding: 8px 4px; color: #6B7280; font-weight: 500; width: 40%;'>{label}</td>
                    <td style='padding: 8px 4px; color: #111827;'>{safe_value}</td>
                </tr>"""

    html += "</table></div>"
    return html


# =============================================================================
# GEOMETRY UTILITIES
# =============================================================================


def simplify_geojson(geojson_data: Dict, tolerance: float = 0.001) -> Dict:
    """
    Simplify GeoJSON geometries to reduce file size.

    Args:
        geojson_data: GeoJSON FeatureCollection
        tolerance: Simplification tolerance in degrees (default 0.001 ~ 100m).
            Zero disables simplification and preserves the original coordinates.

    Returns:
        Simplified GeoJSON FeatureCollection
    """
    if not geojson_data or not geojson_data.get("features"):
        return geojson_data

    simplified_data = copy.deepcopy(geojson_data)
    simplified_features = []

    for feature in simplified_data["features"]:
        geometry = feature.get("geometry") if isinstance(feature, dict) else None
        if not isinstance(geometry, dict) or not geometry.get("type") or not geometry.get("coordinates"):
            logger.warning("Skipping map feature with empty or malformed geometry")
            continue
        try:
            geom = shape(geometry)
            # Even simplify(0) drops collinear vertices. Exact project and land
            # boundaries must bypass simplification and coordinate rewriting.
            simplified_geom = geom if tolerance == 0 else geom.simplify(tolerance, preserve_topology=True)
            if simplified_geom.is_empty:
                logger.warning("Skipping map feature whose simplified geometry is empty")
                continue
            if tolerance != 0:
                feature["geometry"] = mapping(simplified_geom)
            simplified_features.append(feature)
        except Exception as exc:
            logger.warning("Could not simplify map feature: %s", exc)

    simplified_data["features"] = simplified_features
    return simplified_data


# =============================================================================
# MAP LAYER RENDERING
# =============================================================================


def _get_point_icon(layer_type: str, feature: Dict) -> folium.Icon:
    """Get appropriate icon for point features."""
    if layer_type == "roi":
        return folium.Icon(color="red", icon="map-marker", prefix="fa", icon_color="white")

    if layer_type == "nhd_infrastructure":
        infrastructure_type = feature.get("properties", {}).get("infrastructure_type", "")
        icon_map = {
            "Dam": ("darkred", "stop"),
            "Spring": ("blue", "tint"),
            "Seep": ("blue", "tint"),
            "Gage": ("blue", "bar-chart"),
            "Well": ("blue", "dot-circle"),
            "Intake": ("blue", "exchange"),
            "Outfall": ("blue", "exchange"),
        }
        for keyword, (color, icon) in icon_map.items():
            if keyword in infrastructure_type:
                return folium.Icon(color=color, icon=icon, prefix="fa", icon_color="white")
        return folium.Icon(color="red", icon="info", prefix="fa", icon_color="white")

    return folium.Icon(color="blue", icon="circle", prefix="fa", icon_color="white")


def add_geojson_layer(
    map_obj: folium.Map,
    geojson_data: Dict,
    layer_name: str,
    layer_type: str,
    show: bool = True,
) -> None:
    """
    Add a GeoJSON layer to the folium map.

    Args:
        map_obj: Folium map object
        geojson_data: GeoJSON FeatureCollection
        layer_name: Display name for the layer
        layer_type: Type identifier (roi, tribal_lands, etc.)
        show: Whether layer is visible by default
    """
    if not geojson_data or not geojson_data.get("features"):
        logger.info("No features in %s; skipping map layer", layer_name)
        return

    preserve_boundary = layer_type == "roi" or layer_type in LAND_BOUNDARY_LAYERS
    geojson_data = simplify_geojson(geojson_data, tolerance=0 if preserve_boundary else 0.001)
    if not geojson_data.get("features"):
        logger.info("No valid geometries in %s; skipping map layer", layer_name)
        return

    config = LAYER_CONFIG.get(layer_type, {})
    color = config.get("color", "#888888")

    feature_group = folium.FeatureGroup(name=layer_name, show=show)

    def style_function(feature):
        geom_type = feature["geometry"]["type"]
        if geom_type in ("Polygon", "MultiPolygon"):
            return {
                "fillColor": color,
                "color": color,
                "weight": 2,
                "fillOpacity": 0.3,
                "opacity": 0.8,
            }
        return {"color": color, "weight": 2, "opacity": 0.8}

    # Separate point and geometry features
    point_features = [f for f in geojson_data["features"] if f.get("geometry", {}).get("type") == "Point"]
    geom_features = [
        f
        for f in geojson_data["features"]
        if f.get("geometry", {}).get("type") in ("Polygon", "MultiPolygon", "LineString", "MultiLineString")
    ]

    # Add point markers
    for feature in point_features:
        props = feature.get("properties", {})
        popup_html = create_layer_popup(props, layer_type)
        coords = feature["geometry"]["coordinates"]
        # Escape tooltip: upstream feature names are untrusted.
        tooltip_name = _html_escape(str(props.get("name", layer_name)))
        folium.Marker(
            location=[coords[1], coords[0]],
            popup=folium.Popup(popup_html, max_width=300),
            tooltip=tooltip_name,
            icon=_get_point_icon(layer_type, feature),
        ).add_to(feature_group)

    # Add polygon/line features
    for feature in geom_features:
        props = feature.get("properties", {})
        popup_html = create_layer_popup(props, layer_type)
        # Escape tooltip: upstream feature names are untrusted.
        name = _html_escape(str(props.get("name", layer_name)))

        folium.GeoJson(
            feature,
            style_function=style_function,
            highlight_function=lambda x: {"weight": 3, "fillOpacity": 0.5},
            tooltip=folium.Tooltip(name, sticky=True),
            popup=folium.Popup(popup_html, max_width=400),
        ).add_to(feature_group)

    feature_group.add_to(map_obj)


# =============================================================================
# MAIN RENDER FUNCTION
# =============================================================================


def render_environmental_map(
    layers_data: Dict[str, Dict],
    center_lat: float,
    center_lon: float,
    output_path: str,
    title: Optional[str] = None,
    basemap: str = "CartoDB Positron",
    zoom_start: int = 10,
    source_attribution: Optional[List[str]] = None,
    layer_statuses: Optional[Dict[str, Dict[str, Any]]] = None,
) -> str:
    """
    Render interactive HTML map with multiple environmental layers.

    Args:
        layers_data: Dictionary mapping layer names to GeoJSON FeatureCollections
        center_lat: Map center latitude
        center_lon: Map center longitude
        output_path: Path to save HTML file
        title: Optional map title
        basemap: Basemap style (CartoDB Positron, OpenStreetMap, USGS,
            Satellite). Defaults to CartoDB Positron.
        zoom_start: Initial folium zoom level. Default 10 works for ~5 mi
            ROIs; use 7-8 for larger (30-55 mi) buffers so the full ROI
            fits in a standard screenshot frame.
        source_attribution: Optional source labels to include in the map.
        layer_statuses: Optional per-layer collection statuses used to display
            requested, rendered, empty, partial, and failed counts.

    Returns:
        Path to generated HTML file
    """
    # Select basemap
    basemap_options = {
        "CartoDB Positron": ("CartoDB positron", "CartoDB"),
        "OpenStreetMap": ("OpenStreetMap", "OpenStreetMap"),
        "USGS": ("https://basemap.nationalmap.gov/arcgis/rest/services/USGSTopo/MapServer/tile/{z}/{y}/{x}", "USGS"),
        "Satellite": (
            "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
            "ESRI",
        ),
    }
    tiles, attr = basemap_options.get(basemap, ("CartoDB positron", "CartoDB"))

    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=zoom_start,
        tiles=tiles,
        attr=attr,
        control_scale=True,
    )

    # Add title
    if title:
        title_html = f"""
        <div style="
            position: fixed;
            top: 20px;
            left: 50%;
            transform: translateX(-50%);
            background: rgba(255, 255, 255, 0.95);
            backdrop-filter: blur(10px);
            -webkit-backdrop-filter: blur(10px);
            padding: 14px 32px;
            border: 1px solid rgba(0, 51, 102, 0.2);
            border-radius: 8px;
            font-family: 'Segoe UI', 'Helvetica Neue', Arial, sans-serif;
            font-size: 18px;
            font-weight: 600;
            color: #003366;
            letter-spacing: 0.3px;
            z-index: 9999;
            box-shadow: 0 4px 12px rgba(0, 51, 102, 0.15);
        ">{_html_escape(str(title))}</div>
        """
        m.get_root().html.add_child(folium.Element(title_html))

    if layer_statuses:
        requested_count = len(layer_statuses)
        rendered_count = sum(status.get("feature_count", 0) > 0 for status in layer_statuses.values())
        empty_count = sum(status.get("status") == "empty" for status in layer_statuses.values())
        partial_count = sum(status.get("status") == "partial" for status in layer_statuses.values())
        failed_count = sum(status.get("status") == "failed" for status in layer_statuses.values())
        partial_text = f" ({partial_count} partial)" if partial_count else ""
        status_top = "86px" if title else "20px"
        status_html = f"""
        <div aria-label="Map layer status" style="
            position: fixed;
            top: {status_top};
            left: 50%;
            transform: translateX(-50%);
            background: rgba(255, 255, 255, 0.95);
            padding: 6px 12px;
            border: 1px solid rgba(0, 51, 102, 0.18);
            border-radius: 999px;
            font: 600 11px/1.2 'Segoe UI', 'Helvetica Neue', Arial, sans-serif;
            color: #334155;
            white-space: nowrap;
            z-index: 9999;
            box-shadow: 0 2px 8px rgba(0, 51, 102, 0.10);
        ">
            {requested_count} requested &middot;
            {rendered_count} rendered{partial_text} &middot;
            {empty_count} empty &middot;
            {failed_count} failed
        </div>
        """
        m.get_root().html.add_child(folium.Element(status_html))

    # Add layers in defined order
    for layer_type in LAYER_ORDER:
        if layer_type in layers_data:
            config = LAYER_CONFIG.get(layer_type, {})
            add_geojson_layer(
                m,
                layers_data[layer_type],
                config.get("name", layer_type),
                layer_type,
                show=True,
            )

    # Add any remaining layers not in order
    for layer_type, geojson_data in layers_data.items():
        if layer_type not in LAYER_ORDER:
            config = LAYER_CONFIG.get(layer_type, {})
            add_geojson_layer(m, geojson_data, config.get("name", layer_type), layer_type, show=True)

    # Add layer control
    folium.LayerControl(position="topright", collapsed=False).add_to(m)

    if source_attribution:
        source_items = "".join(f"<li>{_html_escape(str(source))}</li>" for source in source_attribution)
        notes = []
        for layer_id, status in (layer_statuses or {}).items():
            notes.extend(f"{layer_id}: {warning}" for warning in status.get("warnings", []))
            if status.get("screening_note"):
                notes.append(status["screening_note"])
        note_items = "".join(f"<li>{_html_escape(str(note))}</li>" for note in dict.fromkeys(notes))
        attribution_html = f"""
        <details style="
            position: fixed;
            left: 10px;
            bottom: 10px;
            z-index: 9998;
            max-width: 420px;
            background: rgba(255,255,255,0.95);
            border: 1px solid #CBD5E1;
            border-radius: 6px;
            padding: 8px 10px;
            font: 11px/1.35 Arial, sans-serif;
            color: #334155;
        ">
            <summary style="cursor: pointer; font-weight: 600;">Data sources and limitations</summary>
            <ul style="margin: 6px 0 4px 18px; padding: 0;">{source_items}</ul>
            <p style="margin: 6px 0 0;">Screening information; confirm material findings against current authoritative records.</p>
            <ul style="margin: 6px 0 4px 18px; padding: 0; max-height: 220px; overflow-y: auto;">{note_items}</ul>
        </details>
        """
        m.get_root().html.add_child(folium.Element(attribution_html))

    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = target.with_suffix(target.suffix + ".tmp")
    m.save(str(temporary))
    os.replace(temporary, target)
    target.chmod(0o600)
    logger.info("Map saved to %s", target)

    return str(target)


def export_combined_geojson(
    layers_data: Dict[str, Dict],
    output_path: str,
    *,
    collection_metadata: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Export all layers as a single GeoJSON file.

    Args:
        layers_data: Dictionary mapping layer names to GeoJSON FeatureCollections
        output_path: Path to save GeoJSON file
        collection_metadata: Optional provenance and per-layer status metadata.

    Returns:
        Path to generated GeoJSON file
    """
    all_features = []

    for layer_type, geojson_data in layers_data.items():
        for feature in geojson_data.get("features", []):
            exported_feature = copy.deepcopy(feature)
            exported_feature.setdefault("properties", {})["layer"] = layer_type
            all_features.append(exported_feature)

    metadata = dict(collection_metadata or {})
    metadata.update(
        {
            "generated": datetime.now(timezone.utc).isoformat(),
            "layer_count": len(layers_data),
            "feature_count": len(all_features),
        }
    )
    combined = {
        "type": "FeatureCollection",
        "features": all_features,
        "metadata": metadata,
    }

    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(combined, indent=2), encoding="utf-8")
    os.replace(temporary, target)
    target.chmod(0o600)
    logger.info("GeoJSON exported to %s", target)
    return str(target)
