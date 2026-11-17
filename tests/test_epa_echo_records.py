"""Exercise EPA response contracts without a network dependency."""

import asyncio
import json
import os
from io import BytesIO

import pytest
import requests
from fastmcp import Client
from urllib3.exceptions import ReadTimeoutError

from epa_echo.src.apis import echo_api as api
from nepa_mcp.loader import load_server_module
from nepa_mcp_common.http import ResponseTooLarge, UpstreamServiceError

FRS = "110029030144"
PERMIT = "DC0021199"
CASE = "03-2022-0102"


def install(monkeypatch, payload):
    calls = []

    def fetch(url, *, params, **kwargs):
        calls.append((url, params))
        return {"Results": {"Message": "Success", **payload}}

    monkeypatch.setattr(api, "get_json", fetch)
    return calls


def test_search_two_steps_and_multiple_permits(monkeypatch):
    calls = []

    def fetch(url, *, params, **kw):
        calls.append(params)
        if url.endswith("get_facilities"):
            assert params["responseset"] == 1 and params["p_st"] == "DC" and params["p_fn"] == "Blue Plains"
            return {"Results": {"Message": "Success", "QueryRows": "2", "QueryID": "423"}}
        assert params["qid"] == "423" and params["pageno"] == 2 and "23" in params["qcolumns"].split(",")
        return {
            "Results": {
                "Message": "Working",
                "QueryID": "423",
                "PageNo": "2",
                "Facilities": [
                    {"RegistryID": FRS, "NPDESIDs": "DC0021199 DCL021199", "FacLat": "38.81", "FacLong": "-77.03"}
                ],
            }
        }

    monkeypatch.setattr(api, "get_json", fetch)
    r = api.search("Blue Plains", "dc", None, None, 25, 1, 2)
    assert len(calls) == 2 and not r["has_more"] and r["records"][0]["NPDESIDs"] == "DC0021199 DCL021199"


def test_radius_and_no_results(monkeypatch):
    calls = install(monkeypatch, {"QueryRows": "0"})
    r = api.search(None, None, 38.8, -77, 0.1, 25, 1)
    assert r["status"] == "empty" and len(calls) == 1 and calls[0][1]["p_radius"] == 0.1


@pytest.mark.parametrize(
    "args",
    [
        ("test", "DC", 0, 0, 25, 1, 1),
        (None, None, 1, None, 25, 1, 1),
        ("test", "ZZ", None, None, 25, 1, 1),
        (None, None, 0, 0, 100.1, 1, 1),
    ],
)
def test_invalid_search_before_network(monkeypatch, args):
    monkeypatch.setattr(api, "get_json", lambda *a, **kw: pytest.fail("unexpected request"))
    with pytest.raises(ValueError):
        api.search(*args)


def test_interrupted_page_and_bad_qid(monkeypatch):
    def broken(url, **kw):
        if url.endswith("get_qid"):
            raise UpstreamServiceError("timeout")
        return {"Results": {"Message": "Success", "QueryRows": "12", "QueryID": "7"}}

    monkeypatch.setattr(api, "get_json", broken)
    r = api.search("Blue Plains", "DC", None, None, 25, 10, 1)
    assert r["status"] == "partial" and r["reported_matches"] == 12 and "records" not in r
    assert "timeout" not in str(r["warnings"])


def test_dfr_source_scoped_ids_and_periods(monkeypatch):
    install(
        monkeypatch,
        {
            "RegistryID": FRS,
            "SystemExtractDates": {"Dates": [{"EPASystem": "ICIS-Air", "SystemExtractDate": "09/10/2026"}]},
            "Permits": [{"SourceID": PERMIT, "Statute": "CWA"}, {"SourceID": "DCL021199", "Statute": "CWA"}],
            "ICISFormalActions": {"Action": [{"CaseID": CASE}]},
            "AirCompliance": {
                "Header": {"Qtr1Start": "01/01/2024", "Qtr1End": "03/31/2024"},
                "Sources": [{"PermitHistory": {"SourceID": "AIR1", "Qtr1Status": "High Priority Violation"}}],
            },
            "RCRACompliance": {},
            "SDWISCompliance": {},
            "CWA3YrCompliance": {},
        },
    )
    r = api.report(FRS, "permits", 1, 0)
    assert r["next_offset"] == 1 and api.report(FRS, "permits", 1, 1)["records"][0]["SourceID"] == "DCL021199"
    assert api.report(FRS, "cases", 1, 0)["records"][0]["CaseID"] == CASE
    q = api.report(FRS, "quarters", 25, 0)
    assert q["status"] == "complete" and q["records"] == [
        dict(
            section="quarters",
            program="ICIS-Air",
            SourceID="AIR1",
            status="High Priority Violation",
            start="01/01/2024",
            end="03/31/2024",
        )
    ]
    assert api.report(FRS, "inspections", 25, 0)["status"] == "partial"


