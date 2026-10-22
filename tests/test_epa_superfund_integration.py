"""
Integration tests for the EPA Superfund MCP server.

These load ``epa_superfund/server.py`` through a real ``fastmcp.Client`` and
exercise the tool -> api -> adapter -> formatter -> Markdown path with only
the network boundaries (ArcGIS queries, Envirofacts DMAP rows, and Federal Register JSON)
replaced by in-memory responses.
"""

from __future__ import annotations

import asyncio
import importlib.util
import re
import sys
from pathlib import Path

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from nepa_mcp_common.arcgis import ArcGISFeatureQueryResult, ArcGISService

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "epa_superfund"
ROI = {
    "rings": [[[-74.3, 40.0], [-74.0, 40.0], [-74.0, 40.3], [-74.3, 40.3], [-74.3, 40.0]]],
    "spatialReference": {"wkid": 4326},
}
TOOLS = {
    "search_epa_superfund_sites",
    "get_epa_superfund_sites_in_roi",
    "get_epa_superfund_site",
    "get_epa_superfund_operable_units",
    "get_epa_superfund_institutional_controls",
    "get_epa_superfund_documents",
    "get_epa_superfund_cleanup_actions",
    "get_epa_superfund_contaminants",
    "get_epa_superfund_public_notices",
}
POINT = {
    "attributes": {
        "ObjectId2": 651,
        "Site_Name": "Bog Creek Farm",
        "Site_EPA_ID": "NJD063157150",
        "SEMS_ID": 200397,
        "Region_ID": 2,
        "State": "New Jersey",
        "City": "Howell Township",
        "Status": "NPL Site",
        "Listing_Date": "09/08/1983",
        "Site_has_had_a_Partial_Deletion": "No",
        "Final_FR_Notice": '<a href="https://semspub.epa.gov/src/document/11/189620" target="_blank">09/08/1983 (PDF)</a>',
    },
    "geometry": {"x": -74.161111, "y": 40.150831},
}
BOUNDARY = {
    "attributes": {
        "OBJECTID": 137,
        "EPA_ID": "NJD063157150",
        "SITE_NAME": "BOG CREEK FARM",
        "NPL_STATUS_CODE": "F",
        "SITE_FEATURE_CLASS": 5,
        "SITE_FEATURE_TYPE": "Comprehensive Site Area",
    },
    "geometry": {
        "rings": [
            [[-74.1614, 40.1505], [-74.1586, 40.1505], [-74.1586, 40.1523], [-74.1614, 40.1523], [-74.1614, 40.1505]]
        ]
    },
}
OU_FEATURES = [
    {
        "attributes": {
            "OBJECTID": index,
            "EPA_ID": "NJD063157150",
            "SITE_FEATURE_CLASS": 4,
            "SITE_FEATURE_TYPE": "Operable Unit Boundary",
            "SITE_FEATURE_NAME": f"OU {index}: Area",
        }
    }
    for index in range(1, 6)
]
IC_FEATURES = [
    {
        "attributes": {
            "OBJECTID": 50,
            "EPA_ID": "NJD063157150",
            "SITE_FEATURE_CLASS": 3,
            "SITE_FEATURE_TYPE": "Eroded Area",
        }
    }
]
DMAP_SITE = {
    "site_id": "0200397",
    "epa_id": "NJD063157150",
    "name": "BOG CREEK FARM",
    "npl_status_code": "F",
    "fk_ref_state_code": "NJ",
    "saa_agreement_site_ind": "N",
}
CONTAMINANT = {
    "fk_site_id": "0200397",
    "preferred_contaminant_name": "CHROMIUM",
    "media_name": "Soil",
    "operable_unit_num": "01",
    "action_name": "Record of Decision",
    "type_code": "RO",
    "seq": 1,
}
FEDERAL_REGISTER = {"count": 0, "results": []}


