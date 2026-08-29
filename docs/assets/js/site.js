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
        description: 'Jurisdictional, habitat, soil, water, flood, cultural, social, and economic context for a project area.'
    },
    {
        icon: 'fa-database',
        color: 'emerald',
        title: 'Public Federal Data',
        description: 'Up-to-date information from 13 federal agencies, read straight from their public services.'
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

/**
 * Client configuration options. The CLI writes to these same paths; see
 * nepa_mcp/clients.py for the authoritative targets. `path` is the literal file,
 * shown in the terminal's title bar; `scope` is the sentence below the block,
 * and says which directory decides the location and what the client needs
 * afterward — the tools do not appear until it reloads, and what that means
 * differs per client.
 */
var CLIENT_CONFIGS = [
    {
        id: 'claude',
        label: 'Claude Code',
        icon: 'fa-terminal',
        command: 'nepa-mcp configure claude',
        path: '.mcp.json',
        scope: 'Created in the directory you run it from. Reload Claude Code afterward.'
    },
    {
        id: 'vscode',
        label: 'VS Code',
        icon: 'fa-code',
        command: 'nepa-mcp configure vscode',
        path: '.vscode/mcp.json',
        scope: 'Created in the workspace directory you run it from. Reload VS Code afterward.'
    },
    {
        id: 'codex',
        label: 'Codex',
        icon: 'fa-laptop-code',
        command: 'nepa-mcp configure codex',
        path: '~/.codex/config.toml',
        scope: 'One global file, so any directory works. Start a new Codex task afterward.',
        note: 'The Codex plugin below registers the same 21 servers and adds the screening skill. Use one or the other — do not run this command as well.'
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
    epa_acres: {
        icon: 'fa-industry',
        items: [
            ['Brownfields grant properties', 'Identifiable EPA ACRES records near the project area'],
            ['Nearest-first screening', 'Distance, location, EPA region, FRS ID, and ACRES ID'],
            ['Evidence boundary', 'Not a complete inventory or contamination determination']
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
    nrcs_soils: {
        icon: 'fa-seedling',
        items: [
            ['Soil map units', 'Mapped soils and clipped site coverage'],
            ['Siting indicators', 'Drainage, runoff, slopes, restrictions, and erosion'],
            ['Farmland context', 'Prime and other farmland classifications']
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
 * Write text to the clipboard, falling back to a hidden textarea where the
 * async API is unavailable or blocked.
 * @param {string} text
 * @param {Function} done Called with true on success, false on failure.
 */
function writeClipboard(text, done) {
    function fallback() {
        var textArea = document.createElement('textarea');
        textArea.value = text;
        textArea.style.position = 'fixed';
        textArea.style.left = '-9999px';
        document.body.appendChild(textArea);
        textArea.select();
        var ok = false;
        try {
            ok = document.execCommand('copy');
        } catch (err) {
            ok = false;
        }
        document.body.removeChild(textArea);
        done(ok);
    }

    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(function () {
            done(true);
        }, fallback);
    } else {
        fallback();
    }
}

/**
 * Copy a code block's text to the clipboard with visual feedback. Buttons built
 * as an icon plus a label span are updated in place; anything else has its
 * markup swapped, which keeps the older footer button working.
 * @param {Event} e
 * @param {string} elementId
 */
function copyCode(e, elementId) {
    var codeElement = document.getElementById(elementId);
    var button = e.target.closest('button');
    if (!codeElement || !button) {
        return;
    }

    // A block that a set piece is still typing keeps its finished text in
    // data-full-text, so what lands on the clipboard is always the whole command.
    var code = codeElement.dataset.fullText || codeElement.textContent;
    var icon = button.querySelector('i');
    var label = button.querySelector('span');
    var inPlace = Boolean(icon && label);
    var originalIcon = inPlace ? icon.className : '';
    var originalLabel = inPlace ? label.textContent : '';
    var originalHTML = button.innerHTML;
    var usesSlate = button.classList.contains('bg-slate-700/90');

    function paint(iconClass, text) {
        if (inPlace) {
            icon.className = iconClass;
            label.textContent = text;
        } else {
            button.innerHTML = '<i class="' + iconClass + ' mr-2" aria-hidden="true"></i>' + text;
        }
    }

    function restore() {
        if (inPlace) {
            icon.className = originalIcon;
            label.textContent = originalLabel;
        } else {
            button.innerHTML = originalHTML;
        }
        delete button.dataset.copied;
        if (usesSlate) {
            button.classList.remove('bg-emerald-600');
            button.classList.add('bg-slate-700/90', 'hover:bg-slate-600');
        }
    }

    writeClipboard(code, function (ok) {
        if (ok) {
            paint('fas fa-check', 'Copied');
            button.dataset.copied = 'true';
            if (usesSlate) {
                button.classList.remove('bg-slate-700/90', 'hover:bg-slate-600');
                button.classList.add('bg-emerald-600');
            }
        } else {
            paint('fas fa-triangle-exclamation', 'Copy failed');
        }
        window.setTimeout(restore, 2400);
    });
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
 * Render the client segmented control and its panels. One sliding indicator
 * carries the selection, so no tab has to restate its own state.
 */
function renderClientConfigs() {
    var tabs = document.getElementById('client-tabs');
    var panels = document.getElementById('client-panels');
    if (!tabs || !panels) {
        return;
    }

    // Inside the tab box, so its offsets are measured against the tabs and the
    // Codex Desktop link beside them never shifts it.
    var thumb = el('span', 'seg-thumb');
    thumb.setAttribute('aria-hidden', 'true');
    tabs.appendChild(thumb);

    function positionThumb() {
        var active = tabs.querySelector('.seg-item[aria-selected="true"]');
        if (!active || !active.offsetWidth) {
            return;
        }
        thumb.style.width = active.offsetWidth + 'px';
        thumb.style.height = active.offsetHeight + 'px';
        thumb.style.top = active.offsetTop + 'px';
        thumb.style.transform = 'translateX(' + active.offsetLeft + 'px)';
        thumb.classList.add('is-ready');
    }

    function select(id, animate) {
        Array.prototype.forEach.call(tabs.querySelectorAll('.seg-item'), function (tab) {
            var selected = tab.dataset.client === id;
            tab.setAttribute('aria-selected', selected ? 'true' : 'false');
            tab.tabIndex = selected ? 0 : -1;
        });
        var shown = null;
        Array.prototype.forEach.call(panels.children, function (panel) {
            var selected = panel.dataset.client === id;
            panel.hidden = !selected;
            panel.classList.remove('seg-panel-in');
            if (selected && animate && !prefersReducedMotion()) {
                // Reading offsetWidth restarts the animation on a repeat select.
                void panel.offsetWidth;
                panel.classList.add('seg-panel-in');
                shown = panel;
            }
        });
        positionThumb();

        // Each tab is a different command, so switching retypes it rather than
        // swapping in a finished line — the step reads the same however the
        // visitor arrives at it. Only once the step itself has played, so a
        // switch made before then does not pre-empt its own arrival.
        if (shown && document.querySelector('#qs-step-3.step-lit')) {
            var block = shown.querySelector('pre[data-type]');
            if (block) {
                typeCommandBlock(block);
            }
        }
    }

    CLIENT_CONFIGS.forEach(function (client, index) {
        var tab = el('button', 'seg-item');
        tab.type = 'button';
        tab.dataset.client = client.id;
        tab.setAttribute('role', 'tab');
        tab.setAttribute('aria-selected', index === 0 ? 'true' : 'false');
        tab.setAttribute('aria-controls', 'client-panel-' + client.id);
        tab.tabIndex = index === 0 ? 0 : -1;
        tab.innerHTML = '<i class="fas ' + client.icon + '" aria-hidden="true"></i>';
        tab.appendChild(el('span', null, client.label));
        tab.addEventListener('click', function () {
            select(client.id, true);
        });
        // Arrow keys move between tabs, as expected of a tablist.
        tab.addEventListener('keydown', function (event) {
            var step = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0;
            if (!step) {
                return;
            }
            event.preventDefault();
            var next = CLIENT_CONFIGS[(index + step + CLIENT_CONFIGS.length) % CLIENT_CONFIGS.length];
            select(next.id, true);
            tabs.querySelector('[data-client="' + next.id + '"]').focus();
        });
        tabs.appendChild(tab);

        var panel = el('div', 'seg-panel');
        panel.id = 'client-panel-' + client.id;
        panel.dataset.client = client.id;
        panel.setAttribute('role', 'tabpanel');
        panel.hidden = index !== 0;

        // The prompt carries the directory, because where the command is run is
        // what decides where its config lands. `type` opts the block into the
        // same live typing steps 1 and 2 run, so the sequence does not go static
        // at the one step the visitor has to act on.
        panel.appendChild(buildTerminal(
            'client-cli-' + client.id,
            client.command,
            'writes ' + client.path,
            { cwd: '~/my-project', type: 22 }
        ));
        panel.appendChild(el('p', 'seg-meta', client.scope));
        if (client.note) {
            var note = el('p', 'seg-note');
            note.innerHTML = '<i class="fas fa-circle-info" aria-hidden="true"></i>';
            note.appendChild(el('span', null, client.note));
            panel.appendChild(note);
        }

        panels.appendChild(panel);
    });

    Array.prototype.forEach.call(document.querySelectorAll('[data-client-target]'), function (link) {
        link.addEventListener('click', function () {
            select(link.dataset.clientTarget, true);
        });
    });

    // The indicator is measured, so it has to be re-measured whenever the row
    // rewraps or the webfont changes the label widths.
    positionThumb();
    window.addEventListener('resize', debounce(positionThumb, 120));
    window.addEventListener('load', positionThumb);
    if (document.fonts && document.fonts.ready) {
        document.fonts.ready.then(positionThumb);
    }
}

/**
 * Build a terminal block matching the chrome used across the page.
 * @param {string} id Applied to the <pre>, for copyCode.
 * @param {string} command One or more newline-separated commands.
 * @param {string} title Shown in the title bar.
 * @param {{cwd?: string, type?: number}} [options] `cwd` puts a working
 *   directory in the prompt. It is drawn by CSS from the attribute, so it stays
 *   out of anything copied and survives a block being retyped by a set piece.
 *   `type` is milliseconds per character, and opts the block into live typing.
 * @returns {HTMLElement}
 */
function buildTerminal(id, command, title, options) {
    var settings = options || {};
    var figure = el('figure', 'term term-cmd');

    var bar = el('figcaption', 'term-bar');
    var dots = el('span', 'term-dots');
    dots.setAttribute('aria-hidden', 'true');
    dots.innerHTML = '<span></span><span></span><span></span>';
    bar.appendChild(dots);
    bar.appendChild(el('span', 'term-title', title));

    var tools = el('span', 'term-tools');
    var button = el('button', 'term-copy');
    button.type = 'button';
    button.innerHTML = '<i class="fas fa-clone" aria-hidden="true"></i>';
    button.appendChild(el('span', null, 'Copy'));
    button.addEventListener('click', function (event) {
        copyCode(event, id);
    });
    tools.appendChild(button);
    bar.appendChild(tools);
    figure.appendChild(bar);

    var pre = el('pre', 'term-body');
    pre.id = id;
    if (settings.type) {
        pre.dataset.type = String(settings.type);
    }
    var code = el('code');
    command.split('\n').forEach(function (line, index) {
        if (index) {
            code.appendChild(document.createTextNode('\n'));
        }
        var span = el('span', 'c-line', line);
        if (settings.cwd) {
            span.dataset.cwd = settings.cwd;
        }
        code.appendChild(span);
    });
    pre.appendChild(code);
    figure.appendChild(pre);

    return figure;
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

// Server cards shown before the "show more" control. Eight fills whole rows at
// the four- and two-column grids; the three-column grid between them ends one
// short, where the fade reads as a cut list rather than a gap. No count below
// twelve divides evenly into 2, 3, and 4, and twelve of twenty is no preview.
var SERVER_PREVIEW = 8;

// Cards in the clipped teaser row below the preview. Four fills the widest grid;
// narrower grids wrap the surplus below the clip, which costs nothing on a row
// that exists only to be glimpsed.
var SERVER_PEEK = 4;

var serversExpanded = false;

function renderServerCards() {
    var grid = document.getElementById('mcp-servers-grid');
    var peek = document.getElementById('mcp-servers-peek');
    var moreContainer = document.getElementById('server-show-more');
    if (!grid || !DATA) {
        return;
    }

    grid.textContent = '';
    if (peek) {
        peek.textContent = '';
        peek.hidden = true;
    }
    if (moreContainer) {
        moreContainer.textContent = '';
    }

    var visible = serversExpanded
        ? DATA.servers
        : DATA.servers.slice(0, SERVER_PREVIEW);
    var hidden = DATA.servers.length - visible.length;

    visible.forEach(function (server) {
        grid.appendChild(buildServerCard(server));
    });

    if (peek && hidden) {
        DATA.servers.slice(SERVER_PREVIEW, SERVER_PREVIEW + SERVER_PEEK).forEach(function (server) {
            // cloneNode drops the flip handler: a card the visitor cannot read is
            // not one they should be able to turn over. It is decorative, so it
            // leaves the tab order and the accessibility tree too — the control
            // below is the real affordance, and it names the full count.
            var card = buildServerCard(server).cloneNode(true);
            card.removeAttribute('role');
            card.removeAttribute('aria-label');
            card.setAttribute('aria-hidden', 'true');
            card.tabIndex = -1;
            peek.appendChild(card);
        });
        peek.hidden = false;
        peek.classList.add('collapsed-fade');
    }

    // The count stays on screen in the button label, so collapsing the grid
    // still states the inventory size rather than hiding it.
    if (moreContainer && (hidden || serversExpanded)) {
        moreContainer.appendChild(buildShowMore({
            expanded: serversExpanded,
            moreLabel: 'Show ' + hidden + ' more ' + (hidden === 1 ? 'server' : 'servers'),
            lessLabel: 'Show fewer servers',
            controls: 'mcp-servers-grid',
            onToggle: toggleServers
        }));
    }
}

function toggleServers() {
    serversExpanded = !serversExpanded;
    renderServerCards();
}

function initServerCards() {
    // The peek container outlives every render, so its handler is wired once
    // here; binding it inside renderServerCards would stack one per toggle.
    var peek = document.getElementById('mcp-servers-peek');
    if (peek) {
        peek.addEventListener('click', toggleServers);
    }
    renderServerCards();
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

// Approximate number of tool rows and layers to show before collapsing. A group
// count was the wrong unit for tools: registry order puts cfr (7 tools) third,
// so a three-group preview let one regulatory-text server fill most of it.
// Budget by row instead and stop at a server boundary — a server always shows
// its whole list, so a count in the header never disagrees with the rows below.
//
// Both previews are deliberately short: enough to show what an entry looks like,
// with the rest one click away. A budget of 10 stops after the second server and
// the third layer category.
var TOOL_ROW_BUDGET = 10;
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

    // Show a useful starting set, then reveal the rest on request: fill a row
    // budget and stop before a server that would overrun it. Cutting only at a
    // server boundary keeps every listed server's tools together. A result set
    // that already fits the budget is shown whole, so a filter never truncates
    // the handful of rows it matched.
    var visible = grouped;
    if (!toolState.expanded && tools.length > TOOL_ROW_BUDGET) {
        var budget = TOOL_ROW_BUDGET;
        visible = [];
        grouped.some(function (group) {
            if (group.tools.length > budget) {
                return true;
            }
            budget -= group.tools.length;
            visible.push(group);
            return budget === 0;
        });
    }

    var shownTools = visible.reduce(function (total, group) {
        return total + group.tools.length;
    }, 0);
    var hiddenTools = tools.length - shownTools;

    visible.forEach(function (group) {
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
    if (moreContainer && (hiddenTools || (toolState.expanded && tools.length > TOOL_ROW_BUDGET))) {
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

/**
 * Footnote marks: a line that ships visible, then collapses behind its mark once
 * the toggle exists. A script-less visit keeps the line rather than losing it to
 * a control that cannot run.
 */
function initInfoNotes() {
    Array.prototype.forEach.call(document.querySelectorAll('[data-info-toggle]'), function (button) {
        var target = document.getElementById(button.getAttribute('aria-controls'));
        if (!target) {
            return;
        }

        target.hidden = true;
        button.setAttribute('aria-expanded', 'false');

        button.addEventListener('click', function () {
            var opening = target.hidden;
            target.hidden = !opening;
            button.setAttribute('aria-expanded', opening ? 'true' : 'false');
        });
    });
}

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

/* ============================================
   Quick Start
   ============================================ */

/* Install, verify, connect, ask is a real sequence, so the section plays as one:
   the rail draws itself a segment at a time, and each step runs the one set piece
   that belongs to it. Every hidden state is class-gated, so a reduced-motion or
   script-less visit gets the finished section with nothing withheld. */

var termRunSeq = 0;

function initQuickStart() {
    var container = document.getElementById('quick-start-steps');
    if (!container) {
        return;
    }

    // Copying an example prompt and opening the credentials panel are content,
    // not motion, so they are wired up first and independently of everything
    // below.
    initAskPrompts(container);
    initCredentialsDisclosure(container);
    initStepProgress(container);

    if (prefersReducedMotion() || !('IntersectionObserver' in window)) {
        return;
    }

    var rows = container.querySelectorAll('.step-row');
    if (!rows.length) {
        return;
    }

    container.classList.add('steps-in-motion');
    prepareTerminals(container);
    initTranscriptReplay(container);

    var observer = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
            if (!entry.isIntersecting) {
                return;
            }
            entry.target.classList.add('step-lit');
            observer.unobserve(entry.target);
            runStepSetPiece(entry.target);
        });
    }, { threshold: 0.16, rootMargin: '0px 0px -8% 0px' });

    Array.prototype.forEach.call(rows, function (row) {
        observer.observe(row);
    });
}

/**
 * Trade a step's numeral for a check once the reader has gone past it. The step
 * crossing the middle of the viewport is the current one, so this follows
 * scrolling in both directions.
 * @param {Element} container
 */
function initStepProgress(container) {
    var steps = container.querySelectorAll('.step-row[data-step]');
    if (!steps.length || !('IntersectionObserver' in window)) {
        return;
    }

    function setCurrent(current) {
        Array.prototype.forEach.call(steps, function (step) {
            step.classList.toggle('step-done', parseInt(step.dataset.step, 10) < current);
        });
    }

    var observer = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
            if (entry.isIntersecting) {
                setCurrent(parseInt(entry.target.dataset.step, 10));
            }
        });
    }, { rootMargin: '-45% 0px -45% 0px' });

    Array.prototype.forEach.call(steps, function (step) {
        observer.observe(step);
    });
}

/**
 * The credentials panel stays closed, because nothing in it blocks a first
 * setup. Anything that points at it — the note under `doctor`, or a shared
 * #qs-credentials link — opens it, so the link lands on the content and not on
 * a closed row.
 * @param {Element} container
 */
function initCredentialsDisclosure(container) {
    var panel = container.querySelector('[data-cred]');
    var row = document.getElementById('qs-credentials');
    if (!panel || !row) {
        return;
    }

    function open() {
        panel.open = true;
    }

    Array.prototype.forEach.call(document.querySelectorAll('a[href="#qs-credentials"]'), function (link) {
        link.addEventListener('click', open);
    });

    if (window.location.hash === '#qs-credentials') {
        open();
    }
    window.addEventListener('hashchange', function () {
        if (window.location.hash === '#qs-credentials') {
            open();
        }
    });
}

/**
 * Record what each animated block has to end up saying, before anything blanks
 * it. Copy and replay both read from what is stored here.
 * @param {Element} container
 */
function prepareTerminals(container) {
    Array.prototype.forEach.call(container.querySelectorAll('pre[data-type]'), function (pre) {
        pre.dataset.fullText = pre.textContent;
    });
    Array.prototype.forEach.call(container.querySelectorAll('.c-line, .t-line'), function (line) {
        if (!('text' in line.dataset)) {
            line.dataset.text = line.textContent;
        }
    });
}

/**
 * The block a step should type. A step whose commands sit behind tabs has one
 * per tab, and only the shown one is the visitor's — a link from the hero can
 * preselect any of them before the step has arrived, so this cannot assume the
 * first is the right one.
 * @param {Element} row
 * @returns {HTMLPreElement|null}
 */
function shownTypableBlock(row) {
    var blocks = row.querySelectorAll('pre[data-type]');
    for (var i = 0; i < blocks.length; i += 1) {
        // Null offsetParent is the cheapest read of "inside a hidden panel".
        if (blocks[i].offsetParent !== null) {
            return blocks[i];
        }
    }
    return blocks[0] || null;
}

/**
 * Run the one set piece that belongs to a step, once it has landed.
 * @param {Element} row
 */
function runStepSetPiece(row) {
    var typed = shownTypableBlock(row);
    if (typed) {
        typeCommandBlock(typed);
    }

    var transcript = row.querySelector('[data-transcript]');
    if (transcript) {
        runTranscript(transcript);
    }

    if (row.querySelector('[data-ask]')) {
        askStart();
    }
}

/**
 * Claim a terminal for a new run. Any run still in flight sees a stale token and
 * stops, so a replay never interleaves with the run it replaced.
 * @param {Element} term
 * @returns {string}
 */
function beginTermRun(term) {
    termRunSeq += 1;
    term.dataset.run = String(termRunSeq);
    term.classList.add('is-typing');
    return term.dataset.run;
}

function termRunIsCurrent(term, token) {
    return term.dataset.run === token && document.contains(term);
}

function endTermRun(term, token) {
    if (termRunIsCurrent(term, token)) {
        term.classList.remove('is-typing');
    }
}

/**
 * Type text into a node one character at a time, with a caret while it runs.
 * @param {Element} node
 * @param {string} text
 * @param {number} speed Milliseconds per character.
 * @param {Element} term
 * @param {string} token
 * @param {Function} [done]
 */
function typeText(node, text, speed, term, token, done) {
    node.classList.add('tw-typing');
    var index = 0;

    function tick() {
        if (!termRunIsCurrent(term, token)) {
            return;
        }
        node.textContent = text.slice(0, index);
        if (index >= text.length) {
            node.classList.remove('tw-typing');
            if (done) {
                window.setTimeout(done, 110);
            }
            return;
        }
        index += 1;
        window.setTimeout(tick, speed);
    }

    tick();
}

/**
 * Type a command block line by line, the way it would be entered.
 * @param {HTMLPreElement} pre
 */
function typeCommandBlock(pre) {
    var term = pre.closest('.term');
    var lines = pre.querySelectorAll('.c-line');
    if (!term || !lines.length) {
        return;
    }

    var speed = parseInt(pre.dataset.type, 10) || 16;
    var token = beginTermRun(term);
    Array.prototype.forEach.call(lines, function (line) {
        line.classList.remove('is-in');
        line.textContent = '';
    });

    var index = 0;
    function nextLine() {
        if (!termRunIsCurrent(term, token)) {
            return;
        }
        if (index >= lines.length) {
            endTermRun(term, token);
            return;
        }
        var line = lines[index];
        index += 1;
        line.classList.add('is-in');
        typeText(line, line.dataset.text, speed, term, token, nextLine);
    }

    window.setTimeout(nextLine, 340);
}

/**
 * Replay a recorded session: the command is typed, then the output flushes a
 * line at a time, with a beat before the line that carries the proof.
 * @param {Element} term
 */
function runTranscript(term) {
    var lines = term.querySelectorAll('.t-line');
    if (!lines.length) {
        return;
    }

    var token = beginTermRun(term);
    Array.prototype.forEach.call(lines, function (line) {
        line.classList.remove('is-in');
    });

    var prompt = lines[0];
    prompt.textContent = '';

    window.setTimeout(function () {
        if (!termRunIsCurrent(term, token)) {
            return;
        }
        prompt.classList.add('is-in');
        typeText(prompt, prompt.dataset.text, 34, term, token, function () {
            printTranscriptLine(term, lines, 1, token);
        });
    }, 340);
}

function printTranscriptLine(term, lines, index, token) {
    if (!termRunIsCurrent(term, token)) {
        return;
    }
    if (index >= lines.length) {
        endTermRun(term, token);
        return;
    }

    var line = lines[index];
    var delay = line.classList.contains('t-proof') ? 300 : 110;

    window.setTimeout(function () {
        if (!termRunIsCurrent(term, token)) {
            return;
        }
        line.classList.add('is-in');
        printTranscriptLine(term, lines, index + 1, token);
    }, delay);
}

/**
 * A recording is worth watching twice, so let the visitor run it again.
 * @param {Element} container
 */
function initTranscriptReplay(container) {
    Array.prototype.forEach.call(container.querySelectorAll('[data-replay]'), function (button) {
        var term = button.closest('.term');
        if (!term) {
            return;
        }
        button.addEventListener('click', function () {
            button.classList.remove('is-spinning');
            void button.offsetWidth;
            button.classList.add('is-spinning');
            runTranscript(term);
        });
    });
}

/* --- Step 4: the composer ------------------------------------------------ */

/* The composer types each example prompt in turn and marks the card it is
   typing, which is what ties the two together without a caption saying so. The
   cards hold the real text: they are what a visitor copies, and what a
   script-less visit shows. */

var askComposer = null;

function initAskPrompts(container) {
    var root = container.querySelector('[data-ask]');
    if (!root) {
        return;
    }

    var bar = root.querySelector('.ask-text');
    var cards = Array.prototype.slice.call(root.querySelectorAll('[data-prompt]'));
    if (!bar || !cards.length) {
        return;
    }

    askComposer = {
        root: root,
        bar: bar,
        send: root.querySelector('.ask-send'),
        cards: cards,
        texts: cards.map(function (card) {
            var text = card.querySelector('.prompt-text');
            return text ? text.textContent.trim() : '';
        }),
        run: 0,
        cycles: 0,
        visible: true,
        started: false
    };

    cards.forEach(function (card, index) {
        card.addEventListener('click', function () {
            copyPrompt(card, askComposer.texts[index]);
            if (prefersReducedMotion()) {
                askMarkCard(index);
                askComposer.bar.textContent = askComposer.texts[index];
                return;
            }
            // A click takes over the rotation and settles on what was clicked.
            askComposer.cycles = 0;
            askComposer.run += 1;
            askType(index, askComposer.run, true);
        });
    });

    if ('IntersectionObserver' in window) {
        new IntersectionObserver(function (entries) {
            askComposer.visible = entries[0].isIntersecting;
        }, { threshold: 0.2 }).observe(root);
    }
}

function askStart() {
    if (!askComposer || askComposer.started) {
        return;
    }
    askComposer.started = true;
    askComposer.run += 1;
    askType(0, askComposer.run, false);
}

function askMarkCard(index) {
    askComposer.cards.forEach(function (card, position) {
        card.classList.toggle('is-active', position === index);
    });
}

/**
 * Type one example into the composer, then either settle on it or move to the
 * next. Paused whenever the composer is off screen, so nothing runs unwatched.
 * @param {number} index
 * @param {number} token
 * @param {boolean} settle Stop here instead of rotating on.
 */
function askType(index, token, settle) {
    if (!askComposer || token !== askComposer.run) {
        return;
    }

    var full = askComposer.texts[index];
    var bar = askComposer.bar;
    askMarkCard(index);
    bar.classList.add('is-typing');

    var typed = 0;
    function forward() {
        if (!askComposer || token !== askComposer.run) {
            return;
        }
        if (!askComposer.visible) {
            window.setTimeout(forward, 400);
            return;
        }
        bar.textContent = full.slice(0, typed);
        if (typed >= full.length) {
            if (askComposer.send) {
                askComposer.send.classList.remove('is-sending');
                void askComposer.send.offsetWidth;
                askComposer.send.classList.add('is-sending');
            }
            if (settle) {
                window.setTimeout(function () {
                    if (askComposer && token === askComposer.run) {
                        bar.classList.remove('is-typing');
                    }
                }, 1400);
                return;
            }
            window.setTimeout(back, 2400);
            return;
        }
        typed += 1;
        window.setTimeout(forward, 26);
    }

    var left = full.length;
    function back() {
        if (!askComposer || token !== askComposer.run) {
            return;
        }
        if (!askComposer.visible) {
            window.setTimeout(back, 400);
            return;
        }
        bar.textContent = full.slice(0, left);
        if (left <= 0) {
            var next = (index + 1) % askComposer.texts.length;
            if (next === 0) {
                askComposer.cycles += 1;
            }
            // Two passes is enough to show what the servers answer; after that
            // it settles rather than looping at the visitor forever.
            window.setTimeout(function () {
                askType(next, token, askComposer.cycles >= 2);
            }, 240);
            return;
        }
        left -= 1;
        window.setTimeout(back, 12);
    }

    forward();
}

/**
 * Copy an example prompt, with feedback on the card itself.
 * @param {Element} card
 * @param {string} text
 */
function copyPrompt(card, text) {
    var action = card.querySelector('.prompt-action span');
    var icon = card.querySelector('.prompt-action i');
    var label = action ? action.textContent : '';

    writeClipboard(text, function (ok) {
        if (!action || !icon) {
            return;
        }
        action.textContent = ok ? 'Copied' : 'Copy failed';
        icon.className = ok ? 'fas fa-check' : 'fas fa-triangle-exclamation';
        card.classList.add('is-copied');
        window.setTimeout(function () {
            action.textContent = label;
            icon.className = 'fas fa-clone';
            card.classList.remove('is-copied');
        }, 2400);
    });
}

/* ============================================
   Codex Desktop plugin
   ============================================ */

/* Quick Start's steps are commands, so each plays in a terminal. These three are
   form-filling in a desktop app, so the set piece is the form: the steps light
   in turn, the two values type themselves into their fields, and the plugin row
   lands installed. The sentences hold both values, so a reduced-motion or
   script-less visit reads the same instructions with the form already filled. */

var pluginInstall = null;

function initCodexPlugin() {
    var section = document.getElementById('codex-plugin');
    if (!section) {
        return;
    }

    var list = section.querySelector('[data-plugin-steps]');
    if (!list || prefersReducedMotion() || !('IntersectionObserver' in window)) {
        return;
    }

    var steps = Array.prototype.slice.call(list.querySelectorAll('[data-pin-step]'));
    var fields = Array.prototype.slice.call(list.querySelectorAll('[data-pin-value]'));
    if (steps.length < 3 || !fields.length) {
        return;
    }

    pluginInstall = {
        // The list stands in for a terminal, so the run token that keeps two
        // terminals from interleaving keeps a replay from interleaving here.
        stage: list,
        steps: steps,
        form: list.querySelector('.pin-form'),
        fields: fields,
        // Recorded before the first run blanks them; a replay retypes this.
        texts: fields.map(function (node) {
            return node.textContent.trim();
        }),
        installed: list.querySelector('[data-pin-installed]'),
        epilogue: section.querySelector('[data-plugin-epilogue]')
    };

    section.classList.add('plugin-in-motion');

    var replay = section.querySelector('[data-plugin-replay]');
    if (replay) {
        replay.addEventListener('click', function () {
            replay.classList.remove('is-spinning');
            void replay.offsetWidth;
            replay.classList.add('is-spinning');
            runPluginInstall();
        });
    }

    var observer = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
            if (!entry.isIntersecting) {
                return;
            }
            observer.unobserve(entry.target);
            runPluginInstall();
        });
    }, { threshold: 0.45 });

    observer.observe(list);
}

