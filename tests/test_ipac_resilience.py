"""
Resilience tests for the IPaC API layer.

Verify graceful behavior when the upstream IPaC HTTP endpoint errors, times
out, returns malformed payloads, or returns an empty resources object. The
``requests.post`` call and the ArcGIS buffer layer are mocked to simulate each
failure mode. Note that ``ipac_api`` wraps ``requests`` exceptions and
``KeyError``/``ValueError`` in a generic ``Exception``.
"""

from __future__ import annotations

import importlib.util
import sys
from copy import deepcopy
from pathlib import Path

import pytest

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
            "_ipac_resilience_api", server_dir / "src" / "apis" / "ipac_api.py"
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules["_ipac_resilience_api"] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(server_dir))


class _FakeResponse:
    def __init__(self, payload, status_code=200, json_exc=None):
        self._payload = payload
        self.status_code = status_code
        self._json_exc = json_exc

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests as req_mod

            raise req_mod.exceptions.HTTPError(f"status {self.status_code}")

    def json(self):
        if self._json_exc is not None:
            raise self._json_exc
        return self._payload


def _patch_geometry(api, monkeypatch):
    monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", lambda *_a, **_k: SIMPLE_GEOMETRY)
    monkeypatch.setattr(api.ArcGISService, "simplify_polygon_geometry", lambda *_a, **_k: SIMPLE_GEOMETRY)


class TestUpstreamRequestFailure:
    def test_timeout_is_wrapped(self, monkeypatch):
        api = _load_ipac_api()
        _patch_geometry(api, monkeypatch)

        import requests as req_mod

        def timeout(*_a, **_k):
            raise req_mod.exceptions.Timeout("timed out")

        monkeypatch.setattr(api.requests, "post", timeout)
        with pytest.raises(Exception) as exc:
            api.get_ipac_resources_in_roi(34.5, -106.5)
        assert "IPaC API request failed" in str(exc.value)

    def test_connection_error_is_wrapped(self, monkeypatch):
        api = _load_ipac_api()
        _patch_geometry(api, monkeypatch)

        import requests as req_mod

        def conn_err(*_a, **_k):
            raise req_mod.exceptions.ConnectionError("connection refused")

        monkeypatch.setattr(api.requests, "post", conn_err)
        with pytest.raises(Exception) as exc:
            api.get_ipac_resources_in_roi(34.5, -106.5)
        assert "IPaC API request failed" in str(exc.value)

    def test_http_error_status_is_wrapped(self, monkeypatch):
        api = _load_ipac_api()
        _patch_geometry(api, monkeypatch)
        monkeypatch.setattr(api.requests, "post", lambda *_a, **_k: _FakeResponse({}, status_code=500))
        with pytest.raises(Exception) as exc:
            api.get_ipac_resources_in_roi(34.5, -106.5)
        assert "IPaC API request failed" in str(exc.value)


class TestMalformedPayload:
    def test_missing_resources_object_raises(self, monkeypatch):
        api = _load_ipac_api()
        _patch_geometry(api, monkeypatch)
        # No "resources" key -> resources is None -> ValueError -> wrapped.
        monkeypatch.setattr(api.requests, "post", lambda *_a, **_k: _FakeResponse({"other": 1}))
        with pytest.raises(Exception) as exc:
            api.get_ipac_resources_in_roi(34.5, -106.5)
        assert "Error parsing IPaC response" in str(exc.value)

    def test_resources_not_a_dict_raises(self, monkeypatch):
        api = _load_ipac_api()
        _patch_geometry(api, monkeypatch)
        monkeypatch.setattr(api.requests, "post", lambda *_a, **_k: _FakeResponse({"resources": []}))
        with pytest.raises(Exception) as exc:
            api.get_ipac_resources_in_roi(34.5, -106.5)
        assert "Error parsing IPaC response" in str(exc.value)

    def test_invalid_json_body_is_wrapped(self, monkeypatch):
        api = _load_ipac_api()
        _patch_geometry(api, monkeypatch)
        monkeypatch.setattr(
            api.requests,
            "post",
            lambda *_a, **_k: _FakeResponse(None, json_exc=ValueError("No JSON object")),
        )
        with pytest.raises(Exception) as exc:
            api.get_ipac_resources_in_roi(34.5, -106.5)
        assert "Error parsing IPaC response" in str(exc.value)


