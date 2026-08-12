#!/usr/bin/env python3
"""
MCP Server for Federal Code of Federal Regulations (CFR)

Provides tools for querying CFR regulatory text via eCFR API, tracking
regulatory changes, and monitoring amendments over time.
Essential for NEPA/EIS regulatory citation and compliance documentation.

API Documentation:
- eCFR: https://www.ecfr.gov/developers/documentation/api/v1
"""

import sys
import json
import logging
import re as _re_strat
from datetime import datetime, timedelta
from pathlib import Path

from fastmcp import FastMCP

SERVER_DIR = Path(__file__).resolve().parent
REPO_DIR = SERVER_DIR.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))
if (REPO_DIR / "nepa_mcp_common").exists() and str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

from src.apis.cfr_api import (  # noqa: E402
    # Citation parsing + paragraph-tree access
    parse_cfr_citation,
    get_ecfr_section_content,
    _parse_section_html,
    # Structure / browsing
    get_ecfr_title_structure,
    get_ecfr_titles,
    find_part_in_structure,
    # Versions / ancestry
    get_section_versions,
    get_section_ancestry,
    get_changed_sections,
    # Federal Register
    get_federal_register_document,
    get_executive_order_document,
    resolve_fr_citation_to_documents,
    parse_fr_citation,
    correlate_amendment_events_with_fr_documents,
    # Exceptions used by the strategic tools
    CFRAPIError,
    CFRCitationError,
    CFRNotFoundError,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("cfr-mcp-server")

mcp = FastMCP("cfr-server")

READ_ONLY_TOOL_ANNOTATIONS = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": True,
}


def _json_response(result: dict) -> str:
    """Serialize a structured result dict to JSON string."""
    return json.dumps(result, indent=2, ensure_ascii=False, default=str)


def _error_response(error_type: str, message: str) -> str:
    """Return a consistent JSON error response."""
    return _json_response({"error": error_type, "message": str(message)})


def _timestamp() -> str:
    """Current UTC timestamp for retrieved field."""
    return datetime.now().strftime("%Y-%m-%d %H:%M UTC")


# =============================================================================
# Strategic tool surface (Phase 2 — replacement set, traversal-only)
# =============================================================================


def _normalize_data_title(s: str) -> str:
    """Strip HTML tags from a data-title key. The eCFR renderer wraps inner-
    numeric paragraph levels (the 5th and 7th depths) in <em> tags so a real
    data-title looks like '261.4(a)(20)(ii)(B)(<em>1</em>)'. Normalize to
    '261.4(a)(20)(ii)(B)(1)' for matching."""
    if not s:
        return ""
    return _re_strat.sub(r"<[^>]+>", "", s)


def _build_target_data_title(part: int, section: str, paragraph_path: list) -> str:
    """Reconstruct the eCFR renderer data-title key for an addressed node.
    Example: part=261, section='4', path=['a','20','ii','B','1']
             -> '261.4(a)(20)(ii)(B)(1)'."""
    base = f"{part}.{section}"
    if paragraph_path:
        base += "".join(f"({p})" for p in paragraph_path)
    return base


def _walk_for_node(node: dict, target: str):
    """Depth-first search of the paragraph tree for a node whose normalized
    data-title equals `target`. Returns the matching node dict, or None."""
    if _normalize_data_title(node.get("citation", "")) == target:
        return node
    for child in node.get("children", []):
        found = _walk_for_node(child, target)
        if found is not None:
            return found
    return None


def _deepest_ancestor_match(paragraphs: list, part: int, section: str, paragraph_path: list):
    """When the exact path doesn't resolve, walk back from the deepest level
    until we find a real node. Returns (matched_node, matched_path).
    Returns (None, None) if no ancestor matches at all."""
    for i in range(len(paragraph_path), -1, -1):
        target = _build_target_data_title(part, section, paragraph_path[:i])
        for top in paragraphs:
            found = _walk_for_node(top, target)
            if found is not None:
                return found, paragraph_path[:i]
    return None, None


