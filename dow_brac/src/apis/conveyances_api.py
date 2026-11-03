"""Source-reported summaries stay separate from parcel-level executed transfers."""

import re
from src.apis.adapters import Budget, fetch
from src.apis.installations_api import resolve
from src.core.normalization import output, page


def get_brac_conveyance_records(installation_id, max_results=100, result_offset=0):
    page(max_results, result_offset)
    budget = Budget()
    record, reports = resolve(installation_id, budget)
    if record is None:
        return output([], reports, ["Unknown installation source identity"], max_results, result_offset)
    content, report = fetch(record.get("evidence_url") or record.get("url"), budget)
    reports.append(report)
    records = []
    if content is not None:
        value = content.get_text(" ", strip=True)
        match = re.search(r"Conveyance Summary:\s*(.+)", value, re.I)
        if match:
            summary = match[1][:2000]
            acreage = {
                label: found.group(1)
                for label in ["Starting Acres", "Remaining Acres", "Conveyed Acres"]
                if (found := re.search(re.escape(label) + r":\s*([\d,.]+)", summary))
            }
            records.append(
                {
                    "installation_id": installation_id,
                    "scope": "installation_summary",
                    "evidence_type": "published_conveyance_summary",
                    "source_text": summary,
                    "source_reported_acreage": acreage,
                    "units": "acres",
                    "as_of_date": None,
                    "source_url": record.get("evidence_url") or record["url"],
                    "executed_parcel_transactions_established": False,
                    "current_ownership_established": False,
                    "cleanup_complete_established": False,
                }
            )
    return output(
        records,
        reports,
        [
            "Parcel ledger coverage is not established; summary totals do not prove executed deeds, unrestricted use, or remaining availability."
        ],
        max_results,
        result_offset,
    )