def test_dmr_period_and_value_semantics(monkeypatch):
    args = (PERMIT, "2024-01-01", "2024-03-31", "001", "00300", 25, 0)
    rows = [
        dict(
            MonitoringPeriodEndDate="31-MAR-24",
            DMRValueNmbr=0,
            DMRUnitDesc="mg/L",
            LimitValueNmbr="1",
            NPDESViolations=[],
        ),
        dict(
            MonitoringPeriodEndDate="31-MAR-24",
            DMRValueNmbr=None,
            NODICode="P",
            NODIDesc="Lab error",
            LimitUnitDesc="lb/day",
            NPDESViolations=[{"ViolationCode": "D80"}],
        ),
        dict(MonitoringPeriodEndDate="31-DEC-23", DMRValueNmbr=99),
    ]
    calls = install(
        monkeypatch,
        {
            "SourceId": PERMIT,
            "PermFeatures": [
                {
                    "PermFeatureNmbr": "001",
                    "Parameters": [{"ParameterCode": "00300", "DischargeMonitoringReports": rows}],
                }
            ],
        },
    )
    r = api.discharges(*args)
    assert calls[0][1]["start_date"] == "01/01/2024" and calls[0][1]["end_date"] == "03/31/2024"
    a, b = r["records"]
    assert a["DMRValueNmbr"] == 0 and a["violations"] == []
    assert b["DMRValueNmbr"] is None and b["NODICode"] == "P" and b["violations"] == [{"ViolationCode": "D80"}]


@pytest.mark.parametrize("count,more", [(15, False), (16, True)])
def test_discharge_page_counts_matches_and_keeps_later_warnings(monkeypatch, count, more):
    rows = [
        {"MonitoringPeriodEndDate": "31-MAR-24", "DMREventId": i, "NPDESViolations": []} for i in range(1, count + 1)
    ]
    rows.insert(0, {"MonitoringPeriodEndDate": "31-DEC-23"})
    rows.append({"MonitoringPeriodEndDate": "unknown"})
    parameter = {"ParameterCode": "00300", "DischargeMonitoringReports": rows}
    install(monkeypatch, {"SourceId": PERMIT, "PermFeatures": [{"PermFeatureNmbr": "001", "Parameters": [parameter]}]})

    r = api.discharges(PERMIT, "2024-01-01", "2024-03-31", None, None, 5, 10)
    assert [row["DMREventId"] for row in r["records"]] == [11, 12, 13, 14, 15]
    assert r["has_more"] is more and r["next_offset"] == (15 if more else None)
    assert r["status"] == "partial" and "monitoring period" in r["warnings"][0]


def test_discharge_size_limit_and_explicit_retry(monkeypatch):
    payload = json.dumps({"Results": {"Message": "Success", "SourceId": PERMIT, "PermFeatures": []}}).encode()
    body = payload.ljust(1_000_001)
    calls = []

    def fetch(url, *, params, stream, **kw):
        assert stream and "max_response_mb" not in params
        calls.append(params.copy())
        response = requests.Response()
        response.status_code = 200
        response.raw = BytesIO(body)
        return response

    monkeypatch.setattr(requests, "get", fetch)
    args = dict(permit_id=PERMIT, start_date="2024-01-01", end_date="2024-01-31", max_response_mb=1)
    r = asyncio.run(mcp_call("epa_echo", "get_epa_echo_discharge_reports", args))
    assert len(calls) == 1 and r["reason"] == "response_size_limit" and r["status"] == "unavailable"
    assert "records" not in r and r["sources"] and "NEPA-MCP" in r["warnings"][0]
    assert "1 MB" in r["warnings"][0] and "max_response_mb=2" in r["warnings"][0]
    r = asyncio.run(mcp_call("epa_echo", "get_epa_echo_discharge_reports", dict(args, max_response_mb=2)))
    assert calls[0] == calls[1] and r["status"] == "empty" and "reason" not in r


