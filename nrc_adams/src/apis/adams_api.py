"""Official NRC subscription API only; credential-dependent calls fail without blocking discovery."""

import base64
import binascii
import json
import os
import time
from urllib.parse import quote
import requests

from src.core import query
from src.core.normalization import fingerprint, metadata, now

API = "https://adams-api.nrc.gov/aps/api/search"
API_CAP = 8 * 1024 * 1024
_WINDOWS = {}
CONTRACT = "APS API guide v1.0; authenticated contract verification pending"


class SourceError(Exception):
    def __init__(self, state, message, retry_after=None):
        self.state = state
        self.message = message
        self.retry_after = retry_after
        super().__init__(message)


def envelope(state="ok", **values):
    return {
        "status": state,
        "adapter": "official_api",
        "contract": CONTRACT,
        "authenticated_contract_verified": False,
        "retrieved_at": now(),
        "coverage_note": "Publicly discoverable NRC records only. Search presence is not approval, NEPA completion, or current operating authority. Metadata, indexed text, originals, package members, and references are separate evidence representations.",
        **values,
    }


def failure(exc):
    return envelope(exc.state, error=exc.message, retry_after=exc.retry_after)


def _request(method, path="", body=None):
    key = os.environ.get("NRC_ADAMS_API_KEY")
    if not key:
        raise SourceError(
            "missing_configuration",
            "Configure NRC_ADAMS_API_KEY in the private NEPA-MCP credentials.env file (nepa-mcp configure credentials) or process environment; register at https://adams-api-developer.nrc.gov/. Restart the server after changes. Do not paste keys in chat or MCP client configs.",
        )
    # No caller URL and no redirects: this header can reach only the exact API origin.
    for attempt in range(2):
        try:
            with requests.request(
                method,
                API + path,
                json=body,
                headers={
                    "Ocp-Apim-Subscription-Key": key,
                    "Accept": "application/json",
                    "User-Agent": "NEPA-MCP/0.1.6 NRC research",
                },
                timeout=(5, 15),
                allow_redirects=False,
                stream=True,
            ) as response:
                status = response.status_code
                if status in {401, 403}:
                    raise SourceError(
                        "authorization_error",
                        "NRC rejected the subscription; verify its activation and API access in the NRC developer portal.",
                    )
                if status == 429:
                    retry = response.headers.get("Retry-After")
                    # Respect longer intervals by returning to caller instead of retrying early.
                    if attempt == 0 and retry and retry.isdigit() and int(retry) <= 2:
                        time.sleep(int(retry))
                        continue
                    raise SourceError(
                        "rate_limited",
                        "NRC subscription quota/rate limit reached; retry after the publisher interval.",
                        retry,
                    )
                if status == 404:
                    raise SourceError(
                        "not_found",
                        "No matching public record was returned; nonpublic records are outside this lookup.",
                    )
                if 300 <= status < 400:
                    raise SourceError("redirect_rejected", "API redirect refused to protect subscription credentials.")
                if status >= 400:
                    raise SourceError("upstream_unavailable", f"NRC API returned HTTP {status}.")
                chunks = []
                size = 0
                for chunk in response.iter_content(65536):
                    size += len(chunk)
                    if size > API_CAP:
                        raise SourceError(
                            "response_too_large",
                            "API response exceeded the 8 MiB byte cap; no partial JSON was interpreted.",
                        )
                    chunks.append(chunk)
                try:
                    payload = json.loads(b"".join(chunks))
                except (ValueError, UnicodeDecodeError):
                    raise SourceError("schema_error", "NRC API returned malformed JSON.") from None
                if not isinstance(payload, dict):
                    raise SourceError("schema_error", "NRC API response must be an object.")
                return payload
        except requests.RequestException:
            # Never expose exception strings, response bodies, or request headers.
            if attempt:
                raise SourceError("upstream_unavailable", "NRC API request failed or timed out.") from None
            time.sleep(0.25)
    raise SourceError("upstream_unavailable", "NRC API request did not complete.")


