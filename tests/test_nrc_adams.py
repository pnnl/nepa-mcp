"""Offline APS guide-contract and security tests; fixtures do not certify an authenticated live contract."""

import asyncio
import copy
import io
import json
import os

import pytest
from fastmcp import Client
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
from nepa_mcp import config, cli
from nepa_mcp.loader import load_server_module


@pytest.fixture
def modules(monkeypatch):
    server = load_server_module("nrc_adams")
    a, f, r = server.adams_api, server.files_api, server.references_api
    monkeypatch.delenv("NRC_ADAMS_API_KEY", raising=False)
    monkeypatch.setattr(a.requests, "request", lambda *_a, **_k: pytest.fail("Unexpected API network"))
    monkeypatch.setattr(f.requests, "get", lambda *_a, **_k: pytest.fail("Unexpected original network"))
    f._STORE.clear()
    a._WINDOWS.clear()
    return server, a, f, r


def doc(acc="ML25059A029", **updates):
    return {
        "AccessionNumber": acc,
        "DocumentTitle": "Example public record",
        "DocketNumber": ["05000373", "05000374"],
        "DocumentType": ["Letter"],
        "IsPackage": "No",
        "IsLegacy": "No",
        "Url": "https://www.nrc.gov/docs/example.pdf",
        "content": "Example indexed text",
        "Availability": "Publicly Available",
        **updates,
    }


class Response:
    def __init__(self, payload=None, status=200, headers=None, data=None):
        self.status_code = status
        self.headers = headers or {"Content-Type": "application/json"}
        self.data = data if data is not None else json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def iter_content(self, *_):
        yield self.data


def api_record(monkeypatch, a, document):
    monkeypatch.setenv("NRC_ADAMS_API_KEY", "test-secret-never-echo")
    monkeypatch.setattr(a.requests, "request", lambda *_a, **_k: Response({"document": copy.deepcopy(document)}))


@pytest.mark.parametrize(
    "method,args",
    [
        ("get_nrc_adams_document", ("ML25059A029",)),
        ("get_nrc_adams_document_text", ("ML25059A029",)),
        ("get_nrc_adams_package", ("ML25059A029",)),
        ("search_nrc_adams_documents", ("reactor",)),
    ],
)
def test_missing_key_does_not_disable_import_or_discovery(modules, method, args):
    _, a, _, _ = modules
    r = getattr(a, method)(*args)
    assert r["status"] == "missing_configuration" and r["adapter"] == "official_api"
    assert "private" in r["error"] and not r["authenticated_contract_verified"]


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"query_text": "x", "max_results": 0},
        {"query_text": "x", "max_results": True},
        {"query_text": "x", "result_offset": -1},
        {"query_text": "x", "docket_number": "050-123"},
        {"query_text": "x", "date_from": "2026-02-30"},
        {"query_text": "x", "date_basis": "retrieved_at"},
        {"query_text": "x", "sort_by": "content"},
        {"query_text": "x", "sort_direction": "random"},
        {"query_text": "x", "library": "private"},
        {"query_text": "x", "date_from": "2026-10-01", "date_to": "2026-01-01"},
    ],
)
def test_search_validates_before_requests(modules, kwargs):
    with pytest.raises(ValueError):
        modules[1].search_nrc_adams_documents(**kwargs)


def test_filters_libraries_dates_and_no_invented_page_size(modules, monkeypatch):
    _, a, _, _ = modules
    calls = []
    monkeypatch.setenv("NRC_ADAMS_API_KEY", "secret")

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return Response({"count": 201, "results": [{"document": doc()}]})

    monkeypatch.setattr(a.requests, "request", request)
    r = a.search_nrc_adams_documents(
        "O'Brien AND reactor",
        docket_number="05000373",
        document_type="O'Brien Report",
        date_from="2026-01-01",
        date_to="2026-10-23",
        date_basis="date_added",
        library="legacy",
        max_results=1,
        result_offset=100,
    )
    body = calls[0][2]["json"]
    assert body["skip"] == 100 and "pageSize" not in body and "page" not in body
    assert body["mainLibFilter"] is False and body["legacyLibFilter"] is True and not body["anyFilters"]
    assert body["filters"][0] == {"field": "DocketNumber", "operator": "equals", "value": "05000373"}
    assert body["filters"][1]["value"] == "O'Brien Report"
    assert body["filters"][2]["value"] == "(DateAddedTimestamp ge '2026-01-01')"
    assert r["pagination"]["next_result_offset"] == 101
    assert r["records"][0]["dockets"] == ["05000373", "05000374"]
    assert "text" not in r["records"][0] and "content" not in r["records"][0]
    assert calls[0][2]["allow_redirects"] is False


