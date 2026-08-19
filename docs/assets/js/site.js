/**
 * NEPA MCP Toolkit - site behavior
 *
 * Every count and label rendered here comes from SITE_DATA, which is generated
 * from the server registry and each server's live MCP tools/list contract. See
 * scripts/generate_site_data.py.
 */

'use strict';

var DATA = typeof SITE_DATA !== 'undefined' ? SITE_DATA : null;

var GITHUB_BLOB = 'https://github.com/pnnl/nepa-mcp/blob/main/';

/* ============================================
   Static page content
   ============================================ */

var FEATURE_CARDS = [
    {
        icon: 'fa-shield-halved',
        color: 'teal',
        title: 'Environmental Screening',
        description: 'Jurisdictional, habitat, water, flood, cultural, social, and economic context for a project area.'
    },
    {
        icon: 'fa-database',
        color: 'emerald',
        title: 'Public Federal Data',
        description: 'Up-to-date information from 12 federal agencies, read straight from their public services.'
    },
    {
        icon: 'fa-gavel',
        color: 'slate',
        title: 'Regulatory Research',
        description: 'Federal regulations, rulemakings, and executive actions, with the history behind each change.'
    },
    {
        icon: 'fa-layer-group',
        color: 'violet',
        title: 'Interactive Visualization',
        description: 'Maps and GeoJSON exports with per-layer sources for review and analysis.'
    }
];

var TRANSFORM_ROWS = [
    {
        before: 'Data siloed across a dozen federal agencies',
        after: 'One protocol, 19 focused servers'
    },
    {
        before: 'Weeks of manual data collection',
        after: 'Project-area screening in one request'
    },
    {
        before: 'Inconsistent formats, no provenance',
        after: 'Structured results with cited sources'
    },
    {
        before: 'Easy to miss a jurisdiction',
        after: 'Every layer reported, nothing silent'
    }
];

/**
 * Client configuration options. The CLI writes to these same paths; see
 * nepa_mcp/clients.py for the authoritative targets. `path` is the literal file
 * and stays monospaced; `where` is the prose that follows it, and says which
 * directory decides the location.
 */
var CLIENT_CONFIGS = [
    {
        id: 'claude',
        label: 'Claude Code',
        command: 'nepa-mcp configure claude',
        path: '.mcp.json',
        where: 'in the directory you run it from'
    },
    {
        id: 'vscode',
        label: 'VS Code',
        command: 'nepa-mcp configure vscode',
        path: '.vscode/mcp.json',
        where: 'in the workspace directory you run it from'
    },
    {
        id: 'codex',
        label: 'Codex',
        command: 'nepa-mcp configure codex',
        path: '~/.codex/config.toml',
        where: '— one global file, so any directory works',
        note: 'Prefer the plugin below to register every server and the screening skill in one step.'
    }
];

var DOC_CARDS = [
    {
        icon: 'fas fa-list-check',
        color: 'teal',
        title: 'MCP Tool Catalog',
        description: 'The complete server and tool inventory.',
        url: GITHUB_BLOB + 'docs/mcp-tool-catalog.md'
    },
    {
        icon: 'fas fa-map-location-dot',
        color: 'violet',
        title: 'Map Composer Guide',
        description: 'The 32-layer catalog, profiles, and output behavior.',
        url: GITHUB_BLOB + 'docs/map-composer.md'
    },
    {
        icon: 'fas fa-location-crosshairs',
        color: 'emerald',
        title: 'Geographic Inputs',
        description: 'Project-area constraints and coverage behavior.',
        url: GITHUB_BLOB + 'docs/geographic-inputs-and-data-behavior.md'
    },
    {
        icon: 'fas fa-scale-balanced',
        color: 'amber',
        title: 'Data Sources & Licensing',
        description: 'Upstream services and license signals per server.',
        url: GITHUB_BLOB + 'docs/mcp-data-source-licenses.md'
    }
];

/**
 * What each server contributes to a review, keyed by registry name. Titles and
 * agencies come from SITE_DATA; this adds the review-facing coverage shown on
 * the back of each flip card.
 */
