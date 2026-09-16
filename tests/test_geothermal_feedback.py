"""Regression tests for geothermal practitioner feedback: source contracts and interpretation."""

import copy
import importlib
import inspect
import json
import re
import sys
from pathlib import Path

import pytest
from shapely.geometry import box, mapping

from nepa_mcp.loader import load_server_module as _load_server
from nepa_mcp_common.arcgis import ArcGISFeatureQueryResult
from nepa_mcp_common.land_status import designation_details, padus_conflict


@pytest.fixture(autouse=True)
def isolate_server_paths():
    original = list(sys.path)
    yield
    sys.path[:] = original
    for name in tuple(sys.modules):
        if name == "src" or name.startswith("src."):
            sys.modules.pop(name, None)


def load_server_module(name):
    directory = str(Path(__file__).resolve().parents[1] / name)
    sys.path[:] = [entry for entry in sys.path if entry != directory]
    return _load_server(name)


def modules():
    server = load_server_module("map_composer")
    return (
        server,
        importlib.import_module("src.core.geometry_collector"),
        importlib.import_module("src.core.land_layers"),
    )


def esri(x=0, y=0, size=1):
    return {
        "rings": [[[x, y], [x, y + size], [x + size, y + size], [x + size, y], [x, y]]],
        "spatialReference": {"wkid": 4326},
    }


def feature(attrs=None, geometry=None):
    return {"attributes": attrs or {}, "geometry": geometry or esri()}


def query_result(features, partial=False):
    return ArcGISFeatureQueryResult(
        features=features, warnings=["Source truncated"] if partial else [], truncated=partial
    )


def test_geothermal_profile_matches_practitioner_document():
    server, collector, _ = modules()
    chosen = server._resolve_layers("geothermal", None)
    assert chosen == [
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
    ]
    assert len(chosen) == len(set(chosen)) == 21
    renderer = importlib.import_module("src.core.map_renderer")
    assert set(chosen) <= set(renderer.LAYER_ORDER)
    assert set(collector.DEFAULT_LAYERS) <= set(renderer.LAYER_CONFIG)


@pytest.mark.parametrize(
    "layer",
    [
        "blm_wilderness_areas",
        "blm_national_conservation_areas",
        "padus_designations",
        "blm_geothermal_leases",
    ],
)
def test_removed_overlays_are_not_advertised_or_selectable(layer):
    server, collector, _ = modules()
    chosen = server._resolve_layers("geothermal", None)
    assert layer not in chosen
    assert layer not in server._resolve_layers("full", None)
    assert len(collector.DEFAULT_LAYERS) == 32
    assert layer not in server.LAYER_METADATA
    assert layer not in server.LAYER_SOURCE_URLS
    assert layer not in server.list_available_layers()
    renderer = importlib.import_module("src.core.map_renderer")
    assert layer not in renderer.LAYER_CONFIG
    assert layer not in renderer.LAYER_ORDER
    with pytest.raises(ValueError, match="Unknown Map Composer"):
        server._resolve_layers("geothermal", chosen + [layer])
    assert server._resolve_layers("geothermal", None) == chosen


def test_existing_nps_layer_and_standalone_servers_remain_available():
    server, _, _ = modules()
    assert "nps_boundaries" in server._resolve_layers("full", None)
    assert "nps_boundaries" in server._resolve_layers("lands", None)
    assert "nps_boundaries" not in server._resolve_layers("geothermal", None)
    assert callable(load_server_module("blm").get_blm_wilderness_areas_in_roi_tool)
    assert callable(load_server_module("blm_mlrs").get_blm_mlrs_energy_leases_in_roi_tool)


def test_removed_lease_map_option_is_not_in_tool_signatures():
    server, collector, _ = modules()
    for function in (server.compose_environmental_map, server.export_all_layers_geojson, collector.collect_all_layers):
        assert "geothermal_dispositions" not in inspect.signature(function).parameters