def record(accession_number):
    number = query.accession(accession_number)
    payload = _request("GET", "/" + quote(number, safe=""))
    doc = payload.get("document")
    if not isinstance(doc, dict):
        raise SourceError("schema_error", "NRC record response is missing the documented document object.")
    try:
        normalized = metadata(doc)
    except (ValueError, TypeError):
        raise SourceError("schema_error", "NRC record has invalid identity/metadata.") from None
    if normalized["accession_number"] != number:
        raise SourceError("schema_error", "NRC returned a different accession; record was not attributed.")
    return doc, normalized


def get_nrc_adams_document(accession_number):
    number = query.accession(accession_number)
    try:
        _, doc = record(number)
        return envelope(document=doc, next_step="get_nrc_adams_package" if doc["record_kind"] == "package" else None)
    except SourceError as exc:
        return failure(exc)


def search_nrc_adams_documents(
    query_text="",
    docket_number=None,
    document_type=None,
    date_basis="document_date",
    date_from=None,
    date_to=None,
    library="both",
    sort_by="document_date",
    sort_direction="descending",
    max_results=50,
    result_offset=0,
):
    body = query.build(
        query_text,
        docket_number,
        document_type,
        date_basis,
        date_from,
        date_to,
        library,
        sort_by,
        sort_direction,
        max_results,
        result_offset,
    )
    try:
        payload = _request("POST", body=body)
        rows = payload.get("results")
        total = payload.get("count")
        if not isinstance(rows, list) or type(total) is not int or total < 0:
            raise SourceError("schema_error", "Search response lacks documented results/count fields.")
        # max_results is local output size; no invented page/pageSize parameter.
        docs = []
        seen = set()
        warnings = []
        for row in rows:
            try:
                d = metadata(row["document"])
            except (TypeError, KeyError, ValueError):
                warnings.append("Malformed result identity/metadata")
                continue
            if d["accession_number"] in seen:
                warnings.append("Repeated accession in source window")
                continue
            seen.add(d["accession_number"])
            docs.append(d)
        if len(rows) > 1000:
            raise SourceError("schema_error", "Source window exceeded the 1,000-record safety cap.")
        window_key = fingerprint({key: value for key, value in body.items() if key != "skip"})
        window_ids = [d["accession_number"] for d in docs]
        previous = _WINDOWS.get(window_key)
        if previous and previous[0] != result_offset and window_ids and previous[1] == window_ids:
            warnings.append("Source repeated the same accession window at a different skip; continuation stopped")
        if len(_WINDOWS) >= 128:
            _WINDOWS.clear()
        _WINDOWS[window_key] = (result_offset, window_ids)
        selected = docs[:max_results]
        # If filtering malformed rows removed a hit, do not promise gap-free continuation.
        more = result_offset + len(rows) < total or len(docs) > max_results
        if not rows and result_offset < total:
            warnings.append("Source reports remaining records but returned no window")
        next_offset = result_offset + len(selected) if selected and more and not warnings else None
        return envelope(
            "partial" if warnings else "ok" if selected else "empty",
            records=selected,
            query=body,
            date_boundary_semantics="Source ge/le comparisons on YYYY-MM-DD; timestamps retain source timezone ambiguity.",
            source_total=total,
            total_scope="Source search scope matching the submitted filters/library",
            source_window_count=len(rows),
            warnings=warnings,
            window_fingerprint=fingerprint([d["accession_number"] for d in docs]),
            pagination={
                "max_results": max_results,
                "result_offset": result_offset,
                "returned_count": len(selected),
                "has_more": more if not warnings else None,
                "next_result_offset": next_offset,
                "request_count": 1,
                "request_cap": 1,
                "snapshot_guaranteed": False,
            },
        )
    except SourceError as exc:
        return failure(exc)