var SERVER_COVERAGE = {
    blm: {
        icon: 'fa-mountain',
        items: [
            ['Land use plan conformance', 'Approved RMPs and plans in revision'],
            ['Wilderness Act areas', 'Designated wilderness and study areas'],
            ['National Monuments', 'Monuments and Conservation Areas']
        ]
    },
    census: {
        icon: 'fa-users',
        items: [
            ['Socioeconomic baseline', 'ACS 5-Year indicators by county'],
            ['Income and employment', 'Poverty, labor force, and industry mix'],
            ['Affected population', 'Demographics for the project area']
        ]
    },
    cfr: {
        icon: 'fa-gavel',
        items: [
            ['Federal regulations', 'Verbatim CFR text at any depth'],
            ['Rulemakings', 'Federal Register documents and amendments'],
            ['Executive actions', 'Executive orders and version history']
        ]
    },
    efh: {
        icon: 'fa-fish',
        items: [
            ['Essential Fish Habitat', 'EFH areas and HAPC designations'],
            ['Salmon habitat', 'Salmon EFH by HUC-8 watershed'],
            ['Managed species', 'HMS, coastal pelagic, and groundfish']
        ]
    },
    epa_aqs: {
        icon: 'fa-wind',
        items: [
            ['Air quality baseline', 'Monitor readings for criteria pollutants'],
            ['NAAQS comparison', 'Screening against national standards'],
            ['Monitoring network', 'Stations near the project area']
        ]
    },
    esa_ranges: {
        icon: 'fa-water',
        items: [
            ['ESA-listed ranges', 'Salmon and steelhead by HUC-12'],
            ['Watershed context', 'Range overlap with the project area'],
            ['Consultation triggers', 'Early signal for ESA review']
        ]
    },
    fema_nfhl: {
        icon: 'fa-house-flood-water',
        items: [
            ['Flood hazard zones', 'National Flood Hazard Layer zones'],
            ['Levees', 'Mapped levee systems'],
            ['Water areas', 'Rivers, lakes, and mapped water']
        ]
    },
    gbif: {
        icon: 'fa-binoculars',
        items: [
            ['Species occurrences', 'Georeferenced observation records'],
            ['County presence', 'Threatened and endangered species lists'],
            ['Observation history', 'Records filtered by year']
        ]
    },
    gis: {
        icon: 'fa-draw-polygon',
        items: [
            ['Project area buffer', 'Region of interest from a coordinate'],
            ['Area calculations', 'Square miles and acres'],
            ['GeoJSON geometry', 'Boundary for downstream tools']
        ]
    },
    ipac: {
        icon: 'fa-dove',
        items: [
            ['ESA species', 'Listed species and critical habitat'],
            ['Migratory birds', 'Birds of conservation concern'],
            ['Wetlands and refuges', 'NWI wetlands and refuge lands']
        ]
    },
    map_composer: {
        icon: 'fa-layer-group',
        items: [
            ['Interactive maps', '32 overlays with independent controls'],
            ['GeoJSON export', 'One file for QGIS and ArcGIS'],
            ['Source provenance', 'Per-layer publisher and status']
        ]
    },
    nepa_assist: {
        icon: 'fa-leaf',
        items: [
            ['Multi-category screening', 'Aggregated NEPAssist indicators'],
            ['Water and air flags', 'Impaired waters and air concerns'],
            ['Contaminated sites', 'Regulated and cleanup locations']
        ]
    },
    noaa: {
        icon: 'fa-fish-fins',
        items: [
            ['Critical habitat', 'West Coast ESA designations'],
            ['Marine species', 'Habitat overlap with the project area'],
            ['Consultation context', 'Input for NOAA coordination']
        ]
    },
    nrhp: {
        icon: 'fa-landmark-dome',
        items: [
            ['Historic properties', 'National Register listed locations'],
            ['Section 106 screening', 'Early signal for NHPA review'],
            ['Cultural resources', 'Properties near the project area']
        ]
    },
    padus: {
        icon: 'fa-tree',
        items: [
            ['Protected areas', 'PAD-US 4.1 owner and manager records'],
            ['Land ownership', 'Federal, state, local, and private'],
            ['Management context', 'Designations across the area']
        ]
    },
    pcsrf: {
        icon: 'fa-otter',
        items: [
            ['Species ranges', 'NOAA range records for the area'],
            ['Critical habitat', 'A 2021 designation snapshot'],
            ['Recovery projects', 'PCSRF salmon restoration work']
        ]
    },
    tigerweb_counties: {
        icon: 'fa-map-location-dot',
        items: [
            ['County jurisdiction', 'Counties intersecting the area'],
            ['Scoping contacts', 'Local governments to notify'],
            ['Administrative context', 'Basis for county-level data']
        ]
    },
    tribal: {
        icon: 'fa-landmark',
        items: [
            ['Tribal lands', 'AIANNHA geographic areas'],
            ['Early coordination', 'Context for government-to-government outreach'],
            ['Jurisdictional overlap', 'Areas intersecting the project']
        ]
    },
    usace: {
        icon: 'fa-water',
        items: [
            ['Section 404 jurisdiction', 'Regulatory district for permitting'],
            ['Wetland delineation', 'Regional supplement boundaries'],
            ['Subregion context', 'Finer wetland classifications']
        ]
    }
};

/* ============================================
   Utilities
   ============================================ */

/**
 * Create an element with optional class name and text content.
 * @param {string} tag
 * @param {string} [className]
 * @param {string} [text]
 * @returns {HTMLElement}
 */
function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) {
        node.className = className;
    }
    if (text !== undefined && text !== null) {
        node.textContent = text;
    }
    return node;
}

/**
 * Debounce a function so rapid input produces one render.
 * @param {Function} fn
 * @param {number} wait
 * @returns {Function}
 */
function debounce(fn, wait) {
    var timer = null;
    return function () {
        var args = arguments;
        var context = this;
        if (timer) {
            window.clearTimeout(timer);
        }
        timer = window.setTimeout(function () {
            timer = null;
            fn.apply(context, args);
        }, wait);
    };
}

/**
 * Treat Enter and Space as activation on non-button elements.
 * @param {HTMLElement} node
 * @param {Function} handler
 */
function onActivate(node, handler) {
    node.addEventListener('click', handler);
    node.addEventListener('keydown', function (event) {
        if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            handler(event);
        }
    });
}

function prefersReducedMotion() {
    return window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/**
 * Copy a code block's text to the clipboard with visual feedback.
 * @param {Event} e
 * @param {string} elementId
 */
function copyCode(e, elementId) {
    var codeElement = document.getElementById(elementId);
    var button = e.target.closest('button');
    if (!codeElement || !button) {
        return;
    }

    var code = codeElement.textContent;
    var originalHTML = button.innerHTML;

    function succeed() {
        button.innerHTML = '<i class="fas fa-check mr-2"></i>Copied';
        button.classList.remove('bg-slate-700/90', 'hover:bg-slate-600');
        button.classList.add('bg-emerald-600');
        window.setTimeout(function () {
            button.innerHTML = originalHTML;
            button.classList.remove('bg-emerald-600');
            button.classList.add('bg-slate-700/90', 'hover:bg-slate-600');
        }, 2500);
    }

    function fallback() {
        var textArea = document.createElement('textarea');
        textArea.value = code;
        textArea.style.position = 'fixed';
        textArea.style.left = '-9999px';
        document.body.appendChild(textArea);
        textArea.select();
        try {
            document.execCommand('copy');
            succeed();
        } catch (err) {
            button.innerHTML = '<i class="fas fa-triangle-exclamation mr-2"></i>Copy failed';
            window.setTimeout(function () {
                button.innerHTML = originalHTML;
            }, 2500);
        }
        document.body.removeChild(textArea);
    }

    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(code).then(succeed, fallback);
    } else {
        fallback();
    }
}

/* ============================================
   Static component rendering
   ============================================ */

function renderReleaseMetadata() {
    if (!DATA || !DATA.release) {
        return;
    }

    Array.prototype.forEach.call(document.querySelectorAll('[data-release-version]'), function (node) {
        node.textContent = DATA.release.version;
    });
    Array.prototype.forEach.call(document.querySelectorAll('[data-license-name]'), function (node) {
        node.textContent = DATA.release.licenseName;
    });
}

