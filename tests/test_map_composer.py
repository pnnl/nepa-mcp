from __future__ import annotations

import ast
import copy
import importlib
import inspect
import json
import stat
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests

from nepa_mcp.loader import load_server_module
from nepa_mcp_common import arcgis as arcgis_module
from nepa_mcp_common.arcgis import ArcGISFeatureQueryResult


ROOT = Path(__file__).resolve().parents[1]


def _load_map_modules():
    server = load_server_module("map_composer")
    collector = importlib.import_module("src.core.geometry_collector")
    renderer = importlib.import_module("src.core.map_renderer")
    return server, collector, renderer


@pytest.fixture
def minimal_layers_data() -> dict:
    return {
        "roi": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [-77.0, 38.8]},
                    "properties": {"type": "Project Location"},
                },
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [-77.1, 38.7],
                                [-76.9, 38.7],
                                [-76.9, 38.9],
                                [-77.1, 38.9],
                                [-77.1, 38.7],
                            ]
                        ],
                    },
                    "properties": {"type": "Region of Interest", "buffer_miles": 5},
                },
            ],
        },
        "counties": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [-77.0, 38.8]},
                    "properties": {"name": "District of Columbia", "state": "11", "fips": "11001"},
                }
            ],
        },
    }


def test_layer_metadata_profiles_and_sources_are_consistent() -> None:
    server, collector, _ = _load_map_modules()

    expected = set(collector.DEFAULT_LAYERS)
    assert len(expected) == 32
    assert set(server.LAYER_METADATA) == expected
    assert set(server.LAYER_SOURCE_URLS) == expected
    assert set(collector.LAYER_PROFILES) == {
        "screening",
        "biological",
        "water",
        "lands",
        "full",
    }
    assert collector.LAYER_PROFILES["full"] == collector.DEFAULT_LAYERS
    assert all(set(layers) <= expected for layers in collector.LAYER_PROFILES.values())


def test_layer_selection_rejects_unknown_and_empty_values() -> None:
    server, _, _ = _load_map_modules()

    assert server._resolve_layers("water", ["roi", "roi", "nhd_lakes"]) == [
        "roi",
        "nhd_lakes",
    ]
    with pytest.raises(ValueError, match="At least one"):
        server._resolve_layers("screening", [])
    with pytest.raises(ValueError, match="Unknown Map Composer"):
        server._resolve_layers("screening", ["not_a_layer"])


def test_comprehensive_profile_is_the_tool_default() -> None:
    server, collector, _ = _load_map_modules()

    compose_parameters = inspect.signature(server.compose_environmental_map).parameters
    export_parameters = inspect.signature(server.export_all_layers_geojson).parameters

    assert compose_parameters["profile"].default == "full"
    assert export_parameters["profile"].default == "full"
    assert server._resolve_layers("full", None) == collector.DEFAULT_LAYERS


@pytest.mark.parametrize(
    ("buffer_miles", "expected_zoom"),
    [(1, 13), (5, 12), (10, 11), (25, 10), (50, 9), (100, 8)],
)
def test_initial_zoom_tracks_buffer_size(buffer_miles: float, expected_zoom: int) -> None:
    server, _, _ = _load_map_modules()
    assert server._zoom_start_for_buffer(buffer_miles) == expected_zoom


def test_artifacts_use_private_operator_controlled_directory(tmp_path: Path, monkeypatch) -> None:
    server, _, _ = _load_map_modules()
    configured = tmp_path / "private-artifacts"
    monkeypatch.setenv("NEPA_MCP_OUTPUT_DIR", str(configured))

    directory = server._artifact_directory()
    first = server._artifact_path(
        prefix="map",
        suffix=".html",
        latitude=38.9,
        longitude=-77.0,
        buffer_miles=5,
    )
    second = server._artifact_path(
        prefix="map",
        suffix=".html",
        latitude=38.9,
        longitude=-77.0,
        buffer_miles=5,
    )

    assert directory == configured.resolve()
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert first.parent == directory
    assert first != second