@mcp.tool(name="cfr_resolve_citation", annotations=READ_ONLY_TOOL_ANNOTATIONS, timeout=60.0)
def cfr_resolve_citation(
    citation: str,
    as_of: str | None = None,
    include_ancestry: bool = True,
    include_full_section: bool = False,
) -> str:
    """Resolve a CFR citation (any depth) to its current verbatim text.

    Accepts citations from "43 CFR 46.215" through deep paragraph addressing
    like "40 CFR 261.4(a)(20)(ii)(B)(1)". Returns the verbatim text at the
    addressed depth, the section heading, the ancestry breadcrumb, and any
    cross-references. When the addressed paragraph doesn't exist at `as_of`
    (e.g. it was reorganized), returns the deepest matching ancestor with a
    `resolution_warning` field — never raises for navigation reasons.

    Args:
        citation: Citation string. Examples: "43 CFR 46.215",
            "33 CFR 328.3(a)", "40 CFR 261.4(a)(20)(ii)(B)(1)".
        as_of: YYYY-MM-DD; None = current (eCFR ~1 day lag).
        include_ancestry: Include the title->section breadcrumb (default True).
        include_full_section: Also return the entire section tree alongside
            the addressed node. Useful when you want sibling context or an
            explicit full-section payload.

    Returns:
        JSON with: citation (parsed), as_of, ancestry, addressed_node,
        section_heading, fr_citations_in_text, source_and_authority,
        and optionally full_section + resolution_warning.
    """
    try:
        cit = parse_cfr_citation(citation)
    except CFRCitationError as e:
        return _error_response("CFRCitationError", str(e))

    if not cit.section or cit.part is None:
        return _error_response(
            "CFRCitationError",
            f"cfr_resolve_citation requires a section-level citation. Got: {cit.to_display()}",
        )

    # Fetch & parse the section HTML
    try:
        html = get_ecfr_section_content(cit, date=as_of)
    except CFRNotFoundError as e:
        return _error_response("CFRNotFoundError", str(e))
    except CFRAPIError as e:
        return _error_response("CFRAPIError", str(e))

    parsed = _parse_section_html(html)
    if not parsed:
        return _error_response(
            "CFRAPIError",
            f"Failed to parse section HTML for {cit.to_display()}",
        )

    # Resolve to a paragraph node (or fall back).
    paragraphs = parsed.get("paragraphs", []) or []
    target_key = _build_target_data_title(cit.part, cit.section, cit.paragraph_path)
    addressed_node = None
    matched_path = cit.paragraph_path
    resolution_warning = None

    if cit.paragraph_path:
        for top in paragraphs:
            addressed_node = _walk_for_node(top, target_key)
            if addressed_node is not None:
                break
        if addressed_node is None:
            addressed_node, matched_path = _deepest_ancestor_match(
                paragraphs,
                cit.part,
                cit.section,
                cit.paragraph_path,
            )
            if addressed_node is None:
                resolution_warning = (
                    f"Paragraph path {cit.paragraph_path} not found in "
                    f"{cit.part}.{cit.section}; no ancestor matched either."
                )
            else:
                resolution_warning = (
                    f"Paragraph path {cit.paragraph_path} not found at "
                    f"{as_of or 'current'}. Falling back to deepest matching "
                    f"ancestor: {matched_path}."
                )
    else:
        # No path requested — give the section root.
        addressed_node = {
            "citation": f"{cit.part}.{cit.section}",
            "depth": 0,
            "text": parsed.get("preamble", "") or "",
            "children": paragraphs,
        }

    # Ancestry
    ancestors = []
    if include_ancestry:
        try:
            ancestors = get_section_ancestry(cit, date=as_of) or []
        except CFRAPIError as e:
            logger.warning(f"Ancestry fetch failed: {e}")
            ancestors = []

    result = {
        "citation": {
            "title": cit.title,
            "part": cit.part,
            "section": cit.section,
            "paragraph_path": cit.paragraph_path,
            "matched_paragraph_path": matched_path,
            "display": cit.to_display(),
        },
        "as_of": as_of,
        "section_heading": parsed.get("heading", ""),
        "addressed_node": _strip_addressed(addressed_node),
        "ancestry": ancestors,
        "fr_citations_in_text": parsed.get("fr_citations", []),
        "source_and_authority": parsed.get("source_and_authority"),
        "source": "eCFR Renderer + Ancestry",
        "retrieved": _timestamp(),
    }

    if include_full_section:
        result["full_section"] = {
            "heading": parsed.get("heading", ""),
            "preamble": parsed.get("preamble", ""),
            "paragraphs": paragraphs,
        }

    if resolution_warning:
        result["resolution_warning"] = resolution_warning

    return _json_response(result)


def _strip_addressed(node):
    """Return a shallow-cleaned copy of a paragraph node — normalize the
    citation key (strip <em>) and recursively clean children."""
    if node is None:
        return None
    cleaned = {
        "citation": _normalize_data_title(node.get("citation", "")),
        "depth": node.get("depth", 0),
        "text": node.get("text", ""),
    }
    if node.get("defined_term"):
        cleaned["defined_term"] = node["defined_term"]
    if node.get("cross_references"):
        cleaned["cross_references"] = node["cross_references"]
    children = node.get("children", [])
    if children:
        cleaned["children"] = [_strip_addressed(c) for c in children]
    return cleaned


