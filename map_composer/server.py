#!/usr/bin/env python3
"""
MCP server for multi-layer environmental map composition.
Generates interactive HTML maps with toggleable layers from multiple data sources.
"""

from __future__ import annotations

import copy
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4

from fastmcp import FastMCP
from platformdirs import user_data_path
from pydantic import Field

from nepa_mcp_common.arcgis import ArcGISService
from nepa_mcp_common.validation import validate_coordinates
from src.core.geometry_collector import DEFAULT_LAYERS, LAYER_PROFILES, NHD_BASE_URL, collect_all_layers
from src.core.map_renderer import export_combined_geojson, render_environmental_map
from src.core.land_layers import LAND_SOURCES

# Authoritative metadata for every layer in DEFAULT_LAYERS. Single source of
# truth consumed by list_available_layers() below and by the Map Composer
# documentation's layer table (kept in sync by the same grouping).
LAYER_METADATA: dict[str, dict[str, str]] = {
    "roi": {
        "category": "Region of Interest",
        "title": "Project Location and Buffer",
        "source": "User-specified coordinates (calculated via ArcGIS geometry service)",
        "geometry": "Point + Polygon",
        "review_use": "Defines the project area used for map-based screening",
    },
    "tribal_lands": {
        "category": "Tribal",
        "title": "Tribal Lands",
        "source": "U.S. Census Bureau TIGERweb AIANNHA",
        "geometry": "Polygon",
        "review_use": "Provides geographic context for early coordination and project-area review",
    },
    "counties": {
        "category": "Administrative",
        "title": "County Boundaries",
        "source": "U.S. Census Bureau TIGERweb",
        "geometry": "Polygon",
        "review_use": "Provides administrative context for scoping and related county-level data",
    },
    "critical_habitat": {
        "category": "Species and Habitat",
        "title": "Critical Habitat",
        "source": "U.S. Fish and Wildlife Service Critical Habitat FeatureServer",
        "geometry": "Polygon",
        "review_use": "Identifies mapped habitat for closer biological-resource review",
    },
    "wildlife_refuges": {
        "category": "Species and Habitat",
        "title": "National Wildlife Refuges",
        "source": "U.S. Fish and Wildlife Service National Wildlife Refuge System",
        "geometry": "Polygon",
        "review_use": "Identifies refuge boundaries for land and resource context",
    },
    "usace_districts": {
        "category": "Water Resources (USACE)",
        "title": "USACE Regulatory Districts",
        "source": "U.S. Army Corps of Engineers regulatory boundary service",
        "geometry": "Polygon",
        "review_use": "Identifies the relevant USACE district for agency follow-up",
    },
    "wetland_regions": {
        "category": "Water Resources (USACE)",
        "title": "Wetland Delineation Regions",
        "source": "USACE COE wetland regions service",
        "geometry": "Polygon",
        "review_use": "Provides regional wetland-delineation method context",
    },
    "wetland_subregions": {
        "category": "Water Resources (USACE)",
        "title": "Wetland Delineation Subregions",
        "source": "USACE COE wetland subregions service",
        "geometry": "Polygon",
        "review_use": "Provides subregional wetland-delineation context",
    },
    "nhd_lakes": {
        "category": "Water Resources (USGS NHD)",
        "title": "Lakes and Ponds",
        "source": "USGS National Hydrography Dataset",
        "geometry": "Polygon",
        "review_use": "Maps lakes and ponds for water-resource screening",
    },
    "nhd_reservoirs": {
        "category": "Water Resources (USGS NHD)",
        "title": "Reservoirs",
        "source": "USGS National Hydrography Dataset",
        "geometry": "Polygon",
        "review_use": "Maps reservoirs for water-resource and infrastructure context",
    },
    "nhd_estuaries": {
        "category": "Water Resources (USGS NHD)",
        "title": "Estuaries",
        "source": "USGS National Hydrography Dataset",
        "geometry": "Polygon",
        "review_use": "Maps estuarine features for coastal and water-resource context",
    },
    "nhd_ice_masses": {
        "category": "Water Resources (USGS NHD)",
        "title": "Glaciers and Ice Masses",
        "source": "USGS National Hydrography Dataset",
        "geometry": "Polygon",
        "review_use": "Maps glaciers and ice masses for baseline environmental context",
    },
    "nhd_perennial_streams": {
        "category": "Water Resources (USGS NHD)",
        "title": "Perennial Stream Centerlines",
        "source": "USGS National Hydrography Dataset",
        "geometry": "Polyline",
        "review_use": "Maps perennial hydrography for water-resource screening",
    },
    "nhd_stream_areas": {
        "category": "Water Resources (USGS NHD)",
        "title": "River and Stream Areas",
        "source": "USGS National Hydrography Dataset",
        "geometry": "Polygon",
        "review_use": "Maps river and stream areas for water-resource screening",
    },
    "nhd_infrastructure": {
        "category": "Water Resources (USGS NHD)",
        "title": "Water Infrastructure (Dams, Springs, Gages, Wells, Intakes)",
        "source": "USGS National Hydrography Dataset",
        "geometry": "Point",
        "review_use": "Provides water-infrastructure and monitoring context",
    },
    "federal_lands": {
        "category": "Federal Lands (non-BLM)",
        "title": "Federal Protected Lands",
        "source": "USGS Protected Areas Database (PAD-US 4.1), filtered to non-BLM federal managers",
        "geometry": "Polygon",
        "review_use": "Identifies mapped federal land managers and protected areas",
    },
    "usfs_forests": {
        "category": "Federal Lands (non-BLM)",
        "title": "National Forest System Boundaries",
        "source": "USDA Forest Service Enterprise Data Warehouse",
        "geometry": "Polygon",
        "review_use": "Provides National Forest System and land-management context",
    },
    "usfs_roadless_areas": {
        "category": "Federal Lands (non-BLM)",
        "title": "Inventoried Roadless Areas (2001 Rule)",
        "source": "USDA Forest Service Enterprise Data Warehouse",
        "geometry": "Polygon",
        "review_use": "Identifies inventoried roadless areas for land-use context",
    },
    "nps_boundaries": {
        "category": "Federal Lands (non-BLM)",
        "title": "National Park Service Unit Boundaries",
        "source": "NPS Land Resources Division Boundary and Tract Data Service",
        "geometry": "Polygon",
        "review_use": "Identifies National Park Service units for land and resource context",
    },
    "blm_managed_lands": {
        "category": "Federal Lands (BLM)",
        "title": "BLM-Managed Protected Lands (PAD-US Fee)",
        "source": "USGS Protected Areas Database (PAD-US 4.1), filtered to BLM",
        "geometry": "Polygon",
        "review_use": "Identifies mapped BLM-managed lands",
    },
    "blm_land_use_plans": {
        "category": "Federal Lands (BLM)",
        "title": "Approved Land Use Plans (RMPs)",
        "source": "BLM National ArcGIS Portal",
        "geometry": "Polygon",
        "review_use": "Provides approved BLM land-use-plan context",
    },
    "blm_plans_in_progress": {
        "category": "Federal Lands (BLM)",
        "title": "Land Use Plans Under Revision",
        "source": "BLM National ArcGIS Portal",
        "geometry": "Polygon",
        "review_use": "Identifies BLM planning areas with revisions in progress",
    },
    "blm_wilderness_study_areas": {
        "category": "Federal Lands (BLM)",
        "title": "Wilderness Study Areas",
        "source": "BLM National Conservation Lands System",
        "geometry": "Polygon",
        "review_use": "Identifies mapped wilderness study areas",
    },
    "blm_national_monuments": {
        "category": "Federal Lands (BLM)",
        "title": "National Monuments and Conservation Areas",
        "source": "BLM National Conservation Lands System",
        "geometry": "Polygon",
        "review_use": "Identifies mapped monuments and conservation areas",
    },
    "blm_rights_of_way": {
        "category": "Federal Lands (BLM)",
        "title": "No Surface Occupancy Restrictions",
        "source": "BLM National ArcGIS Portal",
        "geometry": "Polygon",
        "review_use": "Provides mapped right-of-way and surface-use context",
    },
    "grsg_habitat": {
        "category": "Habitat Protection",
        "title": "Greater Sage-Grouse Habitat Management Areas",
        "source": "BLM National ArcGIS Portal (2026 ROD)",
        "geometry": "Polygon",
        "review_use": "Provides greater sage-grouse habitat-management context",
    },
    "sagebrush_focal_areas": {
        "category": "Habitat Protection",
        "title": "Sagebrush Focal Areas",
        "source": "BLM National ArcGIS Portal",
        "geometry": "Polygon",
        "review_use": "Identifies mapped sagebrush focal areas",
    },
    "wild_horse_hma": {
        "category": "Habitat Protection",
        "title": "Wild Horse and Burro Herd Management Areas",
        "source": "BLM National ArcGIS Portal",
        "geometry": "Polygon",
        "review_use": "Identifies wild horse and burro management areas",
    },
    "national_trails": {
        "category": "Contextual",
        "title": "National Scenic and Historic Trails",
        "source": "BLM National ArcGIS Portal",
        "geometry": "Polyline",
        "review_use": "Provides national trail and corridor context",
    },
    "fire_perimeters": {
        "category": "Contextual",
        "title": "Historical Fire Perimeters",
        "source": "National Interagency Fire Center authoritative fire history",
        "geometry": "Polygon",
        "review_use": "Provides historical disturbance context",
    },
    "lwcf_lands": {
        "category": "Contextual",
        "title": "Land and Water Conservation Fund Parcels",
        "source": "BLM National ArcGIS Portal",
        "geometry": "Polygon",
        "review_use": "Identifies mapped Land and Water Conservation Fund parcels",
    },
    "eis_boundaries": {
        "category": "Contextual",
        "title": "Western US EIS Planning Boundaries",
        "source": "BLM National ArcGIS Portal",
        "geometry": "Polygon",
        "review_use": "Identifies prior EIS planning boundaries for contextual review",
    },
}

