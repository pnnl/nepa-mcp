"""Shared ArcGIS REST helpers used by the NEPA MCP servers."""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from typing import Any

from shapely.geometry import MultiPolygon, Polygon

from .http import DEFAULT_TIMEOUT_SECONDS, get_json


@dataclass(frozen=True)
class Point:
    """A geographic point in WGS84 decimal degrees."""

    latitude: float
    longitude: float

    def to_esri_json(self) -> dict[str, Any]:
        """Convert the point to ESRI JSON format."""
        return {
            "x": self.longitude,
            "y": self.latitude,
            "spatialReference": {"wkid": 4326},
        }


@dataclass(frozen=True)
class ArcGISFeatureQueryResult:
    """Result from an ArcGIS FeatureServer or MapServer query."""

    features: list[dict[str, Any]]
    warnings: list[str]
    truncated: bool = False


class ArcGISService:
    """Small wrapper for ArcGIS geometry operations used by the MCP servers."""

    GEOMETRY_SERVICE = "https://utility.arcgisonline.com/arcgis/rest/services/Geometry/GeometryServer"
    UNITS = {"miles": 9035, "kilometers": 9036, "meters": 9001, "feet": 9002}
    DEFAULT_TIMEOUT_SECONDS = DEFAULT_TIMEOUT_SECONDS
    DEFAULT_SIMPLIFICATION_TOLERANCE_DEGREES = 0.001
    DEFAULT_PAGE_SIZE = 2000
    DEFAULT_MAX_FEATURES = 10_000

    @staticmethod
    def create_roi_buffer(lat: float, lon: float, buffer_miles: float) -> dict[str, Any]:
        """Create a geodesic ArcGIS polygon buffer for a region of interest."""
        point = Point(latitude=float(lat), longitude=float(lon))
        return ArcGISService.create_buffer(point, float(buffer_miles), "miles")

    @staticmethod
    def create_buffer(point: Point, distance: float, unit: str = "miles") -> dict[str, Any]:
        """Create a geodesic ArcGIS polygon buffer around a point."""
        url = f"{ArcGISService.GEOMETRY_SERVICE}/buffer"
        params = {
            "geometries": json.dumps({"geometryType": "esriGeometryPoint", "geometries": [point.to_esri_json()]}),
            "inSR": 4326,
            "outSR": 4326,
            "bufferSR": 3857,
            "distances": distance,
            "unit": ArcGISService.UNITS.get(unit, ArcGISService.UNITS["miles"]),
            "unionResults": True,
            "geodesic": True,
            "f": "json",
        }

        result = get_json(
            url,
            params=params,
            timeout=ArcGISService.DEFAULT_TIMEOUT_SECONDS,
            service_name="ArcGIS GeometryServer",
        )
        geometries = result.get("geometries")
        if not isinstance(geometries, list) or not geometries:
            raise ValueError(f"ArcGIS GeometryServer did not return buffered geometries: {result}")
        return geometries[0]

    @staticmethod
    def simplify_polygon_geometry(
        buffer_geometry: dict[str, Any],
        tolerance: float | None = None,
    ) -> dict[str, Any]:
        """Simplify an ESRI polygon while preserving topology.

        The default tolerance is intentionally smaller than the former copied
        helper's 0.01 degree default so small 0.1 mile ROIs are not collapsed.
        """
        rings = buffer_geometry.get("rings")
        if not isinstance(rings, list) or not rings:
            return buffer_geometry

        tolerance = ArcGISService.DEFAULT_SIMPLIFICATION_TOLERANCE_DEGREES if tolerance is None else tolerance
        simplified_rings: list[list[tuple[float, float]]] = []

        for ring in rings:
            if not isinstance(ring, list) or len(ring) < 4:
                simplified_rings.append(ring)
                continue

            polygon = Polygon(ring)
            if polygon.is_empty:
                simplified_rings.append(ring)
                continue

            simplified = polygon.simplify(tolerance=tolerance, preserve_topology=True)
            if isinstance(simplified, Polygon):
                simplified_rings.append(list(simplified.exterior.coords))
            elif isinstance(simplified, MultiPolygon):
                simplified_rings.extend(list(poly.exterior.coords) for poly in simplified.geoms if not poly.is_empty)
            else:
                simplified_rings.append(ring)

        if not simplified_rings:
            return buffer_geometry

        return {
            "rings": simplified_rings,
            "spatialReference": buffer_geometry.get("spatialReference", {"wkid": 4326}),
        }

    @staticmethod
    def get_extent_from_geometry(geometry: dict[str, Any]) -> dict[str, Any]:
        """Calculate a bounding extent from an ESRI geometry."""
        if geometry.get("rings"):
            all_coords = [coord for ring in geometry["rings"] for coord in ring]
        elif geometry.get("paths"):
            all_coords = [coord for path in geometry["paths"] for coord in path]
        else:
            return {
                "xmin": geometry["x"],
                "ymin": geometry["y"],
                "xmax": geometry["x"],
                "ymax": geometry["y"],
                "spatialReference": geometry.get("spatialReference", {"wkid": 4326}),
            }

        x_coords = [coord[0] for coord in all_coords]
        y_coords = [coord[1] for coord in all_coords]
        return {
            "xmin": min(x_coords),
            "ymin": min(y_coords),
            "xmax": max(x_coords),
            "ymax": max(y_coords),
            "spatialReference": geometry.get("spatialReference", {"wkid": 4326}),
        }

    @staticmethod
    def query_features(
        service_url: str,
        layer_id: int,
        geometry: dict[str, Any],
        *,
        out_fields: str,
        return_geometry: bool = False,
        timeout: float | tuple[float, float] = DEFAULT_TIMEOUT_SECONDS,
        page_size: int = DEFAULT_PAGE_SIZE,
        max_features: int = DEFAULT_MAX_FEATURES,
        headers: dict[str, str] | None = None,
        service_name: str | None = None,
        simplify_geometry: bool = True,
        simplification_tolerance: float | None = None,
        out_sr: int | None = None,
        geometry_type: str = "esriGeometryPolygon",
        in_sr: int = 4326,
        spatial_relation: str = "esriSpatialRelIntersects",
        extra_params: dict[str, Any] | None = None,
        max_attempts: int = 3,
        strict_features: bool = False,
    ) -> ArcGISFeatureQueryResult:
        """Query ArcGIS features with pagination and defensive response handling.

        ``out_sr`` is especially important when ``return_geometry`` is true:
        downstream spatial analysis must not infer a layer's native CRS from its
        numeric coordinates.
        """
        import requests

        if page_size <= 0:
            raise ValueError("page_size must be greater than zero")
        if max_features <= 0:
            raise ValueError("max_features must be greater than zero")
        if max_attempts <= 0:
            raise ValueError("max_attempts must be greater than zero")

        url = f"{service_url}/{layer_id}/query"
        service_label = service_name or f"ArcGIS layer {service_url}/{layer_id}"
        query_geometry = (
            ArcGISService.simplify_polygon_geometry(geometry, tolerance=simplification_tolerance)
            if simplify_geometry
            else geometry
        )
        base_params = {
            "geometry": json.dumps(query_geometry),
            "geometryType": geometry_type,
            "inSR": in_sr,
            "spatialRel": spatial_relation,
            "returnGeometry": return_geometry,
            "outFields": out_fields,
            "f": "json",
        }
        if out_sr is not None:
            base_params["outSR"] = int(out_sr)
        if extra_params:
            protected_params = {
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
            conflicts = protected_params.intersection(extra_params)
            if conflicts:
                raise ValueError(
                    "extra_params cannot override managed ArcGIS query parameters: " + ", ".join(sorted(conflicts))
                )
            base_params.update(extra_params)

        features: list[dict[str, Any]] = []
        warnings: list[str] = []
        offset = 0
        truncated = False

        while True:
            request_count = min(page_size, max_features - len(features))
            params = {
                **base_params,
                "resultOffset": offset,
                "resultRecordCount": request_count,
            }
            for attempt in range(1, max_attempts + 1):
                try:
                    response = requests.post(url, data=params, timeout=timeout, headers=headers)
                    response.raise_for_status()
                    payload = response.json()
                    break
                except requests.RequestException as exc:
                    status_code = getattr(getattr(exc, "response", None), "status_code", None)
                    retriable = isinstance(exc, (requests.Timeout, requests.ConnectionError)) or status_code in {
                        429,
                        500,
                        502,
                        503,
                        504,
                    }
                    if attempt >= max_attempts or not retriable:
                        raise RuntimeError(f"{service_label} request failed: {exc}") from exc
                    time.sleep(0.25 * (2 ** (attempt - 1)))
                except ValueError as exc:
                    raise RuntimeError(f"{service_label} returned invalid JSON") from exc

            if not isinstance(payload, dict):
                raise RuntimeError(f"{service_label} returned unexpected JSON type: {type(payload).__name__}")
            if "error" in payload:
                error = payload["error"]
                if isinstance(error, dict):
                    message = error.get("message", "Unknown ArcGIS error")
                    details = error.get("details") or []
                    if isinstance(details, list) and details:
                        message = f"{message}: {'; '.join(str(detail) for detail in details)}"
                else:
                    message = str(error)
                raise RuntimeError(f"{service_label} returned an error: {message}")

            raw_features = payload.get("features")
            if raw_features is None and strict_features:
                raise RuntimeError(f"{service_label} returned a missing or null features list")
            page_features = raw_features or []
            if not isinstance(page_features, list):
                raise RuntimeError(f"{service_label} returned malformed features")

            response_spatial_reference = payload.get("spatialReference")
            if return_geometry and isinstance(response_spatial_reference, dict):
                for feature in page_features:
                    if not isinstance(feature, dict):
                        continue
                    feature_geometry = feature.get("geometry")
                    if isinstance(feature_geometry, dict) and "spatialReference" not in feature_geometry:
                        feature_geometry["spatialReference"] = response_spatial_reference

            features.extend(page_features)
            exceeded = bool(payload.get("exceededTransferLimit"))
            if len(features) >= max_features:
                # Reaching the cap exactly is not partial when ArcGIS also says
                # there are no more records. A page that pushes us beyond the
                # cap, or an explicit transfer-limit flag, is genuinely partial.
                truncated = len(features) > max_features or exceeded
                features = features[:max_features]
                if truncated:
                    warnings.append(
                        f"{service_label} reached the {max_features} feature safety cap; results are partial."
                    )
                break
            if not exceeded and len(page_features) < request_count:
                break
            if not page_features:
                if exceeded:
                    truncated = True
                    warnings.append(f"{service_label} reported more records but returned an empty page.")
                break
            offset += len(page_features)

        return ArcGISFeatureQueryResult(features=features, warnings=warnings, truncated=truncated)


def calculate_area(geometry: dict[str, Any], unit: str = "square_miles") -> float:
    """Approximate the area of a circular ESRI polygon buffer."""
    if "rings" not in geometry or not geometry["rings"]:
        raise ValueError("Invalid geometry - no rings found")

    ring = geometry["rings"][0]
    x_coords = [coord[0] for coord in ring]
    y_coords = [coord[1] for coord in ring]
    center_x = sum(x_coords) / len(x_coords)
    center_y = sum(y_coords) / len(y_coords)

    distances = []
    for coord in ring:
        dx = coord[0] - center_x
        dy = coord[1] - center_y
        lat_rad = math.radians(center_y)
        dx_m = dx * 111320 * math.cos(lat_rad)
        dy_m = dy * 110540
        distances.append(math.sqrt(dx_m**2 + dy_m**2))

    avg_radius_m = sum(distances) / len(distances)
    area_sq_m = math.pi * (avg_radius_m**2)
    conversions = {
        "square_miles": area_sq_m / 2589988.110336,
        "square_kilometers": area_sq_m / 1_000_000,
        "acres": area_sq_m / 4046.8564224,
        "hectares": area_sq_m / 10_000,
        "square_meters": area_sq_m,
    }
    return conversions.get(unit, conversions["square_miles"])