def _prune_to_depth(node: dict, current_depth: int, max_depth: int) -> dict:
    """Return a copy of `node` with children pruned beyond `max_depth`.

    Depth counting (cfr-browse-structure semantics):
        depth 1 = parts (under the title/subtitle root)
        depth 2 = subparts and subject_groups
        depth 3 = sections
        depth 4 = paragraph nodes (rare — eCFR structure rarely exposes them
                  but we keep the convention for max_depth=4 callers)

    Implementation: we just count "useful structural levels" by depth-first
    walking and counting the level of each child relative to the root caller.
    """
    out = {
        "type": node.get("type"),
        "identifier": node.get("identifier"),
        "label": node.get("label"),
        "label_level": node.get("label_level"),
        "reserved": node.get("reserved", False),
    }
    if node.get("size") is not None:
        out["size"] = node["size"]
    if node.get("descendant_range") is not None:
        out["descendant_range"] = node["descendant_range"]

    if current_depth < max_depth:
        children = node.get("children") or []
        if children:
            out["children"] = [_prune_to_depth(c, current_depth + 1, max_depth) for c in children]
            out["children_count"] = len(children)
        else:
            out["children"] = []
            out["children_count"] = 0
    else:
        # Stop descending; report how many we elided.
        children = node.get("children") or []
        out["children"] = []
        out["children_count"] = len(children)
        if children:
            out["children_truncated"] = True

    return out


@mcp.tool(name="cfr_browse_structure", annotations=READ_ONLY_TOOL_ANNOTATIONS, timeout=60.0)
def cfr_browse_structure(
    title: int | None = None,
    part: int | None = None,
    as_of: str | None = None,
    max_depth: int = 3,
) -> str:
    """Browse the table of contents at any level of the CFR hierarchy.

    Use this when you don't already know the exact citation but need to
    discover what regulations live where. Three modes:

    * No args / `title=None` → returns the list of all 50 CFR titles plus
      freshness metadata (latest_amended_on, up_to_date_as_of).
    * `title=N` → returns the title's structure pruned to `max_depth`.
    * `title=N, part=P` → returns only the subtree rooted at that part.

    Args:
        title: CFR title number (1-50). None = list titles.
        part: Part number; restricts the returned subtree to that part.
        as_of: YYYY-MM-DD; None = current (eCFR ~1 day lag).
        max_depth: 1=parts, 2=subparts, 3=sections (default), 4=paragraphs.
            Children below this depth are elided with `children_truncated=true`.

    Returns:
        JSON with `mode`, `as_of`, and either:
            - `titles` (list of title summaries) when no `title` provided, OR
            - `root_node` (pruned tree) for the title or part subtree.
    """
    # Mode A: list all titles
    if title is None:
        try:
            titles_raw = get_ecfr_titles() or {}
        except CFRAPIError as e:
            return _error_response("CFRAPIError", str(e))

        titles_list = titles_raw.get("titles", []) if isinstance(titles_raw, dict) else []
        return _json_response(
            {
                "mode": "titles",
                "as_of": as_of,
                "count": len(titles_list),
                "titles": titles_list,
                "source": "eCFR Titles",
                "retrieved": _timestamp(),
            }
        )

    # Mode B & C: structure for a title (optionally narrowed to a part)
    try:
        structure = get_ecfr_title_structure(title, date=as_of)
    except CFRNotFoundError:
        # Reserved title (e.g. Title 35 - Panama Canal) or title that didn't
        # exist at the requested date. Return a graceful "reserved/missing"
        # marker rather than an error so the calling agent can handle it.
        return _json_response(
            {
                "mode": "reserved_or_missing",
                "title": title,
                "as_of": as_of,
                "reserved": True,
                "note": (
                    f"Title {title} returned no structure at {as_of or 'current'}. "
                    "Likely reserved (e.g. Title 35 - Panama Canal) or did not "
                    "exist at the requested date."
                ),
                "source": "eCFR Structure",
                "retrieved": _timestamp(),
            }
        )
    except CFRAPIError as e:
        return _error_response("CFRAPIError", str(e))

    if not structure:
        return _json_response(
            {
                "mode": "reserved_or_missing",
                "title": title,
                "as_of": as_of,
                "reserved": True,
                "source": "eCFR Structure",
                "retrieved": _timestamp(),
            }
        )

    if part is not None:
        part_node = find_part_in_structure(structure, part)
        if not part_node:
            return _error_response(
                "CFRNotFoundError",
                f"Part {part} not found in title {title} at {as_of or 'current'}.",
            )
        pruned = _prune_to_depth(part_node, current_depth=0, max_depth=max_depth)
        mode = "part_subtree"
    else:
        pruned = _prune_to_depth(structure, current_depth=0, max_depth=max_depth)
        mode = "title_tree"

    return _json_response(
        {
            "mode": mode,
            "title": title,
            "part": part,
            "as_of": as_of,
            "max_depth": max_depth,
            "root_node": pruned,
            "source": "eCFR Structure",
            "retrieved": _timestamp(),
        }
    )


