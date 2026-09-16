"""
Geometry Collector - Query and collect full geometries from environmental data APIs

This module collects complete GeoJSON geometries (polygons, lines, points)
for use in multi-layer environmental mapping.
"""

import copy
import json
import logging
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from shapely.geometry import shape, Point as ShapelyPoint

from nepa_mcp_common.arcgis import ArcGISFeatureQueryResult, ArcGISService
from nepa_mcp_common.land_status import designation_details
from src.core.constants import (
    TRIBAL_LAYERS,
    TIGERWEB_AIANNHA_URL,
    SQ_METERS_TO_SQ_MILES,
    BLM_MANAGED_LANDS_URL,
    BLM_MANAGED_LANDS_LAYER_ID,
    BLM_LAND_USE_PLANS_URL,
    BLM_LAND_USE_PLANS_LAYER_ID,
    BLM_PLANS_IN_PROGRESS_URL,
    BLM_PLANS_IN_PROGRESS_LAYER_ID,
    BLM_NATIONAL_MONUMENTS_URL,
    BLM_NATIONAL_MONUMENTS_LAYER_ID,
    BLM_WSA_URL,
    BLM_WSA_LAYER_ID,
    BLM_ROW_URL,
    BLM_ROW_NSO_LAYER_ID,
    GRSG_HABITAT_URL,
    GRSG_HABITAT_LAYER_ID,
    SAGEBRUSH_FOCAL_URL,
    SAGEBRUSH_FOCAL_LAYER_ID,
    WILD_HORSE_HMA_URL,
    WILD_HORSE_HMA_LAYER_ID,
    NATIONAL_TRAILS_URL,
    NATIONAL_TRAILS_LAYER_ID,
    FIRE_PERIMETERS_URL,
    FIRE_PERIMETERS_LAYER_ID,
    LWCF_URL,
    LWCF_LAYER_ID,
    EIS_BOUNDARIES_URL,
    EIS_BOUNDARIES_LAYER_ID,
    USFS_FORESTS_URL,
    USFS_FORESTS_LAYER_ID,
    USFS_ROADLESS_AREAS_URL,
    USFS_ROADLESS_AREAS_LAYER_ID,
    NPS_BOUNDARIES_URL,
    NPS_BOUNDARIES_LAYER_ID,
    PADUS_URL,
    PADUS_LAYER_ID,
)
from src.core.fips_utils import STATE_FIPS_TO_NAME, STATE_FIPS_TO_ABBR

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CollectionResult:
    """Collected map layers plus explicit per-layer availability status."""

    layers: Dict[str, Dict]
    statuses: Dict[str, Dict[str, Any]]
    project_geometry: Optional[Dict] = None

    @property
    def warnings(self) -> List[str]:
        return [warning for status in self.statuses.values() for warning in status.get("warnings", [])]


def _query_arcgis_features(
    url: str,
    params: Dict,
    *,
    timeout: float,
    max_features: int = 4500,
) -> ArcGISFeatureQueryResult:
    """Route a Map Composer query through the shared, completeness-aware helper."""

    suffix = "/query"
    if not url.endswith(suffix):
        raise ValueError(f"ArcGIS feature query URL must end with {suffix!r}: {url}")

    layer_url = url[: -len(suffix)]
    service_url, layer_id_text = layer_url.rsplit("/", 1)
    try:
        layer_id = int(layer_id_text)
    except ValueError as exc:
        raise ValueError(f"ArcGIS feature query URL has a non-numeric layer id: {url}") from exc

    geometry = params.get("geometry")
    if isinstance(geometry, str):
        try:
            geometry = json.loads(geometry)
        except json.JSONDecodeError as exc:
            raise ValueError("ArcGIS query geometry must be a JSON object") from exc
    if not isinstance(geometry, dict):
        raise ValueError("ArcGIS query geometry must be an object")

    managed_params = {
        "geometry",
        "geometryType",
        "inSR",
        "spatialRel",
        "returnGeometry",
        "outFields",
        "outSR",
        "f",
        "resultOffset",
        "resultRecordCount",
    }
    extra_params = {key: value for key, value in params.items() if key not in managed_params}

    return ArcGISService.query_features(
        service_url,
        layer_id,
        geometry,
        out_fields=str(params.get("outFields", "*")),
        return_geometry=bool(params.get("returnGeometry", False)),
        timeout=timeout,
        page_size=int(params.get("resultRecordCount", ArcGISService.DEFAULT_PAGE_SIZE)),
        max_features=max_features,
        simplify_geometry=False,
        out_sr=int(params["outSR"]) if params.get("outSR") is not None else None,
        geometry_type=str(params.get("geometryType", "esriGeometryPolygon")),
        in_sr=int(params.get("inSR", 4326)),
        spatial_relation=str(params.get("spatialRel", "esriSpatialRelIntersects")),
        extra_params=extra_params,
    )


def _feature_collection(
    features: List[Dict],
    *query_results: ArcGISFeatureQueryResult,
    warnings: Optional[List[str]] = None,
) -> Dict:
    """Build a FeatureCollection while preserving partial-query warnings."""

    combined_warnings = list(warnings or [])
    for query_result in query_results:
        combined_warnings.extend(query_result.warnings)
    valid_features = [
        feature
        for feature in features
        if isinstance(feature, dict)
        and isinstance(feature.get("geometry"), dict)
        and feature["geometry"].get("type")
        and feature["geometry"].get("coordinates")
    ]
    dropped_count = len(features) - len(valid_features)
    if dropped_count:
        combined_warnings.append(f"Dropped {dropped_count} feature(s) whose upstream geometry was empty or malformed.")
    return {
        "type": "FeatureCollection",
        "features": valid_features,
        "status": "partial" if combined_warnings else ("ok" if valid_features else "empty"),
        "warnings": combined_warnings,
    }


def _failed_feature_collection(message: str) -> Dict:
    """Represent an unavailable layer without conflating it with a true no-hit."""

    return {
        "type": "FeatureCollection",
        "features": [],
        "status": "failed",
        "warnings": [message],
    }