def test_collection_distinguishes_failed_empty_and_successful_layers(monkeypatch) -> None:
    _, collector, _ = _load_map_modules()
    monkeypatch.setattr(
        collector.ArcGISService,
        "create_roi_buffer",
        lambda *_args: {"rings": [[[-77, 38], [-76, 38], [-76, 39], [-77, 38]]]},
    )
    monkeypatch.setattr(
        collector,
        "get_roi_geojson",
        lambda *_args: {
            "type": "FeatureCollection",
            "features": [{"type": "Feature", "geometry": None, "properties": {}}],
        },
    )
    monkeypatch.setattr(
        collector,
        "get_critical_habitat_geojson",
        lambda *_args: collector._failed_feature_collection("service unavailable"),
    )
    monkeypatch.setattr(
        collector,
        "get_wildlife_refuges_geojson",
        lambda *_args: {"type": "FeatureCollection", "features": []},
    )

    result = collector.collect_all_layers(
        38.9,
        -77.0,
        5,
        ["roi", "critical_habitat", "wildlife_refuges"],
    )

    assert result.statuses["roi"]["status"] == "ok"
    assert result.statuses["critical_habitat"] == {
        "status": "failed",
        "feature_count": 0,
        "warnings": ["service unavailable"],
    }
    assert result.statuses["wildlife_refuges"]["status"] == "empty"
    assert "service unavailable" in result.warnings


def test_collection_converts_fetcher_exception_to_failed_status(monkeypatch, capsys) -> None:
    _, collector, _ = _load_map_modules()
    monkeypatch.setattr(
        collector.ArcGISService,
        "create_roi_buffer",
        lambda *_args: {"rings": [[[-77, 38], [-76, 38], [-76, 39], [-77, 38]]]},
    )

    def fail(*_args):
        raise RuntimeError("upstream timeout")

    monkeypatch.setattr(collector, "get_roi_geojson", fail)
    result = collector.collect_all_layers(38.9, -77.0, 5, ["roi"])

    assert result.statuses["roi"]["status"] == "failed"
    assert "upstream timeout" in result.statuses["roi"]["warnings"][0]
    assert capsys.readouterr().out == ""


def test_arcgis_error_payload_is_not_treated_as_an_empty_layer(monkeypatch) -> None:
    _, collector, _ = _load_map_modules()

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "error": {
                    "message": "Service unavailable",
                    "details": ["retry later"],
                }
            }

    monkeypatch.setattr(requests, "post", lambda *_args, **_kwargs: Response())

    with pytest.raises(RuntimeError, match="Service unavailable: retry later"):
        collector._query_arcgis_features(
            "https://example.test/FeatureServer/0/query",
            {
                "geometry": json.dumps({"rings": [[[0, 0], [0, 1], [1, 0], [0, 0]]]}),
                "geometryType": "esriGeometryPolygon",
                "outFields": "*",
                "f": "json",
            },
            timeout=30,
        )


def test_optional_species_enrichment_warning_marks_counties_partial(monkeypatch) -> None:
    _, collector, _ = _load_map_modules()

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "features": [
                    {
                        "attributes": {
                            "NAME": "Example County",
                            "BASENAME": "Example",
                            "STATE": "11",
                            "GEOID": "11001",
                        },
                        "geometry": {
                            "rings": [
                                [
                                    [-77.1, 38.7],
                                    [-76.9, 38.7],
                                    [-76.9, 38.9],
                                    [-77.1, 38.7],
                                ]
                            ]
                        },
                    }
                ]
            }

    monkeypatch.setattr(requests, "post", lambda *_args, **_kwargs: Response())
    monkeypatch.setattr(
        collector,
        "_enrich_counties_with_species",
        lambda *_args, **_kwargs: ["GBIF enrichment unavailable"],
    )

    result = collector.get_counties_geojson(
        {"rings": [[[-77.1, 38.7], [-76.9, 38.7], [-76.9, 38.9], [-77.1, 38.7]]]},
        include_species_data=True,
        latitude=38.8,
        longitude=-77.0,
        buffer_miles=5,
    )

    assert result["status"] == "partial"
    assert result["warnings"] == ["GBIF enrichment unavailable"]
    assert len(result["features"]) == 1