@mcp.tool(name="cfr_history", annotations=READ_ONLY_TOOL_ANNOTATIONS, timeout=60.0)
def cfr_history(
    citation: str,
    start_date: str | None = None,
    end_date: str | None = None,
    substantive_only: bool = False,
) -> str:
    """All amendment events for a citation in a date window.

    Pure eCFR Versions data — no Federal Register enrichment. Pair this with
    `cfr_rulemaking` if you also need the rulemaking that caused each event.

    Citation can be a section, part, or whole title. Examples:
        "33 CFR 328.3"          → events for that one section
        "43 CFR Part 3800"      → events anywhere in part 3800 (incl. subparts)
        "title 50"              → every change in Title 50

    The `substantive: bool` flag from eCFR is preserved on every event;
    `substantive_only=True` filters to real text changes (excludes
    editorial/typo amendments).

    Args:
        citation: CFR citation. See examples above.
        start_date: YYYY-MM-DD. Default: 5 years ago.
        end_date: YYYY-MM-DD. Default: today.
        substantive_only: If True, drop editorial-only events.

    Returns:
        JSON with `citation`, `window`, `events[]` (each with date,
        substantive flag, identifier/section, subpart, removed flag),
        `event_count`, `substantive_count`.
    """
    try:
        cit = parse_cfr_citation(citation)
    except CFRCitationError as e:
        return _error_response("CFRCitationError", str(e))

    today = datetime.now()
    if end_date is None:
        end_date = today.strftime("%Y-%m-%d")
    if start_date is None:
        start_date = (today - timedelta(days=365 * 5)).strftime("%Y-%m-%d")

    try:
        events = get_section_versions(
            cit,
            start_date=start_date,
            end_date=end_date,
            substantive_only=substantive_only,
        )
    except CFRAPIError as e:
        return _error_response("CFRAPIError", str(e))

    # Total substantive count (regardless of filter) for visibility
    substantive_count = sum(1 for e in events if e.get("substantive") is True)

    return _json_response(
        {
            "citation": {
                "title": cit.title,
                "part": cit.part,
                "section": cit.section,
                "display": cit.to_display(),
            },
            "window": {"start": start_date, "end": end_date},
            "substantive_only": substantive_only,
            "events": events,
            "event_count": len(events),
            "substantive_count": substantive_count,
            "source": "eCFR Versions",
            "retrieved": _timestamp(),
        }
    )


def _flatten_paragraph_tree(paragraphs: list) -> dict:
    """Walk a paragraph tree and return a dict keyed by normalized data-title.
    Each value is the leaf text only (no children)."""
    out: dict = {}

    def visit(node: dict):
        key = _normalize_data_title(node.get("citation", "") or "")
        if key:
            out[key] = (node.get("text") or "").strip()
        for ch in node.get("children", []) or []:
            visit(ch)

    for p in paragraphs or []:
        visit(p)
    return out


