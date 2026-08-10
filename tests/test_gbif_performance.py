"""
Performance / scaling tests for the GBIF API layer.

These are hermetic (GBIF REST + counties ArcGIS mocked) and assert algorithmic
behavior at larger synthetic feature counts: deduplication reduces many
occurrences to few unique species, pagination respects ``max_records``, and
parsing/aggregation stays bounded in time. No network, so deterministic in CI.
"""

from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "gbif"
SIMPLE_GEOMETRY = {
    "rings": [[[-107.0, 34.0], [-106.0, 34.0], [-106.0, 35.0], [-107.0, 35.0], [-107.0, 34.0]]],
    "spatialReference": {"wkid": 4326},
}


def _load_gbif_api():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src."):
            sys.modules.pop(module_name, None)
    sys.path.insert(0, str(SERVER_DIR))
    try:
        spec = importlib.util.spec_from_file_location("_gbif_perf_api", SERVER_DIR / "src" / "apis" / "gbif_api.py")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules["_gbif_perf_api"] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(SERVER_DIR))


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _no_sleep(api, monkeypatch):
    monkeypatch.setattr(api.time, "sleep", lambda *_a, **_k: None)


def _record(i, sci):
    return {
        "key": i,
        "scientificName": sci,
        "vernacularName": "",
        "decimalLatitude": 34.5,
        "decimalLongitude": -106.5,
        "eventDate": "2020-01-01T00:00:00",
        "year": 2020,
        "month": 1,
        "iucnRedListCategory": "EN",
        "stateProvince": "",
        "county": "",
    }


def _paged_get(api, monkeypatch, records, page_size=300):
    """Serve `records` across GBIF pages of `page_size`, honoring offset/limit."""

    def fake_get(url, params=None, timeout=None):
        offset = int((params or {}).get("offset", 0))
        limit = int((params or {}).get("limit", page_size))
        page = records[offset : offset + limit]
        end = offset + limit >= len(records)
        return _FakeResponse({"results": page, "endOfRecords": end})

    monkeypatch.setattr(api.requests, "get", fake_get)


class TestDeduplicationScaling:
    def test_many_occurrences_collapse_to_unique_species(self):
        api = _load_gbif_api()
        occ = [{"scientific_name": f"Species {i % 10}", "threat_status": "EN"} for i in range(2000)]
        species = api._deduplicate_to_species_list(occ)
        assert len(species) == 10
        # Every species should tally 200 occurrences.
        assert all(s["observation_count"] == 200 for s in species)

    def test_summary_unique_species_across_large_set(self, monkeypatch):
        api = _load_gbif_api()
        _no_sleep(api, monkeypatch)
        records = [_record(i, f"Species {i % 50}") for i in range(1500)]
        _paged_get(api, monkeypatch, records)
        result = api.get_gbif_occurrences_in_roi(34.5, -106.5, 25.0, max_records=2000)
        assert result["count"] == 1500
        assert result["summary"]["unique_species"] == 50


class TestPaginationBounds:
    def test_respects_max_records_cap(self, monkeypatch):
        api = _load_gbif_api()
        _no_sleep(api, monkeypatch)
        records = [_record(i, f"Species {i}") for i in range(5000)]
        _paged_get(api, monkeypatch, records)
        result = api.get_gbif_occurrences_in_roi(34.5, -106.5, 25.0, max_records=600)
        assert result["count"] == 600


class TestParsingThroughput:
    def test_large_feature_set_parses_quickly(self, monkeypatch):
        api = _load_gbif_api()
        _no_sleep(api, monkeypatch)
        records = [_record(i, f"Species {i % 100}") for i in range(5000)]
        _paged_get(api, monkeypatch, records)
        start = time.perf_counter()
        result = api.get_gbif_occurrences_in_roi(34.5, -106.5, 25.0, max_records=5000)
        elapsed = time.perf_counter() - start
        assert result["count"] == 5000
        # In-memory parse + summary of 5k records should be well under a second.
        assert elapsed < 1.0

    def test_dedup_of_large_list_is_bounded(self):
        api = _load_gbif_api()
        occ = [{"scientific_name": f"Species {i % 500}", "threat_status": "EN"} for i in range(20000)]
        start = time.perf_counter()
        species = api._deduplicate_to_species_list(occ)
        elapsed = time.perf_counter() - start
        assert len(species) == 500
        assert elapsed < 1.0