def _format_wsa_rod_date(value: Any) -> Optional[str]:
    """Format an ArcGIS epoch-millisecond WSA ROD date when it is usable."""

    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        parsed = datetime.fromtimestamp(float(value) / 1000, tz=timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        return None
    if (parsed.year, parsed.month, parsed.day) == (9999, 9, 9):
        return None
    return parsed.date().isoformat()


# Server-side geometry simplification tolerance in decimal degrees.
# 0.002 ~= 200 m at mid-latitudes, finer than typical browser pixel
# resolution for 25-100 mile ROI buffers. Reduces GRSG fetch from
# 213s/124MB to 5.5s/10MB with no visible quality change.
DEFAULT_OUTPUT_OFFSET_DEG = 0.002


# =============================================================================
# LAYER CONFIGURATION
# =============================================================================
# Centralized configuration for all environmental data layers

NHD_BASE_URL = "https://hydro.nationalmap.gov/arcgis/rest/services/nhd/MapServer"

# NHD layer configuration - defines all NHD layer types in one place
NHD_LAYER_CONFIG = {
    "nhd_lakes": {
        "layer_id": 12,  # Waterbody layer
        "where_clause": "FTYPE = 390",  # Lake/Pond
        "geometry_type": "esriGeometryPolygon",
        "out_fields": "GNIS_NAME,PERMANENT_IDENTIFIER,AREASQKM,FCODE,ELEVATION",
        "waterbody_type": "Lake/Pond",
        "unnamed_prefix": "Unnamed Lake",
    },
    "nhd_reservoirs": {
        "layer_id": 12,
        "where_clause": "FTYPE = 436",  # Reservoir
        "geometry_type": "esriGeometryPolygon",
        "out_fields": "GNIS_NAME,PERMANENT_IDENTIFIER,AREASQKM,FCODE,ELEVATION",
        "waterbody_type": "Reservoir",
        "unnamed_prefix": "Unnamed Reservoir",
    },
    "nhd_estuaries": {
        "layer_id": 12,
        "where_clause": "FTYPE = 493",  # Estuary
        "geometry_type": "esriGeometryPolygon",
        "out_fields": "GNIS_NAME,PERMANENT_IDENTIFIER,AREASQKM,ELEVATION",
        "waterbody_type": "Estuary",
        "unnamed_prefix": "Unnamed Estuary",
    },
    "nhd_ice_masses": {
        "layer_id": 12,
        "where_clause": "FTYPE = 378",  # Ice Mass
        "geometry_type": "esriGeometryPolygon",
        "out_fields": "GNIS_NAME,PERMANENT_IDENTIFIER,AREASQKM,ELEVATION",
        "waterbody_type": "Ice Mass/Glacier",
        "unnamed_prefix": "Unnamed Glacier",
    },
    "nhd_perennial_streams": {
        "layer_id": 6,  # Flowline layer
        "where_clause": "FTYPE = 460 AND FCODE IN (46000, 46006)",  # Perennial streams
        "geometry_type": "esriGeometryPolyline",
        "out_fields": "GNIS_NAME,LENGTHKM,FLOWDIR,REACHCODE",
        "waterbody_type": "Perennial Stream",
        "unnamed_prefix": "Unnamed Stream",
    },
    "nhd_stream_areas": {
        "layer_id": 9,  # Area layer
        "where_clause": "FTYPE = 460 AND FCODE IN (46000, 46006)",  # Perennial stream areas
        "geometry_type": "esriGeometryPolygon",
        "out_fields": "GNIS_NAME,AREASQKM,FCODE",
        "waterbody_type": "River/Stream Area",
        "unnamed_prefix": "Unnamed Stream Area",
    },
    "nhd_infrastructure": {
        "layer_id": 0,  # Point layer
        "where_clause": "FTYPE IN (343, 450, 458, 485, 488)",  # Dams, springs, gages, etc.
        "geometry_type": "esriGeometryPoint",
        "out_fields": "GNIS_NAME,FTYPE,FCODE,PERMANENT_IDENTIFIER",
        "waterbody_type": "Infrastructure",
        "unnamed_prefix": "Unnamed",
        # Infrastructure type mapping
        "ftype_names": {
            343: "Dam/Weir",
            450: "Spring/Seep",
            458: "Stream Gage",
            485: "Water Intake/Outfall",
            488: "Well",
        },
    },
}

# Tribal lands layer configuration imported from src.core.constants

# Wetland regional supplement URLs
WETLAND_SUPPLEMENT_URLS = {
    "Arid West": "https://usace.contentdm.oclc.org/digital/collection/p266001coll1/id/4597/",
    "Great Plains": "https://usace.contentdm.oclc.org/digital/collection/p266001coll1/id/4636/",
    "Western Mountains, Valleys, and Coast": "https://usace.contentdm.oclc.org/digital/collection/p266001coll1/id/7591/",
    "Atlantic and Gulf Coastal Plain": "https://usace.contentdm.oclc.org/digital/collection/p266001coll1/id/7605/",
    "Midwest": "https://usace.contentdm.oclc.org/digital/collection/p266001coll1/id/7617/",
    "Northcentral and Northeast": "https://usace.contentdm.oclc.org/digital/collection/p266001coll1/id/7632/",
    "Alaska": "https://usace.contentdm.oclc.org/digital/collection/p266001coll1/id/7645/",
    "Caribbean Islands": "https://usace.contentdm.oclc.org/digital/collection/p266001coll1/id/7650/",
    "Hawaii and Pacific Islands": "https://usace.contentdm.oclc.org/digital/collection/p266001coll1/id/7655/",
}

# Wetland region code to name mapping
WETLAND_REGION_CODES = {
    "AW": "Arid West",
    "GP": "Great Plains",
    "WMVC": "Western Mountains, Valleys, and Coast",
    "AGCP": "Atlantic and Gulf Coastal Plain",
    "MW": "Midwest",
    "NCNE": "Northcentral and Northeast",
    "AK": "Alaska",
    "CB": "Caribbean Islands",
    "HPI": "Hawaii and Pacific Islands",
}

# Default layers to collect when none specified
DEFAULT_LAYERS = [
    "roi",
    "tribal_lands",
    "counties",
    "critical_habitat",
    "wildlife_refuges",
    "usace_districts",
    "wetland_regions",
    "wetland_subregions",
    "nhd_lakes",
    "nhd_reservoirs",
    "nhd_estuaries",
    "nhd_ice_masses",
    "nhd_perennial_streams",
    "nhd_stream_areas",
    "nhd_infrastructure",
    "federal_lands",
    "usfs_forests",
    "usfs_roadless_areas",
    "nps_boundaries",
    "blm_managed_lands",
    "blm_land_use_plans",
    "blm_plans_in_progress",
    "blm_wilderness_study_areas",
    "blm_national_monuments",
    "blm_rights_of_way",
    "grsg_habitat",
    "sagebrush_focal_areas",
    "wild_horse_hma",
    "national_trails",
    "fire_perimeters",
    "lwcf_lands",
    "eis_boundaries",
]

LAYER_PROFILES = {
    "screening": [
        "roi",
        "tribal_lands",
        "counties",
        "critical_habitat",
        "wildlife_refuges",
        "usace_districts",
        "wetland_regions",
        "nhd_perennial_streams",
        "federal_lands",
        "usfs_forests",
        "nps_boundaries",
        "blm_land_use_plans",
    ],
    "biological": [
        "roi",
        "critical_habitat",
        "wildlife_refuges",
        "grsg_habitat",
        "sagebrush_focal_areas",
        "wild_horse_hma",
    ],
    "water": [
        "roi",
        "usace_districts",
        "wetland_regions",
        "wetland_subregions",
        "nhd_lakes",
        "nhd_reservoirs",
        "nhd_estuaries",
        "nhd_ice_masses",
        "nhd_perennial_streams",
        "nhd_stream_areas",
        "nhd_infrastructure",
    ],
    "lands": [
        "roi",
        "federal_lands",
        "usfs_forests",
        "usfs_roadless_areas",
        "nps_boundaries",
        "blm_managed_lands",
        "blm_land_use_plans",
        "blm_plans_in_progress",
        "blm_wilderness_study_areas",
        "blm_national_monuments",
        "blm_rights_of_way",
        "national_trails",
        "lwcf_lands",
        "eis_boundaries",
    ],
    "geothermal": [
        "roi",
        "counties",
        "tribal_lands",
        "blm_managed_lands",
        "federal_lands",
        "usfs_forests",
        "blm_land_use_plans",
        "blm_plans_in_progress",
        "blm_wilderness_study_areas",
        "blm_national_monuments",
        "blm_rights_of_way",
        "critical_habitat",
        "wildlife_refuges",
        "grsg_habitat",
        "sagebrush_focal_areas",
        "wild_horse_hma",
        "usace_districts",
        "wetland_regions",
        "nhd_perennial_streams",
        "nhd_infrastructure",
        "eis_boundaries",
    ],
    "full": DEFAULT_LAYERS,
}


# =============================================================================
# GEOMETRY CONVERSION UTILITIES
# =============================================================================


def esri_to_geojson_geometry(esri_geometry: Dict, geometry_type: str) -> Optional[Dict]:
    """
    Convert ESRI JSON geometry to GeoJSON geometry.

    Args:
        esri_geometry: ESRI JSON geometry object
        geometry_type: ESRI type (esriGeometryPoint, esriGeometryPolygon, esriGeometryPolyline)

    Returns:
        GeoJSON geometry object or None if conversion fails. Polygon conversion
        is all-or-nothing: an unusable ring invalidates the entire feature so
        downstream completeness accounting cannot mistake a lost hole or part
        for a complete boundary.
    """
    if not isinstance(esri_geometry, dict):
        return None

    if geometry_type == "esriGeometryPoint":
        return {"type": "Point", "coordinates": [esri_geometry.get("x"), esri_geometry.get("y")]}

    elif geometry_type == "esriGeometryPolygon":
        rings = esri_geometry.get("rings", [])
        if not isinstance(rings, list) or not rings:
            return None

        closed_rings = []
        ring_polygons = []
        for ring in rings:
            if not isinstance(ring, list) or len(ring) < 3:
                return None
            for vertex in ring:
                if (
                    not isinstance(vertex, (list, tuple))
                    or len(vertex) not in (2, 3)
                    or any(
                        isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
                        for value in vertex
                    )
                ):
                    return None
            closed_ring = list(ring)
            if closed_ring[0] != closed_ring[-1]:
                closed_ring.append(closed_ring[0])
            if len(closed_ring) < 4:
                return None
            try:
                ring_polygon = shape({"type": "Polygon", "coordinates": [closed_ring]})
            except Exception:
                return None
            if (
                ring_polygon.is_empty
                or not ring_polygon.is_valid
                or not math.isfinite(ring_polygon.area)
                or ring_polygon.area == 0
            ):
                return None
            closed_rings.append(closed_ring)
            ring_polygons.append(ring_polygon)

        if not closed_rings:
            return None

        # ESRI stores exterior and interior rings in one flat list. Build a
        # containment tree instead of treating every ring after the first as a
        # hole; that preserves disjoint exterior parts as a MultiPolygon.
        parents: List[Optional[int]] = []
        for index, polygon in enumerate(ring_polygons):
            containers = [
                candidate_index
                for candidate_index, candidate in enumerate(ring_polygons)
                if candidate_index != index and candidate.area > polygon.area and candidate.covers(polygon)
            ]
            parents.append(
                min(containers, key=lambda candidate_index: ring_polygons[candidate_index].area, default=None)
            )

        depths: List[int] = []
        for index in range(len(closed_rings)):
            depth = 0
            parent = parents[index]
            visited = {index}
            while parent is not None and parent not in visited:
                visited.add(parent)
                depth += 1
                parent = parents[parent]
            depths.append(depth)

        polygons = []
        for index, ring in enumerate(closed_rings):
            if depths[index] % 2:
                continue
            holes = [
                closed_rings[hole_index]
                for hole_index, parent in enumerate(parents)
                if parent == index and depths[hole_index] % 2 == 1
            ]
            polygons.append([ring, *holes])

        if not polygons:
            return None
        geometry = (
            {"type": "Polygon", "coordinates": polygons[0]}
            if len(polygons) == 1
            else {"type": "MultiPolygon", "coordinates": polygons}
        )
        # Individually valid rings can still form invalid overlapping parts or
        # holes. Do not repair them or silently change the mapped boundary.
        try:
            polygon = shape(geometry)
            return geometry if polygon.is_valid and not polygon.is_empty else None
        except Exception:
            return None

    elif geometry_type == "esriGeometryPolyline":
        paths = esri_geometry.get("paths", [])
        if not paths:
            return None
        if len(paths) == 1:
            return {"type": "LineString", "coordinates": paths[0]}
        return {"type": "MultiLineString", "coordinates": paths}

    return None


# =============================================================================
# ROI LAYER
# =============================================================================


def get_roi_geojson(latitude: float, longitude: float, buffer_miles: float) -> Dict:
    """
    Get ROI as GeoJSON FeatureCollection (point + buffer polygon).

    Args:
        latitude: Latitude in decimal degrees
        longitude: Longitude in decimal degrees
        buffer_miles: Buffer distance in miles

    Returns:
        GeoJSON FeatureCollection with project location and buffer
    """
    buffer_geom = ArcGISService.create_roi_buffer(latitude, longitude, buffer_miles)
    buffer_geojson = esri_to_geojson_geometry(buffer_geom, "esriGeometryPolygon")

    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
                "properties": {
                    "type": "Project Location",
                    "latitude": latitude,
                    "longitude": longitude,
                },
            },
            {
                "type": "Feature",
                "geometry": buffer_geojson,
                "properties": {
                    "type": "Region of Interest",
                    "buffer_miles": buffer_miles,
                    "center_lat": latitude,
                    "center_lon": longitude,
                },
            },
        ],
    }


# =============================================================================
# TRIBAL LANDS LAYER
# =============================================================================


def get_tribal_lands_geojson(buffer_geometry: Dict) -> Dict:
    """
    Get tribal lands with full polygon geometries as GeoJSON.

    Args:
        buffer_geometry: ESRI JSON polygon geometry (ROI buffer)

    Returns:
        GeoJSON FeatureCollection with tribal land polygons
    """
    features = []
    warnings = []
    query_results = []
    successful_layers = 0

    for layer_id, layer_type in TRIBAL_LAYERS.items():
        url = f"{TIGERWEB_AIANNHA_URL}/{layer_id}/query"
        params = {
            "geometry": json.dumps(buffer_geometry),
            "geometryType": "esriGeometryPolygon",
            "inSR": 4326,
            "spatialRel": "esriSpatialRelIntersects",
            "returnGeometry": True,
            "outSR": 4326,
            "maxAllowableOffset": DEFAULT_OUTPUT_OFFSET_DEG,
            "outFields": "NAME,GEOID,AREALAND",
            "f": "json",
        }

        try:
            query_result = _query_arcgis_features(url, params, timeout=15)
            query_results.append(query_result)
            successful_layers += 1

            for feature in query_result.features:
                attrs = feature.get("attributes", {})
                geom = feature.get("geometry")

                if geom:
                    geojson_geom = esri_to_geojson_geometry(geom, "esriGeometryPolygon")
                    area_land = attrs.get("AREALAND")
                    try:
                        area_sq_mi = float(area_land) / SQ_METERS_TO_SQ_MILES if area_land else None
                    except (TypeError, ValueError):
                        area_sq_mi = None

                    features.append(
                        {
                            "type": "Feature",
                            "geometry": geojson_geom,
                            "properties": {
                                "name": attrs.get("NAME", "Unknown"),
                                "type": layer_type,
                                "geoid": attrs.get("GEOID", ""),
                                "area_sq_mi": round(area_sq_mi, 2) if area_sq_mi else None,
                                "layer": "tribal_lands",
                            },
                        }
                    )
        except Exception as exc:
            warning = f"Census TIGERweb {layer_type} layer request failed: {exc}"
            logger.warning(warning)
            warnings.append(warning)

    if successful_layers == 0:
        return _failed_feature_collection(
            "No Census TIGERweb tribal geography layers were available; results are unavailable, not a no-hit."
        )

    return _feature_collection(features, *query_results, warnings=warnings)


# =============================================================================
# COUNTIES LAYER
# =============================================================================


