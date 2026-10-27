"""Bounded original PDFs, immutable in-process resources, and isolated PDF parsing."""

import hashlib
import json
import subprocess
import sys
import threading
import time
from urllib.parse import urljoin
import requests

from src.apis.adams_api import SourceError, envelope, failure, record
from src.core.normalization import official_url
from src.core.query import accession, integer

LIFETIME_SECONDS = 900
STORE_CAP = 50 * 1024 * 1024
_STORE = {}
_LOCK = threading.Lock()

# A separate interpreter bounds parser time and prevents parser crashes taking down MCP.
PDF_PROGRAM = """
import io,json,sys
from pypdf import PdfReader
reader=PdfReader(io.BytesIO(sys.stdin.buffer.read()),strict=True)
if reader.is_encrypted: raise ValueError('encrypted PDF')
n=len(reader.pages)
mode=sys.argv[1]
pages=[]
remaining=1000000
if mode=='text':
 for i,page in enumerate(reader.pages[:500]):
  text=page.extract_text() or ''
  part=text[:remaining]
  pages.append({'page':i+1,'text':part,'page_text_complete':len(part)==len(text)})
  remaining-=len(part)
  if remaining<=0: break
print(json.dumps({'page_count':n,'pages':pages,'scan_complete':len(pages)==n and all(p['page_text_complete'] for p in pages) if mode=='text' else None}))
"""


def parse_pdf(data, extract=False):
    try:
        proc = subprocess.run(
            [sys.executable, "-c", PDF_PROGRAM, "text" if extract else "count"],
            input=data,
            capture_output=True,
            timeout=15,
        )
        if proc.returncode or len(proc.stdout) > 8 * 1024 * 1024:
            raise ValueError("parser failed")
        return json.loads(proc.stdout)
    except (subprocess.TimeoutExpired, ValueError, OSError):
        raise SourceError(
            "parser_failure", "PDF parser failed, exceeded its time/output cap, or could not safely read this document."
        ) from None


def _purge():
    current = time.monotonic()
    for key, (expires, _) in list(_STORE.items()):
        if expires <= current:
            del _STORE[key]


def snapshot(number, sha):
    number = accession(number)
    if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
        raise ValueError("Invalid SHA-256 resource identifier")
    with _LOCK:
        _purge()
        hit = _STORE.get((number, sha))
        if not hit:
            raise ValueError(
                "Resource expired or unavailable; run get_nrc_adams_document_file again for a new verified retrieval"
            )
        data = hit[1]
    if hashlib.sha256(data).hexdigest() != sha:
        raise ValueError("Resource integrity failure")
    return data


def _download(url, max_bytes):
    current = official_url(url)
    if not current:
        raise SourceError("source_url_rejected", "Record link is absent or outside the official NRC HTTPS allowlist.")
    started = time.monotonic()
    for _ in range(4):
        if time.monotonic() - started > 30:
            raise SourceError("original_unavailable", "Original-file request budget exhausted.")
        try:
            # Never use the API request adapter/session/headers for document hosts.
            with requests.get(
                current,
                headers={"Accept": "application/pdf", "User-Agent": "NEPA-MCP/0.1.6 original-file research"},
                timeout=(5, 12),
                stream=True,
                allow_redirects=False,
            ) as response:
                status = response.status_code
                if status in {301, 302, 303, 307, 308}:
                    current = official_url(urljoin(current, response.headers.get("Location", "")))
                    if not current:
                        raise SourceError(
                            "redirect_rejected", "Original redirect left the official NRC HTTPS allowlist."
                        )
                    continue
                if status in {401, 403}:
                    raise SourceError(
                        "access_challenge", "NRC original-file access was rejected; inspect the official link manually."
                    )
                if status in {404, 503}:
                    raise SourceError(
                        "original_temporarily_unavailable",
                        "Original may lag public indexing or be temporarily unavailable; no snapshot was created.",
                    )
                if status >= 400:
                    raise SourceError("original_unavailable", f"NRC original-file host returned HTTP {status}.")
                if 300 <= status < 400:
                    raise SourceError("redirect_rejected", "Unsupported original-file redirect.")
                mime = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
                if mime not in {"application/pdf", "application/octet-stream"}:
                    raise SourceError(
                        "unsupported_mime",
                        "Original is not an accepted PDF response; HTML/challenge pages are not documents.",
                    )
                declared = response.headers.get("Content-Length")
                if declared and declared.isdigit() and int(declared) > max_bytes:
                    raise SourceError(
                        "file_too_large", "Source-declared file size exceeds max_bytes; no snapshot created."
                    )
                chunks = []
                size = 0
                for chunk in response.iter_content(65536):
                    size += len(chunk)
                    if size > max_bytes:
                        raise SourceError(
                            "file_too_large",
                            "Stream exceeded max_bytes regardless of Content-Length; no snapshot created.",
                        )
                    if time.monotonic() - started > 30:
                        raise SourceError("original_unavailable", "Original-file streaming budget exhausted.")
                    chunks.append(chunk)
                data = b"".join(chunks)
                if not data.startswith(b"%PDF-"):
                    raise SourceError(
                        "invalid_pdf_signature", "Original response lacks a PDF signature; no snapshot created."
                    )
                return data, current, mime, declared
        except requests.RequestException:
            raise SourceError("original_unavailable", "Original-file request failed or timed out.") from None
    raise SourceError("redirect_limit", "Original exceeded three allowed redirects; no snapshot created.")


def get_nrc_adams_document_file(accession_number, max_bytes=10485760):
    number = accession(accession_number)
    integer(max_bytes, "max_bytes", 1, 25 * 1024 * 1024)
    meta = None
    try:
        _, meta = record(number)
        if not meta["official_url"]:
            state = (
                "package_without_original"
                if meta["record_kind"] == "package"
                else "metadata_only"
                if meta["record_kind"] == "legacy"
                else "original_url_absent"
            )
            return envelope(state, document=meta, snapshot_created=False)
        data, final, mime, declared = _download(meta["official_url"], max_bytes)
        parsed = parse_pdf(data)
        sha = hashlib.sha256(data).hexdigest()
        with _LOCK:
            _purge()
            while _STORE and sum(len(v[1]) for v in _STORE.values()) + len(data) > STORE_CAP:
                del _STORE[min(_STORE, key=lambda k: _STORE[k][0])]
            _STORE[(number, sha)] = (time.monotonic() + LIFETIME_SECONDS, data)
        return envelope(
            accession_number=number,
            source_url=meta["official_url"],
            final_url=final,
            mime_type="application/pdf",
            source_mime_type=mime,
            actual_bytes=len(data),
            source_declared_bytes=declared,
            max_bytes=max_bytes,
            sha256=sha,
            page_count=parsed["page_count"],
            snapshot_created=True,
            resource_uri=f"nrc-adams://documents/{number}/{sha}/original",
            resource_lifetime_seconds=LIFETIME_SECONDS,
            resource_store_policy="In-process immutable snapshots; expire after 15 minutes, on memory-budget eviction, or server restart. A new verified retrieval is required after expiry.",
            indexed_text_reviewed=False,
            pdf_text_reviewed=False,
        )
    except SourceError as exc:
        return {
            **failure(exc),
            "source_url": meta.get("official_url") if meta else None,
            "snapshot_created": False,
            "max_bytes": max_bytes,
        }
