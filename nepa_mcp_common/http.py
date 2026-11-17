"""HTTP helpers for upstream environmental data services."""

from __future__ import annotations

import json
from typing import Any

import requests
from urllib3.exceptions import ReadTimeoutError

DEFAULT_TIMEOUT_SECONDS = 20


class UpstreamServiceError(RuntimeError):
    """Raised when an upstream service fails or returns an error payload."""

    def __init__(self, message: str, *, reason: str = "upstream_error"):
        super().__init__(message)
        self.reason = reason


class ResponseTooLarge(UpstreamServiceError):
    """The decoded response exceeded the caller's byte limit."""


def _reject_redirect(response, **kwargs):
    # Requests otherwise reads the entire redirect body before following it.
    if response.is_redirect:
        response.close()
        raise UpstreamServiceError("Unexpected redirect for a size-limited request")


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
    max_bytes: int | None = None,
) -> dict[str, Any]:
    """Return a JSON object from an upstream service with consistent errors."""
    try:
        if max_bytes is None:
            response = requests.get(url, params=params, timeout=timeout)
            response.raise_for_status()
        else:
            with requests.get(
                url, params=params, timeout=timeout, stream=True, hooks={"response": _reject_redirect}
            ) as response:
                response.raise_for_status()
                body = bytearray()
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    if len(body) + len(chunk) > max_bytes:
                        raise ResponseTooLarge(f"{service_name} response exceeded {max_bytes} bytes")
                    body.extend(chunk)
    except requests.RequestException as exc:
        # During iter_content, Requests wraps a read timeout in ConnectionError.
        if isinstance(exc, requests.Timeout) or (exc.args and isinstance(exc.args[0], ReadTimeoutError)):
            raise UpstreamServiceError(f"{service_name} timed out. Try again.", reason="upstream_timeout") from exc
        if isinstance(exc, requests.HTTPError) and exc.response is not None:
            status = exc.response.status_code
            if status == 429:
                raise UpstreamServiceError(
                    f"{service_name} rate-limited this request (HTTP 429). Wait before retrying.",
                    reason="upstream_rate_limited",
                ) from exc
            raise UpstreamServiceError(f"{service_name} returned HTTP {status}.", reason="upstream_http_error") from exc
        if isinstance(exc, requests.ConnectionError):
            raise UpstreamServiceError(
                f"The connection to {service_name} failed. Try again.", reason="upstream_connection_error"
            ) from exc
        raise UpstreamServiceError(f"{service_name} request failed: {exc}") from exc

    try:
        data = response.json() if max_bytes is None else json.loads(body)
    except ValueError as exc:
        raise UpstreamServiceError(f"{service_name} returned invalid JSON", reason="invalid_upstream_response") from exc

    if not isinstance(data, dict):
        raise UpstreamServiceError(
            f"{service_name} returned unexpected JSON type: {type(data).__name__}", reason="invalid_upstream_response"
        )

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


def get_json_rows(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    timeout: float | tuple[float, float] = DEFAULT_TIMEOUT_SECONDS,
    service_name: str = "upstream service",
) -> list[dict[str, Any]]:
    """GET a JSON array of records, retaining the object helpers' error contract.

    Public tabular APIs such as Socrata return arrays rather than objects.
    An error object or malformed row must not become a successful empty list.
    """
    try:
        response = requests.get(url, params=params, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise UpstreamServiceError(f"{service_name} request failed: {exc}") from exc
    try:
        data = response.json()
    except ValueError as exc:
        raise UpstreamServiceError(f"{service_name} returned invalid JSON") from exc
    if isinstance(data, dict) and ("error" in data or "message" in data):
        raise UpstreamServiceError(f"{service_name} returned an error: {data.get('message') or data['error']}")
    if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
        raise UpstreamServiceError(f"{service_name} returned unexpected JSON rows")
    return data