def test_arcgis_spatial_queries_use_post_bodies(monkeypatch) -> None:
    _, collector, _ = _load_map_modules()
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"features": []}

    def post(url, *, data, timeout, headers=None):
        captured.update(url=url, data=data, timeout=timeout, headers=headers)
        return Response()

    monkeypatch.setattr(requests, "post", post)
    result = collector._query_arcgis_features(
        "https://example.test/FeatureServer/0/query",
        {
            "geometry": json.dumps({"rings": [[[0, 0], [0, 1], [1, 0], [0, 0]]]}),
            "geometryType": "esriGeometryPolygon",
            "outFields": "NAME",
            "where": "TYPE = 'example'",
            "maxAllowableOffset": 0.002,
            "f": "json",
        },
        timeout=30,
    )

    assert result.features == []
    assert captured["url"] == "https://example.test/FeatureServer/0/query"
    assert captured["timeout"] == 30
    assert captured["headers"] is None
    assert captured["data"]["where"] == "TYPE = 'example'"
    assert captured["data"]["maxAllowableOffset"] == 0.002
    assert captured["data"]["resultOffset"] == 0
    assert captured["data"]["resultRecordCount"] == 2000


def test_arcgis_spatial_queries_retry_transient_failures(monkeypatch) -> None:
    _, collector, _ = _load_map_modules()
    attempts = 0
    delays = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"features": []}

    def post(*_args, **_kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise requests.Timeout("temporary timeout")
        return Response()

    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(arcgis_module.time, "sleep", delays.append)

    result = collector._query_arcgis_features(
        "https://example.test/FeatureServer/0/query",
        {
            "geometry": json.dumps({"rings": [[[0, 0], [0, 1], [1, 0], [0, 0]]]}),
            "geometryType": "esriGeometryPolygon",
            "outFields": "*",
            "f": "json",
        },
        timeout=30,
    )

    assert result.features == []
    assert attempts == 2
    assert delays == [0.25]


def test_drifted_service_contracts_are_current(monkeypatch) -> None:
    server, collector, _ = _load_map_modules()
    calls = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"features": []}

    def post(url, *, data, timeout, headers=None):
        calls.append((url, data, timeout))
        return Response()

    monkeypatch.setattr(requests, "post", post)
    polygon = {
        "rings": [[[-77.1, 38.7], [-76.9, 38.7], [-76.9, 38.9], [-77.1, 38.7]]],
        "spatialReference": {"wkid": 4326},
    }

    collector.get_usace_districts_geojson(polygon)
    collector.get_nps_boundaries_geojson(polygon)
    collector.get_fire_perimeters_geojson(polygon)

    assert "usace_cw_districts" in calls[0][0]
    assert server.LAYER_SOURCE_URLS["usace_districts"] in calls[0][0]
    assert calls[1][1]["outFields"] == "UNIT_NAME,UNIT_CODE,UNIT_TYPE,STATE,REGION"
    assert "GNIS_ID" not in calls[1][1]["outFields"]
    assert "InterAgencyFirePerimeterHistory_All_Years_View" in calls[2][0]
    assert calls[2][1]["outFields"] == "INCIDENT,FIRE_YEAR_INT,FIRE_YEAR,FEATURE_CA,GIS_ACRES,AGENCY,SOURCE"


