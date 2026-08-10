"""
Resilience tests for the GIS/ROI API layer.

Verify graceful behavior when the upstream ArcGIS geometry service errors,
times out, or returns malformed/degenerate buffer geometry. The shared
``ArcGISService.create_roi_buffer`` is mocked to simulate each failure mode.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SIMPLE_GEOMETRY = {
    "rings": [[[-107.0, 34.0], [-106.0, 34.0], [-106.0, 35.0], [-107.0, 35.0], [-107.0, 34.0]]],
    "spatialReference": {"wkid": 4326},
}


def _load_roi_api():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src."):
            sys.modules.pop(module_name, None)
    server_dir = ROOT / "gis"
    sys.path.insert(0, str(server_dir))
    try:
        spec = importlib.util.spec_from_file_location("_gis_resilience_api", server_dir / "src" / "apis" / "roi_api.py")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules["_gis_resilience_api"] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(server_dir))


class TestUpstreamBufferFailure:
    def test_buffer_raises_bubbles_up(self, monkeypatch):
        api = _load_roi_api()

        def boom(*_a, **_k):
            raise RuntimeError("ArcGIS GeometryServer upstream 500")

        monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", boom)
        with pytest.raises(RuntimeError):
            api.get_roi_geojson(34.5, -106.5)

    def test_timeout_bubbles_up(self, monkeypatch):
        api = _load_roi_api()

        import requests as req_mod

        def timeout(*_a, **_k):
            raise req_mod.exceptions.Timeout("timed out")

        monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", timeout)
        with pytest.raises(req_mod.exceptions.Timeout):
            api.calculate_roi_area(34.5, -106.5)

    def test_invalid_geometry_from_upstream_raises(self, monkeypatch):
        api = _load_roi_api()
        # calculate_area raises ValueError when the buffer has no rings.
        monkeypatch.setattr(
            api.ArcGISService, "create_roi_buffer", lambda *_a, **_k: {"spatialReference": {"wkid": 4326}}
        )
        with pytest.raises(ValueError):
            api.calculate_roi_area(34.5, -106.5)


class TestDegenerateGeometry:
    def test_empty_rings_raises_value_error(self, monkeypatch):
        api = _load_roi_api()
        monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", lambda *_a, **_k: {"rings": []})
        with pytest.raises(ValueError):
            api.get_roi_geojson(34.5, -106.5)

    def test_valid_small_buffer_still_computes(self, monkeypatch):
        api = _load_roi_api()
        monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", lambda *_a, **_k: SIMPLE_GEOMETRY)
        sq_miles, acres = api.calculate_roi_area(34.5, -106.5, 0.1)
        assert sq_miles > 0
        assert acres > 0