function renderFeatureCards() {
    var grid = document.getElementById('features-grid');
    if (!grid) {
        return;
    }
    FEATURE_CARDS.forEach(function (feature, index) {
        var card = el('div', 'text-center space-y-3 animate-on-scroll' + (index > 0 ? ' delay-' + index * 100 : ''));
        var iconWrap = el('div', 'w-16 h-16 mx-auto bg-' + feature.color + '-50 rounded-2xl flex items-center justify-center');
        var icon = el('i', 'fas ' + feature.icon + ' text-' + feature.color + '-600 text-2xl');
        icon.setAttribute('aria-hidden', 'true');
        iconWrap.appendChild(icon);
        card.appendChild(iconWrap);
        card.appendChild(el('h3', 'text-lg font-semibold text-ink', feature.title));
        card.appendChild(el('p', 'text-slate-600 text-sm leading-relaxed', feature.description));
        grid.appendChild(card);
    });
}

/**
 * Render the client configuration tabs and their panels.
 */
function renderClientConfigs() {
    var tabs = document.getElementById('client-tabs');
    var panels = document.getElementById('client-panels');
    if (!tabs || !panels) {
        return;
    }

    function select(id) {
        Array.prototype.forEach.call(tabs.querySelectorAll('.filter-chip'), function (tab) {
            tab.setAttribute('aria-selected', tab.dataset.client === id ? 'true' : 'false');
            tab.setAttribute('aria-pressed', tab.dataset.client === id ? 'true' : 'false');
            tab.tabIndex = tab.dataset.client === id ? 0 : -1;
        });
        Array.prototype.forEach.call(panels.children, function (panel) {
            panel.hidden = panel.dataset.client !== id;
        });
    }

    CLIENT_CONFIGS.forEach(function (client, index) {
        var tab = el('button', 'filter-chip', client.label);
        tab.type = 'button';
        tab.dataset.client = client.id;
        tab.setAttribute('role', 'tab');
        tab.setAttribute('aria-selected', index === 0 ? 'true' : 'false');
        tab.setAttribute('aria-pressed', index === 0 ? 'true' : 'false');
        tab.setAttribute('aria-controls', 'client-panel-' + client.id);
        tab.tabIndex = index === 0 ? 0 : -1;
        tab.addEventListener('click', function () {
            select(client.id);
        });
        // Arrow keys move between tabs, as expected of a tablist.
        tab.addEventListener('keydown', function (event) {
            var step = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0;
            if (!step) {
                return;
            }
            event.preventDefault();
            var next = CLIENT_CONFIGS[(index + step + CLIENT_CONFIGS.length) % CLIENT_CONFIGS.length];
            select(next.id);
            tabs.querySelector('[data-client="' + next.id + '"]').focus();
        });
        tabs.appendChild(tab);

        var panel = el('div');
        panel.id = 'client-panel-' + client.id;
        panel.dataset.client = client.id;
        panel.setAttribute('role', 'tabpanel');
        panel.hidden = index !== 0;

        var cliLabel = el('p', 'text-xs text-slate-500 mb-2');
        cliLabel.appendChild(el('span', null, 'Writes to '));
        cliLabel.appendChild(el('code', 'text-teal-800', client.path));
        if (client.where) {
            cliLabel.appendChild(el('span', null, ' ' + client.where + '.'));
        }
        panel.appendChild(cliLabel);

        var cliId = 'client-cli-' + client.id;
        panel.appendChild(buildCodeBlock(cliId, client.command, 'text-xs', 'p-4'));

        if (client.note) {
            panel.appendChild(el('p', 'text-xs text-slate-500 mt-3 leading-relaxed', client.note));
        }

        panels.appendChild(panel);
    });

    Array.prototype.forEach.call(document.querySelectorAll('[data-client-target]'), function (link) {
        link.addEventListener('click', function () {
            select(link.dataset.clientTarget);
        });
    });
}

/**
 * Build a copyable code block matching the markup used elsewhere on the page.
 * @param {string} id
 * @param {string} code
 * @param {string} textClass
 * @param {string} padClass
 * @returns {HTMLElement}
 */
function buildCodeBlock(id, code, textClass, padClass) {
    var wrapper = el('div', 'code-block rounded-xl overflow-hidden shadow-inner');

    var button = el('button', 'copy-button bg-slate-700/90 hover:bg-slate-600 text-white px-3 py-1.5 rounded text-xs font-medium');
    button.type = 'button';
    button.innerHTML = '<i class="fas fa-copy mr-1" aria-hidden="true"></i>Copy';
    button.addEventListener('click', function (event) {
        copyCode(event, id);
    });
    wrapper.appendChild(button);

    var pre = el('pre', padClass + ' text-slate-100 ' + textClass + ' leading-relaxed overflow-x-auto');
    pre.id = id;
    pre.appendChild(el('code', null, code));
    wrapper.appendChild(pre);

    return wrapper;
}

function renderTransformRows() {
    var container = document.getElementById('transform-rows');
    if (!container) {
        return;
    }
    TRANSFORM_ROWS.forEach(function (row) {
        var wrapper = el('div', 'transform-row group flex items-center py-3 px-4 rounded-xl bg-white/5 hover:bg-white/10 transition-all duration-300 border border-white/10 hover:border-teal-500/30');
        wrapper.appendChild(el('span', 'flex-1 text-right text-slate-400 text-sm pr-4 group-hover:text-slate-300 transition-colors', row.before));

        var chevronWrap = el('div', 'w-6 h-6 rounded-full bg-teal-500/20 flex items-center justify-center flex-shrink-0');
        var chevron = el('i', 'fas fa-chevron-right text-teal-300 text-xs');
        chevron.setAttribute('aria-hidden', 'true');
        chevronWrap.appendChild(chevron);
        wrapper.appendChild(chevronWrap);

        wrapper.appendChild(el('span', 'flex-1 text-white text-sm font-medium pl-4', row.after));
        container.appendChild(wrapper);
    });
    initTransformRowsAnimation();
}

function renderDocCards() {
    var grid = document.getElementById('doc-cards-grid');
    if (!grid) {
        return;
    }
    DOC_CARDS.forEach(function (doc) {
        var link = el('a', 'premium-card rounded-2xl p-7 shadow-md group');
        link.href = doc.url;
        link.rel = 'noopener';

        var row = el('div', 'flex items-start space-x-4');
        var iconWrap = el('div', 'w-12 h-12 bg-' + doc.color + '-50 rounded-xl flex items-center justify-center flex-shrink-0');
        var icon = el('i', doc.icon + ' text-' + doc.color + '-600 text-xl');
        icon.setAttribute('aria-hidden', 'true');
        iconWrap.appendChild(icon);
        row.appendChild(iconWrap);

        var body = el('div');
        body.appendChild(el('h3', 'text-lg font-semibold text-ink mb-2 group-hover:text-teal-800 transition-colors', doc.title));
        body.appendChild(el('p', 'text-slate-600 text-sm leading-relaxed', doc.description));
        row.appendChild(body);

        link.appendChild(row);
        grid.appendChild(link);
    });
}

