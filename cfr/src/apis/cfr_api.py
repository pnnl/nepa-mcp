"""
Federal Code of Federal Regulations (CFR) API Wrapper

This module provides functions to query the eCFR API for regulatory text
retrieval, version tracking, and change monitoring.
Essential for NEPA/EIS regulatory citation and compliance documentation.

API Documentation:
- eCFR: https://www.ecfr.gov/developers/documentation/api/v1
"""

import re
import time
import logging
import hashlib
import json
from datetime import datetime, timedelta
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import requests

from src.apis.cfr_constants import (
    ECFR_ENDPOINTS,
    FEDERAL_REGISTER_ENDPOINTS,
    REQUEST_TIMEOUT_SECONDS,
    HTTP_MAX_RETRIES as _HTTP_MAX_RETRIES,
    HTTP_BACKOFF_BASE_SECONDS as _HTTP_BACKOFF_BASE,
    DEFAULT_CACHE_DIR,
    CACHE_TTL,
    get_ecfr_versions_url,
    get_ecfr_ancestry_url,
)

logger = logging.getLogger(__name__)

# =============================================================================
# Exceptions
# =============================================================================


class CFRAPIError(Exception):
    """Base exception for CFR API errors."""

    pass


class CFRCitationError(CFRAPIError):
    """Invalid CFR citation format."""

    pass


class CFRNotFoundError(CFRAPIError):
    """Requested CFR content not found."""

    pass


# =============================================================================
# Citation Parsing
# =============================================================================


@dataclass
class CFRCitation:
    """Parsed CFR citation components.

    `paragraph_path` holds an arbitrary tail of paragraph levels
    (e.g. ["d", "5", "iv", "C"] for 262.34(d)(5)(iv)(C)). Case is preserved
    so roman-numeral levels (iv) survive distinct from upper-case (IV).

    `paragraph` is kept for backward compatibility; it joins paragraph_path
    with parentheses (e.g. "d(5)(iv)(C)") when present.

    `part` is optional to allow whole-title citations like "title 50" used by
    cfr-history.
    """

    title: int
    part: Optional[int] = None
    section: Optional[str] = None
    subpart: Optional[str] = None
    paragraph: Optional[str] = None
    paragraph_path: List[str] = None
    raw: str = ""

    def __post_init__(self):
        if self.paragraph_path is None:
            self.paragraph_path = []

    def to_display(self) -> str:
        """Format for display (e.g., '43 CFR 46.205(c)(1)')."""
        if self.section:
            base = f"{self.title} CFR {self.part}.{self.section}"
            if self.paragraph_path:
                base += "".join(f"({p})" for p in self.paragraph_path)
            return base
        if self.part is not None:
            return f"{self.title} CFR Part {self.part}"
        return f"Title {self.title} CFR"


def parse_cfr_citation(citation: str) -> CFRCitation:
    """
    Parse a CFR citation string into structured components.

    Supports formats:
    - "43 CFR 46.105"
    - "43 CFR § 46.215"
    - "43 CFR § 46.215(a)"
    - "43 C.F.R. Part 46"
    - "40 C.F.R. § 261.4(a)(20)(ii)(B)(1)"   # arbitrary depth
    - "Title 43, Part 46, Section 215"
    - "title 50"                              # whole title (no part)
    - "title 43 part 46"

    Paragraph levels are case-preserved in `paragraph_path`. The standalone
    `paragraph` field is set for backward compat to the joined string
    (e.g. "d(5)(iv)(C)").

    Raises:
        CFRCitationError: If citation cannot be parsed.
    """
    original = citation
    # Normalize whitespace and the section symbol; do NOT uppercase yet, we
    # need original case for paragraph path (roman vs upper).
    norm = citation.strip()
    norm = re.sub(r"[§]", "", norm)
    norm = re.sub(r"C\.F\.R\.", "CFR", norm, flags=re.IGNORECASE)
    norm = re.sub(r"\s+", " ", norm)

    # ---- Pattern A: standard "43 CFR 46.205(c)(1)..." ----
    # Match the "title CFR (Part )?part(.section)?" head case-insensitively.
    head = re.match(
        r"\s*(\d+)\s*CFR\s*(?:PART\s*)?(\d+)(?:\.(\d+))?",
        norm,
        re.IGNORECASE,
    )
    if head:
        title = int(head.group(1))
        part = int(head.group(2))
        section = head.group(3)
        # Paragraph tail: everything after the head, find all (token) groups.
        tail = norm[head.end() :]
        paragraph_path = [m.group(1) for m in re.finditer(r"\(([^)]+)\)", tail)]
        paragraph = "".join(f"({p})" for p in paragraph_path).lstrip("(").rstrip(")") if paragraph_path else None
        # Re-join with explicit parens for the legacy field
        if paragraph_path:
            paragraph = paragraph_path[0]
            for p in paragraph_path[1:]:
                paragraph += f"({p})"
        return CFRCitation(
            title=title,
            part=part,
            section=section,
            paragraph=paragraph,
            paragraph_path=paragraph_path,
            raw=original,
        )

    # ---- Pattern B: verbose "Title 43, Part 46, Section 215" or "title 50" ----
    title_only = re.match(r"\s*TITLE\s*(\d+)\s*$", norm, re.IGNORECASE)
    if title_only:
        return CFRCitation(title=int(title_only.group(1)), raw=original)

    verbose = re.search(
        r"TITLE\s*(\d+)(?:.*?PART\s*(\d+))?(?:.*?SECTION\s*(\d+))?",
        norm,
        re.IGNORECASE,
    )
    if verbose and verbose.group(1):
        return CFRCitation(
            title=int(verbose.group(1)),
            part=int(verbose.group(2)) if verbose.group(2) else None,
            section=verbose.group(3),
            raw=original,
        )

    raise CFRCitationError(
        f"Cannot parse CFR citation: '{citation}'. "
        "Expected format like '43 CFR 46.105', '43 CFR Part 46', "
        "'40 CFR 262.34(d)(5)(iv)(C)', or 'title 50'."
    )


# =============================================================================
# Caching
# =============================================================================


CACHE_DIR = Path(DEFAULT_CACHE_DIR) / ".cache"


def _get_cache_key(endpoint: str, params: dict) -> str:
    """Generate cache key from endpoint and parameters."""
    param_str = json.dumps(params, sort_keys=True)
    return hashlib.md5(f"{endpoint}:{param_str}".encode()).hexdigest()