def _load_server():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src.") or module_name.startswith("_epa_superfund_int_"):
            sys.modules.pop(module_name, None)
    sys.path[:] = [entry for entry in sys.path if entry != str(SERVER_DIR)]
    sys.path.insert(0, str(SERVER_DIR))
    spec = importlib.util.spec_from_file_location("_epa_superfund_int_server", SERVER_DIR / "server.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["_epa_superfund_int_server"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def server(monkeypatch):
    module = _load_server()
    adapters = sys.modules["src.apis.adapters"]
    calls: list[str] = []
    layers = {
        "Superfund_National": [POINT],
        "Site_Boundaries": [BOUNDARY],
        "Operable_Unit": OU_FEATURES,
        "Institutional_Control": IC_FEATURES,
        "FRS_INTERESTS": [],
        "Sites_In_Reuse": [],
    }

    def query_features(service_url, *_args, **kwargs):
        calls.append(service_url)
        features = next(value for key, value in layers.items() if key in service_url)
        selected = kwargs.get("extra_params", {}).get("objectIds")
        if selected is not None:
            oid_field = "ObjectId2" if "Superfund_National" in service_url else "OBJECTID"
            features = [f for f in features if str(f["attributes"][oid_field]) in selected.split(",")]
        return ArcGISFeatureQueryResult(features=[dict(f) for f in features], warnings=[], truncated=False)

    def query_object_ids(service_url, *_args, **_kwargs):
        features = query_features(service_url).features
        oid_field = "ObjectId2" if "Superfund_National" in service_url else "OBJECTID"
        return sorted({f["attributes"][oid_field] for f in features})

    def get_json_rows(url, **_kwargs):
        calls.append(url)
        return [dict(CONTAMINANT)] if "contaminants" in url else [dict(DMAP_SITE)]

    def get_json(url, *, params=None, **_kwargs):
        calls.append(url)
        return dict(FEDERAL_REGISTER)

    ArcGISService.create_roi_buffer = staticmethod(lambda *_a, **_k: ROI)
    ArcGISService.query_features = staticmethod(query_features)
    monkeypatch.setattr(ArcGISService, "query_object_ids", query_object_ids)
    monkeypatch.setattr(adapters, "get_json_rows", get_json_rows)
    monkeypatch.setattr(adapters, "get_json", get_json)
    module.calls = calls
    return module


def _call(module, name, arguments):
    async def run():
        async with Client(module.mcp) as client:
            result = await client.call_tool(name, arguments)
            return result.content[0].text

    return asyncio.run(run())


def _tools(module):
    async def run():
        async with Client(module.mcp) as client:
            return await client.list_tools()

    return asyncio.run(run())


def test_all_nine_tools_are_registered_with_bounded_paging(server):
    tools = {tool.name: tool for tool in _tools(server)}
    assert set(tools) == TOOLS
    for name, tool in tools.items():
        properties = tool.inputSchema["properties"]
        if name != "get_epa_superfund_site":
            assert properties["max_results"]["minimum"] == 1 and properties["max_results"]["maximum"] == 100
            assert properties["result_offset"]["minimum"] == 0 and properties["result_offset"]["default"] == 0
            fingerprint_schema = next(s for s in properties["result_fingerprint"]["anyOf"] if s["type"] == "string")
            assert fingerprint_schema["pattern"] == r"^[0-9a-f]{64}$"
    roi = tools["get_epa_superfund_sites_in_roi"].inputSchema["properties"]
    assert roi["buffer_miles"]["default"] == 25.0 and roi["inventory_scope"]["default"] == "npl_and_mapped"


@pytest.mark.parametrize(
    ("tool", "arguments", "expected"),
    [
        ("search_epa_superfund_sites", {"query": "bog creek", "state": "NJ"}, "Bog Creek Farm"),
        (
            "get_epa_superfund_sites_in_roi",
            {"latitude": 40.15, "longitude": -74.16, "buffer_miles": 5},
            "point+polygon",
        ),
        ("get_epa_superfund_site", {"epa_id": "NJD063157150"}, "SEMS site id: 0200397"),
        ("get_epa_superfund_operable_units", {"epa_id": "NJD063157150", "max_results": 2}, "result_offset=2"),
        ("get_epa_superfund_institutional_controls", {"epa_id": "NJD063157150"}, "Eroded Area"),
        ("get_epa_superfund_documents", {"epa_id": "NJD063157150"}, "Federal Register: final NPL listing"),
        ("get_epa_superfund_cleanup_actions", {"epa_id": "NJD063157150"}, "Finalized on the NPL"),
        ("get_epa_superfund_contaminants", {"epa_id": "NJD063157150"}, "CHROMIUM"),
        ("get_epa_superfund_public_notices", {"epa_id": "NJD063157150"}, "Federal Register: final NPL listing"),
    ],
)
def test_each_tool_returns_markdown_with_a_sources_table(server, tool, arguments, expected):
    text = _call(server, tool, arguments)
    assert text.startswith("## EPA Superfund") and expected in text
    assert "### Sources" in text and "| Source | State | Records | Note |" in text
    assert all(
        url.startswith(("https://services.arcgis.com/", "https://data.epa.gov/", "https://www.federalregister.gov/"))
        for url in server.calls
    )


def test_independent_pagination_and_offsets_past_the_end(server):
    second = _call(
        server, "get_epa_superfund_operable_units", {"epa_id": "NJD063157150", "max_results": 2, "result_offset": 2}
    )
    past = _call(server, "get_epa_superfund_institutional_controls", {"epa_id": "NJD063157150", "result_offset": 5})
    assert "(3–4 of 6)" in second and "Map feature 2**" in second and "Map feature 1**" not in second
    assert "No mapped control records at result_offset=5; 1 mapped control records are available." in past


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("get_epa_superfund_site", {}),
        ("get_epa_superfund_site", {"epa_id": "NJD063157150", "sems_id": "0200397"}),
        ("get_epa_superfund_site", {"sems_id": "02003970"}),
        ("get_epa_superfund_contaminants", {"epa_id": "NJD063157150'--"}),
        ("search_epa_superfund_sites", {}),
        ("search_epa_superfund_sites", {"query": "bog%"}),
        ("search_epa_superfund_sites", {"state": "ZZ"}),
        ("search_epa_superfund_sites", {"npl_status": "clean"}),
        ("get_epa_superfund_cleanup_actions", {"epa_id": "NJD063157150", "operable_unit": "001"}),
        ("get_epa_superfund_public_notices", {"epa_id": "NJD063157150", "published_on_or_after": "2026-02-30"}),
        ("get_epa_superfund_documents", {"epa_id": "NJD063157150", "max_results": 0}),
        ("get_epa_superfund_documents", {"epa_id": "NJD063157150", "result_fingerprint": "invalid"}),
    ],
)
def test_invalid_arguments_are_rejected_before_upstream_calls(server, tool, arguments):
    with pytest.raises(ToolError):
        _call(server, tool, arguments)
    assert server.calls == []


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("search_epa_superfund_sites", {"query": "Bog"}),
        ("get_epa_superfund_sites_in_roi", {"latitude": 40.15, "longitude": -74.16}),
        *[
            ("get_epa_superfund_" + suffix, {"epa_id": "NJD063157150"})
            for suffix in (
                "operable_units",
                "institutional_controls",
                "documents",
                "cleanup_actions",
                "contaminants",
                "public_notices",
            )
        ],
    ],
)
def test_each_list_tool_accepts_unchanged_fingerprint_across_pages(server, monkeypatch, tool, arguments):
    api = sys.modules["src.apis.superfund_api"]
    monkeypatch.setattr(api, "now_utc", lambda: "2026-10-21T00:00:00Z")
    first = _call(server, tool, {**arguments, "max_results": 1})
    token = re.search(r"\*\*Result fingerprint:\*\* `([0-9a-f]{64})`", first).group(1)
    monkeypatch.setattr(api, "now_utc", lambda: "2026-10-21T00:01:00Z")
    second = _call(server, tool, {**arguments, "max_results": 1, "result_offset": 1, "result_fingerprint": token})
    assert token in second and "2026-10-21T00:01:00Z" in second


