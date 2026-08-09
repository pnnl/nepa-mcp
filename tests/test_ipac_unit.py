"""
Unit tests for the IPaC API layer (``ipac/src/apis/ipac_api.py``).

These exercise the pure parsing/formatting logic with the ArcGIS buffer layer
and the ``requests.post`` call to the USFWS IPaC API mocked, so no network
calls are made. They follow the same dynamic per-server import pattern used by
``test_usace_unit.py``.
"""

from __future__ import annotations

import importlib.util
import sys
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
        spec = importlib.util.spec_from_file_location(
            "_ipac_unit_api",
            server_dir / "src" / "apis" / "ipac_api.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules["_ipac_unit_api"] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(server_dir))


class _FakeResponse:
    """Minimal stand-in for a ``requests`` Response object."""

    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests as req_mod

            raise req_mod.exceptions.HTTPError(f"status {self.status_code}")

    def json(self):
        return self._payload


def _sample_resources():
    """A small but realistic IPaC ``resources`` payload."""
    return {
        "populationsBySid": {
            "POP1": {
                "population": {
                    "sid": {"val": "POP1"},
                    "optionalCommonName": "Whooping Crane",
                    "optionalScientificName": "Grus americana",
                    "shortName": "crane",
                    "listingStatusName": "Endangered",
                    "listingStatusCode": "E",
                    "criticalHabitat": "Final",
                },
                "optionalFederalRegisterCrithabStatus": {
                    "date": "1978-05-15",
                    "displayType": "Final Rule",
                    "url": "https://www.federalregister.gov/whooping-crane",
                },
            },
            "POP2": {
                "population": {
                    "sid": {"val": "POP2"},
                    "optionalCommonName": "Arctic Grayling",
                    "optionalScientificName": "Thymallus arcticus",
                    "shortName": "grayling",
                    "listingStatusName": "Threatened",
                    "listingStatusCode": "T",
                    "criticalHabitat": "None",
                }
            },
        },
        "migbirds": [
            {
                "phenologySpecies": {
                    "commonName": "Bald Eagle",
                    "scientificName": "Haliaeetus leucocephalus",
                    "code": "BAEA",
                },
                "level": {"name": "BCC Rangewide"},
                "bcc": True,
                "optionalBreedsFrom": "Jan",
                "optionalBreedsTo": "Aug",
            },
            {
                "phenologySpecies": {
                    "commonName": "American Kestrel",
                    "scientificName": "Falco sparverius",
                    "code": "AMKE",
                },
                "level": {"name": "BCC - BCR"},
                "bcc": True,
                "optionalBreedsFrom": "",
                "optionalBreedsTo": "",
            },
        ],
        "wetlands": {
            "items": [
                {
                    "wetlandCode": "PEM1A",
                    "attributes": {
                        "SYSTEM_NAME": "Palustrine",
                        "CLASS_NAME": "Emergent",
                        "WATER_REGIME_SUBGROUP": "Temporarily Flooded",
                        "Shape": "polygon",
                    },
                }
            ]
        },
        "refuges": {
            "items": [
                {
                    "name": "Bosque del Apache NWR",
                    "rslType": "Refuge",
                    "acres": 57191,
                    "orgCode": "22540",
                }
            ]
        },
        "fieldOffices": [{"officeName": "New Mexico Ecological Services", "officeCode": "NMESFO"}],
        "crithabs": [
            {
                "populationSid": {"val": "POP1"},
                "type": "Final",
                "speciesInFootprint": True,
                "hasGeometry": False,
            },
            {
                "populationSid": {"val": "UNKNOWN_POP"},
                "type": "Proposed",
                "speciesInFootprint": False,
                "hasGeometry": False,
            },
        ],
    }


def _patch_geometry(api, monkeypatch):
    monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", lambda *_a, **_k: SIMPLE_GEOMETRY)
    monkeypatch.setattr(api.ArcGISService, "simplify_polygon_geometry", lambda *_a, **_k: SIMPLE_GEOMETRY)


def _patch_post(api, monkeypatch, resources, status_code=200, extra=None):
    payload = {"resources": resources}
    if extra:
        payload.update(extra)
    monkeypatch.setattr(
        api.requests,
        "post",
        lambda *_a, **_k: _FakeResponse(payload, status_code=status_code),
    )


# ---------------------------------------------------------------------------
# Species parsing
# ---------------------------------------------------------------------------


class TestSpeciesParsing:
    def test_parses_species_fields(self, monkeypatch):
        api = _load_ipac_api()
        _patch_geometry(api, monkeypatch)
        _patch_post(api, monkeypatch, _sample_resources())
        result = api.get_ipac_resources_in_roi(34.5, -106.5, 25.0)
        assert result["species_count"] == 2
        # Sorted by common name: "Arctic Grayling" precedes "Whooping Crane".
        first = result["species"][0]
        assert first["common_name"] == "Arctic Grayling"
        assert first["scientific_name"] == "Thymallus arcticus"
        assert first["listing_status"] == "Threatened"
        assert result["center"] == {"latitude": 34.5, "longitude": -106.5}
        assert result["buffer_miles"] == 25.0

    def test_species_sorted_by_common_name(self, monkeypatch):
        api = _load_ipac_api()
        _patch_geometry(api, monkeypatch)
        _patch_post(api, monkeypatch, _sample_resources())
        result = api.get_ipac_resources_in_roi(34.5, -106.5)
        names = [s["common_name"] for s in result["species"]]
        assert names == sorted(names)

    def test_empty_populations_yield_zero_species(self, monkeypatch):
        api = _load_ipac_api()
        _patch_geometry(api, monkeypatch)
        res = _sample_resources()
        res["populationsBySid"] = {}
        _patch_post(api, monkeypatch, res)
        result = api.get_ipac_resources_in_roi(34.5, -106.5)
        assert result["species_count"] == 0
        assert result["species"] == []


# ---------------------------------------------------------------------------
# Migratory birds
# ---------------------------------------------------------------------------


class TestMigratoryBirds:
    def test_parses_and_sorts_birds(self, monkeypatch):
        api = _load_ipac_api()
        _patch_geometry(api, monkeypatch)
        _patch_post(api, monkeypatch, _sample_resources())
        result = api.get_ipac_resources_in_roi(34.5, -106.5)
        assert result["migbirds_count"] == 2
        names = [b["common_name"] for b in result["migratory_birds"]]
        assert names == sorted(names)
        assert result["migratory_birds"][0]["common_name"] == "American Kestrel"
        assert result["migratory_birds"][0]["conservation_level"] == "BCC - BCR"

    def test_no_migbirds_key(self, monkeypatch):
        api = _load_ipac_api()
        _patch_geometry(api, monkeypatch)
        res = _sample_resources()
        del res["migbirds"]
        _patch_post(api, monkeypatch, res)
        result = api.get_ipac_resources_in_roi(34.5, -106.5)
        assert result["migbirds_count"] == 0


# ---------------------------------------------------------------------------
# Wetlands and refuges
# ---------------------------------------------------------------------------


class TestWetlandsAndRefuges:
    def test_parses_wetlands(self, monkeypatch):
        api = _load_ipac_api()
        _patch_geometry(api, monkeypatch)
        _patch_post(api, monkeypatch, _sample_resources())
        result = api.get_ipac_resources_in_roi(34.5, -106.5)
        assert result["wetlands_count"] == 1
        w = result["wetlands"][0]
        assert w["code"] == "PEM1A"
        assert w["system"] == "Palustrine"
        assert w["class"] == "Emergent"

    def test_parses_refuges(self, monkeypatch):
        api = _load_ipac_api()
        _patch_geometry(api, monkeypatch)
        _patch_post(api, monkeypatch, _sample_resources())
        result = api.get_ipac_resources_in_roi(34.5, -106.5)
        assert result["refuges_count"] == 1
        r = result["refuges"][0]
        assert r["name"] == "Bosque del Apache NWR"
        assert r["acres"] == 57191

    def test_wetlands_not_a_dict_is_tolerated(self, monkeypatch):
        api = _load_ipac_api()
        _patch_geometry(api, monkeypatch)
        res = _sample_resources()
        res["wetlands"] = []  # unexpected type
        _patch_post(api, monkeypatch, res)
        result = api.get_ipac_resources_in_roi(34.5, -106.5)
        assert result["wetlands_count"] == 0
        assert result["wetlands"] == []


# ---------------------------------------------------------------------------
# Field offices and critical habitat
# ---------------------------------------------------------------------------


class TestFieldOfficesAndCritHab:
    def test_parses_field_offices(self, monkeypatch):
        api = _load_ipac_api()
        _patch_geometry(api, monkeypatch)
        _patch_post(api, monkeypatch, _sample_resources())
        result = api.get_ipac_resources_in_roi(34.5, -106.5)
        assert result["field_offices"][0]["name"] == "New Mexico Ecological Services"
        assert result["field_offices"][0]["code"] == "NMESFO"

    def test_crithab_cross_references_species(self, monkeypatch):
        api = _load_ipac_api()
        _patch_geometry(api, monkeypatch)
        _patch_post(api, monkeypatch, _sample_resources())
        result = api.get_ipac_resources_in_roi(34.5, -106.5)
        assert result["critical_habitat_count"] == 2
        matched = next(c for c in result["critical_habitat"] if c["species_id"] == "POP1")
        assert matched["common_name"] == "Whooping Crane"
        assert matched["listing_status"] == "Endangered"
        assert matched["federal_register_date"] == "1978-05-15"
        assert matched["federal_register_type"] == "Final Rule"

    def test_crithab_unknown_population_falls_back(self, monkeypatch):
        api = _load_ipac_api()
        _patch_geometry(api, monkeypatch)
        _patch_post(api, monkeypatch, _sample_resources())
        result = api.get_ipac_resources_in_roi(34.5, -106.5)
        unmatched = next(c for c in result["critical_habitat"] if c["species_id"] == "UNKNOWN_POP")
        assert unmatched["common_name"] == "Unknown"
        assert unmatched["federal_register_date"] == ""


# ---------------------------------------------------------------------------
# Formatter
# ---------------------------------------------------------------------------


class TestFormatter:
    def test_summary_renders_counts_and_headers(self, monkeypatch):
        api = _load_ipac_api()
        _patch_geometry(api, monkeypatch)
        _patch_post(api, monkeypatch, _sample_resources())
        data = api.get_ipac_resources_in_roi(34.5, -106.5)
        out = api.format_ipac_summary(data)
        assert "USFWS IPaC Resources within ROI" in out
        assert "Threatened/Endangered Species: 2" in out
        assert "Migratory Birds: 2" in out
        assert "Critical Habitat Units: 2" in out
        assert "Whooping Crane" in out
        assert "Section 7 consultation" in out

    def test_summary_handles_empty_resources(self, monkeypatch):
        api = _load_ipac_api()
        data = {
            "center": {"latitude": 34.5, "longitude": -106.5},
            "buffer_miles": 25.0,
            "species": [],
            "species_count": 0,
            "migratory_birds": [],
            "migbirds_count": 0,
            "wetlands": [],
            "wetlands_count": 0,
            "critical_habitat": [],
            "critical_habitat_count": 0,
        }
        out = api.format_ipac_summary(data)
        assert "Threatened/Endangered Species: 0" in out
        assert "Critical Habitat Units: 0" in out

    def test_summary_truncates_bird_list(self, monkeypatch):
        api = _load_ipac_api()
        birds = [{"common_name": f"Bird {i:02d}", "conservation_level": "BCC"} for i in range(15)]
        data = {
            "center": {"latitude": 1, "longitude": 2},
            "buffer_miles": 25.0,
            "species": [],
            "species_count": 0,
            "migratory_birds": birds,
            "migbirds_count": len(birds),
            "wetlands": [],
            "wetlands_count": 0,
            "critical_habitat": [],
            "critical_habitat_count": 0,
        }
        out = api.format_ipac_summary(data)
        assert "... and 5 additional species" in out