def _get_cached_response(cache_key: str, ttl_seconds: int = None) -> Optional[dict]:
    """Retrieve cached API response if valid.

    Args:
        cache_key: The cache key for the response
        ttl_seconds: Time-to-live in seconds (default: 24 hours)
    """
    if ttl_seconds is None:
        ttl_seconds = CACHE_TTL["current_content"]

    cache_file = CACHE_DIR / f"{cache_key}.json"
    if not cache_file.exists():
        return None

    try:
        with open(cache_file, "r") as f:
            cached = json.load(f)

        cached_time = datetime.fromisoformat(cached["timestamp"])
        ttl = timedelta(seconds=ttl_seconds)

        if datetime.now() - cached_time > ttl:
            return None

        logger.debug(f"Cache hit for {cache_key}")
        return cached["data"]

    except (json.JSONDecodeError, KeyError):
        return None


def _cache_response(cache_key: str, data: dict) -> None:
    """Cache API response.

    Caching is best-effort: a read-only or non-writable cache directory (as on
    some deployment runtimes) must never break tool execution, so directory
    creation and the write are both guarded.
    """
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_file = CACHE_DIR / f"{cache_key}.json"
        with open(cache_file, "w") as f:
            json.dump({"timestamp": datetime.now().isoformat(), "data": data}, f)
    except OSError as e:
        logger.warning(f"Failed to cache response: {e}")


def _fallback_ecfr_current_date() -> str:
    """Best-effort local fallback when the Titles API is unavailable."""
    return (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")


def get_current_ecfr_date(title: int = None) -> str:
    """Return the latest date eCFR says is available.

    The eCFR date-addressed endpoints do not necessarily have data for the
    local machine's yesterday, especially in test environments where the clock
    can be ahead of eCFR publication. The Titles API exposes the authoritative
    `up_to_date_as_of` value; use that for "current" reads.
    """
    try:
        titles_status = get_ecfr_titles() or {}
        titles = titles_status.get("titles", [])

        if title is not None:
            for entry in titles:
                if entry.get("number") == title and entry.get("up_to_date_as_of"):
                    return entry["up_to_date_as_of"]

        available_dates = [entry.get("up_to_date_as_of") for entry in titles if entry.get("up_to_date_as_of")]
        if available_dates:
            return max(available_dates)
    except Exception as e:
        logger.warning(f"Failed to resolve current eCFR date from Titles API: {e}")

    return _fallback_ecfr_current_date()


def _cached_get(
    url: str,
    params: dict = None,
    ttl: int = None,
    extract_key: str = None,
    not_found_error: str = None,
    fallback=None,
    error_context: str = "API",
):
    """Cached HTTP GET with consistent error handling.

    Args:
        url: The URL to fetch.
        params: Query parameters.
        ttl: Cache TTL in seconds (default: current_content TTL).
        extract_key: Key to extract from JSON response (e.g. 'content_versions').
                     If None, returns the full parsed JSON.
        not_found_error: If set, raise CFRNotFoundError with this message on 404.
                         If None, return *fallback* on 404.
        fallback: Value to return on 404 (when not_found_error is None) or on
                  non-HTTP request failures when the caller prefers graceful degradation.
        error_context: Label for error messages (e.g. "eCFR Structure").

    Returns:
        Parsed JSON (or extracted sub-key), or *fallback* on soft errors.
    """
    if params is None:
        params = {}
    if ttl is None:
        ttl = CACHE_TTL["current_content"]

    cache_key = _get_cache_key(url, params)
    cached = _get_cached_response(cache_key, ttl_seconds=ttl)
    if cached is not None:
        return cached

    # Retry transient failures (429/5xx, empty bodies, network blips) with
    # exponential backoff. eCFR and the Federal Register API both rate-limit
    # bursts; a single attempt returns empty/non-JSON, which would silently
    # corrupt the citation bisection below.
    last_exc = None
    for attempt in range(_HTTP_MAX_RETRIES):
        try:
            response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)

            if response.status_code == 404:
                if not_found_error:
                    raise CFRNotFoundError(not_found_error)
                return fallback if fallback is not None else []

            if response.status_code == 429 or response.status_code >= 500:
                last_exc = CFRAPIError(f"{error_context} transient HTTP {response.status_code}")
                time.sleep(_HTTP_BACKOFF_BASE * (2**attempt))
                continue

            response.raise_for_status()

            body = response.text
            if not body or not body.strip():
                # Rate limiter sometimes returns an empty 200 body.
                last_exc = CFRAPIError(f"{error_context} returned an empty body")
                time.sleep(_HTTP_BACKOFF_BASE * (2**attempt))
                continue

            data = response.json()
            result = data.get(extract_key, []) if extract_key else data
            _cache_response(cache_key, result)
            return result

        except CFRNotFoundError:
            raise
        except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
            last_exc = e
            time.sleep(_HTTP_BACKOFF_BASE * (2**attempt))

    # All retries exhausted.
    if fallback is not None:
        logger.warning(f"{error_context} failed after retries: {last_exc}")
        return fallback
    raise CFRAPIError(f"{error_context} request failed: {last_exc}")


# =============================================================================
# eCFR API (Current Regulations)
# =============================================================================


def get_ecfr_title_structure(title: int, date: str = None) -> Dict:
    """
    Get the structure (table of contents) for a CFR title from eCFR.

    Args:
        title: CFR title number
        date: Date in YYYY-MM-DD format (None for current)

    Returns:
        Title structure with chapters, subchapters, parts, sections
    """
    current_read = date is None
    if date is None:
        date = get_current_ecfr_date(title)

    url = f"{ECFR_ENDPOINTS['structure']}/{date}/title-{title}.json"
    ttl = CACHE_TTL["structure"] if current_read else CACHE_TTL["historical_content"]

    return _cached_get(
        url,
        params={"date": date},
        ttl=ttl,
        not_found_error=f"CFR Title {title} not found in eCFR for date {date}",
        error_context="eCFR Structure",
    )


def find_part_in_structure(structure: dict, target_part: int) -> dict | None:
    """
    Find a specific part in the title structure.

    Args:
        structure: Title structure from eCFR
        target_part: Part number to find

    Returns:
        Part data or None if not found
    """
    if not structure:
        return None
    if structure.get("type") == "part":
        identifier = str(structure.get("identifier", ""))
        match = re.search(r"\bPart\s+(\d+)\b|\b(\d+)\b", identifier, flags=re.IGNORECASE)
        if match and int(match.group(1) or match.group(2)) == int(target_part):
            return structure
    for child in structure.get("children", []):
        result = find_part_in_structure(child, target_part)
        if result:
            return result
    return None


