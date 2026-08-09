"""
Integration tests for the NEPA Assist MCP server.

These load ``nepa_assist/server.py`` through a real ``fastmcp.Client`` and
exercise the full tool -> api -> formatter -> report path, with only the HTTP
(``requests``) and ArcGIS ROI layers mocked. This mirrors the loading approach
used by the USACE integration suite.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path

import pytest
from fastmcp import Client

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "nepa_assist"
SIMPLE_GEOMETRY = {
    "rings": [[[-107.0, 34.0], [-106.0, 34.0], [-106.0, 35.0], [-107.0, 35.0], [-107.0, 34.0]]],
    "spatialReference": {"wkid": 4326},
}

_TOOL_NAME = "analyze_nepa_assist_screening"


def _load_server():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src.") or module_name.startswith("_nepa_assist_int_"):
            sys.modules.pop(module_name, None)
    sys.path[:] = [entry for entry in sys.path if entry != str(SERVER_DIR)]
    sys.path.insert(0, str(SERVER_DIR))
    spec = importlib.util.spec_from_file_location("_nepa_assist_int_server", SERVER_DIR / "server.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["_nepa_assist_int_server"] = module
    spec.loader.exec_module(module)
    return module


def _row(css_class: str, question: str, answer: str) -> str:
    return (
        f'<tr class="{css_class}">'
        f'<td class="questionText"><a href="#">{question}</a></td>'
        f'<td><a href="#">{answer}</a></td>'
        f"</tr>"
    )


def _build_html(rows) -> str:
    return f"<html><body><table>{''.join(rows)}</table></body></html>"


_MIXED_ROWS = [
    _row("yes0", "Is the site in an ozone non-attainment area?", "Yes"),
    _row("yes1", "Is there a stream within the buffer?", "Yes"),
    _row("no0", "Is critical habitat present?", "No"),
    _row("yes0", "Is there a historic property nearby?", "Yes"),
]


class _FakeResponse:
    def __init__(self, text: str, url: str = "https://nepassisttool.epa.gov/nepassist/analysis.aspx?f=report"):
        self.text = text
        self.url = url

    def raise_for_status(self):
        return None


def _install_mock_http(module, html: str):
    """Patch the api module's ArcGIS ROI helper and requests.get."""
    api = sys.modules.get("src.apis.nepa_assist_api", module)

    from nepa_mcp_common.arcgis import ArcGISService

    ArcGISService.create_roi_buffer = staticmethod(lambda *_a, **_k: SIMPLE_GEOMETRY)

    def fake_get(url, params=None, timeout=None):
        return _FakeResponse(html)

    fake_requests = types.SimpleNamespace(get=fake_get, exceptions=api.requests.exceptions)
    api.requests = fake_requests


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


class TestToolRegistration:
    def test_screening_tool_registered(self):
        module = _load_server()

        async def _names():
            async with Client(module.mcp) as client:
                return {t.name for t in await client.list_tools()}

        assert _TOOL_NAME in asyncio.run(_names())


class TestScreeningTool:
    def test_returns_report_with_sections(self):
        module = _load_server()
        _install_mock_http(module, _build_html(_MIXED_ROWS))
        result = asyncio.run(
            _call(
                module, _TOOL_NAME, {"latitude": 34.5, "longitude": -106.5, "buffer_miles": 25, "project_title": "Demo"}
            )
        )
        text = _text(result)
        assert "EPA NEPA ASSIST ENVIRONMENTAL SCREENING REPORT" in text
        assert "EXECUTIVE SUMMARY" in text
        assert "AIR QUALITY" in text
        assert "NEPA COMPLIANCE GUIDANCE" in text
        assert "Demo" in text

    def test_flagged_issues_surface_guidance(self):
        module = _load_server()
        _install_mock_http(module, _build_html(_MIXED_ROWS))
        result = asyncio.run(_call(module, _TOOL_NAME, {"latitude": 34.5, "longitude": -106.5}))
        text = _text(result)
        assert "FLAGGED ENVIRONMENTAL CONCERNS" in text
        assert "AIR QUALITY COMPLIANCE:" in text
        assert "CULTURAL RESOURCES COMPLIANCE:" in text

    def test_clean_screening_reports_no_concerns(self):
        module = _load_server()
        _install_mock_http(module, _build_html([_row("no0", "Is there a stream within the buffer?", "No")]))
        result = asyncio.run(_call(module, _TOOL_NAME, {"latitude": 34.5, "longitude": -106.5}))
        text = _text(result)
        assert "No major environmental concerns flagged" in text
        assert "GENERAL NEPA COMPLIANCE:" in text

    def test_default_buffer_applied(self):
        module = _load_server()
        _install_mock_http(module, _build_html([_row("no0", "Any stream?", "No")]))
        result = asyncio.run(_call(module, _TOOL_NAME, {"latitude": 34.5, "longitude": -106.5}))
        assert "25.0 miles" in _text(result)


class TestInputValidationThroughTool:
    def test_out_of_range_latitude_is_rejected(self):
        module = _load_server()
        with pytest.raises(Exception):
            asyncio.run(_call(module, _TOOL_NAME, {"latitude": 999, "longitude": -106.5}))

    def test_zero_buffer_is_rejected(self):
        module = _load_server()
        with pytest.raises(Exception):
            asyncio.run(_call(module, _TOOL_NAME, {"latitude": 34.5, "longitude": -106.5, "buffer_miles": 0}))

    def test_buffer_above_max_is_rejected(self):
        module = _load_server()
        with pytest.raises(Exception):
            asyncio.run(_call(module, _TOOL_NAME, {"latitude": 34.5, "longitude": -106.5, "buffer_miles": 250}))
