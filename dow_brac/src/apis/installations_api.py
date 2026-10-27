"""Published source records are stable local identities; aliases never silently merge installations."""

import re
from src.apis.adapters import Budget, fetch, links
from src.core.normalization import fingerprint, output, page, text
from src.core.sources import ARMY, ROUNDS, SEEDS


def local_id(url):
    return "army:" + fingerprint(url.rstrip("/"))[:16]


def registry(budget=None):
    budget = budget or Budget()
    records = {}
    reports = []
    for year in ROUNDS:
        url = f"{ARMY}brac-{year}/"
        content, report = fetch(url, budget)
        reports.append(report)
        if content is None:
            continue
        found = 0
        for section in content.select(".usa-accordion__content"):
            heading = section.find_previous_sibling()
            category = heading.get_text(" ", strip=True) if heading else "unknown"
            for li in section.select("li"):
                # Ignore nested explanatory links to receiving installations.
                if li.find_parent("li") is not None:
                    continue
                a = li.find("a", recursive=False)
                if a is None:
                    continue
                label = a.get_text(" ", strip=True)
                href = a.get("href", "")
                name_state = re.fullmatch(r"(.+),\s*([A-Z]{2})", label)
                if not name_state:
                    continue
                from urllib.parse import urljoin
                from src.core.normalization import source_url

                target = source_url(urljoin(url, href)) if href not in {"", "#"} else None
                # Preserve records with no linked detail as directory-scoped identities.
                identity = local_id(target or url + "#" + label)
                record = records.setdefault(
                    identity,
                    {
                        "installation_id": identity,
                        "name": name_state[1],
                        "aliases": [],
                        "state": name_state[2],
                        "component": "army",
                        "url": target,
                        "actions": [],
                        "identity_basis": "Exact official source URL, or directory row when no detail link; local identifier is not a government-wide BRAC ID",
                        "geometry_available": False,
                        "identity_crosswalks": [],
                    },
                )
                action = {
                    "round": year,
                    "source_category": category,
                    "action": "closure"
                    if "Closure" in category
                    else "realignment"
                    if "Realignment" in category
                    else "impacted_unknown_role",
                    "role": "not established",
                    "source_url": url,
                    "source_text": li.get_text(" ", strip=True),
                    "program": "BRAC",
                }
                if action not in record["actions"]:
                    record["actions"].append(action)
                found += 1
        if not found:
            report.update(
                status="schema_error",
                complete=False,
                warnings=["No expected round/action groups parsed; source schema may have changed"],
            )
    # These are explicit limited research entrypoints, not fabricated live installation records.
    for identity, seed in SEEDS.items():
        records[identity] = {
            **seed,
            "installation_id": identity,
            "aliases": [],
            "actions": [],
            "identity_basis": "Curated official research entrypoint from issue #55; current program/action evidence requires retrieval",
            "geometry_available": False,
            "identity_crosswalks": [],
        }
    # Reviewed official page explicitly identifies the same installation and BRAC 1995 action.
    round_url = ARMY + "brac-1995/fort-indiantown-gap/"
    identity = local_id(round_url)
    if identity in records:
        records[identity]["documents_url"] = ARMY + "pennsylvania-reserve-component/fort-indiantown-gap/"
        records[identity]["evidence_url"] = records[identity]["documents_url"]
        records[identity]["identity_crosswalks"].append(
            {
                "source_url": round_url,
                "target_url": records[identity]["documents_url"],
                "basis": "Reviewed official page explicitly names Fort Indiantown Gap and BRAC 1995, with a 1995 Commission record; verified 2026-10-23",
            }
        )
    umatilla = local_id(ARMY + "brac-2005/umatilla-chemical-depot-2005/")
    if umatilla in records:
        records[umatilla]["notices_url"] = ARMY
        records[umatilla]["notice_link_title_prefix"] = "Umatilla Chemical Depot "
    return list(records.values()), reports


def validate_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"(?:army|navy|air_force):[a-z0-9-]{1,64}", value):
        raise ValueError("installation_id must be a source-namespaced ID returned by installation search")
    return value


def resolve(installation_id, budget=None):
    validate_id(installation_id)
    records, reports = registry(budget)
    return next((r for r in records if r["installation_id"] == installation_id), None), reports


def search_brac_installations(
    query=None, component=None, state=None, brac_round=None, max_results=100, result_offset=0
):
    page(max_results, result_offset)
    query = text(query, "query", True)
    if component not in {None, "army", "navy", "marine_corps", "air_force"}:
        raise ValueError("component must be army, navy, marine_corps, or air_force")
    if state is not None:
        state = text(state, "state").upper()
        if state not in set(
            "AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY PR GU VI AS MP".split()
        ):
            raise ValueError("state must be a US state/territory postal code")
    if brac_round is not None and (type(brac_round) is not int or brac_round not in ROUNDS):
        raise ValueError("brac_round must be 1988, 1991, 1993, 1995, or 2005")
    if not any([query, component, state, brac_round]):
        raise ValueError("At least one search term or filter is required")
    records, reports = registry()
    matches = []
    for record in records:
        if query and query.casefold() not in record["name"].casefold():
            continue
        if component and component != record["component"]:
            continue
        if state and state != record["state"]:
            continue
        actions = [a for a in record["actions"] if brac_round is None or a["round"] == brac_round]
        if brac_round is not None and not actions:
            continue
        matches.append({**record, "matched_actions": actions})
    # Curated blocked-source entries cannot certify complete cross-service coverage.
    warnings = [
        "Registry covers parsed Army round directories plus a few explicitly labelled research entrypoints; Navy/Marine Corps and Air Force inventories remain unverified. Different source URLs are unresolved identities even if names resemble one another."
    ]
    matches.sort(key=lambda r: (r["name"].casefold(), r["installation_id"]))
    return output(matches, reports, warnings, max_results, result_offset)


def get_brac_installation(installation_id):
    budget = Budget()
    record, reports = resolve(installation_id, budget)
    if record is None:
        return output([], reports, ["No matching local source identity; narrow or repeat installation search"])
    url = record.get("evidence_url") or record.get("url")
    if not url:
        return output([record], reports, ["Directory row has no supported detail URL"])
    content, report = fetch(url, budget)
    reports.append(report)
    detail = {
        **record,
        "evidence_url": url,
        "cleanup_statements": [],
        "conveyance_statements": [],
        "operational_status": "not established",
        "responsible_office": {
            "source_url": ARMY + "contact-poc/" if record["component"] == "army" else record["url"],
            "assignment": "Published program entrypoint only; individual office not inferred",
        },
        "documents": [],
    }
    if content is not None:
        detail["documents"] = [r for r in links(content, url) if ".pdf" in r["url"].lower()]
        detail["published_page_text"] = content.get_text(" ", strip=True)[:16000]
        detail["page_text_complete"] = len(content.get_text(" ", strip=True)) <= 16000
    return output(
        [detail], reports, registry_scope="Source records, not a comprehensive national installation/parcel registry"
    )