def get_ecfr_section_content(citation: CFRCitation, date: str = None) -> str:
    """
    Get the HTML content of a specific CFR section from eCFR renderer API.

    Args:
        citation: Parsed CFR citation
        date: Date in YYYY-MM-DD format. None uses the title-specific
            `up_to_date_as_of` value from the eCFR Titles API. Callers that
            need stable historical text (e.g. NEPA regulations removed in
            2025) should pass an explicit date.

    Returns:
        HTML content of the section
    """
    if date is None:
        date = get_current_ecfr_date(citation.title)

    section_id = f"{citation.part}.{citation.section}" if citation.section else str(citation.part)
    url = f"{ECFR_ENDPOINTS['content']}/{date}/title-{citation.title}"
    params = {"section": section_id}

    try:
        response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        return response.text

    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            raise CFRNotFoundError(f"Section {citation.to_display()} not found in eCFR for date {date}")
        raise CFRAPIError(f"eCFR API error: {e}")
    except requests.exceptions.RequestException as e:
        raise CFRAPIError(f"eCFR request failed: {e}")


def _parse_section_html(html: str) -> Optional[Dict]:
    """
    Parse eCFR renderer HTML into a hierarchical paragraph tree.

    The renderer API returns nested <div id="p-328.3(a)(1)(i)"> containers
    with <p class="indent-N" data-title="328.3(a)(1)(i)"> elements inside.
    This function preserves that hierarchy as a JSON-serializable tree.

    Returns:
        Dict with 'hierarchy_metadata', 'heading', 'preamble',
        'paragraphs' (recursive tree with cross_references per node),
        'citation_line', 'fr_citations', and 'source_and_authority',
        or None if parsing fails.
    """
    try:
        from html.parser import HTMLParser
        import json as _json
        import re as _re

        class _SectionParser(HTMLParser):
            """Event-driven HTML parser that builds a paragraph tree."""

            def __init__(self):
                super().__init__()
                # Stack of (div_id, node_dict) for open paragraph divs
                self._stack: list = []
                # Top-level results
                self.heading = ""
                self.hierarchy_metadata: Optional[Dict] = None
                self.preamble_parts: list = []
                self.top_paragraphs: list = []
                self.citation_line = ""
                self.fr_citations: list = []
                self.source_and_authority: Optional[Dict] = None
                # Transient state
                self._in_heading = False
                self._in_citation = False
                self._current_p_class = ""
                self._current_p_data_title = ""
                self._collecting_p = False
                self._text_buf: list = []
                self._in_em_heading = False
                self._defined_term_buf: list = []
                # Track whether we've seen any paragraph divs yet
                self._seen_para_div = False
                # Link tracking
                self._in_link = False
                self._current_link_href = ""
                self._current_link_type = ""  # "cfr" or "fr-reference"
                self._current_link_data_ref = ""
                self._link_text_buf: list = []
                self._current_p_refs: list = []
                # Script tracking for source-and-authority JSON
                self._in_script = False
                self._script_id = ""
                self._script_buf: list = []

            def handle_starttag(self, tag, attrs):
                attrs_d = dict(attrs)

                if tag == "h4":
                    self._in_heading = True
                    self._text_buf = []
                    # Capture hierarchy metadata from data attribute
                    meta_json = attrs_d.get("data-hierarchy-metadata", "")
                    if meta_json:
                        try:
                            self.hierarchy_metadata = _json.loads(meta_json)
                        except (ValueError, TypeError):
                            pass

                elif tag == "div":
                    div_id = attrs_d.get("id", "")
                    if div_id.startswith("p-"):
                        self._seen_para_div = True
                        node = {
                            "citation": "",
                            "depth": 0,
                            "text": "",
                            "children": [],
                        }
                        self._stack.append((div_id, node))

                elif tag == "p":
                    cls = attrs_d.get("class", "")
                    data_title = attrs_d.get("data-title", "")
                    self._current_p_class = cls
                    self._current_p_data_title = data_title
                    self._collecting_p = True
                    self._text_buf = []
                    self._current_p_refs = []

                    if "citation" in cls:
                        self._in_citation = True
                        self._text_buf = []

                elif tag == "a":
                    href = attrs_d.get("href", "")
                    cls = attrs_d.get("class", "")
                    self._in_link = True
                    self._current_link_href = href
                    self._link_text_buf = []
                    self._current_link_data_ref = attrs_d.get("data-reference", "")
                    if "fr-reference" in cls:
                        self._current_link_type = "fr-reference"
                    elif "cfr" in cls:
                        self._current_link_type = "cfr"
                    else:
                        self._current_link_type = "other"

                elif tag == "em":
                    if attrs_d.get("class", "") == "paragraph-heading":
                        self._in_em_heading = True
                        self._defined_term_buf = []

                elif tag == "script":
                    if attrs_d.get("id", "") == "source-and-authority-data":
                        self._in_script = True
                        self._script_id = "source-and-authority-data"
                        self._script_buf = []

            def handle_endtag(self, tag):
                if tag == "h4":
                    self._in_heading = False
                    candidate = "".join(self._text_buf).strip()
                    # Keep the first real section heading (starts with "§")
                    # — don't let later <h4>s like "Editorial Note:" replace it.
                    if not self.heading.startswith("§"):
                        self.heading = candidate
                    self._text_buf = []

                elif tag == "a":
                    if self._in_link:
                        link_text = "".join(self._link_text_buf).strip()
                        ref = {
                            "text": link_text,
                            "href": self._current_link_href,
                            "type": self._current_link_type,
                        }
                        if self._current_link_data_ref:
                            ref["data_reference"] = self._current_link_data_ref

                        if self._in_citation:
                            # FR citation links in the citation <p>
                            if self._current_link_type == "fr-reference":
                                self.fr_citations.append(ref)
                        elif self._collecting_p:
                            # Cross-references inside paragraph text
                            self._current_p_refs.append(ref)

                        self._in_link = False
                        self._current_link_href = ""
                        self._current_link_type = ""
                        self._current_link_data_ref = ""
                        self._link_text_buf = []

                elif tag == "p":
                    if self._in_citation:
                        self._in_citation = False
                        self.citation_line = "".join(self._text_buf).strip()
                        self._text_buf = []
                        self._collecting_p = False
                        return

                    if self._collecting_p:
                        p_text = "".join(self._text_buf).strip()
                        p_text = _re.sub(r"\s+", " ", p_text)

                        if self._stack:
                            # Attach text to the current stack node
                            _, node = self._stack[-1]
                            node["text"] = p_text
                            node["citation"] = self._current_p_data_title

                            # Parse depth from class like "indent-2"
                            depth_match = _re.search(r"indent-(\d+)", self._current_p_class)
                            if depth_match:
                                node["depth"] = int(depth_match.group(1))

                            if self._defined_term_buf:
                                node["defined_term"] = "".join(self._defined_term_buf).strip()
                                self._defined_term_buf = []

                            if self._current_p_refs:
                                node["cross_references"] = self._current_p_refs

                        elif not self._seen_para_div:
                            # Preamble text (before any paragraph divs)
                            self.preamble_parts.append(p_text)

                        self._collecting_p = False
                        self._text_buf = []
                        self._current_p_refs = []

                elif tag == "em":
                    if self._in_em_heading:
                        self._in_em_heading = False

                elif tag == "div":
                    if self._stack:
                        div_id, node = self._stack[-1]
                        if div_id.startswith("p-"):
                            self._stack.pop()
                            if self._stack:
                                # Attach as child of parent div
                                _, parent = self._stack[-1]
                                parent["children"].append(node)
                            else:
                                # Top-level paragraph
                                self.top_paragraphs.append(node)

                elif tag == "script":
                    if self._in_script:
                        raw = "".join(self._script_buf).strip()
                        if raw:
                            try:
                                self.source_and_authority = _json.loads(raw)
                            except (ValueError, TypeError):
                                pass
                        self._in_script = False
                        self._script_id = ""
                        self._script_buf = []

            def handle_data(self, data):
                if self._in_script:
                    self._script_buf.append(data)
                    return
                if self._in_link:
                    self._link_text_buf.append(data)
                if self._in_heading or self._collecting_p or self._in_citation:
                    self._text_buf.append(data)
                if self._in_em_heading:
                    self._defined_term_buf.append(data)

        parser = _SectionParser()
        parser.feed(html)

        # Clean up empty children lists and empty cross_references
        def _clean(node):
            if not node.get("children"):
                node.pop("children", None)
            else:
                for child in node["children"]:
                    _clean(child)
            return node

        result = {
            "heading": parser.heading,
            "preamble": " ".join(parser.preamble_parts),
            "paragraphs": [_clean(p) for p in parser.top_paragraphs],
            "citation_line": parser.citation_line,
        }

        if parser.hierarchy_metadata:
            result["hierarchy_metadata"] = parser.hierarchy_metadata
        if parser.fr_citations:
            result["fr_citations"] = parser.fr_citations
        if parser.source_and_authority:
            result["source_and_authority"] = parser.source_and_authority

        return result

    except Exception as e:
        logger.warning(f"Failed to parse section HTML into structure: {e}")
        return None


