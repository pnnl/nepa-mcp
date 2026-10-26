"""Source-scoped BRAC contracts; blocked-source group examples are explicitly synthetic."""

import asyncio
import os
from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from fastmcp import Client
from nepa_mcp.loader import load_server_module
from nepa_mcp_common.arcgis import ArcGISFeatureQueryResult

FIXTURES = Path(__file__).parent / "fixtures" / "dow_brac"


@pytest.fixture
def server(monkeypatch):
    m = load_server_module("dow_brac")
    import sys

    adapters = sys.modules["src.apis.adapters"]
    adapters._CACHE.clear()
    monkeypatch.setattr(adapters.requests, "get", lambda *_a, **_k: pytest.fail("Unmocked network"))
    monkeypatch.setattr(
        m.spatial_api.ArcGISService, "query_object_ids", lambda *_a, **_k: pytest.fail("Unmocked GIS IDs")
    )
    monkeypatch.setattr(
        m.spatial_api.ArcGISService, "query_features", lambda *_a, **_k: pytest.fail("Unmocked GIS features")
    )
    monkeypatch.setattr(
        m.spatial_api.ArcGISService,
        "create_roi_buffer",
        lambda *_a: {
            "rings": [[[179.99, 0], [-179.99, 0], [-179.99, 0.01], [179.99, 0]]],
            "spatialReference": {"wkid": 4326},
        },
    )
    return m


class Response:
    def __init__(self, data, status=200, headers=None):
        self.data = data.encode() if isinstance(data, str) else data
        self.status_code = status
        self.headers = headers or {"Content-Type": "text/html"}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def iter_content(self, *args):
        yield self.data


def sources(server, monkeypatch):
    import sys

    adapters = sys.modules["src.apis.adapters"]
    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs))
        for year in [1988, 1991, 1993, 1995, 2005]:
            if url.endswith(f"/brac-{year}/"):
                return Response((FIXTURES / f"round{year}.html").read_text())
        if "/pennsylvania-reserve-component/fort-indiantown-gap/" in url:
            return Response((FIXTURES / "indiantown.html").read_text())
        if url == "https://www.denix.osd.mil/armybrac/":
            return Response((FIXTURES / "army.html").read_text())
        if url.endswith("/properties-for-sale/"):
            return Response((FIXTURES / "offers.html").read_text())
        return Response("restricted", 403)

    monkeypatch.setattr(adapters.requests, "get", get)
    return calls


@pytest.mark.parametrize(
    "function,args",
    [
        ("search_brac_installations", ()),
        ("search_brac_installations", (None, "marines")),
        ("search_brac_installations", (None, None, "ZZ")),
        ("search_brac_installations", (None, None, None, 2026)),
        ("search_brac_installations", ("x", None, None, None, 0)),
        ("get_brac_installation", ("https://evil.test",)),
        ("get_brac_installation", ("../../key",)),
    ],
)
def test_search_identity_validation_before_requests(server, function, args):
    with pytest.raises(ValueError):
        getattr(server.installations_api, function)(*args)


@pytest.mark.parametrize("args", [(91, 0), (0, 181), (float("nan"), 0), (0, 0, 0.09), (0, 0, 101), (0, 0, 25, "yes")])
def test_spatial_validation_before_requests(server, args):
    with pytest.raises(ValueError):
        server.spatial_api.get_brac_installations_in_roi(*args)


def test_directory_action_groups_and_independent_identity(server, monkeypatch):
    sources(server, monkeypatch)
    r = server.installations_api.search_brac_installations(query="Fort Indiantown")
    row = r["records"][0]
    assert row["actions"][0]["round"] == 1995 and row["actions"][0]["program"] == "BRAC"
    assert row["identity_crosswalks"] and not row["geometry_available"]
    assert all(a["round"] == 1995 for a in row["actions"])
    r = server.installations_api.search_brac_installations(query="Red River")
    assert len(r["records"]) == 2
    assert {a["round"] for r in r["records"] for a in r["actions"]} == {1995, 2005}
    # Source URLs differ; they remain unresolved identities instead of name-merging.
    assert len({r["installation_id"] for r in r["records"]}) == 2
    assert any(a["action"] == "realignment" for r in r["records"] for a in r["actions"])