@pytest.mark.parametrize("override,limit", [({}, 50), ({"max_response_mb": 100}, 100)])
def test_discharge_limit_warning_at_default_and_maximum(monkeypatch, override, limit):
    def oversized(url, *, max_bytes, **kw):
        assert max_bytes == limit * 1_000_000
        raise ResponseTooLarge("too large")

    monkeypatch.setattr(api, "get_json", oversized)
    r = api.discharges(PERMIT, "2024-01-01", "2024-01-31", None, None, 1, 0, **override)
    warning = r["warnings"][0]
    assert r["reason"] == "response_size_limit" and f"{limit} MB" in warning
    assert ("max_response_mb=100" in warning) == (limit < 100)
    assert "date range" in warning


@pytest.mark.parametrize("value", [0, 101, 1.5, True])
def test_discharge_rejects_invalid_response_budget_before_request(monkeypatch, value):
    monkeypatch.setattr(api, "get_json", lambda *a, **kw: pytest.fail("unexpected request"))
    with pytest.raises(ValueError, match="max_response_mb"):
        api.discharges(PERMIT, "2024-01-01", "2024-01-31", None, None, 1, 0, value)


@pytest.mark.parametrize(
    "failure,reason,warning",
    [
        (429, "upstream_rate_limited", "HTTP 429"),
        (503, "upstream_http_error", "HTTP 503"),
        (requests.Timeout("private detail"), "upstream_timeout", "timed out"),
        (requests.ConnectionError(ReadTimeoutError(None, None, "private detail")), "upstream_timeout", "timed out"),
        (requests.ConnectionError("private detail"), "upstream_connection_error", "connection"),
        (200, "invalid_upstream_response", "invalid JSON"),
    ],
)
def test_discharge_distinguishes_upstream_failures(monkeypatch, failure, reason, warning):
    def fetch(url, **kw):
        if isinstance(failure, Exception):
            raise failure
        response = requests.Response()
        response.status_code = failure
        response.raw = BytesIO(b"private detail")
        return response

    monkeypatch.setattr(requests, "get", fetch)
    r = api.discharges(PERMIT, "2024-01-01", "2024-01-31", None, None, 1, 0)
    assert r["status"] == "unavailable" and r["reason"] == reason and warning in r["warnings"][0]
    assert "records" not in r and "private detail" not in str(r) and "max_response_mb" not in str(r)


def test_case_and_penalty_roles(monkeypatch):
    install(
        monkeypatch,
        {
            "CaseInformation": {
                "CaseNumber": CASE,
                "CaseStatus": "Closed",
                "TotalFederalPenalty": "$0",
                "TotalStatePenalty": None,
            },
            "CaseMilestones": [{"Event": "Final Order Issued", "ActualDate": "09/16/2022"}],
            "LawsAndSections": [{"Law": "RCRA"}],
            "EnforcementConclusions": [],
            "ProgramLinks": [],
        },
    )
    r = api.civil_case(CASE, 100, 0)
    assert r["case"]["TotalFederalPenalty"] == "$0" and r["case"]["TotalStatePenalty"] is None
    assert r["records"][1]["ActualDate"] == "09/16/2022"


@pytest.mark.parametrize("payload", [{"RegistryID": "110000000000"}, {"Error": {"ErrorMessage": "invalid ID"}}, {}])
def test_wrong_missing_or_rejected_identity(monkeypatch, payload):
    install(monkeypatch, payload)
    r = api.report(FRS, "all", 1, 0)
    assert r["status"] == "unavailable" and r["warnings"] and "records" not in r


async def mcp_call(server, tool, args, patch=None):
    module = load_server_module(server)
    if patch:
        patch(module)
    async with Client(module.mcp) as client:
        result = await client.call_tool(tool, args)
    return json.loads(result.content[0].text)