# =============================================================================
# eCFR Titles API
# =============================================================================


def get_ecfr_titles() -> Dict:
    """
    Get live status of all CFR titles from eCFR Titles API.

    Returns:
        Dict with title metadata including latest_amended_on dates
    """
    return _cached_get(
        ECFR_ENDPOINTS["titles"],
        ttl=CACHE_TTL["titles"],
        fallback={"titles": []},
        error_context="eCFR Titles",
    )


# =============================================================================
# eCFR Versions API (Amendment Tracking)
# =============================================================================


def get_section_versions(
    citation: CFRCitation,
    start_date: str,
    end_date: str = None,
    substantive_only: bool = False,
) -> List[Dict]:
    """
    Query eCFR Versions API for section amendment history.

    Each event preserves the `substantive: bool` flag from eCFR (True = real
    text change, False = editorial/typo). When `substantive_only=True`,
    editorial events are filtered out.

    Args:
        citation: Parsed CFR citation. If part is None, queries the entire title.
        start_date: Start date in YYYY-MM-DD format.
        end_date: End date in YYYY-MM-DD format (None for today).
        substantive_only: If True, return only events with substantive=True.

    Returns:
        List of version records with amendment dates and `substantive` flag.
    """
    if end_date is None:
        end_date = datetime.now().strftime("%Y-%m-%d")

    section_id = f"{citation.part}.{citation.section}" if citation.section and citation.part is not None else None
    params = {
        "issue_date[gte]": start_date,
        "issue_date[lte]": end_date,
    }
    if section_id:
        params["section"] = section_id
    elif citation.part is not None:
        params["part"] = citation.part
    # else: whole-title query, no part/section filter

    events = _cached_get(
        get_ecfr_versions_url(citation.title),
        params=params,
        ttl=CACHE_TTL["versions"],
        extract_key="content_versions",
        error_context="eCFR Versions",
    )

    if substantive_only:
        events = [e for e in events if e.get("substantive") is True]

    return events


def get_changed_sections(
    title: int,
    part: int = None,
    start_date: str = None,
    end_date: str = None,
    substantive_only: bool = False,
) -> List[Dict]:
    """
    Query eCFR Versions API for changed sections in date range.

    Args:
        title: CFR title number.
        part: Optional part number filter.
        start_date: Start date in YYYY-MM-DD format (default: 365 days ago).
        end_date: End date in YYYY-MM-DD format (default: today).
        substantive_only: If True, return only events with substantive=True.

    Returns:
        List of changed sections with amendment dates and `substantive` flag.
    """
    if end_date is None:
        end_date = datetime.now().strftime("%Y-%m-%d")
    if start_date is None:
        start_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")

    params = {
        "issue_date[gte]": start_date,
        "issue_date[lte]": end_date,
    }
    if part:
        params["part"] = part

    events = _cached_get(
        get_ecfr_versions_url(title),
        params=params,
        ttl=CACHE_TTL["versions"],
        extract_key="content_versions",
        error_context="eCFR Versions",
    )

    if substantive_only:
        events = [e for e in events if e.get("substantive") is True]

    return events


# =============================================================================
# eCFR Ancestry API
# =============================================================================


