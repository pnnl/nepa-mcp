"""Metadata is separate from indexed text, original files, and resolved evidence."""

import hashlib
import json
from datetime import UTC, datetime
from urllib.parse import urlsplit
from src.core.query import accession


def now():
    return datetime.now(UTC).isoformat()


def fingerprint(value):
    return hashlib.sha256(
        value if isinstance(value, bytes) else json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def official_url(value):
    if not isinstance(value, str):
        return None
    try:
        p = urlsplit(value)
    except ValueError:
        return None
    try:
        if (
            p.scheme == "https"
            and p.hostname in {"www.nrc.gov", "nrc.gov", "adams.nrc.gov", "adams-search.nrc.gov"}
            and p.port in {None, 443}
            and not p.username
            and not p.password
            and not p.fragment
        ):
            return value
    except ValueError:
        return None
    return None


def metadata(doc):
    if not isinstance(doc, dict):
        raise ValueError("Document is not an object")
    acc = accession(doc.get("AccessionNumber"))
    flags = {k: doc.get(k) for k in ("IsPackage", "IsLegacy", "ItemType")}
    package = doc.get("IsPackage") in {"Yes", True}
    legacy = doc.get("IsLegacy") in {"Yes", True}
    warnings = []
    for field in ("DocketNumber", "DocumentType", "AuthorName", "AuthorAffiliation"):
        if doc.get(field) is not None and not isinstance(doc[field], list):
            warnings.append(f"Unexpected {field} representation; preserved raw")
    return {
        "accession_number": acc,
        "title": doc.get("DocumentTitle") or doc.get("Name"),
        "record_kind": "package" if package else "legacy" if legacy else "document",
        "source_flags": flags,
        "document_date": doc.get("DocumentDate"),
        "date_added": doc.get("DateAdded"),
        "date_added_timestamp": doc.get("DateAddedTimestamp"),
        "dockets": doc.get("DocketNumber"),
        "document_types": doc.get("DocumentType"),
        "authors": doc.get("AuthorName"),
        "author_affiliations": doc.get("AuthorAffiliation"),
        "availability": doc.get("Availability"),
        "official_url": official_url(doc.get("Url")),
        "source_url_rejected": bool(doc.get("Url")) and not official_url(doc.get("Url")),
        "estimated_page_count": doc.get("EstimatedPageCount"),
        "package_membership_present": "DocumentsFiledInPackage" in doc,
        "packages_filed_in": doc.get("PackagesFiledIn"),
        "content_field_present": "content" in doc,
        "content_availability": "absent"
        if doc.get("content") is None
        else "present"
        if isinstance(doc.get("content"), str)
        else "unsupported_representation",
        "warnings": warnings,
    }