def test_no_round_from_navigation_and_nonbrac_not_imported(server, monkeypatch):
    sources(server, monkeypatch)
    r = server.installations_api.search_brac_installations(component="army", brac_round=2005, max_results=1)
    assert r["pagination"]["next_result_offset"] == 1
    assert all(a["round"] == 2005 for a in r["records"][0]["matched_actions"])
    assert not any(a.get("program") == "Non-BRAC Excess" for x in r["records"] for a in x["actions"])
    r = server.installations_api.search_brac_installations(component="navy")
    assert all(not x["actions"] and "Curated" in x["identity_basis"] for x in r["records"])
    assert r["status"] == "partial" and r["source_manifest"]["navy"]["validation_status"].startswith("HTTP 403")


def test_documents_and_conveyance_scope_and_zero_acres(server, monkeypatch):
    calls = sources(server, monkeypatch)
    identity = server.installations_api.local_id("https://www.denix.osd.mil/armybrac/brac-1995/fort-indiantown-gap/")
    docs = server.documents_api.get_brac_documents(identity, max_results=1)
    assert docs["pagination"]["has_more"] and docs["records"][0]["retrieval_status"] == "metadata_only"
    assert not docs["records"][0]["body_reviewed"]
    r = server.conveyances_api.get_brac_conveyance_records(identity)
    row = r["records"][0]
    assert row["scope"] == "installation_summary" and row["source_reported_acreage"]["Remaining Acres"] == "0.00"
    assert not row["cleanup_complete_established"] and not row["executed_parcel_transactions_established"]
    assert all(call[1]["allow_redirects"] is False for call in calls)


def test_planned_disposals_and_explicit_crosswalks(server, monkeypatch):
    sources(server, monkeypatch)
    identity = server.installations_api.local_id(
        "https://www.denix.osd.mil/armybrac/brac-1995/defense-distribution-depot-memphis/"
    )
    r = server.offers_api.get_brac_property_offers(identity)
    row = r["records"][0]
    assert row["evidence_type"] == "planned_disposal" and row["bid_deadline"] is None
    assert row["expected_disposal_date"] == "2029-12-31" and row["published_acres"] == "34.31"
    assert row["parcel_label"] == "Dunn Field – West"
    r = server.offers_api.get_brac_property_offers("navy:alameda")
    assert not r["records"] and any(s["status"] == "unsupported" for s in r["sources"])


def test_html_schema_challenge_cache_and_restricted_source(server, monkeypatch):
    import sys

    adapters = sys.modules["src.apis.adapters"]
    monkeypatch.setattr(adapters.requests, "get", lambda *a, **k: Response("<html>HTTP 200 challenge</html>"))
    c, r = adapters.fetch("https://www.denix.osd.mil/armybrac/")
    assert c is None and r["status"] == "schema_error"
    monkeypatch.setattr(adapters.requests, "get", lambda *a, **k: Response("forbidden", 403))
    c, r = adapters.fetch("https://www.bracpmo.navy.mil/BRAC-Bases/")
    assert c is None and r["status"] == "restricted"
    sources(server, monkeypatch)
    url = "https://www.denix.osd.mil/armybrac/brac-2005/"
    c, r = adapters.fetch(url)
    c2, r2 = adapters.fetch(url)
    assert r2["cached"] and r2["retrieved_at"] == r["retrieved_at"]
    c, r = adapters.fetch("https://evil.test/")
    assert c is None and r["status"] == "unsupported"


def test_synthetic_explicit_site_ou_groups_remain_scoped_candidates(server):
    content = BeautifulSoup(
        '<main><h3>Operable Unit 2</h3><ul><li>IR Site 7 <a href="https://www.bracpmo.navy.mil/a.pdf">Plan</a></li></ul></main>',
        "html.parser",
    )
    records = server.environmental_sites_api.parse_sites(content, "navy:alameda", "https://www.bracpmo.navy.mil/index/")
    assert records[0]["site_id"] == "navy:alameda:IR:7" and records[0]["operable_units"] == ["2"]
    assert records[0]["geometry_available"] is False and "pending" in records[0]["inventory_verification"]
    content = BeautifulSoup("<main><p>This document mentions IR Site 7.</p></main>", "html.parser")
    assert (
        server.environmental_sites_api.parse_sites(content, "navy:alameda", "https://www.bracpmo.navy.mil/index/") == []
    )


def test_unknown_notice_deadline_and_source_failure_are_visible(server, monkeypatch):
    sources(server, monkeypatch)
    r = server.notices_api.get_brac_public_notices("navy:roosevelt-roads")
    assert any(x["status"] == "restricted" for x in r["sources"])
    assert not r["records"] and r["status"] == "partial"
    with pytest.raises(ValueError):
        server.notices_api.get_brac_public_notices("navy:roosevelt-roads", "2026-02-30")