def test_wsa_uses_national_service_contract_and_preserves_output_schema(monkeypatch) -> None:
    server, collector, _ = _load_map_modules()
    captured = {}
    raw_feature = {
        "attributes": {
            "NLCS_NAME": "Example Nevada WSA",
            "NLCS_ID": "NV-EXAMPLE",
            "CASEFILE_NO": "NV-000-000",
            "WSA_RCMND": "Pending",
            "ADMIN_ST": "NV",
            "ROD_DATE": 946684800000,
        },
        "geometry": {
            "rings": [
                [
                    [-117.1, 39.0],
                    [-117.0, 39.1],
                    [-116.9, 39.0],
                    [-117.1, 39.0],
                ]
            ]
        },
    }

    def query(url, params, **kwargs):
        captured.update(url=url, params=params, kwargs=kwargs)
        return ArcGISFeatureQueryResult(features=[raw_feature], warnings=[])

    monkeypatch.setattr(collector, "_query_arcgis_features", query)

    result = collector.get_blm_wilderness_study_areas_geojson(
        {
            "rings": [[[-118, 38], [-116, 38], [-116, 40], [-118, 38]]],
            "spatialReference": {"wkid": 4326},
        }
    )

    national_layer_url = (
        "https://services1.arcgis.com/KbxwQRRfWyEYLgp4/arcgis/rest/services/"
        "BLM_Natl_NLCS_Wilderness_Study_Areas_Polygons/FeatureServer/3"
    )
    assert captured["url"] == f"{national_layer_url}/query"
    assert captured["params"]["outFields"] == "NLCS_NAME,NLCS_ID,CASEFILE_NO,WSA_RCMND,ADMIN_ST,ROD_DATE"
    assert server.LAYER_SOURCE_URLS["blm_wilderness_study_areas"] == national_layer_url
    assert result["status"] == "ok"
    assert result["features"][0]["properties"] == {
        "name": "Example Nevada WSA",
        "nlcs_id": "NV-EXAMPLE",
        "casefile": "NV-000-000",
        "recommendation": "Pending",
        "admin_state": "NV",
        "rod_date": "2000-01-01",
        "wsa_type": None,
        "suitability": None,
        "wilderness_values": None,
        "layer": "blm_wilderness_study_areas",
    }


@pytest.mark.parametrize(
    ("source_value", "expected"),
    [
        (946684800000, "2000-01-01"),
        (253392451200000, None),
        (None, None),
        ("not-a-date", None),
    ],
)
def test_wsa_rod_date_handles_valid_sentinel_and_unusable_values(source_value, expected) -> None:
    _, collector, _ = _load_map_modules()

    assert collector._format_wsa_rod_date(source_value) == expected


@pytest.mark.parametrize("casefile", ["NV-010-106", "NV060-541"])
def test_wsa_preserves_source_casefile_format(monkeypatch, casefile: str) -> None:
    _, collector, _ = _load_map_modules()
    monkeypatch.setattr(
        collector,
        "_query_arcgis_features",
        lambda *_args, **_kwargs: ArcGISFeatureQueryResult(
            features=[
                {
                    "attributes": {
                        "NLCS_NAME": "Example WSA",
                        "CASEFILE_NO": casefile,
                        "ROD_DATE": 253392451200000,
                    },
                    "geometry": {
                        "rings": [[[0, 0], [0, 1], [1, 0], [0, 0]]],
                    },
                }
            ],
            warnings=[],
        ),
    )

    result = collector.get_blm_wilderness_study_areas_geojson(
        {
            "rings": [[[0, 0], [0, 2], [2, 0], [0, 0]]],
            "spatialReference": {"wkid": 4326},
        }
    )

    properties = result["features"][0]["properties"]
    assert properties["casefile"] == casefile
    assert properties["rod_date"] is None


def test_esri_multipart_polygon_preserves_disjoint_exteriors_and_holes() -> None:
    _, collector, _ = _load_map_modules()
    outer = [[0, 0], [0, 4], [4, 4], [4, 0], [0, 0]]
    hole = [[1, 1], [3, 1], [3, 3], [1, 3], [1, 1]]
    disjoint_outer = [[10, 10], [10, 12], [12, 12], [12, 10], [10, 10]]

    geometry = collector.esri_to_geojson_geometry(
        {"rings": [outer, hole, disjoint_outer]},
        "esriGeometryPolygon",
    )

    assert geometry["type"] == "MultiPolygon"
    assert len(geometry["coordinates"]) == 2
    assert geometry["coordinates"][0] == [outer, hole]
    assert geometry["coordinates"][1] == [disjoint_outer]


def test_critical_habitat_and_nhd_query_the_geodesic_roi_polygon(monkeypatch) -> None:
    _, collector, _ = _load_map_modules()
    buffer_geometry = {
        "rings": [[[-123.4, 47.4], [-122.8, 47.4], [-122.8, 47.8], [-123.4, 47.4]]],
        "spatialReference": {"wkid": 4326},
    }
    calls = []

    def query(url, params, **kwargs):
        calls.append((url, params, kwargs))
        return ArcGISFeatureQueryResult(features=[], warnings=[])

    monkeypatch.setattr(collector, "_query_arcgis_features", query)

    collector.get_critical_habitat_geojson(47.6, -123.1, 25, buffer_geometry)
    collector.get_nhd_lakes_geojson(47.6, -123.1, 25, buffer_geometry)

    assert len(calls) == 2
    for _url, params, _kwargs in calls:
        assert params["geometryType"] == "esriGeometryPolygon"
        assert json.loads(params["geometry"]) == buffer_geometry