def get_section_ancestry(citation: CFRCitation, date: str = None) -> List[Dict]:
    """
    Query eCFR Ancestry API for full hierarchy path.

    Note on the API: eCFR's /ancestry endpoint requires *some* chapter
    parameter to be present even though it ignores the value — passing
    only part+section returns null. We pass a probe chapter "I" which is
    universally accepted; the API then returns the real chapter in the
    ancestry chain regardless. Verified live 2026-05-22.

    Args:
        citation: Parsed CFR citation
        date: Date in YYYY-MM-DD format (None for current)

    Returns:
        List of ancestry nodes from Title to Section, or empty list if
        the citation lacks the required levels (no part).
    """
    if citation.part is None:
        return []

    if date is None:
        date = get_current_ecfr_date(citation.title)

    # The API requires a chapter param to be present (any value).
    # Real chapter is returned in the response regardless.
    params = {"chapter": "I", "part": citation.part}
    if citation.section:
        params["section"] = f"{citation.part}.{citation.section}"

    return _cached_get(
        get_ecfr_ancestry_url(citation.title, date),
        params=params,
        ttl=CACHE_TTL["structure"],
        extract_key="ancestors",
        error_context="eCFR Ancestry",
    )


# =============================================================================
# Federal Register API (Amendment Tracking)
# =============================================================================


def get_federal_register_document(
    document_number: str,
    include_body: bool = True,
    max_body_chars: int = 50000,
) -> Dict:
    """
    Fetch a single Federal Register document by document number.

    Retrieves full metadata and optionally the document body text from
    the Federal Register API. Used by cfr_rulemaking when the caller passes
    a document number in `include_body_for` to drill into a specific
    rulemaking's full content.

    Args:
        document_number: FR document number (e.g., "2024-09237")
        include_body: Fetch the full document body text (default: True)
        max_body_chars: Truncate body text to this many characters (default: 50000)

    Returns:
        Dict with metadata fields plus optional 'body_text' containing
        the full document text from the GPO raw text endpoint.
    """
    url = f"{FEDERAL_REGISTER_ENDPOINTS['document']}/{document_number}.json"
    params = {
        "fields[]": [
            "title",
            "type",
            "abstract",
            "document_number",
            "publication_date",
            "html_url",
            "pdf_url",
            "body_html_url",
            "raw_text_url",
            "full_text_xml_url",
            "cfr_references",
            "agencies",
            "effective_on",
            "citation",
            "docket_ids",
            "regulation_id_numbers",
            "significant",
            "action",
            "dates",
            "topics",
            "page_length",
            "start_page",
            "end_page",
            "president",
            "subtype",
            "executive_order_number",
            "proclamation_number",
            "signing_date",
        ]
    }

    def _attach_body_text(doc: Dict) -> Dict:
        """Attach raw FR body text when requested, even for cached metadata."""
        raw_url = doc.get("raw_text_url")
        if not raw_url:
            return doc
        try:
            body_resp = requests.get(raw_url, timeout=REQUEST_TIMEOUT_SECONDS * 2)
            body_resp.raise_for_status()
            # Strip HTML wrapper -- raw_text_url returns <html><body><pre>...</pre>
            body_text = body_resp.text
            body_text = re.sub(r"<[^>]+>", "", body_text)
            body_text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]+", " ", body_text)
            body_text = body_text.strip()
            if len(body_text) > max_body_chars:
                doc["body_text"] = body_text[:max_body_chars]
                doc["body_truncated"] = True
                doc["body_total_chars"] = len(body_text)
            else:
                doc["body_text"] = body_text
                doc["body_truncated"] = False
        except requests.exceptions.RequestException as e:
            logger.warning(f"Failed to fetch FR document body: {e}")
            doc["body_text"] = None
            doc["body_error"] = str(e)
        return doc

    def _strip_body_fields(doc: Dict) -> Dict:
        clean = dict(doc)
        for key in ("body_text", "body_truncated", "body_total_chars", "body_error"):
            clean.pop(key, None)
        return clean

    def _respect_body_limit(doc: Dict) -> Dict:
        clean = dict(doc)
        body_text = clean.get("body_text")
        if isinstance(body_text, str) and len(body_text) > max_body_chars:
            clean["body_text"] = body_text[:max_body_chars]
            clean["body_truncated"] = True
            clean["body_total_chars"] = clean.get("body_total_chars", len(body_text))
        return clean

    cache_key = _get_cache_key(url, params)
    cached = _get_cached_response(cache_key, ttl_seconds=CACHE_TTL["historical_content"])
    if cached is not None:
        doc = dict(cached)
        if not include_body:
            return _strip_body_fields(doc)
        cached_body = doc.get("body_text")
        needs_body_fetch = cached_body is None or (
            bool(doc.get("body_truncated")) and isinstance(cached_body, str) and len(cached_body) < max_body_chars
        )
        if needs_body_fetch:
            return _attach_body_text(_strip_body_fields(doc))
        return _respect_body_limit(doc)

    try:
        response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        doc = response.json()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            raise CFRNotFoundError(
                f"Federal Register document '{document_number}' not found. "
                "Check the document number format (e.g., '2024-09237')."
            )
        raise CFRAPIError(f"Federal Register API error: {e}")
    except requests.exceptions.RequestException as e:
        raise CFRAPIError(f"Federal Register request failed: {e}")

    _cache_response(cache_key, _strip_body_fields(doc))
    if include_body:
        return _attach_body_text(dict(doc))
    return _strip_body_fields(doc)


# FR correction/reissue document numbers carry a "C<n>-" or "R<n>-" prefix
# (e.g. "C1-2009-31418", "R1-2016-03141") ahead of the original's number.
_EO_CORRECTION_RE = re.compile(r"^[CR]\d+-", re.IGNORECASE)


def _is_eo_correction(document_number: Optional[str]) -> bool:
    """True when an FR document number is a correction/reissue of an EO."""
    return bool(_EO_CORRECTION_RE.match(document_number or ""))


def _executive_order_search(
    eo_number: int,
    year: int = None,
    use_term: bool = True,
) -> List[Dict]:
    """Search FR presidential documents for an EO number."""
    target = str(int(eo_number))
    params = {
        "conditions[presidential_document_type][]": "executive_order",
        "fields[]": [
            "document_number",
            "executive_order_number",
            "citation",
            "publication_date",
            "signing_date",
            "title",
        ],
        "per_page": 1000,
        "order": "newest",
    }
    if use_term:
        params["conditions[term]"] = target
    if year is not None:
        params["conditions[publication_date][year]"] = int(year)

    results = _cached_get(
        FEDERAL_REGISTER_ENDPOINTS["documents"],
        params=params,
        ttl=CACHE_TTL["historical_content"],
        extract_key="results",
        fallback=[],
        error_context="Federal Register EO Lookup",
    )
    return [d for d in results if str(d.get("executive_order_number")) == target]