@pytest.mark.parametrize(("field", "value"), [("OBJECTID", 51), ("SITE_FEATURE_NAME", "Changed area")])
def test_changed_ids_or_attributes_reject_continuation_pages(server, monkeypatch, field, value):
    arguments = {"epa_id": "NJD063157150", "max_results": 1}
    first = _call(server, "get_epa_superfund_institutional_controls", arguments)
    token = re.search(r"\*\*Result fingerprint:\*\* `([0-9a-f]{64})`", first).group(1)
    monkeypatch.setitem(IC_FEATURES[0]["attributes"], field, value)
    with pytest.raises(ToolError, match="Evidence or source coverage changed"):
        _call(
            server,
            "get_epa_superfund_institutional_controls",
            {**arguments, "result_offset": 1, "result_fingerprint": token},
        )


def test_changed_source_coverage_rejects_continuation_pages(server, monkeypatch):
    arguments = {"epa_id": "NJD063157150"}
    first = _call(server, "get_epa_superfund_institutional_controls", arguments)
    token = re.search(r"\*\*Result fingerprint:\*\* `([0-9a-f]{64})`", first).group(1)

    def unavailable(*_a, **_k):
        raise RuntimeError("source unavailable")

    monkeypatch.setattr(ArcGISService, "query_object_ids", unavailable)
    with pytest.raises(ToolError, match="Evidence or source coverage changed"):
        _call(
            server,
            "get_epa_superfund_institutional_controls",
            {**arguments, "result_offset": 1, "result_fingerprint": token},
        )