@pytest.mark.parametrize("method", ["get_blm_wilderness_study_areas_geojson", "get_blm_national_monuments_geojson"])
def test_nlcs_keeps_separate_parts_and_does_not_simplify_query(monkeypatch, method):
    _, collector, _ = modules()
    seen = {}

    def query(url, params, **kwargs):
        seen.update(params)
        return query_result(
            [
                feature({"NLCS_NAME": "Same", "NCA_NAME": "Same", "NLCS_ID": "1"}),
                feature({"NLCS_NAME": "Same", "NCA_NAME": "Same", "NLCS_ID": "1"}, esri(2)),
            ]
        )

    monkeypatch.setattr(collector, "_query_arcgis_features", query)
    result = getattr(collector, method)(esri())
    assert len(result["features"]) == 2
    assert json.loads(seen["geometry"]) == esri()
    assert "maxAllowableOffset" not in seen


@pytest.mark.parametrize(
    "layer",
    ["blm_wilderness_study_areas", "blm_national_monuments"],
)
@pytest.mark.parametrize(
    "geometry_fields",
    [
        pytest.param({}, id="missing-geometry"),
        pytest.param({"geometry": None}, id="null-geometry"),
        pytest.param({"geometry": {}}, id="empty-geometry"),
        pytest.param({"geometry": {"rings": []}}, id="empty-rings"),
    ],
)
@pytest.mark.parametrize("include_valid", [False, True], ids=["all-unavailable", "mixed"])
def test_nlcs_missing_geometry_is_partial_through_collection_and_summary(
    monkeypatch, layer, geometry_fields, include_valid
):
    server, collector, _ = modules()
    attrs = {"NLCS_NAME": "Example WSA", "NCA_NAME": "Example NCA", "NLCS_ID": "example", "sma_code": "BLM_NCA"}
    features = [{"attributes": dict(attrs), **geometry_fields}]
    if include_valid:
        features.append(feature(dict(attrs)))
    upstream = query_result(features, partial=True)
    original = copy.deepcopy(upstream)
    monkeypatch.setattr(collector.ArcGISService, "create_roi_buffer", lambda *a, **k: esri())
    monkeypatch.setattr(collector, "_query_arcgis_features", lambda *a, **k: upstream)

    collection = collector.collect_all_layers(0.5, 0.5, 1, layers=[layer])

    status = collection.statuses[layer]
    assert status["status"] == collection.layers[layer]["status"] == "partial"
    assert status["feature_count"] == len(collection.layers[layer]["features"]) == int(include_valid)
    assert "Source truncated" in status["warnings"]
    assert any("Dropped 1 feature(s)" in warning for warning in status["warnings"])
    summary = "\n".join(server._summary_lines(collection))
    assert "(partial)" in summary and "Dropped 1 feature(s)" in summary
    if include_valid:
        props = collection.layers[layer]["features"][0]["properties"]
        assert props["nlcs_id"] == "example"
        assert props["project_relation"] == "unknown_incomplete_source"
    assert upstream == original


@pytest.mark.parametrize(
    "layer",
    ["blm_wilderness_study_areas", "blm_national_monuments"],
)
@pytest.mark.parametrize("include_valid", [False, True], ids=["all-unavailable", "mixed"])
def test_nlcs_null_geometry_alone_marks_result_partial(monkeypatch, layer, include_valid):
    _, collector, _ = modules()
    attrs = {"NLCS_NAME": "WSA", "NCA_NAME": "NCA", "NLCS_ID": "example", "sma_code": "BLM_NCA"}
    features = [{"attributes": dict(attrs), "geometry": None}]
    if include_valid:
        features.append(feature(dict(attrs)))
    monkeypatch.setattr(collector.ArcGISService, "create_roi_buffer", lambda *a, **k: esri())
    monkeypatch.setattr(collector, "_query_arcgis_features", lambda *a, **k: query_result(features))

    collection = collector.collect_all_layers(0.5, 0.5, 1, layers=[layer])

    assert collection.statuses[layer]["status"] == "partial"
    assert collection.statuses[layer]["feature_count"] == int(include_valid)
    assert len(collection.statuses[layer]["warnings"]) == 1
    if include_valid:
        assert collection.layers[layer]["features"][0]["properties"]["project_relation"] == "unknown_incomplete_source"


