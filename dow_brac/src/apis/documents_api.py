"""Official link indexes: metadata retrieval is distinct from document review."""

from src.apis.adapters import Budget, fetch, links
from src.apis.installations_api import resolve
from src.core.normalization import output, page, text


def index(installation_id, kind="documents_url", budget=None):
    budget = budget or Budget()
    record, reports = resolve(installation_id, budget)
    if record is None:
        return None, [], reports
    url = record.get(kind) or record.get("url")
    if not url:
        return (
            record,
            [],
            reports
            + [
                {
                    "url": None,
                    "status": "unsupported",
                    "complete": False,
                    "warnings": ["No published supported index URL"],
                }
            ],
        )
    content, report = fetch(url, budget)
    reports.append(report)
    if content is None:
        return record, [], reports
    docs = []
    for link in links(content, url):
        if ".pdf" not in link["url"].lower():
            continue
        # Titles are discovery metadata, not verified NEPA/remedy/legal categories.
        docs.append(
            {
                **link,
                "installation_id": installation_id,
                "source_repository": url,
                "document_type": "unresolved",
                "source_category": "index title only",
                "published_date": None,
                "retrieval_status": "metadata_only",
                "category_warning": "Record of Decision alone does not establish NEPA vs cleanup remedy scope",
            }
        )
    return record, docs, reports


def get_brac_documents(installation_id, query=None, document_type=None, max_results=100, result_offset=0):
    page(max_results, result_offset)
    query = text(query, "query", True)
    if document_type not in {None, "unresolved"}:
        raise ValueError(
            "Only unresolved index categories are verified; use query for title search rather than inventing a document-type vocabulary"
        )
    record, docs, reports = index(installation_id)
    if query:
        docs = [d for d in docs if query.casefold() in d["title"].casefold()]
    docs.sort(key=lambda r: (r["title"].casefold(), r["url"]))
    return output(
        docs,
        reports,
        ["Filtering covers fetched supported index links only, not every repository document or document body."],
        max_results,
        result_offset,
    )
