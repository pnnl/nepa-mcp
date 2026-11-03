"""Two archived GSA notices for one identified auction; no live listing state is inferred."""

import re

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
    event = (
        r"The auction opened (March 1, 2022, at 2:00 p\.m\. CT)"
        if opening
        else r"has set Thursday, (June 2, 2022), as the soft close date"
    )
    match = re.search(event, paragraphs)
    # Check the reviewed parcel, source date, IFB and event together. A different sale or
    # a changed notice needs a new review; never scan generic auction-status templates.
    expected_date = "2022-03-07" if opening else "2022-05-11"
    if not (
        stamp
        and stamp["datetime"].split("T")[0] == expected_date
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
        "published_date": expected_date,
        "event": "auction_opened" if opening else "soft_close_announced",
        "source_date_text": match[1],
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
            "soft_close_date": "2022-06-02" if update else None,
            "events": events,
            "source_url": events[0]["source_url"],
            "published_ifb_url": IFB,
            "listing_id": None,
            "crosswalk_source": SEEDS["navy:south-weymouth"]["url"],
            "crosswalk_basis": "Navy BRAC records the Coast Guard housing transfer at NAS South Weymouth; "
            "GSA identifies the former housing, 1998 Navy transfer, both parcels and their common IFB. "
            "This was a subsequent GSA auction of the housing property.",
        }
    ], [first, second]
