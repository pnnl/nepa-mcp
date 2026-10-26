---
name: adams-research
description: Research NRC ADAMS public records by accession, exact docket, topic, and date, with explicit document roles and evidence limits.
---

# NRC ADAMS research

Use `nrc_adams` for NRC documents. USDA `nrcs_soils` is unrelated. Establish the subject, time period, accession/docket if known, and library scope. A facility name alone does not establish its docket. A subscription key belongs in the private credential file or process environment, never chat or tool arguments. Missing keys must leave tool discovery and other servers available.

1. Use `search_nrc_adams_documents` with targeted query/filter choices. Docket and document-type filters have exact AND semantics. Preserve leading zeros. Use addition dates for newly public discoveries and document dates for chronology. Follow returned offsets within a stated request budget; the index changes and does not provide an atomic snapshot.
2. Retrieve selected metadata and bounded indexed text. Keep author, procedural role, library scope, availability, and content completeness distinct. Character locations are not PDF page numbers. Metadata-only records remain useful, but do not support quotations. A package title is not review of all enclosures; inspect explicit membership and report unvisited/unresolved members separately.
3. Use `get_nrc_adams_document_file` when original pages, exact quotations, figures, or completeness matter. Read the returned immutable PDF resource before claiming review; links expire after 15 minutes, memory eviction, or server restart. A download does not establish successful text extraction or complete review.
4. Use `get_nrc_adams_document_references` for bounded next research leads. Show source fingerprints, character/physical-PDF-page locators, unverified/failed targets, self exclusions, and scan limits. A mention is not a package member, endorsement, supersession, or proof that the target supports a claim. Do not recursively crawl without an explicit budget.
5. Assemble a cited dossier/chronology with accessions, titles, dates, dockets, official URLs, evidence for each substantive claim, document roles, contradictory statements, source status, incomplete pages/packages/text, and unresolved questions. Preserve draft versus final, applicant submissions versus NRC decisions, achieved milestones versus forecasts/deadlines, and possible supersession requiring content review.

An applicant's environmental report is not NRC approval; a draft EIS is not a final NEPA decision. NRC hosting does not establish NRC authorship or endorsement. Do not infer licensing approval, compliance, NEPA completion, or operating authority from search results. Search misses concern public records only; missing originals may lag newly indexed metadata. Use geographic screening only when requested; ADAMS is not a facility-location inventory.

Current release preparation uses the official subscription API contract from the APS v1.0 guide. Authenticated live search/package/legacy/text verification is pending. Report that limitation and do not switch silently to the public website backend.
