"""Read-only EPA ECHO search, detailed facility, effluent, and civil case services."""

import re
from datetime import date, datetime
from urllib.parse import urlencode

from nepa_mcp_common.epa_records import evidence, fields, page, warn, window
from nepa_mcp_common.http import ResponseTooLarge, UpstreamServiceError, get_json
from nepa_mcp_common.validation import validate_coordinates

BASE = "https://echodata.epa.gov/echo/"
DEFAULT_RESPONSE_MB = 50
MAX_RESPONSE_MB = 100
COLS = "1,2,3,4,6,19,20,21,22,23,24,25,26,27,28,29,30,31"
FAC_FIELDS = "FacName FacStreet FacCity FacState RegistryID FacLat FacLong AIRIDs CamdIDs NPDESIDs RCRAIDs RmpIDs SemsIDs SDWAIDs TRIIDs EisIDs GHGIDs TscaIDs"
STATES = set(
    "AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY AS GU MP PR VI UM FM MH PW".split()
)


def _request(result, service, *, max_bytes=None, timeout=20, **params):
    params["output"] = "JSON"
    url = BASE + service
    result["sources"].append(url + "?" + urlencode(params))
    try:
        payload = get_json(url, params=params, service_name="EPA ECHO", timeout=timeout, max_bytes=max_bytes)
    except ResponseTooLarge as exc:
        limit_mb = max_bytes // 1_000_000
        message = f"NEPA-MCP stopped reading this report at its {limit_mb} MB limit. "
        if limit_mb < MAX_RESPONSE_MB:
            message += f"Retry with max_response_mb={min(2 * limit_mb, MAX_RESPONSE_MB)}, or narrow the date range, outfall, or pollutant."
        else:
            message += "Narrow the date range, outfall, or pollutant."
        raise UpstreamServiceError(message, reason="response_size_limit") from exc
    except UpstreamServiceError as exc:
        if exc.reason != "upstream_error":
            raise
        raise UpstreamServiceError(f"ECHO {service} was unavailable for this request.") from exc
    data = payload.get("Results")
    err = payload.get("Error") or (data.get("Error") if isinstance(data, dict) else None)
    if err:
        raise UpstreamServiceError(f"ECHO {service} returned an error for this request.", reason="upstream_api_error")
    if not isinstance(data, dict) or data.get("Message") not in ("Success", "Working"):
        raise UpstreamServiceError(
            f"ECHO {service}: missing or unsuccessful results.", reason="invalid_upstream_response"
        )
    return data


def _lookup(result, service, identifier, identity_field, container=None, **params):
    try:
        data = _request(result, service, p_id=identifier, **params)
        identity = data if container is None else data.get(container)
        if not isinstance(identity, dict) or identity.get(identity_field) != identifier:
            raise UpstreamServiceError(
                "Missing or conflicting EPA identifier; no records attributed.", reason="invalid_upstream_response"
            )
        return data
    except UpstreamServiceError as exc:
        result["reason"] = exc.reason
        warn(result, str(exc), unavailable=True)
        return None


def _rows(result, obj, key):
    """ECHO uses empty objects or lists for empty sections."""
    value = obj.get(key)
    if value == {}:
        return []
    if not isinstance(value, list):
        warn(result, f"ECHO did not return a record list for {key}.")
        return []
    if all(isinstance(row, dict) for row in value):
        return value
    warn(result, f"Skipped malformed {key} rows.")
    return [row for row in value if isinstance(row, dict)]


def _id(value, pattern, name):
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise ValueError(f"Invalid {name}.")