def test_query_truncation_marks_feature_collection_partial() -> None:
    _, collector, _ = _load_map_modules()
    feature = {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [-77, 38]},
        "properties": {},
    }
    query_result = ArcGISFeatureQueryResult(
        features=[],
        warnings=["Example service reached its safety cap; results are partial."],
        truncated=True,
    )

    result = collector._feature_collection([feature], query_result)

    assert result["status"] == "partial"
    assert result["warnings"] == query_result.warnings


def test_feature_collection_drops_empty_geometry_with_a_partial_warning() -> None:
    _, collector, _ = _load_map_modules()

    result = collector._feature_collection(
        [{"type": "Feature", "geometry": None, "properties": {}}],
        ArcGISFeatureQueryResult(features=[], warnings=[]),
    )

    assert result["features"] == []
    assert result["status"] == "partial"
    assert result["warnings"] == ["Dropped 1 feature(s) whose upstream geometry was empty or malformed."]


def test_grsg_null_eis_hab_does_not_fail_the_layer(monkeypatch) -> None:
    _, collector, _ = _load_map_modules()
    raw_feature = {
        "attributes": {
            "EIS_HAB": None,
            "Habitat_Type": "Priority Habitat",
            "Source": "BLM",
            "SUM_ACRES": 100,
        },
        "geometry": {"rings": [[[0, 0], [0, 1], [1, 0], [0, 0]]]},
    }
    monkeypatch.setattr(
        collector,
        "_query_arcgis_features",
        lambda *_args, **_kwargs: ArcGISFeatureQueryResult(features=[raw_feature], warnings=[]),
    )

    result = collector.get_grsg_habitat_geojson(
        {"rings": [[[0, 0], [0, 2], [2, 0], [0, 0]]], "spatialReference": {"wkid": 4326}}
    )

    assert result["status"] == "ok"
    assert result["features"][0]["properties"]["name"] == "Priority Habitat"


def test_gbif_roi_query_uses_the_current_year(monkeypatch) -> None:
    _load_map_modules()
    gbif_api = importlib.import_module("src.apis.gbif_api")
    captured = {}

    def query(params, _max_records):
        captured.update(params)
        return []

    monkeypatch.setattr(gbif_api, "_gbif_paginated_query", query)
    gbif_api.get_gbif_occurrences_in_roi(47.6, -122.3, 25, threatened_only=False)

    assert captured["year"] == f"2015,{datetime.now(timezone.utc).year}"
    min_lon, max_lon = (float(value) for value in captured["decimalLongitude"].split(","))
    assert max_lon - min_lon > 2 * (25 / 69.0)


def test_renderer_escapes_title_feature_values_and_unsafe_links(
    tmp_path: Path,
    minimal_layers_data: dict,
) -> None:
    _, _, renderer = _load_map_modules()
    malicious = "</div><script>alert('xss')</script>"
    data = copy.deepcopy(minimal_layers_data)
    data["counties"]["features"][0]["properties"]["name"] = malicious
    data["usace_districts"] = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [-77.0, 38.8]},
                "properties": {
                    "name": "District",
                    "website_url": "javascript:alert(1)",
                },
            }
        ],
    }

    output = tmp_path / "map.html"
    renderer.render_environmental_map(
        data,
        38.8,
        -77.0,
        str(output),
        title=malicious,
    )
    html = output.read_text(encoding="utf-8")

    assert malicious not in html
    assert "href='javascript:" not in html
    assert stat.S_IMODE(output.stat().st_mode) == 0o600