@pytest.mark.parametrize(
    "status,state",
    [
        (401, "authorization_error"),
        (403, "authorization_error"),
        (429, "rate_limited"),
        (404, "not_found"),
        (500, "upstream_unavailable"),
        (302, "redirect_rejected"),
    ],
)
def test_api_errors_and_no_secret_echo(modules, monkeypatch, status, state):
    _, a, _, _ = modules
    monkeypatch.setenv("NRC_ADAMS_API_KEY", "secret-do-not-echo")
    monkeypatch.setattr(
        a.requests,
        "request",
        lambda *_a, **_k: Response({"error": "secret-do-not-echo"}, status, {"Retry-After": "120"}),
    )
    r = a.get_nrc_adams_document("ML25059A029")
    assert r["status"] == state and "secret-do-not-echo" not in json.dumps(r)


def test_bounded_api_json_and_schema_failures(modules, monkeypatch):
    _, a, _, _ = modules
    monkeypatch.setenv("NRC_ADAMS_API_KEY", "secret")
    for payload, state in [(b"not JSON", "schema_error"), (b"[]", "schema_error"), (b"{}", "schema_error")]:
        monkeypatch.setattr(a.requests, "request", lambda *_a, **_k: Response(data=payload))
        assert a.get_nrc_adams_document("ML25059A029")["status"] == state
    monkeypatch.setattr(a, "API_CAP", 1)
    assert a.get_nrc_adams_document("ML25059A029")["status"] == "response_too_large"


def test_exact_accession_and_legacy_leading_zeros(modules, monkeypatch):
    _, a, _, _ = modules
    api_record(monkeypatch, a, doc("00001234", IsLegacy="Yes", Url=None, content=None))
    r = a.get_nrc_adams_document("00001234")
    assert r["document"]["accession_number"] == "00001234" and r["document"]["record_kind"] == "legacy"
    assert a.get_nrc_adams_document("00001235")["status"] == "schema_error"
    for bad in ["https://evil.test", "../../key", "ML\n123", ""]:
        with pytest.raises(ValueError):
            a.get_nrc_adams_document(bad)


@pytest.mark.parametrize(
    "content,expected", [(None, "text_unavailable"), ("", "empty_text"), ({"text": "x"}, "unsupported_encoding")]
)
def test_text_states(modules, monkeypatch, content, expected):
    _, a, _, _ = modules
    api_record(monkeypatch, a, doc(content=content))
    assert a.get_nrc_adams_document_text("ML25059A029")["status"] == expected


def test_text_chunks_and_changed_fingerprints(modules, monkeypatch):
    _, a, _, _ = modules
    api_record(monkeypatch, a, doc(content="αβγδε"))
    r = a.get_nrc_adams_document_text("ML25059A029", 1, 2)
    assert r["text"] == "βγ" and r["next_character_offset"] == 3 and r["source_completeness"] == "unknown"
    api_record(monkeypatch, a, doc(content="changed"))
    assert a.get_nrc_adams_document_text("ML25059A029")["content_fingerprint"] != r["content_fingerprint"]


def test_explicit_package_direction_cycles_dedup_and_cap(modules, monkeypatch):
    _, a, _, _ = modules
    monkeypatch.setenv("NRC_ADAMS_API_KEY", "secret")
    package = doc(
        IsPackage="Yes",
        DocumentsFiledInPackage=["ML25059A030", "ML25059A030", "ML25059A029"],
        PackagesFiledIn=["ML24017A120"],
    )

    def request(method, url, **kwargs):
        return Response({"document": package if url.endswith("ML25059A029") else doc(url.rsplit("/", 1)[1])})

    monkeypatch.setattr(a.requests, "request", request)
    r = a.get_nrc_adams_package("ML25059A029")
    assert r["unique_member_count"] == 2 and r["source_member_count"] == 3
    assert r["members"][1]["state"] == "cycle_to_self"
    assert all(x.get("document", {}).get("accession_number") != "ML24017A120" for x in r["members"])
    package.pop("DocumentsFiledInPackage")
    assert a.get_nrc_adams_package("ML25059A029")["status"] == "membership_unavailable"


def pdf_bytes(text="Reference ADAMS ML24017A120. Own accession ML25059A029."):
    w = PdfWriter()
    p = w.add_blank_page(width=300, height=200)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    p[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): w._add_object(font)})}
    )
    stream = DecodedStreamObject()
    stream.set_data(f"BT /F1 10 Tf 10 100 Td ({text}) Tj ET".encode())
    p[NameObject("/Contents")] = w._add_object(stream)
    out = io.BytesIO()
    w.write(out)
    return out.getvalue()