/**
 * Play the install: the dialog opens, the two values type into their fields,
 * then the plugin row lands.
 */
function runPluginInstall() {
    if (!pluginInstall) {
        return;
    }

    var stage = pluginInstall.stage;
    var token = beginTermRun(stage);

    // Back to the start, whether this is the first run or a replay. The form is
    // still hidden at this point, so blanking it is never seen.
    pluginInstall.steps.forEach(function (step) {
        step.classList.remove('pin-lit', 'pin-done');
    });
    pluginInstall.fields.forEach(function (node) {
        node.textContent = '';
        node.classList.remove('tw-typing');
        pluginFieldOf(node).classList.remove('is-focus');
    });
    if (pluginInstall.form) {
        pluginInstall.form.classList.remove('is-in');
    }
    if (pluginInstall.installed) {
        pluginInstall.installed.classList.remove('is-in');
    }
    if (pluginInstall.epilogue) {
        pluginInstall.epilogue.classList.remove('is-in');
    }

    // 1. Open Plugins, choose Add plugin marketplace.
    window.setTimeout(function () {
        if (!termRunIsCurrent(stage, token)) {
            return;
        }
        pluginInstall.steps[0].classList.add('pin-lit');

        window.setTimeout(function () {
            if (!termRunIsCurrent(stage, token)) {
                return;
            }
            // 2. The dialog is open, so the fields arrive and fill themselves.
            pluginInstall.steps[0].classList.add('pin-done');
            pluginInstall.steps[1].classList.add('pin-lit');
            if (pluginInstall.form) {
                pluginInstall.form.classList.add('is-in');
            }
            window.setTimeout(function () {
                typePluginField(0, token);
            }, 420);
        }, 760);
    }, 220);
}