class TestDegradedButUsable:
    def test_empty_resources_object_is_not_an_error(self, monkeypatch):
        api = _load_ipac_api()
        _patch_geometry(api, monkeypatch)
        monkeypatch.setattr(api.requests, "post", lambda *_a, **_k: _FakeResponse({"resources": {}}))
        result = api.get_ipac_resources_in_roi(34.5, -106.5)
        assert result["species_count"] == 0
        assert result["migbirds_count"] == 0
        assert result["wetlands_count"] == 0
        assert result["critical_habitat_count"] == 0
        assert result["refuges_count"] == 0

    def test_partial_resources_parse_available_sections(self, monkeypatch):
        api = _load_ipac_api()
        _patch_geometry(api, monkeypatch)
        # Only migbirds present; other sections absent.
        partial = {
            "resources": {
                "migbirds": [
                    {
                        "phenologySpecies": {"commonName": "Bald Eagle"},
                        "level": {"name": "BCC"},
                    }
                ]
            }
        }
        monkeypatch.setattr(api.requests, "post", lambda *_a, **_k: _FakeResponse(partial))
        result = api.get_ipac_resources_in_roi(34.5, -106.5)
        assert result["migbirds_count"] == 1
        assert result["species_count"] == 0


NULL_RESOURCES = {
    "populationsBySid": None,
    "migbirds": None,
    "wetlands": {"items": None},
    "refuges": {"items": None},
    "fieldOffices": None,
    "crithabs": None,
    "marineMammals": None,
    "allReferencedPopulationsBySid": None,
    "fishHatcheries": {"items": None},
    "coastalBarriers": None,
}
UNAVAILABLE_FIELDS = {
    "populationsBySid",
    "migbirds",
    "wetlands.items",
    "refuges.items",
    "fieldOffices",
    "crithabs",
    "marineMammals",
    "allReferencedPopulationsBySid",
    "fishHatcheries.items",
    "coastalBarriers",
}


def test_all_null_collections_preserve_partial_response_and_raw_audit(monkeypatch):
    api = _load_ipac_api()
    _patch_geometry(api, monkeypatch)
    payload = {"resources": deepcopy(NULL_RESOURCES), "audit_marker": "unchanged"}
    original = deepcopy(payload)
    monkeypatch.setattr(api.requests, "post", lambda *_a, **_k: _FakeResponse(payload))

    result = api.get_ipac_resources_in_roi(34.55, -107.8, 100.0)

    assert result["partial"] is True
    assert set(result["unavailable_resource_fields"]) == UNAVAILABLE_FIELDS
    for key in (
        "species_count",
        "migbirds_count",
        "wetlands_count",
        "refuges_count",
        "field_offices_count",
        "critical_habitat_count",
        "marine_mammals_count",
        "referenced_populations_count",
        "fish_hatcheries_count",
        "coastal_barriers_count",
    ):
        assert result[key] is None
        assert result["returned_counts"][key] == 0
    summary = api.format_ipac_summary(result)
    assert "PARTIAL IPAC RESPONSE" in summary
    assert summary.count("Unavailable in this response") == 10
    assert "not confirmed no-hit findings" in summary
    assert "reviewer follow-up" in summary
    assert result["raw_response"] == payload == original


def test_mixed_null_collection_preserves_valid_birds(monkeypatch):
    api = _load_ipac_api()
    _patch_geometry(api, monkeypatch)
    payload = {
        "resources": {
            "marineMammals": None,
            "migbirds": [{"phenologySpecies": {"commonName": "Bald Eagle"}, "level": {"name": "BCC"}}],
        }
    }
    monkeypatch.setattr(api.requests, "post", lambda *_a, **_k: _FakeResponse(payload))
    result = api.get_ipac_resources_in_roi(34.55, -107.8, 100)
    assert result["migbirds_count"] == 1
    assert result["marine_mammals_count"] is None
    assert result["unavailable_resource_fields"] == ["marineMammals"]
    summary = api.format_ipac_summary(result)
    assert "Migratory Birds: 1" in summary and "Bald Eagle" in summary
    assert "Marine Mammals: Unavailable in this response" in summary


