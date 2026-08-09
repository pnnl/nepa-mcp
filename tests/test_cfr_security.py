"""
Security tests for the CFR server.

The CFR server is not lat/lon based, so instead of coordinate/buffer bounds we
test its input handling: malformed CFR citations, malformed Federal Register
citations, invalid Executive Order numbers, and invalid dates. We verify these
are surfaced as structured JSON error envelopes (not tracebacks), that error
messages do not leak internal filesystem paths or stack traces, and that the
source has no hardcoded secrets and only public API endpoints.

Validation entry points read from source:
  * parse_cfr_citation / parse_fr_citation raise CFRCitationError.
  * server tools wrap those and return _error_response(...) JSON envelopes.
  * cfr_resolve_executive_order validates eo_number type/sign inline.
  * cfr_rulemaking validates dates via datetime.strptime.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "cfr"


def _load_server():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src.") or module_name.startswith("_cfr_sec_"):
            sys.modules.pop(module_name, None)
    sys.path[:] = [entry for entry in sys.path if entry != str(SERVER_DIR)]
    sys.path.insert(0, str(SERVER_DIR))
    spec = importlib.util.spec_from_file_location("_cfr_sec_server", SERVER_DIR / "server.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["_cfr_sec_server"] = module
    spec.loader.exec_module(module)
    return module


def _load_api():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src.") or module_name.startswith("_cfr_secapi_"):
            sys.modules.pop(module_name, None)
    sys.path.insert(0, str(SERVER_DIR))
    try:
        spec = importlib.util.spec_from_file_location("_cfr_secapi_api", SERVER_DIR / "src" / "apis" / "cfr_api.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules["_cfr_secapi_api"] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(SERVER_DIR))


# ---------------------------------------------------------------------------
# Malformed citation handling -> structured error envelopes
# ---------------------------------------------------------------------------


class TestMalformedCitationHandling:
    @pytest.mark.parametrize(
        "bad",
        [
            "",
            "   ",
            "definitely not a citation",
            "<script>alert(1)</script>",
            "40 CFR",  # no part
            "'; DROP TABLE regs; --",
        ],
    )
    def test_resolve_citation_returns_error_json(self, bad):
        module = _load_server()
        raw = module.cfr_resolve_citation(bad)
        payload = json.loads(raw)
        # Either a citation parse error, or (for the no-section forms) the
        # section-level guard — both are structured, neither is a traceback.
        assert "error" in payload
        assert payload["error"] in {"CFRCitationError"}

    @pytest.mark.parametrize("bad", ["", "no fr here", "FR 3142", "abc FR def"])
    def test_resolve_fr_citation_returns_error_json(self, bad):
        module = _load_server()
        raw = module.cfr_resolve_fr_citation(bad)
        payload = json.loads(raw)
        assert payload["error"] == "CitationError"

    def test_history_bad_citation_error_json(self):
        module = _load_server()
        raw = module.cfr_history("garbage")
        payload = json.loads(raw)
        assert payload["error"] == "CFRCitationError"

    def test_compare_versions_bad_citation_error_json(self):
        module = _load_server()
        raw = module.cfr_compare_versions("garbage", "2023-01-01", "2023-02-01")
        payload = json.loads(raw)
        assert payload["error"] == "CFRCitationError"


# ---------------------------------------------------------------------------
# Invalid dates and EO numbers
# ---------------------------------------------------------------------------


class TestInvalidParameters:
    def test_rulemaking_invalid_date_error_json(self):
        module = _load_server()
        raw = module.cfr_rulemaking(cfr_title=40, start_date="not-a-date", end_date="2023-12-31")
        payload = json.loads(raw)
        assert payload["error"] == "ValueError"
        assert "Invalid date" in payload["message"]

    @pytest.mark.parametrize("bad_eo", [-1, 0, "14008", 3.5, True])
    def test_executive_order_invalid_number(self, bad_eo):
        module = _load_server()
        raw = module.cfr_resolve_executive_order(bad_eo)
        payload = json.loads(raw)
        assert payload["error"] == "CitationError"


# ---------------------------------------------------------------------------
# Error message safety: no internal paths / tracebacks leaked
# ---------------------------------------------------------------------------


class TestErrorMessageSafety:
    def test_citation_error_has_no_internal_paths(self):
        module = _load_server()
        raw = module.cfr_resolve_citation("totally bogus citation")
        payload = json.loads(raw)
        msg = payload.get("message", "")
        assert "/Users/" not in msg
        assert "Traceback" not in msg
        # The offending value is echoed back, which is useful and acceptable.
        assert "citation" in msg.lower() or "totally bogus" in msg

    def test_error_response_is_valid_json_shape(self):
        module = _load_server()
        raw = module._error_response("SomeError", "a message")
        payload = json.loads(raw)
        assert set(payload.keys()) == {"error", "message"}


# ---------------------------------------------------------------------------
# No hardcoded secrets; only public endpoints
# ---------------------------------------------------------------------------


class TestNoHardcodedSecrets:
    def test_no_secret_patterns_in_source(self):
        for path in [
            SERVER_DIR / "server.py",
            SERVER_DIR / "src" / "apis" / "cfr_api.py",
            SERVER_DIR / "src" / "apis" / "cfr_constants.py",
        ]:
            content = path.read_text(encoding="utf-8")
            for pattern in ("API_KEY", "SECRET", "PASSWORD", "api_key=", "Authorization:"):
                assert pattern not in content, f"{pattern} found in {path.name}"

    def test_endpoints_are_public_gov(self):
        content = (SERVER_DIR / "src" / "apis" / "cfr_constants.py").read_text(encoding="utf-8")
        assert "ecfr.gov" in content
        assert "federalregister.gov" in content
        assert "api_key" not in content.lower()


# ---------------------------------------------------------------------------
# Parser robustness against hostile HTML input
# ---------------------------------------------------------------------------


class TestParserHostileInput:
    def test_script_injection_in_html_does_not_execute_or_crash(self):
        api = _load_api()
        malicious = '<h4>&sect; 1.1 X</h4><script id="x">os.system("rm -rf /")</script><p class="indent-0">ok</p>'
        parsed = api._parse_section_html(malicious)
        # Parser must not crash; script content is just data, never evaluated.
        assert isinstance(parsed, dict)
        assert "ok" in parsed.get("preamble", "")

    def test_deeply_nested_citation_does_not_crash_parser(self):
        api = _load_api()
        cit = api.parse_cfr_citation("40 CFR 1.1" + "(a)" * 50)
        assert len(cit.paragraph_path) == 50