@pytest.mark.parametrize(
    "layer",
    ["blm_wilderness_study_areas", "blm_national_monuments"],
)
@pytest.mark.parametrize("include_valid", [False, True], ids=["empty", "valid"])
def test_nlcs_complete_empty_and_valid_results_remain_distinct(monkeypatch, layer, include_valid):
    _, collector, _ = modules()
    attrs = {"NLCS_NAME": "WSA", "NCA_NAME": "NCA", "NLCS_ID": "example", "sma_code": "BLM_NCA"}
    monkeypatch.setattr(collector.ArcGISService, "create_roi_buffer", lambda *a, **k: esri())
    monkeypatch.setattr(
        collector, "_query_arcgis_features", lambda *a, **k: query_result([feature(attrs)] if include_valid else [])
    )

    collection = collector.collect_all_layers(0.5, 0.5, 1, layers=[layer])

    assert collection.statuses[layer]["status"] == ("ok" if include_valid else "empty")
    assert collection.statuses[layer]["feature_count"] == int(include_valid)
    assert collection.statuses[layer]["warnings"] == []
    if include_valid:
        assert collection.layers[layer]["features"][0]["properties"]["project_relation"] == "contained"


def test_nca_null_code_uses_verified_identifier_and_unknowns_stay_unknown(monkeypatch):
    _, collector, _ = modules()
    monkeypatch.setattr(
        collector,
        "_query_arcgis_features",
        lambda *a, **k: query_result(
            [
                feature({"NCA_NAME": "Numunaa Nobe", "NLCS_ID": "NLCS000607", "sma_code": None}),
                feature({"NCA_NAME": "Unknown", "NLCS_ID": "other", "sma_code": None}),
                feature({"NCA_NAME": "Monument", "sma_code": "BLM_NM"}),
            ]
        ),
    )
    result = collector.get_blm_national_monuments_geojson(esri())
    assert len(result["features"]) == 3
    props = result["features"][0]["properties"]
    assert props["sma_code"] is None
    assert props["designation_type"] == "national_conservation_area"
    assert "460hhhh" in props["classification_authority"]
    assert result["status"] == "ok"
    assert result["features"][1]["properties"]["designation_type"] == "unclassified"
    assert result["features"][2]["properties"]["designation_type"] == "national_monument"
    assert designation_details({"NCA_NAME": "Numunaa Nobe"})["designation_type"] == "unclassified"


@pytest.mark.parametrize("name", ["Clan Alpine Mountains", "Stillwater Range", "Job Peak"])
def test_padus_conflicts_are_cited_and_do_not_rewrite_source(name):
    attrs = {"Unit_Nm": name + " Wilderness Study Area", "Mang_Name": "BLM", "Des_Tp": "WSA", "Date_Est": "1992"}
    original = dict(attrs)
    result = padus_conflict(attrs)
    assert "potentially outdated" in result["designation_conflict"]
    assert "117-263" in result["conflict_provisions"]
    assert attrs == original
    assert not padus_conflict({**attrs, "Mang_Name": "USFS"})
    assert not padus_conflict({**attrs, "Des_Tp": "WILD"})
    assert not padus_conflict({**attrs, "Unit_Nm": "Unverified WSA"})


def test_standalone_padus_keeps_conflict_warnings_and_map_composer_keeps_fee(monkeypatch):
    _, collector, _ = modules()
    assert collector.PADUS_LAYER_ID == 0
    assert "PAD_US_4_1" in collector.PADUS_URL
    load_server_module("padus")
    api = importlib.import_module("src.apis.padus_api")
    attrs = {
        "Unit_Nm": "Job Peak Wilderness Study Area",
        "Mang_Name": "BLM",
        "Des_Tp": "WSA",
        "Category": "Designation",
    }
    monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", lambda *a, **k: esri())
    monkeypatch.setattr(api.ArcGISService, "query_features", lambda *a, **k: query_result([feature(attrs)]))
    result = api.get_padus_in_roi(0.5, 0.5, 1)
    assert result["records"][0]["designation_type"] == "WSA"
    assert "potentially outdated" in result["records"][0]["designation_conflict"]
    assert result["warnings"]


@pytest.mark.parametrize("partial", [False, True])
def test_failed_or_partial_upstream_never_becomes_clean_empty(monkeypatch, partial):
    _, collector, _ = modules()

    def query(*a, **k):
        if partial:
            return query_result([], partial=True)
        raise RuntimeError("ArcGIS error 400 Invalid URL")

    monkeypatch.setattr(collector, "_query_arcgis_features", query)
    result = collector.get_blm_wilderness_study_areas_geojson(esri())
    assert result["status"] == ("partial" if partial else "failed")
    assert result["warnings"]


