"""Public ACRES property, accomplishment, and grant tables in Envirofacts."""

import re

from nepa_mcp_common.epa_records import evidence, fields, page, warn, window
from nepa_mcp_common.http import UpstreamServiceError, get_json_rows

BASE = "https://data.epa.gov/dmapservice/acres."
PROFILE = (
    "https://obipublic.epa.gov/analytics/saw.dll?PortalPages&Action=Navigate"
    "&PortalPath=/shared/CIMC/_portal/CIMC&Page=Profile+Page"
    "&col1=ACRES_GRANT_EXPORT.PROPERTY_ID&val1=%22{}%22"
)


def _read(result, table, column, ids, sort, offset=0, count=101):
    # All path components are constants or numeric IDs validated on both sides of the API.
    operator = "equals" if len(ids) == 1 else "in"
    url = f"{BASE}{table}/{column}/{operator}/{','.join(ids)}/sort/acres.{table}.{sort}:asc/{offset + 1}:{offset + count}/JSON"
    result["sources"].append(url)
    try:
        return get_json_rows(url, service_name=f"ACRES {table}", timeout=8)
    except UpstreamServiceError as exc:
        raise UpstreamServiceError(f"ACRES {table} was unavailable for this request.") from exc


def _matched(result, table, rows, column, ids):
    for row in rows:
        if str(row.get(column)) in ids:
            yield row
        else:
            warn(result, f"{table}: skipped rows with missing or conflicting {column}.")


def _id(value):
    return bool(re.fullmatch(r"[0-9]{1,12}", str(value)))


def _lookup(result, records, key, table):
    ids = sorted({str(row[key]) for row in records if _id(row.get(key))})
    if not ids:
        return {}
    try:
        rows = _read(result, table, key, ids, key, count=len(ids) + 1)
    except UpstreamServiceError as exc:
        warn(result, str(exc))
        return {}
    by_id = {}
    for row in _matched(result, table, rows, key, ids):
        value = str(row[key])
        if value in by_id:
            warn(result, f"{table}: ambiguous {key} {value}.")
            by_id[value] = {}
        else:
            by_id[value] = row
    return by_id


def property_records(property_id, max_results=25, result_offset=0, *, grants=False):
    if not _id(property_id):
        raise ValueError("property_id must contain 1–12 digits")
    window(max_results, result_offset)
    pid = str(int(property_id))  # Envirofacts defines property_id as numeric.
    result = evidence(
        property_id=pid,
        profile_url=PROFILE.format(pid),
        scope="Grant records describe whole awards."
        if grants
        else "Grantee-reported milestones do not establish suitability for reuse.",
    )
    try:
        props = _read(result, "grant_property", "property_id", [pid], "property_id", count=2)
    except UpstreamServiceError as exc:
        warn(result, str(exc), unavailable=True)
        return result
    props = list(_matched(result, "grant_property", props, "property_id", [pid]))
    if not props:
        page(result, [], max_results, result_offset, more=False)
        return result
    if len(props) != 1:
        warn(result, "Ambiguous ACRES property ID; no records attributed.")
        return result
    result["property"] = fields(props[0], "property_id property_name city state_id p_epa_frs_id mod_date")
    table, key = ("grant_property_assoc", "grant_id") if grants else ("grant_property_accomplishment", "gpa_id")
    try:
        rows = _read(result, table, "property_id", [pid], key, result_offset, max_results + 1)
    except UpstreamServiceError as exc:
        warn(result, str(exc))
        return result
    more = len(rows) > max_results
    rows = list(_matched(result, table, rows[:max_results], "property_id", [pid]))
    if grants:
        details = _lookup(result, rows, "grant_id", "grants")
        types = _lookup(result, details.values(), "grant_type_id", "ref_grant_type")
    else:
        types = _lookup(result, rows, "gpa_type_id", "ref_gpa_type")
    records = []
    for row in rows:
        if grants:
            record = fields(row, "property_id grant_id")
            grant = details.get(str(row.get("grant_id"))) or {}
            record.update(
                fields(
                    grant,
                    "recipient_name p_recipient_organization grant_type_id coop_agreement_number award_date award_amount_cumulative mod_date",
                )
            )
            label = types.get(str(grant.get("grant_type_id")), {}).get("label_grant_type")
            record["grant_type"] = label
            if not grant or not label:
                warn(result, "Missing grant details or grant type for a published property association.")
        else:
            record = fields(
                row,
                "gpa_id grant_id gpa_type_id gpa_start_date gpa_completion_date gpa_flag flag_delete flag_count_accomplishment mod_date",
            )
            record["activity"] = types.get(str(row.get("gpa_type_id")), {}).get("label_gpa_type")
            if not record["activity"] or not _id(row.get("gpa_id")):
                warn(result, "Activity ID or activity type unavailable.")
        records.append(record)
    page(result, records, max_results, result_offset, more=more)
    if not grants and not result_offset and result["status"] == "empty":
        result["status"] = "complete"  # A property profile can have no activity rows.
    return result
