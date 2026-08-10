"""
Unit tests for the PCSRF API layer (``pcsrf/src/apis/pcsrf_api.py``).

These exercise the pure parsing/formatting logic with the ArcGIS query layer
mocked, so no network calls are made. They follow the same dynamic per-server
import pattern used by ``test_five_server_updates.py`` and
``test_point_buffer_area_rollout.py``.

PCSRF is one of the four ROI-AREA servers: critical-habitat polygons and
Atlantic-salmon EFH polygons clip their area to the requested ROI, while
critical-habitat lines keep a legacy source-coordinate length and the
projects/all-species-range tools are presence-only.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from nepa_mcp_common.arcgis import ArcGISFeatureQueryResult

ROOT = Path(__file__).resolve().parents[1]
# A West Coast ROI ring so PCSRF project coverage warnings are not triggered.
SIMPLE_GEOMETRY = {
    "rings": [[[-121.0, 46.0], [-120.0, 46.0], [-120.0, 47.0], [-121.0, 47.0], [-121.0, 46.0]]],
    "spatialReference": {"wkid": 4326},
}


def _load_pcsrf_api():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src."):
            sys.modules.pop(module_name, None)
    server_dir = ROOT / "pcsrf"
    sys.path.insert(0, str(server_dir))
    try:
        spec = importlib.util.spec_from_file_location(
            "_pcsrf_unit_api",
            server_dir / "src" / "apis" / "pcsrf_api.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules["_pcsrf_unit_api"] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(server_dir))


def _patch_roi(api, monkeypatch):
    monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", lambda *_a, **_k: SIMPLE_GEOMETRY)


def _patch_query(api, monkeypatch, feature_map, warnings=None, truncated=False):
    """Return features keyed by service_name/url substring."""

    def query_features(url, _layer_id, _geometry, *, service_name=None, **_kwargs):
        for key, feats in feature_map.items():
            if key in (service_name or "") or key in url:
                return ArcGISFeatureQueryResult(features=feats, warnings=warnings or [], truncated=truncated)
        return ArcGISFeatureQueryResult(features=[], warnings=warnings or [])

    monkeypatch.setattr(api.ArcGISService, "query_features", query_features)


def _ch_poly_feature(*, geometry=SIMPLE_GEOMETRY, area=999.0, unit="Unit A", entity="Test salmon DPS"):
    feature = {
        "attributes": {
            "COMNAME": "Test salmon",
            "SCIENAME": "Testus salmonus",
            "LISTENTITY": entity,
            "LISTSTATUS": "Threatened",
            "UNIT": unit,
            "AREASqKm": area,
            "HABTYPE": "Estuary",
        }
    }
    if geometry is not None:
        feature["geometry"] = geometry
    return feature


# ---------------------------------------------------------------------------
# Species ranges (presence-only)
# ---------------------------------------------------------------------------


class TestSpeciesRanges:
    def test_parses_range_fields(self, monkeypatch):
        api = _load_pcsrf_api()
        _patch_roi(api, monkeypatch)
        _patch_query(
            api,
            monkeypatch,
            {
                "species ranges": [
                    {
                        "attributes": {
                            "COMNAME": "Chinook salmon",
                            "SCIENAME": "Oncorhynchus tshawytscha",
                            "LISTENTITY": "Chinook salmon, Puget Sound ESU",
                            "DPSESU": "Puget Sound ESU",
                            "LISTSTATUS": "Threatened",
                            "TAXON": "Fish",
                        }
                    }
                ]
            },
        )
        result = api.get_species_ranges_in_roi(46.5, -120.5, 25.0)
        assert result["total"] == 1
        assert result["species_count"] == 1
        s = result["species"][0]
        assert s["listed_entity"] == "Chinook salmon, Puget Sound ESU"
        assert s["scientific_name"] == "Oncorhynchus tshawytscha"
        assert s["dps_esu"] == "Puget Sound ESU"
        # Presence-only: no area fields are added by the range parser.
        assert "area_sqkm" not in s
        assert result["center"] == {"latitude": 46.5, "longitude": -120.5}

    def test_deduplicates_by_listed_entity(self, monkeypatch):
        api = _load_pcsrf_api()
        _patch_roi(api, monkeypatch)
        feat = {"attributes": {"COMNAME": "Coho", "LISTENTITY": "Coho salmon ESU", "LISTSTATUS": "T"}}
        _patch_query(api, monkeypatch, {"species ranges": [feat, dict(feat), dict(feat)]})
        result = api.get_species_ranges_in_roi(46.5, -120.5)
        assert result["total"] == 1
        assert result["species_count"] == 1

    def test_empty_features_yields_zero(self, monkeypatch):
        api = _load_pcsrf_api()
        _patch_roi(api, monkeypatch)
        _patch_query(api, monkeypatch, {})
        result = api.get_species_ranges_in_roi(46.5, -120.5)
        assert result["total"] == 0
        assert result["species"] == []


# ---------------------------------------------------------------------------
# Critical habitat — polygon clipping + line legacy length + dedup
# ---------------------------------------------------------------------------


class TestCriticalHabitatDedupClip:
    def test_polygon_duplicate_fragments_unioned_and_source_retained(self):
        api = _load_pcsrf_api()
        feature = _ch_poly_feature()
        one = api._deduplicate_ch_fragments([feature], "polygon", roi_geometry=SIMPLE_GEOMETRY)[0]
        duplicate = api._deduplicate_ch_fragments([feature, feature], "polygon", roi_geometry=SIMPLE_GEOMETRY)[0]

        assert one["area_status"] == "ok"
        assert one["area_complete"] is True
        # Clipped area is derived from geometry, independent of the source attribute.
        assert one["area_sqkm"] > 0
        assert one["source_area_sqkm"] == 999.0
        # Union does not double-count overlapping duplicate geometry...
        assert duplicate["area_sqkm"] == one["area_sqkm"]
        # ...but source attributes accumulate across fragments.
        assert duplicate["source_area_sqkm"] == 1_998.0

    def test_distinct_units_are_kept_separate(self):
        api = _load_pcsrf_api()
        records = api._deduplicate_ch_fragments(
            [_ch_poly_feature(unit="Unit A"), _ch_poly_feature(unit="Unit B")],
            "polygon",
            roi_geometry=SIMPLE_GEOMETRY,
        )
        assert len(records) == 2
        assert {r["unit"] for r in records} == {"Unit A", "Unit B"}

    def test_line_records_remain_length_only(self):
        api = _load_pcsrf_api()
        record = api._deduplicate_ch_fragments(
            [{"attributes": {"LISTENTITY": "Test salmon DPS", "UNIT": "River", "Shape__Length": 1.0}}],
            "line",
            roi_geometry=SIMPLE_GEOMETRY,
        )[0]
        assert record["area_sqkm"] is None
        # 1.0 degree -> 111.0 km legacy estimate.
        assert record["length_km"] == 111.0
        # Lines get no clipped-area status.
        assert "area_status" not in record

    def test_missing_geometry_is_not_reported_as_zero_area(self):
        api = _load_pcsrf_api()
        record = api._deduplicate_ch_fragments(
            [_ch_poly_feature(geometry=None)],
            "polygon",
            roi_geometry=SIMPLE_GEOMETRY,
        )[0]
        assert record["area_sqkm"] is None
        assert record["source_area_sqkm"] == 999.0
        assert record["area_status"] == "no_geometry"
        assert record["area_complete"] is False

    def test_truncated_geometry_marks_area_incomplete(self):
        api = _load_pcsrf_api()
        record = api._deduplicate_ch_fragments(
            [_ch_poly_feature()],
            "polygon",
            roi_geometry=SIMPLE_GEOMETRY,
            geometry_complete=False,
        )[0]
        assert record["area_status"] == "ok"
        assert record["area_complete"] is False
        assert "may be understated" in record["area_warnings"][-1]

    def test_no_roi_preserves_legacy_source_area_semantics(self):
        api = _load_pcsrf_api()
        record = api._deduplicate_ch_fragments([_ch_poly_feature()], "polygon")[0]
        # Without an ROI, the polygon path falls back to source attribute area.
        assert record["area_status"] == "source_feature_attributes"
        assert record["area_complete"] is None
        assert record["area_sqkm"] == 999.0


class TestCriticalHabitatEndToEnd:
    def test_combines_polygon_and_line_layers(self, monkeypatch):
        api = _load_pcsrf_api()
        _patch_roi(api, monkeypatch)
        _patch_query(
            api,
            monkeypatch,
            {
                "polygons": [_ch_poly_feature(unit="Poly Unit")],
                "lines": [{"attributes": {"LISTENTITY": "Test salmon DPS", "UNIT": "River", "Shape__Length": 1.0}}],
            },
        )
        result = api.get_critical_habitat_in_roi(46.5, -120.5, 25.0)
        assert result["total"] == 2
        units = {h["unit"] for h in result["habitats"]}
        assert units == {"Poly Unit", "River"}
        # Line-length legacy warning is surfaced when a line record is present.
        assert any("legacy source-coordinate estimate" in w for w in result["warnings"])


# ---------------------------------------------------------------------------
# EFH — Atlantic salmon polygon clipping / grouping
# ---------------------------------------------------------------------------


class TestEFHParsing:
    def test_area_is_clipped_and_source_units_accumulate(self):
        api = _load_pcsrf_api()
        feature = {
            "attributes": {
                "GNIS_Name": "Atlantic salmon EFH",
                "TYPE": "EFH",
                "REGION": "GAR",
                "Shape__Area": 12345.0,
            },
            "geometry": SIMPLE_GEOMETRY,
        }
        clipped = api._parse_efh([feature, feature], roi_geometry=SIMPLE_GEOMETRY)[0]
        assert clipped["area_acres"] > 0
        assert clipped["area_status"] == "ok"
        assert clipped["area_sq_units"] == 24_690.0

    def test_missing_geometry_is_explicit(self):
        api = _load_pcsrf_api()
        feature = {
            "attributes": {"GNIS_Name": "Atlantic salmon EFH", "TYPE": "EFH", "REGION": "GAR", "Shape__Area": 1.0},
            "geometry": None,
        }
        record = api._parse_efh([feature], roi_geometry=SIMPLE_GEOMETRY)[0]
        assert record["area_acres"] is None
        assert record["area_status"] == "no_geometry"
        assert record["area_complete"] is False

    def test_parser_preserves_legacy_cardinality_without_roi(self):
        api = _load_pcsrf_api()
        features = [
            {
                "attributes": {
                    "GNIS_Name": "Atlantic salmon EFH",
                    "TYPE": "EFH",
                    "REGION": "GAR",
                    "LINK": f"https://example.test/{i}",
                    "BUFF_DIST": i,
                    "Shape__Area": float(i),
                }
            }
            for i in (1, 2)
        ]
        records = api._parse_efh(features)
        assert len(records) == 2
        assert all("area_status" not in r for r in records)

    def test_efh_end_to_end_sets_area_acres(self, monkeypatch):
        api = _load_pcsrf_api()
        _patch_roi(api, monkeypatch)
        _patch_query(
            api,
            monkeypatch,
            {
                "EFH": [
                    {
                        "attributes": {
                            "GNIS_Name": "Penobscot River",
                            "TYPE": "EFH",
                            "REGION": "GAR",
                            "Shape__Area": 5000.0,
                        },
                        "geometry": SIMPLE_GEOMETRY,
                    }
                ]
            },
        )
        result = api.get_efh_in_roi(44.8, -68.8, 25.0)
        assert result["total"] == 1
        assert result["efh_areas"][0]["area_acres"] > 0
        assert result["efh_areas"][0]["area_status"] == "ok"


# ---------------------------------------------------------------------------
# Projects (presence-only, with funding aggregation)
# ---------------------------------------------------------------------------


class TestProjects:
    def test_parses_projects_and_sums_funding(self, monkeypatch):
        api = _load_pcsrf_api()
        _patch_roi(api, monkeypatch)
        _patch_query(
            api,
            monkeypatch,
            {
                "projects": [
                    {
                        "attributes": {
                            "PROJECT_NAME": "Riparian Restoration",
                            "STATUS": "Completed",
                            "PCSRF_FUNDS": 100000.0,
                            "DESCRIPTION": "Planting native vegetation.",
                        }
                    },
                    {
                        "attributes": {
                            "PROJECT_NAME": "Fish Passage",
                            "STATUS": "Active",
                            "PCSRF_FUNDS": 250000.0,
                        }
                    },
                ]
            },
        )
        result = api.get_pcsrf_projects_in_roi(46.5, -120.5, 25.0)
        assert result["total"] == 2
        assert result["total_pcsrf_funding"] == 350000.0
        # Presence-only: no clipped-area fields on project records.
        assert all("area_sqkm" not in p for p in result["projects"])

    def test_missing_funding_defaults_to_zero(self, monkeypatch):
        api = _load_pcsrf_api()
        _patch_roi(api, monkeypatch)
        _patch_query(
            api,
            monkeypatch,
            {"projects": [{"attributes": {"PROJECT_NAME": "Unfunded", "STATUS": "Planned"}}]},
        )
        result = api.get_pcsrf_projects_in_roi(46.5, -120.5)
        assert result["total"] == 1
        assert result["total_pcsrf_funding"] == 0

    def test_empty_out_of_coverage_adds_warning(self, monkeypatch):
        api = _load_pcsrf_api()
        # Chicago-area ROI is outside the PCSRF project expected bounds.
        chicago = {
            "rings": [[[-88.0, 41.5], [-87.0, 41.5], [-87.0, 42.0], [-88.0, 42.0], [-88.0, 41.5]]],
            "spatialReference": {"wkid": 4326},
        }
        monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", lambda *_a, **_k: chicago)
        _patch_query(api, monkeypatch, {})
        result = api.get_pcsrf_projects_in_roi(41.8, -87.6)
        assert result["total"] == 0
        assert result.get("outside_expected_coverage") is True
        assert "coverage_warning" in result


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------


class TestFormatters:
    def test_ch_summary_labels_roi_area_and_source(self):
        api = _load_pcsrf_api()
        summary = api.format_critical_habitat_summary(
            {
                "center": {"latitude": 46.5, "longitude": -120.5},
                "buffer_miles": 5.0,
                "total": 2,
                "species_count": 1,
                "warnings": [],
                "habitats": [
                    {
                        "listed_entity": "Test salmon DPS",
                        "scientific_name": "Testus salmonus",
                        "listing_status": "Threatened",
                        "taxon": "fish",
                        "unit": "Polygon",
                        "habitat_type": "polygon",
                        "area_sqkm": 1.0,
                        "source_area_sqkm": 99.0,
                        "area_status": "ok",
                        "length_km": None,
                    },
                    {
                        "listed_entity": "Test salmon DPS",
                        "scientific_name": "Testus salmonus",
                        "listing_status": "Threatened",
                        "taxon": "fish",
                        "unit": "River",
                        "habitat_type": "line",
                        "area_sqkm": None,
                        "length_km": 12.5,
                    },
                ],
            }
        )
        assert "1.0 sq km within ROI" in summary
        assert "Source feature-area total (not clipped to ROI): 99.0 sq km" in summary
        assert "12.5 km (legacy estimate; not ROI-clipped)" in summary
        assert "ESA Section 7" in summary

    def test_ch_summary_handles_empty(self):
        api = _load_pcsrf_api()
        summary = api.format_critical_habitat_summary(
            {
                "center": {"latitude": 46.5, "longitude": -120.5},
                "buffer_miles": 5.0,
                "total": 0,
                "species_count": 0,
                "warnings": [],
                "habitats": [],
            }
        )
        assert "No NOAA critical habitat found within the ROI." in summary

    def test_efh_summary_labels_partial_area(self):
        api = _load_pcsrf_api()
        summary = api.format_efh_summary(
            {
                "center": {"latitude": 44.8, "longitude": -68.8},
                "buffer_miles": 5.0,
                "total": 1,
                "warnings": [],
                "efh_areas": [
                    {
                        "gnis_name": "Atlantic salmon EFH",
                        "type": "EFH",
                        "region": "GAR",
                        "area_acres": 12.5,
                        "area_status": "ok",
                        "area_complete": False,
                    }
                ],
            }
        )
        assert "Partial area within ROI: 12.50 acres" in summary
        assert "Magnuson-Stevens Act" in summary

    def test_projects_summary_groups_by_status(self):
        api = _load_pcsrf_api()
        summary = api.format_pcsrf_projects_summary(
            {
                "center": {"latitude": 46.5, "longitude": -120.5},
                "buffer_miles": 5.0,
                "total": 1,
                "total_pcsrf_funding": 100000.0,
                "warnings": [],
                "projects": [
                    {
                        "project_name": "Riparian Restoration",
                        "status": "Completed",
                        "pcsrf_funds": 100000.0,
                        "description": "Planting native vegetation.",
                    }
                ],
            }
        )
        assert "PCSRF Salmon Recovery Projects" in summary
        assert "Total PCSRF funding:** $100,000.00" in summary
        assert "### Completed (1 projects)" in summary
        assert "Riparian Restoration" in summary

    def test_projects_summary_surfaces_coverage_warning(self):
        api = _load_pcsrf_api()
        summary = api.format_pcsrf_projects_summary(
            {
                "center": {"latitude": 41.8, "longitude": -87.6},
                "buffer_miles": 25.0,
                "total": 0,
                "total_pcsrf_funding": 0,
                "warnings": [],
                "coverage_warning": "The queried area is outside the expected geographic coverage.",
                "projects": [],
            }
        )
        assert "Warning: The queried area is outside the expected" in summary
        assert "No PCSRF projects found within the ROI." in summary

    def test_species_ranges_summary_renders(self):
        api = _load_pcsrf_api()
        summary = api.format_species_ranges_summary(
            {
                "center": {"latitude": 46.5, "longitude": -120.5},
                "buffer_miles": 5.0,
                "total": 1,
                "species_count": 1,
                "warnings": [],
                "species": [
                    {
                        "listed_entity": "Chinook salmon ESU",
                        "scientific_name": "Oncorhynchus tshawytscha",
                        "listing_status": "Threatened",
                        "dps_esu": "Puget Sound ESU",
                    }
                ],
            }
        )
        assert "NOAA ESA-Listed Species Ranges" in summary
        assert "Chinook salmon ESU" in summary
        assert "Puget Sound ESU" in summary
