"""Bounded indexed-control PDF evidence with explicit title-only and extraction states."""

import hashlib
import json
import re
import subprocess
import sys
import time
import requests
from src.apis.documents_api import index
from src.apis.installations_api import validate_id
from src.core.normalization import output, page, text, source_url

PDF_SCAN = """
import io,json,sys
from pypdf import PdfReader
r=PdfReader(io.BytesIO(sys.stdin.buffer.read()),strict=True)
if r.is_encrypted:raise ValueError('encrypted')
pages=[];remaining=500000
for i,p in enumerate(r.pages[:100]):
 t=p.extract_text() or '';part=t[:remaining];remaining-=len(part)
 pages.append({'page':i+1,'text':part,'complete':len(part)==len(t)})
 if remaining<=0:break
print(json.dumps({'page_count':len(r.pages),'pages':pages}))
"""


def extract_control(url):
    if not source_url(url):
        return {"status": "source_url_rejected", "body_reviewed": False}
    try:
        started = time.monotonic()
        with requests.get(
            url.split("#")[0],
            headers={"Accept": "application/pdf", "User-Agent": "NEPA-MCP/0.1.6 control-evidence research"},
            timeout=(4, 10),
            allow_redirects=False,
            stream=True,
        ) as response:
            if response.status_code != 200:
                return {"status": "unavailable_or_redirect_rejected", "body_reviewed": False}
            if response.headers.get("Content-Type", "").split(";")[0].lower() != "application/pdf":
                return {"status": "unsupported_mime", "body_reviewed": False}
            data = bytearray()
            for chunk in response.iter_content(65536):
                data.extend(chunk)
                if len(data) > 10 * 1024 * 1024:
                    return {"status": "oversized", "byte_cap": 10 * 1024 * 1024, "body_reviewed": False}
                if time.monotonic() - started > 20:
                    return {"status": "time_budget", "body_reviewed": False}
        if not data.startswith(b"%PDF-"):
            return {"status": "invalid_pdf_signature", "body_reviewed": False}
        proc = subprocess.run([sys.executable, "-c", PDF_SCAN], input=bytes(data), capture_output=True, timeout=15)
        if proc.returncode or len(proc.stdout) > 4 * 1024 * 1024:
            return {"status": "parser_failure", "body_reviewed": False}
        parsed = json.loads(proc.stdout)
        evidence = []
        for p in parsed["pages"]:
            for match in re.finditer(
                r"land.use control|institutional control|restrict(?:ion|ed)|record(?:ed|ing)|amendment|addendum|release",
                p["text"],
                re.I,
            ):
                if len(evidence) >= 20:
                    break
                evidence.append(
                    {
                        "physical_pdf_page": p["page"],
                        "printed_page_label": None,
                        "character_range": [match.start(), match.end()],
                        "source_text": p["text"][max(0, match.start() - 100) : match.end() + 160],
                        "restriction_category": "unresolved; exact language requires contextual/legal review",
                    }
                )
        return {
            "status": "text_extracted" if any(p["text"].strip() for p in parsed["pages"]) else "image_only_or_no_text",
            "sha256": hashlib.sha256(data).hexdigest(),
            "actual_bytes": len(data),
            "page_count": parsed["page_count"],
            "scanned_pages": len(parsed["pages"]),
            "scan_complete": len(parsed["pages"]) == parsed["page_count"]
            and all(p["complete"] for p in parsed["pages"]),
            "evidence": evidence,
            "body_reviewed": "bounded selectable-text extraction only",
            "ocr_performed": False,
            "current_legal_effect": "unresolved",
            "instrument_number": None,
            "execution_or_recording_date": None,
        }
    except (requests.RequestException, subprocess.TimeoutExpired, ValueError, OSError):
        return {"status": "extraction_unavailable", "body_reviewed": False}


def get_brac_land_use_controls(installation_id, site_id=None, parcel_id=None, max_results=100, result_offset=0):
    page(max_results, result_offset)
    validate_id(installation_id)
    text(site_id, "site_id", True)
    text(parcel_id, "parcel_id", True)
    if site_id or parcel_id:
        return output(
            [],
            [
                {
                    "url": None,
                    "status": "unsupported",
                    "complete": False,
                    "warnings": ["No verified site/parcel-to-control-instrument crosswalk; filter was not guessed"],
                }
            ],
            ["Use installation-scoped evidence until an explicit published crosswalk is verified."],
            max_results,
            result_offset,
        )
    record, docs, reports = index(installation_id)
    candidates = [d for d in docs if re.search(r"land.use.control|institutional.control|\bLUCIP\b", d["title"], re.I)]
    records = []
    for i, d in enumerate(candidates):
        extraction = (
            extract_control(d["url"])
            if result_offset <= i < result_offset + min(max_results, 3)
            else {"status": "document_request_cap", "body_reviewed": False}
        )
        records.append(
            {
                **d,
                "evidence_type": "control_document_title_candidate",
                "instrument_effect": "unresolved; signed/recorded filename is not proof",
                "affected_entity": "installation research scope; individual parcel/site effect unresolved",
                "extraction": extraction,
            }
        )
    return output(
        records,
        reports,
        [
            "Control index and bounded selectable-text evidence only; not a deed/title registry or verification of current restriction effect. Up to three indexed PDFs, 10 MiB / 100 pages / 500,000 characters each; no OCR."
        ],
        max_results,
        result_offset,
    )