def test_mcp_civil_case_call(monkeypatch):
    def patch(module):
        monkeypatch.setattr(
            module.api,
            "get_json",
            lambda *a, **kw: {
                "Results": {
                    "Message": "Success",
                    "CaseInformation": {"CaseNumber": CASE, "CaseName": "Test case"},
                    "LawsAndSections": [],
                    "CaseMilestones": [],
                    "ProgramLinks": [],
                    "EnforcementConclusions": [],
                }
            },
        )

    r = asyncio.run(mcp_call("epa_echo", "get_epa_echo_civil_case", {"case_number": CASE}, patch))
    assert r["case"]["CaseNumber"] == CASE and r["status"] == "complete"


@pytest.mark.skipif(os.getenv("NEPA_EPA_LIVE") != "1", reason="opt-in public EPA service checks")
@pytest.mark.parametrize(
    "server,tool,args",
    [
        ("epa_acres", "get_epa_acres_property", {"property_id": "135202"}),
        ("epa_acres", "get_epa_acres_property_grants", {"property_id": "135202"}),
        ("epa_echo", "search_epa_echo_facilities", {"name": "Blue Plains", "state": "DC"}),
        ("epa_echo", "search_epa_echo_facilities", {"latitude": 38.82, "longitude": -77.03, "radius_miles": 0.5}),
        ("epa_echo", "get_epa_echo_facility_report", {"frs_id": FRS, "section": "cases"}),
        ("epa_echo", "get_epa_echo_facility_report", {"frs_id": FRS, "section": "quarters"}),
        (
            "epa_echo",
            "get_epa_echo_discharge_reports",
            {"permit_id": PERMIT, "start_date": "2024-01-01", "end_date": "2024-03-31"},
        ),
        ("epa_echo", "get_epa_echo_civil_case", {"case_number": CASE}),
    ],
)
def test_public_epa_mcp(server, tool, args):
    r = asyncio.run(mcp_call(server, tool, dict(args, max_results=5)))
    assert r["status"] == "complete" and r["records"] and r["sources"], r


def test_loading_echo_after_acres_reselects_its_own_api():
    for name in ["epa_echo", "epa_acres", "epa_echo"]:
        assert load_server_module(name).mcp.name == name.replace("_", "-") + "-server"


@pytest.mark.parametrize(
    "permit,start,end,outfall,code",
    [
        ("../escape", "2024-01-01", "2024-02-01", None, None),
        (PERMIT, "2024-02-30", "2024-03-01", None, None),
        (PERMIT, "2024-02-01", "2024-01-31", None, None),
        (PERMIT, "2020-01-01", "2024-01-31", None, None),
        (PERMIT, "2024-01-01", "2024-02-01", "toolong", None),
        (PERMIT, "2024-01-01", "2024-02-01", None, "invalid"),
    ],
)
def test_dmr_rejects_invalid_filters_before_network(monkeypatch, permit, start, end, outfall, code):
    monkeypatch.setattr(api, "get_json", lambda *a, **kw: pytest.fail("unexpected request"))
    with pytest.raises(ValueError):
        api.discharges(permit, start, end, outfall, code, 25, 0)


def test_civil_case_does_not_attribute_other_case(monkeypatch):
    install(monkeypatch, {"CaseInformation": {"CaseNumber": "03-2019-0001"}})
    r = api.civil_case(CASE, 20, 0)
    assert r["status"] == "unavailable" and "case" not in r


def test_reporting_periods_are_section_specific(monkeypatch):
    install(
        monkeypatch,
        {
            "RegistryID": FRS,
            "SystemExtractDates": {"Dates": []},
            "ComplianceHistory": {
                "ProgramDates": [{"Program": "CAA", "StartDate": "07/01/2022", "EndDate": "06/30/2025"}],
                "Inspection": [{"SourceID": "A1", "EPASystem": "ICIS-Air", "Date": "05/03/2025"}],
            },
        },
    )
    r = api.report(FRS, "inspections", 25, 0)
    assert r["status"] == "complete" and r["records"][0]["Date"] == "05/03/2025"
    assert r["reporting_periods"]["inspections"][0]["EndDate"] == "06/30/2025"