def search(name, state, latitude, longitude, radius_miles, max_results, page_number):
    window(max_results, (page_number - 1) * max_results)
    params = {}
    if latitude is not None or longitude is not None:
        if name is not None or state is not None or latitude is None or longitude is None:
            raise ValueError("Use either name and state, or a complete coordinate pair.")
        lat, lon, radius = validate_coordinates(latitude, longitude, radius_miles)
        params.update(p_lat=lat, p_long=lon, p_radius=radius)
    else:
        if not name or not 2 <= len(name.strip()) <= 120 or "," in name or not state or state.upper() not in STATES:
            raise ValueError("Provide one facility name (2–120 characters) and a state or territory abbreviation.")
        if radius_miles != 25:
            raise ValueError("radius_miles applies only to coordinate searches.")
        params.update(p_fn=name.strip(), p_st=state.upper())
    result = evidence(
        page_number=page_number, page_size=max_results, scope="Facility reference locations, not outfall locations."
    )
    try:
        head = _request(result, "echo_rest_services.get_facilities", responseset=max_results, **params)
        if not str(head.get("QueryRows")).isdigit():
            raise UpstreamServiceError("Missing ECHO facility count.")
        total = int(head["QueryRows"])
        result["reported_matches"] = total
        offset = (page_number - 1) * max_results
        if total <= offset:
            result.update(status="empty", records=[], has_more=False)
            return result
        qid = str(head.get("QueryID"))
        if not qid.isdigit():
            raise UpstreamServiceError("Missing ECHO query ID.")
        data = _request(result, "echo_rest_services.get_qid", qid=qid, pageno=page_number, qcolumns=COLS)
        if str(data.get("QueryID")) != qid or str(data.get("PageNo")) != str(page_number):
            raise UpstreamServiceError("ECHO returned a different query or page.")
        rows = _rows(result, data, "Facilities")
        if len(rows) != min(max_results, total - offset):
            warn(result, "Facility page size differs from EPA's reported count.")
        more = offset + max_results < total
        result.update(
            records=[fields(r, FAC_FIELDS) for r in rows[:max_results]],
            has_more=more,
            next_page=page_number + 1 if more and offset + max_results <= 9999 else None,
        )
        if more and result["next_page"] is None:
            warn(result, "Additional facilities exceed the supported page range; narrow the search.")
        if any(not r.get("RegistryID") for r in result["records"]):
            warn(result, "Some facilities lack an FRS ID.")
    except UpstreamServiceError as exc:
        result["reason"] = exc.reason
        warn(result, str(exc), unavailable="reported_matches" not in result)
    return result


# Outer DFR sections have independent coverage. Report their dates alongside each page.
DFR = {
    "permits": ("Permits", None, "SourceID Statute EPASystem FacilityName Universe ExpDate Latitude Longitude"),
    "inspections": (
        "ComplianceHistory",
        "Inspection",
        "SourceID Statute EPASystem Date ActivityType InspectionType LeadAgency Finding CompMonitorID",
    ),
    "compliance": ("ComplianceSummary", "Source", "SourceID Statute CurrentSNC Description CurrentAsOf QtrsInNC"),
    "notices": ("Notices", "Notice", "SourceID Statute EPASystem ActionType LeadAgency NoticeDate EnfIdentifier"),
    "actions": ("FormalActions", "Action", "SourceID Statute ActionType ActionDate LeadAgency PenaltyAmount"),
    "cases": (
        "ICISFormalActions",
        "Action",
        "CaseID CaseName StatuteCode LawSectionCode CaseType IssueDate SettlementDate FederalPenalty StateLocalPenalty",
    ),
}
QUARTERS = {
    "ICIS-Air": "AirCompliance",
    "ICIS-NPDES": "CWA3YrCompliance",
    "RCRA": "RCRACompliance",
    "SDWA": "SDWISCompliance",
}