@pytest.mark.parametrize(
    "target,expected",
    [
        (box(0.1, 0.1, 0.9, 0.9), "contained"),
        (box(0.5, 0.5, 1.5, 1.5), "overlap"),
        (box(1, 0, 2, 1), "boundary_touch"),
        (box(2, 0, 3, 1), "outside"),
    ],
)
def test_boundary_relation_is_about_footprint_not_buffer(target, expected):
    _, _, land = modules()
    layer = "blm_national_monuments"
    data = {layer: {"features": [{"geometry": mapping(box(0, 0, 1, 1)), "properties": {"nlcs_id": "1"}}]}}
    statuses = {layer: {"status": "ok"}}
    land.annotate_land_relations(data, statuses, 0.5, 0.5, target)
    props = data[layer]["features"][0]["properties"]
    assert props["project_relation"] == expected
    assert props["relation_target"] == "project_footprint"


def test_boundary_union_includes_all_parts_but_respects_holes_and_partial_sources():
    _, _, land = modules()
    layer = "blm_wilderness_study_areas"
    data = {
        layer: {
            "features": [
                {"geometry": mapping(box(0, 0, 1, 1)), "properties": {"nlcs_id": "1"}},
                {"geometry": mapping(box(1, 0, 2, 1)), "properties": {"nlcs_id": "1"}},
            ]
        }
    }
    statuses = {layer: {"status": "ok"}}
    land.annotate_land_relations(data, statuses, 0, 0, box(0.5, 0.1, 1.5, 0.9))
    assert all(f["properties"]["project_relation"] == "contained" for f in data[layer]["features"])
    data[layer]["features"] = [{"geometry": mapping(box(0, 0, 3, 3).difference(box(1, 1, 2, 2))), "properties": {}}]
    land.annotate_land_relations(data, statuses, 1.5, 1.5)
    assert data[layer]["features"][0]["properties"]["project_relation"] == "outside"
    statuses[layer]["status"] = "partial"
    land.annotate_land_relations(data, statuses, 1.5, 1.5)
    assert data[layer]["features"][0]["properties"]["project_relation"] == "unknown_incomplete_source"


