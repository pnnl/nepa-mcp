"""Source capabilities are per adapter, not implied by a working neighboring source."""

ARMY = "https://www.denix.osd.mil/armybrac/"
FRS = "https://gispub.epa.gov/arcgis/rest/services/OEI/FRS_INTERESTS/MapServer"
HISTORICAL = "https://services.arcgis.com/hRUr1F8lE8Jq2uJo/arcgis/rest/services/milbases/FeatureServer"
ROUNDS = (1988, 1991, 1993, 1995, 2005)
SEEDS = {
    "navy:alameda": {
        "name": "Former Naval Air Station Alameda",
        "component": "navy",
        "state": "CA",
        "url": "https://www.bracpmo.navy.mil/BRAC-Bases/California/Former-Naval-Air-Station-Alameda/",
        "documents_url": "https://www.bracpmo.navy.mil/BRAC-Bases/California/Former-Naval-Air-Station-Alameda/Documents/",
    },
    "navy:roosevelt-roads": {
        "name": "Former Naval Station Roosevelt Roads",
        "component": "navy",
        "state": "PR",
        "url": "https://www.bracpmo.navy.mil/BRAC-Bases/Southeast/Former-Naval-Station-Roosevelt-Roads/",
        "notices_url": "https://www.bracpmo.navy.mil/BRAC-Bases/Southeast/Former-Naval-Station-Roosevelt-Roads/Public-Notices/",
    },
    "air_force:wurtsmith": {
        "name": "Wurtsmith",
        "component": "air_force",
        "state": "MI",
        "url": "https://www.afcec.af.mil/Home/BRAC/Wurtsmith.aspx",
    },
    "army:devens": {
        "name": "Former Fort Devens",
        "component": "army",
        "state": "MA",
        "url": "https://www.nae.usace.army.mil/Missions/Projects-Topics/Former-Fort-Devens-Environmental-Cleanup/",
        "documents_url": "https://www.nae.usace.army.mil/Missions/Projects-Topics/Former-Fort-Devens-Environmental-Cleanup/Document-Repository/",
    },
}
MANIFEST = {
    "version": "2026-10-23.1",
    "parser_version": "1 (Army verified; blocked-source parsers require captured live contracts)",
    "army_rounds": {
        "url": ARMY,
        "method": "GET HTML, content-scoped round/action groups",
        "validated": "2026-10-23",
        "coverage": "Five published Army BRAC round directories; not every installation/annex or non-BRAC excess record",
    },
    "army_evidence": {
        "url": ARMY,
        "method": "GET installation HTML and official document links",
        "validated": "2026-10-23",
        "coverage": "Source-specific documents and conveyance summaries; no executed-deed inference",
    },
    "army_planned_offers": {
        "url": ARMY + "properties-for-sale/",
        "method": "GET HTML table",
        "validated": "2026-10-23",
        "coverage": "Published plans, not advertised open auctions; exact curated aliases required",
    },
    "frs": {
        "url": FRS + "/5",
        "method": "ArcGIS ID query + bounded feature batches; outSR=4326",
        "validated": "2026-10-23",
        "coverage": "EPA BRAC interests/reference points, not a complete DoW installation registry",
    },
    "historical": {
        "url": HISTORICAL + "/0",
        "method": "Opt-in ArcGIS polygon intersections",
        "validated": "2026-10-23",
        "coverage": "2010 Base Structure Report / NTAD2014 context; not current parcels",
    },
    "navy": {
        "url": "https://www.bracpmo.navy.mil/BRAC-Bases/",
        "method": "GET official installation indexes",
        "validation_status": "HTTP 403 in this environment; source-specific parser/live validation pending",
    },
    "air_force": {
        "url": SEEDS["air_force:wurtsmith"]["url"],
        "method": "GET official portfolio pages",
        "validation_status": "HTTP 403; live validation pending",
    },
    "devens_controls": {
        "url": SEEDS["army:devens"]["documents_url"],
        "method": "Official index and bounded indexed control PDF parsing",
        "validation_status": "HTTP 403; nonempty instrument/content validation pending",
    },
    "advertised_offers": {
        "url": "https://www.realestatesales.gov/our-listing/",
        "validation_status": "No verified BRAC parcel crosswalk/authoritative auction-state contract; unsupported, not inferred from template text",
    },
}
NOTE = "BRAC association, historical geometry, remedy or conveyance milestones do not establish clean land, unrestricted use, current ownership, land availability, completed cleanup, or development suitability. Cleanup, operational status, and conveyance are separate source statements."
