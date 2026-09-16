"""Footprint validation and provenance for existing BLM land-boundary overlays."""

import math
from datetime import datetime, timezone

from shapely.geometry import Point, shape
from shapely.ops import unary_union

from nepa_mcp_common.land_status import (
    BLM_DESIGNATION_GUIDANCE,
    NCA_LAYER,
    WILDERNESS_LEASING_RULE,
    WSA_LAYER,
)

LAND_SOURCES = {
    "blm_wilderness_study_areas": WSA_LAYER,
    "blm_national_monuments": NCA_LAYER,
}


def validate_project_geometry(geometry):
    if not isinstance(geometry, dict) or geometry.get("type") not in ("Polygon", "MultiPolygon"):
        raise ValueError("project_geometry must be a WGS84 GeoJSON Polygon or MultiPolygon geometry")
    try:
        polygons = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
        vertices = [point for polygon in polygons for ring in polygon for point in ring]
        if not vertices or len(vertices) > 10000:
            raise ValueError("project_geometry must have 1–10000 vertices")
        for point in vertices:
            if len(point) != 2 or any(isinstance(v, bool) or not math.isfinite(v) for v in point):
                raise ValueError("project_geometry coordinates must be finite longitude/latitude pairs")
            if not -180 <= point[0] <= 180 or not -90 <= point[1] <= 90:
                raise ValueError("project_geometry coordinates must use WGS84 longitude/latitude")
        for polygon in polygons:
            for ring in polygon:
                if len(ring) < 4 or ring[0] != ring[-1]:
                    raise ValueError("project_geometry rings must be closed with at least four vertices")
                if any(abs(a[0] - b[0]) > 180 for a, b in zip(ring, ring[1:])):
                    raise ValueError("Antimeridian-crossing project footprints are not supported")
        result = shape(geometry)
        if result.is_empty or not result.is_valid:
            raise ValueError("project_geometry must be a nonempty valid polygon")
        return result
    except (KeyError, TypeError, IndexError) as exc:
        raise ValueError("Malformed project_geometry") from exc


def annotate_land_relations(layers, statuses, longitude, latitude, project_shape=None):
    """Evaluate exact retrieved polygons; search-buffer hits never imply footprint containment."""
    target = project_shape if project_shape is not None else Point(longitude, latitude)
    for layer, source in LAND_SOURCES.items():
        if layer not in layers:
            continue
        collection = layers[layer]
        groups = {}
        for index, feature in enumerate(collection["features"]):
            props = feature["properties"]
            key = props.get("nlcs_id") or index
            groups.setdefault(key, []).append(feature)
        for features in groups.values():
            relation = "unknown"
            try:
                geometries = [shape(f["geometry"]) for f in features]
                if all(g.is_valid and not g.is_empty for g in geometries):
                    boundary = unary_union(geometries)
                    relation = (
                        "boundary_touch"
                        if boundary.touches(target)
                        else "contained"
                        if boundary.covers(target)
                        else "overlap"
                        if boundary.intersects(target)
                        else "outside"
                    )
                    if statuses[layer]["status"] in ("partial", "failed"):
                        relation = "unknown_incomplete_source"
            except Exception:
                relation = "unknown_invalid_geometry"
            for feature in features:
                props = feature["properties"]
                props.update(
                    {
                        "source_url": source,
                        "retrieved_at": datetime.now(timezone.utc).isoformat(),
                        "project_relation": relation,
                        "relation_target": "project_footprint" if project_shape is not None else "project_point",
                        "boundary_note": "Mapped screening relationship; no protective buffer or legal determination inferred.",
                    }
                )
                if layer == "blm_wilderness_study_areas":
                    props.update(
                        {
                            "geothermal_leasing_rule": "New geothermal leases are generally not issued in Wilderness/WSAs; "
                            "see 43 CFR 3201.11(h), including statutory exceptions. Existing rights are not adjudicated.",
                            "leasing_authority": WILDERNESS_LEASING_RULE,
                        }
                    )
        statuses[layer]["screening_note"] = BLM_DESIGNATION_GUIDANCE
        statuses[layer]["warnings"] = collection.get("warnings", [])