def _quarterly(result, data):
    for program, key in QUARTERS.items():
        block = data.get(key)
        if not isinstance(block, dict):
            warn(result, f"Missing ECHO {key} section.")
            continue
        if not block:
            continue
        header = block.get("Header", block)
        if not isinstance(header, dict):
            warn(result, f"Missing quarter dates for {program}.")
            header = {}
        for src in _rows(result, block, "Sources"):
            history = src.get("PermitHistory" if program == "ICIS-Air" else "Status")
            if isinstance(history, dict):
                history = [history]
            if not isinstance(history, list):
                warn(result, f"Missing {program} quarter history.")
                continue
            for row in history:
                if not isinstance(row, dict):
                    warn(result, f"Malformed {program} quarter history.")
                    continue
                for i in range(1, 14):
                    q = f"Qtr{i}"
                    if q + "Status" in row:
                        if not row.get("SourceID") or not header.get(q + "Start") or not header.get(q + "End"):
                            warn(result, f"Missing source ID or quarter dates for {program}.")
                        yield dict(
                            section="quarters",
                            program=program,
                            SourceID=row.get("SourceID"),
                            status=row[q + "Status"],
                            start=header.get(q + "Start"),
                            end=header.get(q + "End"),
                        )


def report(frs_id, section, max_results, result_offset):
    _id(frs_id, r"[0-9]{12}", "FRS registry ID")
    window(max_results, result_offset)
    if section not in ("all", "quarters", *DFR):
        raise ValueError("Unknown facility report section.")
    result = evidence(
        registry_id=frs_id,
        section=section,
        report_url="https://echo.epa.gov/detailed-facility-report?fid=" + frs_id,
        scope="ECHO reporting periods vary by program. An empty history does not establish compliance.",
    )
    data = _lookup(result, "dfr_rest_services.get_dfr", frs_id, "RegistryID")
    if data is None:
        return result
    dates = data.get("SystemExtractDates")
    result["system_extract_dates"] = [
        fields(d, "EPASystem SystemExtractDate")
        for d in _rows(result, dates if isinstance(dates, dict) else {}, "Dates")
    ]
    rows = []
    result["reporting_periods"] = {}
    for label, (key, child, names) in DFR.items():
        if section not in ("all", label):
            continue
        if child is None:
            items = _rows(result, data, key)
        else:
            block = data.get(key)
            if block == {}:
                continue
            block = block if isinstance(block, dict) else {}
            items = _rows(result, block, child)
            result["reporting_periods"][label] = [
                fields(period, "Program StartDate EndDate") for period in _rows(result, block, "ProgramDates")
            ]
        for row in items:
            record = fields(row, names)
            if not record.get("CaseID" if label == "cases" else "SourceID"):
                warn(result, f"Missing identifier in {label}.")
            rows.append(dict(section=label, **record))
    if section in ("all", "quarters"):
        rows.extend(_quarterly(result, data))
    page(
        result,
        rows[result_offset : result_offset + max_results],
        max_results,
        result_offset,
        more=len(rows) > result_offset + max_results,
    )
    return result


def civil_case(case_number, max_results, result_offset):
    _id(case_number, r"[A-Za-z0-9]{1,6}-[0-9]{4}-[0-9]{3,6}", "ICIS case number")
    window(max_results, result_offset)
    result = evidence(
        case_number=case_number, report_url="https://echo.epa.gov/enforcement-case-report?id=" + case_number
    )
    data = _lookup(result, "case_rest_services.get_case_report", case_number, "CaseNumber", "CaseInformation")
    if data is None:
        return result
    result["case"] = fields(
        data["CaseInformation"],
        "CaseNumber CaseName CaseType CaseStatus CaseStatusDate Lead EnforcementOutcome TotalFederalPenalty TotalStatePenalty PenaltyCollected",
    )
    sections = {
        "LawsAndSections": "Law Sections Programs",
        "CaseMilestones": "Event ActualDate",
        "EnforcementConclusions": "EnforcementConclusionId EnforcementConclusionType SettlementEnteredDate SettlementLodgedDate FederalPenalty StatePenalty",
        "ProgramLinks": "FRSNumber Program ProgramID",
    }
    rows = [
        dict(section=key, **fields(row, names)) for key, names in sections.items() for row in _rows(result, data, key)
    ]
    page(
        result,
        rows[result_offset : result_offset + max_results],
        max_results,
        result_offset,
        more=len(rows) > result_offset + max_results,
    )
    # An identified case is still a result when it has no accompanying event rows.
    if result["status"] == "empty" and result_offset == 0:
        result["status"] = "complete"
    return result