COUNT_FIELDS = {
    "populationsBySid": "species_count",
    "migbirds": "migbirds_count",
    "wetlands": "wetlands_count",
    "refuges": "refuges_count",
    "fieldOffices": "field_offices_count",
    "crithabs": "critical_habitat_count",
    "marineMammals": "marine_mammals_count",
    "allReferencedPopulationsBySid": "referenced_populations_count",
    "fishHatcheries": "fish_hatcheries_count",
    "coastalBarriers": "coastal_barriers_count",
}
MAPPING_FIELDS = {"populationsBySid", "allReferencedPopulationsBySid", "wetlands", "refuges", "fishHatcheries"}


def _run_resources(monkeypatch, resources):
    api = _load_ipac_api()
    _patch_geometry(api, monkeypatch)
    payload = {"resources": resources}
    original = deepcopy(payload)
    monkeypatch.setattr(api.requests, "post", lambda *_a, **_k: _FakeResponse(payload))
    result = api.get_ipac_resources_in_roi(34.55, -107.8, 100)
    assert result["raw_response"] == payload == original
    return api, result


@pytest.mark.parametrize(
    "field",
    sorted(set(COUNT_FIELDS) | {"wetlands.items", "refuges.items", "fishHatcheries.items", "coastalBarriers.items"}),
)
@pytest.mark.parametrize("bad_value", [None, False, 0, "unexpected", "wrong-container"])
def test_each_unusable_collection_is_identified(monkeypatch, field, bad_value):
    expected_field = field
    if bad_value == "wrong-container":
        if field == "coastalBarriers":
            bad_value = {"items": "unexpected"}
            expected_field = "coastalBarriers.items"
        else:
            bad_value = [] if field in MAPPING_FIELDS else {}
    root, _, child = field.partition(".")
    resources = {root: {child: bad_value} if child else bad_value}
    api, result = _run_resources(monkeypatch, resources)
    assert result["partial"] is True
    assert result["unavailable_resource_fields"] == [expected_field]
    assert result[COUNT_FIELDS[root]] is None
    assert "Unavailable in this response" in api.format_ipac_summary(result)


@pytest.mark.parametrize("field", sorted(UNAVAILABLE_FIELDS))
def test_malformed_entries_do_not_discard_valid_entries(monkeypatch, field):
    root, _, child = field.partition(".")
    good = {"name": "Valid resource", "phenologySpecies": {"commonName": "Bald Eagle"}}
    good.update({"populationSid": {"val": "P1"}, "population": {"optionalCommonName": "Valid species"}})
    if field in {"populationsBySid", "allReferencedPopulationsBySid"}:
        value = {"P1": good, "P2": None, "P3": []}
    else:
        value = [good, None, [], 42, "bad record"]
    resources = {root: {child: value} if child else value}
    if field == "marineMammals":
        resources["allReferencedPopulationsBySid"] = {"P1": {"optionalCommonName": "Marine mammal"}}
    api, result = _run_resources(monkeypatch, resources)
    assert result["unavailable_resource_fields"] == [field]
    count_key = COUNT_FIELDS[root]
    assert result[count_key] is None
    assert result["returned_counts"][count_key] == 1
    assert "1 records retained; not a complete count" in api.format_ipac_summary(result)


@pytest.mark.parametrize("payload", [None, [], "bad", 42, {"resources": None}, {"resources": False}])
def test_unusable_top_level_resources_still_fail(monkeypatch, payload):
    api = _load_ipac_api()
    _patch_geometry(api, monkeypatch)
    monkeypatch.setattr(api.requests, "post", lambda *_a, **_k: _FakeResponse(payload))
    with pytest.raises(Exception, match="Error parsing IPaC response"):
        api.get_ipac_resources_in_roi(34.55, -107.8, 100)