@mcp.tool(name="cfr_compare_versions", annotations=READ_ONLY_TOOL_ANNOTATIONS, timeout=60.0)
def cfr_compare_versions(
    citation: str,
    date_a: str,
    date_b: str,
    paragraph_path: list[str] | None = None,
) -> str:
    """Diff a single CFR section between two dates, paragraph by paragraph.

    Returns a structured per-paragraph diff (added / removed / modified /
    unchanged) plus a summary count. When `paragraph_path` is provided, the
    diff is restricted to nodes within that subtree — supports drilling into
    a single (d)(5) without surrounding noise from the rest of the section.

    Args:
        citation: CFR citation. Must resolve to a section.
        date_a: Earlier date YYYY-MM-DD.
        date_b: Later date YYYY-MM-DD.
        paragraph_path: Restrict the diff to a subtree, e.g. ["a", "4", "ii"].

    Returns:
        JSON with `citation`, `date_a`, `date_b`, `paragraph_diff[]`,
        `summary` (added/removed/modified/unchanged counts), and the section
        headings at both dates (so caller can spot title changes too).
    """
    try:
        cit = parse_cfr_citation(citation)
    except CFRCitationError as e:
        return _error_response("CFRCitationError", str(e))

    if not cit.section or cit.part is None:
        return _error_response(
            "CFRCitationError",
            f"cfr_compare_versions requires a section-level citation. Got: {cit.to_display()}",
        )

    def _fetch_parsed(date: str):
        try:
            html = get_ecfr_section_content(cit, date=date)
        except CFRNotFoundError:
            return {"removed": True, "heading": "", "paragraphs": []}
        except CFRAPIError as e:
            return {"error": str(e), "heading": "", "paragraphs": []}
        parsed = _parse_section_html(html)
        if parsed is None:
            return {"error": "parse failed", "heading": "", "paragraphs": []}
        parsed["removed"] = False
        return parsed

    a = _fetch_parsed(date_a)
    b = _fetch_parsed(date_b)

    if a.get("error"):
        return _error_response("CFRAPIError", f"date_a fetch: {a['error']}")
    if b.get("error"):
        return _error_response("CFRAPIError", f"date_b fetch: {b['error']}")

    flat_a = _flatten_paragraph_tree(a.get("paragraphs", []))
    flat_b = _flatten_paragraph_tree(b.get("paragraphs", []))

    # If paragraph_path provided, restrict to the subtree.
    target_prefix = None
    if paragraph_path:
        target_prefix = _build_target_data_title(cit.part, cit.section, paragraph_path)
        flat_a = {k: v for k, v in flat_a.items() if k == target_prefix or k.startswith(target_prefix + "(")}
        flat_b = {k: v for k, v in flat_b.items() if k == target_prefix or k.startswith(target_prefix + "(")}

    keys = sorted(set(flat_a) | set(flat_b))
    paragraph_diff = []
    summary = {"added": 0, "removed": 0, "modified": 0, "unchanged": 0}

    for key in keys:
        ta = flat_a.get(key)
        tb = flat_b.get(key)
        if ta is None and tb is not None:
            status = "added"
        elif ta is not None and tb is None:
            status = "removed"
        elif ta != tb:
            status = "modified"
        else:
            status = "unchanged"
        summary[status] += 1
        # Only include diff entries; skip unchanged from the body for token efficiency.
        if status != "unchanged":
            paragraph_diff.append(
                {
                    "path": key,
                    "status": status,
                    "text_a": ta,
                    "text_b": tb,
                }
            )

    return _json_response(
        {
            "citation": {
                "title": cit.title,
                "part": cit.part,
                "section": cit.section,
                "paragraph_path": paragraph_path or [],
                "display": cit.to_display(),
            },
            "date_a": date_a,
            "date_b": date_b,
            "section_heading_a": a.get("heading", ""),
            "section_heading_b": b.get("heading", ""),
            "section_removed_a": a.get("removed", False),
            "section_removed_b": b.get("removed", False),
            "paragraph_diff": paragraph_diff,
            "summary": summary,
            "scoped_to_paragraph_path": paragraph_path,
            "source": "eCFR Renderer comparison",
            "retrieved": _timestamp(),
        }
    )


