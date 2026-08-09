"""
Unit tests for the esa_ranges API layer (``esa_ranges/src/apis/esa_ranges_api.py``).

These exercise the pure parsing / dedup / clipping / merge logic with the ArcGIS
query layer mocked, so no network calls are made. They follow the same dynamic
per-server import pattern used by ``test_five_server_updates.py`` and add the
broader unit coverage around the cases already exercised there.

esa_ranges is one of the four ROI-AREA servers. It exposes a single tool and
queries two complementary NOAA ``Ranges_dice`` layers:
  * Layer 2 (``ESA_RANGES_LAYER_ID``): CA + southern OR
  * Layer 1 (``ESA_RANGES_FISH_LAYER_ID``): WA/ID/OR + transboundary fish
Range records are de-duplicated on (listed_entity, huc12), watershed geometry is
clipped/unioned to the ROI, and the two layers are merged with Layer 2 winning
on collision (which flags ``area_complete=False``).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from nepa_mcp_common.arcgis import ArcGISFeatureQueryResult

ROOT = Path(__file__).resolve().parents[1]
# A West-Coast ROI so the empty-result coverage warning never fires for these
# hermetic tests (the geometry intersects NOAA_WEST_COAST_EXPECTED_BOUNDS).
SIMPLE_GEOMETRY = {
    "rings": [[[-121.0, 46.0], [-120.0, 46.0], [-120.0, 47.0], [-121.0, 47.0], [-121.0, 46.0]]],
    "spatialReference": {"wkid": 4326},
}


def _load_esa_api():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src."):
            sys.modules.pop(module_name, None)
    server_dir = ROOT / "esa_ranges"
    sys.path.insert(0, str(server_dir))
    try:
        spec = importlib.util.spec_from_file_location(
            "_esa_ranges_unit_api",
            server_dir / "src" / "apis" / "esa_ranges_api.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules["_esa_ranges_unit_api"] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(server_dir))


def _patch_roi(api, monkeypatch):
    monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", lambda *_a, **_k: SIMPLE_GEOMETRY)


def _patch_query_by_layer(api, monkeypatch, layer_features, warnings=None, truncated=False):
    """Return features keyed by layer_id (Layer 2 == ESA_RANGES_LAYER_ID)."""

    def query_features(_url, layer_id, _geometry, **_kwargs):
        feats = layer_features.get(layer_id, [])
        return ArcGISFeatureQueryResult(
            features=feats,
            warnings=warnings or [],
            truncated=truncated and bool(feats),
        )

    monkeypatch.setattr(api.ArcGISService, "query_features", query_features)


def _layer2_feature(*, listentity="STUCR", huc12="170200160601", area=999.0, geometry=SIMPLE_GEOMETRY, **extra):
    attrs = {
        "listentity": listentity,
        "liststatus": "T",
        "sciename": "3",
        "comname": "ST",
        "taxon": "3",
        "leadoffice": "WCR",
        "areasqkm": area,
        "huc12": huc12,
        "huc12_name": "Parsons Canyon-Columbia River",
        "feature_access": "AC",
    }
    attrs.update(extra)
    feature = {"attributes": attrs}
    if geometry is not None:
        feature["geometry"] = geometry
    return feature


def _layer1_feature(
    *,
    dps="Steelhead (Puget Sound DPS)",
    dps_id="STPUG",
    huc12="171100020101",
    area=42.5,
    geometry=SIMPLE_GEOMETRY,
    **extra,
):
    attrs = {
        "dps": dps,
        "dps_id": dps_id,
        "species": "ST",
        "listing_status": "T",
        "hydrologic_huc_12": huc12,
        "hydrologic_hu_12_name": "Puget Sound",
        "hydrologic_hu_area_sqkm": area,
        "link_feature_access": "AC",
    }
    attrs.update(extra)
    feature = {"attributes": attrs}
    if geometry is not None:
        feature["geometry"] = geometry
    return feature


# ---------------------------------------------------------------------------
# Coded-value decoding
# ---------------------------------------------------------------------------


class TestDecode:
    def test_decodes_known_code(self):
        api = _load_esa_api()
        assert api._decode("T", api._LISTSTATUS) == "Threatened"
        assert api._decode("3", api._SCIENAME) == "Oncorhynchus mykiss"
        assert api._decode("WCR", api._LEADOFFICE) == "West Coast Region"

    def test_unknown_code_returns_raw_value(self):
        api = _load_esa_api()
        assert api._decode("ZZZ", api._LISTSTATUS) == "ZZZ"

    def test_empty_value_returns_empty_string(self):
        api = _load_esa_api()
        assert api._decode("", api._LISTSTATUS) == ""


# ---------------------------------------------------------------------------
# Layer 2 dedup + clipping (_deduplicate_ranges)
# ---------------------------------------------------------------------------


class TestDeduplicateRanges:
    def test_parses_and_decodes_fields(self):
        api = _load_esa_api()
        record = api._deduplicate_ranges([_layer2_feature()], roi_geometry=SIMPLE_GEOMETRY)[0]
        assert record["listed_entity"] == "Steelhead (Upper Columbia River DPS)"
        assert record["listing_status"] == "Threatened"
        assert record["scientific_name"] == "Oncorhynchus mykiss"
        assert record["taxon"] == "fish"
        assert record["lead_office"] == "West Coast Region"
        assert record["feature_access"] == "Accessible"
        assert record["huc12"] == "170200160601"

    def test_duplicate_fragments_union_area_and_retain_source(self):
        api = _load_esa_api()
        feature = _layer2_feature()
        one = api._deduplicate_ranges([feature], roi_geometry=SIMPLE_GEOMETRY)[0]
        duplicate = api._deduplicate_ranges([feature, feature], roi_geometry=SIMPLE_GEOMETRY)[0]
        assert one["area_status"] == "ok"
        assert one["area_complete"] is True
        assert one["area_sqkm"] > 0
        # Union clip is identical, but the reported source area sums fragments.
        assert duplicate["area_sqkm"] == one["area_sqkm"]
        assert duplicate["source_area_sqkm"] == 1_998.0

    def test_distinct_hucs_are_separate_records(self):
        api = _load_esa_api()
        result = api._deduplicate_ranges(
            [_layer2_feature(huc12="111111111111"), _layer2_feature(huc12="222222222222")],
            roi_geometry=SIMPLE_GEOMETRY,
        )
        assert len(result) == 2
        assert {r["huc12"] for r in result} == {"111111111111", "222222222222"}

    def test_missing_geometry_is_not_zero_area(self):
        api = _load_esa_api()
        record = api._deduplicate_ranges([_layer2_feature(geometry=None)], roi_geometry=SIMPLE_GEOMETRY)[0]
        assert record["area_sqkm"] is None
        assert record["source_area_sqkm"] == 999.0
        assert record["area_status"] == "no_geometry"
        assert record["area_complete"] is False

    def test_no_roi_geometry_uses_source_area(self):
        api = _load_esa_api()
        record = api._deduplicate_ranges([_layer2_feature()])[0]
        assert record["area_status"] == "source_feature_attributes"
        assert record["area_sqkm"] == 999.0
        assert record["area_complete"] is None

    def test_truncation_marks_incomplete(self):
        api = _load_esa_api()
        record = api._deduplicate_ranges([_layer2_feature()], roi_geometry=SIMPLE_GEOMETRY, geometry_complete=False)[0]
        assert record["area_status"] == "ok"
        assert record["area_complete"] is False
        assert any("may be understated" in w for w in record["area_warnings"])


# ---------------------------------------------------------------------------
# Layer 1 normalization (_normalize_layer1)
# ---------------------------------------------------------------------------


class TestNormalizeLayer1:
    def test_maps_layer1_fields_onto_common_shape(self):
        api = _load_esa_api()
        record = api._normalize_layer1([_layer1_feature()], roi_geometry=SIMPLE_GEOMETRY)[0]
        assert record["listed_entity"] == "Steelhead (Puget Sound DPS)"
        assert record["listed_entity_code"] == "STPUG"
        assert record["scientific_name"] == "Oncorhynchus mykiss"
        assert record["common_name"] == "Steelhead"
        assert record["taxon"] == "fish"
        assert record["lead_office"] == "West Coast Region"

    def test_repeated_huc_area_uses_max_not_sum(self):
        api = _load_esa_api()
        base = dict(dps="Steelhead (Puget Sound DPS)", dps_id="STPUG", huc12="171100020101", area=42.5)
        record = api._normalize_layer1(
            [
                _layer1_feature(**{**base, "population": "A"}),
                _layer1_feature(**{**base, "population": "B"}),
            ]
        )[0]
        # Whole-HUC area repeated across population rows must not be multiplied.
        assert record["source_area_sqkm"] == 42.5

    def test_dps_id_falls_back_to_decoded_listentity(self):
        api = _load_esa_api()
        # No explicit "dps" string -> decode dps_id via _LISTENTITY.
        record = api._normalize_layer1([_layer1_feature(dps=None, dps_id="STPUG")], roi_geometry=SIMPLE_GEOMETRY)[0]
        assert record["listed_entity"] == "Steelhead (Puget Sound DPS)"


# ---------------------------------------------------------------------------
# Layer merge (_merge_ranges): Layer 2 wins, collision flags incomplete
# ---------------------------------------------------------------------------


class TestMergeRanges:
    def test_layer2_wins_on_collision_and_flags_incomplete(self):
        api = _load_esa_api()
        key_kwargs = dict(dps="Steelhead (Upper Columbia River DPS)", dps_id="STUCR", huc12="170200160601")
        layer1 = api._normalize_layer1([_layer1_feature(**key_kwargs)], roi_geometry=SIMPLE_GEOMETRY)
        layer2 = api._deduplicate_ranges([_layer2_feature(notes="layer-2-authoritative")], roi_geometry=SIMPLE_GEOMETRY)
        merged = api._merge_ranges(layer2, layer1)
        assert len(merged) == 1
        winner = merged[0]
        assert winner["notes"] == "layer-2-authoritative"
        assert winner["area_complete"] is False
        assert any("Both NOAA ESA range layers" in w for w in winner["area_warnings"])

    def test_layer1_only_record_is_preserved(self):
        api = _load_esa_api()
        layer1 = api._normalize_layer1([_layer1_feature()], roi_geometry=SIMPLE_GEOMETRY)
        merged = api._merge_ranges([], layer1)
        assert len(merged) == 1
        assert merged[0]["listed_entity"] == "Steelhead (Puget Sound DPS)"

    def test_disjoint_keys_are_both_kept(self):
        api = _load_esa_api()
        layer1 = api._normalize_layer1(
            [_layer1_feature(dps="Steelhead (Puget Sound DPS)", dps_id="STPUG", huc12="171100020101")],
            roi_geometry=SIMPLE_GEOMETRY,
        )
        layer2 = api._deduplicate_ranges(
            [_layer2_feature(listentity="STUCR", huc12="170200160601")], roi_geometry=SIMPLE_GEOMETRY
        )
        merged = api._merge_ranges(layer2, layer1)
        assert len(merged) == 2


# ---------------------------------------------------------------------------
# Full get_esa_species_ranges_in_roi orchestration
# ---------------------------------------------------------------------------


class TestGetRangesInRoi:
    def test_queries_both_layers_and_layer2_wins(self, monkeypatch):
        api = _load_esa_api()
        _patch_roi(api, monkeypatch)
        _patch_query_by_layer(
            api,
            monkeypatch,
            {
                api.ESA_RANGES_LAYER_ID: [_layer2_feature(notes="layer-2-authoritative")],
                api.ESA_RANGES_FISH_LAYER_ID: [
                    _layer1_feature(dps="Steelhead (Upper Columbia River DPS)", dps_id="STUCR", huc12="170200160601")
                ],
            },
        )
        result = api.get_esa_species_ranges_in_roi(46.47, -119.30, 5.0)
        assert result["total"] == 1
        assert result["species"][0]["notes"] == "layer-2-authoritative"
        assert result["species"][0]["area_complete"] is False
        assert result["species_count"] == 1
        assert result["watershed_count"] == 1

    def test_counts_unique_entities_and_watersheds(self, monkeypatch):
        api = _load_esa_api()
        _patch_roi(api, monkeypatch)
        _patch_query_by_layer(
            api,
            monkeypatch,
            {
                api.ESA_RANGES_LAYER_ID: [
                    _layer2_feature(listentity="STUCR", huc12="111111111111"),
                    _layer2_feature(listentity="STUCR", huc12="222222222222"),
                    _layer2_feature(listentity="STPUG", huc12="222222222222"),
                ],
                api.ESA_RANGES_FISH_LAYER_ID: [],
            },
        )
        result = api.get_esa_species_ranges_in_roi(46.47, -119.30, 5.0)
        assert result["total"] == 3
        assert result["species_count"] == 2  # STUCR, STPUG
        assert result["watershed_count"] == 2  # two distinct HUC-12s

    def test_empty_both_layers_yields_zero(self, monkeypatch):
        api = _load_esa_api()
        _patch_roi(api, monkeypatch)
        _patch_query_by_layer(api, monkeypatch, {api.ESA_RANGES_LAYER_ID: [], api.ESA_RANGES_FISH_LAYER_ID: []})
        result = api.get_esa_species_ranges_in_roi(46.47, -119.30, 5.0)
        assert result["total"] == 0
        assert result["species"] == []


# ---------------------------------------------------------------------------
# Formatter
# ---------------------------------------------------------------------------


class TestFormatter:
    def test_renders_header_and_section7_note(self):
        api = _load_esa_api()
        summary = api.format_esa_species_ranges_summary(
            {
                "center": {"latitude": 46.5, "longitude": -120.5},
                "buffer_miles": 5.0,
                "total": 1,
                "species_count": 1,
                "watershed_count": 1,
                "warnings": [],
                "species": [
                    {
                        "listed_entity": "Test salmon DPS",
                        "scientific_name": "Testus salmonus",
                        "listing_status": "Threatened",
                        "taxon": "fish",
                        "huc12": "123",
                        "huc12_name": "Test watershed",
                        "feature_access": "",
                        "area_sqkm": 1.25,
                        "source_area_sqkm": 99.0,
                        "area_status": "ok",
                    }
                ],
            }
        )
        assert "NOAA ESA Species Ranges" in summary
        assert "Area within ROI: 1.2 sq km" in summary
        assert "Source watershed-area total (not clipped to ROI): 99.0 sq km" in summary
        assert "ESA Section 7 Note" in summary

    def test_empty_species_renders_scope_note(self):
        api = _load_esa_api()
        summary = api.format_esa_species_ranges_summary(
            {
                "center": {"latitude": 40.0, "longitude": -100.0},
                "buffer_miles": 25.0,
                "total": 0,
                "species_count": 0,
                "watershed_count": 0,
                "warnings": [],
                "species": [],
            }
        )
        assert "No NOAA ESA-listed species ranges found within the ROI." in summary
        assert "out-of-scope" in summary

    def test_partial_area_label_when_incomplete(self):
        api = _load_esa_api()
        summary = api.format_esa_species_ranges_summary(
            {
                "center": {"latitude": 46.5, "longitude": -120.5},
                "buffer_miles": 5.0,
                "total": 1,
                "species_count": 1,
                "watershed_count": 1,
                "warnings": [],
                "species": [
                    {
                        "listed_entity": "Test salmon DPS",
                        "scientific_name": "Testus salmonus",
                        "listing_status": "Threatened",
                        "taxon": "fish",
                        "huc12": "123",
                        "huc12_name": "Test watershed",
                        "feature_access": "",
                        "area_sqkm": 1.25,
                        "source_area_sqkm": 99.0,
                        "area_status": "ok",
                        "area_complete": False,
                    }
                ],
            }
        )
        assert "Partial area within ROI" in summary

    def test_warnings_and_error_surface(self):
        api = _load_esa_api()
        summary = api.format_esa_species_ranges_summary(
            {
                "center": {"latitude": 46.5, "longitude": -120.5},
                "buffer_miles": 5.0,
                "total": 0,
                "species_count": 0,
                "watershed_count": 0,
                "warnings": ["upstream degraded"],
                "error": "buffer creation failed",
                "species": [],
            }
        )
        assert "Warning: upstream degraded" in summary
        assert "Warning: buffer creation failed" in summary
