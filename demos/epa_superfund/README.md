# epa_superfund demo

A local page that calls the nine `epa_superfund` tools and shows each result
as records, per-source coverage, and the raw MCP response. Nearby-site and
site results are plotted on a map. Live queries and MCP pagination run
against the real public sources.

```bash
.venv/bin/python demos/epa_superfund/capture.py
.venv/bin/python demos/epa_superfund/serve.py
```

Run both commands from the repository root, then open http://127.0.0.1:8788.
`capture.py` records one example per tool into `captures/` and `data.js`,
which are git-ignored. `serve.py` listens on
loopback only and answers live queries for the nine tools.

Every request the tools make is checked during capture. It must go to one of
the sources the server is allowed to contact (EPA ArcGIS layers, Envirofacts,
the Federal Register API, and the shared ArcGIS buffer service), identify
the project, and not follow redirects. EPA's site-profile pages and search
pages are never fetched.

Results are EPA program records, not clean-land, exposure, legal-restriction,
or suitability determinations. The map basemap and icons load from public
CDNs.