def test_footprint_validation_and_search_coverage(monkeypatch):
    _, collector, land = modules()
    valid = json.loads(json.dumps(mapping(box(0.1, 0.1, 0.9, 0.9))))
    assert land.validate_project_geometry(valid).area > 0
    for geometry in [
        {"type": "Point", "coordinates": [0, 0]},
        {"type": "Polygon", "coordinates": []},
        {"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [float("nan"), 1], [0, 0]]]},
    ]:
        with pytest.raises(ValueError):
            land.validate_project_geometry(geometry)
    monkeypatch.setattr(collector.ArcGISService, "create_roi_buffer", lambda *a, **k: esri())
    with pytest.raises(ValueError, match="contained in the search buffer"):
        collector.collect_all_layers(0.5, 0.5, 1, layers=[], project_geometry=mapping(box(2, 2, 3, 3)))


def test_collector_and_export_preserve_footprint_relations(monkeypatch, tmp_path):
    _, collector, _ = modules()
    monkeypatch.setattr(collector.ArcGISService, "create_roi_buffer", lambda *a, **k: esri(-1, -1, 4))
    monkeypatch.setattr(
        collector,
        "_query_arcgis_features",
        lambda *a, **k: query_result([feature({"NLCS_NAME": "Test WSA", "NLCS_ID": "test"})]),
    )
    footprint = json.loads(json.dumps(mapping(box(0.1, 0.1, 0.9, 0.9))))
    collection = collector.collect_all_layers(
        0.5, 0.5, 1, layers=["roi", "blm_wilderness_study_areas"], project_geometry=footprint
    )
    assert collection.statuses["roi"]["feature_count"] == 3
    properties = collection.layers["blm_wilderness_study_areas"]["features"][0]["properties"]
    assert properties["project_relation"] == "contained"
    assert properties["relation_target"] == "project_footprint"
    renderer = importlib.import_module("src.core.map_renderer")
    path = renderer.export_combined_geojson(collection.layers, str(tmp_path / "land.geojson"))
    exported = json.loads(Path(path).read_text())
    assert any(f["properties"].get("project_relation") == "contained" for f in exported["features"])
    assert any(f["geometry"] == footprint for f in exported["features"])


@pytest.mark.parametrize(
    "bad_ring",
    [
        None,
        [],
        [[0.2, 0.2], [0.8, 0.8]],
        [[0.2, 0.2], [0.5, 0.5], [0.8, 0.8]],
        [[0.2, 0.2], [0.8, 0.8], [0.2, 0.8], [0.9, 0.2], [0.2, 0.2]],
        [[0.2, 0.2], [0.8, float("nan")], [0.8, 0.8], [0.2, 0.2]],
        [[0.2, 0.2], [float("inf"), 0.8], [0.8, 0.8], [0.2, 0.2]],
        [[0.2, 0.2], ["bad", 0.8], [0.8, 0.8], [0.2, 0.2]],
        [[0.2, 0.2], [False, 0.8], [0.8, 0.8], [0.2, 0.2]],
        [[0.2, 0.2], [0.8], [0.8, 0.8], [0.2, 0.2]],
    ],
)
@pytest.mark.parametrize("bad_first", [False, True])
def test_polygon_conversion_rejects_whole_feature_if_any_ring_is_unusable(bad_ring, bad_first):
    _, collector, _ = modules()
    rings = [esri()["rings"][0], bad_ring]
    if bad_first:
        rings.reverse()
    assert collector.esri_to_geojson_geometry({"rings": rings}, "esriGeometryPolygon") is None


@pytest.mark.parametrize("geometry", [None, "not geometry", {"rings": "not rings"}, {"rings": {"0": []}}])
def test_polygon_conversion_rejects_invalid_containers(geometry):
    _, collector, _ = modules()
    assert collector.esri_to_geojson_geometry(geometry, "esriGeometryPolygon") is None


def test_polygon_conversion_rejects_overlapping_rings_but_preserves_nested_parts():
    _, collector, _ = modules()
    assert (
        collector.esri_to_geojson_geometry(
            {"rings": [esri()["rings"][0], esri(0.5, 0.5)["rings"][0]]}, "esriGeometryPolygon"
        )
        is None
    )
    rings = [esri(size=4)["rings"][0], esri(1, 1, 2)["rings"][0], esri(1.5, 1.5, 0.5)["rings"][0]]
    original = copy.deepcopy(rings)
    converted = collector.esri_to_geojson_geometry({"rings": rings}, "esriGeometryPolygon")
    assert converted == {"type": "MultiPolygon", "coordinates": [[rings[0], rings[1]], [rings[2]]]}
    assert rings == original


@pytest.mark.parametrize(
    "layer",
    [
        "blm_wilderness_study_areas",
        "blm_national_monuments",
    ],
)
@pytest.mark.parametrize("include_valid", [False, True], ids=["all-unavailable", "mixed"])
def test_bad_ring_marks_land_collection_partial_without_containment_claims(monkeypatch, layer, include_valid):
    server, collector, _ = modules()
    attrs = {"NLCS_NAME": "Unit", "NCA_NAME": "Unit", "NLCS_ID": "unit", "sma_code": "BLM_NCA", "CSE_NR": "NV1"}
    bad_geometry = esri()
    bad_geometry["rings"].append([[0.4, 0.4], [0.6, 0.6]])
    records = [feature(dict(attrs), bad_geometry)]
    if include_valid:
        records.append(feature(dict(attrs)))
    original = copy.deepcopy(records)
    monkeypatch.setattr(collector.ArcGISService, "create_roi_buffer", lambda *a, **k: esri())
    monkeypatch.setattr(collector, "_query_arcgis_features", lambda *a, **k: query_result(records))

    collection = collector.collect_all_layers(
        0.5, 0.5, 1, layers=[layer], project_geometry=mapping(box(0.45, 0.45, 0.55, 0.55))
    )

    assert collection.statuses[layer]["status"] == "partial"
    assert collection.statuses[layer]["feature_count"] == int(include_valid)
    assert any("Dropped 1 feature(s)" in warning for warning in collection.warnings)
    assert "(partial)" in "\n".join(server._summary_lines(collection))
    if include_valid:
        props = collection.layers[layer]["features"][0]["properties"]
        assert props["project_relation"] == "unknown_incomplete_source"
        assert props["relation_target"] == "project_footprint"
    assert records == original


def detailed_footprint(multipart=False):
    # Both collinear vertices and a small notch must survive rendering unchanged.
    polygon = [
        [[0.1, 0.1], [0.1, 0.5], [0.1, 0.9], [0.5, 0.9], [0.9, 0.9], [0.9, 0.1], [0.5001, 0.1001], [0.1, 0.1]],
        [[0.3, 0.3], [0.7, 0.3], [0.7, 0.7], [0.5, 0.7], [0.3, 0.7], [0.3, 0.3]],
    ]
    if multipart:
        return {"type": "MultiPolygon", "coordinates": [polygon, esri(1.2, 1.2, 0.2)["rings"]]}
    return {"type": "Polygon", "coordinates": polygon}


@pytest.mark.parametrize("multipart", [False, True])
@pytest.mark.parametrize(
    "layer",
    [
        "roi",
        "blm_wilderness_study_areas",
        "blm_national_monuments",
    ],
)
def test_html_preserves_exact_footprint_and_land_boundary_coordinates(tmp_path, layer, multipart):
    modules()
    renderer = importlib.import_module("src.core.map_renderer")
    geometry = detailed_footprint(multipart)
    data = {
        layer: {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": geometry,
                    "properties": {"name": "Project Footprint", "type": "Project Footprint"},
                }
            ],
        }
    }
    original = copy.deepcopy(data)
    output = tmp_path / "exact-boundaries.html"

    renderer.render_environmental_map(data, 0.5, 0.5, str(output))

    payloads = re.findall(r"geo_json_\w+_add\((\{[^\n]+\})\);", output.read_text())
    assert len(payloads) == 1
    rendered = json.loads(payloads[0])
    assert rendered["features"][0]["geometry"] == geometry
    assert data == original


