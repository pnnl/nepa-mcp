"""Configured-source HTTP and content-scoped HTML parsing; no restricted-system bypass."""

import time
from urllib.parse import urljoin
from bs4 import BeautifulSoup
import requests
from src.core.normalization import now, source_url

_CACHE = {}


class Budget:
    def __init__(self):
        self.deadline = time.monotonic() + 75
        self.requests = 0

    def check(self):
        self.requests += 1
        if self.requests > 16 or time.monotonic() > self.deadline:
            raise RuntimeError("Source request budget exhausted")


def fetch(url, budget=None):
    report = {
        "url": url,
        "status": "unavailable",
        "complete": False,
        "retrieved_at": now(),
        "warnings": [],
        "cached": False,
    }
    if not source_url(url):
        return None, {**report, "status": "unsupported", "warnings": ["Unapproved source URL; not fetched"]}
    hit = _CACHE.get(url)
    if hit and time.monotonic() - hit[0] < 600:
        return hit[1], {**hit[2], "cached": True, "cache_age_seconds": round(time.monotonic() - hit[0], 2)}
    budget = budget or Budget()
    current = url
    try:
        for _ in range(4):
            budget.check()
            with requests.get(
                current,
                timeout=(4, 10),
                headers={"User-Agent": "NEPA-MCP/0.1.6 BRAC research"},
                allow_redirects=False,
                stream=True,
            ) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    current = source_url(urljoin(current, response.headers.get("Location", "")))
                    if not current:
                        raise RuntimeError("Redirect rejected outside official allowlist")
                    continue
                if response.status_code in {401, 403}:
                    return None, {
                        **report,
                        "status": "restricted",
                        "warnings": [f"Official source returned HTTP {response.status_code}; access was not bypassed"],
                    }
                if response.status_code != 200:
                    return None, {**report, "warnings": [f"Official source HTTP {response.status_code}"]}
                data = bytearray()
                for chunk in response.iter_content(65536):
                    data.extend(chunk)
                    if len(data) > 3 * 1024 * 1024:
                        raise RuntimeError("HTML response exceeded 3 MiB cap")
                soup = BeautifulSoup(bytes(data), "html.parser", from_encoding="utf-8")
                content = (
                    soup.select_one("article .entry-content")
                    or soup.select_one("main")
                    or soup.select_one("#dnn_ContentPane")
                )
                if content is None:
                    return None, {
                        **report,
                        "status": "schema_error",
                        "warnings": [
                            "Expected source content container absent; challenge/schema change is not an empty index"
                        ],
                    }
                for tag in content.select('nav,script,style,header,footer,[hidden],[aria-hidden="true"]'):
                    tag.decompose()
                update = soup.find(string=lambda s: bool(s and "Last Page Update:" in s))
                report.update(
                    status="ok",
                    complete=True,
                    final_url=current,
                    source_page_update=str(update).strip() if update else None,
                )
                if len(_CACHE) >= 128:
                    _CACHE.clear()
                _CACHE[url] = (time.monotonic(), content, report)
                return content, report
        raise RuntimeError("Redirect cap exceeded")
    except (requests.RequestException, RuntimeError) as exc:
        return None, {
            **report,
            "warnings": [str(exc) if isinstance(exc, RuntimeError) else "Official source request failed or timed out"],
        }


def links(content, url):
    records = {}
    for a in content.find_all("a", href=True):
        target = source_url(urljoin(url, a["href"]))
        if not target:
            continue
        title = a.get_text(" ", strip=True)
        if not title:
            continue
        key = target.split("#", 1)[0]
        if key not in records:
            records[key] = {"title": title, "url": target, "discovery_paths": [url], "body_reviewed": False}
        elif url not in records[key]["discovery_paths"]:
            records[key]["discovery_paths"].append(url)
    return list(records.values())
