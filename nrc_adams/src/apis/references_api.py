"""Evidence-located accession mentions; no automatic citation graph or package inference."""

import re
import time

from src.apis.adams_api import SourceError, envelope, failure, indexed, record
from src.apis.files_api import get_nrc_adams_document_file, parse_pdf, snapshot
from src.core.normalization import fingerprint
from src.core.query import accession, page

MODERN = re.compile(r"(?<![A-Za-z0-9])ML[0-9]{5}[A-Z][0-9]{3}(?![A-Za-z0-9])", re.I)
# Numeric legacy strings require an explicit ADAMS URL context, not a naked number.
LEGACY_LINK = re.compile(
    r'https://(?:www\.)?(?:adams-search|adams)\.nrc\.gov/[^\s<>"\']*(?:AccessionNumber=|/search/)([0-9]{1,20})(?![0-9])',
    re.I,
)


def extract(texts, own, representation, source_fingerprint):
    candidates = {}
    self_count = 0
    duplicates = 0
    for locator, text in texts:
        matches = [(m.start(), m.end(), m.group()) for m in MODERN.finditer(text)]
        matches += [(m.start(1), m.end(1), m.group(1)) for m in LEGACY_LINK.finditer(text)]
        for start, end, observed in sorted(matches):
            target = accession(observed)
            if target == own:
                self_count += 1
                continue
            snippet = text[max(0, start - 100) : min(len(text), end + 100)]
            context = text[max(0, start - 60) : start].lower()
            kind = (
                "reference_section_entry"
                if re.search(r"references?\s*[:\n]", context)
                else "inline_citation_or_link"
                if re.search(r"\b(?:adams|accession|reference|see)\b", context)
                else "ambiguous_identifier_mention"
            )
            occurrence = {
                "observed_identifier": observed,
                "evidence_snippet": snippet,
                "locator": {**locator, "character_start": start, "character_end": end},
                "classification": kind,
            }
            if target in candidates:
                duplicates += 1
            candidate = candidates.setdefault(
                target,
                {
                    "accession_number": target,
                    "representation": representation,
                    "source_fingerprint": source_fingerprint,
                    "target_state": "unverified",
                    "occurrences": [],
                },
            )
            if len(candidate["occurrences"]) < 20:
                candidate["occurrences"].append(occurrence)
            else:
                candidate["occurrence_cap_reached"] = True
    return list(candidates.values()), self_count, duplicates


def get_nrc_adams_document_references(
    accession_number, source="indexed_text", verify_targets=False, max_results=100, result_offset=0
):
    number = accession(accession_number)
    page(max_results, result_offset)
    if source not in {"indexed_text", "original_pdf"}:
        raise ValueError("source must be indexed_text or original_pdf")
    if type(verify_targets) is not bool:
        raise ValueError("verify_targets must be boolean")
    try:
        if source == "indexed_text":
            doc, _ = record(number)
            full = indexed(doc)
            value = full[:1000000]
            sha = fingerprint(full.encode())
            texts = [({"representation": "indexed_text"}, value)]
            coverage = {
                "character_cap": 1000000,
                "scanned_characters": len(value),
                "available_characters": len(full),
                "scan_complete": len(value) == len(full),
                "source_text_completeness": "unknown",
                "locator_note": "Character offsets in API indexed representation, not PDF pages",
            }
        else:
            file = get_nrc_adams_document_file(number)
            if not file.get("snapshot_created"):
                return file
            sha = file["sha256"]
            parsed = parse_pdf(snapshot(number, sha), extract=True)
            texts = [
                ({"representation": "original_pdf", "physical_pdf_page": p["page"]}, p["text"]) for p in parsed["pages"]
            ]
            coverage = {
                "page_cap": 500,
                "character_cap": 1000000,
                "available_pages": parsed["page_count"],
                "scanned_pages": len(parsed["pages"]),
                "scan_complete": parsed["scan_complete"],
                "pages_without_extractable_text": [p["page"] for p in parsed["pages"] if not p["text"].strip()],
                "ocr_performed": False,
                "locator_note": "One-based physical PDF pages; printed labels unknown. Selectable text may be incomplete.",
            }
        candidates, self_count, duplicates = extract(texts, number, source, sha)
        selected = candidates[result_offset : result_offset + max_results]
        if verify_targets:
            lookup_started = time.monotonic()
            for candidate in selected[:10]:
                if time.monotonic() - lookup_started > 90:
                    candidate["target_state"] = "unverified_time_budget"
                    continue
                try:
                    _, target = record(candidate["accession_number"])
                    candidate.update(target_state="resolved", target_metadata=target)
                except SourceError as exc:
                    candidate["target_state"] = exc.state
            for candidate in selected[10:]:
                candidate["target_state"] = "unverified_request_cap"
        more = result_offset + len(selected) < len(candidates)
        no_text = not any(t.strip() for _, t in texts)
        return envelope(
            "no_extractable_text"
            if no_text
            else "partial"
            if not coverage["scan_complete"]
            else "ok"
            if candidates
            else "empty",
            accession_number=number,
            references=selected,
            source=source,
            source_fingerprint=sha,
            coverage=coverage,
            self_mentions_excluded=self_count,
            duplicate_mentions=duplicates,
            candidate_count=len(candidates),
            target_lookup_cap=10,
            recursive_crawling=False,
            reference_meaning="Observed mentions only: not package membership, endorsement, supersession, verified support, or a complete citation graph.",
            pagination={
                "max_results": max_results,
                "result_offset": result_offset,
                "has_more": more,
                "next_result_offset": result_offset + len(selected) if more else None,
                "resume_policy": "Refetch representation and compare source_fingerprint; discard mixed pages if changed.",
            },
        )
    except SourceError as exc:
        return failure(exc)