def test_nonboundary_layers_can_still_simplify_without_mutating_source():
    modules()
    renderer = importlib.import_module("src.core.map_renderer")
    data = {
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "geometry": detailed_footprint(), "properties": {}}],
    }
    original = copy.deepcopy(data)
    simplified = renderer.simplify_geojson(data)
    assert simplified["features"][0]["geometry"] != data["features"][0]["geometry"]
    assert data == original


@pytest.mark.parametrize("include_roi", [False, True])
@pytest.mark.parametrize("footprint_kind", ["point", "polygon", "multipolygon"])
def test_export_tool_records_footprint_independently_of_roi_selection(
    monkeypatch, tmp_path, include_roi, footprint_kind
):
    server, collector, _ = modules()
    monkeypatch.setattr(collector.ArcGISService, "create_roi_buffer", lambda *a, **k: esri(-1, -1, 4))
    monkeypatch.setattr(
        collector, "_query_arcgis_features", lambda *a, **k: query_result([feature({"NLCS_ID": "unit"})])
    )
    output = tmp_path / "footprint-export.geojson"
    monkeypatch.setattr(server, "_artifact_path", lambda **kwargs: output)
    selected = (["roi"] if include_roi else []) + ["blm_wilderness_study_areas"]
    footprint = None if footprint_kind == "point" else detailed_footprint(footprint_kind == "multipolygon")
    original = copy.deepcopy(footprint)

    server.export_all_layers_geojson(0.5, 0.5, 1, layers=selected, project_geometry=footprint)

    exported = json.loads(output.read_text())
    assert exported["metadata"]["project_geometry"] == original
    expected_target = "project_point" if footprint is None else "project_footprint"
    assert exported["metadata"]["relation_target"] == expected_target
    assert exported["metadata"]["selected_layers"] == selected
    assert {f["properties"]["layer"] for f in exported["features"]} == set(selected)
    assert all(
        f["properties"]["relation_target"] == expected_target
        for f in exported["features"]
        if f["properties"]["layer"] != "roi"
    )
    assert footprint == original


