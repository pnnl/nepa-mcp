"""
Performance / scaling tests for the EPA ACRES API layer.

These are hermetic (ArcGIS mocked) and assert algorithmic behavior at larger
synthetic feature counts: parsing and sorting stay bounded in time, and
100-record pages keep formatter output size bounded while retaining complete
aggregate counts. They do not hit the network, so they are deterministic in CI.
"""

from __future__ import annotations

import importlib.util
import sys
import time
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
            "_epa_acres_perf_api", server_dir / "src" / "apis" / "acres_api.py"
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules["_epa_acres_perf_api"] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(server_dir))


def _patch_roi(api, monkeypatch):
    monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", lambda *_a, **_k: SIMPLE_GEOMETRY)


def _features(count):
    return [
        {
            "attributes": {
                "primary_name": f"SITE {i:05d}",
                "city_name": f"CITY {i % 40}",
                "state_code": ["PA", "OH", "WV", "NY"][i % 4],
                "registry_id": str(110000000000 + i),
                "pgm_sys_id": str(i),
                "latitude": 40.0 + (i % 100) / 1000,
                "longitude": -80.0 + (i % 100) / 1000,
            }
        }
        for i in range(count)
    ]


class TestParsingThroughput:
    def test_large_feature_set_parses_quickly(self, monkeypatch):
        api = _load_acres_api()
        _patch_roi(api, monkeypatch)
        features = _features(5000)
        monkeypatch.setattr(
            api.ArcGISService,
            "query_features",
            lambda *_a, **_k: ArcGISFeatureQueryResult(features=features, warnings=[]),
        )
        start = time.perf_counter()
        result = api.get_epa_acres_properties_in_roi(40.44, -79.99)
        elapsed = time.perf_counter() - start
        assert result["total"] == 5000
        # Pure in-memory parse + sort of 5k features should be well under a second.
        assert elapsed < 1.0

    def test_formatter_bounded_on_large_result(self, monkeypatch):
        api = _load_acres_api()
        _patch_roi(api, monkeypatch)
        features = _features(3000)
        monkeypatch.setattr(
            api.ArcGISService,
            "query_features",
            lambda *_a, **_k: ArcGISFeatureQueryResult(features=features, warnings=[]),
        )
        result = api.get_epa_acres_properties_in_roi(40.44, -79.99)
        start = time.perf_counter()
        out = api.format_epa_acres_summary(result)
        elapsed = time.perf_counter() - start
        assert "Total ACRES Properties:** 3000" in out
        assert elapsed < 1.0


class TestListingCapScaling:
    def test_output_size_stays_flat_as_totals_grow(self, monkeypatch):
        """Pagination bounds output while preserving exact aggregate counts."""
        api = _load_acres_api()
        _patch_roi(api, monkeypatch)

        outputs = {}
        for count in (500, 5000):
            features = _features(count)
            monkeypatch.setattr(
                api.ArcGISService,
                "query_features",
                lambda *_a, _f=features, **_k: ArcGISFeatureQueryResult(features=_f, warnings=[]),
            )
            result = api.get_epa_acres_properties_in_roi(40.44, -79.99)
            outputs[count] = api.format_epa_acres_summary(result)

        assert f"Property Details (1–{api.MAX_PAGE_SIZE} of 500)" in outputs[500]
        assert f"Property Details (1–{api.MAX_PAGE_SIZE} of 5000)" in outputs[5000]
        assert outputs[500].count("- **SITE") == api.MAX_PAGE_SIZE
        assert outputs[5000].count("- **SITE") == api.MAX_PAGE_SIZE
        # Same bounded detail page either way; only aggregate counts differ.
        assert abs(len(outputs[5000]) - len(outputs[500])) < 500