def get_executive_order_document(
    eo_number: int,
    year: int = None,
    include_body: bool = False,
    max_body_chars: int = 50000,
) -> Optional[Dict]:
    """Resolve an Executive Order number to its Federal Register document.

    The Federal Register API does not expose a direct executive-order-number
    filter. We query Presidential Documents of subtype executive_order, request
    the `executive_order_number` field, and filter exact matches locally.

    Args:
        eo_number: Executive Order number, e.g. 14008.
        year: Optional publication-year hint. Useful for older EOs or when a
            permitting document includes a date.
        include_body: Fetch raw body text from the FR/GovInfo text URL.
        max_body_chars: Truncate fetched body text to this many characters.

    Returns:
        Full Federal Register document record, or None if the FR API has no
        matching presidential document.
    """
    if not eo_number:
        raise CFRCitationError("Executive Order number is required.")

    matches = _executive_order_search(eo_number, year=year, use_term=True)
    if not matches and year is not None:
        # Some older records are easier to find by scanning the year and
        # filtering the explicit executive_order_number field.
        matches = _executive_order_search(eo_number, year=year, use_term=False)

    if not matches:
        return None

    # When an EO number maps to more than one FR document, the extra ones are
    # corrections/reissues (doc numbers prefixed "C1-"/"R1-") published AFTER
    # the original order. Prefer the substantive original: rank non-corrections
    # first, then by EARLIEST publication date (the original precedes its
    # correction), with document_number as a stable tiebreaker.
    def _selection_key(d: Dict) -> tuple:
        return (
            _is_eo_correction(d.get("document_number")),
            d.get("publication_date") or "",
            d.get("document_number") or "",
        )

    matches.sort(key=_selection_key)
    return get_federal_register_document(
        matches[0]["document_number"],
        include_body=include_body,
        max_body_chars=max_body_chars,
    )


# Federal Register volume N was published in year (1935 + N): vol 88 -> 2023.
_FR_VOL_BASE_YEAR = 1935

# "90 FR 29498" / "90 Fed. Reg. 29498" -> (volume, page).
_FR_CITATION_RE = re.compile(
    r"(?P<volume>\d{1,3})\s*(?:FR|Fed\.?\s*Reg\.?)\s*(?P<page>\d{1,6})",
    re.IGNORECASE,
)


def parse_fr_citation(citation: str) -> tuple[int, int]:
    """Parse a Federal Register citation into (volume, page).

    Accepts "90 FR 29498", "90 Fed. Reg. 29498", and the data-reference form the
    eCFR renderer emits ("90 FR 29498"). Raises CFRCitationError on malformed
    input.
    """
    if not citation:
        raise CFRCitationError("Empty FR citation.")
    m = _FR_CITATION_RE.search(citation)
    if not m:
        raise CFRCitationError(
            f"Could not parse Federal Register citation '{citation}'. Expected a form like '90 FR 29498'."
        )
    return int(m.group("volume")), int(m.group("page"))


def _fr_earliest_issue_in(gte_iso: str, lte_iso: str):
    """Return (issue_date, docs) for the earliest FR issue in [gte, lte].

    One `order=oldest` query returns the earliest documents in the window; the
    first result's publication_date identifies the earliest issue, and we keep
    every doc sharing that date -- the issue's full document set. (A single FR
    issue is well under the 1000-per-page cap, so one page covers it.)

    `order=oldest` does NOT page-sort within a day, so callers must compute the
    issue's page span from min(start_page)/max(end_page) over all its docs --
    never from the first document alone.

    Returns (None, []) when the window holds no documents.
    """
    results = _cached_get(
        FEDERAL_REGISTER_ENDPOINTS["documents"],
        params={
            "conditions[publication_date][gte]": gte_iso,
            "conditions[publication_date][lte]": lte_iso,
            "fields[]": ["document_number", "citation", "start_page", "end_page", "publication_date"],
            "per_page": 1000,
            "order": "oldest",
        },
        ttl=CACHE_TTL["historical_content"],
        extract_key="results",
        fallback=[],
        error_context="Federal Register Citation Lookup",
    )
    if not results:
        return None, []
    issue_date = results[0].get("publication_date")
    docs = [d for d in results if d.get("publication_date") == issue_date]
    return issue_date, docs


def _fr_issue_docs_for_page(volume: int, page: int) -> Optional[List[Dict]]:
    """Find the FR issue whose page span contains the cited page."""
    from datetime import date as _date

    year = _FR_VOL_BASE_YEAR + int(volume)
    lo = _date(year, 1, 1)
    hi = _date(year, 12, 31)

    while lo <= hi:
        mid = lo + (hi - lo) // 2
        issue_date_iso, docs = _fr_earliest_issue_in(mid.isoformat(), hi.isoformat())
        if not docs:
            # No issues in [mid, hi]; the target, if any, is earlier.
            hi = mid - timedelta(days=1)
            continue

        issue_date = datetime.strptime(issue_date_iso, "%Y-%m-%d").date()
        starts = [d["start_page"] for d in docs if d.get("start_page")]
        ends = [d["end_page"] for d in docs if d.get("end_page")]
        if not starts:
            hi = mid - timedelta(days=1)
            continue
        span_min, span_max = min(starts), max(ends or starts)

        if page < span_min:
            # Target precedes this (earliest-in-window) issue. The gap
            # [mid, issue_date) holds no issues, so skip straight below mid.
            hi = mid - timedelta(days=1)
        elif page > span_max:
            # Target is in a later issue.
            lo = issue_date + timedelta(days=1)
        else:
            # The cited page falls within this issue's page span.
            return docs

    return None


def _fr_doc_citation_matches(doc: Dict, volume: int, page: int) -> bool:
    """Return True when the API's canonical citation equals volume/page."""
    citation = doc.get("citation")
    if not citation:
        return False
    try:
        doc_volume, doc_page = parse_fr_citation(citation)
    except CFRCitationError:
        return False
    return doc_volume == int(volume) and doc_page == int(page)