def test_controls_reject_guessed_crosswalks_and_handle_oversize_mime(server, monkeypatch):
    r = server.controls_api.get_brac_land_use_controls("navy:alameda", site_id="IR:7")
    assert not r["records"] and r["sources"][0]["status"] == "unsupported"
    monkeypatch.setattr(
        server.controls_api.requests,
        "get",
        lambda *_a, **_k: Response(b"<html>", headers={"Content-Type": "application/pdf"}),
    )
    r = server.controls_api.extract_control("https://www.nae.usace.army.mil/a.pdf")
    assert r["status"] == "invalid_pdf_signature" and not r["body_reviewed"]
    monkeypatch.setattr(
        server.controls_api.requests,
        "get",
        lambda *_a, **_k: Response(b"x" * (10 * 1024 * 1024 + 1), headers={"Content-Type": "application/pdf"}),
    )
    assert server.controls_api.extract_control("https://www.nae.usace.army.mil/a.pdf")["status"] == "oversized"


def test_frs_many_interests_and_historical_unresolved_polygons(server, monkeypatch):
    api = server.spatial_api
    calls = []

    def ids(base, layer, geometry, **kwargs):
        calls.append((base, kwargs))
        return [1, 2] if layer == 5 else [1]

    def features(base, layer, geometry, **kwargs):
        fields = api.FRS_FIELDS if layer == 5 else api.HIST_FIELDS
        rows = []
        for oid in [1, 2] if layer == 5 else [1]:
            attrs = {f: None for f in fields}
            attrs.update(OBJECTID=oid)
            if layer == 5:
                attrs.update(
                    REGISTRY_ID="110000000001",
                    PGM_SYS_ID=str(oid),
                    PGM_SYS_ACRNM="BRAC",
                    ACCURACY_VALUE=-999,
                    ACTIVE_STATUS="ACTIVE",
                )
            else:
                attrs.update(BRAC_SITE="YES", COMPONENT="Historical code")
            rows.append({"attributes": attrs, "geometry": {"x": 179.999, "y": 0, "spatialReference": {"wkid": 4326}}})
        assert kwargs["out_sr"] == 4326
        return ArcGISFeatureQueryResult(rows, [])

    monkeypatch.setattr(api.ArcGISService, "query_object_ids", ids)
    monkeypatch.setattr(api.ArcGISService, "query_features", features)
    r = api.get_brac_installations_in_roi(0, 179.999, 0.1, True)
    assert len(r["records"]) == 3 and all(x["installation_id"] is None for x in r["records"])
    interests = [x for x in r["records"] if x["match_basis"] == "reference_point"]
    assert len({x["frs_registry_id"] for x in interests}) == 1
    assert len({x["program_identity"]["program_id"] for x in interests}) == 2
    assert interests[0]["raw"]["ACCURACY_VALUE"] == -999
    assert all(kwargs["simplify_geometry"] is False for base, kwargs in calls)
    assert any(x["match_basis"] == "historical_polygon_intersection" for x in r["records"])


def test_mcp_nine_readonly_tools_and_bounds(server):
    async def check():
        async with Client(server.mcp) as c:
            tools = await c.list_tools()
            assert len(tools) == 9
            assert all(t.annotations.readOnlyHint and not t.annotations.destructiveHint for t in tools)
            spatial = next(t for t in tools if t.name == "get_brac_installations_in_roi")
            assert spatial.inputSchema["properties"]["buffer_miles"]["minimum"] == 0.1

    asyncio.run(check())


@pytest.mark.skipif(os.environ.get("NEPA_BRAC_LIVE") != "1", reason="Explicit live source check")
def test_live_army_planned_disposals():
    m = load_server_module("dow_brac")
    identity = m.installations_api.local_id(
        "https://www.denix.osd.mil/armybrac/brac-1995/defense-distribution-depot-memphis/"
    )
    r = m.offers_api.get_brac_property_offers(identity)
    assert r["records"] and r["records"][0]["evidence_type"] == "planned_disposal"


def test_verified_army_notice_scope_and_ambiguous_deadline(server, monkeypatch):
    sources(server, monkeypatch)
    identity = server.installations_api.local_id(
        "https://www.denix.osd.mil/armybrac/brac-2005/umatilla-chemical-depot-2005/"
    )
    result = server.notices_api.get_brac_public_notices(identity, published_on_or_after="2026-10-01")
    assert len(result["records"]) == 3
    assert all(row["published_date"] == "2026-10-15" for row in result["records"])
    assert all(row["deadline"] is None and "unresolved" in row["participation_status"] for row in result["records"])
    assert server.notices_api.get_brac_public_notices(identity, published_on_or_after="2026-10-16")["records"] == []
