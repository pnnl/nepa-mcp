"""
Performance / scaling tests for the CFR API layer.

These are hermetic (``requests`` mocked) and assert algorithmic behavior at
larger synthetic payloads: large version-history lists filter and count in
bounded time, large section HTML parses to a deep tree quickly, and citation
parsing of very deep paragraph paths stays linear. They do not hit the network,
so they are deterministic in CI.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_cfr_api():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src."):
            sys.modules.pop(module_name, None)
    server_dir = ROOT / "cfr"
    sys.path.insert(0, str(server_dir))
    try:
        spec = importlib.util.spec_from_file_location("_cfr_perf_api", server_dir / "src" / "apis" / "cfr_api.py")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules["_cfr_perf_api"] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(server_dir))


class _FakeResponse:
    def __init__(self, status_code=200, json_data=None, text=None):
        self.status_code = status_code
        self._json = {} if json_data is None else json_data
        self.text = text if text is not None else json.dumps(self._json)

    def json(self):
        return self._json

    def raise_for_status(self):
        return None


def _disable_cache(api, monkeypatch):
    monkeypatch.setattr(api, "_get_cached_response", lambda *_a, **_k: None)
    monkeypatch.setattr(api, "_cache_response", lambda *_a, **_k: None)
    monkeypatch.setattr(api.time, "sleep", lambda *_a, **_k: None)


class TestVersionHistoryScaling:
    def test_large_version_list_filters_quickly(self, monkeypatch):
        api = _load_cfr_api()
        _disable_cache(api, monkeypatch)
        events = [
            {"date": f"2020-01-{(i % 28) + 1:02d}", "substantive": bool(i % 2), "identifier": "1502.14"}
            for i in range(5000)
        ]
        monkeypatch.setattr(
            api.requests, "get", lambda *_a, **_k: _FakeResponse(json_data={"content_versions": events})
        )
        cit = api.parse_cfr_citation("40 CFR 1502.14")
        start = time.perf_counter()
        subst = api.get_section_versions(cit, start_date="2020-01-01", end_date="2020-12-31", substantive_only=True)
        elapsed = time.perf_counter() - start
        assert len(subst) == 2500
        assert elapsed < 1.0


class TestSectionHTMLParsingThroughput:
    def test_deep_nested_html_parses_quickly(self, monkeypatch):
        api = _load_cfr_api()
        # Build a section with 1000 sibling paragraphs.
        parts = ["<h4>&sect; 1502.14 Alternatives.</h4>"]
        for i in range(1000):
            parts.append(
                f'<div id="p-1502.14({i})"><p class="indent-1" data-title="1502.14({i})">Paragraph {i} text.</p></div>'
            )
        html = "\n".join(parts)
        start = time.perf_counter()
        parsed = api._parse_section_html(html)
        elapsed = time.perf_counter() - start
        assert len(parsed["paragraphs"]) == 1000
        assert elapsed < 2.0


class TestCitationParsingThroughput:
    def test_very_deep_paragraph_path_parses_fast(self):
        api = _load_cfr_api()
        deep = "40 CFR 1.1" + "(a)" * 200
        start = time.perf_counter()
        cit = api.parse_cfr_citation(deep)
        elapsed = time.perf_counter() - start
        assert len(cit.paragraph_path) == 200
        assert elapsed < 0.5

    def test_many_citations_parse_bounded(self):
        api = _load_cfr_api()
        start = time.perf_counter()
        for i in range(5000):
            api.parse_cfr_citation(f"40 CFR {1500 + (i % 100)}.{i % 30}")
        elapsed = time.perf_counter() - start
        assert elapsed < 2.0


class TestCorrelationScaling:
    def test_many_events_and_docs_correlate_bounded(self):
        api = _load_cfr_api()
        events = [{"date": f"2023-{(i % 12) + 1:02d}-01", "title": 40, "part": 1502} for i in range(200)]
        docs = [
            {
                "document_number": f"2023-{i:04d}",
                "publication_date": f"2023-{(i % 12) + 1:02d}-01",
                "type": "RULE",
                "cfr_references": [{"title": 40, "part": 1502}],
            }
            for i in range(200)
        ]
        start = time.perf_counter()
        correlated = api.correlate_amendment_events_with_fr_documents(events, docs)
        elapsed = time.perf_counter() - start
        assert len(correlated) == 200
        # 200x200 date correlation should still be well under a couple seconds.
        assert elapsed < 3.0