/**
 * Render one server as a flip card: identity on the front, review coverage on
 * the back.
 * @param {Object} server
 * @returns {HTMLElement}
 */
function buildServerCard(server) {
    var coverage = SERVER_COVERAGE[server.name] || { icon: 'fa-server', items: [] };
    var toolLabel = server.toolCount + (server.toolCount === 1 ? ' tool' : ' tools');

    var card = el('div', 'flip-card');
    card.tabIndex = 0;
    card.setAttribute('role', 'button');
    card.setAttribute('aria-label', server.name + ' server — activate to see what it covers');

    var inner = el('div', 'flip-card-inner');

    /* Front */
    var front = el('div', 'flip-card-front');
    var frontCard = el('div', 'premium-card rounded-2xl p-6 shadow-md');

    var iconWrap = el('div', 'w-14 h-14 bg-teal-50 rounded-xl flex items-center justify-center mb-4');
    var icon = el('i', 'fas ' + coverage.icon + ' text-teal-700 text-2xl');
    icon.setAttribute('aria-hidden', 'true');
    iconWrap.appendChild(icon);
    frontCard.appendChild(iconWrap);

    frontCard.appendChild(el('h3', 'text-lg font-semibold text-ink mb-1', server.name));
    frontCard.appendChild(el('p', 'text-xs text-slate-500 mb-3', server.agency));
    frontCard.appendChild(el('p', 'text-slate-600 text-sm leading-relaxed mb-4', server.description));

    var meta = el('div', 'flex items-center gap-2 flex-wrap text-xs');
    meta.appendChild(el('span', 'bg-teal-100 text-teal-800 px-3 py-1.5 rounded-full font-medium', toolLabel));
    if (server.credentials.length) {
        meta.appendChild(el('span', 'credential-pill credential-pill-optional', 'optional key'));
    } else {
        meta.appendChild(el('span', 'credential-pill credential-pill-none', 'no key'));
    }
    frontCard.appendChild(meta);

    var hint = el('p', 'flip-hint-front');
    hint.innerHTML = '<i class="fas fa-rotate mr-1" aria-hidden="true"></i>Flip for coverage';
    frontCard.appendChild(hint);

    front.appendChild(frontCard);
    inner.appendChild(front);

    /* Back */
    var back = el('div', 'flip-card-back');
    var backCard = el('div', 'premium-card rounded-2xl p-6 shadow-md');
    backCard.appendChild(el('h3', 'text-base font-semibold text-teal-800 mb-4', 'What it covers'));

    var list = el('ul', 'coverage-list');
    coverage.items.forEach(function (item) {
        var entry = el('li', 'coverage-item');
        var check = el('i', 'fas fa-circle-check coverage-icon text-teal-600 text-xs');
        check.setAttribute('aria-hidden', 'true');
        entry.appendChild(check);

        var text = el('div', 'coverage-text');
        text.appendChild(el('span', 'coverage-code', item[0]));
        text.appendChild(document.createTextNode(item[1]));
        entry.appendChild(text);
        list.appendChild(entry);
    });
    backCard.appendChild(list);
    backCard.appendChild(el('p', 'flip-hint', 'Flip back'));

    back.appendChild(backCard);
    inner.appendChild(back);

    card.appendChild(inner);

    onActivate(card, function () {
        card.classList.toggle('flipped');
        card.setAttribute('aria-pressed', card.classList.contains('flipped') ? 'true' : 'false');
    });

    return card;
}

function renderServerCards() {
    var grid = document.getElementById('mcp-servers-grid');
    if (!grid || !DATA) {
        return;
    }
    grid.textContent = '';
    DATA.servers.forEach(function (server) {
        grid.appendChild(buildServerCard(server));
    });
}

/* ============================================
   Hero stat badge
   ============================================ */

function initUnifiedBadge() {
    var badge = document.getElementById('unified-badge');
    if (!badge) {
        return;
    }

    var sequence = Array.prototype.slice.call(badge.querySelectorAll('.badge-stat, .badge-arrow'));
    var hasPlayed = false;

    if (prefersReducedMotion()) {
        sequence.forEach(function (node) {
            node.classList.add('revealed');
        });
        return;
    }

    function play() {
        sequence.forEach(function (node) {
            node.classList.remove('revealed');
        });
        sequence.forEach(function (node, index) {
            window.setTimeout(function () {
                node.classList.add('revealed');
            }, index * 240);
        });
    }

    onActivate(badge, play);

    var observer = new IntersectionObserver(function (entries) {
        if (entries[0].isIntersecting && !hasPlayed) {
            hasPlayed = true;
            window.setTimeout(play, 500);
        }
    }, { threshold: 0.5 });
    observer.observe(badge);
}

/* ============================================
   Finding -> review pathway ticker
   ============================================ */

