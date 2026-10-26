"""Explicit index groups supply installation-scoped site/OU research candidates."""

import re
from src.apis.adapters import Budget, fetch
from src.apis.installations_api import resolve
from src.core.normalization import output, page, source_url
from urllib.parse import urljoin


def parse_sites(content, installation_id, url):
    records = {}
    for heading in content.find_all(re.compile("^h[1-6]$")):
        label = heading.get_text(" ", strip=True)
        ou = re.search(r"\b(?:Operable Unit|OU)\s*([0-9A-Za-z-]+)", label, re.I)
        if not ou:
            continue
        for node in heading.find_next_siblings():
            if re.fullmatch(r"h[1-6]", node.name or ""):
                break
            for li in node.find_all("li"):
                observed = li.get_text(" ", strip=True)
                site = re.search(r"\bIR\s*Site\s*([0-9A-Za-z-]+)", observed, re.I)
                if not site:
                    continue
                key = f"{installation_id}:IR:{site[1]}"
                row = records.setdefault(
                    key,
                    {
                        "site_id": key,
                        "installation_id": installation_id,
                        "source_program": "IR",
                        "source_site_label": site.group(),
                        "operable_units": [],
                        "parcel_association": "unresolved",
                        "status": "not inferred from document titles",
                        "geometry_available": False,
                        "source_url": url,
                        "inventory_verification": "Index grouping candidate; current nonempty live contract verification pending",
                        "evidence": [],
                    },
                )
                if ou[1] not in row["operable_units"]:
                    row["operable_units"].append(ou[1])
                row["evidence"].append(
                    {
                        "source_text": observed[:1000],
                        "heading": label,
                        "document_urls": [
                            target
                            for a in li.find_all("a", href=True)
                            if (target := source_url(urljoin(url, a["href"])))
                        ],
                    }
                )
    return list(records.values())


def get_brac_environmental_sites(installation_id, max_results=100, result_offset=0):
    page(max_results, result_offset)
    budget = Budget()
    record, reports = resolve(installation_id, budget)
    if record is None:
        return output([], reports, ["Unknown installation source identity"], max_results, result_offset)
    url = record.get("documents_url") or record.get("url")
    content, report = fetch(url, budget)
    reports.append(report)
    records = parse_sites(content, installation_id, url) if content is not None else []
    if content is not None and not records:
        report.update(
            status="schema_error",
            complete=False,
            warnings=["No verified explicit IR-site/OU groups parsed; this is not a no-environmental-sites finding"],
        )
    return output(
        sorted(records, key=lambda r: r["site_id"]),
        reports,
        [
            "Only explicit site/OU index groups are candidates; document mentions alone do not establish a complete site inventory. Geometry, parcel association, and media-specific cleanup conclusions remain unresolved."
        ],
        max_results,
        result_offset,
    )