def _enrich_counties_with_species(
    county_features: List[Dict], min_year: int = 2015, max_records: int = 1000
) -> List[str]:
    """
    Enrich county features with GBIF species data in-place using spatial filtering.

    OPTIMIZED:
    - Single query with all IUCN categories (4x fewer API calls)
    - Parallel county queries with asyncio (5-7x faster for multi-county ROIs)

    Args:
        county_features: List of county GeoJSON features to enrich
        min_year: Minimum observation year for GBIF queries
        max_records: Maximum records to retrieve per county

    Returns:
        Warnings for counties whose optional enrichment was unavailable.
    """
    import asyncio
    from src.apis.gbif_api import (
        _gbif_paginated_query,
        _deduplicate_to_species_list,
        IUCN_CATEGORIES_LIST,
        MAX_CONCURRENT_REQUESTS,
        GBIF_RATE_LIMIT_SECONDS,
    )

    async def _query_single_county(idx: int, feature: Dict, semaphore: asyncio.Semaphore) -> Dict:
        """Query GBIF for a single county asynchronously."""
        async with semaphore:
            props = feature.get("properties", {})
            county_basename = props.get("basename", "").strip()
            state_fips = props.get("state", "")
            state_name = STATE_FIPS_TO_NAME.get(state_fips, "")
            state_abbr = STATE_FIPS_TO_ABBR.get(state_fips, "")
            geometry = feature.get("geometry")

            result = {
                "feature": feature,
                "species_count": 0,
                "species_list": [],
                "total_observations": 0,
                "warning": None,
            }

            if not county_basename or not state_name or not geometry:
                result["warning"] = f"County {idx} lacked the name, state, or geometry needed for GBIF enrichment."
                logger.warning(result["warning"])
                return result

            logger.info(f"[{idx}/{len(county_features)}] Querying species for {county_basename} County, {state_abbr}")

            try:
                county_shape = shape(geometry)
                bounds = county_shape.bounds
                buffer_deg = 0.01

                min_lon, min_lat, max_lon, max_lat = bounds
                params = {
                    "decimalLatitude": f"{min_lat - buffer_deg},{max_lat + buffer_deg}",
                    "decimalLongitude": f"{min_lon - buffer_deg},{max_lon + buffer_deg}",
                    "country": "US",
                    "hasCoordinate": "true",
                    "hasGeospatialIssue": "false",
                    "occurrenceStatus": "PRESENT",
                    "year": f"{min_year},{datetime.now(timezone.utc).year}",
                    "limit": 300,
                    "iucnRedListCategory": IUCN_CATEGORIES_LIST,
                }

                # Run sync query in thread pool
                all_occurrences = await asyncio.to_thread(_gbif_paginated_query, params, max_records)

                await asyncio.sleep(GBIF_RATE_LIMIT_SECONDS)

                if not all_occurrences:
                    logger.info("    No species found in bounding box")
                    return result

                # Spatially filter to county polygon
                filtered_occurrences = [
                    occ
                    for occ in all_occurrences
                    if occ.get("latitude") is not None
                    and occ.get("longitude") is not None
                    and (
                        county_shape.contains(ShapelyPoint(occ["longitude"], occ["latitude"]))
                        or county_shape.intersects(ShapelyPoint(occ["longitude"], occ["latitude"]))
                    )
                ]

                if not filtered_occurrences:
                    logger.info("    No species within county boundaries")
                    return result

                species_list = _deduplicate_to_species_list(filtered_occurrences, include_date_range=False)

                result["species_count"] = len(species_list)
                result["species_list"] = species_list
                result["total_observations"] = len(filtered_occurrences)

                logger.info(
                    f"    Found {len(species_list)} species ({len(filtered_occurrences)} observations within county)"
                )

            except Exception as exc:
                result["warning"] = f"GBIF enrichment failed for {county_basename} County: {exc}"
                logger.error(result["warning"])

            return result

    async def _query_all_counties():
        """Query all counties in parallel."""
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
        tasks = [_query_single_county(idx, feature, semaphore) for idx, feature in enumerate(county_features, 1)]
        return await asyncio.gather(*tasks, return_exceptions=True)

    # Run parallel queries - handle both sync and async contexts
    logger.info(
        f"Querying GBIF for {len(county_features)} counties in parallel (max {MAX_CONCURRENT_REQUESTS} concurrent)"
    )

    try:
        # Check if already in async context (e.g., MCP server)
        asyncio.get_running_loop()
        # Already in async context - run in thread pool to avoid blocking
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(asyncio.run, _query_all_counties())
            results = future.result()
    except RuntimeError:
        # No running event loop - safe to use asyncio.run()
        results = asyncio.run(_query_all_counties())

    warnings: List[str] = []
    # Apply results to features in-place
    for result in results:
        if isinstance(result, Exception):
            warning = f"GBIF county enrichment task failed: {result}"
            logger.error(warning)
            warnings.append(warning)
            continue

        feature = result.get("feature")
        if feature:
            props = feature.get("properties", {})
            props["species_count"] = result["species_count"]
            props["species_list"] = result["species_list"]
            props["total_observations"] = result["total_observations"]
        if result.get("warning"):
            warnings.append(result["warning"])

    return warnings


def get_counties_geojson(
    buffer_geometry: Dict,
    include_species_data: bool = False,
    latitude: float = None,
    longitude: float = None,
    buffer_miles: float = None,
) -> Dict:
    """
    Get county boundaries with full polygon geometries as GeoJSON.

    Args:
        buffer_geometry: ESRI JSON polygon geometry (ROI buffer)
        include_species_data: If True, enrich with GBIF species data
        latitude: Center latitude (required if include_species_data=True)
        longitude: Center longitude (required if include_species_data=True)
        buffer_miles: Buffer distance (required if include_species_data=True)

    Returns:
        GeoJSON FeatureCollection with county polygons
    """
    tigerweb_url = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/tigerWMS_Current/MapServer"
    county_layer_id = 82

    url = f"{tigerweb_url}/{county_layer_id}/query"
    out_fields = "NAME,STATE,BASENAME,GEOID" if include_species_data else "NAME,STATE,GEOID"

    params = {
        "geometry": json.dumps(buffer_geometry),
        "geometryType": "esriGeometryPolygon",
        "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "returnGeometry": True,
        "outSR": 4326,
        "maxAllowableOffset": DEFAULT_OUTPUT_OFFSET_DEG,
        "outFields": out_fields,
        "f": "json",
    }

    query_result = _query_arcgis_features(url, params, timeout=30)

    features = []
    for feature in query_result.features:
        attrs = feature.get("attributes", {})
        geom = feature.get("geometry")

        if geom:
            geojson_geom = esri_to_geojson_geometry(geom, "esriGeometryPolygon")
            properties = {
                "name": attrs.get("NAME", "Unknown"),
                "state": attrs.get("STATE", ""),
                "fips": attrs.get("GEOID", ""),
                "layer": "counties",
            }
            if include_species_data:
                properties["basename"] = attrs.get("BASENAME", "")

            features.append(
                {
                    "type": "Feature",
                    "geometry": geojson_geom,
                    "properties": properties,
                }
            )

    warnings: List[str] = []
    if include_species_data and features:
        if latitude is None or longitude is None or buffer_miles is None:
            warning = "Cannot enrich counties without latitude, longitude, and buffer distance."
            logger.warning(warning)
            warnings.append(warning)
        else:
            logger.info("Enriching %s counties with GBIF species data", len(features))
            warnings.extend(_enrich_counties_with_species(features))

    return _feature_collection(features, query_result, warnings=warnings)


# =============================================================================
# CRITICAL HABITAT LAYER
# =============================================================================


def get_critical_habitat_geojson(
    latitude: float,
    longitude: float,
    radius_miles: float,
    buffer_geometry: Dict = None,
) -> Dict:
    """
    Get critical habitat designations with geometries as GeoJSON.

    Args:
        latitude: Center latitude
        longitude: Center longitude
        radius_miles: Search radius in miles
        buffer_geometry: Optional ESRI JSON polygon for precise filtering

    Returns:
        GeoJSON FeatureCollection with critical habitat polygons
    """
    crithab_url = (
        "https://services.arcgis.com/QVENGdaPbd4LUkLV/arcgis/rest/services/USFWS_Critical_Habitat/FeatureServer"
    )

    query_geometry = buffer_geometry or ArcGISService.create_roi_buffer(latitude, longitude, radius_miles)

    url = f"{crithab_url}/0/query"
    params = {
        "geometry": json.dumps(query_geometry),
        "geometryType": "esriGeometryPolygon",
        "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "returnGeometry": True,
        "outSR": 4326,
        "maxAllowableOffset": DEFAULT_OUTPUT_OFFSET_DEG,
        "outFields": "COMNAME,SCINAME,STATUS",
        "f": "json",
    }

    try:
        query_result = _query_arcgis_features(url, params, timeout=30)

        features = []
        for feature in query_result.features:
            attrs = feature.get("attributes", {})
            geom = feature.get("geometry")

            if geom:
                geojson_geom = esri_to_geojson_geometry(geom, "esriGeometryPolygon")
                features.append(
                    {
                        "type": "Feature",
                        "geometry": geojson_geom,
                        "properties": {
                            "common_name": attrs.get("COMNAME", "Unknown"),
                            "scientific_name": attrs.get("SCINAME", ""),
                            "status": attrs.get("STATUS", ""),
                            "layer": "critical_habitat",
                        },
                    }
                )

        return _feature_collection(features, query_result)

    except Exception as exc:
        return _failed_feature_collection(f"USFWS critical habitat request failed: {exc}")


# =============================================================================
# WILDLIFE REFUGES LAYER
# =============================================================================


def get_wildlife_refuges_geojson(buffer_geometry: Dict) -> Dict:
    """
    Get National Wildlife Refuge System boundaries as GeoJSON.

    Args:
        buffer_geometry: ESRI JSON polygon geometry (ROI buffer)

    Returns:
        GeoJSON FeatureCollection with refuge boundary polygons
    """
    nwrs_url = "https://services.arcgis.com/QVENGdaPbd4LUkLV/arcgis/rest/services/National_Wildlife_Refuge_System_Boundaries/FeatureServer"

    url = f"{nwrs_url}/0/query"
    params = {
        "geometry": json.dumps(buffer_geometry),
        "geometryType": "esriGeometryPolygon",
        "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "returnGeometry": True,
        "outSR": 4326,
        "maxAllowableOffset": DEFAULT_OUTPUT_OFFSET_DEG,
        "outFields": "ORGNAME,RSL_TYPE,FWSREGION",
        "f": "json",
    }

    try:
        query_result = _query_arcgis_features(url, params, timeout=60)

        features = []
        for feature in query_result.features:
            attrs = feature.get("attributes", {})
            geom = feature.get("geometry")

            if geom:
                geojson_geom = esri_to_geojson_geometry(geom, "esriGeometryPolygon")
                features.append(
                    {
                        "type": "Feature",
                        "geometry": geojson_geom,
                        "properties": {
                            "name": attrs.get("ORGNAME", "Unknown"),
                            "type": attrs.get("RSL_TYPE", ""),
                            "fws_region": attrs.get("FWSREGION", ""),
                            "layer": "wildlife_refuges",
                        },
                    }
                )

        return _feature_collection(features, query_result)

    except Exception as exc:
        return _failed_feature_collection(f"USFWS refuge boundary request failed: {exc}")


# =============================================================================
# USACE LAYERS
# =============================================================================


