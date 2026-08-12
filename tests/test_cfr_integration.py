"""
Integration tests for the CFR MCP server.

These load ``cfr/server.py`` through a real ``fastmcp.Client`` and exercise the
full tool -> api -> parser -> JSON path, with only the HTTP layer (``requests``)
mocked. The CFR server queries the eCFR and Federal Register REST APIs (it is
NOT lat/lon/buffer based), so the mock routes by request URL and returns
canned eCFR / FR payloads. This mirrors the loading approach in
``test_usace_integration.py`` and ``test_mcp_contracts.py``.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from pathlib import Path

import pytest
from fastmcp import Client

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "cfr"

_TOOL_NAMES = {
    "cfr_resolve_citation",
    "cfr_browse_structure",
    "cfr_history",
    "cfr_compare_versions",
    "cfr_rulemaking",
    "cfr_resolve_fr_citation",
    "cfr_resolve_executive_order",
}

SAMPLE_SECTION_HTML = """
<h4 data-hierarchy-metadata='{"title":"43","part":"46"}'>&sect; 46.205 Actions categorically excluded from further NEPA review.</h4>
<p class="indent-0">Categorical Exclusion means a category of actions that a bureau has determined normally do not significantly affect the quality of the human environment.</p>
<div id="p-46.205(c)">
  <p class="indent-1" data-title="46.205(c)">DOI has provided for extraordinary circumstances in which a normally excluded action may have a significant environmental effect and require additional analysis.</p>
  <div id="p-46.205(c)(1)">
    <p class="indent-2" data-title="46.205(c)(1)">Any action that is normally categorically excluded must be evaluated to determine whether it meets any of the extraordinary circumstances in &sect; 46.215.</p>
  </div>