def test_renderer_skips_null_geometry_without_aborting_map(
    tmp_path: Path,
    minimal_layers_data: dict,
) -> None:
    _, _, renderer = _load_map_modules()
    data = copy.deepcopy(minimal_layers_data)
    data["counties"]["features"].append(
        {
            "type": "Feature",
            "geometry": None,
            "properties": {"name": "Malformed upstream record"},
        }
    )
    output = tmp_path / "null-geometry-map.html"

    renderer.render_environmental_map(data, 38.8, -77.0, str(output))

    assert output.exists()
    assert "District of Columbia" in output.read_text(encoding="utf-8")


def test_renderer_escapes_value_bearing_formatter_output() -> None:
    _, _, renderer = _load_map_modules()
    malicious = "</td><script>alert(1)</script>"

    popup = renderer.create_layer_popup(
        {"name": "Lake", "elevation": malicious, "area_acres": malicious},
        "nhd_lakes",
    )

    assert malicious not in popup
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in popup


def test_renderer_exposes_layer_availability_summary(
    tmp_path: Path,
    minimal_layers_data: dict,
) -> None:
    _, _, renderer = _load_map_modules()
    output = tmp_path / "status-map.html"

    renderer.render_environmental_map(
        minimal_layers_data,
        38.8,
        -77.0,
        str(output),
        title="Status map",
        layer_statuses={
            "roi": {"status": "ok", "feature_count": 2, "warnings": []},
            "counties": {"status": "partial", "feature_count": 1, "warnings": ["truncated"]},
            "critical_habitat": {"status": "empty", "feature_count": 0, "warnings": []},
            "nps_boundaries": {"status": "failed", "feature_count": 0, "warnings": ["unavailable"]},
        },
    )

    html = output.read_text(encoding="utf-8")
    assert 'aria-label="Map layer status"' in html
    assert "4 requested" in html
    assert "2 rendered (1 partial)" in html
    assert "1 empty" in html
    assert "1 failed" in html


def test_map_defaults_to_cartodb_without_redundant_legend(
    tmp_path: Path,
    minimal_layers_data: dict,
) -> None:
    server, _, renderer = _load_map_modules()
    output = tmp_path / "default-map.html"

    renderer.render_environmental_map(
        minimal_layers_data,
        38.8,
        -77.0,
        str(output),
    )

    html = output.read_text(encoding="utf-8")
    tool_parameters = inspect.signature(server.compose_environmental_map).parameters
    renderer_parameters = inspect.signature(renderer.render_environmental_map).parameters

    assert tool_parameters["basemap"].default == "CartoDB Positron"
    assert renderer_parameters["basemap"].default == "CartoDB Positron"
    assert "include_legend" not in tool_parameters
    assert "include_legend" not in renderer_parameters
    assert "basemaps.cartocdn.com/light_all" in html
    assert "Map Legend" not in html


def test_geojson_export_is_atomic_provenance_rich_and_non_mutating(
    tmp_path: Path,
    minimal_layers_data: dict,
) -> None:
    _, _, renderer = _load_map_modules()
    original = copy.deepcopy(minimal_layers_data)
    output = tmp_path / "layers.geojson"

    result = renderer.export_combined_geojson(
        minimal_layers_data,
        str(output),
        collection_metadata={
            "profile": "screening",
            "layers": {"roi": {"status": "ok"}},
        },
    )

    exported = json.loads(output.read_text(encoding="utf-8"))
    assert result == str(output)
    assert exported["metadata"]["profile"] == "screening"
    assert exported["metadata"]["layers"]["roi"]["status"] == "ok"
    assert exported["metadata"]["feature_count"] == 3
    assert {feature["properties"]["layer"] for feature in exported["features"]} == {
        "roi",
        "counties",
    }
    assert minimal_layers_data == original
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert not output.with_suffix(".geojson.tmp").exists()


def test_all_direct_requests_calls_declare_timeouts() -> None:
    source_paths = [
        ROOT / "map_composer" / "src" / "core" / "geometry_collector.py",
        ROOT / "map_composer" / "src" / "apis" / "counties_api.py",
        ROOT / "map_composer" / "src" / "apis" / "gbif_api.py",
    ]

    missing = []
    for path in source_paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if (
                node.func.attr in {"get", "post"}
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "requests"
                and not any(keyword.arg == "timeout" for keyword in node.keywords)
            ):
                missing.append(f"{path.name}:{node.lineno}")

    assert missing == []