function initJurisdictionFlow() {
    var container = document.getElementById('jurisdiction-flow');
    if (!container) {
        return;
    }

    var featureEl = container.querySelector('.flow-feature');
    var arrowEl = container.querySelector('.flow-arrow');
    var resultEl = container.querySelector('.flow-result');
    if (!featureEl || !arrowEl || !resultEl) {
        return;
    }

    var sequence = [
        { feature: 'Finding', result: 'Review pathway', isTheme: true },
        { feature: 'Wetlands nearby', result: 'Army Corps permit review' },
        { feature: 'Federal land ownership', result: 'Cooperating agency coordination' },
        { feature: 'Tribal lands in the area', result: 'Tribal nation consultation' },
        { feature: 'Listed species habitat', result: 'Wildlife Service consultation' },
        { feature: 'Air quality monitors', result: 'Clean Air Act review' },
        { feature: 'Mapped flood zones', result: 'Floodplain compliance' },
        { feature: 'Historic properties', result: 'Section 106 review' },
        { feature: 'A CFR citation', result: 'Current regulatory text' },
        { feature: 'Automated screening', result: 'Faster, traceable review', isFinale: true }
    ];

    var currentIndex = 0;
    var timeout = null;
    var isPaused = false;
    var isFirstLoad = true;

    function showStep(index) {
        var step = sequence[index];

        featureEl.style.opacity = '0';
        arrowEl.style.opacity = '0';
        resultEl.style.opacity = '0';
        featureEl.style.transform = 'translateY(-4px)';
        resultEl.style.transform = 'translateY(4px)';

        window.setTimeout(function () {
            featureEl.textContent = step.feature;
            arrowEl.textContent = step.isTheme ? '×' : '→';
            resultEl.textContent = step.result;

            featureEl.style.opacity = '1';
            arrowEl.style.opacity = '1';
            resultEl.style.opacity = '1';
            featureEl.style.transform = 'translateY(0)';
            resultEl.style.transform = 'translateY(0)';
        }, 300);
    }

    function scheduleNext() {
        if (timeout) {
            window.clearTimeout(timeout);
        }
        var step = sequence[currentIndex];
        var delay = 1800;
        if (isFirstLoad) {
            delay = 1300;
            isFirstLoad = false;
        } else if (step.isTheme) {
            delay = 2000;
        } else if (step.isFinale) {
            delay = 2600;
        }

        timeout = window.setTimeout(function () {
            if (!isPaused) {
                currentIndex = (currentIndex + 1) % sequence.length;
                showStep(currentIndex);
            }
            scheduleNext();
        }, delay);
    }

    container.addEventListener('mouseenter', function () {
        isPaused = true;
    });
    container.addEventListener('mouseleave', function () {
        window.setTimeout(function () {
            isPaused = false;
        }, 1000);
    });
    onActivate(container, function () {
        currentIndex = (currentIndex + 1) % sequence.length;
        showStep(currentIndex);
        isPaused = true;
        window.setTimeout(function () {
            isPaused = false;
        }, 4000);
    });

    if (prefersReducedMotion()) {
        return;
    }

    var observer = new IntersectionObserver(function (entries) {
        if (entries[0].isIntersecting) {
            scheduleNext();
        } else if (timeout) {
            window.clearTimeout(timeout);
            timeout = null;
        }
    }, { threshold: 0.3 });
    observer.observe(container);
}

/* ============================================
   Tool explorer
   ============================================ */

// Server groups shown before the "show more" control, and the approximate
// number of layers to show before collapsing. Layer categories vary from 1 to 7
// members, so budget by layer count and stop at a category boundary.
//
// Both previews are deliberately short: enough to show what an entry looks like,
// with the rest one click away. Three server groups reach cfr, the richest tool
// list; a budget of 10 stops after the third layer category.
var TOOL_GROUP_PREVIEW = 3;
var LAYER_PREVIEW_BUDGET = 10;

// Presentation order for the layer section. site-data.js lists categories in
// catalog order, which leads with three single-layer categories and buries the
// two biggest. Lead with what a reviewer screens for first instead.
//
// Categories are grouped for display only — each layer keeps the category it
// carries in the server's LAYER_METADATA. A group with several members collapses
// its categories under one heading so single-layer rows do not sit near-empty.
var LAYER_GROUPS = [
    { categories: ['Federal Lands (BLM)'] },
    { categories: ['Species and Habitat'] },
    { categories: ['Habitat Protection'] },
    { categories: ['Federal Lands (non-BLM)'] },
    { categories: ['Water Resources (USACE)'] },
    { categories: ['Water Resources (USGS NHD)'] },
    {
        label: 'Administrative · Tribal · Region of Interest',
        categories: ['Administrative', 'Tribal', 'Region of Interest']
    },
    { categories: ['Contextual'] }
];

/**
 * Resolve LAYER_GROUPS against the generated catalog. Unknown categories are
 * appended in catalog order so a new layer never silently disappears.
 * @param {string[]} categories
 * @returns {{label: string, categories: string[]}[]}
 */
function layerGroups(categories) {
    var claimed = {};
    var groups = [];
    LAYER_GROUPS.forEach(function (group) {
        var present = group.categories.filter(function (category) {
            return categories.indexOf(category) !== -1;
        });
        present.forEach(function (category) {
            claimed[category] = true;
        });
        if (present.length) {
            groups.push({ label: group.label || present[0], categories: present });
        }
    });
    categories.forEach(function (category) {
        if (!claimed[category]) {
            groups.push({ label: category, categories: [category] });
        }
    });
    return groups;
}

var toolState = {
    query: '',
    agency: 'all',
    credentialFreeOnly: false,
    expanded: false
};

function serverByName(name) {
    var match = null;
    DATA.servers.some(function (server) {
        if (server.name === name) {
            match = server;
            return true;
        }
        return false;
    });
    return match;
}

/**
 * Return the tools matching the current search text and filters.
 * @returns {Array<Object>}
 */
function filteredTools() {
    var query = toolState.query.trim().toLowerCase();
    return DATA.tools.filter(function (tool) {
        var server = serverByName(tool.server);
        if (!server) {
            return false;
        }
        if (toolState.agency !== 'all' && server.agency !== toolState.agency) {
            return false;
        }
        if (toolState.credentialFreeOnly && server.credentials.length) {
            return false;
        }
        if (!query) {
            return true;
        }
        var haystack = (
            tool.name + ' ' + tool.purpose + ' ' + tool.server + ' ' + server.agency
        ).toLowerCase();
        return haystack.indexOf(query) !== -1;
    });
}

function buildParameterList(tool) {
    var wrapper = el('div', 'tool-params');
    wrapper.id = 'params-' + tool.server + '-' + tool.name;

    if (!tool.parameters.length) {
        wrapper.appendChild(el('p', 'param-description pt-3', 'This tool takes no parameters.'));
        return wrapper;
    }

    wrapper.appendChild(el('p', 'layer-category-name pt-3 pb-1', 'Parameters'));

    tool.parameters.forEach(function (parameter) {
        var row = el('div', 'param-row');
        row.appendChild(el('code', 'param-name', parameter.name));
        row.appendChild(el('span', 'param-type', parameter.type));

        if (parameter.required) {
            row.appendChild(el('span', 'param-flag param-flag-required', 'required'));
        } else if (parameter.default) {
            row.appendChild(el('span', 'param-flag param-flag-default', '= ' + parameter.default));
        }

        var description = parameter.description;
        if (parameter.choices && parameter.choices.length) {
            var choices = 'One of: ' + parameter.choices.join(', ') + '.';
            description = description ? description + ' ' + choices : choices;
        }
        if (description) {
            row.appendChild(el('span', 'param-description', description));
        }

        wrapper.appendChild(row);
    });

    return wrapper;
}

