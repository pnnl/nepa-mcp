"""
Resilience tests for the NRHP API layer.

Verify behavior when the upstream NPS ArcGIS service errors, times out, or
returns malformed payloads. The shared ArcGISService is mocked to simulate each
failure mode.

Key correctness concern documented here (see ``TestBothLayersFail``): the two
layer queries (polygon layer 1, then point layer 0) are each wrapped in their
own try/except. A failure in one layer is recorded as a warning but does not
raise. When BOTH layers fail, no exception propagates; the api returns
``total == 0`` with an empty ``properties`` list, which the formatter renders
with the "No NRHP-listed properties were identified" text. The api DOES,
however, distinguish an outage from a true no-hit result by appending an
explicit warning ("No NRHP layers were queried successfully; results are
unavailable, not a no-hit finding.") and does NOT set the ``error`` key. These
tests assert that ACTUAL current behavior.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from nepa_mcp_common.arcgis import ArcGISFeatureQueryResult

ROOT = Path(__file__).resolve().parents[1]
SIMPLE_GEOMETRY = {
    "rings": [[[-107.0, 34.0], [-106.0, 34.0], [-106.0, 35.0], [-107.0, 35.0], [-107.0, 34.0]]],
    "spatialReference": {"wkid": 4326},
}


def _load_nrhp_api():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src."):
            sys.modules.pop(module_name, None)
    server_dir = ROOT / "nrhp"
    sys.path.insert(0, str(server_dir))
    try:
        spec = importlib.util.spec_from_file_location(
            "_nrhp_resilience_api", server_dir / "src" / "apis" / "nrhp_api.py"
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules["_nrhp_resilience_api"] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(server_dir))


def _patch_roi(api, monkeypatch):
    monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", lambda *_a, **_k: SIMPLE_GEOMETRY)


class TestSingleLayerFailure:
    def test_one_layer_failing_is_a_warning_not_a_raise(self, monkeypatch):
        api = _load_nrhp_api()
        _patch_roi(api, monkeypatch)

        def query_features(url, layer_id, _geometry, *, service_name=None, **_k):
            # Fail the point layer (layer 0); polygon layer (1) succeeds.
            if layer_id == 0:
                raise RuntimeError("point layer 503")
            return ArcGISFeatureQueryResult(
                features=[{"attributes": {"NRIS_Refnum": "1", "RESNAME": "Poly Hall", "State": "NM"}}],
                warnings=[],
            )

        monkeypatch.setattr(api.ArcGISService, "query_features", query_features)
        result = api.get_nrhp_properties_in_roi(35.6, -105.9)
        # Polygon results survive; the point-layer failure is surfaced as a warning.
        assert result["total"] == 1
        assert result["properties"][0]["name"] == "Poly Hall"
        assert any("layer query failed" in w for w in result["warnings"])
        # A partial outage still returns data, so no top-level error key.
        assert "error" not in result


class TestBothLayersFail:
    def test_both_layers_failing_is_flagged_as_unavailable_not_a_no_hit(self, monkeypatch):
        """A full outage must be distinguishable from a genuine no-hit screen.

        When BOTH layer queries raise, the api still does not propagate an
        exception, but it now sets ``data_unavailable=True`` and an ``error``
        message on the result — so a consumer that only inspects the structured
        fields (not ``warnings``) cannot mistake an outage for "no properties
        found". The distinguishing warning is retained as well.
        """
        api = _load_nrhp_api()
        _patch_roi(api, monkeypatch)

        def boom(*_a, **_k):
            raise RuntimeError("NPS ArcGIS 500")

        monkeypatch.setattr(api.ArcGISService, "query_features", boom)
        result = api.get_nrhp_properties_in_roi(35.6, -105.9)

        # Still no exception; still an empty property list...
        assert result["total"] == 0
        assert result["properties"] == []
        assert result["nhl_count"] == 0
        # ...but the outage is now flagged in the structured result, not only warnings.
        assert result.get("data_unavailable") is True
        assert "error" in result
        assert "not a no-hit finding" in result["error"]
        # The distinguishing warning and per-layer failures are still recorded.
        assert any("results are unavailable, not a no-hit finding" in w for w in result["warnings"])
        assert sum("layer query failed" in w for w in result["warnings"]) == 2

    def test_formatter_renders_no_hit_text_but_keeps_outage_warning(self, monkeypatch):
        """The formatter emits the "No properties identified" line even during a
        full outage, so the outage signal lives ONLY in the surfaced warning.
        This asserts that both appear together in current output.
        """
        api = _load_nrhp_api()
        _patch_roi(api, monkeypatch)

        def boom(*_a, **_k):
            raise RuntimeError("NPS ArcGIS 500")

        monkeypatch.setattr(api.ArcGISService, "query_features", boom)
        result = api.get_nrhp_properties_in_roi(35.6, -105.9)
        out = api.format_nrhp_summary(result)
        # Ambiguity made concrete: negative-screen phrasing is present...
        assert "No NRHP-listed properties were identified within the ROI buffer." in out
        # ...alongside the warning that flags the results as unavailable.
        assert "results are unavailable, not a no-hit finding" in out


class TestTimeout:
    def test_timeout_in_both_layers_is_swallowed_into_warnings(self, monkeypatch):
        """A ``requests`` Timeout raised by the query layer is caught per-layer,
        so it does not bubble out of ``get_nrhp_properties_in_roi``.
        """
        api = _load_nrhp_api()
        _patch_roi(api, monkeypatch)

        import requests as req_mod

        def timeout(*_a, **_k):
            raise req_mod.exceptions.Timeout("timed out")

        monkeypatch.setattr(api.ArcGISService, "query_features", timeout)
        result = api.get_nrhp_properties_in_roi(35.6, -105.9)
        assert result["total"] == 0
        assert any("results are unavailable" in w for w in result["warnings"])


class TestDegradedButUsable:
    def test_warnings_are_carried_through(self, monkeypatch):
        api = _load_nrhp_api()
        _patch_roi(api, monkeypatch)

        def query_features(url, layer_id, _geometry, *, service_name=None, **_k):
            if layer_id == 1:
                return ArcGISFeatureQueryResult(
                    features=[{"attributes": {"NRIS_Refnum": "1", "RESNAME": "Poly Hall"}}],
                    warnings=["reached the feature safety cap; results are partial."],
                    truncated=True,
                )
            return ArcGISFeatureQueryResult(features=[], warnings=[])

        monkeypatch.setattr(api.ArcGISService, "query_features", query_features)
        result = api.get_nrhp_properties_in_roi(35.6, -105.9)
        assert result["total"] == 1
        assert any("safety cap" in w for w in result["warnings"])

    def test_empty_features_is_not_an_error(self, monkeypatch):
        api = _load_nrhp_api()
        _patch_roi(api, monkeypatch)
        monkeypatch.setattr(
            api.ArcGISService,
            "query_features",
            lambda *_a, **_k: ArcGISFeatureQueryResult(features=[], warnings=[]),
        )
        result = api.get_nrhp_properties_in_roi(35.6, -105.9)
        assert result["total"] == 0
        assert result["properties"] == []
        # Both layers succeeded (returned empty), so the outage warning is absent.
        assert not any("results are unavailable" in w for w in result["warnings"])


class TestMalformedFeatures:
    def test_feature_without_attributes_key(self, monkeypatch):
        api = _load_nrhp_api()
        _patch_roi(api, monkeypatch)

        def query_features(url, layer_id, _geometry, *, service_name=None, **_k):
            if layer_id == 1:
                return ArcGISFeatureQueryResult(features=[{}], warnings=[])
            return ArcGISFeatureQueryResult(features=[], warnings=[])

        monkeypatch.setattr(api.ArcGISService, "query_features", query_features)
        result = api.get_nrhp_properties_in_roi(35.6, -105.9)
        # A feature with no attributes still parses to an "Unknown" property.
        assert result["total"] == 1
        assert result["properties"][0]["name"] == "Unknown"

    def test_null_attribute_values_do_not_crash(self, monkeypatch):
        api = _load_nrhp_api()
        _patch_roi(api, monkeypatch)

        def query_features(url, layer_id, _geometry, *, service_name=None, **_k):
            if layer_id == 1:
                return ArcGISFeatureQueryResult(
                    features=[{"attributes": {"NRIS_Refnum": None, "RESNAME": None, "State": None}}],
                    warnings=[],
                )
            return ArcGISFeatureQueryResult(features=[], warnings=[])

        monkeypatch.setattr(api.ArcGISService, "query_features", query_features)
        result = api.get_nrhp_properties_in_roi(35.6, -105.9)
        assert result["total"] == 1
        assert result["properties"][0]["name"] == "Unknown"


class TestBufferCreationFailure:
    def test_buffer_failure_sets_error_and_does_not_query(self, monkeypatch):
        api = _load_nrhp_api()

        def boom(*_a, **_k):
            raise RuntimeError("geometry service down")

        monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", boom)

        def should_not_run(*_a, **_k):  # pragma: no cover - guards against a call
            raise AssertionError("query_features should not be called after buffer failure")

        monkeypatch.setattr(api.ArcGISService, "query_features", should_not_run)
        result = api.get_nrhp_properties_in_roi(35.6, -105.9)
        # Unlike the both-layers-fail path, buffer failure DOES set an error key.
        assert result["error"] == "geometry service down"
        assert result["total"] == 0