@pytest.mark.parametrize(
    "resources,field",
    [
        ({"populationsBySid": {"P1": {"population": None}}}, "populationsBySid"),
        ({"populationsBySid": {"P1": {"population": {"sid": None}}}}, "populationsBySid"),
        ({"migbirds": [{"phenologySpecies": None}]}, "migbirds"),
        ({"migbirds": [{"level": []}]}, "migbirds"),
        ({"wetlands": {"items": [{"attributes": None}]}}, "wetlands.items"),
        ({"crithabs": [{"populationSid": None}]}, "crithabs"),
        ({"crithabs": [{"populationSid": {"val": []}}]}, "crithabs"),
        ({"marineMammals": [{"populationSid": None}]}, "marineMammals"),
        ({"marineMammals": [{"populationSid": {"val": {}}}]}, "marineMammals"),
    ],
)
def test_unusable_nested_objects_do_not_crash_other_categories(monkeypatch, resources, field):
    resources = deepcopy(resources)
    resources["fieldOffices"] = [{"officeName": "Valid field office"}]
    api, result = _run_resources(monkeypatch, resources)
    assert field in result["unavailable_resource_fields"]
    assert result["field_offices_count"] == 1
    assert "PARTIAL IPAC RESPONSE" in api.format_ipac_summary(result)


@pytest.mark.parametrize(
    "reference",
    [
        None,
        {},
        {"P1": {"optionalCommonName": "Sea otter"}},
        {"P1": {"population": {"optionalCommonName": "Sea otter"}}},
    ],
)
def test_marine_mammal_reference_availability_never_silently_drops_resource(monkeypatch, reference):
    _, result = _run_resources(
        monkeypatch,
        {
            "marineMammals": [{"populationSid": {"val": "P1"}}],
            "allReferencedPopulationsBySid": reference,
        },
    )
    assert len(result["marine_mammals"]) == 1
    assert result["marine_mammals"][0]["species_id"] == "P1"
    if reference:
        assert result["marine_mammals_count"] == 1
        assert result["marine_mammals"][0]["common_name"] == "Sea otter"
        assert result["partial"] is False
    else:
        assert result["marine_mammals_count"] is None
        assert result["marine_mammals"][0]["common_name"] == "Unknown"
        assert result["partial"] is True


@pytest.mark.parametrize("explicit_empty", [False, True])
def test_missing_and_empty_collections_keep_legacy_empty_behavior(monkeypatch, explicit_empty):
    resources = {field: {} if field in MAPPING_FIELDS else [] for field in COUNT_FIELDS} if explicit_empty else {}
    api, result = _run_resources(monkeypatch, resources)
    assert result["partial"] is False
    assert result["unavailable_resource_fields"] == []
    assert all(result[count] == 0 for count in COUNT_FIELDS.values())
    assert "PARTIAL IPAC RESPONSE" not in api.format_ipac_summary(result)


@pytest.mark.parametrize("wrapped", [False, True])
@pytest.mark.parametrize("items", [[], [{"name": "Example coastal barrier"}]])
def test_coastal_barriers_accept_live_wrapper_and_legacy_list(monkeypatch, wrapped, items):
    value = {"items": items, "truncated": False} if wrapped else items
    _, result = _run_resources(monkeypatch, {"coastalBarriers": value})
    assert result["coastal_barriers"] == items
    assert result["coastal_barriers_count"] == len(items)
    assert result["partial"] is False


@pytest.mark.parametrize("field", ["wetlands", "refuges", "fishHatcheries", "coastalBarriers"])
def test_truncated_wrappers_do_not_claim_complete_counts(monkeypatch, field):
    api, result = _run_resources(monkeypatch, {field: {"items": [{"name": "Retained resource"}], "truncated": True}})
    assert result["partial"] is True
    assert result["unavailable_resource_fields"] == [field]
    assert result[COUNT_FIELDS[field]] is None
    assert result["returned_counts"][COUNT_FIELDS[field]] == 1
    assert "not a complete count" in api.format_ipac_summary(result)
