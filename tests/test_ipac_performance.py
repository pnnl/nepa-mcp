"""
Performance / scaling tests for the IPaC API layer.

These are hermetic (ArcGIS buffer + ``requests.post`` mocked) and assert
algorithmic behavior at larger synthetic payload sizes: parsing and sorting
of many species/birds/crithabs stays bounded in time and produces the right
counts. They do not hit the network, so they are deterministic in CI.
"""

from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIMPLE_GEOMETRY = {
    "rings": [[[-107.0, 34.0], [-106.0, 34.0], [-106.0, 35.0], [-107.0, 35.0], [-107.0, 34.0]]],
    "spatialReference": {"wkid": 4326},
}


def _load_ipac_api():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src."):
            sys.modules.pop(module_name, None)
    server_dir = ROOT / "ipac"
    sys.path.insert(0, str(server_dir))
    try:
        spec = importlib.util.spec_from_file_location("_ipac_perf_api", server_dir / "src" / "apis" / "ipac_api.py")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules["_ipac_perf_api"] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(server_dir))


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _patch(api, monkeypatch, resources):
    monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", lambda *_a, **_k: SIMPLE_GEOMETRY)
    monkeypatch.setattr(api.ArcGISService, "simplify_polygon_geometry", lambda *_a, **_k: SIMPLE_GEOMETRY)
    monkeypatch.setattr(api.requests, "post", lambda *_a, **_k: _FakeResponse({"resources": resources}))


def _build_resources(n_species=0, n_birds=0, n_crithabs=0):
    populations = {}
    for i in range(n_species):
        pid = f"POP{i}"
        populations[pid] = {
            "population": {
                "sid": {"val": pid},
                "optionalCommonName": f"Species {n_species - i:05d}",
                "optionalScientificName": f"Genus species{i}",
                "listingStatusName": "Threatened",
                "listingStatusCode": "T",
                "criticalHabitat": "None",
            }
        }
    migbirds = [
        {
            "phenologySpecies": {"commonName": f"Bird {n_birds - i:05d}"},
            "level": {"name": "BCC"},
        }
        for i in range(n_birds)
    ]
    crithabs = [{"populationSid": {"val": f"POP{i}"}, "type": "Final"} for i in range(n_crithabs)]
    return {"populationsBySid": populations, "migbirds": migbirds, "crithabs": crithabs}


class TestParsingThroughput:
    def test_large_species_set_parses_quickly(self, monkeypatch):
        api = _load_ipac_api()
        _patch(api, monkeypatch, _build_resources(n_species=5000))
        start = time.perf_counter()
        result = api.get_ipac_resources_in_roi(34.5, -106.5)
        elapsed = time.perf_counter() - start
        assert result["species_count"] == 5000
        assert elapsed < 1.0

    def test_species_sorted_after_large_parse(self, monkeypatch):
        api = _load_ipac_api()
        _patch(api, monkeypatch, _build_resources(n_species=2000))
        result = api.get_ipac_resources_in_roi(34.5, -106.5)
        names = [s["common_name"] for s in result["species"]]
        assert names == sorted(names)

    def test_large_bird_set_parses_quickly(self, monkeypatch):
        api = _load_ipac_api()
        _patch(api, monkeypatch, _build_resources(n_birds=5000))
        start = time.perf_counter()
        result = api.get_ipac_resources_in_roi(34.5, -106.5)
        elapsed = time.perf_counter() - start
        assert result["migbirds_count"] == 5000
        assert elapsed < 1.0

    def test_full_payload_bounded(self, monkeypatch):
        api = _load_ipac_api()
        _patch(
            api,
            monkeypatch,
            _build_resources(n_species=2000, n_birds=2000, n_crithabs=2000),
        )
        start = time.perf_counter()
        result = api.get_ipac_resources_in_roi(34.5, -106.5)
        elapsed = time.perf_counter() - start
        assert result["species_count"] == 2000
        assert result["migbirds_count"] == 2000
        assert result["critical_habitat_count"] == 2000
        assert elapsed < 2.0