DMR_FIELDS = (
    "DMREventId LimitId LimitBeginDate LimitEndDate LimitValueTypeDesc LimitValueNmbr LimitUnitDesc LimitValueQualifierCode StatisticalBaseDesc "
    "MonitoringPeriodEndDate DMRValueNmbr DMRUnitDesc DMRValueQualifierCode NODICode NODIDesc ValueReceivedDate ExceedencePct"
)


def discharges(
    permit_id,
    start_date,
    end_date,
    outfall,
    parameter_code,
    max_results,
    result_offset,
    max_response_mb=DEFAULT_RESPONSE_MB,
):
    _id(permit_id, r"[A-Z0-9]{9}", "NPDES permit ID")
    window(max_results, result_offset)
    if type(max_response_mb) is not int or not 1 <= max_response_mb <= MAX_RESPONSE_MB:
        raise ValueError(f"max_response_mb must be an integer from 1 to {MAX_RESPONSE_MB}.")
    start, end = date.fromisoformat(start_date), date.fromisoformat(end_date)
    if not 0 <= (end - start).days <= 366:
        raise ValueError("Use an ordered monitoring period of at most 367 days.")
    params = {"start_date": start.strftime("%m/%d/%Y"), "end_date": end.strftime("%m/%d/%Y")}
    for key, val, pattern in [("outfall", outfall, r"[A-Z0-9]{3}"), ("parameter_code", parameter_code, r"[0-9]{5}")]:
        if val is not None:
            _id(val, pattern, key)
            params[key] = val
    result = evidence(
        permit_id=permit_id,
        start_date=start_date,
        end_date=end_date,
        scope="Reported monitoring values and violations; missing values are not zero.",
    )
    data = _lookup(
        result,
        "eff_rest_services.get_effluent_chart",
        permit_id,
        "SourceId",
        max_bytes=max_response_mb * 1_000_000,
        timeout=(5, 50),
        **params,
    )
    if data is None:
        return result
    result["permit"] = fields(data, "SourceId RegistryId CWPPermitStatusDesc StartDate EndDate")
    rows = []
    matches = 0
    page_end = result_offset + max_results
    for feature in _rows(result, data, "PermFeatures"):
        fid = feature.get("PermFeatureNmbr")
        if not fid:
            warn(result, "Missing outfall ID.")
        if outfall and outfall != fid:
            continue
        for parameter in _rows(result, feature, "Parameters"):
            code = parameter.get("ParameterCode")
            if not code:
                warn(result, "Missing pollutant ID.")
            if parameter_code and parameter_code != code:
                continue
            for dmr in _rows(result, parameter, "DischargeMonitoringReports"):
                try:
                    period = datetime.strptime(dmr["MonitoringPeriodEndDate"], "%d-%b-%y").date()
                except (ValueError, TypeError, KeyError):
                    warn(result, "Skipped a DMR without a usable monitoring period.")
                    continue
                if not start <= period <= end:
                    continue
                if "NPDESViolations" not in dmr:
                    warn(result, "EPA omitted the reported violations field.")
                violations = [] if dmr.get("NPDESViolations") is None else _rows(result, dmr, "NPDESViolations")
                matches += 1
                if not result_offset < matches <= page_end:
                    continue
                rows.append(
                    dict(
                        outfall=fid,
                        **fields(parameter, "ParameterCode ParameterDesc MonitoringLocationCode"),
                        **fields(dmr, DMR_FIELDS),
                        violations=[
                            fields(e, "NPDESViolationId ViolationCode ViolationDesc RNCDetectionDate RNCResolutionDate")
                            for e in violations
                        ],
                    )
                )
    page(result, rows, max_results, result_offset, more=matches > page_end)
    return result
