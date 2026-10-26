"""Explicit curated crosswalks for Army plans; no auction state inferred from page templates."""

from datetime import datetime
from src.apis.adapters import Budget, fetch
from src.apis.installations_api import resolve
from src.core.normalization import output, page
from src.core.sources import ARMY

# These exact source URLs are in the official round directories. The offer table labels
# are separately published aliases. Preserve the crosswalk basis in every result.
OFFER_CROSSWALKS = {
    ARMY + "brac-1995/defense-distribution-depot-memphis/": "Defense Depot – Memphis",
    ARMY + "brac-1995/red-river-army-depot-95/": "Red River AD (RRAD)",
    ARMY + "brac-2005/red-river-army-depot-2005/": "Red River AD (RRAD)",
}


def parse_offers(content):
    records = []
    for row in content.select("table tr"):
        cells = row.find_all("td", recursive=False)
        if len(cells) != 2:
            continue
        label = cells[0].get_text(" ", strip=True)
        values = {}
        for strong in cells[1].find_all(["b", "strong"]):
            field = strong.get_text(" ", strip=True).rstrip(":")
            parts = []
            for sibling in strong.next_siblings:
                if getattr(sibling, "name", None) in {"br", "b", "strong"}:
                    break
                parts.append(str(sibling))
            values[field] = " ".join(" ".join(parts).split())
        if "Parcel" not in values or "Expected Disposal Date" not in values:
            continue
        raw_date = values["Expected Disposal Date"]
        try:
            date = datetime.strptime(raw_date, "%d-%b-%Y").date().isoformat()
        except ValueError:
            date = None
        records.append(
            {
                "source_installation_label": label,
                "parcel_label": values["Parcel"],
                "evidence_type": "planned_disposal",
                "status": "source_reported_plan; no advertised bid window established",
                "method": values.get("Conveyance Method"),
                "published_acres": values.get("Acres"),
                "acreage_units": "acres",
                "expected_disposal_date_raw": raw_date,
                "expected_disposal_date": date,
                "bid_deadline": None,
                "listing_id": None,
                "source_fields": values,
            }
        )
    return records


def get_brac_property_offers(installation_id, include_historical=False, max_results=100, result_offset=0):
    page(max_results, result_offset)
    if type(include_historical) is not bool:
        raise ValueError("include_historical must be boolean")
    budget = Budget()
    record, reports = resolve(installation_id, budget)
    if record is None:
        return output([], reports, ["Unknown installation source identity"], max_results, result_offset)
    alias = OFFER_CROSSWALKS.get(record.get("url"))
    if alias is None:
        reports.append(
            {
                "url": ARMY + "properties-for-sale/",
                "status": "unsupported",
                "complete": False,
                "warnings": ["No verified installation/parcel crosswalk for the published planned offers"],
            }
        )
        return output(
            [],
            reports,
            ["Advertised offer adapters and historical auction state are unverified; no availability conclusion."],
            max_results,
            result_offset,
        )
    url = ARMY + "properties-for-sale/"
    content, report = fetch(url, budget)
    reports.append(report)
    records = []
    if content is not None:
        rows = parse_offers(content)
        if not rows:
            report.update(
                status="schema_error",
                complete=False,
                warnings=["No expected planned-disposal table rows parsed; not treated as an empty inventory"],
            )
        records = [
            {
                **r,
                "installation_id": installation_id,
                "source_url": url,
                "crosswalk_basis": "Explicit curated table-label to official Army round-record URL; no name/proximity auto-join",
            }
            for r in rows
            if r["source_installation_label"] == alias
        ]
    return output(
        records,
        reports,
        [
            "Only source-reported Army disposal plans are supported. No verified advertised-sale state or historical auction adapter; expected disposal dates are not bidding deadlines."
        ],
        max_results,
        result_offset,
    )
