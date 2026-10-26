---
name: superfund-research
description: Assemble a cited EPA Superfund site dossier from NEPA-MCP's epa_superfund tools, separating published program status from mapped evidence, cleanup records, contaminant associations, restrictions, and unresolved questions.
---

# Superfund Research

Use this skill when a user asks about a Superfund or NPL site, a contaminated
federal facility, or Superfund evidence near a project area. It produces a
cited dossier, not a hazard score, exposure conclusion, liability or ownership
finding, or development-suitability determination.

## 1. Start from a location, name, or identifier

- Location: `get_epa_superfund_sites_in_roi` with latitude, longitude, and a
  buffer in miles.
- Name, city, county, state, or listing status: `search_epa_superfund_sites`.
- Typed identifier: `get_epa_superfund_site` with exactly one of `epa_id`,
  `sems_id`, or `frs_registry_id`.

State the inventory scope you used. `npl_and_mapped` covers NPL status points
and total-site boundaries. `sems_candidates` adds FRS SEMS facility interests
and the SEMS site table. Neither covers every Superfund site.

For a developer screening a parcel: run `get_epa_superfund_sites_in_roi` with
`sems_candidates`, then `get_epa_superfund_site` for each hit you discuss (it
adds federal-facility, archive, non-NPL, SAA, reuse-map, and area evidence),
then the OU, control, contaminant, and notice tools for sites that matter.
SEMS records without coordinates never appear in location results; also search
the county or city by name.

These tools cannot answer: current contamination extent or exposure, whether
land is suitable or available for a new use, ownership or liability, the
detailed cleanup schedule, five-year-review findings, or local notices. Say so
and give the EPA site-profile link rather than guessing. Treat a very large
site area (mining districts, federal facilities) as a boundary artifact, not a
contamination footprint.

## 2. Resolve identity

- Confirmed site records have an EPA ID found in the NPL status layer, the
  total-site boundaries, or the SEMS site table. A SEMS site-table record is
  not necessarily an NPL site: most rows are archived or not on the NPL
  (for example, NFRAP). Check listing, archived, and non-NPL status.
- FRS facility interests are candidates until another source confirms them.
  An FRS registry ID is not a SEMS site identity, and one registry ID can
  carry several EPA IDs; when the tool selects none, look each up by EPA ID.
  FRS activity labels are not listing evidence.
- Never link records by name similarity or proximity alone. Report crosswalk
  conflicts the tools flag.

## 3. Compare listing and milestone evidence

Report each source's status separately, with its raw value. When sources
disagree, show all of them and do not pick one. A boundary feature with no
status is not "not on the NPL." Call `get_epa_superfund_site` for each site
you discuss to get federal-facility, archived, non-NPL, and SAA indicators.

- Deletion, partial deletion, construction completion, archiving, and reuse
  milestones are named program events. None of them means unrestricted use or
  absence of contamination.
- A partial deletion does not map the deleted portion, and an unflagged site
  is not proof that no partial deletion occurred.
- A site listed as final can still publish a deletion date (for example,
  after restoration); report both and flag the contradiction.
- Deleted sites can still have five-year reviews and other ongoing duties.
- Report Superfund Alternative Approach participation only from the SEMS site
  table's explicit indicator.

## 4. Retrieve mapped evidence

- `get_epa_superfund_operable_units`: SEMS decision-reference OUs and mapped
  OU features are separate, incomplete inventories; profile OUs are not fetched.
  OU `00` is a sitewide grouping, not a physical
  area. A mapped deleted-area boundary is not an active OU.
- `get_epa_superfund_institutional_controls`: mapped control-related areas,
  not executed covenants, deed restrictions, or proof a restriction is in
  force. An empty result is not evidence that no controls apply.
- A total-site polygon is a research lead, not a parcel, survey, or
  contamination footprint. Federal-facility polygons may follow the facility
  perimeter. Do not calculate contaminated acreage from overlap.

## 5. Records, chronology, contaminants, and notices

- `get_epa_superfund_documents`: NPL listing narratives and Federal Register
  links, decision documents recorded in SEMS by OU (RODs, amendments, ESDs;
  undated, unlinked), and Federal Register documents that name the site.
  Entries are references. Say which documents you actually opened and read;
  listing a title is not review. A Superfund Record of Decision is a cleanup
  remedy decision, not a NEPA decision.
- `get_epa_superfund_cleanup_actions`: NPL milestones, SEMS decision records
  by OU, and dated Federal Register actions naming the site. This is not the
  detailed cleanup schedule; say so, and send the user to the site profile
  for remedial phases and five-year-review dates.
- `get_epa_superfund_contaminants`: contaminant, media, OU, and
  decision-document associations. They are not concentrations, sampling
  results, exposure findings, or a complete list.
- `get_epa_superfund_public_notices`: Federal Register notices naming the
  site (NPL listings, deletions, partial deletions, settlements) with comment
  close dates and dockets. Name matches are candidates until the notice text
  confirms the site. Reproduce close dates as published, with the as-of date,
  and never derive a deadline from a statutory period. Local and web-only
  announcements (most five-year-review notices) are not covered.

## Paging and completeness

Every list tool returns at most 100 rows per call. Keep paging with the
returned `result_offset` until the list is exhausted, or state which page range
you reviewed. Reuse the response's `result_fingerprint` and the same filters on
subsequent pages. If evidence or source coverage changes, the tool rejects the
continuation: restart from offset zero without the old fingerprint rather than
combining incompatible pages. Without a fingerprint, calls remain independent
live reads. Fingerprints reflect retrieved evidence (including cached SEMS and
Federal Register data), not an atomic EPA snapshot or proof of currentness.
Treat "(lower bound)" totals as minimums. Document categories and
notice kinds come from titles, so read the title before relying on a
`document_type` filter.

## Source states

Every tool reports each source as complete, empty, partial, truncated, failed,
unsupported, or skipped. Only `complete` or `empty` from a source supports a
statement about that source. Do not describe failed, skipped, or unsupported
sources as "no records."

EPA's site-profile pages (detailed cleanup schedules, profile OUs, document
collections, participation notices) and its notice and news-release searches
are never retrieved, because EPA's robots.txt disallows automated access. Say
which evidence that leaves unchecked and give the user the official profile
link to open in a browser. Do not try to work around this.
Access, attribution, and reuse notes are maintained in
`docs/mcp-data-source-licenses.md` under EPA Superfund Access And Reuse.

## Federal facilities

For military or other federal facilities, keep EPA Superfund identities and
responsibilities separate from military cleanup-program identities. Other
NEPA-MCP servers may add context when available, but this skill does not
depend on them.

## Dossier template

1. Identifiers: EPA ID, SEMS site id, FRS registry IDs, and names by source.
2. Listing status by source, with raw values, dates, and conflicts.
3. Milestones: proposed, final, construction completion, deletion, and
   partial deletion.
4. Mapped evidence: total-site, OU, and IC features with their coverage
   limits.
5. Milestones and decisions: NPL dates, Federal Register actions, and SEMS
   decision types by OU, noting that the detailed schedule was not retrieved.
6. Contaminant, media, and action associations, with the stated limits.
7. Documents listed versus documents reviewed, with links.
8. Public notices and comment due dates, with the as-of date.
9. Source states, evidence limits, and unresolved questions for the site
   team, such as instrument-level control review, current remedy status, or
   offsite impacts.
