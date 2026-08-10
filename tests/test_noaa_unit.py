"""
Unit tests for the NOAA WCR critical habitat API layer
(``noaa/src/apis/noaa_api.py``).

These exercise the pure de-duplication, area-clipping, and formatting logic
with the ArcGIS query layer mocked, so no network calls are made. They follow
the dynamic per-server import pattern used by ``test_five_server_updates.py``.

NOAA is one of the four ROI-AREA servers. It exposes a single tool,
``get_noaa_critical_habitat_in_roi``. Layer 1 (lines) keeps its source length;
layer 2 (polygons) receives geometry so the union-and-clip path runs and area
is measured within the ROI. Diced fragments are de-duplicated by listed entity.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from nepa_mcp_common.arcgis import ArcGISFeatureQueryResult

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "noaa"
# A small ROI over the NOAA West Coast Region service geography (PNW).
SIMPLE_GEOMETRY = {
    "rings": [[[-121.0, 46.0], [-120.0, 46.0], [-120.0, 47.0], [-121.0, 47.0], [-121.0, 46.0]]],
    "spatialReference": {"wkid": 4326},
}


def _load_noaa_api():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src."):
            sys.modules.pop(module_name, None)
    sys.path.insert(0, str(SERVER_DIR))
    try:
        spec = importlib.util.spec_from_file_location(
            "_noaa_unit_api",
            SERVER_DIR / "src" / "apis" / "noaa_api.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules["_noaa_unit_api"] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(SERVER_DIR))


def _patch_roi(api, monkeypatch):
    monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", lambda *_a, **_k: SIMPLE_GEOMETRY)


def _polygon_feature(
    *, entity="Test whale DPS", unit="Unit A", area=99_999.0, geometry=SIMPLE_GEOMETRY, comname="Test whale"
):
    feature = {
        "attributes": {
            "comname": comname,
            "sciename": "Testus whaleus",
            "listentity": entity,
            "liststatus": "Endangered",
            "unit": unit,
            "taxon": "Marine mammal",
            "areasqkm": area,
            "frn": "80 FR 1",
        }
    }
    if geometry is not None:
        feature["geometry"] = geometry
    return feature


def _line_feature(*, entity="Test salmon DPS", unit="River Reach", length=12.5, comname="Test salmon"):
    return {
        "attributes": {
            "comname": comname,
            "sciename": "Testus salmonus",
            "listentity": entity,
            "liststatus": "Threatened",
            "unit": unit,
            "taxon": "Fish",
            "lengthkm": length,
            "frn": "75 FR 2",
        }
    }


# ---------------------------------------------------------------------------
# Deduplication of diced fragments (layer-agnostic behavior)
# ---------------------------------------------------------------------------


class TestDeduplication:
    def test_fragments_collapse_to_one_entity_and_preserve_units(self):
        api = _load_noaa_api()
        features = [
            _polygon_feature(unit="Unit A", area=1.25),
            _polygon_feature(unit="Unit B", area=2.75),
        ]
        deduped = api._deduplicate_fragments(features, 2, "polygon")
        assert len(deduped) == 1
        assert deduped[0]["units"] == ["Unit A", "Unit B"]
        assert deduped[0]["unit_count"] == 2
        # Without an ROI, the source-attribute area is summed and retained.
        assert deduped[0]["area_sqkm"] == 4.0

    def test_distinct_entities_stay_separate(self):
        api = _load_noaa_api()
        features = [
            _polygon_feature(entity="Whale A DPS", unit="Unit A"),
            _polygon_feature(entity="Whale B DPS", unit="Unit B"),
        ]
        deduped = api._deduplicate_fragments(features, 2, "polygon")
        assert len(deduped) == 2
        assert {h["listed_entity"] for h in deduped} == {"Whale A DPS", "Whale B DPS"}

    def test_blank_units_are_not_counted(self):
        api = _load_noaa_api()
        features = [
            _polygon_feature(unit=""),
            _polygon_feature(unit="   "),
        ]
        deduped = api._deduplicate_fragments(features, 2, "polygon")
        assert deduped[0]["units"] == []
        assert deduped[0]["unit_count"] == 0

    def test_missing_listentity_groups_under_empty_key(self):
        api = _load_noaa_api()
        features = [
            {"attributes": {"comname": "Anon", "unit": "U1", "areasqkm": 1.0}},
            {"attributes": {"comname": "Anon", "unit": "U2", "areasqkm": 2.0}},
        ]
        deduped = api._deduplicate_fragments(features, 2, "polygon")
        assert len(deduped) == 1
        assert deduped[0]["listed_entity"] == ""
        assert deduped[0]["units"] == ["U1", "U2"]


# ---------------------------------------------------------------------------
# Polygon area clipping (layer 2)
# ---------------------------------------------------------------------------


class TestPolygonClipping:
    def test_clipped_area_is_less_than_source_and_source_retained(self):
        api = _load_noaa_api()
        feature = _polygon_feature(area=99_999.0)
        one = api._deduplicate_fragments([feature], 2, "polygon", roi_geometry=SIMPLE_GEOMETRY)[0]
        assert one["area_status"] == "ok"
        assert one["area_sqkm"] > 0
        assert one["area_sqkm"] < one["source_area_sqkm"]
        assert one["source_area_sqkm"] == 99_999.0
        assert one["area_complete"] is True

    def test_duplicate_fragments_do_not_inflate_clipped_area(self):
        api = _load_noaa_api()
        feature = _polygon_feature(area=99_999.0)
        one = api._deduplicate_fragments([feature], 2, "polygon", roi_geometry=SIMPLE_GEOMETRY)[0]
        duplicate = api._deduplicate_fragments([feature, feature], 2, "polygon", roi_geometry=SIMPLE_GEOMETRY)[0]
        # Union collapses identical geometry -> same clipped area,
        # but the source attribute total does double (provenance only).
        assert duplicate["area_sqkm"] == one["area_sqkm"]
        assert duplicate["source_area_sqkm"] == 199_998.0

    def test_missing_geometry_does_not_masquerade_as_clipped_zero(self):
        api = _load_noaa_api()
        habitat = api._deduplicate_fragments(
            [_polygon_feature(area=42.0, geometry=None)],
            2,
            "polygon",
            roi_geometry=SIMPLE_GEOMETRY,
        )[0]
        assert habitat["area_sqkm"] is None
        assert habitat["source_area_sqkm"] == 42.0
        assert habitat["area_status"] == "no_geometry"
        assert habitat["area_complete"] is False
        assert any("No feature polygon geometries" in w for w in habitat["area_warnings"])

    def test_without_roi_falls_back_to_source_attribute_area(self):
        api = _load_noaa_api()
        habitat = api._deduplicate_fragments([_polygon_feature(area=42.0)], 2, "polygon")[0]
        # No ROI supplied -> legacy source-attribute area, flagged as such.
        assert habitat["area_sqkm"] == 42.0
        assert habitat["source_area_sqkm"] == 42.0
        assert habitat["area_status"] == "source_feature_attributes"
        assert habitat["area_complete"] is None
        assert habitat["area_warnings"] == []


# ---------------------------------------------------------------------------
# Line-vs-polygon behavior (layer 1)
# ---------------------------------------------------------------------------


class TestLineLayer:
    def test_lines_keep_source_length_and_no_area(self):
        api = _load_noaa_api()
        habitat = api._deduplicate_fragments([_line_feature(length=12.5)], 1, "line")[0]
        assert habitat["length_km"] == 12.5
        assert habitat["area_sqkm"] is None
        # Lines never take an area_status / source_area_sqkm.
        assert "area_status" not in habitat
        assert "source_area_sqkm" not in habitat

    def test_line_fragments_sum_length_per_entity(self):
        api = _load_noaa_api()
        features = [_line_feature(length=10.0, unit="A"), _line_feature(length=5.0, unit="B")]
        habitat = api._deduplicate_fragments(features, 1, "line")[0]
        assert habitat["length_km"] == 15.0
        assert habitat["units"] == ["A", "B"]

    def test_zero_length_line_normalizes_to_none(self):
        api = _load_noaa_api()
        habitat = api._deduplicate_fragments([_line_feature(length=0.0)], 1, "line")[0]
        assert habitat["length_km"] is None


# ---------------------------------------------------------------------------
# Truncation / skipped-fragment area completeness flags
# ---------------------------------------------------------------------------


class TestAreaCompleteness:
    def test_truncated_geometry_marks_area_incomplete(self):
        api = _load_noaa_api()
        habitat = api._deduplicate_fragments(
            [_polygon_feature(area=42.0)],
            2,
            "polygon",
            roi_geometry=SIMPLE_GEOMETRY,
            geometry_complete=False,
        )[0]
        assert habitat["area_status"] == "ok"
        assert habitat["area_complete"] is False
        assert "may be understated" in habitat["area_warnings"][-1]

    def test_line_path_fragment_in_polygon_layer_marks_incomplete(self):
        api = _load_noaa_api()
        valid = _polygon_feature(area=42.0)
        invalid = {
            "attributes": {"listentity": "Test whale DPS", "areasqkm": 2.0},
            "geometry": {"paths": [[[0.0, 0.0], [1.0, 1.0]]]},
        }
        habitat = api._deduplicate_fragments([valid, invalid], 2, "polygon", roi_geometry=SIMPLE_GEOMETRY)[0]
        assert habitat["area_status"] == "ok"
        assert habitat["area_complete"] is False
        assert any("Line paths" in w for w in habitat["area_warnings"])


# ---------------------------------------------------------------------------
# Layer query orchestration: geometry requested only for polygon layer
# ---------------------------------------------------------------------------


class TestLayerQueryOrchestration:
    def test_geometry_only_requested_for_polygon_layer(self, monkeypatch):
        api = _load_noaa_api()
        calls: dict[int, dict] = {}

        def query_features(_url, layer_id, _geometry, **kwargs):
            calls[layer_id] = kwargs
            features = [_polygon_feature(area=99_999.0)] if layer_id == 2 else []
            return ArcGISFeatureQueryResult(features=features, warnings=[])

        monkeypatch.setattr(api.ArcGISService, "query_features", query_features)
        habitats, warnings = api._query_noaa_ch_layers(SIMPLE_GEOMETRY)

        assert warnings == []
        assert calls[1]["return_geometry"] is False
        assert calls[1]["out_sr"] is None
        assert calls[2]["return_geometry"] is True
        assert calls[2]["out_sr"] == 4326
        assert calls[2]["simplify_geometry"] is False
        assert habitats[0]["area_status"] == "ok"
        assert habitats[0]["area_complete"] is True

    def test_top_level_aggregates_species_and_unit_counts(self, monkeypatch):
        api = _load_noaa_api()
        _patch_roi(api, monkeypatch)

        def query_features(_url, layer_id, _geometry, **_kwargs):
            if layer_id == 2:
                return ArcGISFeatureQueryResult(
                    features=[
                        _polygon_feature(entity="Whale A DPS", unit="Unit A", area=10.0),
                        _polygon_feature(entity="Whale B DPS", unit="Unit B", area=20.0),
                    ],
                    warnings=[],
                )
            return ArcGISFeatureQueryResult(features=[], warnings=[])

        monkeypatch.setattr(api.ArcGISService, "query_features", query_features)
        result = api.get_noaa_critical_habitat_in_roi(46.5, -120.5, 5.0)
        assert result["total"] == 2
        assert result["species_count"] == 2
        assert result["named_unit_count"] == 2
        assert result["center"] == {"latitude": 46.5, "longitude": -120.5}


# ---------------------------------------------------------------------------
# Formatter provenance labeling
# ---------------------------------------------------------------------------


class TestFormatter:
    def _base(self, habitats):
        return {
            "center": {"latitude": 46.5, "longitude": -120.5},
            "buffer_miles": 5.0,
            "total": len(habitats),
            "species_count": len({h["listed_entity"] for h in habitats}),
            "named_unit_count": 0,
            "habitats": habitats,
            "warnings": [],
        }

    def test_clipped_area_labeled_explicitly(self):
        api = _load_noaa_api()
        summary = api.format_noaa_critical_habitat_summary(
            self._base(
                [
                    {
                        "listed_entity": "Test whale DPS",
                        "scientific_name": "Testus whaleus",
                        "listing_status": "Endangered",
                        "taxon": "Marine mammal",
                        "units": ["Unit A"],
                        "area_sqkm": 1.25,
                        "source_area_sqkm": 42.0,
                        "area_status": "ok",
                        "length_km": None,
                        "federal_register": "",
                    }
                ]
            )
        )
        assert "Area within ROI: 1.25 sq km" in summary
        assert "Source feature-area total (not clipped to ROI): 42.0 sq km" in summary
        assert "Combined intersecting extent" not in summary

    def test_unavailable_area_and_source_line_length(self):
        api = _load_noaa_api()
        summary = api.format_noaa_critical_habitat_summary(
            self._base(
                [
                    {
                        "listed_entity": "Test salmon DPS",
                        "scientific_name": "Testus salmonus",
                        "listing_status": "Threatened",
                        "taxon": "Fish",
                        "units": [],
                        "area_sqkm": None,
                        "area_status": "no_geometry",
                        "length_km": None,
                        "federal_register": "",
                    },
                    {
                        "listed_entity": "Test salmon DPS",
                        "scientific_name": "Testus salmonus",
                        "listing_status": "Threatened",
                        "taxon": "Fish",
                        "units": [],
                        "area_sqkm": None,
                        "length_km": 12.5,
                        "federal_register": "",
                    },
                ]
            )
        )
        assert "Area within ROI: unavailable (no_geometry)" in summary
        assert "Intersecting line-feature length (source attribute): 12.5 km" in summary

    def test_legacy_source_area_visible_when_no_clip_status(self):
        api = _load_noaa_api()
        summary = api.format_noaa_critical_habitat_summary(
            self._base(
                [
                    {
                        "listed_entity": "Legacy whale DPS",
                        "scientific_name": "Testus whaleus",
                        "listing_status": "Endangered",
                        "taxon": "Marine mammal",
                        "units": [],
                        "area_sqkm": 42.0,
                        "length_km": None,
                        "federal_register": "",
                    }
                ]
            )
        )
        assert "Reported polygon area (source attribute): 42.0 sq km" in summary

    def test_empty_result_shows_coverage_note(self):
        api = _load_noaa_api()
        summary = api.format_noaa_critical_habitat_summary(
            {
                "center": {"latitude": 46.5, "longitude": -120.5},
                "buffer_miles": 5.0,
                "total": 0,
                "species_count": 0,
                "named_unit_count": 0,
                "habitats": [],
                "warnings": [],
            }
        )
        assert "No NOAA West Coast Region critical habitat was identified" in summary
        assert "West Coast Region designations only" in summary

    def test_federal_register_notices_rendered(self):
        api = _load_noaa_api()
        summary = api.format_noaa_critical_habitat_summary(
            self._base(
                [
                    {
                        "listed_entity": "Test whale DPS",
                        "scientific_name": "Testus whaleus",
                        "listing_status": "Endangered",
                        "taxon": "Marine mammal",
                        "units": ["Unit A"],
                        "area_sqkm": 1.0,
                        "source_area_sqkm": 2.0,
                        "area_status": "ok",
                        "length_km": None,
                        "federal_register": "80 FR 1234",
                    }
                ]
            )
        )
        assert "Federal Register Notices:" in summary
        assert "80 FR 1234" in summary
        assert "ESA Section 7 Note" in summary