LAYER_SOURCE_URLS = {
    "roi": ArcGISService.GEOMETRY_SERVICE,
    "tribal_lands": "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/AIANNHA/MapServer",
    "counties": "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/tigerWMS_Current/MapServer",
    "critical_habitat": "https://services.arcgis.com/QVENGdaPbd4LUkLV/arcgis/rest/services/USFWS_Critical_Habitat/FeatureServer",
    "wildlife_refuges": "https://services.arcgis.com/QVENGdaPbd4LUkLV/arcgis/rest/services/National_Wildlife_Refuge_System_Boundaries/FeatureServer",
    "usace_districts": "https://services7.arcgis.com/n1YM8pTrFmm7L4hs/ArcGIS/rest/services/usace_cw_districts/FeatureServer",
    "wetland_regions": "https://services7.arcgis.com/n1YM8pTrFmm7L4hs/ArcGIS/rest/services/coe_wetland_regions/FeatureServer",
    "wetland_subregions": "https://services7.arcgis.com/n1YM8pTrFmm7L4hs/ArcGIS/rest/services/coe_wetland_subregions/FeatureServer",
    **{
        layer: NHD_BASE_URL
        for layer in (
            "nhd_lakes",
            "nhd_reservoirs",
            "nhd_estuaries",
            "nhd_ice_masses",
            "nhd_perennial_streams",
            "nhd_stream_areas",
            "nhd_infrastructure",
        )
    },
    "federal_lands": "https://edits.nationalmap.gov/arcgis/rest/services/PAD-US/PAD_US_4_1/MapServer",
    "usfs_forests": "https://apps.fs.usda.gov/arcx/rest/services/EDW/EDW_ForestSystemBoundaries_01/MapServer",
    "usfs_roadless_areas": "https://apps.fs.usda.gov/arcx/rest/services/EDW/EDW_InventoriedRoadlessAreas2001_01/MapServer",
    "nps_boundaries": "https://services1.arcgis.com/fBc8EJBxQRMcHlei/arcgis/rest/services/NPS_Land_Resources_Division_Boundary_and_Tract_Data_Service/FeatureServer",
    "blm_managed_lands": "https://edits.nationalmap.gov/arcgis/rest/services/PAD-US/PAD_US_4_1/MapServer",
    "blm_land_use_plans": "https://services1.arcgis.com/KbxwQRRfWyEYLgp4/arcgis/rest/services/BLM_Natl_Land_Use_Plans_Approved_2022/FeatureServer",
    "blm_plans_in_progress": "https://services1.arcgis.com/KbxwQRRfWyEYLgp4/arcgis/rest/services/BLM_Natl_Revision_Development_Land_Use_Plans/FeatureServer",
    "blm_wilderness_study_areas": "https://services1.arcgis.com/KbxwQRRfWyEYLgp4/arcgis/rest/services/BLM_Natl_NLCS_Wilderness_Study_Areas_Polygons/FeatureServer/3",
    "blm_national_monuments": "https://services1.arcgis.com/KbxwQRRfWyEYLgp4/arcgis/rest/services/BLM_Natl_NLCS_National_Monuments_National_Conservation_Areas_Polygons/FeatureServer",
    "blm_rights_of_way": "https://services1.arcgis.com/KbxwQRRfWyEYLgp4/arcgis/rest/services/Rights_of_Way/FeatureServer",
    "grsg_habitat": "https://services1.arcgis.com/KbxwQRRfWyEYLgp4/arcgis/rest/services/BLM_Natl_WesternUS_GRSG_ROD_HabitatMgmtAreas_Feb_2026/FeatureServer",
    "sagebrush_focal_areas": "https://services1.arcgis.com/KbxwQRRfWyEYLgp4/arcgis/rest/services/BLM_Natl_WesternUS_GRSG_Sagebrush_Focal_Areas_v2/FeatureServer",
    "wild_horse_hma": "https://services1.arcgis.com/KbxwQRRfWyEYLgp4/arcgis/rest/services/BLM_Natl_Wild_Horse_and_Burro_Heard_Mgmt_Area_Polygons/FeatureServer",
    "national_trails": "https://services1.arcgis.com/KbxwQRRfWyEYLgp4/arcgis/rest/services/National_Scenic_and_Historic_Trails_NSHT/FeatureServer",
    "fire_perimeters": "https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/InterAgencyFirePerimeterHistory_All_Years_View/FeatureServer",
    "lwcf_lands": "https://services1.arcgis.com/KbxwQRRfWyEYLgp4/arcgis/rest/services/BLM_Natl_Land_and_Water_Conservation_Fund_LWCF_Polygons/FeatureServer",
    "eis_boundaries": "https://services1.arcgis.com/KbxwQRRfWyEYLgp4/arcgis/rest/services/BLM_Natl_WesternUS_EIS_Boundaries/FeatureServer",
}