def get_usace_districts_geojson(buffer_geometry: Dict) -> Dict:
    """
    Get USACE regulatory district boundaries as GeoJSON.

    Args:
        buffer_geometry: ESRI JSON polygon geometry (ROI buffer)

    Returns:
        GeoJSON FeatureCollection with district boundary polygons
    """
    usace_url = "https://services7.arcgis.com/n1YM8pTrFmm7L4hs/ArcGIS/rest/services/usace_cw_districts/FeatureServer"
    simplified_geom = ArcGISService.simplify_polygon_geometry(buffer_geometry)

    url = f"{usace_url}/0/query"
    params = {
        "geometry": json.dumps(simplified_geom),
        "geometryType": "esriGeometryPolygon",
        "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "returnGeometry": True,
        "outSR": 4326,
        "maxAllowableOffset": DEFAULT_OUTPUT_OFFSET_DEG,
        "outFields": "*",
        "f": "json",
    }

    try:
        query_result = _query_arcgis_features(url, params, timeout=30)

        features = []
        seen_districts = set()

        for feature in query_result.features:
            attrs = feature.get("attributes", {})
            geom = feature.get("geometry")

            district_name = attrs.get(
                "ERO_FORMALNAME", attrs.get("ENGINEER_REPORTING_ORG_NAME", attrs.get("DISTRICT", "Unknown"))
            )

            if district_name in seen_districts:
                continue
            seen_districts.add(district_name)

            if geom:
                geojson_geom = esri_to_geojson_geometry(geom, "esriGeometryPolygon")
                features.append(
                    {
                        "type": "Feature",
                        "geometry": geojson_geom,
                        "properties": {
                            "name": district_name,
                            "abbreviation": attrs.get(
                                "DIST_ABBR", attrs.get("USACE_DISTRICT_CODE", attrs.get("AGENCY_CODE", ""))
                            ),
                            "division_name": attrs.get("REPORTS_TO", ""),
                            "division_abbreviation": attrs.get("USACE_DIVISION_CODE", ""),
                            "website_url": attrs.get("WEB_ADDR", ""),
                            "phone": attrs.get("DISTRICT_N", ""),
                            "address": attrs.get("DISTRICT_A", ""),
                            "layer": "usace_districts",
                        },
                    }
                )

        return _feature_collection(features, query_result)

    except Exception as exc:
        return _failed_feature_collection(f"USACE regulatory district request failed: {exc}")


def get_wetland_regions_geojson(buffer_geometry: Dict) -> Dict:
    """
    Get wetland delineation regions as GeoJSON.

    Args:
        buffer_geometry: ESRI JSON polygon geometry (ROI buffer)

    Returns:
        GeoJSON FeatureCollection with wetland region polygons
    """
    wetland_url = "https://services7.arcgis.com/n1YM8pTrFmm7L4hs/ArcGIS/rest/services/coe_wetland_regions/FeatureServer"
    simplified_geom = ArcGISService.simplify_polygon_geometry(buffer_geometry)

    url = f"{wetland_url}/0/query"
    params = {
        "geometry": json.dumps(simplified_geom),
        "geometryType": "esriGeometryPolygon",
        "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "returnGeometry": True,
        "outSR": 4326,
        "maxAllowableOffset": DEFAULT_OUTPUT_OFFSET_DEG,
        "outFields": "*",
        "f": "json",
    }

    try:
        query_result = _query_arcgis_features(url, params, timeout=30)

        features = []
        seen_regions = set()

        for feature in query_result.features:
            attrs = feature.get("attributes", {})
            geom = feature.get("geometry")

            region_name = attrs.get("REGION", "Unknown")
            if region_name in seen_regions:
                continue
            seen_regions.add(region_name)

            if geom:
                geojson_geom = esri_to_geojson_geometry(geom, "esriGeometryPolygon")
                features.append(
                    {
                        "type": "Feature",
                        "geometry": geojson_geom,
                        "properties": {
                            "name": region_name,
                            "mlra_name": attrs.get("MLRA_NAME", ""),
                            "lrr_name": attrs.get("LRR_NAME", ""),
                            "supplement_url": WETLAND_SUPPLEMENT_URLS.get(region_name, ""),
                            "layer": "wetland_regions",
                        },
                    }
                )

        return _feature_collection(features, query_result)

    except Exception as exc:
        return _failed_feature_collection(f"USACE wetland region request failed: {exc}")


def get_wetland_subregions_geojson(buffer_geometry: Dict) -> Dict:
    """
    Get wetland subregion classifications as GeoJSON.

    Args:
        buffer_geometry: ESRI JSON polygon geometry (ROI buffer)

    Returns:
        GeoJSON FeatureCollection with wetland subregion polygons
    """
    subregion_url = (
        "https://services7.arcgis.com/n1YM8pTrFmm7L4hs/ArcGIS/rest/services/coe_wetland_subregions/FeatureServer"
    )
    simplified_geom = ArcGISService.simplify_polygon_geometry(buffer_geometry)

    url = f"{subregion_url}/0/query"
    params = {
        "geometry": json.dumps(simplified_geom),
        "geometryType": "esriGeometryPolygon",
        "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "returnGeometry": True,
        "outSR": 4326,
        "maxAllowableOffset": DEFAULT_OUTPUT_OFFSET_DEG,
        "outFields": "*",
        "f": "json",
    }

    try:
        query_result = _query_arcgis_features(url, params, timeout=30)

        features = []
        seen_subregions = set()

        for feature in query_result.features:
            attrs = feature.get("attributes", {})
            geom = feature.get("geometry")

            subregion_name = attrs.get("ADS_SUB_NM", attrs.get("MLRA_NAME", "Unknown"))
            if subregion_name in seen_subregions:
                continue
            seen_subregions.add(subregion_name)

            region_code = attrs.get("ADS_REGSUP", "")
            parent_region = WETLAND_REGION_CODES.get(region_code, region_code)

            if geom:
                geojson_geom = esri_to_geojson_geometry(geom, "esriGeometryPolygon")
                features.append(
                    {
                        "type": "Feature",
                        "geometry": geojson_geom,
                        "properties": {
                            "name": subregion_name,
                            "subregion_code": attrs.get("MLRARSYM", ""),
                            "parent_region": parent_region,
                            "mlra_name": attrs.get("MLRA_NAME", ""),
                            "lrr_name": attrs.get("LRR_NAME", ""),
                            "layer": "wetland_subregions",
                        },
                    }
                )

        return _feature_collection(features, query_result)

    except Exception as exc:
        return _failed_feature_collection(f"USACE wetland subregion request failed: {exc}")


# =============================================================================
# NHD LAYERS (GENERIC FUNCTION)
# =============================================================================


def _get_nhd_layer_geojson(
    layer_key: str,
    latitude: float,
    longitude: float,
    radius_miles: float,
    buffer_geometry: Optional[Dict] = None,
) -> Dict:
    """
    Generic function to fetch any NHD layer as GeoJSON.

    Args:
        layer_key: Key from NHD_LAYER_CONFIG (e.g., "nhd_lakes", "nhd_reservoirs")
        latitude: Center latitude
        longitude: Center longitude
        radius_miles: Search radius in miles

    Returns:
        GeoJSON FeatureCollection with NHD features
    """
    config = NHD_LAYER_CONFIG.get(layer_key)
    if not config:
        return _failed_feature_collection(f"Unknown NHD layer key: {layer_key}")

    query_geometry = buffer_geometry or ArcGISService.create_roi_buffer(latitude, longitude, radius_miles)

    url = f"{NHD_BASE_URL}/{config['layer_id']}/query"
    params = {
        "where": config["where_clause"],
        "geometry": json.dumps(query_geometry),
        "geometryType": "esriGeometryPolygon",
        "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "returnGeometry": True,
        "outSR": 4326,
        "maxAllowableOffset": DEFAULT_OUTPUT_OFFSET_DEG,
        "outFields": config["out_fields"],
        "f": "json",
    }

    try:
        query_result = _query_arcgis_features(url, params, timeout=30, max_features=10000)

        features = []
        for feature in query_result.features:
            attrs = feature.get("attributes", {})
            geom = feature.get("geometry")

            if not geom:
                continue

            geojson_geom = esri_to_geojson_geometry(geom, config["geometry_type"])
            if not geojson_geom:
                continue

            # Build feature name
            gnis_name = attrs.get("GNIS_NAME")
            perm_id = attrs.get("PERMANENT_IDENTIFIER", "")
            if gnis_name:
                name = gnis_name
            elif perm_id:
                name = f"{config['unnamed_prefix']} ({perm_id[:8]})"
            else:
                name = config["unnamed_prefix"]

            # Build properties based on geometry type
            properties = {
                "name": name,
                "layer": layer_key,
            }

            # Polygon-specific properties (area)
            if config["geometry_type"] == "esriGeometryPolygon":
                area_sqkm = attrs.get("AREASQKM", 0)
                area_acres = area_sqkm * 247.105 if area_sqkm else 0
                properties["waterbody_type"] = config["waterbody_type"]
                properties["area_acres"] = round(area_acres, 2) if area_acres else None
                if "ELEVATION" in config["out_fields"]:
                    properties["elevation"] = attrs.get("ELEVATION")
                if "FCODE" in config["out_fields"]:
                    properties["fcode"] = attrs.get("FCODE", "")

            # Polyline-specific properties (length)
            elif config["geometry_type"] == "esriGeometryPolyline":
                length_km = attrs.get("LENGTHKM", 0)
                length_miles = length_km * 0.621371 if length_km else 0
                properties["stream_type"] = config["waterbody_type"]
                properties["length_miles"] = round(length_miles, 2) if length_miles else None
                properties["flow_direction"] = attrs.get("FLOWDIR", "")
                properties["reach_code"] = attrs.get("REACHCODE", "")

            # Point-specific properties (infrastructure)
            elif config["geometry_type"] == "esriGeometryPoint":
                ftype = attrs.get("FTYPE", 0)
                ftype_names = config.get("ftype_names", {})
                properties["infrastructure_type"] = ftype_names.get(ftype, f"Type {ftype}")
                properties["ftype"] = ftype
                properties["fcode"] = attrs.get("FCODE", "")
                properties["permanent_id"] = attrs.get("PERMANENT_IDENTIFIER", "")

            features.append(
                {
                    "type": "Feature",
                    "geometry": geojson_geom,
                    "properties": properties,
                }
            )

        return _feature_collection(features, query_result)

    except Exception as exc:
        return _failed_feature_collection(f"USGS NHD {layer_key} request failed: {exc}")


# Public wrappers for NHD layers (for backward compatibility and clarity)
def get_nhd_lakes_geojson(lat: float, lon: float, radius_miles: float, buffer_geometry: Optional[Dict] = None) -> Dict:
    """Get perennial lakes and ponds from NHD."""
    return _get_nhd_layer_geojson("nhd_lakes", lat, lon, radius_miles, buffer_geometry)


def get_nhd_reservoirs_geojson(
    lat: float, lon: float, radius_miles: float, buffer_geometry: Optional[Dict] = None
) -> Dict:
    """Get reservoirs from NHD."""
    return _get_nhd_layer_geojson("nhd_reservoirs", lat, lon, radius_miles, buffer_geometry)


def get_nhd_estuaries_geojson(
    lat: float, lon: float, radius_miles: float, buffer_geometry: Optional[Dict] = None
) -> Dict:
    """Get estuaries from NHD."""
    return _get_nhd_layer_geojson("nhd_estuaries", lat, lon, radius_miles, buffer_geometry)