def test_original_caps_redirects_mime_signature_and_key_isolation(modules, monkeypatch):
    _, a, f, _ = modules
    api_record(monkeypatch, a, doc())
    calls = []
    data = pdf_bytes()

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return Response(data=data, headers={"Content-Type": "application/pdf", "Content-Length": "1"})

    monkeypatch.setattr(f.requests, "get", get)
    r = f.get_nrc_adams_document_file("ML25059A029")
    assert r["snapshot_created"] and r["actual_bytes"] == len(data) and r["page_count"] == 1
    assert f.snapshot("ML25059A029", r["sha256"]) == data
    assert "Ocp-Apim-Subscription-Key" not in calls[0][1]["headers"]
    assert calls[0][1]["allow_redirects"] is False
    oversized = f.get_nrc_adams_document_file("ML25059A029", 1)
    assert oversized["status"] == "file_too_large"
    assert oversized["source_url"] == "https://www.nrc.gov/docs/example.pdf"
    assert oversized["snapshot_created"] is False
    for response, expected in [
        (Response(status=302, headers={"Location": "https://evil.test/key"}), "redirect_rejected"),
        (Response(data=b"<html>challenge</html>", headers={"Content-Type": "text/html"}), "unsupported_mime"),
        (Response(data=b"<html>", headers={"Content-Type": "application/pdf"}), "invalid_pdf_signature"),
    ]:
        monkeypatch.setattr(f.requests, "get", lambda *_a, **_k: response)
        assert f.get_nrc_adams_document_file("ML25059A029")["status"] == expected
    monkeypatch.setattr(f.time, "monotonic", lambda: 10**20)
    with pytest.raises(ValueError, match="expired"):
        f.snapshot("ML25059A029", r["sha256"])


def test_reference_locators_self_dedup_negative_and_pdf_pages(modules, monkeypatch):
    _, a, f, r = modules
    api_record(
        monkeypatch, a, doc(content="References:\nADAMS ML24017A120, see ML24017A120. ML25059A029 05000373 1234567")
    )
    result = r.get_nrc_adams_document_references("ML25059A029")
    assert (
        result["candidate_count"] == 1 and result["self_mentions_excluded"] == 1 and result["duplicate_mentions"] == 1
    )
    assert len(result["references"][0]["occurrences"]) == 2
    location = result["references"][0]["occurrences"][0]["locator"]
    assert location["character_end"] - location["character_start"] == 11
    monkeypatch.setattr(
        f.requests, "get", lambda *_a, **_k: Response(data=pdf_bytes(), headers={"Content-Type": "application/pdf"})
    )
    result = r.get_nrc_adams_document_references("ML25059A029", source="original_pdf")
    assert result["references"][0]["occurrences"][0]["locator"]["physical_pdf_page"] == 1
    api_record(monkeypatch, a, doc(content="ML25059A029 in routing block, docket 05000373"))
    result = r.get_nrc_adams_document_references("ML25059A029")
    assert result["candidate_count"] == 0 and result["status"] == "empty"


def test_private_config_loading_env_precedence_existing_file_and_diagnostics(modules, tmp_path, monkeypatch, capsys):
    p = tmp_path / "credentials.env"
    monkeypatch.setenv("NEPA_MCP_CONFIG_FILE", str(p))
    config.create_credential_template()
    assert p.stat().st_mode & 0o077 == 0
    p.write_text("NRC_ADAMS_API_KEY=file-secret\nUNRELATED_SECRET=not-loaded\n")
    sources = config.load_credentials()
    assert sources["NRC_ADAMS_API_KEY"] == "user config"
    assert os.environ["NRC_ADAMS_API_KEY"] == "file-secret" and "UNRELATED_SECRET" not in os.environ
    monkeypatch.setenv("NRC_ADAMS_API_KEY", "environment-secret")
    config.load_credentials()
    assert os.environ["NRC_ADAMS_API_KEY"] == "environment-secret"
    cli.doctor()
    output = capsys.readouterr().out
    assert "environment-secret" not in output and "file-secret" not in output
    p.write_text("CENSUS_API_KEY=old-file\n")
    _, created = config.create_credential_template()
    assert not created and "NRC_ADAMS_API_KEY" not in p.read_text()


def test_mcp_discovery_without_key_and_resource_link(modules, monkeypatch):
    server, a, f, _ = modules

    async def check():
        async with Client(server.mcp) as c:
            assert len(await c.list_tools()) == 6
            result = await c.call_tool("get_nrc_adams_document", {"accession_number": "ML25059A029"})
            assert json.loads(result.data)["status"] == "missing_configuration"
            api_record(monkeypatch, a, doc())
            monkeypatch.setattr(
                f.requests,
                "get",
                lambda *_a, **_k: Response(data=pdf_bytes(), headers={"Content-Type": "application/pdf"}),
            )
            result = await c.call_tool("get_nrc_adams_document_file", {"accession_number": "ML25059A029"})
            assert any(x.type == "resource_link" for x in result.content)
            uri = json.loads(result.structured_content["result"])["resource_uri"]
            resources = await c.read_resource(uri)
            assert resources

    asyncio.run(check())


def test_repeated_source_window_stops_continuation(modules, monkeypatch):
    _, a, _, _ = modules
    monkeypatch.setenv("NRC_ADAMS_API_KEY", "secret")
    monkeypatch.setattr(
        a.requests, "request", lambda *_a, **_k: Response({"count": 200, "results": [{"document": doc()}]})
    )
    a.search_nrc_adams_documents("reactor")
    result = a.search_nrc_adams_documents("reactor", result_offset=100)
    assert result["status"] == "partial"
    assert result["pagination"]["next_result_offset"] is None
    assert any("repeated" in w for w in result["warnings"])