LAYER_SOURCE_URLS.update(LAND_SOURCES)

ARTIFACT_TOOL_ANNOTATIONS = {
    "title": "Create environmental map artifact",
    "readOnlyHint": False,
    "destructiveHint": False,
    "idempotentHint": False,
    "openWorldHint": True,
}
REFERENCE_TOOL_ANNOTATIONS = {
    "title": "List Map Composer layers",
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
}

Latitude = Annotated[
    float,
    Field(
        ge=-90,
        le=90,
        description="Latitude in decimal degrees (WGS84), valid range -90 to 90.",
    ),
]
Longitude = Annotated[
    float,
    Field(
        ge=-180,
        le=180,
        description="Longitude in decimal degrees (WGS84), valid range -180 to 180.",
    ),
]
BufferMiles = Annotated[
    float,
    Field(
        ge=0.1,
        le=100.0,
        description="Circular point-buffer radius in miles, valid range 0.1 to 100.",
    ),
]
MapProfile = Annotated[
    Literal["screening", "biological", "water", "lands", "geothermal", "full"],
    Field(
        description=(
            "Named layer profile. The default full profile requests all 32 layers; "
            "explicit layers override the selected profile."
        )
    ),
]
LayerSelection = Annotated[
    list[str] | None,
    Field(description="Optional explicit Map Composer layer IDs; overrides profile when provided."),
]
ProjectGeometry = Annotated[
    dict | None,
    Field(
        description="Optional WGS84 GeoJSON Polygon/MultiPolygon footprint inside the search buffer, at most 10000 vertices. "
        "Land-designation relations use this footprint; otherwise they refer only to the project point."
    ),
]
MapTitle = Annotated[
    str | None,
    Field(max_length=200, description="Optional plain-text map title, maximum 200 characters."),
]
Basemap = Annotated[
    Literal["CartoDB Positron", "OpenStreetMap", "USGS", "Satellite"],
    Field(description="Interactive basemap style. Defaults to CartoDB Positron."),
]