def get_nhd_ice_masses_geojson(
    lat: float, lon: float, radius_miles: float, buffer_geometry: Optional[Dict] = None
) -> Dict:
    """Get ice masses/glaciers from NHD."""
    return _get_nhd_layer_geojson("nhd_ice_masses", lat, lon, radius_miles, buffer_geometry)


def get_nhd_perennial_streams_geojson(
    lat: float, lon: float, radius_miles: float, buffer_geometry: Optional[Dict] = None
) -> Dict:
    """Get perennial stream centerlines from NHD."""
    return _get_nhd_layer_geojson("nhd_perennial_streams", lat, lon, radius_miles, buffer_geometry)


def get_nhd_stream_areas_geojson(
    lat: float, lon: float, radius_miles: float, buffer_geometry: Optional[Dict] = None
) -> Dict:
    """Get perennial river/stream area polygons from NHD."""
    return _get_nhd_layer_geojson("nhd_stream_areas", lat, lon, radius_miles, buffer_geometry)


def get_nhd_infrastructure_geojson(
    lat: float, lon: float, radius_miles: float, buffer_geometry: Optional[Dict] = None
) -> Dict:
    """Get NHD infrastructure points (dams, springs, gages, wells, intakes)."""
    return _get_nhd_layer_geojson("nhd_infrastructure", lat, lon, radius_miles, buffer_geometry)


# =============================================================================
# BLM LAYERS
# =============================================================================


def get_blm_managed_lands_geojson(buffer_geometry: Dict) -> Dict:
    """
    Get BLM-managed land boundaries as GeoJSON via PAD-US.

    Queries USGS Protected Areas Database (PAD-US 4.1) filtered to
    BLM-managed protected lands. This is ownership/management screening
    context, not comprehensive cadastral boundaries or mineral ownership.

    Args:
        buffer_geometry: ESRI JSON polygon geometry (ROI buffer)

    Returns:
        GeoJSON FeatureCollection with BLM land management polygons
    """
    simplified_geom = ArcGISService.simplify_polygon_geometry(buffer_geometry)

    url = f"{BLM_MANAGED_LANDS_URL}/{BLM_MANAGED_LANDS_LAYER_ID}/query"
    params = {
        "geometry": json.dumps(simplified_geom),
        "geometryType": "esriGeometryPolygon",
        "where": "Mang_Name = 'BLM'",
        "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "returnGeometry": True,
        "outSR": 4326,
        "maxAllowableOffset": DEFAULT_OUTPUT_OFFSET_DEG,
        "outFields": "Own_Name,Mang_Name,Mang_Type,Unit_Nm,Des_Tp,State_Nm,GIS_Acres,GAP_Sts",
        "f": "json",
    }

    try:
        query_result = _query_arcgis_features(url, params, timeout=30, max_features=4500)

        features = []
        for feature in query_result.features:
            attrs = feature.get("attributes", {})
            geom = feature.get("geometry")

            if geom:
                geojson_geom = esri_to_geojson_geometry(geom, "esriGeometryPolygon")

                gis_acres = 0.0
                try:
                    gis_acres = float(attrs.get("GIS_Acres", 0)) if attrs.get("GIS_Acres") else 0.0
                except (ValueError, TypeError):
                    pass

                features.append(
                    {
                        "type": "Feature",
                        "geometry": geojson_geom,
                        "properties": {
                            "name": attrs.get("Unit_Nm", "BLM Lands"),
                            "owner_name": attrs.get("Own_Name", ""),
                            "manager_name": attrs.get("Mang_Name", "BLM"),
                            "manager_type": attrs.get("Mang_Type", ""),
                            "designation_type": attrs.get("Des_Tp", ""),
                            "state": attrs.get("State_Nm", ""),
                            "acres": round(gis_acres, 0) if gis_acres else None,
                            "gap_status": attrs.get("GAP_Sts", ""),
                            "layer": "blm_managed_lands",
                        },
                    }
                )

        return _feature_collection(features, query_result)

    except Exception as exc:
        return _failed_feature_collection(f"PAD-US BLM managed lands request failed: {exc}")


def get_federal_lands_geojson(buffer_geometry: Dict) -> Dict:
    """
    Get non-BLM federal protected land boundaries as GeoJSON via PAD-US.

    Queries USGS Protected Areas Database (PAD-US 4.1) filtered to
    federal managers other than BLM (USFS, NPS, FWS, DOD, DOE, etc.).

    Args:
        buffer_geometry: ESRI JSON polygon geometry (ROI buffer)

    Returns:
        GeoJSON FeatureCollection with federal land management polygons
    """
    simplified_geom = ArcGISService.simplify_polygon_geometry(buffer_geometry)

    url = f"{PADUS_URL}/{PADUS_LAYER_ID}/query"
    params = {
        "geometry": json.dumps(simplified_geom),
        "geometryType": "esriGeometryPolygon",
        "where": "Mang_Type = 'FED' AND Mang_Name <> 'BLM'",
        "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "returnGeometry": True,
        "outSR": 4326,
        "maxAllowableOffset": DEFAULT_OUTPUT_OFFSET_DEG,
        "outFields": "Own_Name,Mang_Name,Mang_Type,Unit_Nm,Des_Tp,State_Nm,GIS_Acres,GAP_Sts",
        "f": "json",
    }

    try:
        query_result = _query_arcgis_features(url, params, timeout=30, max_features=4500)

        features = []
        for feature in query_result.features:
            attrs = feature.get("attributes", {})
            geom = feature.get("geometry")

            if geom:
                geojson_geom = esri_to_geojson_geometry(geom, "esriGeometryPolygon")

                gis_acres = 0.0
                try:
                    gis_acres = float(attrs.get("GIS_Acres", 0)) if attrs.get("GIS_Acres") else 0.0
                except (ValueError, TypeError):
                    pass

                features.append(
                    {
                        "type": "Feature",
                        "geometry": geojson_geom,
                        "properties": {
                            "name": attrs.get("Unit_Nm", "Federal Lands"),
                            "owner_name": attrs.get("Own_Name", ""),
                            "manager_name": attrs.get("Mang_Name", ""),
                            "manager_type": attrs.get("Mang_Type", ""),
                            "designation_type": attrs.get("Des_Tp", ""),
                            "state": attrs.get("State_Nm", ""),
                            "acres": round(gis_acres, 0) if gis_acres else None,
                            "gap_status": attrs.get("GAP_Sts", ""),
                            "layer": "federal_lands",
                        },
                    }
                )

        return _feature_collection(features, query_result)

    except Exception as exc:
        return _failed_feature_collection(f"PAD-US federal lands request failed: {exc}")


def get_blm_land_use_plans_geojson(buffer_geometry: Dict) -> Dict:
    """
    Get approved BLM land use plans (RMPs) as GeoJSON.

    Args:
        buffer_geometry: ESRI JSON polygon geometry (ROI buffer)

    Returns:
        GeoJSON FeatureCollection with land use plan boundary polygons
    """
    simplified_geom = ArcGISService.simplify_polygon_geometry(buffer_geometry)

    url = f"{BLM_LAND_USE_PLANS_URL}/{BLM_LAND_USE_PLANS_LAYER_ID}/query"
    params = {
        "geometry": json.dumps(simplified_geom),
        "geometryType": "esriGeometryPolygon",
        "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "returnGeometry": True,
        "outSR": 4326,
        "maxAllowableOffset": DEFAULT_OUTPUT_OFFSET_DEG,
        "outFields": "LUPName,Status,RODdate,RODyear,ePLink,AdminSt,NEPAnum,MapType",
        "f": "json",
    }

    try:
        query_result = _query_arcgis_features(url, params, timeout=30)

        features = []
        seen_plans = set()

        for feature in query_result.features:
            attrs = feature.get("attributes", {})
            geom = feature.get("geometry")

            plan_name = attrs.get("LUPName", "Unknown")
            if plan_name in seen_plans:
                continue
            seen_plans.add(plan_name)

            if geom:
                geojson_geom = esri_to_geojson_geometry(geom, "esriGeometryPolygon")
                features.append(
                    {
                        "type": "Feature",
                        "geometry": geojson_geom,
                        "properties": {
                            "name": plan_name,
                            "status": attrs.get("Status", ""),
                            "rod_date": attrs.get("RODdate", ""),
                            "rod_year": attrs.get("RODyear"),
                            "eplan_link": attrs.get("ePLink", ""),
                            "admin_state": attrs.get("AdminSt", ""),
                            "nepa_number": attrs.get("NEPAnum", ""),
                            "map_type": attrs.get("MapType", ""),
                            "layer": "blm_land_use_plans",
                        },
                    }
                )

        return _feature_collection(features, query_result)

    except Exception as exc:
        return _failed_feature_collection(f"BLM land-use-plan request failed: {exc}")


def get_blm_plans_in_progress_geojson(buffer_geometry: Dict) -> Dict:
    """
    Get BLM land use plans under revision/development as GeoJSON.

    Args:
        buffer_geometry: ESRI JSON polygon geometry (ROI buffer)

    Returns:
        GeoJSON FeatureCollection with in-progress plan boundary polygons
    """
    simplified_geom = ArcGISService.simplify_polygon_geometry(buffer_geometry)

    url = f"{BLM_PLANS_IN_PROGRESS_URL}/{BLM_PLANS_IN_PROGRESS_LAYER_ID}/query"
    params = {
        "geometry": json.dumps(simplified_geom),
        "geometryType": "esriGeometryPolygon",
        "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "returnGeometry": True,
        "outSR": 4326,
        "maxAllowableOffset": DEFAULT_OUTPUT_OFFSET_DEG,
        "outFields": "LUPName,Status,RODdate,ePLink,AdminSt,NEPAnum,MapType",
        "f": "json",
    }

    try:
        query_result = _query_arcgis_features(url, params, timeout=30)

        features = []
        seen_plans = set()

        for feature in query_result.features:
            attrs = feature.get("attributes", {})
            geom = feature.get("geometry")

            plan_name = attrs.get("LUPName", "Unknown")
            if plan_name in seen_plans:
                continue
            seen_plans.add(plan_name)

            if geom:
                geojson_geom = esri_to_geojson_geometry(geom, "esriGeometryPolygon")
                features.append(
                    {
                        "type": "Feature",
                        "geometry": geojson_geom,
                        "properties": {
                            "name": plan_name,
                            "status": attrs.get("Status", ""),
                            "rod_date": attrs.get("RODdate", ""),
                            "eplan_link": attrs.get("ePLink", ""),
                            "admin_state": attrs.get("AdminSt", ""),
                            "nepa_number": attrs.get("NEPAnum", ""),
                            "map_type": attrs.get("MapType", ""),
                            "layer": "blm_plans_in_progress",
                        },
                    }
                )

        return _feature_collection(features, query_result)

    except Exception as exc:
        return _failed_feature_collection(f"BLM plans-in-progress request failed: {exc}")


