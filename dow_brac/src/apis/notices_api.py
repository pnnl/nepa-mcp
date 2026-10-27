"""Notice discovery never turns unknown deadlines into an open participation window."""

import re
from datetime import date, datetime
from src.apis.adapters import Budget, fetch, links
from src.apis.installations_api import resolve
from src.core.normalization import now, output, page, source_url
from urllib.parse import urljoin


def get_brac_public_notices(installation_id, published_on_or_after=None, max_results=100, result_offset=0):
    page(max_results, result_offset)
    if published_on_or_after is not None:
        if not isinstance(published_on_or_after, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", published_on_or_after):
            raise ValueError("published_on_or_after must be YYYY-MM-DD")
        date.fromisoformat(published_on_or_after)
    budget = Budget()
    record, reports = resolve(installation_id, budget)
    if record is None:
        return output([], reports, ["Unknown installation source identity"], max_results, result_offset)
    url = record.get("notices_url") or record.get("url")
    content, report = fetch(url, budget)
    reports.append(report)
    records = []
    if content is not None and record.get("notice_link_title_prefix"):
        for anchor in content.find_all("a", href=True):
            title = anchor.get("title", "")
            if not title.startswith(record["notice_link_title_prefix"]):
                continue
            target = source_url(urljoin(url, anchor["href"]))
            if not target:
                continue
            block = anchor.find_parent(class_="usa-collection__body")
            if block is None:
                report.update(status="schema_error", complete=False, warnings=["Notice content group changed"])
                continue
            calendar = block.find_previous_sibling()
            posted_raw = calendar.get_text(" ", strip=True) if calendar else None
            try:
                posted = datetime.strptime(posted_raw, "%b %d %Y").date().isoformat()
            except (ValueError, TypeError):
                posted = None
            if posted and published_on_or_after and posted < published_on_or_after:
                continue
            observed = block.get_text(" ", strip=True)
            records.append(
                {
                    "installation_id": installation_id,
                    "title": title,
                    "url": target,
                    "source_url": url,
                    "published_date": posted,
                    "publication_date_raw": posted_raw,
                    "source_comment_period_text": observed[-600:],
                    "deadline": None,
                    "timezone": None,
                    "participation_status": "unresolved_deadline_year_timezone_and_revision_state",
                    "body_reviewed": False,
                    "crosswalk_basis": "Exact full installation name in official source link title; explicit curated round-record association",
                    "date_filter_status": "matched_published_date" if posted else "unresolved_missing_publication_date",
                }
            )
    elif content is not None:
        for link in links(content, url):
            if not re.search(r"notice|comment|hearing|meeting|five.year.review", link["title"], re.I):
                continue
            records.append(
                {
                    **link,
                    "installation_id": installation_id,
                    "evidence_type": "notice_index_candidate",
                    "published_date": None,
                    "deadline": None,
                    "event_date": None,
                    "timezone": None,
                    "participation_status": "unresolved_dates_and_revision_state",
                    "cancellation_or_extension": "not established from linked document contents",
                    "date_filter_status": "unresolved_missing_publication_date"
                    if published_on_or_after
                    else "not_requested",
                }
            )
    result = output(
        records,
        reports,
        [
            "Notice index metadata only; participation dates, cancellations/extensions, and source time zones require underlying notice review. Unknown dates cannot establish an open window."
            if not published_on_or_after
            else "Publication-date filter cannot be verified for undated index entries; returned candidates are unresolved, not confirmed date matches."
        ],
        max_results,
        result_offset,
    )
    # Evaluation time describes this call, not a change to the source notice inventory.
    evaluated_at = now()
    for notice in result["records"]:
        notice["evaluated_at"] = evaluated_at
    return result
