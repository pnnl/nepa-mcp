/* Agency marks lead; the smaller line highlights one dataset. Full coverage
 * remains in Data Sources & Licensing. IDs are checked against SITE_DATA. */
'use strict';

var AGENCY_SOURCES = [
    {
        id: 'usfws', name: 'USFWS', logo: 'usfws.svg', url: 'https://www.fws.gov/',
        datasets: 'IPaC',
        coverage: 'IPaC species, migratory birds, wetlands, critical habitat and refuges; Critical Habitat and National Wildlife Refuge System map services.',
        servers: ['ipac'], layers: ['critical_habitat', 'wildlife_refuges']
    },
    {
        id: 'noaa', name: 'NOAA Fisheries', logo: 'noaa.png', url: 'https://www.fisheries.noaa.gov/',
        datasets: 'Essential Fish Habitat',
        coverage: 'EFH, HAPC, Pacific salmon watershed EFH, and HMS/CPS/groundfish EFH; West Coast ESA species ranges and critical habitat; NOAA All Species Ranges; the dated 2021-09-04 critical-habitat snapshot; Atlantic salmon EFH/HAPC; PCSRF recovery projects.',
        servers: ['efh', 'esa_ranges', 'noaa', 'pcsrf'], layers: []
    },
    {
        id: 'epa', name: 'EPA', logo: 'epa.svg', url: 'https://www.epa.gov/',
        datasets: 'Brownfields',
        coverage: 'ACRES Brownfields grant-program properties; AQS monitoring stations, annual criteria pollutants and baseline screening; NEPAssist environmental screening.',
        servers: ['epa_acres', 'epa_aqs', 'nepa_assist'], layers: []
    },
    {
        id: 'fema', name: 'FEMA', logo: 'fema.svg', url: 'https://www.fema.gov/',
        datasets: 'Flood hazard maps',
        coverage: 'National Flood Hazard Layer: flood hazard zones, levees and water areas.',
        servers: ['fema_nfhl'], layers: []
    },
    {
        id: 'blm', name: 'BLM', logo: 'blm.svg', url: 'https://www.blm.gov/',
        datasets: 'Land & mineral records',
        coverage: 'Land-use plans, wilderness areas and monuments; MLRS land-use authorizations, mineral operations and energy leases; planning revisions, wilderness study areas, monuments/NCAs, mapped no-surface-occupancy restrictions, sage-grouse habitat, sagebrush focal areas, wild horse/burro areas, national trails, LWCF lands and Western U.S. EIS boundaries.',
        servers: ['blm', 'blm_mlrs'],
        layers: ['blm_land_use_plans', 'blm_plans_in_progress', 'blm_wilderness_study_areas', 'blm_national_monuments', 'blm_rights_of_way', 'grsg_habitat', 'sagebrush_focal_areas', 'wild_horse_hma', 'national_trails', 'lwcf_lands', 'eis_boundaries']
    },
    {
        id: 'usgs', name: 'USGS', logo: 'usgs.png', darken: true, url: 'https://www.usgs.gov/',
        datasets: 'Protected areas',
        coverage: 'PAD-US protected-area records and federal-manager map subsets, including BLM-managed lands; NHD lakes, reservoirs, estuaries, ice masses, perennial streams, stream areas and water infrastructure. The BLM-managed land subset retains USGS as its publisher.',
        servers: ['padus'], layers: ['federal_lands', 'blm_managed_lands', 'nhd_lakes', 'nhd_reservoirs', 'nhd_estuaries', 'nhd_ice_masses', 'nhd_perennial_streams', 'nhd_stream_areas', 'nhd_infrastructure']
    },
    {
        id: 'census', name: 'Census Bureau', logo: 'census.svg', url: 'https://www.census.gov/',
        datasets: 'American Community Survey',
        coverage: 'ACS socioeconomic profiles; TIGERweb county boundaries; AIANNHA tribal geography.',
        servers: ['census', 'tigerweb_counties', 'tribal'], layers: ['counties', 'tribal_lands']
    },
    {
        id: 'nrcs', name: 'USDA-NRCS', logo: 'nrcs.png', url: 'https://www.nrcs.usda.gov/',
        datasets: 'Soil survey',
        coverage: 'SSURGO through Soil Data Access: map units, soil screening indicators and farmland classifications.',
        servers: ['nrcs_soils'], layers: []
    },
    {
        id: 'usfs', name: 'USDA Forest Service', logo: 'usfs.svg', url: 'https://www.fs.usda.gov/',
        datasets: 'National forest boundaries',
        coverage: 'National Forest System boundaries and Inventoried Roadless Areas under the 2001 Rule.',
        servers: [], layers: ['usfs_forests', 'usfs_roadless_areas']
    },
    {
        id: 'nps', name: 'National Park Service', logo: 'nps.png', url: 'https://www.nps.gov/',
        datasets: 'National Register of Historic Places',
        coverage: 'National Register of Historic Places listed properties; National Park Service unit boundaries.',
        servers: ['nrhp'], layers: ['nps_boundaries']
    },
    {
        id: 'nifc', name: 'NIFC', logo: 'nifc.svg', url: 'https://www.nifc.gov/',
        datasets: 'Fire perimeters',
        coverage: 'National Interagency Fire Center interagency historical fire perimeters.',
        servers: [], layers: ['fire_perimeters']
    },
    {
        id: 'nara-gpo', name: 'NARA / GPO', logo: 'nara.png', url: 'https://www.archives.gov/',
        datasets: 'Federal Register',
        coverage: 'eCFR, Federal Register documents and rulemakings, executive orders, amendment history and version comparisons. The National Archives mark represents the Office of the Federal Register; GPO is the publishing partner.',
        servers: ['cfr'], layers: []
    },
    {
        id: 'dot', name: 'U.S. DOT / Permitting Council', logo: 'dot-symbol.svg', darken: true, url: 'https://www.transportation.gov/PermittingImprovementCenter',
        datasets: 'Permitting Dashboard',
        coverage: 'Permitting Dashboard project records, tracked reviews, timetables and milestones. FPISC publishes the dataset; DOT manages the Dashboard on behalf of the Permitting Council. Coverage is limited to Dashboard-listed projects.',
        servers: ['permitting_dashboard'], layers: []
    },
    {
        id: 'usace', name: 'U.S. Army Corps of Engineers', logo: 'usace.svg', url: 'https://www.usace.army.mil/',
        datasets: 'Regulatory districts',
        coverage: 'USACE regulatory district boundaries, wetland delineation regions and wetland subregions.',
        servers: ['usace'], layers: ['usace_districts', 'wetland_regions', 'wetland_subregions']
    },
    {
        id: 'gbif', name: 'GBIF', logo: 'gbif.png', url: 'https://www.gbif.org/',
        datasets: 'Species occurrences',
        coverage: 'Georeferenced species occurrence records and county-based species searches. Individual records retain their contributing dataset publisher and license.',
        servers: ['gbif'], layers: []
    }
];