def get_blm_wilderness_study_areas_geojson(buffer_geometry: Dict) -> Dict:
    """
    Get BLM Wilderness Study Areas as GeoJSON.

    Args:
        buffer_geometry: ESRI JSON polygon geometry (ROI buffer)

    Returns:
        GeoJSON FeatureCollection with WSA boundary polygons
    """
    url = f"{BLM_WSA_URL}/{BLM_WSA_LAYER_ID}/query"
    params = {
        "geometry": json.dumps(buffer_geometry),
        "geometryType": "esriGeometryPolygon",
        "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "returnGeometry": True,
        "outSR": 4326,
        "outFields": "NLCS_NAME,NLCS_ID,CASEFILE_NO,WSA_RCMND,ADMIN_ST,ROD_DATE",
        "f": "json",
    }

    try:
        query_result = _query_arcgis_features(url, params, timeout=30, max_features=4500)

        features = []

        for feature in query_result.features:
            attrs = feature.get("attributes", {})
            geom = feature.get("geometry")

            wsa_name = attrs.get("NLCS_NAME", "Unknown")

            geojson_geom = esri_to_geojson_geometry(geom, "esriGeometryPolygon") if isinstance(geom, dict) else None
            # Include missing geometry so _feature_collection records the loss
            # and marks the result partial instead of silently reporting no hit.
            features.append(
                {
                    "type": "Feature",
                    "geometry": geojson_geom,
                    "properties": {
                        "name": wsa_name,
                        "nlcs_id": attrs.get("NLCS_ID", ""),
                        "casefile": attrs.get("CASEFILE_NO", ""),
                        "recommendation": attrs.get("WSA_RCMND", ""),
                        "admin_state": attrs.get("ADMIN_ST", ""),
                        "rod_date": _format_wsa_rod_date(attrs.get("ROD_DATE")),
                        "rod_date_raw": attrs.get("ROD_DATE"),
                        "source_url": url.removesuffix("/query"),
                        # The national public layer does not expose these
                        # fields. Retain the keys for output compatibility
                        # without manufacturing values.
                        "wsa_type": None,
                        "suitability": None,
                        "wilderness_values": None,
                        "layer": "blm_wilderness_study_areas",
                    },
                }
            )

        return _feature_collection(features, query_result)

    except Exception as exc:
        return _failed_feature_collection(f"BLM wilderness study area request failed: {exc}")


def get_blm_national_monuments_geojson(buffer_geometry: Dict) -> Dict:
    """
    Get BLM National Monuments and National Conservation Areas as GeoJSON.

    Args:
        buffer_geometry: ESRI JSON polygon geometry (ROI buffer)

    Returns:
        GeoJSON FeatureCollection with NM/NCA boundary polygons
    """
    url = f"{BLM_NATIONAL_MONUMENTS_URL}/{BLM_NATIONAL_MONUMENTS_LAYER_ID}/query"
    params = {
        "geometry": json.dumps(buffer_geometry),
        "geometryType": "esriGeometryPolygon",
        "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "returnGeometry": True,
        "outSR": 4326,
        "outFields": "NCA_NAME,sma_code,STATE_ADMN,STATE_GEOG,Label,NLCS_ID",
        "f": "json",
    }

    try:
        query_result = _query_arcgis_features(url, params, timeout=30)

        features = []

        for feature in query_result.features:
            attrs = feature.get("attributes", {})
            geom = feature.get("geometry")

            monument_name = attrs.get("NCA_NAME", "Unknown")

            geojson_geom = esri_to_geojson_geometry(geom, "esriGeometryPolygon") if isinstance(geom, dict) else None
            # Preserve missing-geometry accounting for both the bundled layer
            # and the distinct NCA layer that filters this collection.
            features.append(
                {
                    "type": "Feature",
                    "geometry": geojson_geom,
                    "properties": {
                        "name": monument_name,
                        "designation": attrs.get("Label", ""),
                        "sma_code": attrs.get("sma_code", ""),
                        **designation_details(attrs),
                        "source_url": url.removesuffix("/query"),
                        "admin_state": attrs.get("STATE_ADMN", ""),
                        "geographic_state": attrs.get("STATE_GEOG", ""),
                        "nlcs_id": attrs.get("NLCS_ID", ""),
                        "layer": "blm_national_monuments",
                    },
                }
            )

        return _feature_collection(features, query_result)

    except Exception as exc:
        return _failed_feature_collection(f"BLM monument and conservation area request failed: {exc}")


def get_blm_rights_of_way_geojson(buffer_geometry: Dict) -> Dict:
    """
    Get BLM Rights of Way NSO restriction areas as GeoJSON.

    Queries NSO (No Surface Occupancy) restriction areas from the
    BLM Rights of Way service.

    Args:
        buffer_geometry: ESRI JSON polygon geometry (ROI buffer)

    Returns:
        GeoJSON FeatureCollection with ROW NSO restriction polygons
    """
    simplified_geom = ArcGISService.simplify_polygon_geometry(buffer_geometry)

    url = f"{BLM_ROW_URL}/{BLM_ROW_NSO_LAYER_ID}/query"
    params = {
        "geometry": json.dumps(simplified_geom),
        "geometryType": "esriGeometryPolygon",
        "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "returnGeometry": True,
        "outSR": 4326,
        "maxAllowableOffset": DEFAULT_OUTPUT_OFFSET_DEG,
        "outFields": "*",
        "f": "json",
    }

    try:
        query_result = _query_arcgis_features(url, params, timeout=30, max_features=4500)

        features = []
        for feature in query_result.features:
            attrs = feature.get("attributes", {})
            geom = feature.get("geometry")

            if geom:
                geojson_geom = esri_to_geojson_geometry(geom, "esriGeometryPolygon")
                name = attrs.get("Name", attrs.get("NAME", attrs.get("LABEL", "NSO Restriction Area")))
                features.append(
                    {
                        "type": "Feature",
                        "geometry": geojson_geom,
                        "properties": {
                            "name": name,
                            "restriction_type": "No Surface Occupancy",
                            "layer": "blm_rights_of_way",
                        },
                    }
                )

        return _feature_collection(features, query_result)

    except Exception as exc:
        return _failed_feature_collection(f"BLM right-of-way layer request failed: {exc}")


# =============================================================================
# SAGE-GROUSE AND HABITAT LAYERS
# =============================================================================


def get_grsg_habitat_geojson(buffer_geometry: Dict) -> Dict:
    """
    Get Greater Sage-Grouse Habitat Management Areas (Feb 2026 ROD) as GeoJSON.

    Args:
        buffer_geometry: ESRI JSON polygon geometry (ROI buffer)

    Returns:
        GeoJSON FeatureCollection with GRSG habitat management polygons
    """
    simplified_geom = ArcGISService.simplify_polygon_geometry(buffer_geometry)

    url = f"{GRSG_HABITAT_URL}/{GRSG_HABITAT_LAYER_ID}/query"
    params = {
        "geometry": json.dumps(simplified_geom),
        "geometryType": "esriGeometryPolygon",
        "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "returnGeometry": True,
        "outSR": 4326,
        "maxAllowableOffset": DEFAULT_OUTPUT_OFFSET_DEG,
        "outFields": "EIS_HAB,Source,Habitat_Type,SUM_ACRES",
        "f": "json",
    }

    try:
        query_result = _query_arcgis_features(url, params, timeout=60)

        features = []
        for feature in query_result.features:
            attrs = feature.get("attributes", {})
            geom = feature.get("geometry")

            if geom:
                geojson_geom = esri_to_geojson_geometry(geom, "esriGeometryPolygon")
                habitat_type = str(attrs.get("Habitat_Type") or "Unknown")
                eis_hab = str(attrs.get("EIS_HAB") or "")
                state = eis_hab.split("_")[0] if "_" in eis_hab else ""
                acres = attrs.get("SUM_ACRES", 0)

                features.append(
                    {
                        "type": "Feature",
                        "geometry": geojson_geom,
                        "properties": {
                            "name": f"{state} {habitat_type}" if state else habitat_type,
                            "habitat_type": habitat_type,
                            "source": attrs.get("Source", ""),
                            "acres": round(acres, 0) if acres else None,
                            "layer": "grsg_habitat",
                        },
                    }
                )

        return _feature_collection(features, query_result)

    except Exception as exc:
        return _failed_feature_collection(f"Greater sage-grouse habitat request failed: {exc}")


def get_sagebrush_focal_areas_geojson(buffer_geometry: Dict) -> Dict:
    """
    Get Sagebrush Focal Areas as GeoJSON.

    These represent the most critical sage-grouse habitat with
    the highest level of protection (mineral withdrawal recommended).

    Args:
        buffer_geometry: ESRI JSON polygon geometry (ROI buffer)

    Returns:
        GeoJSON FeatureCollection with sagebrush focal area polygons
    """
    simplified_geom = ArcGISService.simplify_polygon_geometry(buffer_geometry)

    url = f"{SAGEBRUSH_FOCAL_URL}/{SAGEBRUSH_FOCAL_LAYER_ID}/query"
    params = {
        "geometry": json.dumps(simplified_geom),
        "geometryType": "esriGeometryPolygon",
        "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "returnGeometry": True,
        "outSR": 4326,
        "maxAllowableOffset": DEFAULT_OUTPUT_OFFSET_DEG,
        "outFields": "SFA_Name,Subsurface,SMA",
        "f": "json",
    }

    try:
        query_result = _query_arcgis_features(url, params, timeout=60)

        features = []
        for feature in query_result.features:
            attrs = feature.get("attributes", {})
            geom = feature.get("geometry")

            if geom:
                geojson_geom = esri_to_geojson_geometry(geom, "esriGeometryPolygon")
                features.append(
                    {
                        "type": "Feature",
                        "geometry": geojson_geom,
                        "properties": {
                            "name": attrs.get("SFA_Name", "Unknown"),
                            "subsurface_withdrawal": attrs.get("Subsurface", ""),
                            "surface_management_agency": attrs.get("SMA", ""),
                            "layer": "sagebrush_focal_areas",
                        },
                    }
                )

        return _feature_collection(features, query_result)

    except Exception as exc:
        return _failed_feature_collection(f"Sagebrush focal area request failed: {exc}")


def get_wild_horse_hma_geojson(buffer_geometry: Dict) -> Dict:
    """
    Get Wild Horse and Burro Herd Management Areas as GeoJSON.

    Args:
        buffer_geometry: ESRI JSON polygon geometry (ROI buffer)

    Returns:
        GeoJSON FeatureCollection with HMA boundary polygons
    """
    simplified_geom = ArcGISService.simplify_polygon_geometry(buffer_geometry)

    url = f"{WILD_HORSE_HMA_URL}/{WILD_HORSE_HMA_LAYER_ID}/query"
    params = {
        "geometry": json.dumps(simplified_geom),
        "geometryType": "esriGeometryPolygon",
        "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "returnGeometry": True,
        "outSR": 4326,
        "maxAllowableOffset": DEFAULT_OUTPUT_OFFSET_DEG,
        "outFields": "HMA_NAME,HMA_ID,ADMIN_ST,HERD_TYPE,BLM_ACRES",
        "f": "json",
    }

    try:
        query_result = _query_arcgis_features(url, params, timeout=30)

        features = []
        for feature in query_result.features:
            attrs = feature.get("attributes", {})
            geom = feature.get("geometry")

            if geom:
                geojson_geom = esri_to_geojson_geometry(geom, "esriGeometryPolygon")
                acres = attrs.get("BLM_ACRES", 0)
                features.append(
                    {
                        "type": "Feature",
                        "geometry": geojson_geom,
                        "properties": {
                            "name": attrs.get("HMA_NAME", "Unknown"),
                            "hma_id": attrs.get("HMA_ID", ""),
                            "admin_state": attrs.get("ADMIN_ST", ""),
                            "herd_type": attrs.get("HERD_TYPE", ""),
                            "blm_acres": round(float(acres), 0) if acres else None,
                            "layer": "wild_horse_hma",
                        },
                    }
                )

        return _feature_collection(features, query_result)

    except Exception as exc:
        return _failed_feature_collection(f"Wild horse and burro management area request failed: {exc}")