mcp = FastMCP("map-composer")


def _artifact_directory() -> Path:
    """Return the operator-controlled artifact directory with private permissions."""

    configured = os.environ.get("NEPA_MCP_OUTPUT_DIR")
    directory = (
        Path(configured).expanduser() if configured else user_data_path("nepa-mcp") / "artifacts" / "map_composer"
    )
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    return directory.resolve()


def _artifact_path(
    *,
    prefix: str,
    suffix: str,
    latitude: float,
    longitude: float,
    buffer_miles: float,
) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    location = f"{latitude:.5f}_{longitude:.5f}_{buffer_miles:g}mi"
    location = location.replace("-", "m").replace(".", "p")
    return _artifact_directory() / f"{prefix}_{location}_{timestamp}_{uuid4().hex[:8]}{suffix}"


def _zoom_start_for_buffer(buffer_miles: float) -> int:
    """Choose a readable initial zoom while keeping the ROI in context."""

    if buffer_miles <= 2:
        return 13
    if buffer_miles <= 5:
        return 12
    if buffer_miles <= 10:
        return 11
    if buffer_miles <= 25:
        return 10
    if buffer_miles <= 50:
        return 9
    return 8


def _resolve_layers(profile: str, layers: list[str] | None) -> list[str]:
    selected = list(layers if layers is not None else LAYER_PROFILES[profile])
    selected = list(dict.fromkeys(selected))
    if not selected:
        raise ValueError("At least one Map Composer layer must be selected.")

    unknown = [layer for layer in selected if layer not in DEFAULT_LAYERS]
    if unknown:
        raise ValueError(
            "Unknown Map Composer layer(s): " + ", ".join(unknown) + ". Call list_available_layers for valid layer IDs."
        )
    return selected


