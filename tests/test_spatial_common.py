from __future__ import annotations

import pytest
from pyproj import CRS, Geod
from shapely import from_wkt
from shapely.geometry import Polygon

from nepa_mcp_common.spatial import (
    AreaUnit,
    SpatialAreaStatus,
    clipped_union_area_from_esri_geometries,
    convert_area,
    esri_polygon_to_wgs84_wkt,
)


def _geometry(*rings, wkid: int | None = 4326):
    geometry = {"rings": list(rings)}
    if wkid is not None:
        geometry["spatialReference"] = {"wkid": wkid}
    return geometry


ROI_RING = [[-0.2, -0.2], [-0.2, 0.2], [0.2, 0.2], [0.2, -0.2], [-0.2, -0.2]]
OUTER_RING = [[-0.1, -0.1], [-0.1, 0.1], [0.1, 0.1], [0.1, -0.1], [-0.1, -0.1]]
HOLE_RING = [[-0.05, -0.05], [0.05, -0.05], [0.05, 0.05], [-0.05, 0.05], [-0.05, -0.05]]


def test_clipped_area_preserves_esri_holes() -> None:
    roi = _geometry(ROI_RING)
    full = clipped_union_area_from_esri_geometries([_geometry(OUTER_RING)], roi)
    donut = clipped_union_area_from_esri_geometries([_geometry(OUTER_RING, HOLE_RING)], roi)

    assert full.status is SpatialAreaStatus.OK
    assert donut.status is SpatialAreaStatus.OK
    assert donut.area_square_meters == pytest.approx(full.area_square_meters * 0.75, rel=0.001)


def test_duplicate_fragments_are_unioned_before_area() -> None:
    roi = _geometry(ROI_RING)
    one = clipped_union_area_from_esri_geometries([_geometry(OUTER_RING)], roi)
    duplicate = clipped_union_area_from_esri_geometries([_geometry(OUTER_RING), _geometry(OUTER_RING)], roi)

    assert duplicate.area_square_meters == pytest.approx(one.area_square_meters, rel=1e-9)
    assert duplicate.used_geometry_count == 2


def test_disjoint_multipart_rings_are_both_retained() -> None:
    left = [[-0.15, -0.1], [-0.15, 0.1], [-0.05, 0.1], [-0.05, -0.1], [-0.15, -0.1]]
    right = [[0.05, -0.1], [0.05, 0.1], [0.15, 0.1], [0.15, -0.1], [0.05, -0.1]]
    roi = _geometry(ROI_RING)

    multipart = clipped_union_area_from_esri_geometries([_geometry(left, right)], roi)
    separate_left = clipped_union_area_from_esri_geometries([_geometry(left)], roi)
    separate_right = clipped_union_area_from_esri_geometries([_geometry(right)], roi)

    assert multipart.status is SpatialAreaStatus.OK
    assert multipart.area_square_meters == pytest.approx(
        separate_left.area_square_meters + separate_right.area_square_meters,
        rel=1e-6,
    )


def test_dateline_polygon_uses_short_geographic_span() -> None:
    dateline_ring = [
        [179.9, -0.1],
        [179.9, 0.1],
        [-179.9, 0.1],
        [-179.9, -0.1],
        [179.9, -0.1],
    ]
    geometry = _geometry(dateline_ring)

    result = clipped_union_area_from_esri_geometries([geometry], geometry)

    assert result.status is SpatialAreaStatus.OK
    assert result.area(AreaUnit.SQUARE_KILOMETERS) == pytest.approx(492.36, rel=0.002)


def test_high_latitude_area_matches_wgs84_geodesic_area() -> None:
    ring = [[0.0, 75.0], [2.0, 75.0], [2.0, 76.45], [0.0, 76.45], [0.0, 75.0]]
    geometry = _geometry(ring)
    expected, _perimeter = Geod(ellps="WGS84").geometry_area_perimeter(Polygon(ring))

    result = clipped_union_area_from_esri_geometries([geometry], geometry)

    assert result.status is SpatialAreaStatus.OK
    assert result.area_square_meters == pytest.approx(abs(expected), rel=0.001)


def test_non_wgs84_geometry_is_reprojected() -> None:
    web_mercator_square = [[0.0, 0.0], [1000.0, 0.0], [1000.0, 1000.0], [0.0, 1000.0], [0.0, 0.0]]
    roi = _geometry([[-0.02, -0.02], [-0.02, 0.02], [0.02, 0.02], [0.02, -0.02], [-0.02, -0.02]])

    result = clipped_union_area_from_esri_geometries([_geometry(web_mercator_square, wkid=3857)], roi)

    assert result.status is SpatialAreaStatus.OK
    assert result.area(AreaUnit.SQUARE_KILOMETERS) == pytest.approx(0.99, abs=0.02)