(function () {
    function initAgencySources() {
        var section = document.getElementById('sources');
        if (!section) return;
        var frame = document.getElementById('agency-frame');
        var controls = document.getElementById('agency-controls');
        var pause = document.getElementById('agency-pause');
        var narrow = matchMedia('(max-width: 760px)');
        var reduced = matchMedia('(prefers-reduced-motion: reduce)');
        var size = reduced.matches ? AGENCY_SOURCES.length : narrow.matches ? 4 : 5;
        var paused = false;
        var visible = false;
        var timer;
        var slots = [];
        var nextSource = size % AGENCY_SOURCES.length;

        function element(tag, className, text) {
            var el = document.createElement(tag);
            if (className) el.className = className;
            if (text) el.textContent = text;
            return el;
        }
        function logo(source) {
            var wrap = element('span', 'agency-logo' + (source.darken ? ' agency-logo-darken' : ''));
            var img = document.createElement('img');
            img.src = 'assets/images/agencies/' + source.logo;
            img.alt = ''; // The adjacent visible agency name supplies the label.
            img.width = 132;
            img.height = 68;
            img.decoding = 'async';
            wrap.appendChild(img);
            return wrap;
        }

        function tile(source) {
            var link = element('a', 'agency-tile');
            link.href = source.url;
            link.target = '_blank';
            link.rel = 'noopener noreferrer';
            link.dataset.sourceId = source.id;
            link.append(logo(source), element('span', 'agency-name', source.name), element('span', 'agency-datasets', source.datasets));
            return link;
        }

        function canAnimate() {
            return !paused && !reduced.matches && visible && !document.hidden;
        }

        function settle() {
            slots.forEach(function (slot) { if (slot.finish) slot.finish(); });
        }

        function schedule(first) {
            clearTimeout(timer);
            controls.hidden = reduced.matches;
            pause.dataset.paused = String(paused);
            pause.setAttribute('aria-label', paused ? 'Play agency animation' : 'Pause agency animation');
            pause.title = paused ? 'Play animation' : 'Pause animation';
            if (canAnimate()) {
                // The Business-page logo reel uses a short staggered wave,
                // followed by a hold. Keep that rhythm across the whole row.
                timer = setTimeout(tick, first === true ? 1500 : 3000);
            } else {
                settle();
            }
        }

        function replace(slot, sourceIndex, delay) {
            var outgoing = slot.link;
            var incoming = tile(AGENCY_SOURCES[sourceIndex]);
            slot.outgoingIndex = slot.sourceIndex;
            slot.sourceIndex = sourceIndex;
            // During the crossfade there is one accessible/clickable source,
            // not two overlapping links. Hovered or focused slots never turn.
            outgoing.inert = true;
            outgoing.setAttribute('aria-hidden', 'true');
            incoming.inert = true;
            incoming.style.opacity = '0';
            slot.node.classList.add('agency-moving');
            slot.node.appendChild(incoming);
            var animations = [];
            function finish() {
                if (!slot.finish) return;
                slot.finish = null;
                animations.forEach(function (animation) {
                    animation.onfinish = null;
                    animation.cancel();
                });
                outgoing.remove();
                incoming.style.opacity = '';
                incoming.inert = false;
                slot.link = incoming;
                slot.outgoingIndex = null;
                slot.node.classList.remove('agency-moving');
            }
            slot.finish = finish;
            if (typeof incoming.animate !== 'function' || reduced.matches) {
                finish();
                return;
            }
            var timing = { duration: 400, delay: delay, easing: 'cubic-bezier(.17, .17, .3, 1)', fill: 'both' };
            animations.push(outgoing.animate([
                { opacity: 1, transform: 'translateY(0)' },
                { opacity: 0, transform: 'translateY(-40px)' }
            ], timing));
            var entering = incoming.animate([
                { opacity: 0, transform: 'translateY(40px)' },
                { opacity: 1, transform: 'translateY(0)' }
            ], timing);
            animations.push(entering);
            entering.onfinish = finish;
        }

        function tick() {
            if (!canAnimate()) return;
            slots.forEach(function (slot, index) {
                if (slot.hovered || slot.finish || slot.node.contains(document.activeElement)) return;
                // Include outgoing marks until their transitions finish so a
                // hovered position cannot introduce duplicate visible logos.
                while (slots.some(function (other) {
                    return other.sourceIndex === nextSource || other.outgoingIndex === nextSource;
                })) {
                    nextSource = (nextSource + 1) % AGENCY_SOURCES.length;
                }
                replace(slot, nextSource, (index + 1) * 120);
                nextSource = (nextSource + 1) % AGENCY_SOURCES.length;
            });
            schedule();
        }

        function buildSlots() {
            clearTimeout(timer);
            settle();
            var previous = slots.map(function (slot) { return slot.sourceIndex; });
            var hadFocus = frame.contains(document.activeElement);
            slots = [];
            frame.replaceChildren();
            for (var index = 0; index < size; index += 1) {
                var sourceIndex = previous[index];
                if (sourceIndex === undefined) {
                    sourceIndex = 0;
                    while (slots.some(function (slot) { return slot.sourceIndex === sourceIndex; })) sourceIndex += 1;
                }
                var slot = { node: element('div', 'agency-slot'), sourceIndex: sourceIndex, outgoingIndex: null, hovered: false, finish: null };
                slot.link = tile(AGENCY_SOURCES[sourceIndex]);
                slot.node.appendChild(slot.link);
                // Capture this slot rather than pausing the entire row on hover.
                (function (current) {
                    current.node.addEventListener('mouseenter', function () {
                        current.hovered = true;
                        if (current.finish) current.finish();
                    });
                    current.node.addEventListener('mouseleave', function () { current.hovered = false; });
                }(slot));
                slots.push(slot);
                frame.appendChild(slot.node);
            }
            if (hadFocus) slots[0].link.focus({ preventScroll: true });
            schedule(true);
        }

        pause.addEventListener('click', function () { paused = !paused; schedule(); });
        frame.addEventListener('focusin', function () { paused = true; schedule(); });
        document.addEventListener('visibilitychange', function () { schedule(true); });
        reduced.addEventListener('change', function () {
            size = reduced.matches ? AGENCY_SOURCES.length : narrow.matches ? 4 : 5;
            buildSlots();
        });
        narrow.addEventListener('change', function () {
            size = reduced.matches ? AGENCY_SOURCES.length : narrow.matches ? 4 : 5;
            buildSlots();
        });
        new IntersectionObserver(function (records) {
            var entering = !visible && records[0].isIntersecting;
            visible = records[0].isIntersecting;
            schedule(entering);
        }, { threshold: .2 }).observe(frame);

        document.getElementById('agency-fallback').hidden = true;
        buildSlots();
    }
    if (typeof document === 'undefined') return; // Allows a data-coverage check in Node.
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initAgencySources);
    else initAgencySources();
}());