# =============================================================================
# CONTEXTUAL/SUPPORTING LAYERS
# =============================================================================


def get_national_trails_geojson(buffer_geometry: Dict) -> Dict:
    """
    Get National Scenic and Historic Trails as GeoJSON.

    Returns polyline features. These are long linear trails spanning
    thousands of miles -- any reasonably sized ROI buffer will intersect
    trails that pass through the area.

    Args:
        buffer_geometry: ESRI JSON polygon geometry (ROI buffer)

    Returns:
        GeoJSON FeatureCollection with trail polyline features
    """
    simplified_geom = ArcGISService.simplify_polygon_geometry(buffer_geometry)

    url = f"{NATIONAL_TRAILS_URL}/{NATIONAL_TRAILS_LAYER_ID}/query"
    params = {
        "geometry": json.dumps(simplified_geom),
        "geometryType": "esriGeometryPolygon",
        "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "returnGeometry": True,
        "outSR": 4326,
        "maxAllowableOffset": DEFAULT_OUTPUT_OFFSET_DEG,
        "outFields": "Trail_Name,Display_Name",
        "f": "json",
    }

    try:
        query_result = _query_arcgis_features(url, params, timeout=60)

        features = []
        for feature in query_result.features:
            attrs = feature.get("attributes", {})
            geom = feature.get("geometry")

            if geom:
                geojson_geom = esri_to_geojson_geometry(geom, "esriGeometryPolyline")
                if geojson_geom:
                    features.append(
                        {
                            "type": "Feature",
                            "geometry": geojson_geom,
                            "properties": {
                                "name": attrs.get("Trail_Name", attrs.get("Display_Name", "Unknown")),
                                "display_name": attrs.get("Display_Name", ""),
                                "layer": "national_trails",
                            },
                        }
                    )

        return _feature_collection(features, query_result)

    except Exception as exc:
        return _failed_feature_collection(f"National trail layer request failed: {exc}")


def get_fire_perimeters_geojson(buffer_geometry: Dict) -> Dict:
    """
    Get authoritative interagency historical fire perimeters as GeoJSON.

    Args:
        buffer_geometry: ESRI JSON polygon geometry (ROI buffer)

    Returns:
        GeoJSON FeatureCollection with fire perimeter polygons
    """
    simplified_geom = ArcGISService.simplify_polygon_geometry(buffer_geometry)

    url = f"{FIRE_PERIMETERS_URL}/{FIRE_PERIMETERS_LAYER_ID}/query"
    params = {
        "geometry": json.dumps(simplified_geom),
        "geometryType": "esriGeometryPolygon",
        "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "returnGeometry": True,
        "outSR": 4326,
        "maxAllowableOffset": DEFAULT_OUTPUT_OFFSET_DEG,
        "outFields": "INCIDENT,FIRE_YEAR_INT,FIRE_YEAR,FEATURE_CA,GIS_ACRES,AGENCY,SOURCE",
        "f": "json",
    }

    try:
        query_result = _query_arcgis_features(url, params, timeout=30, max_features=2000)

        features = []
        for feature in query_result.features:
            attrs = feature.get("attributes", {})
            geom = feature.get("geometry")

            if geom:
                geojson_geom = esri_to_geojson_geometry(geom, "esriGeometryPolygon")
                acres = attrs.get("GIS_ACRES", 0)
                features.append(
                    {
                        "type": "Feature",
                        "geometry": geojson_geom,
                        "properties": {
                            "name": attrs.get("INCIDENT", "Unknown Fire"),
                            "year": attrs.get("FIRE_YEAR_INT") or attrs.get("FIRE_YEAR"),
                            "category": attrs.get("FEATURE_CA", ""),
                            "acres": round(float(acres), 0) if acres else None,
                            "agency": attrs.get("AGENCY", ""),
                            "source": attrs.get("SOURCE", ""),
                            "layer": "fire_perimeters",
                        },
                    }
                )

        return _feature_collection(features, query_result)

    except Exception as exc:
        return _failed_feature_collection(f"Historical fire perimeter request failed: {exc}")


def get_lwcf_lands_geojson(buffer_geometry: Dict) -> Dict:
    """
    Get Land and Water Conservation Fund acquisition parcels as GeoJSON.

    LWCF-acquired lands have Section 6(f) protections -- conversion
    requires NPS approval.

    Args:
        buffer_geometry: ESRI JSON polygon geometry (ROI buffer)

    Returns:
        GeoJSON FeatureCollection with LWCF parcel polygons
    """
    simplified_geom = ArcGISService.simplify_polygon_geometry(buffer_geometry)

    url = f"{LWCF_URL}/{LWCF_LAYER_ID}/query"
    params = {
        "geometry": json.dumps(simplified_geom),
        "geometryType": "esriGeometryPolygon",
        "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "returnGeometry": True,
        "outSR": 4326,
        "maxAllowableOffset": DEFAULT_OUTPUT_OFFSET_DEG,
        "outFields": "Prjt_Name,Geo_State,Purpose,Fund_Year,Area_Acq,County_Rec,Administrating_Agency",
        "f": "json",
    }

    try:
        query_result = _query_arcgis_features(url, params, timeout=30)

        features = []
        for feature in query_result.features:
            attrs = feature.get("attributes", {})
            geom = feature.get("geometry")

            if geom:
                geojson_geom = esri_to_geojson_geometry(geom, "esriGeometryPolygon")
                acres = attrs.get("Area_Acq", 0)
                features.append(
                    {
                        "type": "Feature",
                        "geometry": geojson_geom,
                        "properties": {
                            "name": attrs.get("Prjt_Name", "LWCF Parcel"),
                            "state": attrs.get("Geo_State", ""),
                            "purpose": attrs.get("Purpose", ""),
                            "fund_year": attrs.get("Fund_Year"),
                            "acres": round(float(acres), 1) if acres else None,
                            "county": attrs.get("County_Rec", ""),
                            "agency": attrs.get("Administrating_Agency", ""),
                            "layer": "lwcf_lands",
                        },
                    }
                )

        return _feature_collection(features, query_result)

    except Exception as exc:
        return _failed_feature_collection(f"LWCF parcel request failed: {exc}")


def get_eis_boundaries_geojson(buffer_geometry: Dict) -> Dict:
    """
    Get Western US EIS planning boundaries as GeoJSON.

    These boundaries identify existing BLM EIS planning areas,
    enabling NEPA tiering off prior analysis.

    Args:
        buffer_geometry: ESRI JSON polygon geometry (ROI buffer)

    Returns:
        GeoJSON FeatureCollection with EIS boundary polygons
    """
    simplified_geom = ArcGISService.simplify_polygon_geometry(buffer_geometry)

    url = f"{EIS_BOUNDARIES_URL}/{EIS_BOUNDARIES_LAYER_ID}/query"
    params = {
        "geometry": json.dumps(simplified_geom),
        "geometryType": "esriGeometryPolygon",
        "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "returnGeometry": True,
        "outSR": 4326,
        "maxAllowableOffset": DEFAULT_OUTPUT_OFFSET_DEG,
        "outFields": "EISName,Acres",
        "f": "json",
    }

    try:
        query_result = _query_arcgis_features(url, params, timeout=60)

        features = []
        for feature in query_result.features:
            attrs = feature.get("attributes", {})
            geom = feature.get("geometry")

            if geom:
                geojson_geom = esri_to_geojson_geometry(geom, "esriGeometryPolygon")
                acres = attrs.get("Acres", 0)
                features.append(
                    {
                        "type": "Feature",
                        "geometry": geojson_geom,
                        "properties": {
                            "name": attrs.get("EISName", "Unknown EIS"),
                            "acres": round(float(acres), 0) if acres else None,
                            "layer": "eis_boundaries",
                        },
                    }
                )

        return _feature_collection(features, query_result)

    except Exception as exc:
        return _failed_feature_collection(f"EIS planning boundary request failed: {exc}")


# =============================================================================
# USFS LAYERS
# =============================================================================


def get_usfs_forests_geojson(buffer_geometry: Dict) -> Dict:
    """
    Get USFS National Forest System boundaries as GeoJSON.

    Queries the USDA Forest Service Enterprise Data Warehouse for
    National Forest boundaries intersecting the ROI.

    Args:
        buffer_geometry: ESRI JSON polygon geometry (ROI buffer)

    Returns:
        GeoJSON FeatureCollection with National Forest boundary polygons
    """
    simplified_geom = ArcGISService.simplify_polygon_geometry(buffer_geometry)

    url = f"{USFS_FORESTS_URL}/{USFS_FORESTS_LAYER_ID}/query"
    params = {
        "geometry": json.dumps(simplified_geom),
        "geometryType": "esriGeometryPolygon",
        "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "returnGeometry": True,
        "outSR": 4326,
        "maxAllowableOffset": DEFAULT_OUTPUT_OFFSET_DEG,
        "outFields": "FORESTNAME,REGION,GIS_ACRES,ADMINFORESTID,FORESTORGCODE",
        "f": "json",
    }

    try:
        query_result = _query_arcgis_features(url, params, timeout=30, max_features=4500)

        features = []
        for feature in query_result.features:
            attrs = feature.get("attributes", {})
            geom = feature.get("geometry")

            if geom:
                geojson_geom = esri_to_geojson_geometry(geom, "esriGeometryPolygon")

                gis_acres = 0.0
                try:
                    gis_acres = float(attrs.get("GIS_ACRES", 0)) if attrs.get("GIS_ACRES") else 0.0
                except (ValueError, TypeError):
                    pass

                features.append(
                    {
                        "type": "Feature",
                        "geometry": geojson_geom,
                        "properties": {
                            "name": attrs.get("FORESTNAME", "Unknown Forest"),
                            "region": attrs.get("REGION", ""),
                            "acres": round(gis_acres, 0) if gis_acres else None,
                            "forest_id": attrs.get("ADMINFORESTID", ""),
                            "forest_org_code": attrs.get("FORESTORGCODE", ""),
                            "layer": "usfs_forests",
                        },
                    }
                )

        return _feature_collection(features, query_result)

    except Exception as exc:
        return _failed_feature_collection(f"USFS National Forest boundary request failed: {exc}")