def _enriched_statuses(collection) -> dict[str, dict]:
    enriched: dict[str, dict] = {}
    for layer_id, status in collection.statuses.items():
        meta = LAYER_METADATA[layer_id]
        enriched[layer_id] = {
            **status,
            "title": meta["title"],
            "source": meta["source"],
            "source_url": LAYER_SOURCE_URLS[layer_id],
        }
    return enriched


def _collection_metadata(
    *,
    collection,
    latitude: float,
    longitude: float,
    buffer_miles: float,
    profile: str,
    selected_layers: list[str],
) -> dict:
    return {
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "profile": profile,
        "selected_layers": selected_layers,
        "project_geometry": copy.deepcopy(collection.project_geometry),
        "relation_target": "project_footprint" if collection.project_geometry is not None else "project_point",
        "roi": {
            "latitude": latitude,
            "longitude": longitude,
            "buffer_miles": buffer_miles,
            "coordinate_reference_system": "WGS84",
        },
        "layer_summary": _status_counts(collection),
        "layers": _enriched_statuses(collection),
        "limitations": (
            "Screening information; confirm material findings against current "
            "authoritative records. An unavailable layer is not a no-hit."
        ),
    }


def _summary_lines(collection) -> list[str]:
    lines: list[str] = []
    for layer_id, status in collection.statuses.items():
        line = f"- {layer_id}: {status['feature_count']} features ({status['status']})"
        lines.append(line)
        lines.extend(f"  Warning: {warning}" for warning in status.get("warnings", []))
        if status.get("screening_note"):
            lines.append("  " + status["screening_note"])
    return lines