def test_collection_and_metadata_take_independent_footprint_snapshots(monkeypatch):
    server, collector, _ = modules()
    monkeypatch.setattr(collector.ArcGISService, "create_roi_buffer", lambda *a, **k: esri(-1, -1, 4))
    footprint = detailed_footprint()
    original = copy.deepcopy(footprint)
    collection = collector.collect_all_layers(0.5, 0.5, 1, layers=["roi"], project_geometry=footprint)
    metadata = server._collection_metadata(
        collection=collection, latitude=0.5, longitude=0.5, buffer_miles=1, profile="custom", selected_layers=["roi"]
    )
    footprint["coordinates"][0][0][0] = 42
    collection.layers["roi"]["features"][-1]["geometry"]["coordinates"][0][1][0] = 43
    assert collection.project_geometry == original
    assert metadata["project_geometry"] == original
    metadata["project_geometry"]["coordinates"][0][2][0] = 44
    assert collection.project_geometry == original


def test_nca_api_filter_keeps_null_code_verified_nca(monkeypatch):
    server = load_server_module("blm")
    api = importlib.import_module("src.apis.blm_api")
    monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", lambda *a: esri())
    monkeypatch.setattr(
        api.ArcGISService,
        "query_features",
        lambda *a, **k: query_result(
            [
                feature({"NCA_NAME": "Numunaa Nobe", "NLCS_ID": "NLCS000607", "sma_code": None}),
                feature({"NCA_NAME": "Other", "NLCS_ID": "x", "sma_code": None}),
            ]
        ),
    )
    result = api.get_blm_national_monuments_in_roi(0, 0, designation_type="national_conservation_area")
    assert len(result["national_conservation_areas"]) == result["total"] == 1
    assert result["warnings"]
    text = server.get_blm_national_monuments_in_roi_tool(0, 0, designation_type="national_conservation_area")
    assert "Numunaa Nobe" in text and "460hhhh" in text


def test_mlrs_energy_case_name_and_null_expiration_are_explicit():
    load_server_module("blm_mlrs")
    api = importlib.import_module("src.apis.blm_mlrs_api")
    attrs = {"CSE_NR": "NV1", "CSE_NAME": "Dixie Example", "CSE_DISP": "Authorized", "EXP_DT": None}
    record = api._parse_record(attrs, api.GEOTHERMAL_SOURCE)
    assert "CSE_NAME" in api.GEOTHERMAL_SOURCE.fields
    assert record["case_name"] == "Dixie Example"
    assert "expiration date not reported by source" in api._format_record(record)
    assert "Authorized" in api._format_record(record)


@pytest.mark.parametrize(
    "ratings,shares,hydric,unknown",
    [
        (["Yes", "No"], [20, 80], 20, 0),
        (["Yes", "Not rated", "No"], [20, 30, 50], 20, 30),
        (["Yes"], [20], 20, 80),
        (["Not rated"], [100], 0, 100),
        (["Yes"], [None], None, None),
        (["Yes", "No"], [80, 80], None, None),
        (["Yes"], [-2], None, None),
        ([], [], None, None),
    ],
)
def test_hydric_percentages_do_not_normalize_unknowns(ratings, shares, hydric, unknown):
    load_server_module("nrcs_soils")
    api = importlib.import_module("src.apis.nrcs_soils_api")
    result = {"mapunits": [{"mukey": "1"}]}
    components = [
        {"mukey": "1", "cokey": str(i), "name": "Soil", "hydric_rating": rating, "component_percentage": share}
        for i, (rating, share) in enumerate(zip(ratings, shares))
    ]
    original = copy.deepcopy(components)
    api._attach_hydric_ratings(result, components, partial=False)
    rating = result["mapunits"][0]["hydric"]
    assert rating["hydric_percentage"] == hydric
    assert rating["unknown_percentage"] == unknown
    assert rating["rating_complete"] == (hydric is not None and unknown == 0)
    assert components == original
    if unknown or hydric is None:
        assert rating["rating_class"] == "Incomplete or unavailable"


def test_truncated_hydric_components_are_not_a_complete_rating():
    load_server_module("nrcs_soils")
    api = importlib.import_module("src.apis.nrcs_soils_api")
    result = {"mapunits": [{"mukey": "1"}]}
    api._attach_hydric_ratings(
        result, [{"mukey": "1", "cokey": "1", "hydric_rating": "No", "component_percentage": 100}], partial=True
    )
    assert result["mapunits"][0]["hydric"]["hydric_percentage"] is None
