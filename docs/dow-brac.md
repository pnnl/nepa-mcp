# DoW BRAC source coverage

Implementation/verification is per adapter. This branch is **draft work** for issue #55: access and representative-source acceptance checks below remain pending. A working Army source does not establish national coverage or validate another military department.

| Adapter | Verified retrieval on October 23, 2026 | Limits / pending work |
| --- | --- | --- |
| Army five round directories | Public HTML, section-scoped installation/action lists | Not all annexes; aliases remain unresolved across different official source records |
| Army installation documents/conveyance | Fort Indiantown Gap document links and summary | Summary acreage is not parcel transactions, present availability, or cleanup completion |
| Army public-comment links | Umatilla source links explicitly name the installation; posting date captured | Comment-period text lacks a full deadline/year/timezone; no open-window assertion |
| Army disposal plans | Actual table with Memphis and Red River planned parcels | Expected disposal dates are not bid deadlines; advertised-sale contract/crosswalk unverified |
| EPA FRS BRAC points | Layer schema and public queries | EPA interests and NAD83-derived reference locations are not installation identities/footprints |
| Historical military-base polygons | Published layer/schema | Explicit opt-in, 2010/NTAD2014 provenance; unresolved candidates retained |
| Navy Alameda/notice indexes | HTTP 403 | Parser fixtures and current nonempty environmental-site/notice contract need live validation |
| Air Force portfolio | HTTP 403 | Representative program records/office/administrative-record access unverified |
| Fort Devens document/control index | HTTP 403 | Current nonempty control instrument/extraction contract unverified |

All nine tools are exposed, but this branch must not be represented as satisfying every acceptance criterion of #55 until the blocked adapters have permitted public access and representative fixtures. The versioned source manifest is included in results. Unavailable sources remain visible, with official links; no mirror, fabricated API, or alternate inventory is silently substituted.

## Identity, access, and pagination

IDs are local source-namespaced identities, not government-wide BRAC identifiers. Army actions come from the installation rows inside a round's content/action groups; navigation menus and non-BRAC links are excluded. Distinct official URLs are not merged by name or proximity. Exact shared URLs can preserve multiple action records. An explicit reviewed crosswalk links the Army round-1995 Indiantown Gap entry to its working state-page evidence; the target explicitly names that installation/action. Other aliases remain unresolved.

A few Navy/Air Force/Devens URLs are labelled curated research entrypoints from issue #55, with unknown actions, rather than presented as a verified live national registry. Search requires a term or supported filter. Unsupported filter values fail before requests. Registry entries without geometry remain searchable. FRS registry IDs, program acronym/ID pairs, and historical feature IDs stay separate. ArcGIS geometry is requested in WGS84 with `outSR=4326`; raw NAD83 attribute fields and collection/accuracy metadata are preserved. FRS program-interest activity is not military operational status.

HTML requests validate official HTTPS hosts and each redirect, use 4-second connect / 10-second read timeouts, cap at 3 MiB, and reject missing content containers/challenge pages as schema failures. A tool budget allows up to 16 operations / 75 seconds checked before each request. Successful reads may be reused for up to ten minutes, retaining the original retrieval time and reporting cache age; failures are not cached or replaced with another source.

GIS discovery selects IDs and fetches at most 2,500 features per source in 250-feature batches, rechecking IDs. It uses the full unsimplified ROI for point/polygon intersection. Missing IDs, source changes, caps, and failures remain visible. Retrieval completeness differs from program/geometry coverage, and no atomic snapshot across requests is promised. All list tools bound page sizes to 1–100 and offsets to 0–100,000. Listings are independently paginated; compare fingerprints and restart when records change.

Notice fingerprints cover source records and retrieval status, excluding the call's `evaluated_at` timestamp. Control fingerprints cover the full document index and source retrieval status, independently of which page's PDFs were extracted; each extracted PDF has its own SHA-256 fingerprint. Cached transport reports are copied for each caller so a tool-specific parser failure does not change another tool's source status. Installation detail follows a reviewed `evidence_url` crosswalk when present, preserving the original installation identity and attributing document discovery to the evidence page.

## Evidence limits

Document filters cover fetched index titles only; the only verified category is unresolved. A title “Record of Decision” does not establish NEPA/remedy scope. Conveyance summaries preserve raw published acreage and unknown as-of dates, without manufacturing parcel transactions. Notice candidates keep missing publication/deadline/time-zone/revision state unresolved; a requested publication filter is explicitly unverified for undated records. Environmental-site parsers retain only explicit IR-site/OU groups as candidates, not loose document mentions, and need current nonempty Navy fixtures.

Control evidence follows only specifically indexed official PDF links matching control-document titles, with at most three selected documents per page, 10 MiB per file, 100 physical pages / 500,000 text characters, and a separate 15-second parser limit. It preserves title-only, oversized, image-only, parse/access failures, fingerprints, physical-page snippets, and unknown legal effect; no OCR. Site/parcel filters require verified crosswalks and otherwise report unsupported rather than guessing. Instrument/execution/recording status is not inferred from filenames.

Offer adapters use explicit table-label/official-record crosswalks for Memphis and Red River plans. Raw acreage, parcel labels, expected disposal dates, and source methods are retained. No authoritative advertised-auction adapter/crosswalk has been verified, so historical/advertised availability is not claimed. No bids, registrations, or seller contacts are performed.

Default tests are offline. Set `NEPA_BRAC_LIVE=1` to opt in to the Army planned-disposal smoke test. Captured Army content fixtures are attributed in their README; blocked-source examples are synthetic parser/error cases and do not certify those adapters. Before opening a completion PR, resolve/validate the Navy/Marine Corps, Air Force, environmental-site, notice-date, control-instrument, and advertised-offer acceptance gaps. This preparation intentionally leaves them explicit.
