"""Shared spatial-analysis helpers for ESRI polygon geometries.

The public clipping helper in this module deliberately accepts ESRI geometry
dictionaries rather than complete ArcGIS feature records.  It normalizes those
polygons to WGS84, preserves shell/hole topology, projects the ROI and features
to a local Lambert azimuthal equal-area CRS, unions feature fragments, and clips
that union to the ROI.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, Mapping, Sequence

from pyproj import CRS, Geod, Transformer
from shapely import make_valid, to_wkt
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform, unary_union


SQ_METERS_PER_ACRE = 4046.8564224
SQ_METERS_PER_SQUARE_MILE = 2_589_988.110336
_WGS84 = CRS.from_epsg(4326)
_WGS84_GEOD = Geod(ellps="WGS84")


class AreaUnit(str, Enum):
    """Supported output units for square-meter area values."""

    SQUARE_METERS = "square_meters"
    SQUARE_KILOMETERS = "square_kilometers"
    ACRES = "acres"
    HECTARES = "hectares"
    SQUARE_MILES = "square_miles"


class SpatialAreaStatus(str, Enum):
    """Outcome of a clipped-area calculation."""

    OK = "ok"
    NO_OVERLAP = "no_overlap"
    NO_GEOMETRY = "no_geometry"
    INVALID_ROI = "invalid_roi"
    INVALID_GEOMETRY = "invalid_geometry"


@dataclass(frozen=True)
class ClippedAreaResult:
    """Structured result for a union-and-clip area operation."""

    area_square_meters: float | None
    status: SpatialAreaStatus
    warnings: tuple[str, ...] = ()
    input_geometry_count: int = 0
    used_geometry_count: int = 0
    complete: bool = False

    def area(self, unit: AreaUnit | str, *, rounded_digits: int | None = None) -> float | None:
        """Return the area in ``unit``, optionally rounded at the presentation edge."""

        if self.area_square_meters is None:
            return None
        converted = convert_area(self.area_square_meters, unit)
        return round(converted, rounded_digits) if rounded_digits is not None else converted


class SpatialGeometryError(ValueError):
    """Raised when an ESRI geometry cannot be interpreted safely."""


def esri_polygon_to_wgs84_wkt(
    geometry: Mapping[str, Any],
    *,
    default_wkid: int = 4326,
    rounding_precision: int = 8,
) -> str:
    """Convert an ESRI polygon to validated WGS84 WKT.

    Ring nesting is reconstructed instead of inferred from source orientation,
    so multipart polygons and holes survive conversion. Longitudes outside the
    conventional WGS84 range are rejected because downstream services may
    interpret antimeridian-spanning WKT inconsistently.
    """
    if not 0 <= rounding_precision <= 15:
        raise ValueError("rounding_precision must be between 0 and 15")

    rings = _geometry_rings_in_wgs84(geometry, default_wkid=default_wkid)
    reference_longitude = _circular_mean_longitude(rings)
    prepared = _prepare_rings(
        rings,
        reference_longitude=reference_longitude,
        max_segment_length_meters=10_000.0,
    )
    if any(not -180.0 <= longitude <= 180.0 for ring in prepared for longitude, _latitude in ring):
        raise SpatialGeometryError(
            "Polygon crosses the antimeridian; this upstream WKT query cannot be represented safely."
        )

    polygon = _polygon_from_rings(prepared)
    if polygon.is_empty or polygon.area <= 0:
        raise SpatialGeometryError("Geometry is empty or has no polygon area.")
    return to_wkt(polygon, rounding_precision=rounding_precision, trim=True)


def convert_area(area_square_meters: float, unit: AreaUnit | str) -> float:
    """Convert square meters to a supported unit, rejecting unknown units."""

    try:
        parsed_unit = unit if isinstance(unit, AreaUnit) else AreaUnit(unit)
    except ValueError as exc:
        supported = ", ".join(item.value for item in AreaUnit)
        raise ValueError(f"Unsupported area unit {unit!r}; expected one of: {supported}") from exc

    conversions = {
        AreaUnit.SQUARE_METERS: 1.0,
        AreaUnit.SQUARE_KILOMETERS: 1_000_000.0,
        AreaUnit.ACRES: SQ_METERS_PER_ACRE,
        AreaUnit.HECTARES: 10_000.0,
        AreaUnit.SQUARE_MILES: SQ_METERS_PER_SQUARE_MILE,
    }
    return float(area_square_meters) / conversions[parsed_unit]


def clipped_union_area_from_esri_geometries(
    esri_geometries: Iterable[Mapping[str, Any] | None],
    roi_geometry: Mapping[str, Any],
    *,
    default_wkid: int = 4326,
    max_segment_length_meters: float = 10_000.0,
) -> ClippedAreaResult:
    """Union ESRI polygons, clip them to an ROI, and return an equal-area result.

    ESRI polygon rings are reconstructed by containment depth, so holes and
    multipart polygons are preserved even when ring orientation is inconsistent.
    Missing ``spatialReference`` metadata is interpreted as ``default_wkid``;
    callers requesting ArcGIS geometry should therefore also request ``outSR``.
    """

    geometries = list(esri_geometries)
    warnings: list[str] = []
    try:
        roi_rings = _geometry_rings_in_wgs84(roi_geometry, default_wkid=default_wkid)
        reference_longitude = _circular_mean_longitude(roi_rings)
        roi_shape = _polygon_from_rings(
            _prepare_rings(
                roi_rings,
                reference_longitude=reference_longitude,
                max_segment_length_meters=max_segment_length_meters,
            )
        )
    except Exception as exc:
        return ClippedAreaResult(
            area_square_meters=None,
            status=SpatialAreaStatus.INVALID_ROI,
            warnings=(str(exc),),
            input_geometry_count=len(geometries),
        )

    if roi_shape.is_empty or roi_shape.area <= 0:
        return ClippedAreaResult(
            area_square_meters=None,
            status=SpatialAreaStatus.INVALID_ROI,
            warnings=("ROI polygon is empty or has no area.",),
            input_geometry_count=len(geometries),
        )

    center = roi_shape.centroid
    if not (-90.0 <= center.y <= 90.0):
        return ClippedAreaResult(
            area_square_meters=None,
            status=SpatialAreaStatus.INVALID_ROI,
            warnings=("ROI centroid is outside valid latitude bounds.",),
            input_geometry_count=len(geometries),
        )

    try:
        projector = _local_equal_area_transformer(center.y, center.x)
        roi_projected = _valid_polygonal(transform(projector.transform, roi_shape))
    except Exception as exc:
        return ClippedAreaResult(
            area_square_meters=None,
            status=SpatialAreaStatus.INVALID_ROI,
            warnings=(f"ROI projection failed: {exc}",),
            input_geometry_count=len(geometries),
        )

    projected_features: list[BaseGeometry] = []
    nonempty_inputs = 0
    for index, esri_geometry in enumerate(geometries):
        if not esri_geometry:
            warnings.append(f"Geometry {index} is missing and was skipped.")
            continue
        nonempty_inputs += 1
        try:
            rings = _geometry_rings_in_wgs84(esri_geometry, default_wkid=default_wkid)
            shape = _polygon_from_rings(
                _prepare_rings(
                    rings,
                    reference_longitude=reference_longitude,
                    max_segment_length_meters=max_segment_length_meters,
                )
            )
            projected = _valid_polygonal(transform(projector.transform, shape))
            if projected.is_empty or projected.area <= 0:
                warnings.append(f"Geometry {index} is empty or has no polygon area and was skipped.")
                continue
            projected_features.append(projected)
        except SpatialGeometryError as exc:
            warnings.append(f"Geometry {index} was skipped: {exc}")
        except Exception as exc:
            warnings.append(f"Geometry {index} could not be processed and was skipped: {exc}")

    if not projected_features:
        status = SpatialAreaStatus.NO_GEOMETRY if nonempty_inputs == 0 else SpatialAreaStatus.INVALID_GEOMETRY
        if status is SpatialAreaStatus.NO_GEOMETRY:
            warnings.append("No feature polygon geometries were provided.")
        return ClippedAreaResult(
            area_square_meters=None,
            status=status,
            warnings=tuple(warnings),
            input_geometry_count=len(geometries),
        )

    try:
        unioned = _valid_polygonal(unary_union(projected_features))
        clipped = _valid_polygonal(unioned.intersection(roi_projected))
    except Exception as exc:
        warnings.append(f"Feature union or ROI intersection failed: {exc}")
        return ClippedAreaResult(
            area_square_meters=None,
            status=SpatialAreaStatus.INVALID_GEOMETRY,
            warnings=tuple(warnings),
            input_geometry_count=len(geometries),
            used_geometry_count=len(projected_features),
        )

    if clipped.is_empty or clipped.area <= 0:
        return ClippedAreaResult(
            area_square_meters=0.0,
            status=SpatialAreaStatus.NO_OVERLAP,
            warnings=tuple(warnings),
            input_geometry_count=len(geometries),
            used_geometry_count=len(projected_features),
            complete=len(projected_features) == len(geometries),
        )

    return ClippedAreaResult(
        area_square_meters=float(clipped.area),
        status=SpatialAreaStatus.OK,
        warnings=tuple(warnings),
        input_geometry_count=len(geometries),
        used_geometry_count=len(projected_features),
        complete=len(projected_features) == len(geometries),
    )


def _geometry_rings_in_wgs84(
    geometry: Mapping[str, Any],
    *,
    default_wkid: int,
) -> list[list[tuple[float, float]]]:
    rings = geometry.get("rings")
    if not isinstance(rings, Sequence) or isinstance(rings, (str, bytes)) or not rings:
        if geometry.get("paths"):
            raise SpatialGeometryError("Line paths are not supported by the polygon-area helper.")
        raise SpatialGeometryError("Geometry does not contain ESRI polygon rings.")

    source_crs = _spatial_reference_crs(geometry, default_wkid=default_wkid)
    try:
        transformer = None if source_crs == _WGS84 else Transformer.from_crs(source_crs, _WGS84, always_xy=True)
    except Exception as exc:
        raise SpatialGeometryError(f"Unsupported spatial reference {source_crs.to_string()}: {exc}") from exc

    transformed_rings: list[list[tuple[float, float]]] = []
    for ring_index, ring in enumerate(rings):
        if not isinstance(ring, Sequence) or isinstance(ring, (str, bytes)) or len(ring) < 3:
            raise SpatialGeometryError(f"Ring {ring_index} has fewer than three coordinates.")
        transformed: list[tuple[float, float]] = []
        for coordinate_index, coordinate in enumerate(ring):
            if not isinstance(coordinate, Sequence) or isinstance(coordinate, (str, bytes)) or len(coordinate) < 2:
                raise SpatialGeometryError(f"Ring {ring_index} coordinate {coordinate_index} is not an x/y pair.")
            try:
                x = float(coordinate[0])
                y = float(coordinate[1])
            except (TypeError, ValueError, OverflowError) as exc:
                raise SpatialGeometryError(f"Ring {ring_index} coordinate {coordinate_index} is not numeric.") from exc
            if transformer is not None:
                try:
                    x, y = transformer.transform(x, y)
                except Exception as exc:
                    raise SpatialGeometryError(
                        f"Ring {ring_index} coordinate {coordinate_index} could not be transformed from "
                        f"{source_crs.to_string()}."
                    ) from exc
            if not math.isfinite(x) or not math.isfinite(y) or not (-90.0 <= y <= 90.0):
                raise SpatialGeometryError(f"Ring {ring_index} coordinate {coordinate_index} is outside WGS84 bounds.")
            transformed.append((x, y))
        transformed_rings.append(transformed)
    return transformed_rings


def _spatial_reference_crs(geometry: Mapping[str, Any], *, default_wkid: int) -> CRS:
    spatial_reference = geometry.get("spatialReference")
    if spatial_reference is None:
        return CRS.from_epsg(int(default_wkid))
    if not isinstance(spatial_reference, Mapping):
        raise SpatialGeometryError("Geometry spatialReference must be an object.")

    wkid = spatial_reference.get("latestWkid", spatial_reference.get("wkid"))
    if wkid is not None:
        try:
            return CRS.from_epsg(int(wkid))
        except Exception as exc:
            raise SpatialGeometryError(f"Invalid spatial-reference WKID: {wkid!r}") from exc

    for key in ("wkt2", "wkt"):
        wkt = spatial_reference.get(key)
        if isinstance(wkt, str) and wkt.strip():
            try:
                return CRS.from_wkt(wkt)
            except Exception as exc:
                raise SpatialGeometryError(f"Invalid spatial-reference {key}: {exc}") from exc

    raise SpatialGeometryError("Geometry spatialReference must include wkid, latestWkid, wkt, or wkt2.")


def _circular_mean_longitude(rings: Sequence[Sequence[tuple[float, float]]]) -> float:
    longitudes = [x for ring in rings for x, _ in ring]
    if not longitudes:
        raise SpatialGeometryError("ROI does not contain coordinates.")
    sin_mean = sum(math.sin(math.radians(value)) for value in longitudes) / len(longitudes)
    cos_mean = sum(math.cos(math.radians(value)) for value in longitudes) / len(longitudes)
    if math.isclose(sin_mean, 0.0, abs_tol=1e-15) and math.isclose(cos_mean, 0.0, abs_tol=1e-15):
        return float(longitudes[0])
    return math.degrees(math.atan2(sin_mean, cos_mean))


def _prepare_rings(
    rings: Sequence[Sequence[tuple[float, float]]],
    *,
    reference_longitude: float,
    max_segment_length_meters: float,
) -> list[list[tuple[float, float]]]:
    if max_segment_length_meters <= 0:
        raise SpatialGeometryError("max_segment_length_meters must be positive.")
    prepared: list[list[tuple[float, float]]] = []
    for ring in rings:
        closed = list(ring)
        if closed[0] != closed[-1]:
            closed.append(closed[0])
        densified = _densify_ring(closed, max_segment_length_meters=max_segment_length_meters)
        prepared.append(_unwrap_ring(densified, reference_longitude=reference_longitude))
    return prepared


def _densify_ring(
    ring: Sequence[tuple[float, float]],
    *,
    max_segment_length_meters: float,
) -> list[tuple[float, float]]:
    densified: list[tuple[float, float]] = [ring[0]]
    for start, end in zip(ring, ring[1:]):
        _azimuth, _back_azimuth, distance = _WGS84_GEOD.inv(start[0], start[1], end[0], end[1])
        intermediate_count = max(0, math.ceil(abs(distance) / max_segment_length_meters) - 1)
        if intermediate_count:
            densified.extend(_WGS84_GEOD.npts(start[0], start[1], end[0], end[1], intermediate_count))
        densified.append(end)
    return densified


def _unwrap_ring(
    ring: Sequence[tuple[float, float]],
    *,
    reference_longitude: float,
) -> list[tuple[float, float]]:
    unwrapped: list[tuple[float, float]] = []
    previous = reference_longitude
    for longitude, latitude in ring:
        adjusted = longitude
        while adjusted - previous > 180.0:
            adjusted -= 360.0
        while adjusted - previous < -180.0:
            adjusted += 360.0
        unwrapped.append((adjusted, latitude))
        previous = adjusted

    mean_longitude = sum(value[0] for value in unwrapped) / len(unwrapped)
    shift = round((reference_longitude - mean_longitude) / 360.0) * 360.0
    return [(longitude + shift, latitude) for longitude, latitude in unwrapped]


def _polygon_from_rings(rings: Sequence[Sequence[tuple[float, float]]]) -> BaseGeometry:
    ring_polygons: list[Polygon] = []
    for ring_index, ring in enumerate(rings):
        polygon = Polygon(ring)
        if polygon.is_empty or polygon.area <= 0:
            raise SpatialGeometryError(f"Ring {ring_index} is empty or has no area.")
        if not polygon.is_valid:
            repaired = make_valid(polygon)
            repaired_polygons = _polygon_parts(repaired)
            if not repaired_polygons:
                raise SpatialGeometryError(f"Ring {ring_index} is invalid and could not be repaired.")
            ring_polygons.extend(Polygon(part.exterior.coords) for part in repaired_polygons)
        else:
            ring_polygons.append(polygon)

    parents: list[int | None] = []
    for index, polygon in enumerate(ring_polygons):
        containers = [
            candidate_index
            for candidate_index, candidate in enumerate(ring_polygons)
            if candidate_index != index and candidate.area > polygon.area and candidate.covers(polygon)
        ]
        parents.append(min(containers, key=lambda candidate_index: ring_polygons[candidate_index].area, default=None))

    depths: list[int] = []
    for index in range(len(ring_polygons)):
        depth = 0
        parent = parents[index]
        visited = {index}
        while parent is not None:
            if parent in visited:
                raise SpatialGeometryError("Polygon ring containment contains a cycle.")
            visited.add(parent)
            depth += 1
            parent = parents[parent]
        depths.append(depth)

    polygons: list[Polygon] = []
    for index, shell in enumerate(ring_polygons):
        if depths[index] % 2:
            continue
        holes = [
            list(ring_polygons[child].exterior.coords)
            for child, parent in enumerate(parents)
            if parent == index and depths[child] == depths[index] + 1
        ]
        polygons.append(Polygon(shell.exterior.coords, holes))

    if not polygons:
        raise SpatialGeometryError("No polygon shells could be reconstructed from the ESRI rings.")
    return _valid_polygonal(unary_union(polygons))


def _valid_polygonal(geometry: BaseGeometry) -> BaseGeometry:
    candidate = make_valid(geometry) if not geometry.is_valid else geometry
    parts = _polygon_parts(candidate)
    if not parts:
        return Polygon()
    if len(parts) == 1:
        return parts[0]
    return MultiPolygon(parts)


def _polygon_parts(geometry: BaseGeometry) -> list[Polygon]:
    if geometry.is_empty:
        return []
    if isinstance(geometry, Polygon):
        return [geometry]
    if isinstance(geometry, MultiPolygon):
        return list(geometry.geoms)
    return [part for part in getattr(geometry, "geoms", ()) if isinstance(part, Polygon) and not part.is_empty]


def _local_equal_area_transformer(center_latitude: float, center_longitude: float) -> Transformer:
    local_equal_area = CRS.from_proj4(
        f"+proj=laea +lat_0={center_latitude:.12f} +lon_0={center_longitude:.12f} +datum=WGS84 +units=m +no_defs"
    )
    return Transformer.from_crs(_WGS84, local_equal_area, always_xy=True, force_over=True)