/**
 * The field a value sits in. Falls back to the node itself, so a markup change
 * that drops the wrapper costs the focus ring and nothing more.
 * @param {Element} node
 * @returns {Element}
 */
function pluginFieldOf(node) {
    return node.closest('.pin-field') || node;
}

/**
 * Type one field value, then move to the next. Slower than the terminals: these
 * are two values the visitor has to read off the screen and retype.
 * @param {number} index
 * @param {string} token
 */
function typePluginField(index, token) {
    if (!pluginInstall) {
        return;
    }

    var stage = pluginInstall.stage;
    if (!termRunIsCurrent(stage, token)) {
        return;
    }

    var node = pluginInstall.fields[index];
    if (!node) {
        finishPluginInstall(token);
        return;
    }

    var field = pluginFieldOf(node);
    field.classList.add('is-focus');

    typeText(node, pluginInstall.texts[index], 38, stage, token, function () {
        field.classList.remove('is-focus');
        window.setTimeout(function () {
            typePluginField(index + 1, token);
        }, 260);
    });
}

/**
 * 3. Add the marketplace, then install: the plugin row lands with what the one
 * install actually registers.
 * @param {string} token
 */
function finishPluginInstall(token) {
    var stage = pluginInstall.stage;
    if (!termRunIsCurrent(stage, token)) {
        return;
    }

    pluginInstall.steps[1].classList.add('pin-done');

    window.setTimeout(function () {
        if (!termRunIsCurrent(stage, token)) {
            return;
        }
        pluginInstall.steps[2].classList.add('pin-lit');

        window.setTimeout(function () {
            if (!termRunIsCurrent(stage, token)) {
                return;
            }
            if (pluginInstall.installed) {
                pluginInstall.installed.classList.add('is-in');
            }
            pluginInstall.steps[2].classList.add('pin-done');

            // The one thing left to do, so it arrives after the install has
            // landed rather than before there is anything to reload for.
            window.setTimeout(function () {
                if (!termRunIsCurrent(stage, token)) {
                    return;
                }
                if (pluginInstall.epilogue) {
                    pluginInstall.epilogue.classList.add('is-in');
                }
                endTermRun(stage, token);
            }, 480);
        }, 520);
    }, 300);
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
    renderDocCards();
    initServerCards();
    initToolExplorer();
    initLayerExplorer();

    initInfoNotes();
    initSmoothScroll();
    initScrollAnimations();
    initQuickStart();
    initCodexPlugin();
    initUnifiedBadge();
    initJurisdictionFlow();
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}