function buildToolRow(tool) {
    var fragment = document.createDocumentFragment();
    var params = buildParameterList(tool);

    var button = el('button', 'tool-row');
    button.type = 'button';
    button.setAttribute('aria-expanded', 'false');
    button.setAttribute('aria-controls', params.id);

    var row = el('div', 'flex items-start gap-3');

    var chevron = el('i', 'fas fa-chevron-right text-xs tool-row-chevron mt-1');
    chevron.setAttribute('aria-hidden', 'true');
    row.appendChild(chevron);

    var body = el('div', 'flex-1 min-w-0');
    body.appendChild(el('code', 'tool-row-name', tool.name));
    body.appendChild(el('p', 'tool-row-purpose', tool.purpose));
    row.appendChild(body);

    var count = el('span', 'text-xs text-slate-400 tabular-nums flex-shrink-0 mt-1',
        tool.parameters.length ? tool.parameters.length + (tool.parameters.length === 1 ? ' param' : ' params') : 'no params');
    row.appendChild(count);

    button.appendChild(row);

    button.addEventListener('click', function () {
        var expanded = button.getAttribute('aria-expanded') === 'true';
        button.setAttribute('aria-expanded', expanded ? 'false' : 'true');
        params.classList.toggle('expanded', !expanded);
    });

    fragment.appendChild(button);
    fragment.appendChild(params);
    return fragment;
}

function renderToolResults() {
    var container = document.getElementById('tool-results');
    var countLabel = document.getElementById('tool-count');
    var moreContainer = document.getElementById('tool-show-more');
    if (!container || !DATA) {
        return;
    }

    var tools = filteredTools();
    container.textContent = '';
    container.classList.remove('collapsed-fade');
    if (moreContainer) {
        moreContainer.textContent = '';
    }

    if (countLabel) {
        countLabel.textContent = tools.length === DATA.tools.length
            ? 'Showing all ' + DATA.tools.length + ' tools'
            : 'Showing ' + tools.length + ' of ' + DATA.tools.length + ' tools';
    }

    if (!tools.length) {
        var empty = el('div', 'explorer-empty');
        empty.appendChild(el('p', 'text-sm', 'No tools match those filters.'));
        var reset = el('button', 'filter-chip mt-4', 'Clear filters');
        reset.type = 'button';
        reset.addEventListener('click', resetToolFilters);
        empty.appendChild(reset);
        container.appendChild(empty);
        return;
    }

    // Preserve registry order while grouping by server.
    var grouped = [];
    var indexByServer = {};
    tools.forEach(function (tool) {
        if (!(tool.server in indexByServer)) {
            indexByServer[tool.server] = grouped.length;
            grouped.push({ server: tool.server, tools: [] });
        }
        grouped[indexByServer[tool.server]].tools.push(tool);
    });

    // Show a useful starting set, then reveal the rest on request. Cutting at a
    // group boundary keeps every server's tools together.
    var visibleGroups = toolState.expanded ? grouped.length : Math.min(TOOL_GROUP_PREVIEW, grouped.length);
    var hiddenTools = 0;
    grouped.slice(visibleGroups).forEach(function (group) {
        hiddenTools += group.tools.length;
    });

    grouped.slice(0, visibleGroups).forEach(function (group) {
        var server = serverByName(group.server);
        var section = el('div', 'tool-group');

        var header = el('div', 'tool-group-header');
        var left = el('div', 'flex items-baseline gap-3 flex-wrap min-w-0');
        left.appendChild(el('span', 'tool-group-name', group.server));
        left.appendChild(el('span', 'text-xs text-slate-500', server ? server.agency : ''));
        header.appendChild(left);

        var right = el('div', 'flex items-center gap-2 flex-shrink-0');
        if (server && !server.credentials.length) {
            right.appendChild(el('span', 'credential-pill credential-pill-none', 'no keys'));
        } else if (server) {
            right.appendChild(el('span', 'credential-pill credential-pill-optional', 'optional keys'));
        }
        right.appendChild(el('span', 'text-xs text-slate-400 tabular-nums',
            group.tools.length + (group.tools.length === 1 ? ' tool' : ' tools')));
        header.appendChild(right);

        section.appendChild(header);
        group.tools.forEach(function (tool) {
            section.appendChild(buildToolRow(tool));
        });
        container.appendChild(section);
    });

    // Only offer the control when it would actually change what is shown.
    if (moreContainer && (hiddenTools || (toolState.expanded && grouped.length > TOOL_GROUP_PREVIEW))) {
        moreContainer.appendChild(buildShowMore({
            expanded: toolState.expanded,
            moreLabel: 'Show ' + hiddenTools + ' more ' + (hiddenTools === 1 ? 'tool' : 'tools'),
            lessLabel: 'Show fewer tools',
            controls: 'tool-results',
            onToggle: function () {
                toolState.expanded = !toolState.expanded;
                renderToolResults();
            }
        }));
        if (!toolState.expanded) {
            container.classList.add('collapsed-fade');
        }
    }
}

/**
 * Build a show-more / show-fewer toggle.
 * @param {{expanded: boolean, moreLabel: string, lessLabel: string, controls: string, onToggle: Function}} options
 * @returns {HTMLElement}
 */
function buildShowMore(options) {
    var button = el('button', 'show-more');
    button.type = 'button';
    button.setAttribute('aria-expanded', options.expanded ? 'true' : 'false');
    button.setAttribute('aria-controls', options.controls);
    button.appendChild(el('span', null, options.expanded ? options.lessLabel : options.moreLabel));
    var chevron = el('i', 'fas fa-chevron-down text-xs');
    chevron.setAttribute('aria-hidden', 'true');
    button.appendChild(chevron);
    button.addEventListener('click', options.onToggle);
    return button;
}

