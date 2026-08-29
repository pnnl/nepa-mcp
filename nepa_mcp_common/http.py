"""HTTP helpers for upstream environmental data services."""

from __future__ import annotations

from typing import Any

import requests

DEFAULT_TIMEOUT_SECONDS = 20


class UpstreamServiceError(RuntimeError):
    """Raised when an upstream service fails or returns an error payload."""


def _format_arcgis_error(error: Any) -> str:
    if not isinstance(error, dict):
        return str(error)

    message = error.get("message") or "Unknown ArcGIS error"
    details = error.get("details")
    if isinstance(details, list) and details:
        return f"{message}: {'; '.join(str(detail) for detail in details)}"
    return str(message)


def get_json(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    timeout: float | tuple[float, float] = DEFAULT_TIMEOUT_SECONDS,
    service_name: str = "upstream service",
) -> dict[str, Any]:
    """Return a JSON object from an upstream service with consistent errors."""
    try:
        response = requests.get(url, params=params, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise UpstreamServiceError(f"{service_name} request failed: {exc}") from exc

    try:
        data = response.json()
    except ValueError as exc:
        raise UpstreamServiceError(f"{service_name} returned invalid JSON") from exc

    if not isinstance(data, dict):
        raise UpstreamServiceError(f"{service_name} returned unexpected JSON type: {type(data).__name__}")

    if "error" in data:
        raise UpstreamServiceError(f"{service_name} returned an error: {_format_arcgis_error(data['error'])}")

    return data


def post_json(
    url: str,
    *,
    json_body: dict[str, Any],
    timeout: float | tuple[float, float] = DEFAULT_TIMEOUT_SECONDS,
    service_name: str = "upstream service",
) -> dict[str, Any]:
    """POST a JSON object and return a JSON-object response with consistent errors."""
    try:
        response = requests.post(url, json=json_body, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise UpstreamServiceError(f"{service_name} request failed: {exc}") from exc

    try:
        data = response.json()
    except ValueError as exc:
        raise UpstreamServiceError(f"{service_name} returned invalid JSON") from exc

    if not isinstance(data, dict):
        raise UpstreamServiceError(f"{service_name} returned unexpected JSON type: {type(data).__name__}")

    if "error" in data:
        raise UpstreamServiceError(f"{service_name} returned an error: {data['error']}")

    return data