def _status_counts(collection) -> dict[str, int]:
    statuses = collection.statuses.values()
    return {
        "requested": len(collection.statuses),
        "rendered": sum(status["feature_count"] > 0 for status in statuses),
        "empty": sum(status["status"] == "empty" for status in collection.statuses.values()),
        "partial": sum(status["status"] == "partial" for status in collection.statuses.values()),
        "failed": sum(status["status"] == "failed" for status in collection.statuses.values()),
    }


def _status_summary_line(collection) -> str:
    counts = _status_counts(collection)
    rendered = f"{counts['rendered']} rendered"
    if counts["partial"]:
        rendered += f" ({counts['partial']} partial)"
    return f"{counts['requested']} requested, {rendered}, {counts['empty']} empty, {counts['failed']} failed"


@mcp.tool(
    name="compose_environmental_map",
    annotations=ARTIFACT_TOOL_ANNOTATIONS,
    timeout=300.0,
)
def compose_environmental_map(
    latitude: Latitude,
    longitude: Longitude,
    buffer_miles: BufferMiles = 25.0,
    profile: MapProfile = "full",
    layers: LayerSelection = None,
    title: MapTitle = None,
    basemap: Basemap = "CartoDB Positron",
    include_species_data: Annotated[
        bool,
        Field(description="Enrich county popups with recent GBIF species occurrence data."),
    ] = False,
    project_geometry: ProjectGeometry = None,
) -> str:
    """Create an interactive environmental screening map as a local HTML artifact."""

    latitude, longitude, buffer_miles = validate_coordinates(latitude, longitude, buffer_miles)
    selected_layers = _resolve_layers(profile, layers)
    land_options = {}
    if project_geometry is not None:
        land_options["project_geometry"] = project_geometry
    collection = collect_all_layers(
        latitude,
        longitude,
        buffer_miles,
        selected_layers,
        include_species_data,
        **land_options,
    )
    metadata = _collection_metadata(
        collection=collection,
        latitude=latitude,
        longitude=longitude,
        buffer_miles=buffer_miles,
        profile="custom" if layers is not None else profile,
        selected_layers=selected_layers,
    )
    output_path = _artifact_path(
        prefix="environmental_map",
        suffix=".html",
        latitude=latitude,
        longitude=longitude,
        buffer_miles=buffer_miles,
    )
    source_attribution = list(dict.fromkeys(LAYER_METADATA[layer]["source"] for layer in selected_layers))
    rendered_path = render_environmental_map(
        layers_data=collection.layers,
        center_lat=latitude,
        center_lon=longitude,
        output_path=str(output_path),
        title=title,
        basemap=basemap,
        zoom_start=_zoom_start_for_buffer(buffer_miles),
        source_attribution=source_attribution,
        layer_statuses=collection.statuses,
    )

    total_features = sum(status["feature_count"] for status in collection.statuses.values())
    summary = "\n".join(_summary_lines(collection))
    return (
        "Interactive environmental map generated\n\n"
        f"Location: ({latitude}, {longitude})\n"
        f"Buffer: {buffer_miles} miles\n"
        f"Profile: {metadata['profile']}\n"
        f"Basemap: {basemap}\n"
        f"Layers: {_status_summary_line(collection)}\n"
        f"Total features: {total_features}\n"
        f"Output: {rendered_path}\n\n"
        f"Layer status:\n{summary}\n\n"
        "The HTML embeds the selected vector data but requires network access "
        "for basemap tiles and standard web-map assets."
    )