function resetToolFilters() {
    toolState.query = '';
    toolState.agency = 'all';
    toolState.credentialFreeOnly = false;

    var search = document.getElementById('tool-search');
    if (search) {
        search.value = '';
    }
    var credentialButton = document.getElementById('tool-credential-filter');
    if (credentialButton) {
        credentialButton.setAttribute('aria-pressed', 'false');
    }
    syncAgencyChips();
    renderToolResults();
}

function syncAgencyChips() {
    var chips = document.querySelectorAll('#tool-agency-filters .filter-chip');
    Array.prototype.forEach.call(chips, function (chip) {
        chip.setAttribute('aria-pressed', chip.dataset.agency === toolState.agency ? 'true' : 'false');
    });
}

function initToolExplorer() {
    if (!DATA) {
        return;
    }

    var filterContainer = document.getElementById('tool-agency-filters');
    if (filterContainer) {
        var toolsByAgency = {};
        DATA.tools.forEach(function (tool) {
            var server = serverByName(tool.server);
            if (!server) {
                return;
            }
            toolsByAgency[server.agency] = (toolsByAgency[server.agency] || 0) + 1;
        });

        var agencies = Object.keys(toolsByAgency).sort(function (a, b) {
            return toolsByAgency[b] - toolsByAgency[a] || a.localeCompare(b);
        });

        var entries = [{ label: 'All agencies', agency: 'all', count: DATA.tools.length }];
        agencies.forEach(function (agency) {
            entries.push({ label: agency, agency: agency, count: toolsByAgency[agency] });
        });

        entries.forEach(function (entry) {
            var chip = el('button', 'filter-chip');
            chip.type = 'button';
            chip.dataset.agency = entry.agency;
            chip.setAttribute('aria-pressed', entry.agency === 'all' ? 'true' : 'false');
            chip.appendChild(el('span', null, entry.label));
            chip.appendChild(el('span', 'chip-count', String(entry.count)));
            chip.addEventListener('click', function () {
                toolState.agency = entry.agency;
                // A narrowed result set is short enough to show in full.
                toolState.expanded = entry.agency !== 'all';
                syncAgencyChips();
                renderToolResults();
            });
            filterContainer.appendChild(chip);
        });
    }

    var search = document.getElementById('tool-search');
    if (search) {
        search.addEventListener('input', debounce(function () {
            toolState.query = search.value;
            // Searching implies wanting every match, not a preview.
            toolState.expanded = search.value.trim().length > 0;
            renderToolResults();
        }, 150));
    }

    var credentialButton = document.getElementById('tool-credential-filter');
    if (credentialButton) {
        credentialButton.addEventListener('click', function () {
            toolState.credentialFreeOnly = !toolState.credentialFreeOnly;
            credentialButton.setAttribute('aria-pressed', toolState.credentialFreeOnly ? 'true' : 'false');
            renderToolResults();
        });
    }

    renderToolResults();
}

/* ============================================
   Layer explorer
   ============================================ */

// Default to 'full' so every overlay reads as available on arrival; the narrower
// profiles are a filter the visitor opts into.
var activeProfile = 'full';
var layersExpanded = false;

function renderLayerCards() {
    var container = document.getElementById('layer-results');
    var countLabel = document.getElementById('layer-count');
    var moreContainer = document.getElementById('layer-show-more');
    if (!container || !DATA) {
        return;
    }

    var mapComposer = DATA.mapComposer;
    container.textContent = '';
    container.classList.remove('collapsed-fade');
    if (moreContainer) {
        moreContainer.textContent = '';
    }

    var active = mapComposer.layers.filter(function (layer) {
        return layer.profiles.indexOf(activeProfile) !== -1;
    });

    if (countLabel) {
        countLabel.textContent = activeProfile === 'full'
            ? 'The full profile requests all ' + mapComposer.layers.length + ' layers'
            : 'The ' + activeProfile + ' profile requests ' + active.length +
              ' of ' + mapComposer.layers.length + ' layers';
    }

    // Fill a layer budget, then cut at the next group boundary so a group is
    // never shown half-empty.
    var groups = layerGroups(mapComposer.categories);
    var layersInGroup = function (group) {
        return mapComposer.layers.filter(function (layer) {
            return group.categories.indexOf(layer.category) !== -1;
        });
    };

    var visibleGroups = groups;
    if (!layersExpanded) {
        var budget = 0;
        visibleGroups = [];
        groups.some(function (group) {
            visibleGroups.push(group);
            budget += layersInGroup(group).length;
            return budget >= LAYER_PREVIEW_BUDGET;
        });
    }
    var shownLayers = visibleGroups.reduce(function (total, group) {
        return total + layersInGroup(group).length;
    }, 0);
    var hiddenLayers = mapComposer.layers.length - shownLayers;

    visibleGroups.forEach(function (group) {
        var layers = layersInGroup(group);
        if (!layers.length) {
            return;
        }

        var section = el('div', 'mb-8');
        var inProfile = layers.filter(function (layer) {
            return layer.profiles.indexOf(activeProfile) !== -1;
        }).length;

        var heading = el('div', 'flex items-baseline gap-3 mb-3');
        heading.appendChild(el('h3', 'layer-category-name', group.label));
        heading.appendChild(el('span', 'text-xs text-slate-400 tabular-nums',
            inProfile + ' of ' + layers.length + ' in profile'));
        section.appendChild(heading);

        var grid = el('div', 'grid sm:grid-cols-2 lg:grid-cols-3 gap-3');
        layers.forEach(function (layer) {
            var isActive = layer.profiles.indexOf(activeProfile) !== -1;
            var card = el('div', 'layer-card' + (isActive ? '' : ' dimmed'));

            var top = el('div', 'flex items-start justify-between gap-2 mb-1');
            top.appendChild(el('span', 'layer-card-title', layer.title));
            top.appendChild(el('span', 'layer-geometry', layer.geometry));
            card.appendChild(top);

            card.appendChild(el('code', 'layer-card-id', layer.id));
            var source = el('p', 'layer-card-meta mt-1.5');
            source.appendChild(document.createTextNode(layer.source + ' · '));
            var sourceLink = el('a', 'layer-source-link', layer.sourceLinkLabel + ' ↗');
            sourceLink.href = layer.sourceUrl;
            sourceLink.target = '_blank';
            sourceLink.rel = 'noopener noreferrer';
            sourceLink.setAttribute('aria-label',
                layer.sourceLinkLabel + ' for ' + layer.title + ' (opens in a new tab)');
            source.appendChild(sourceLink);
            card.appendChild(source);
            card.appendChild(el('p', 'layer-card-meta mt-1.5 text-slate-500 italic', layer.reviewUse));
            grid.appendChild(card);
        });

        section.appendChild(grid);
        container.appendChild(section);
    });

    if (moreContainer && (hiddenLayers || layersExpanded)) {
        moreContainer.appendChild(buildShowMore({
            expanded: layersExpanded,
            moreLabel: 'Show ' + hiddenLayers + ' more ' + (hiddenLayers === 1 ? 'layer' : 'layers'),
            lessLabel: 'Show fewer layers',
            controls: 'layer-results',
            onToggle: function () {
                layersExpanded = !layersExpanded;
                renderLayerCards();
            }
        }));
        if (!layersExpanded) {
            container.classList.add('collapsed-fade');
        }
    }
}

