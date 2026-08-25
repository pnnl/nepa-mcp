"""
Resilience tests for the EPA ACRES API layer.

Verify behavior when the upstream EPA ArcGIS layer errors, times out, or
returns malformed payloads. The shared ArcGISService is mocked to simulate
each failure mode.

Unlike ``nrhp`` (two layers, per-layer try/except), ``epa_acres`` queries a
single layer and never propagates the failure: a raised query is caught and
converted into a ``data_unavailable`` result whose formatter output shows the
unavailable banner INSTEAD of the "No ACRES Brownfields properties" no-hit
sentence. These tests assert that behavior.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from nepa_mcp_common.arcgis import ArcGISFeatureQueryResult

ROOT = Path(__file__).resolve().parents[1]
SIMPLE_GEOMETRY = {
    "rings": [[[-80.1, 40.3], [-79.9, 40.3], [-79.9, 40.5], [-80.1, 40.5], [-80.1, 40.3]]],
    "spatialReference": {"wkid": 4326},
}


def _load_acres_api():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src."):
            sys.modules.pop(module_name, None)
    server_dir = ROOT / "epa_acres"
    sys.path.insert(0, str(server_dir))
    try:
        spec = importlib.util.spec_from_file_location(
            "_epa_acres_resilience_api", server_dir / "src" / "apis" / "acres_api.py"
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules["_epa_acres_resilience_api"] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(server_dir))


def _patch_roi(api, monkeypatch):
    monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", lambda *_a, **_k: SIMPLE_GEOMETRY)


class TestQueryFailure:
    def test_layer_failure_is_flagged_as_unavailable_not_a_no_hit(self, monkeypatch):
        api = _load_acres_api()
        _patch_roi(api, monkeypatch)

        def boom(*_a, **_k):
            raise RuntimeError("EPA ArcGIS 500")

        monkeypatch.setattr(api.ArcGISService, "query_features", boom)
        result = api.get_epa_acres_properties_in_roi(40.44, -79.99)

        assert result["total"] == 0
        assert result["properties"] == []
        assert result["data_unavailable"] is True
        assert result["error"] == "EPA ACRES Brownfields data were unavailable for this request."
        assert "EPA ArcGIS 500" not in result["error"]
        assert any("not a no-hit finding" in w for w in result["warnings"])

    def test_formatter_renders_unavailable_banner_without_no_hit_text(self, monkeypatch):
        api = _load_acres_api()
        _patch_roi(api, monkeypatch)

        def boom(*_a, **_k):
            raise RuntimeError("EPA ArcGIS 500")

        monkeypatch.setattr(api.ArcGISService, "query_features", boom)
        out = api.format_epa_acres_summary(api.get_epa_acres_properties_in_roi(40.44, -79.99))
        assert "unavailable for this request, not a no-hit finding" in out
        assert "No ACRES Brownfields properties were identified" not in out


class TestTimeout:
    def test_timeout_is_caught_and_marked_unavailable(self, monkeypatch):
        api = _load_acres_api()
        _patch_roi(api, monkeypatch)

        import requests as req_mod

        def timeout(*_a, **_k):
            raise req_mod.exceptions.Timeout("timed out")

        monkeypatch.setattr(api.ArcGISService, "query_features", timeout)
        result = api.get_epa_acres_properties_in_roi(40.44, -79.99)
        assert result["total"] == 0
        assert result["data_unavailable"] is True
        assert any("results are unavailable" in w for w in result["warnings"])


class TestDegradedButUsable:
    def test_truncation_warnings_are_carried_through(self, monkeypatch):
        api = _load_acres_api()
        _patch_roi(api, monkeypatch)
        monkeypatch.setattr(
            api.ArcGISService,
            "query_features",
            lambda *_a, **_k: ArcGISFeatureQueryResult(
                features=[{"attributes": {"primary_name": "SITE", "state_code": "PA"}}],
                warnings=["reached the feature safety cap; results are partial."],
                truncated=True,
            ),
        )
        result = api.get_epa_acres_properties_in_roi(40.44, -79.99)
        assert result["total"] == 1
        assert result["truncated"] is True
        assert any("safety cap" in w for w in result["warnings"])

    def test_empty_features_is_not_an_error(self, monkeypatch):
        api = _load_acres_api()
        _patch_roi(api, monkeypatch)
        monkeypatch.setattr(
            api.ArcGISService,
            "query_features",
            lambda *_a, **_k: ArcGISFeatureQueryResult(features=[], warnings=[]),
        )
        result = api.get_epa_acres_properties_in_roi(40.44, -79.99)
        assert result["total"] == 0
        assert "data_unavailable" not in result
        assert not any("results are unavailable" in w for w in result["warnings"])


class TestMalformedFeatures:
    def test_feature_without_attributes_is_not_reported_as_a_property(self, monkeypatch):
        api = _load_acres_api()
        _patch_roi(api, monkeypatch)
        monkeypatch.setattr(
            api.ArcGISService,
            "query_features",
            lambda *_a, **_k: ArcGISFeatureQueryResult(features=[{}], warnings=[]),
        )
        result = api.get_epa_acres_properties_in_roi(40.44, -79.99)
        assert result["total"] == 0
        assert result["properties"] == []
        assert result["data_unavailable"] is True
        assert any("skipped 1 malformed" in warning for warning in result["warnings"])

    def test_null_attributes_do_not_crash_or_create_a_false_record(self, monkeypatch):
        api = _load_acres_api()
        _patch_roi(api, monkeypatch)
        monkeypatch.setattr(
            api.ArcGISService,
            "query_features",
            lambda *_a, **_k: ArcGISFeatureQueryResult(features=[{"attributes": None}], warnings=[]),
        )
        result = api.get_epa_acres_properties_in_roi(40.44, -79.99)
        assert result["total"] == 0
        assert result["data_unavailable"] is True
        assert result["error"] == "EPA ACRES returned no usable property records."

    def test_null_features_list_is_unavailable_not_a_no_hit(self, monkeypatch):
        api = _load_acres_api()
        _patch_roi(api, monkeypatch)
        monkeypatch.setattr(
            api.ArcGISService,
            "query_features",
            lambda *_a, **_k: ArcGISFeatureQueryResult(features=None, warnings=[]),
        )
        result = api.get_epa_acres_properties_in_roi(40.44, -79.99)
        assert result["total"] == 0
        assert result["properties"] == []
        assert result["data_unavailable"] is True
        assert any("malformed feature data" in warning for warning in result["warnings"])

    def test_malformed_feature_is_skipped_and_marks_mixed_results_partial(self, monkeypatch):
        api = _load_acres_api()
        _patch_roi(api, monkeypatch)
        monkeypatch.setattr(
            api.ArcGISService,
            "query_features",
            lambda *_a, **_k: ArcGISFeatureQueryResult(
                features=[
                    {"attributes": None},
                    {
                        "attributes": {
                            "registry_id": "110038700607",
                            "primary_name": "VALID SITE",
                            "state_code": "PA",
                        }
                    },
                ],
                warnings=[],
            ),
        )
        result = api.get_epa_acres_properties_in_roi(40.44, -79.99)
        assert result["total"] == 1
        assert result["properties"][0]["name"] == "VALID SITE"
        assert result["partial"] is True
        assert result["skipped_features"] == 1
        assert any("returned records are partial" in warning for warning in result["warnings"])


class TestBufferCreationFailure:
    def test_buffer_failure_sets_error_and_does_not_query(self, monkeypatch):
        api = _load_acres_api()

        def boom(*_a, **_k):
            raise RuntimeError("geometry service down")

        monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", boom)

        def should_not_run(*_a, **_k):  # pragma: no cover - guards against a call
            raise AssertionError("query_features should not be called after buffer failure")

        monkeypatch.setattr(api.ArcGISService, "query_features", should_not_run)
        result = api.get_epa_acres_properties_in_roi(40.44, -79.99)
        assert result["error"] == "ArcGIS GeometryServer was unavailable for this request."
        assert "geometry service down" not in result["error"]
        assert result["total"] == 0
        assert result["data_unavailable"] is True
