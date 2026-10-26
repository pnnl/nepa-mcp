"""Local stdio NRC ADAMS research with server-side subscription credentials."""

import json
import sys
from pathlib import Path
from typing import Annotated, Literal

SERVER_DIR = Path(__file__).resolve().parent
REPO_DIR = SERVER_DIR.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))
if (REPO_DIR / "nepa_mcp_common").exists() and str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))
from fastmcp import FastMCP
from fastmcp.tools import ToolResult
from mcp.types import ResourceLink, TextContent
from pydantic import Field
from src.apis import adams_api, files_api, references_api

mcp = FastMCP("nrc-adams-server")
READ_ONLY = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True}
Accession = Annotated[
    str, Field(description="NRC accession string, including supported legacy identifiers; preserve leading zeros.")
]
PageSize = Annotated[
    int, Field(ge=1, le=100, description="Maximum output records per page, 1–100; separate from upstream page size.")
]
Offset = Annotated[
    int, Field(ge=0, le=100000, description="Nonnegative result offset; the source index can change between calls.")
]


@mcp.tool(annotations=READ_ONLY, timeout=60)
def search_nrc_adams_documents(
    query: Annotated[
        str, Field(max_length=2000, description="APS Boolean query; a query or substantive typed filter is required.")
    ] = "",
    docket_number: Annotated[
        str | None,
        Field(description="Exact published numeric docket string; no guessed padding or reactor-only normalization."),
    ] = None,
    document_type: Annotated[
        str | None, Field(description="Exact source DocumentType value; no invented exhaustive vocabulary.")
    ] = None,
    date_basis: Annotated[
        Literal["document_date", "date_added"],
        Field(description="Use source document date or public-library addition timestamp."),
    ] = "document_date",
    date_from: Annotated[
        str | None, Field(description="Source on/after boundary in YYYY-MM-DD; source timezone ambiguity is preserved.")
    ] = None,
    date_to: Annotated[
        str | None, Field(description="Source on/before boundary in YYYY-MM-DD; not a guessed timestamp timezone.")
    ] = None,
    library: Annotated[
        Literal["main", "legacy", "both"],
        Field(description="Public library scope; metadata-only legacy records may lack text."),
    ] = "both",
    sort_by: Annotated[
        Literal["document_date", "date_added", "accession_number", "title"],
        Field(description="Allowlisted source sort field; pagination has no immutable snapshot guarantee."),
    ] = "document_date",
    sort_direction: Annotated[
        Literal["ascending", "descending"], Field(description="Source sort direction.")
    ] = "descending",
    max_results: PageSize = 50,
    result_offset: Offset = 0,
) -> str:
    """Search public NRC ADAMS records with typed AND filters, explicit libraries, and skip continuation."""
    return json.dumps(
        adams_api.search_nrc_adams_documents(
            query,
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
    )


@mcp.tool(annotations=READ_ONLY, timeout=60)
def get_nrc_adams_document(accession_number: Accession) -> str:
    """Retrieve one public accession's metadata and source-returned official links, without implying content review."""
    return json.dumps(adams_api.get_nrc_adams_document(accession_number))


@mcp.tool(annotations=READ_ONLY, timeout=60)
def get_nrc_adams_document_text(
    accession_number: Accession,
    character_offset: Annotated[
        int,
        Field(ge=0, le=10000000, description="Offset into the returned indexed text representation, not a PDF page."),
    ] = 0,
    max_characters: Annotated[
        int,
        Field(ge=1, le=20000, description="Maximum characters in this chunk, 1–20000; independent of API byte cap."),
    ] = 12000,
) -> str:
    """Retrieve bounded API indexed text with a fingerprint and explicit completeness limitations."""
    return json.dumps(adams_api.get_nrc_adams_document_text(accession_number, character_offset, max_characters))


@mcp.tool(annotations=READ_ONLY, timeout=300)
def get_nrc_adams_package(accession_number: Accession, max_results: PageSize = 100, result_offset: Offset = 0) -> str:
    """Read explicitly published package membership with bounded member lookups and independent pagination."""
    return json.dumps(adams_api.get_nrc_adams_package(accession_number, max_results, result_offset))


@mcp.tool(
    annotations=READ_ONLY,
    timeout=90,
    output_schema={"type": "object", "properties": {"result": {"type": "string"}}, "required": ["result"]},
)
def get_nrc_adams_document_file(
    accession_number: Accession,
    max_bytes: Annotated[
        int,
        Field(ge=1, le=26214400, description="Hard streamed original-file byte cap; default 10 MiB, maximum 25 MiB."),
    ] = 10485760,
) -> ToolResult:
    """Retrieve a verified bounded original PDF as an immutable, expiring MCP resource link."""
    result = files_api.get_nrc_adams_document_file(accession_number, max_bytes)
    value = json.dumps(result)
    content = [TextContent(type="text", text=value)]
    if result.get("snapshot_created"):
        content.append(
            ResourceLink(
                type="resource_link",
                uri=result["resource_uri"],
                name=f"{result['accession_number']}-original.pdf",
                mimeType="application/pdf",
                size=result["actual_bytes"],
                description="Immutable verified PDF snapshot; expires in 15 minutes or on eviction/server restart.",
            )
        )
    return ToolResult(content=content, structured_content={"result": value})


@mcp.tool(annotations=READ_ONLY, timeout=300)
def get_nrc_adams_document_references(
    accession_number: Accession,
    source: Annotated[
        Literal["indexed_text", "original_pdf"],
        Field(description="Evidence representation; PDF uses verified original bytes and physical page locators."),
    ] = "indexed_text",
    verify_targets: Annotated[
        bool, Field(description="Resolve at most ten candidate targets; does not establish evidentiary support.")
    ] = False,
    max_results: PageSize = 100,
    result_offset: Offset = 0,
) -> str:
    """Extract source-located outgoing accession candidates, excluding self mentions, with bounded verification."""
    return json.dumps(
        references_api.get_nrc_adams_document_references(
            accession_number, source, verify_targets, max_results, result_offset
        )
    )


@mcp.resource("nrc-adams://documents/{accession_number}/{sha256}/original", mime_type="application/pdf")
def read_original(accession_number: str, sha256: str) -> bytes:
    """Read an existing immutable PDF snapshot; expired resources require a new verified file retrieval."""
    return files_api.snapshot(accession_number, sha256)


if __name__ == "__main__":
    mcp.run(transport="stdio", show_banner=False)
