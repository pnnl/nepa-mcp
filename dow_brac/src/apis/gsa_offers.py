"""Two archived GSA notices for one identified auction; no live listing state is inferred."""

import re
from datetime import date, datetime

from src.apis.adapters import fetch
from src.core.sources import WEYMOUTH_ANNOUNCEMENT, WEYMOUTH_SOFT_CLOSE, SEEDS

IFB = "https://realestatesales.gov/ATTACHMENT/REGNB/BOSTN121005001/2022.3.1.IFB.Weymouth.pdf"


def _notice(url, budget):
    content, report = fetch(url, budget)
    if content is None:
        return None, report
    paragraphs = " ".join(p.get_text(" ", strip=True) for p in content.select("p"))
    items = [li.get_text(" ", strip=True) for li in content.select("li") if not li.find("li")]
    stamp = content.select_one("time[datetime]")
    opening = url == WEYMOUTH_ANNOUNCEMENT
    # Identify the reviewed sale independently of dates: retain dated evidence
    # from the publisher, rather than replaying dates from the test fixture.
    date_pattern = r"([A-Z][a-z]+ [0-9]{1,2}, [0-9]{4})"
    pattern = (
        r"The auction opened " + date_pattern + r"(, at [0-9]{1,2}:[0-9]{2} [ap]\.m\. [A-Z]{2,4})"
        if opening
        else r"has set [A-Za-z]+, " + date_pattern + r", as the soft close date"
    )
    matches = list(re.finditer(pattern, paragraphs))
    match = matches[0] if len(matches) == 1 else None
    try:
        published = date.fromisoformat(stamp["datetime"].split("T")[0]) if stamp else None
        event_date = datetime.strptime(match[1], "%B %d, %Y").date() if match else None
    except ValueError:
        published = event_date = None
    listing = content.find(
        "a", href=re.compile(r"^https://realestatesales\.gov/gsaauctions/(?:aucpbsindx/|aucdsclnk)\?sl=BOSTN121005001$")
    )
    if not (
        published
        and event_date
        and listing
        and content.find("a", href=IFB)
        and "as Weymouth Woods and was a former housing site for the US Coast Guard" in paragraphs
        and "transferred from the U.S. Navy to the U.S. Coast Guard in 1998" in paragraphs
        and "The larger parcel is 50.31 acres, with frontage on Shea Memorial Drive" in items
        and "The smaller parcel is 0.77 acres, with access from Memorial Grove Avenue" in items
        and match
    ):
        return None, {
            **report,
            "status": "schema_error",
            "complete": False,
            "warnings": ["Archived notice no longer matches the reviewed auction, parcels and event."],
        }
    return {
        "source_url": url,
        "published_date": published.isoformat(),
        "event_date": event_date.isoformat(),
        "listing_url": listing["href"],
        "event": "auction_opened" if opening else "soft_close_announced",
        "source_date_text": match[1] + (match[2] if opening else ""),
    }, report


def historical_weymouth(record, budget):
    opening, first = _notice(WEYMOUTH_ANNOUNCEMENT, budget)
    update, second = _notice(WEYMOUTH_SOFT_CLOSE, budget)
    events = [e for e in (opening, update) if e]
    if not events:
        return [], [first, second]
    return [
        {
            "installation_id": record["installation_id"],
            "parcel_label": "Weymouth Woods",
            "evidence_type": "advertised_sale",
            "method": "GSA online auction",
            "status": "historical_advertisement",
            "final_disposition": "unknown",
            "current_availability": "unverified",
            "published_parcels": [
                {"frontage_or_access": "Shea Memorial Drive", "acres": "50.31"},
                {"frontage_or_access": "Memorial Grove Avenue", "acres": "0.77"},
            ],
            "bid_deadline": None,
            "soft_close_date": update["event_date"] if update else None,
            "events": events,
            "source_url": events[0]["source_url"],
            "published_ifb_url": IFB,
            "listing_id": events[0]["listing_url"].split("sl=")[1],
            "crosswalk_source": SEEDS["navy:south-weymouth"]["url"],
            "crosswalk_basis": "Navy BRAC records the Coast Guard housing transfer at NAS South Weymouth; "
            "GSA identifies the former housing, 1998 Navy transfer, both parcels and their common IFB. "
            "This was a subsequent GSA auction of the housing property.",
        }
    ], [first, second]