</div>
<p class="citation">[<a class="fr-reference" href="https://www.federalregister.gov/citation/91-FR-8758" data-reference="91 FR 8758">91 FR 8758</a>, Feb. 24, 2026]</p>
"""


class _FakeResponse:
    def __init__(self, status_code=200, json_data=None, text=None):
        self.status_code = status_code
        self._json = {} if json_data is None else json_data
        self.text = text if text is not None else json.dumps(self._json)

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests as _rq

            err = _rq.exceptions.HTTPError(f"HTTP {self.status_code}")
            err.response = self
            raise err


def _router(url, params=None, timeout=None, **_kwargs):
    """Route a mocked eCFR / Federal Register HTTP GET by URL."""
    params = params or {}
    if "titles.json" in url:
        return _FakeResponse(
            json_data={"titles": [{"number": 43, "up_to_date_as_of": "2026-08-07", "name": "Public Lands: Interior"}]}
        )
    if "/renderer/" in url or "content/enhanced" in url:
        return _FakeResponse(text=SAMPLE_SECTION_HTML)
    if "/structure/" in url:
        return _FakeResponse(
            json_data={
                "type": "title",
                "identifier": "43",
                "label": "Title 43",
                "children": [
                    {
                        "type": "chapter",
                        "identifier": "I",
                        "label": "Chapter I",
                        "children": [{"type": "part", "identifier": "Part 46", "label": "Part 46", "children": []}],
                    }
                ],
            }
        )
    if "/versions/" in url:
        return _FakeResponse(
            json_data={
                "content_versions": [
                    {"date": "2025-07-03", "substantive": True, "identifier": "46.215", "part": 46, "title": 43},
                    {"date": "2026-02-24", "substantive": True, "identifier": "46.215", "part": 46, "title": 43},
                ]
            }
        )
    if "/ancestry/" in url:
        return _FakeResponse(
            json_data={
                "ancestors": [
                    {"type": "title", "identifier": "43", "label": "Title 43"},
                    {"type": "part", "identifier": "46", "label": "Part 46"},
                ]
            }
        )
    if "documents.json" in url:
        return _FakeResponse(
            json_data={
                "results": [
                    {
                        "document_number": "2025-12433",
                        "title": "National Environmental Policy Act Implementing Regulations",
                        "type": "Rule",
                        "abstract": "Partially rescinds and updates DOI's NEPA implementing regulations.",
                        "publication_date": "2025-07-03",
                        "effective_on": "2025-07-03",
                        "citation": "90 FR 29498",
                        "start_page": 29498,
                        "end_page": 29507,
                        "cfr_references": [{"title": 43, "part": 46}],
                        "executive_order_number": None,
                    }
                ]
            }
        )
    if "/documents/" in url:  # single FR document
        return _FakeResponse(
            json_data={
                "document_number": "2025-12433",
                "title": "National Environmental Policy Act Implementing Regulations",
                "type": "Rule",
                "abstract": "Partially rescinds and updates DOI's NEPA implementing regulations.",
                "publication_date": "2025-07-03",
                "citation": "90 FR 29498",
                "start_page": 29498,
                "end_page": 29507,
            }
        )
    return _FakeResponse(json_data={})


def _load_server(monkeypatch=None):
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src.") or module_name.startswith("_cfr_int_"):
            sys.modules.pop(module_name, None)
    sys.path[:] = [entry for entry in sys.path if entry != str(SERVER_DIR)]
    sys.path.insert(0, str(SERVER_DIR))
    spec = importlib.util.spec_from_file_location("_cfr_int_server", SERVER_DIR / "server.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["_cfr_int_server"] = module
    spec.loader.exec_module(module)
    return module


def _install_mock_http():
    """Patch the shared ``requests`` module used by cfr_api and the server."""
    import requests

    requests.get = _router  # type: ignore[assignment]
    # Neutralize caching + backoff sleeps in the loaded api module.
    api = sys.modules.get("src.apis.cfr_api")
    if api is not None:
        api._get_cached_response = lambda *_a, **_k: None
        api._cache_response = lambda *_a, **_k: None
        api.time.sleep = lambda *_a, **_k: None


async def _call(module, tool_name, args):
    async with Client(module.mcp) as client:
        return await client.call_tool(tool_name, args)


def _text(result) -> str:
    parts = []
    for block in result.content:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts)


def _json_payload(result) -> dict:
    return json.loads(_text(result))


@pytest.fixture(autouse=True)
def _restore_requests():
    import requests

    original = requests.get
    yield
    requests.get = original


class TestToolRegistration:
    def test_all_seven_tools_registered(self):
        module = _load_server()

        async def _names():
            async with Client(module.mcp) as client:
                return {t.name for t in await client.list_tools()}

        assert _TOOL_NAMES.issubset(asyncio.run(_names()))


class TestResolveCitationTool:
    def test_returns_addressed_node(self):
        module = _load_server()
        _install_mock_http()
        result = asyncio.run(
            _call(module, "cfr_resolve_citation", {"citation": "43 CFR 46.205(c)(1)", "as_of": "2026-08-07"})
        )
        payload = _json_payload(result)
        assert payload["citation"]["display"] == "43 CFR 46.205(c)(1)"
        assert payload["addressed_node"]["citation"] == "46.205(c)(1)"
        assert payload["ancestry"], "ancestry should be populated from mocked API"

    def test_bad_citation_returns_error_envelope(self):
        module = _load_server()
        _install_mock_http()
        result = asyncio.run(_call(module, "cfr_resolve_citation", {"citation": "not a citation"}))
        payload = _json_payload(result)
        assert payload["error"] == "CFRCitationError"

    def test_part_only_citation_rejected_gracefully(self):
        module = _load_server()
        _install_mock_http()
        result = asyncio.run(_call(module, "cfr_resolve_citation", {"citation": "43 CFR Part 46"}))
        payload = _json_payload(result)
        assert payload["error"] == "CFRCitationError"
        assert "section-level" in payload["message"]


class TestBrowseStructureTool:
    def test_titles_mode(self):
        module = _load_server()
        _install_mock_http()
        result = asyncio.run(_call(module, "cfr_browse_structure", {}))
        payload = _json_payload(result)
        assert payload["mode"] == "titles"
        assert payload["count"] >= 1

    def test_title_tree_mode(self):
        module = _load_server()
        _install_mock_http()
        result = asyncio.run(_call(module, "cfr_browse_structure", {"title": 43, "as_of": "2026-08-07"}))
        payload = _json_payload(result)
        assert payload["mode"] == "title_tree"
        assert payload["root_node"]["identifier"] == "43"

    def test_part_subtree_mode(self):
        module = _load_server()
        _install_mock_http()
        result = asyncio.run(_call(module, "cfr_browse_structure", {"title": 43, "part": 46, "as_of": "2026-08-07"}))
        payload = _json_payload(result)
        assert payload["mode"] == "part_subtree"
        assert payload["root_node"]["identifier"] == "Part 46"


class TestHistoryTool:
    def test_returns_events(self):
        module = _load_server()
        _install_mock_http()
        result = asyncio.run(
            _call(
                module,
                "cfr_history",
                {"citation": "43 CFR 46.215", "start_date": "2025-01-01", "end_date": "2026-12-31"},
            )
        )
        payload = _json_payload(result)
        assert payload["event_count"] == 2
        assert payload["substantive_count"] == 2

    def test_substantive_only_preserves_current_substantive_events(self):
        module = _load_server()
        _install_mock_http()
        result = asyncio.run(
            _call(
                module,
                "cfr_history",
                {
                    "citation": "43 CFR 46.215",
                    "start_date": "2025-01-01",
                    "end_date": "2026-12-31",
                    "substantive_only": True,
                },
            )
        )
        payload = _json_payload(result)
        assert payload["event_count"] == 2


class TestRulemakingTool:
    def test_returns_documents(self):
        module = _load_server()
        _install_mock_http()
        result = asyncio.run(
            _call(
                module,
                "cfr_rulemaking",
                {"cfr_title": 43, "cfr_part": 46, "start_date": "2025-01-01", "end_date": "2025-12-31"},
            )
        )
        payload = _json_payload(result)
        assert payload["document_count"] == 1
        assert payload["documents"][0]["document_number"] == "2025-12433"


class TestResolveFRCitationTool:
    def test_bad_fr_citation_error_envelope(self):
        module = _load_server()
        _install_mock_http()
        result = asyncio.run(_call(module, "cfr_resolve_fr_citation", {"citation": "garbage"}))
        payload = _json_payload(result)
        assert payload["error"] == "CitationError"


class TestExecutiveOrderTool:
    def test_invalid_eo_number_error_envelope(self):
        module = _load_server()
        _install_mock_http()
        result = asyncio.run(_call(module, "cfr_resolve_executive_order", {"eo_number": -5}))
        payload = _json_payload(result)
        assert payload["error"] == "CitationError"
