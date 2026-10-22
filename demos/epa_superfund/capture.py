"""Capture example epa_superfund tool calls for the local demo.

Run without arguments to record one example per tool into captures/ and
data.js (both git-ignored). serve.py also runs this script with a JSON call
spec to answer live queries. Every request is checked against the hosts the
server is allowed to contact, must identify the project, and may not follow
redirects.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ALLOWED_HOSTS = {"services.arcgis.com", "utility.arcgisonline.com", "data.epa.gov", "www.federalregister.gov"}
SITE = {"epa_id": "NJD063157150"}
EXAMPLES = (
    ("search", "search_epa_superfund_sites", {"query": "Bog Creek Farm"}),
    ("roi", "get_epa_superfund_sites_in_roi", {"latitude": 40.150831, "longitude": -74.161111, "buffer_miles": 5}),
    ("site", "get_epa_superfund_site", SITE),
    ("ous", "get_epa_superfund_operable_units", {"epa_id": "COD980717557"}),
    ("controls", "get_epa_superfund_institutional_controls", {"epa_id": "COD980717557"}),
    ("documents", "get_epa_superfund_documents", SITE),
    ("actions", "get_epa_superfund_cleanup_actions", SITE),
    ("contaminants", "get_epa_superfund_contaminants", SITE),
    ("notices", "get_epa_superfund_public_notices", {"epa_id": "COD980717557"}),
)


def call_tool(spec: dict) -> dict:
    """Call one tool in-process and return its Markdown, structured result, and outbound requests."""
    sys.path[:0] = [str(ROOT / "epa_superfund"), str(ROOT)]
    import requests
    import server
    from fastmcp import Client

    requests_made = []
    original_request = requests.sessions.Session.request

    def guarded(session, method, url, **kwargs):
        host = urlparse(url).hostname
        if host not in ALLOWED_HOSTS:
            raise AssertionError(f"request to a host outside the allowed sources: {host}")
        if kwargs.get("allow_redirects") is not False:
            raise AssertionError(f"request may follow redirects: {url}")
        if "nepa-mcp" not in kwargs.get("headers", {}).get("User-Agent", ""):
            raise AssertionError(f"request does not identify the project: {url}")
        requests_made.append({"method": method, "url": url})
        return original_request(session, method, url, **kwargs)

    requests.sessions.Session.request = guarded
    captured = {}
    original = getattr(server, spec["tool"])

    def record(*args, **kwargs):
        captured["result"] = original(*args, **kwargs)
        return captured["result"]

    setattr(server, spec["tool"], record)

    async def run():
        async with Client(server.mcp) as client:
            return await client.call_tool(spec["tool"], spec["args"], raise_on_error=False)

    started = time.monotonic()
    response = asyncio.run(run())
    return {
        **spec,
        **captured,
        "elapsed_seconds": round(time.monotonic() - started, 2),
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "is_error": response.is_error,
        "requests": requests_made,
        "markdown": "\n".join(item.text for item in response.content if hasattr(item, "text")),
    }


def _serialize(value):
    if dataclasses.is_dataclass(value):
        return dataclasses.asdict(value)
    raise TypeError(type(value).__name__)


def capture_examples() -> None:
    destination = HERE / "captures"
    destination.mkdir(exist_ok=True)
    captures = []
    for identifier, tool, args in EXAMPLES:
        spec = json.dumps({"id": identifier, "tool": tool, "args": args})
        result = subprocess.run(
            [sys.executable, str(Path(__file__)), spec], text=True, capture_output=True, timeout=110, check=False
        )
        if result.returncode:
            raise SystemExit(f"{identifier} failed:\n{result.stderr[-2000:]}")
        payload = json.loads(result.stdout)
        (destination / f"{identifier}.json").write_text(json.dumps(payload, indent=2))
        captures.append(payload)
        print(identifier, payload["elapsed_seconds"], "s", len(payload["requests"]), "requests", flush=True)
    data = {"captures": captures}
    (HERE / "data.js").write_text("window.DEMO_DATA=" + json.dumps(data).replace("<", "\\u003c") + ";\n")
    print("Wrote data.js with", len(captures), "captures")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        print(json.dumps(call_tool(json.loads(sys.argv[1])), default=_serialize))
    else:
        capture_examples()