def _fr_doc_covers_page(doc: Dict, page: int) -> bool:
    start_page = doc.get("start_page")
    end_page = doc.get("end_page")
    return bool(start_page and end_page and start_page <= page <= end_page)


def _fetch_fr_docs(
    docs: List[Dict],
    selected_document_number: str,
    include_body: bool,
    max_body_chars: int,
) -> List[Dict]:
    """Fetch full FR document metadata for issue-level match summaries."""
    fetched = []
    seen = set()
    for doc in docs:
        document_number = doc.get("document_number")
        if not document_number or document_number in seen:
            continue
        seen.add(document_number)
        fetched.append(
            get_federal_register_document(
                document_number,
                include_body=include_body and document_number == selected_document_number,
                max_body_chars=max_body_chars,
            )
        )
    return fetched


def resolve_fr_citation_to_documents(
    volume: int,
    page: int,
    include_body: bool = False,
    max_body_chars: int = 50000,
) -> Optional[Dict]:
    """Resolve an FR citation (volume + page) to matching document records.

    The FR API has no citation/start_page filter, but FR page numbers increase
    monotonically with publication date within a volume (a volume == a calendar
    year). So we bisect on *publication date* instead of scanning whole months.

    Each step fetches the earliest issue in the remaining window and compares
    the cited page against that issue's true page span [min start, max end]:

      * page below the span  -> the target issue is earlier; search left.
      * page above the span  -> search right (later issues).
      * page within the span -> this is the issue; match the document inside it.

    Using the issue's full span (not its first document's page) is essential:
    `order=oldest` doesn't return a day's lowest-page document first, so a
    single-doc probe would misclassify by an issue (e.g. "75 FR 10411", whose
    issue's first listed doc starts at 10568).

    Within the matched issue, canonical matches are documents whose API
    `citation` or `start_page` matches the requested volume/page. Page-range
    matches are returned as secondary context because inclusive FR page ranges
    commonly overlap at ordinary document boundaries.

    Cost: ~log2(250 publishing days) ~= 8 issue fetches per citation (cached),
    versus the whole-year month scan's repeated multi-page 1000-doc windows.
    Returns a resolution envelope with the backward-compatible selected
    `document`, all canonical matches, all covering-range matches, and an
    ambiguity flag. Returns None if nothing matches -- including pre-~1994
    citations the FR API doesn't cover.
    """
    if not volume or not page:
        raise CFRCitationError("FR citation requires both volume and page.")
    # FR volumes never approach 200k pages/year -- anything larger is bogus.
    if int(page) > 200_000:
        return None

    matched_docs = _fr_issue_docs_for_page(volume, page)
    if not matched_docs:
        return None

    canonical_matches = [
        doc for doc in matched_docs if _fr_doc_citation_matches(doc, volume, page) or doc.get("start_page") == page
    ]
    covering_range_matches = [doc for doc in matched_docs if _fr_doc_covers_page(doc, page)]

    selected = (
        canonical_matches[0] if canonical_matches else covering_range_matches[0] if covering_range_matches else None
    )
    if selected is None:
        return None

    selected_document_number = selected["document_number"]
    canonical_documents = _fetch_fr_docs(
        canonical_matches,
        selected_document_number,
        include_body=include_body,
        max_body_chars=max_body_chars,
    )
    covering_range_documents = _fetch_fr_docs(
        covering_range_matches,
        selected_document_number,
        include_body=include_body,
        max_body_chars=max_body_chars,
    )

    selected_document = next(
        (
            doc
            for doc in canonical_documents + covering_range_documents
            if doc.get("document_number") == selected_document_number
        ),
        None,
    )
    if selected_document is None:
        return None

    if len(canonical_documents) > 1:
        ambiguous = True
        ambiguity_reason = "multiple_documents_share_citation_start_page"
        selection_strategy = "first_canonical_match_for_backward_compatibility"
    elif not canonical_documents and len(covering_range_documents) > 1:
        ambiguous = True
        ambiguity_reason = "multiple_documents_cover_cited_page"
        selection_strategy = "first_covering_range_match_for_backward_compatibility"
    elif canonical_documents:
        ambiguous = False
        ambiguity_reason = None
        selection_strategy = "single_canonical_match"
    else:
        ambiguous = False
        ambiguity_reason = None
        selection_strategy = "single_covering_range_match"

    primary_matches = canonical_documents or covering_range_documents
    return {
        "document": selected_document,
        "ambiguous": ambiguous,
        "ambiguity_reason": ambiguity_reason,
        "match_count": len(primary_matches),
        "canonical_match_count": len(canonical_documents),
        "covering_range_match_count": len(covering_range_documents),
        "canonical_matches": canonical_documents,
        "covering_range_matches": covering_range_documents,
        "selected_document_number": selected_document_number,
        "selection_strategy": selection_strategy,
    }


_DATE_TEXT_RE = re.compile(
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)"
    r"[a-z]*\.?\s+\d{1,2},\s+\d{4}\b"
    r"|\b\d{1,2}/\d{1,2}/\d{4}\b",
    re.IGNORECASE,
)