def indexed(doc):
    value = doc.get("content")
    if value is None:
        raise SourceError("text_unavailable", "The API record has no indexed text; it may be metadata-only.")
    if not isinstance(value, str):
        raise SourceError("unsupported_encoding", "Indexed content has an unsupported representation.")
    encoding = doc.get("contentEncoding", "plain_text")
    if encoding in {"base64", "Base64"}:
        try:
            value = base64.b64decode(value, validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError):
            raise SourceError("unsupported_encoding", "Explicit base64 indexed content was invalid.") from None
    elif encoding not in {"plain_text", "text", "utf-8", None}:
        raise SourceError("unsupported_encoding", "The source declared an unsupported content encoding.")
    return value


def get_nrc_adams_document_text(accession_number, character_offset=0, max_characters=12000):
    number = query.accession(accession_number)
    query.integer(character_offset, "character_offset", 0, 10000000)
    query.integer(max_characters, "max_characters", 1, 20000)
    try:
        doc, _ = record(number)
        value = indexed(doc)
        chunk = value[character_offset : character_offset + max_characters]
        more = character_offset + len(chunk) < len(value)
        return envelope(
            "ok" if value else "empty_text",
            accession_number=number,
            text=chunk,
            source="API indexed text; characters are not PDF pages",
            content_fingerprint=fingerprint(value.encode()),
            source_text_characters=len(value),
            source_completeness="unknown",
            source_truncated=doc.get("contentTruncated"),
            character_offset=character_offset,
            returned_characters=len(chunk),
            has_more=more,
            next_character_offset=character_offset + len(chunk) if more else None,
            api_byte_cap=API_CAP,
            encoding_basis=doc.get(
                "contentEncoding", "plain text per guide; authenticated representation check pending"
            ),
        )
    except SourceError as exc:
        return failure(exc)


def get_nrc_adams_package(accession_number, max_results=100, result_offset=0):
    number = query.accession(accession_number)
    query.page(max_results, result_offset)
    try:
        doc, meta = record(number)
        if meta["record_kind"] != "package":
            return envelope("not_a_package", document=meta)
        members = doc.get("DocumentsFiledInPackage")
        if not isinstance(members, list):
            return envelope(
                "membership_unavailable",
                document=meta,
                membership_complete=False,
                error="Explicit outgoing package membership was absent or malformed; this is not an empty-package finding.",
            )
        identifiers = []
        unresolved = []
        for member in members:
            try:
                identifier = query.accession(member if isinstance(member, str) else member.get("AccessionNumber"))
            except (ValueError, AttributeError):
                unresolved.append({"state": "unverified_member_representation"})
                continue
            if identifier not in identifiers:
                identifiers.append(identifier)
        selected = identifiers[result_offset : result_offset + max_results]
        records = []
        lookup_started = time.monotonic()
        for identifier in selected[:10]:
            if time.monotonic() - lookup_started > 90:
                records.append({"accession_number": identifier, "state": "unresolved_time_budget"})
                continue
            if identifier == number:
                records.append({"accession_number": identifier, "state": "cycle_to_self"})
                continue
            try:
                _, member = record(identifier)
                records.append({"state": "resolved", "document": member})
            except SourceError as exc:
                records.append({"accession_number": identifier, "state": exc.state})
        records.extend(
            {"accession_number": identifier, "state": "unresolved_request_cap"} for identifier in selected[10:]
        )
        return envelope(
            "partial" if unresolved or len(selected) > 10 or any(r["state"] != "resolved" for r in records) else "ok",
            document=meta,
            members=records,
            unresolved=unresolved,
            source_member_count=len(members),
            unique_member_count=len(identifiers),
            membership_complete="unknown; nonempty authenticated contract fixture pending",
            membership_basis="DocumentsFiledInPackage only; PackagesFiledIn remains parent metadata",
            pagination={
                "max_results": max_results,
                "result_offset": result_offset,
                "next_result_offset": result_offset + len(selected)
                if result_offset + len(selected) < len(identifiers)
                else None,
                "has_more": result_offset + len(selected) < len(identifiers),
                "lookup_cap": 10,
                "recursive": False,
            },
        )
    except SourceError as exc:
        return failure(exc)
