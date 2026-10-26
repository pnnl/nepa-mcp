"""Offline FUDS source contracts, identities, completeness, privacy, and MCP tests."""

import asyncio
import copy
import json
import os
from pathlib import Path

import pytest
from fastmcp import Client
from nepa_mcp.loader import load_server_module
from nepa_mcp_common.arcgis import ArcGISFeatureQueryResult

FIXTURES = Path(__file__).parent / "fixtures" / "usace_fuds"


@pytest.fixture
def api(monkeypatch):
    api = load_server_module("usace_fuds").api
    monkeypatch.setattr(
        api.ArcGISService,
        "create_roi_buffer",
        lambda *_a: {
            "rings": [[[179.99, 0], [-179.99, 0], [-179.99, 0.01], [179.99, 0]]],
            "spatialReference": {"wkid": 4326},
        },
    )
    for name in ("query_object_ids", "query_features"):
        monkeypatch.setattr(api.ArcGISService, name, lambda *_a, **_k: pytest.fail("Unmocked network call"))
    return api


def feature(api, layer, oid=1, **attrs):
    base = {field: None for field in api.FIELDS[layer]}
    base.update(OBJECTID=oid, **attrs)
    return {"attributes": base, "geometry": {"x": -88, "y": 32, "spatialReference": {"wkid": 4326}}}


def install(api, monkeypatch, rows, failed=()):
    calls = []

    def ids(base, layer, geometry, **kwargs):
        calls.append(("ids", layer, geometry, kwargs))
        if layer in failed:
            raise RuntimeError("service unavailable")
        return [f["attributes"]["OBJECTID"] for f in rows.get(layer, [])]

    def features(base, layer, geometry, **kwargs):
        calls.append(("features", layer, geometry, kwargs))
        batch = {int(x) for x in kwargs["extra_params"]["objectIds"].split(",")}
        return ArcGISFeatureQueryResult(
            copy.deepcopy([f for f in rows.get(layer, []) if f["attributes"]["OBJECTID"] in batch]), []
        )

    monkeypatch.setattr(api.ArcGISService, "query_object_ids", ids)
    monkeypatch.setattr(api.ArcGISService, "query_features", features)
    return calls


@pytest.mark.parametrize(
    "method,args",
    [
        ("get_usace_fuds_property", ("x OR 1=1",)),
        ("get_usace_fuds_projects", ("https://evil.test",)),
        ("get_usace_fuds_properties_in_roi", (91, 0)),
        ("get_usace_fuds_properties_in_roi", (0, float("nan"))),
        ("get_usace_fuds_properties_in_roi", (0, 0, 0.09)),
        ("get_usace_fuds_properties_in_roi", (0, 0, 101)),
        ("get_usace_fuds_projects", ("A04MS0002", 0)),
        ("get_usace_fuds_projects", ("A04MS0002", 1, -1)),
        ("get_usace_fuds_projects", ("A04MS0002", True)),
        ("get_usace_fuds_program_district", ()),
        ("get_usace_fuds_program_district", ("A04MS0002", 0, 0)),
        ("get_usace_fuds_program_district", (None, 0, None)),
        ("get_usace_fuds_munitions_response_sites_in_roi", (0, 181)),
    ],
)
def test_validate_before_network(api, method, args):
    with pytest.raises(ValueError):
        getattr(api, method)(*args)


def test_merge_point_polygon_then_page_and_keep_polygon_only(api, monkeypatch):
    rows = {
        1: [feature(api, 1, FUDSUNIQUEPROPERTYNUMBER="A04MS0002", HAS_PROJECTS="yes")],
        4: [
            feature(api, 4, FUDSUNIQUEPROPERTYNUMBER="A04MS0002", HASPROJECTS="Yes"),
            feature(api, 4, 2, FUDSUNIQUEPROPERTYNUMBER="J09CA7115", HASPROJECTS="tbd"),
        ],
    }
    calls = install(api, monkeypatch, rows)
    r = api.get_usace_fuds_properties_in_roi(0, 179.999, 0.1, max_results=1)
    assert r["records"][0]["match_basis"] == ["point", "polygon"]
    assert r["pagination"]["total"] == 2 and r["pagination"]["next_result_offset"] == 1
    second = api.get_usace_fuds_properties_in_roi(0, 179.999, 0.1, max_results=1, result_offset=1)
    assert second["records"][0]["property_number"] == "J09CA7115"
    assert second["records"][0]["match_basis"] == ["polygon"]
    assert second["result_fingerprint"] == r["result_fingerprint"]
    for kind, layer, geometry, kwargs in calls:
        if kind == "ids":
            assert kwargs["simplify_geometry"] is False and geometry["rings"]


