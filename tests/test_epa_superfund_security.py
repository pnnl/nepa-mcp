"""
Security tests for the EPA Superfund server.

Cover pre-upstream input validation, where-clause and DMAP path construction,
neutralization of HTML-bearing source fields, EPA-only link emission, the
restriction to configured API hosts, absence of hardcoded secrets,
and that upstream error detail never reaches tool output.
"""

from __future__ import annotations

import importlib.util
import math
import re
import sys
from pathlib import Path

import pytest
import requests

from nepa_mcp_common.arcgis import ArcGISFeatureQueryResult, ArcGISService

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "epa_superfund"


def _load_server():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src.") or module_name.startswith("_epa_superfund_sec_"):
            sys.modules.pop(module_name, None)
    sys.path[:] = [entry for entry in sys.path if entry != str(SERVER_DIR)]
    sys.path.insert(0, str(SERVER_DIR))
    spec = importlib.util.spec_from_file_location("_epa_superfund_sec_server", SERVER_DIR / "server.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["_epa_superfund_sec_server"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def modules(monkeypatch):
    server = _load_server()
    return server, sys.modules["src.apis.superfund_api"], sys.modules["src.apis.adapters"]


@pytest.mark.parametrize(
    ("latitude", "longitude", "buffer"),
    [
        (999, -74, 25),
        (40, 181, 25),
        (40, -74, 0),
        (40, -74, 100.5),
        (math.nan, -74, 25),
        (40, math.inf, 25),
        ("x", -74, 25),
    ],
)
def test_geo_inputs_rejected(modules, latitude, longitude, buffer):
    server, _, _ = modules
    with pytest.raises(ValueError):
        server._validate_geo_inputs(latitude, longitude, buffer)


@pytest.mark.parametrize(("limit", "offset"), [(0, 0), (101, 0), (10, -1), (10, 10_000), (True, 0), ("ten", 0)])
def test_result_window_rejected(modules, limit, offset):
    server, _, _ = modules
    with pytest.raises(ValueError):
        server._validate_result_window(limit, offset)


@pytest.mark.parametrize(
    "epa_id",
    ["NJD063157150' OR '1'='1", "NJD06315715%", "../../etc/passwd", "NJD06315\n7150", "<script>alert(1)</script>"],
)
def test_injection_identifiers_never_reach_upstream(modules, monkeypatch, epa_id):
    _, api, adapters = modules
    calls = []
    monkeypatch.setattr(ArcGISService, "query_object_ids", lambda *_a, **k: calls.append(k) or [])
    ArcGISService.query_features = staticmethod(
        lambda *a, **k: calls.append(k) or ArcGISFeatureQueryResult([], [], False)
    )
    monkeypatch.setattr(adapters, "get_json_rows", lambda url, **_k: calls.append(url) or [])
    for function in (
        api.get_epa_superfund_operable_units,
        api.get_epa_superfund_contaminants,
        api.get_epa_superfund_documents,
    ):
        with pytest.raises(ValueError, match="epa_id"):
            function(epa_id)
    assert calls == []


def test_where_clauses_escape_quotes_and_dmap_paths_avoid_unsafe_characters(modules, monkeypatch):
    _, api, adapters = modules
    wheres, urls = [], []
    monkeypatch.setattr(ArcGISService, "query_object_ids", lambda *_a, **k: wheres.append(k["where"]) or [])
    ArcGISService.query_features = staticmethod(
        lambda *a, **k: wheres.append(k["extra_params"]["where"]) or ArcGISFeatureQueryResult([], [], False)
    )
    monkeypatch.setattr(adapters, "get_json_rows", lambda url, **_k: urls.append(url) or [])
    api.search_epa_superfund_sites(query="O'Brien & Sons / Co", state="NJ", inventory_scope="sems_candidates")
    assert wheres and all("O''BRIEN" in where for where in wheres)
    assert all(re.sub(r"'(?:[^']|'')*'", "", where).count("'") == 0 for where in wheres)
    path = urls[0].split("/sems.envirofacts_site/", 1)[1]
    assert not set("'&+") & set(path) and "/name/like/@O@BRIEN%20@%20SONS%20@%20CO@/" in path
    with pytest.raises(ValueError):
        adapters.dmap_value("A/B")


def test_source_markup_and_foreign_links_are_neutralized(modules, monkeypatch):
    _, api, adapters = modules
    monkeypatch.setattr(ArcGISService, "query_object_ids", lambda *_a, **_k: [1])
    feature = {
        "attributes": {
            "OBJECTID": 1,
            "EPA_ID": "NJD063157150",
            "SITE_FEATURE_CLASS": 3,
            "SITE_FEATURE_TYPE": "<img src=x onerror=alert(1)>Institutional Control Boundary",
            "SITE_FEATURE_DESCRIPTION": "<script>steal()</script>[click](https://evil.example)",
            "FEATURE_INFO_URL": "https://evil.example/covenant",
            "FEATURE_INFO_URL_DESC": "covenant",
        }
    }
    ArcGISService.query_features = staticmethod(lambda *a, **k: ArcGISFeatureQueryResult([feature], [], False))
    text = api.format_institutional_controls(api.get_epa_superfund_institutional_controls("NJD063157150"))
    assert "<script>" not in text and "<img" not in text
    assert "https://evil.example" not in text and "](https://evil" not in text and "https\\://evil.example" in text


def test_upstream_error_detail_is_not_echoed(modules, monkeypatch):
    _, api, adapters = modules

    def explode(*_a, **_k):
        raise RuntimeError("Traceback: /srv/secret/path token=abc123")

    ArcGISService.query_features = staticmethod(explode)
    monkeypatch.setattr(ArcGISService, "query_object_ids", explode)
    monkeypatch.setattr(adapters, "get_json_rows", explode)
    texts = [
        api.format_institutional_controls(api.get_epa_superfund_institutional_controls("NJD063157150")),
        api.format_contaminants(api.get_epa_superfund_contaminants("NJD063157150")),
    ]
    for text in texts:
        assert "secret" not in text and "abc123" not in text and "Traceback" not in text
        assert "not a no-hit finding" in text


def test_no_hardcoded_secrets(modules):
    secret = re.compile(r"(api[_-]?key|token|password|secret)\s*=\s*['\"][^'\"]{8,}", re.IGNORECASE)
    for path in SERVER_DIR.rglob("*.py"):
        assert not secret.search(path.read_text(encoding="utf-8")), path


def test_every_tool_requests_only_configured_api_hosts(modules, monkeypatch):
    """EPA's site-profile host and search pages are robots-disallowed; no tool may request them."""
    _, api, _ = modules
    requested = []

    class Response:
        status_code = 200

        def __init__(self, url):
            self.url = url

        def raise_for_status(self):
            return None

        def json(self):
            if "efservice" in self.url:
                return [{"site_id": "0200397", "epa_id": "NJD063157150", "name": "BOG CREEK FARM"}]
            if "GeometryServer" in self.url:
                return {"geometries": [{"rings": [[[-74.2, 40.1], [-74.1, 40.1], [-74.1, 40.2], [-74.2, 40.1]]]}]}
            if "federalregister" in self.url:
                return {"count": 0, "results": []}
            return {"features": [], "objectIds": []}

    identified = []

    def record(method):
        def call(url, *args, **kwargs):
            requested.append(url)
            assert kwargs.get("allow_redirects") is False
            identified.append((kwargs.get("headers") or {}).get("User-Agent", ""))
            return Response(url)

        return call

    monkeypatch.setattr(requests, "get", record("get"))
    monkeypatch.setattr(requests, "post", record("post"))
    epa_id = "NJD063157150"
    api.search_epa_superfund_sites(query="bog", inventory_scope="sems_candidates")
    api.get_epa_superfund_sites_in_roi(40.15, -74.16, 5, "sems_candidates")
    api.get_epa_superfund_site(epa_id=epa_id)
    for tool in (
        api.get_epa_superfund_operable_units,
        api.get_epa_superfund_institutional_controls,
        api.get_epa_superfund_documents,
        api.get_epa_superfund_cleanup_actions,
        api.get_epa_superfund_contaminants,
        api.get_epa_superfund_public_notices,
    ):
        tool(epa_id)
    hosts = {url.split("/")[2] for url in requested}
    assert hosts == {"utility.arcgisonline.com", "services.arcgis.com", "data.epa.gov", "www.federalregister.gov"}
    assert identified and all(agent.startswith("nepa-mcp-epa-superfund/") for agent in identified)


@pytest.mark.parametrize("source", ["dmap", "federal_register", "layer", "features", "buffer"])
def test_redirect_to_disallowed_epa_host_is_not_requested(modules, monkeypatch, source):
    _, api, adapters = modules
    requested = []

    class Redirect:
        status_code = 302
        headers = {"Location": "https://cumulis.epa.gov/supercpad/"}

        def raise_for_status(self):
            pass

        def json(self):
            pytest.fail("A redirect must be rejected before decoding its body")

    def request(url, **kwargs):
        assert kwargs["allow_redirects"] is False
        requested.append(url)
        return Redirect()

    monkeypatch.setattr(requests, "get", request)
    monkeypatch.setattr(requests, "post", request)
    if source == "dmap":
        _, report = adapters.dmap_sites(["epa_id", "equals", "NJD063157150"], api.Budget())
    elif source == "federal_register":
        _, report = adapters.federal_register_documents("Bog Creek Farm", api.Budget())
    elif source == "layer":
        _, report = adapters.layer_records(api.NPL_POINTS, where="1=1", budget=api.Budget(), max_features=10)
    elif source == "features":
        monkeypatch.setattr(ArcGISService, "query_object_ids", lambda *_a, **_k: [1])
        _, report = adapters.layer_records(api.NPL_POINTS, where="1=1", budget=api.Budget(), max_features=10)
    else:
        report = api.get_epa_superfund_sites_in_roi(40, -74)["reports"][0]
    assert report.status == "failed" and len(requested) == 1
    assert not any("cumulis.epa.gov" in url for url in requested)