function initLayerExplorer() {
    if (!DATA) {
        return;
    }

    var container = document.getElementById('profile-buttons');
    if (container) {
        DATA.mapComposer.profiles.forEach(function (profile) {
            var button = el('button', 'profile-button');
            button.type = 'button';
            button.dataset.profile = profile.id;
            button.setAttribute('aria-pressed', profile.id === activeProfile ? 'true' : 'false');
            button.appendChild(el('span', 'profile-button-name', profile.id));
            button.appendChild(el('span', 'profile-button-count', profile.count + ' layers'));
            button.addEventListener('click', function () {
                activeProfile = profile.id;
                Array.prototype.forEach.call(container.querySelectorAll('.profile-button'), function (node) {
                    node.setAttribute('aria-pressed', node.dataset.profile === activeProfile ? 'true' : 'false');
                });
                renderLayerCards();
            });
            container.appendChild(button);
        });
    }

    renderLayerCards();
}

/* ============================================
   Scroll behavior
   ============================================ */

function initSmoothScroll() {
    document.querySelectorAll('a[href^="#"]').forEach(function (anchor) {
        anchor.addEventListener('click', function (event) {
            var targetSelector = this.getAttribute('href');
            if (!targetSelector || targetSelector === '#') {
                return;
            }
            var target = document.querySelector(targetSelector);
            if (target) {
                event.preventDefault();
                target.scrollIntoView({
                    behavior: prefersReducedMotion() ? 'auto' : 'smooth',
                    block: 'start'
                });
            }
        });
    });
}

function initScrollAnimations() {
    if (prefersReducedMotion()) {
        document.querySelectorAll('.animate-on-scroll').forEach(function (node) {
            node.classList.remove('animate-on-scroll');
        });
        document.querySelectorAll('.scroll-reveal').forEach(function (node) {
            node.classList.add('revealed');
        });
        return;
    }

    var observer = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
            if (entry.isIntersecting) {
                entry.target.classList.add('fade-in-up');
                entry.target.classList.remove('animate-on-scroll');
                observer.unobserve(entry.target);
            }
        });
    }, { threshold: 0.05 });

    document.querySelectorAll('.animate-on-scroll').forEach(function (node) {
        observer.observe(node);
    });

    var revealObserver = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
            if (entry.isIntersecting) {
                entry.target.classList.add('revealed');
                revealObserver.unobserve(entry.target);
            }
        });
    }, { threshold: 0.1 });

    document.querySelectorAll('.scroll-reveal').forEach(function (node) {
        revealObserver.observe(node);
    });
}

/**
 * Light the Quick Start rail as each step arrives. Install, verify, connect, ask
 * is a real sequence, so the rail draws itself in that order instead of landing
 * whole, and step 2's recorded output prints a line at a time. Skipped entirely
 * under reduced motion, where the CSS never hides anything.
 */
function initQuickStartSequence() {
    var container = document.getElementById('quick-start-steps');
    if (!container || prefersReducedMotion() || !('IntersectionObserver' in window)) {
        return;
    }

    var rows = container.querySelectorAll('.step-row');
    if (!rows.length) {
        return;
    }

    container.classList.add('steps-in-motion');

    var observer = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
            if (!entry.isIntersecting) {
                return;
            }
            entry.target.classList.add('step-lit');
            observer.unobserve(entry.target);
            streamTranscript(entry.target.querySelector('.transcript'));
        });
    }, { threshold: 0.2, rootMargin: '0px 0px -6% 0px' });

    Array.prototype.forEach.call(rows, function (row) {
        observer.observe(row);
    });
}

/**
 * Print a recorded transcript one line at a time. The CSS owns the per-line
 * delays; this only holds the class for as long as the last line needs.
 * @param {Element|null} transcript
 */
function streamTranscript(transcript) {
    if (!transcript) {
        return;
    }
    var lines = transcript.querySelectorAll('.t-line');
    if (!lines.length) {
        return;
    }

    transcript.classList.add('is-streaming');
    window.setTimeout(function () {
        transcript.classList.remove('is-streaming');
    }, 1200);
}

function initTransformRowsAnimation() {
    var rows = document.querySelectorAll('#transform-section .transform-row');
    var section = document.getElementById('transform-section');
    if (!rows.length || !section || prefersReducedMotion()) {
        return;
    }

    Array.prototype.forEach.call(rows, function (row, index) {
        row.style.opacity = '0';
        row.style.transform = 'translateX(-20px)';
        row.style.transition = 'all 0.6s cubic-bezier(0.16, 1, 0.3, 1) ' + index * 0.12 + 's';
    });

    var observer = new IntersectionObserver(function (entries) {
        if (entries[0].isIntersecting) {
            Array.prototype.forEach.call(rows, function (row) {
                row.style.opacity = '1';
                row.style.transform = 'translateX(0)';
            });
            observer.disconnect();
        }
    }, { threshold: 0.3 });
    observer.observe(section);
}

/* ============================================
   Init
   ============================================ */

function init() {
    if (!DATA) {
        console.error('site-data.js did not load; regenerate it with scripts/generate_site_data.py');
    }

    renderReleaseMetadata();
    renderFeatureCards();
    renderClientConfigs();
    renderTransformRows();
    renderDocCards();
    renderServerCards();
    initToolExplorer();
    initLayerExplorer();

    initSmoothScroll();
    initScrollAnimations();
    initQuickStartSequence();
    initUnifiedBadge();
    initJurisdictionFlow();
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}