def test_property_conflicts_missing_identity_and_privacy(api, monkeypatch):
    f = feature(api, 1, FUDSUNIQUEPROPERTYNUMBER="A04MS0002", FEATURENAME="Meehan", USACEDISTRICT="sas")
    f["attributes"].update(CURRENTOWNER="do not expose", FEATUREDESCRIPTION="private narrative")
    rows = {
        1: [f, feature(api, 1, 2)],
        4: [feature(api, 4, FUDSUNIQUEPROPERTYNUMBER="A04MS0002", FEATURENAME="Other", USACEDISTRICT="sam")],
    }
    calls = install(api, monkeypatch, rows)
    r = api.get_usace_fuds_property("a04ms0002")
    assert r["records"][0]["conflicts"]["USACEDISTRICT"] == ["sas", "sam"]
    assert any("lacks a valid" in w for w in r["warnings"])
    assert r["source_retrieval_complete"] is True
    assert r["identity_normalization_complete"] is False
    assert r["pagination"]["retrieval_complete"] is False
    assert r["pagination"]["total_kind"] == "lower_bound"
    assert "do not expose" not in json.dumps(r) and "private narrative" not in json.dumps(r)
    assert all("CURRENTOWNER" not in call[3].get("out_fields", "") for call in calls)


@pytest.mark.parametrize(
    "value,state,normalized",
    [
        (None, "missing", None),
        ("tbd", "unknown", None),
        ("weird", "unrecognized", None),
        ("no", "known", False),
        ("Yes", "known", True),
    ],
)
def test_codes_are_not_truthiness(api, value, state, normalized):
    r = api.yes_no(value)
    assert r["state"] == state and r["value"] is normalized and r["raw"] == value


def test_projects_preserve_dates_zero_estimate_and_relationship_conflict(api, monkeypatch):
    rows = {
        2: [
            feature(
                api,
                2,
                FUDSPROPERTYID="A04MS0002",
                DODFUDSPROPERTYIDFK="J09CA7115",
                PROJECTNUMBER="01",
                COSTTOCOMPLETE=0,
                REMEDYINPLACEDATE=2734992000000,
                RESPONSECOMPLETEDATE="bad",
                SITECLOSEOUTDATE=None,
            )
        ]
    }
    calls = install(api, monkeypatch, rows)
    r = api.get_usace_fuds_projects("A04MS0002")
    a = r["records"][0]
    assert a["relationship_verified"] is False and a["cost_estimate"]["raw"] == 0
    assert a["milestones"]["REMEDYINPLACEDATE"]["temporal_role"] == "not established by source field"
    assert a["milestones"]["RESPONSECOMPLETEDATE"]["warning"]
    assert "OR DODFUDSPROPERTYIDFK" in calls[0][3]["where"]
    assert "not published" in a["cost_estimate"]["units"]


def test_recorded_and_geographic_offices_have_separate_basis(api, monkeypatch):
    rows = {
        1: [feature(api, 1, FUDSUNIQUEPROPERTYNUMBER="A04MS0002", USACEDISTRICT="sas")],
        9: [feature(api, 9, DIST="SAS", MIL_DIST="Savannah", WEB="https://www.sas.usace.army.mil")],
    }
    calls = install(api, monkeypatch, rows)
    r = api.get_usace_fuds_program_district("A04MS0002")
    assert r["recorded_districts"] == ["SAS"] and r["resolution_basis"] == "recorded_property_assignment"
    assert r["records"][0]["official_url"].startswith("https://www.sas")
    assert "DIST IN ('SAS')" in [c for c in calls if c[1] == 9][0][3]["where"]
    rows[9].append(feature(api, 9, 2, DIST="SAM", MIL_DIST="Mobile"))
    r = api.get_usace_fuds_program_district(latitude=32, longitude=-88)
    assert r["geographic_districts"] == ["SAM", "SAS"] and r["recorded_districts"] == []


def test_unknown_office_is_unresolved(api, monkeypatch):
    install(api, monkeypatch, {1: [feature(api, 1, FUDSUNIQUEPROPERTYNUMBER="A04MS0002", USACEDISTRICT="tbd")]})
    r = api.get_usace_fuds_program_district("A04MS0002")
    assert not r["records"] and r["recorded_districts"] == ["TBD"] and r["warnings"]


@pytest.mark.parametrize("failed,expected", [((), "empty"), ((1,), "partial"), ((1, 4), "unavailable")])
def test_empty_partial_unavailable(api, monkeypatch, failed, expected):
    install(api, monkeypatch, {}, failed)
    r = api.get_usace_fuds_property("A04MS0002")
    assert r["status"] == expected
    assert r["pagination"]["retrieval_complete"] == (not failed)
    assert r["pagination"]["has_more"] is (None if failed else False)