def get_usfs_roadless_areas_geojson(buffer_geometry: Dict) -> Dict:
    """
    Get USFS Inventoried Roadless Areas (2001 Roadless Rule) as GeoJSON.

    These areas are protected under 36 CFR 294 (Roadless Area Conservation Rule).
    CATEGORY values (e.g., "1C", "1A") are IRA category codes from the 2001 Rule.

    Args:
        buffer_geometry: ESRI JSON polygon geometry (ROI buffer)

    Returns:
        GeoJSON FeatureCollection with roadless area boundary polygons
    """
    simplified_geom = ArcGISService.simplify_polygon_geometry(buffer_geometry)

    url = f"{USFS_ROADLESS_AREAS_URL}/{USFS_ROADLESS_AREAS_LAYER_ID}/query"
    params = {
        "geometry": json.dumps(simplified_geom),
        "geometryType": "esriGeometryPolygon",
        "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "returnGeometry": True,
        "outSR": 4326,
        "maxAllowableOffset": DEFAULT_OUTPUT_OFFSET_DEG,
        "outFields": "NAME,CATEGORY,ACRES,FOREST,STATE,REGION",
        "f": "json",
    }

    try:
        query_result = _query_arcgis_features(url, params, timeout=30, max_features=4500)

        features = []
        seen_areas = set()

        for feature in query_result.features:
            attrs = feature.get("attributes", {})
            geom = feature.get("geometry")

            area_name = attrs.get("NAME", "Unknown")
            if area_name in seen_areas:
                continue
            seen_areas.add(area_name)

            if geom:
                geojson_geom = esri_to_geojson_geometry(geom, "esriGeometryPolygon")
                acres = attrs.get("ACRES", 0)

                features.append(
                    {
                        "type": "Feature",
                        "geometry": geojson_geom,
                        "properties": {
                            "name": area_name,
                            "category": attrs.get("CATEGORY", ""),
                            "acres": round(float(acres), 0) if acres else None,
                            "forest": attrs.get("FOREST", ""),
                            "state": attrs.get("STATE", ""),
                            "region": attrs.get("REGION", ""),
                            "layer": "usfs_roadless_areas",
                        },
                    }
                )

        return _feature_collection(features, query_result)

    except Exception as exc:
        return _failed_feature_collection(f"USFS roadless area request failed: {exc}")


# =============================================================================
# NPS LAYERS
# =============================================================================


def get_nps_boundaries_geojson(buffer_geometry: Dict) -> Dict:
    """
    Get National Park Service unit boundaries as GeoJSON.

    Queries the NPS Land Resources Division Boundary and Tract Data Service
    for park, monument, historic site, and other NPS unit boundaries.

    Args:
        buffer_geometry: ESRI JSON polygon geometry (ROI buffer)

    Returns:
        GeoJSON FeatureCollection with NPS unit boundary polygons
    """
    url = f"{NPS_BOUNDARIES_URL}/{NPS_BOUNDARIES_LAYER_ID}/query"
    params = {
        "geometry": json.dumps(buffer_geometry),
        "geometryType": "esriGeometryPolygon",
        "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "returnGeometry": True,
        "outSR": 4326,
        "maxAllowableOffset": DEFAULT_OUTPUT_OFFSET_DEG,
        "outFields": "UNIT_NAME,UNIT_CODE,UNIT_TYPE,STATE,REGION",
        "f": "json",
    }

    try:
        query_result = _query_arcgis_features(url, params, timeout=60)

        features = []
        for feature in query_result.features:
            attrs = feature.get("attributes", {})
            geom = feature.get("geometry")

            if geom:
                geojson_geom = esri_to_geojson_geometry(geom, "esriGeometryPolygon")
                features.append(
                    {
                        "type": "Feature",
                        "geometry": geojson_geom,
                        "properties": {
                            "name": attrs.get("UNIT_NAME", "Unknown"),
                            "unit_code": attrs.get("UNIT_CODE", ""),
                            "unit_type": attrs.get("UNIT_TYPE", ""),
                            "state": attrs.get("STATE", ""),
                            "region": attrs.get("REGION", ""),
                            "layer": "nps_boundaries",
                        },
                    }
                )

        return _feature_collection(features, query_result)

    except Exception as exc:
        return _failed_feature_collection(f"NPS unit boundary request failed: {exc}")


# =============================================================================
# MAIN COLLECTION FUNCTION
# =============================================================================


def collect_all_layers(
    latitude: float,
    longitude: float,
    buffer_miles: float,
    layers: Optional[List[str]] = None,
    include_species_data: bool = False,
    project_geometry: Optional[Dict] = None,
) -> CollectionResult:
    """
    Collect all environmental data layers as GeoJSON.

    Args:
        latitude: Center latitude
        longitude: Center longitude
        buffer_miles: Buffer distance in miles
        layers: List of layer names to collect (None = all layers)
        include_species_data: If True, enrich county features with GBIF species data

    Returns:
        CollectionResult containing GeoJSON layers and explicit availability
        status for every requested layer.
    """
    from src.core.land_layers import (
        annotate_land_relations,
        validate_project_geometry,
    )

    project_geometry = copy.deepcopy(project_geometry)
    project_shape = validate_project_geometry(project_geometry) if project_geometry is not None else None
    buffer_geometry = ArcGISService.create_roi_buffer(latitude, longitude, buffer_miles)
    if project_shape is not None:
        roi_shape = shape(esri_to_geojson_geometry(buffer_geometry, "esriGeometryPolygon"))
        if not roi_shape.covers(project_shape):
            raise ValueError("project_geometry must be contained in the search buffer; enlarge buffer_miles")

    if layers is None:
        layers = DEFAULT_LAYERS

    result: Dict[str, Dict] = {}
    statuses: Dict[str, Dict[str, Any]] = {}

    # Layer fetch mapping
    layer_fetchers = {
        "roi": lambda: get_roi_geojson(latitude, longitude, buffer_miles),
        "tribal_lands": lambda: get_tribal_lands_geojson(buffer_geometry),
        "counties": lambda: get_counties_geojson(
            buffer_geometry,
            include_species_data=include_species_data,
            latitude=latitude,
            longitude=longitude,
            buffer_miles=buffer_miles,
        ),
        "critical_habitat": lambda: get_critical_habitat_geojson(latitude, longitude, buffer_miles, buffer_geometry),
        "wildlife_refuges": lambda: get_wildlife_refuges_geojson(buffer_geometry),
        "usace_districts": lambda: get_usace_districts_geojson(buffer_geometry),
        "wetland_regions": lambda: get_wetland_regions_geojson(buffer_geometry),
        "wetland_subregions": lambda: get_wetland_subregions_geojson(buffer_geometry),
        "nhd_lakes": lambda: get_nhd_lakes_geojson(latitude, longitude, buffer_miles, buffer_geometry),
        "nhd_reservoirs": lambda: get_nhd_reservoirs_geojson(latitude, longitude, buffer_miles, buffer_geometry),
        "nhd_estuaries": lambda: get_nhd_estuaries_geojson(latitude, longitude, buffer_miles, buffer_geometry),
        "nhd_ice_masses": lambda: get_nhd_ice_masses_geojson(latitude, longitude, buffer_miles, buffer_geometry),
        "nhd_perennial_streams": lambda: get_nhd_perennial_streams_geojson(
            latitude, longitude, buffer_miles, buffer_geometry
        ),
        "nhd_stream_areas": lambda: get_nhd_stream_areas_geojson(latitude, longitude, buffer_miles, buffer_geometry),
        "nhd_infrastructure": lambda: get_nhd_infrastructure_geojson(
            latitude, longitude, buffer_miles, buffer_geometry
        ),
        "federal_lands": lambda: get_federal_lands_geojson(buffer_geometry),
        "usfs_forests": lambda: get_usfs_forests_geojson(buffer_geometry),
        "usfs_roadless_areas": lambda: get_usfs_roadless_areas_geojson(buffer_geometry),
        "nps_boundaries": lambda: get_nps_boundaries_geojson(buffer_geometry),
        "blm_managed_lands": lambda: get_blm_managed_lands_geojson(buffer_geometry),
        "blm_land_use_plans": lambda: get_blm_land_use_plans_geojson(buffer_geometry),
        "blm_plans_in_progress": lambda: get_blm_plans_in_progress_geojson(buffer_geometry),
        "blm_wilderness_study_areas": lambda: get_blm_wilderness_study_areas_geojson(buffer_geometry),
        "blm_national_monuments": lambda: get_blm_national_monuments_geojson(buffer_geometry),
        "blm_rights_of_way": lambda: get_blm_rights_of_way_geojson(buffer_geometry),
        "grsg_habitat": lambda: get_grsg_habitat_geojson(buffer_geometry),
        "sagebrush_focal_areas": lambda: get_sagebrush_focal_areas_geojson(buffer_geometry),
        "wild_horse_hma": lambda: get_wild_horse_hma_geojson(buffer_geometry),
        "national_trails": lambda: get_national_trails_geojson(buffer_geometry),
        "fire_perimeters": lambda: get_fire_perimeters_geojson(buffer_geometry),
        "lwcf_lands": lambda: get_lwcf_lands_geojson(buffer_geometry),
        "eis_boundaries": lambda: get_eis_boundaries_geojson(buffer_geometry),
    }

    # Submit all known fetchers to a bounded thread pool. Federal ArcGIS
    # fetchers are I/O-bound blocking HTTP calls, so threads let them overlap
    # while waiting on the network. max_workers=8 keeps us politely below the
    # effective per-host connection pool of any single upstream service; we
    # have many distinct hosts here so 8 concurrent workers spreads load.
    known_layers = [name for name in layers if name in layer_fetchers]
    for layer_name in layers:
        if layer_name not in layer_fetchers:
            warning = f"Unknown Map Composer layer: {layer_name}"
            statuses[layer_name] = {
                "status": "failed",
                "feature_count": 0,
                "warnings": [warning],
            }

    completed: Dict[str, Dict] = {}
    with ThreadPoolExecutor(max_workers=8) as executor:
        future_to_layer = {executor.submit(layer_fetchers[name]): name for name in known_layers}
        # Drain as each completes so the user sees progress in the order that
        # things actually finish (fast layers first, BLM paginators last).
        for future in as_completed(future_to_layer):
            layer_name = future_to_layer[future]
            try:
                fc = future.result()
                completed[layer_name] = fc
                n_features = len(fc.get("features", [])) if isinstance(fc, dict) else 0
                warnings = list(fc.get("warnings") or []) if isinstance(fc, dict) else []
                explicit_status = fc.get("status") if isinstance(fc, dict) else None
                if explicit_status in {"failed", "partial", "empty", "ok"}:
                    status = explicit_status
                elif warnings and n_features:
                    status = "partial"
                else:
                    status = "ok" if n_features else "empty"
                statuses[layer_name] = {
                    "status": status,
                    "feature_count": n_features,
                    "warnings": warnings,
                }
                logger.info("Collected %s (%s features; %s)", layer_name, n_features, status)
            except Exception as exc:  # noqa: BLE001 - we deliberately catch all
                warning = f"{layer_name} layer request failed: {exc}"
                logger.warning(
                    "Fetcher for layer %r raised %s: %s",
                    layer_name,
                    type(exc).__name__,
                    exc,
                )
                completed[layer_name] = _failed_feature_collection(warning)
                statuses[layer_name] = {
                    "status": "failed",
                    "feature_count": 0,
                    "warnings": [warning],
                }

    # Rebuild the result dict in the caller's requested layer order. Python
    # 3.7+ preserves insertion order, which downstream renderers rely on.
    for layer_name in layers:
        if layer_name in completed:
            result[layer_name] = completed[layer_name]

    annotate_land_relations(result, statuses, longitude, latitude, project_shape)
    if project_geometry is not None and "roi" in result:
        result["roi"]["features"].append(
            {
                "type": "Feature",
                "geometry": copy.deepcopy(project_geometry),
                "properties": {"type": "Project Footprint", "name": "Project Footprint", "layer": "roi"},
            }
        )
        statuses["roi"]["feature_count"] = len(result["roi"]["features"])
    ordered_statuses = {layer_name: statuses[layer_name] for layer_name in layers if layer_name in statuses}
    logger.info("Finished Map Composer collection for %s requested layers", len(layers))
    return CollectionResult(layers=result, statuses=ordered_statuses, project_geometry=project_geometry)