def test_disjoint_polygon_has_explicit_zero_area_status() -> None:
    far_ring = [[10.0, 10.0], [10.0, 11.0], [11.0, 11.0], [11.0, 10.0], [10.0, 10.0]]

    result = clipped_union_area_from_esri_geometries([_geometry(far_ring)], _geometry(ROI_RING))

    assert result.status is SpatialAreaStatus.NO_OVERLAP
    assert result.area_square_meters == 0.0


def test_invalid_geometry_is_skipped_without_hiding_valid_geometry() -> None:
    result = clipped_union_area_from_esri_geometries(
        [{"paths": [[[0.0, 0.0], [1.0, 1.0]]]}, _geometry(OUTER_RING)],
        _geometry(ROI_RING),
    )

    assert result.status is SpatialAreaStatus.OK
    assert result.used_geometry_count == 1
    assert result.complete is False
    assert result.warnings and "Line paths" in result.warnings[0]


def test_empty_input_has_distinct_status() -> None:
    result = clipped_union_area_from_esri_geometries([None], _geometry(ROI_RING))

    assert result.status is SpatialAreaStatus.NO_GEOMETRY
    assert result.area_square_meters is None
    assert any("No feature polygon geometries" in warning for warning in result.warnings)


def test_invalid_roi_has_distinct_status() -> None:
    result = clipped_union_area_from_esri_geometries(
        [_geometry(OUTER_RING)],
        {"paths": [[[0.0, 0.0], [1.0, 1.0]]]},
    )

    assert result.status is SpatialAreaStatus.INVALID_ROI
    assert result.area_square_meters is None
    assert "Line paths" in result.warnings[0]


def test_all_invalid_nonempty_features_have_distinct_status() -> None:
    result = clipped_union_area_from_esri_geometries(
        [{"paths": [[[0.0, 0.0], [1.0, 1.0]]]}],
        _geometry(ROI_RING),
    )

    assert result.status is SpatialAreaStatus.INVALID_GEOMETRY
    assert result.area_square_meters is None
    assert "Line paths" in result.warnings[0]


def test_unknown_area_unit_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unsupported area unit"):
        convert_area(100.0, "hectares_typo")


def test_wkt_only_spatial_reference_is_respected() -> None:
    web_mercator_square = [[0.0, 0.0], [1000.0, 0.0], [1000.0, 1000.0], [0.0, 1000.0], [0.0, 0.0]]
    geometry = {
        "rings": [web_mercator_square],
        "spatialReference": {"wkt": CRS.from_epsg(3857).to_wkt()},
    }
    roi = _geometry([[-0.02, -0.02], [-0.02, 0.02], [0.02, 0.02], [0.02, -0.02], [-0.02, -0.02]])

    result = clipped_union_area_from_esri_geometries([geometry], roi)

    assert result.status is SpatialAreaStatus.OK
    assert result.complete is True
    assert result.area(AreaUnit.SQUARE_KILOMETERS) == pytest.approx(0.99, abs=0.02)


def test_supplied_spatial_reference_without_crs_is_rejected() -> None:
    geometry = {"rings": [OUTER_RING], "spatialReference": {}}

    result = clipped_union_area_from_esri_geometries([geometry], _geometry(ROI_RING))

    assert result.status is SpatialAreaStatus.INVALID_GEOMETRY
    assert "must include wkid" in result.warnings[0]


def test_esri_polygon_to_wkt_preserves_shell_and_hole() -> None:
    wkt = esri_polygon_to_wgs84_wkt(_geometry(OUTER_RING, HOLE_RING))

    polygon = Polygon(OUTER_RING, [HOLE_RING])
    assert wkt.startswith("POLYGON")
    assert from_wkt(wkt).area == pytest.approx(polygon.area, rel=2e-6)


def test_esri_polygon_to_wkt_rejects_antimeridian_wrap() -> None:
    geometry = _geometry([[179.9, -0.1], [179.9, 0.1], [-179.9, 0.1], [-179.9, -0.1], [179.9, -0.1]])

    with pytest.raises(ValueError, match="antimeridian"):
        esri_polygon_to_wgs84_wkt(geometry)
