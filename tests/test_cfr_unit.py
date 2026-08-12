"""
Unit tests for the CFR API layer (``cfr/src/apis/cfr_api.py``).

Unlike the geospatial servers, the CFR server is NOT lat/lon/buffer based: it
queries the eCFR and Federal Register HTTP APIs for regulatory text, structure,
version history and citations. These tests exercise the pure parsing / formatting
logic directly, plus a few HTTP-touching helpers with ``requests`` mocked, so no
network calls are made. They follow the same dynamic per-server import pattern
used by ``test_usace_unit.py``.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_cfr_api():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src."):
            sys.modules.pop(module_name, None)
    server_dir = ROOT / "cfr"
    sys.path.insert(0, str(server_dir))
    try:
        spec = importlib.util.spec_from_file_location(
            "_cfr_unit_api",
            server_dir / "src" / "apis" / "cfr_api.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules["_cfr_unit_api"] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(server_dir))


class _FakeResponse:
    """Minimal stand-in for a ``requests.Response``."""

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


def _disable_cache(api, monkeypatch):
    monkeypatch.setattr(api, "_get_cached_response", lambda *_a, **_k: None)
    monkeypatch.setattr(api, "_cache_response", lambda *_a, **_k: None)
    monkeypatch.setattr(api.time, "sleep", lambda *_a, **_k: None)


# A representative eCFR renderer payload using a real current nested paragraph
# and the current DOI Part 46 Federal Register source citation.
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


# ---------------------------------------------------------------------------
# Citation parsing
# ---------------------------------------------------------------------------


class TestParseCitation:
    def test_simple_section(self):
        api = _load_cfr_api()
        cit = api.parse_cfr_citation("43 CFR 46.215")
        assert cit.title == 43
        assert cit.part == 46
        assert cit.section == "215"
        assert cit.paragraph_path == []

    def test_section_symbol_is_stripped(self):
        api = _load_cfr_api()
        cit = api.parse_cfr_citation("43 CFR § 46.215(a)")
        assert cit.part == 46
        assert cit.section == "215"
        assert cit.paragraph_path == ["a"]

    def test_deep_paragraph_path_preserves_case(self):
        api = _load_cfr_api()
        cit = api.parse_cfr_citation("40 C.F.R. 261.4(a)(20)(ii)(B)(1)")
        assert cit.title == 40
        assert cit.part == 261
        assert cit.section == "4"
        # Roman-numeral and upper-case levels must survive distinct.
        assert cit.paragraph_path == ["a", "20", "ii", "B", "1"]

    def test_part_only_citation(self):
        api = _load_cfr_api()
        cit = api.parse_cfr_citation("43 CFR Part 46")
        assert cit.title == 43
        assert cit.part == 46
        assert cit.section is None

    def test_title_only_citation(self):
        api = _load_cfr_api()
        cit = api.parse_cfr_citation("title 50")
        assert cit.title == 50
        assert cit.part is None
        assert cit.section is None

    def test_verbose_form(self):
        api = _load_cfr_api()
        cit = api.parse_cfr_citation("Title 43, Part 46, Section 215")
        assert cit.title == 43
        assert cit.part == 46
        assert cit.section == "215"

    def test_malformed_raises(self):
        api = _load_cfr_api()
        import pytest

        with pytest.raises(api.CFRCitationError):
            api.parse_cfr_citation("this is not a citation")


class TestCitationDisplay:
    def test_display_section_with_path(self):
        api = _load_cfr_api()
        cit = api.parse_cfr_citation("43 CFR 46.205(c)(1)")
        assert cit.to_display() == "43 CFR 46.205(c)(1)"

    def test_display_part_only(self):
        api = _load_cfr_api()
        cit = api.parse_cfr_citation("43 CFR Part 46")
        assert cit.to_display() == "43 CFR Part 46"

    def test_display_title_only(self):
        api = _load_cfr_api()
        cit = api.parse_cfr_citation("title 50")
        assert cit.to_display() == "Title 50 CFR"


# ---------------------------------------------------------------------------
# FR citation parsing
# ---------------------------------------------------------------------------


class TestParseFRCitation:
    def test_standard_form(self):
        api = _load_cfr_api()
        assert api.parse_fr_citation("90 FR 29498") == (90, 29498)

    def test_fed_reg_form(self):
        api = _load_cfr_api()
        assert api.parse_fr_citation("90 Fed. Reg. 29498") == (90, 29498)

    def test_empty_raises(self):
        api = _load_cfr_api()
        import pytest

        with pytest.raises(api.CFRCitationError):
            api.parse_fr_citation("")

    def test_garbage_raises(self):
        api = _load_cfr_api()
        import pytest

        with pytest.raises(api.CFRCitationError):
            api.parse_fr_citation("no volume or page here")


# ---------------------------------------------------------------------------
# Section HTML parsing
# ---------------------------------------------------------------------------


class TestParseSectionHTML:
    def test_builds_paragraph_tree(self):
        api = _load_cfr_api()
        parsed = api._parse_section_html(SAMPLE_SECTION_HTML)
        assert parsed is not None
        assert parsed["heading"].startswith("§")
        assert "46.205" in parsed["heading"]
        # One top-level paragraph with one nested child.
        paras = parsed["paragraphs"]
        assert len(paras) == 1
        assert paras[0]["citation"] == "46.205(c)"
        assert paras[0]["depth"] == 1
        assert paras[0]["children"][0]["citation"] == "46.205(c)(1)"

    def test_preamble_captured(self):
        api = _load_cfr_api()
        parsed = api._parse_section_html(SAMPLE_SECTION_HTML)
        assert "normally do not significantly affect" in parsed["preamble"]

    def test_fr_citation_link_captured(self):
        api = _load_cfr_api()
        parsed = api._parse_section_html(SAMPLE_SECTION_HTML)
        assert any(ref["text"] == "91 FR 8758" for ref in parsed.get("fr_citations", []))


# ---------------------------------------------------------------------------
# Structure traversal
# ---------------------------------------------------------------------------


class TestFindPartInStructure:
    def _structure(self):
        return {
            "type": "title",
            "identifier": "43",
            "children": [
                {
                    "type": "chapter",
                    "identifier": "I",
                    "children": [
                        {"type": "part", "identifier": "Part 10", "children": []},
                        {"type": "part", "identifier": "Part 46", "children": []},
                    ],
                }
            ],
        }

    def test_finds_nested_part(self):
        api = _load_cfr_api()
        node = api.find_part_in_structure(self._structure(), 46)
        assert node is not None
        assert node["identifier"] == "Part 46"

    def test_missing_part_returns_none(self):
        api = _load_cfr_api()
        assert api.find_part_in_structure(self._structure(), 9999) is None

    def test_empty_structure_returns_none(self):
        api = _load_cfr_api()
        assert api.find_part_in_structure({}, 46) is None


# ---------------------------------------------------------------------------
# FR correlation logic (pure)
# ---------------------------------------------------------------------------


class TestCorrelation:
    def test_exact_date_match(self):
        api = _load_cfr_api()
        events = [{"date": "2025-07-03", "title": 43, "part": 46, "type": "rule"}]
        docs = [
            {
                "document_number": "2025-12433",
                "publication_date": "2025-07-03",
                "effective_on": "2025-07-03",
                "type": "RULE",
                "citation": "90 FR 29498",
                "cfr_references": [{"title": 43, "part": 46}],
            }
        ]
        correlated = api.correlate_amendment_events_with_fr_documents(events, docs)
        assert len(correlated) == 1
        assert correlated[0]["match_confidence"] == "exact_date"
        assert correlated[0]["fr_document"]["document_number"] == "2025-12433"
        assert correlated[0]["delta_days"] == 0

    def test_no_match_out_of_tolerance(self):
        api = _load_cfr_api()
        events = [{"date": "2025-07-03", "title": 43, "part": 46}]
        docs = [{"document_number": "x", "publication_date": "2024-01-01", "type": "RULE"}]
        correlated = api.correlate_amendment_events_with_fr_documents(events, docs, tolerance_days=7)
        assert correlated[0]["fr_document"] is None
        assert correlated[0]["source_label"] == "[No FR Match]"

    def test_event_without_date_flagged(self):
        api = _load_cfr_api()
        correlated = api.correlate_amendment_events_with_fr_documents([{"title": 43}], [])
        assert correlated[0]["match_type"] == "invalid_date"


# ---------------------------------------------------------------------------
# HTTP-touching helpers (requests mocked)
# ---------------------------------------------------------------------------


class TestVersionsWithMockedHTTP:
    def test_substantive_only_filters(self, monkeypatch):
        api = _load_cfr_api()
        _disable_cache(api, monkeypatch)
        payload = {
            "content_versions": [
                {"date": "2023-01-01", "substantive": True, "identifier": "46.215"},
                {"date": "2023-02-01", "substantive": False, "identifier": "46.215"},
            ]
        }
        monkeypatch.setattr(api.requests, "get", lambda *_a, **_k: _FakeResponse(json_data=payload))
        cit = api.parse_cfr_citation("43 CFR 46.215")
        all_events = api.get_section_versions(cit, start_date="2023-01-01", end_date="2023-12-31")
        assert len(all_events) == 2
        subst = api.get_section_versions(cit, start_date="2023-01-01", end_date="2023-12-31", substantive_only=True)
        assert len(subst) == 1
        assert subst[0]["substantive"] is True

    def test_titles_extracts_payload(self, monkeypatch):
        api = _load_cfr_api()
        _disable_cache(api, monkeypatch)
        payload = {"titles": [{"number": 40, "up_to_date_as_of": "2026-01-01"}]}
        monkeypatch.setattr(api.requests, "get", lambda *_a, **_k: _FakeResponse(json_data=payload))
        titles = api.get_ecfr_titles()
        assert titles["titles"][0]["number"] == 40