def _parse_fr_date(raw: str) -> Optional[str]:
    """Normalize common FR citation dates to YYYY-MM-DD."""
    if not raw:
        return None

    cleaned = re.sub(r"\s+", " ", raw.strip()).rstrip(".,;")
    cleaned = cleaned.replace("Sept.", "Sep.").replace("Sept ", "Sep ")

    candidates = [cleaned, cleaned.replace(".", "")]
    for candidate in candidates:
        for fmt in ("%m/%d/%Y", "%b %d, %Y", "%B %d, %Y"):
            try:
                return datetime.strptime(candidate, fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue
    return None


def _extract_dates_from_text(text: str) -> List[str]:
    """Extract normalized dates from FR prose such as the `dates` field."""
    dates = []
    seen = set()
    for match in _DATE_TEXT_RE.finditer(text or ""):
        normalized = _parse_fr_date(match.group(0))
        if normalized and normalized not in seen:
            seen.add(normalized)
            dates.append(normalized)
    return dates


def _document_cfr_part_matches(doc: Dict, title: int, part: Optional[int]) -> bool:
    for ref in doc.get("cfr_references") or []:
        if ref.get("title") != title:
            continue
        if part is None:
            return True
        if str(ref.get("part")) == str(part):
            return True
    return False


def _event_date(event: Dict) -> Optional[str]:
    return event.get("date") or event.get("amendment_date") or event.get("issue_date")


def _document_date_values(doc: Dict) -> List[Dict]:
    values = []
    seen = set()
    for doc_field, match_type in (
        ("publication_date", "publication_date"),
        ("effective_on", "effective_on"),
    ):
        doc_date_str = doc.get(doc_field)
        if not doc_date_str:
            continue
        try:
            datetime.strptime(doc_date_str, "%Y-%m-%d")
        except ValueError:
            continue
        key = (match_type, doc_date_str)
        if key not in seen:
            seen.add(key)
            values.append(
                {
                    "match_type": match_type,
                    "matched_document_date": doc_date_str,
                }
            )

    for date_text_value in _extract_dates_from_text(doc.get("dates") or ""):
        key = ("dates_text", date_text_value)
        if key not in seen:
            seen.add(key)
            values.append(
                {
                    "match_type": "dates_text",
                    "matched_document_date": date_text_value,
                }
            )

    return values


def _date_match_candidates(amend_date: str, doc: Dict, tolerance_days: int) -> List[Dict]:
    try:
        amend_dt = datetime.strptime(amend_date, "%Y-%m-%d")
    except ValueError:
        return []

    matches = []
    for doc_date in _document_date_values(doc):
        try:
            doc_dt = datetime.strptime(doc_date["matched_document_date"], "%Y-%m-%d")
        except ValueError:
            continue
        delta = abs(amend_dt - doc_dt)
        if delta <= timedelta(days=tolerance_days):
            matches.append(
                {
                    "match_type": doc_date["match_type"],
                    "matched_document_date": doc_date["matched_document_date"],
                    "delta_days": delta.days,
                }
            )
    return matches


def _summarize_candidate(candidate: Dict) -> Dict:
    doc = candidate["document"]
    return {
        "document_number": doc.get("document_number"),
        "citation": doc.get("citation"),
        "title": doc.get("title"),
        "type": doc.get("type"),
        "publication_date": doc.get("publication_date"),
        "effective_on": doc.get("effective_on"),
        "match_type": candidate["match_type"],
        "matched_document_date": candidate["matched_document_date"],
        "delta_days": candidate["delta_days"],
        "score": candidate["score"],
        "evidence": candidate["evidence"],
    }


def correlate_amendment_events_with_fr_documents(
    amendment_events: List[Dict],
    fr_documents: List[Dict],
    tolerance_days: int = 7,
) -> List[Dict]:
    """Correlate individual eCFR amendment events to FR source documents.

    This deliberately uses date metadata only: eCFR Versions for amendment
    dates, and Federal Register publication/effective/DATES values for source
    documents. It does not fetch Federal Register XML or historical eCFR full
    XML, because those calls make broad interactive queries too slow.

    When date metadata leaves several equally strong candidates, the result is
    marked ambiguous and returns the tied documents rather than fabricating a
    one-to-one match.
    """
    correlated = []

    for event in amendment_events:
        amend_date = _event_date(event)
        if not amend_date:
            correlated.append(
                {
                    "amendment_date": None,
                    "amendment_event": event,
                    "fr_document": None,
                    "match_type": "invalid_date",
                    "source_label": "[No FR Match]",
                }
            )
            continue

        try:
            title = int(event.get("title")) if event.get("title") is not None else None
        except (TypeError, ValueError):
            title = None
        try:
            part = int(event.get("part")) if event.get("part") is not None else None
        except (TypeError, ValueError):
            part = None

        match_candidates = []
        for doc in fr_documents:
            date_matches = _date_match_candidates(amend_date, doc, tolerance_days)
            best_date = (
                sorted(
                    date_matches,
                    key=lambda m: (
                        m["delta_days"],
                        0 if m["match_type"] == "effective_on" else 1,
                    ),
                )[0]
                if date_matches
                else None
            )

            evidence = []
            score = 0
            if best_date:
                score += max(0, 20 - best_date["delta_days"])
            if best_date and best_date["delta_days"] == 0:
                score += 20
            if best_date and best_date["match_type"] == "effective_on":
                score += 10

            if title and _document_cfr_part_matches(doc, title, part):
                evidence.append({"type": "fr_cfr_reference_part_match"})
                score += 5

            if (doc.get("type") or "").lower() == "rule":
                evidence.append({"type": "fr_document_type_rule"})
                score += 5

            if not best_date:
                continue

            match_candidates.append(
                {
                    "document": doc,
                    "score": score,
                    "evidence": evidence,
                    **best_date,
                }
            )

        match_candidates.sort(
            key=lambda c: (
                -c["score"],
                c["delta_days"],
                0 if c["match_type"] == "effective_on" else 1,
                c["document"].get("publication_date") or "",
                c["document"].get("document_number") or "",
            )
        )

        selected = match_candidates[:1] if match_candidates else []
        if selected:
            best_candidate = selected[0]
            selected = [
                c
                for c in match_candidates
                if c["score"] == best_candidate["score"]
                and c["delta_days"] == best_candidate["delta_days"]
                and c["match_type"] == best_candidate["match_type"]
                and c["matched_document_date"] == best_candidate["matched_document_date"]
            ]
        best = selected[0] if selected else None

        if not best:
            match_confidence = "none"
        elif len(selected) > 1:
            match_confidence = "multiple_date_candidates"
        elif best["delta_days"] == 0:
            match_confidence = "exact_date"
        else:
            match_confidence = "date_proximity"

        correlated.append(
            {
                "amendment_date": amend_date,
                "amendment_event": event,
                "amendment_events": [event],
                "fr_document": best["document"] if best else None,
                "matched_documents": [c["document"] for c in selected],
                "match_type": best["match_type"] if best else "no_match",
                "matched_document_date": best["matched_document_date"] if best else None,
                "delta_days": best["delta_days"] if best else None,
                "candidate_count": len(match_candidates),
                "ambiguous": len(selected) > 1,
                "match_confidence": match_confidence,
                "candidate_documents": [_summarize_candidate(c) for c in match_candidates[:10]],
                "candidate_documents_truncated": max(0, len(match_candidates) - 10),
                "source_label": (
                    "[FR Date Candidates]"
                    if match_confidence == "multiple_date_candidates"
                    else "[FR Candidates]"
                    if best
                    else "[No FR Match]"
                ),
            }
        )

    return correlated
