"""
Resilience tests for the EFH API layer.

Verify graceful behavior when the upstream ArcGIS service errors, times out,
returns malformed payloads, or truncates results. The shared ArcGISService is
mocked to simulate each failure mode. Note: the EFH ``_query_layer`` swallows
query exceptions and returns them as warnings, so a downed service degrades to
an empty-but-usable result rather than raising.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from nepa_mcp_common.arcgis import ArcGISFeatureQueryResult

ROOT = Path(__file__).resolve().parents[1]
SIMPLE_GEOMETRY = {
    "rings": [[[-121.0, 46.0], [-120.0, 46.0], [-120.0, 47.0], [-121.0, 47.0], [-121.0, 46.0]]],
    "spatialReference": {"wkid": 4326},
}


def _load_efh_api():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src."):
            sys.modules.pop(module_name, None)
    server_dir = ROOT / "efh"
    sys.path.insert(0, str(server_dir))
    try:
        spec = importlib.util.spec_from_file_location("_efh_resilience_api", server_dir / "src" / "apis" / "efh_api.py")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules["_efh_resilience_api"] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(server_dir))


def _patch_roi(api, monkeypatch):
    monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", lambda *_a, **_k: SIMPLE_GEOMETRY)


def _efh_feature(*, geometry=SIMPLE_GEOMETRY, acres=999.0):
    feature = {
        "attributes": {
            "SITENAME_L": "Pacific Coast Groundfish",
            "LIFESTAGE": "ALL",
            "TYPE": "EFH",
            "FMC": "PFMC",
            "ZONE": "ALL",
            "ACRES": acres,
        }
    }
    if geometry is not None:
        feature["geometry"] = geometry
    return feature


class TestUpstreamQueryFailure:
    def test_query_failure_degrades_to_warning(self, monkeypatch):
        api = _load_efh_api()
        _patch_roi(api, monkeypatch)

        def boom(*_a, **_k):
            raise RuntimeError("EFH HAPC upstream 500")

        monkeypatch.setattr(api.ArcGISService, "query_features", boom)
        # _query_layer catches the exception and returns it as a warning.
        result = api.get_hapc_in_roi(46.5, -120.5)
        assert result["total"] == 0
        assert any("layer query failed" in w for w in result["warnings"])

    def test_buffer_creation_failure_returns_empty_result(self, monkeypatch):
        api = _load_efh_api()
        monkeypatch.setattr(
            api.ArcGISService,
            "create_roi_buffer",
            lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("buffer boom")),
        )
        result = api.get_efh_areas_in_roi(46.5, -120.5)
        assert result["total"] == 0
        assert result["efh_areas"] == []
        assert result.get("error")


class TestDegradedButUsable:
    def test_warnings_are_carried_through(self, monkeypatch):
        api = _load_efh_api()
        _patch_roi(api, monkeypatch)

        def query_features(*_a, **_k):
            return ArcGISFeatureQueryResult(
                features=[{"attributes": {"HAPC_Siten": "Estuaries", "FisheryM_5": "PFMC"}}],
                warnings=["reached the feature safety cap; results are partial."],
                truncated=True,
            )

        monkeypatch.setattr(api.ArcGISService, "query_features", query_features)
        result = api.get_hapc_in_roi(46.5, -120.5)
        assert result["total"] == 1
        assert any("safety cap" in w for w in result["warnings"])

    def test_empty_features_is_not_an_error(self, monkeypatch):
        api = _load_efh_api()
        _patch_roi(api, monkeypatch)
        monkeypatch.setattr(
            api.ArcGISService,
            "query_features",
            lambda *_a, **_k: ArcGISFeatureQueryResult(features=[], warnings=[]),
        )
        result = api.get_salmon_efh_in_roi(46.5, -120.5)
        assert result["total"] == 0
        assert result["watersheds"] == []


class TestHmsAreaResilience:
    def test_truncation_marks_area_incomplete_and_warns(self, monkeypatch):
        api = _load_efh_api()
        _patch_roi(api, monkeypatch)
        monkeypatch.setattr(
            api.ArcGISService,
            "query_features",
            lambda *_a, **_k: ArcGISFeatureQueryResult(features=[_efh_feature()], warnings=[], truncated=True),
        )
        result = api.get_hms_cps_groundfish_efh_in_roi(46.5, -120.5)
        assert result["efh_areas"][0]["area_complete"] is False
        assert any("understated" in w for w in result["warnings"])

    def test_missing_geometry_is_no_geometry_not_zero(self, monkeypatch):
        api = _load_efh_api()
        _patch_roi(api, monkeypatch)
        monkeypatch.setattr(
            api.ArcGISService,
            "query_features",
            lambda *_a, **_k: ArcGISFeatureQueryResult(features=[_efh_feature(geometry=None)], warnings=[]),
        )
        result = api.get_hms_cps_groundfish_efh_in_roi(46.5, -120.5)
        entry = result["efh_areas"][0]
        assert entry["acres"] is None
        assert entry["area_status"] == "no_geometry"
        assert entry["source_acres"] == 999.0


class TestMalformedFeatures:
    def test_feature_without_attributes_key(self, monkeypatch):
        api = _load_efh_api()
        _patch_roi(api, monkeypatch)
        monkeypatch.setattr(
            api.ArcGISService,
            "query_features",
            lambda *_a, **_k: ArcGISFeatureQueryResult(features=[{}], warnings=[]),
        )
        # HAPC groups by (species, fmc) -> one empty-species entry; does not crash.
        result = api.get_hapc_in_roi(46.5, -120.5)
        assert result["total"] == 1

    def test_null_attribute_values_do_not_crash(self, monkeypatch):
        api = _load_efh_api()
        _patch_roi(api, monkeypatch)
        monkeypatch.setattr(
            api.ArcGISService,
            "query_features",
            lambda *_a, **_k: ArcGISFeatureQueryResult(
                features=[{"attributes": {"SITENAME_L": None, "TYPE": None, "FMC_REPORT": None}}],
                warnings=[],
            ),
        )
        result = api.get_efh_areas_in_roi(46.5, -120.5)
        assert result["total"] == 1

    def test_salmon_feature_with_null_huc_is_skipped(self, monkeypatch):
        api = _load_efh_api()
        _patch_roi(api, monkeypatch)
        monkeypatch.setattr(
            api.ArcGISService,
            "query_features",
            lambda *_a, **_k: ArcGISFeatureQueryResult(
                features=[{"attributes": {"HUC_8": None, "HUC_8_Name": "Nowhere"}}], warnings=[]
            ),
        )
        result = api.get_salmon_efh_in_roi(46.5, -120.5)
        assert result["total"] == 0