@mcp.tool(
    name="export_all_layers_geojson",
    annotations=ARTIFACT_TOOL_ANNOTATIONS,
    timeout=300.0,
)
def export_all_layers_geojson(
    latitude: Latitude,
    longitude: Longitude,
    buffer_miles: BufferMiles = 25.0,
    profile: MapProfile = "full",
    layers: LayerSelection = None,
    include_species_data: Annotated[
        bool,
        Field(description="Enrich county properties with recent GBIF species occurrence data."),
    ] = False,
    project_geometry: ProjectGeometry = None,
) -> str:
    """Export selected environmental map layers as one provenance-rich GeoJSON artifact."""

    latitude, longitude, buffer_miles = validate_coordinates(latitude, longitude, buffer_miles)
    selected_layers = _resolve_layers(profile, layers)
    land_options = {}
    if project_geometry is not None:
        land_options["project_geometry"] = project_geometry
    collection = collect_all_layers(
        latitude,
        longitude,
        buffer_miles,
        selected_layers,
        include_species_data,
        **land_options,
    )
    metadata = _collection_metadata(
        collection=collection,
        latitude=latitude,
        longitude=longitude,
        buffer_miles=buffer_miles,
        profile="custom" if layers is not None else profile,
        selected_layers=selected_layers,
    )
    output_path = _artifact_path(
        prefix="environmental_layers",
        suffix=".geojson",
        latitude=latitude,
        longitude=longitude,
        buffer_miles=buffer_miles,
    )
    exported_path = export_combined_geojson(
        collection.layers,
        str(output_path),
        collection_metadata=metadata,
    )

    total_features = sum(status["feature_count"] for status in collection.statuses.values())
    summary = "\n".join(_summary_lines(collection))
    return (
        "Environmental layer export generated\n\n"
        f"Location: ({latitude}, {longitude})\n"
        f"Buffer: {buffer_miles} miles\n"
        f"Profile: {metadata['profile']}\n"
        f"Layers: {_status_summary_line(collection)}\n"
        f"Total features: {total_features}\n"
        f"Output: {exported_path}\n\n"
        f"Layer status:\n{summary}"
    )


@mcp.tool(
    name="list_available_layers",
    annotations=REFERENCE_TOOL_ANNOTATIONS,
    timeout=30.0,
)
def list_available_layers() -> str:
    """List Map Composer layer IDs, source publishers, review uses, and profiles."""

    categories: dict[str, list[str]] = {}
    for layer_id in DEFAULT_LAYERS:
        categories.setdefault(LAYER_METADATA[layer_id]["category"], []).append(layer_id)

    lines = [
        "Available Map Composer Layers",
        "",
        f"{len(DEFAULT_LAYERS)} layers are available from public federal data services.",
        "Explicit layer IDs override a named profile.",
        "",
        "Profiles:",
    ]
    for profile, layer_ids in LAYER_PROFILES.items():
        lines.append(f"- {profile}: {', '.join(layer_ids)}")

    for category, layer_ids in categories.items():
        lines.extend(["", f"== {category} =="])
        for layer_id in layer_ids:
            meta = LAYER_METADATA[layer_id]
            lines.extend(
                [
                    f"- {layer_id}: {meta['title']} ({meta['geometry']})",
                    f"  Source: {meta['source']}",
                    f"  Review use: {meta['review_use']}",
                ]
            )

    lines.extend(
        [
            "",
            "Layer availability depends on source coverage and service availability.",
            "Failed or partial requests are returned as warnings and are not treated as no-hit findings.",
        ]
    )
    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run(transport="stdio", show_banner=False)