def test_transfer_cap_and_missing_batch_ids(api, monkeypatch):
    rows = {1: [feature(api, 1, i, FUDSUNIQUEPROPERTYNUMBER=f"A04MS{i:04}") for i in range(1, 4)]}
    install(api, monkeypatch, rows)
    monkeypatch.setattr(api, "CAP", 2)
    r = api.get_usace_fuds_property("A04MS0002")
    assert r["sources"][0]["total"] == 3 and r["sources"][0]["status"] == "partial"
    assert r["pagination"]["total_kind"] == "lower_bound"
    monkeypatch.setattr(api.ArcGISService, "query_features", lambda *_a, **_k: ArcGISFeatureQueryResult([], []))
    r = api.get_usace_fuds_property("A04MS0002")
    assert any("missing" in w for w in r["sources"][0]["warnings"])


def test_source_changed_during_fetch(api, monkeypatch):
    install(api, monkeypatch, {})
    ids = iter([[1], [1, 2], [], []])
    monkeypatch.setattr(api.ArcGISService, "query_object_ids", lambda *_a, **_k: next(ids))
    monkeypatch.setattr(
        api.ArcGISService,
        "query_features",
        lambda *_a, **_k: ArcGISFeatureQueryResult([feature(api, 1, FUDSUNIQUEPROPERTYNUMBER="A04MS0002")], []),
    )
    r = api.get_usace_fuds_property("A04MS0002")
    assert any("changed" in w for w in r["sources"][0]["warnings"])


def test_mrs_does_not_join_by_proximity_and_keeps_priority(api, monkeypatch):
    install(
        api,
        monkeypatch,
        {
            3: [
                feature(
                    api,
                    3,
                    FUDSPROPERTYID="J09CA0172",
                    FUDSSITEID="01",
                    PROJECTNUMBER="J09CA017201",
                    RELATIVEPRIORITY="10",
                    PROJECTSTATUS="responseComplete",
                    FISCALYEAR=2024,
                )
            ]
        },
    )
    r = api.get_usace_fuds_munitions_response_sites_in_roi(32, -88, 0.1)
    assert r["records"][0]["raw"]["RELATIVEPRIORITY"] == "10"
    assert r["records"][0]["coded_values"]["RELATIVEPRIORITY"]["label"] == "NLR"
    assert r["records"][0]["raw"]["FISCALYEAR"] == 2024


def test_source_shaped_public_fixtures_and_contract_fields(api):
    for layer in [1, 2, 3, 4, 9]:
        d = json.loads((FIXTURES / f"layer-{layer}.json").read_text())
        attrs = d["features"][0]["attributes"]
        assert set(api.FIELDS[layer]).issubset(attrs)
        assert "CURRENTOWNER" not in attrs and "FEATUREDESCRIPTION" not in attrs


def test_mcp_discovery_readonly_and_schema_bounds():
    async def run():
        async with Client(load_server_module("usace_fuds").mcp) as client:
            tools = await client.list_tools()
            assert len(tools) == 5
            for t in tools:
                assert t.annotations.readOnlyHint and not t.annotations.destructiveHint
            roi = next(t for t in tools if t.name == "get_usace_fuds_properties_in_roi")
            assert roi.inputSchema["properties"]["buffer_miles"]["minimum"] == 0.1
            assert roi.inputSchema["properties"]["max_results"]["maximum"] == 100

    asyncio.run(run())


@pytest.mark.skipif(os.environ.get("NEPA_FUDS_LIVE") != "1", reason="Opt-in live service check")
def test_live_primary_source():
    api = load_server_module("usace_fuds").api
    r = api.get_usace_fuds_projects("A04MS0002")
    assert r["status"] == "ok" and r["records"]
    assert r["records"][0]["relationship_verified"]


def test_recorded_assignment_conflicts_with_geographic_candidates(api, monkeypatch):
    rows = {
        1: [feature(api, 1, FUDSUNIQUEPROPERTYNUMBER="A04MS0002", USACEDISTRICT="sas", LATITUDE=32, LONGITUDE=-88)],
        9: [feature(api, 9, DIST="SAS")],
    }
    install(api, monkeypatch, rows)
    original = api.ArcGISService.query_features

    def features(base, layer, geometry, **kwargs):
        return original(base, layer, geometry, **kwargs)

    ids_original = api.ArcGISService.query_object_ids

    def ids(base, layer, geometry, **kwargs):
        if layer == 9:
            rows[9] = [feature(api, 9, DIST="SAM" if geometry else "SAS")]
        return ids_original(base, layer, geometry, **kwargs)

    monkeypatch.setattr(api.ArcGISService, "query_object_ids", ids)
    result = api.get_usace_fuds_program_district("A04MS0002")
    assert result["recorded_districts"] == ["SAS"]
    assert result["geographic_districts"] == ["SAM"]
    assert any("disagrees" in w for w in result["warnings"])
