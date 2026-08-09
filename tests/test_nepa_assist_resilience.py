"""
Resilience tests for the NEPA Assist API layer.

Verify graceful behavior when the upstream EPA NEPAssist service errors, times
out, returns malformed HTML, or returns empty payloads. The ``requests`` HTTP
layer and the ArcGIS ROI helper are mocked to simulate each failure mode.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest
import requests as req_mod

ROOT = Path(__file__).resolve().parents[1]
SIMPLE_GEOMETRY = {
    "rings": [[[-107.0, 34.0], [-106.0, 34.0], [-106.0, 35.0], [-107.0, 35.0], [-107.0, 34.0]]],
    "spatialReference": {"wkid": 4326},
}


def _load_nepa_assist_api():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src."):
            sys.modules.pop(module_name, None)
    server_dir = ROOT / "nepa_assist"
    sys.path.insert(0, str(server_dir))
    try:
        spec = importlib.util.spec_from_file_location(
            "_nepa_assist_resilience_api", server_dir / "src" / "apis" / "nepa_assist_api.py"
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules["_nepa_assist_resilience_api"] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(server_dir))


def _patch_roi(api, monkeypatch):
    monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", staticmethod(lambda *_a, **_k: SIMPLE_GEOMETRY))


class _FakeResponse:
    def __init__(self, text: str, status_error: Exception | None = None):
        self.text = text
        self.url = "https://nepassisttool.epa.gov/nepassist/analysis.aspx"
        self._status_error = status_error

    def raise_for_status(self):
        if self._status_error is not None:
            raise self._status_error


def _install_get(api, monkeypatch, fn):
    fake_requests = types.SimpleNamespace(get=fn, exceptions=req_mod.exceptions)
    monkeypatch.setattr(api, "requests", fake_requests)


class TestUpstreamFailure:
    def test_timeout_bubbles_up(self, monkeypatch):
        api = _load_nepa_assist_api()
        _patch_roi(api, monkeypatch)

        def timeout(*_a, **_k):
            raise req_mod.exceptions.Timeout("timed out")

        _install_get(api, monkeypatch, timeout)
        with pytest.raises(req_mod.exceptions.Timeout):
            api.query_nepa_assist(34.5, -106.5, 25.0)

    def test_http_error_bubbles_up(self, monkeypatch):
        api = _load_nepa_assist_api()
        _patch_roi(api, monkeypatch)

        def error_response(*_a, **_k):
            return _FakeResponse("<html></html>", status_error=req_mod.exceptions.HTTPError("500 Server Error"))

        _install_get(api, monkeypatch, error_response)
        with pytest.raises(req_mod.exceptions.HTTPError):
            api.query_nepa_assist(34.5, -106.5, 25.0)

    def test_connection_error_bubbles_up(self, monkeypatch):
        api = _load_nepa_assist_api()
        _patch_roi(api, monkeypatch)

        def conn_error(*_a, **_k):
            raise req_mod.exceptions.ConnectionError("cannot connect")

        _install_get(api, monkeypatch, conn_error)
        with pytest.raises(req_mod.exceptions.ConnectionError):
            api.query_nepa_assist(34.5, -106.5, 25.0)


class TestMalformedResponses:
    def test_non_table_html_yields_zero_checks(self, monkeypatch):
        api = _load_nepa_assist_api()
        _patch_roi(api, monkeypatch)
        _install_get(api, monkeypatch, lambda *a, **k: _FakeResponse("<html><body>No data here</body></html>"))
        results = api.query_nepa_assist(34.5, -106.5, 25.0)
        assert results["summary"]["total_checks"] == 0
        assert results["summary"]["flagged_issues"] == []

    def test_empty_body_does_not_crash(self, monkeypatch):
        api = _load_nepa_assist_api()
        _patch_roi(api, monkeypatch)
        _install_get(api, monkeypatch, lambda *a, **k: _FakeResponse(""))
        results = api.query_nepa_assist(34.5, -106.5, 25.0)
        assert results["summary"]["total_checks"] == 0

    def test_row_without_answer_cell_is_skipped(self, monkeypatch):
        api = _load_nepa_assist_api()
        _patch_roi(api, monkeypatch)
        html = (
            "<html><body><table>"
            '<tr class="yes0"><td class="questionText"><a href="#">Only one cell?</a></td></tr>'
            "</table></body></html>"
        )
        _install_get(api, monkeypatch, lambda *a, **k: _FakeResponse(html))
        results = api.query_nepa_assist(34.5, -106.5, 25.0)
        # The single-cell row lacks an answer td and must be skipped without error.
        assert results["summary"]["total_checks"] == 0

    def test_unrecognized_answer_still_counts_as_check(self, monkeypatch):
        api = _load_nepa_assist_api()
        _patch_roi(api, monkeypatch)
        html = (
            "<html><body><table>"
            '<tr class="yes0"><td class="questionText"><a href="#">Stream nearby?</a></td>'
            '<td><a href="#">Maybe</a></td></tr>'
            "</table></body></html>"
        )
        _install_get(api, monkeypatch, lambda *a, **k: _FakeResponse(html))
        results = api.query_nepa_assist(34.5, -106.5, 25.0)
        # A non yes/no answer increments total_checks but not yes/no tallies.
        assert results["summary"]["total_checks"] == 1
        assert results["summary"]["yes_count"] == 0
        assert results["summary"]["no_count"] == 0


class TestRoiFailure:
    def test_missing_rings_raises_before_http(self, monkeypatch):
        api = _load_nepa_assist_api()
        monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", staticmethod(lambda *_a, **_k: {"rings": []}))

        def should_not_be_called(*_a, **_k):
            raise AssertionError("HTTP should not run when ROI geometry is invalid")

        _install_get(api, monkeypatch, should_not_be_called)
        with pytest.raises(ValueError):
            api.query_nepa_assist(34.5, -106.5, 25.0)