@mcp.tool(name="cfr_rulemaking", annotations=READ_ONLY_TOOL_ANNOTATIONS, timeout=60.0)
def cfr_rulemaking(
    cfr_title: int,
    cfr_part: int | None = None,
    document_types: list[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    correlate_with_amendments: bool = False,
    substantive_only: bool = True,
    correlation_tolerance_days: int = 7,
    include_body_for: list[str] | None = None,
    max_results: int = 50,
) -> str:
    """Federal Register documents that touched a CFR citation, plus optional
    correlation to specific eCFR amendment events.

    Replaces three old tools (FR-amendments / FR-document-content / correlated-
    history) because they share the FR document number as primary key. The
    correlation tolerance window is now tunable via `correlation_tolerance_days`
    (was hardcoded at 7). Correlation uses eCFR Versions for amendment dates
    and Federal Register date metadata for source-document candidates. It does
    not fetch Federal Register XML or historical eCFR full XML.

    When to use: discovering FR rulemaking activity by CFR location -- "what
    rules/notices touched this title/part over this window?" Returns a list.
    To dereference a single FR citation you already have (e.g. "90 FR 29498"),
    use cfr_resolve_fr_citation instead.

    Args:
        cfr_title: CFR title number (e.g. 33, 40, 50).
        cfr_part: Optional part filter.
        document_types: List from {"RULE","PRORULE","NOTICE"}. Default:
            ["RULE","PRORULE"] for document search, ["RULE"] when correlating
            to actual eCFR amendments unless explicitly provided.
        start_date: YYYY-MM-DD; default 365 days ago.
        end_date: YYYY-MM-DD; default today.
        correlate_with_amendments: If True, fetch eCFR amendment events in the
            same window and pair each with the strongest FR document(s).
        substantive_only: When correlating, include only eCFR amendment events
            with `substantive=true` by default. Set False for editorial changes.
        correlation_tolerance_days: Days tolerance for the date-matching window
            (default 7). Tighten to 1-3 for stricter joins.
        include_body_for: List of FR document numbers whose full body text
            should be inlined in the response (e.g. ["2022-27225"]).
        max_results: Cap on FR documents returned (default 50; FR API max 1000).

    Returns:
        JSON with `documents[]`, optional `correlations[]`, and the window/
        params echoed back.
    """
    today = datetime.now()
    if end_date is None:
        end_date = today.strftime("%Y-%m-%d")
    if start_date is None:
        start_date = (today - timedelta(days=365)).strftime("%Y-%m-%d")

    try:
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    except ValueError as e:
        return _error_response("ValueError", f"Invalid date: {e}")

    from src.apis.cfr_constants import FEDERAL_REGISTER_ENDPOINTS
    import requests

    def _fetch_fr_documents(date_condition: str) -> list[dict] | dict:
        """Fetch FR docs by publication date or effective date."""
        fr_params = {
            "conditions[cfr][title]": cfr_title,
            f"conditions[{date_condition}][gte]": start_date,
            f"conditions[{date_condition}][lte]": end_date,
            "per_page": min(max_results, 1000),
            "order": "newest",
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
            ],
        }
        if cfr_part is not None:
            fr_params["conditions[cfr][part]"] = cfr_part
        fr_params["conditions[type][]"] = types

        try:
            resp = requests.get(
                FEDERAL_REGISTER_ENDPOINTS["documents"],
                params=fr_params,
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json().get("results", [])
        except requests.exceptions.RequestException as e:
            return {"error": str(e)}

    types = document_types or (["RULE"] if correlate_with_amendments else ["RULE", "PRORULE"])
    date_conditions = ["publication_date"]
    if correlate_with_amendments:
        # Source rules may be published before the eCFR amendment window but
        # become effective inside it, so correlation needs both date axes.
        date_conditions.append("effective_date")

    documents_by_number = {}
    for date_condition in date_conditions:
        fetched = _fetch_fr_documents(date_condition)
        if isinstance(fetched, dict) and fetched.get("error"):
            return _error_response(
                "CFRAPIError",
                f"Federal Register fetch failed ({date_condition}): {fetched['error']}",
            )
        for doc in fetched:
            dn = doc.get("document_number")
            if dn and dn not in documents_by_number:
                documents_by_number[dn] = doc
    documents = list(documents_by_number.values())

    # Optionally fetch full body text for selected docs.
    if include_body_for:
        wanted = set(include_body_for)
        for i, doc in enumerate(documents):
            if doc.get("document_number") in wanted:
                try:
                    enriched = get_federal_register_document(
                        doc["document_number"], include_body=True, max_body_chars=50000
                    )
                    documents[i] = enriched
                except CFRAPIError as e:
                    doc["body_error"] = str(e)
        # If a wanted doc isn't in the list (date filter excludes it), fetch
        # it separately and append.
        in_list = {d.get("document_number") for d in documents}
        for dn in wanted - in_list:
            try:
                enriched = get_federal_register_document(dn, include_body=True, max_body_chars=50000)
                documents.append(enriched)
            except CFRAPIError as e:
                documents.append({"document_number": dn, "body_error": str(e)})

    correlations = None
    amendment_events = []
    if correlate_with_amendments:
        # Fetch eCFR amendments in the same window for the same title/part.
        try:
            amendments = get_changed_sections(
                cfr_title,
                part=cfr_part,
                start_date=start_date,
                end_date=end_date,
                substantive_only=substantive_only,
            )
        except CFRAPIError as e:
            amendments = []
            logger.warning(f"Amendment fetch failed: {e}")

        events_by_date = {}
        for event in amendments:
            event_date = event.get("date") or event.get("amendment_date") or event.get("issue_date")
            if not event_date:
                continue
            try:
                event_dt = datetime.strptime(event_date, "%Y-%m-%d")
            except ValueError:
                continue
            if event_dt < start_dt or event_dt > end_dt:
                continue
            event_summary = {
                "date": event_date,
                "issue_date": event.get("issue_date"),
                "amendment_date": event.get("amendment_date"),
                "title": event.get("title"),
                "identifier": event.get("identifier"),
                "name": event.get("name"),
                "type": event.get("type"),
                "part": event.get("part"),
                "subpart": event.get("subpart"),
                "substantive": event.get("substantive"),
                "removed": event.get("removed"),
            }
            events_by_date.setdefault(event_date, []).append(event_summary)

        amend_dates = sorted(events_by_date)
        amendment_events = [event for date in amend_dates for event in events_by_date[date]]
        correlations = correlate_amendment_events_with_fr_documents(
            amendment_events,
            documents,
            tolerance_days=correlation_tolerance_days,
        )
        for correlation in correlations:
            correlation["same_date_amendment_events"] = events_by_date.get(correlation.get("amendment_date"), [])

    return _json_response(
        {
            "window": {"start": start_date, "end": end_date},
            "cfr_title": cfr_title,
            "cfr_part": cfr_part,
            "document_types": types,
            "fr_date_fields_searched": date_conditions,
            "substantive_only": substantive_only if correlate_with_amendments else None,
            "correlation_tolerance_days": correlation_tolerance_days if correlate_with_amendments else None,
            "documents": documents,
            "document_count": len(documents),
            "correlations": correlations,
            "correlation_strategy": ("date_only_no_fr_xml_no_ecfr_full_xml" if correlate_with_amendments else None),
            "amendment_event_count": len(amendment_events) if correlate_with_amendments else None,
            "amendment_date_count": len({event["date"] for event in amendment_events})
            if correlate_with_amendments
            else None,
            "source": "Federal Register API + eCFR Versions" if correlate_with_amendments else "Federal Register API",
            "retrieved": _timestamp(),
        }
    )


@mcp.tool(name="cfr_resolve_fr_citation", annotations=READ_ONLY_TOOL_ANNOTATIONS, timeout=60.0)
def cfr_resolve_fr_citation(
    citation: str,
    include_body: bool = False,
    max_body_chars: int = 50000,
) -> str:
    """Resolve a Federal Register citation to its source document and summary.

    CFR regulatory text routinely cites the Federal Register documents that
    created or amended it (e.g. "90 FR 29498" in a section's source/authority
    line, surfaced as `fr_citations_in_text` by cfr_resolve_citation). This
    tool turns such a citation into the actual FR document: title, type, action,
    agencies, dates, and the FR `abstract` (the agency's own plain-language
    summary) for inline regulatory-review context.

    When to use: dereferencing one specific FR citation you already have in
    hand. Returns a selected document plus ambiguity metadata when the cited
    page maps to more than one FR document. To instead discover all FR
    rulemaking that touched a CFR title/part over a date range, use
    cfr_rulemaking.

    Args:
        citation: Federal Register citation, e.g. "90 FR 29498" or
            "90 Fed. Reg. 29498".
        include_body: Also inline the full document text from the GPO raw-text
            endpoint. Default False (returns compact metadata + abstract). Set
            True only when the full rule text is needed -- bodies can be large.
        max_body_chars: Truncate inlined body text to this many characters when
            include_body is True (default 50000).

    Returns:
        JSON with the parsed `volume`/`page`, the selected `document` (FR
        metadata, including `abstract`), ambiguity flags, matched documents,
        and a short `summary` for display. Returns an error envelope if the
        citation cannot be parsed or no document matches.
    """
    try:
        volume, page = parse_fr_citation(citation)
    except CFRCitationError as e:
        return _error_response("CitationError", e)

    try:
        resolution = resolve_fr_citation_to_documents(
            volume,
            page,
            include_body=include_body,
            max_body_chars=max_body_chars,
        )
    except CFRNotFoundError as e:
        return _error_response("NotFound", e)
    except CFRAPIError as e:
        return _error_response("APIError", e)

    if not resolution:
        return _error_response(
            "NotFound",
            f"No Federal Register document found for '{volume} FR {page}'.",
        )

    doc = resolution["document"]
    abstract = doc.get("abstract")
    summary_bits = [doc.get("title"), doc.get("action")]
    summary = " - ".join(b for b in summary_bits if b) or abstract

    return _json_response(
        {
            "citation": f"{volume} FR {page}",
            "volume": volume,
            "page": page,
            "summary": summary,
            "abstract": abstract,
            "document": doc,
            "ambiguous": resolution["ambiguous"],
            "ambiguity_reason": resolution["ambiguity_reason"],
            "match_count": resolution["match_count"],
            "canonical_match_count": resolution["canonical_match_count"],
            "covering_range_match_count": resolution["covering_range_match_count"],
            "canonical_matches": resolution["canonical_matches"],
            "covering_range_matches": resolution["covering_range_matches"],
            "matches": (resolution["canonical_matches"] or resolution["covering_range_matches"]),
            "selected_document_number": resolution["selected_document_number"],
            "selection_strategy": resolution["selection_strategy"],
            "source": "Federal Register API",
            "retrieved": _timestamp(),
        }
    )


def _coerce_eo_number(value) -> int | None:
    """Normalize the FR `executive_order_number` field (a string) to an int so
    it matches the int the caller passed. Returns None if it isn't numeric."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _summarize_executive_order(doc: dict) -> dict:
    """Small, stable reference record for an EO FR document."""
    return {
        "eo_number": _coerce_eo_number(doc.get("executive_order_number")),
        "title": doc.get("title"),
        "abstract": doc.get("abstract"),
        "type": doc.get("type"),
        "subtype": doc.get("subtype"),
        "fr_citation": doc.get("citation"),
        "fr_document_number": doc.get("document_number"),
        "publication_date": doc.get("publication_date"),
        "signing_date": doc.get("signing_date"),
        "president": doc.get("president"),
        "agency_names": doc.get("agency_names") or [a.get("name") for a in doc.get("agencies", []) if a.get("name")],
        "pages": {
            "start_page": doc.get("start_page"),
            "end_page": doc.get("end_page"),
            "page_length": doc.get("page_length"),
        },
        "urls": {
            "html": doc.get("html_url"),
            "pdf": doc.get("pdf_url"),
            "body_html": doc.get("body_html_url"),
            "raw_text": doc.get("raw_text_url"),
            "full_text_xml": doc.get("full_text_xml_url"),
        },
    }


@mcp.tool(name="cfr_resolve_executive_order", annotations=READ_ONLY_TOOL_ANNOTATIONS, timeout=60.0)
def cfr_resolve_executive_order(
    eo_number: int,
    year: int | None = None,
    include_document: bool = False,
    include_body: bool = False,
    max_body_chars: int = 50000,
) -> str:
    """Resolve an Executive Order number to its Federal Register record.

    Federal Register Presidential Document records include useful EO reference
    fields such as `executive_order_number`, title, FR citation, publication
    date, signing date, president, page range, and source URLs. The API does
    not support a direct executive-order-number filter, so this tool searches
    Presidential Documents of subtype `executive_order`, requests that field,
    and filters exact matches locally.

    Args:
        eo_number: Normalized Executive Order number, e.g. 14008.
        year: Optional publication year hint.
        include_document: Include the full raw Federal Register document JSON.
        include_body: Include raw full-text body from the FR/GovInfo text URL.
            This also includes the full raw document so the body text is visible.
        max_body_chars: Truncate body text when include_body is true.

    Returns:
        JSON with compact `executive_order` stable reference fields by default.
        The raw `document` is included only when include_document or include_body
        is true.
    """
    try:
        if isinstance(eo_number, bool) or not isinstance(eo_number, int):
            raise CFRCitationError("eo_number must be an integer.")
        if eo_number <= 0:
            raise CFRCitationError("eo_number must be a positive integer.")
        doc = get_executive_order_document(
            eo_number,
            year=year,
            include_body=include_body,
            max_body_chars=max_body_chars,
        )
    except CFRCitationError as e:
        return _error_response("CitationError", str(e))
    except CFRAPIError as e:
        return _error_response("APIError", str(e))

    if not doc:
        return _json_response(
            {
                "eo_number": eo_number,
                "year": year,
                "found": False,
                "note": (
                    "No exact Federal Register Presidential Document match was "
                    "found for this executive_order_number. Older permitting EOs "
                    "may predate the Federal Register API document corpus."
                ),
                "source": "Federal Register API",
                "retrieved": _timestamp(),
            }
        )

    result = {
        "eo_number": eo_number,
        "year": year,
        "found": True,
        "executive_order": _summarize_executive_order(doc),
        "source": "Federal Register API",
        "retrieved": _timestamp(),
    }
    if include_document or include_body:
        result["document"] = doc
        result["available_fields"] = sorted(doc.keys())

    return _json_response(result)


if __name__ == "__main__":
    mcp.run(transport="stdio", show_banner=False)
