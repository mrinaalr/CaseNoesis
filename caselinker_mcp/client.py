"""Thin async HTTP client for the CaseLinker REST API."""

from __future__ import annotations

import os
from typing import Any

import httpx

BASE_URL = os.getenv("CASELINKER_API_URL", "https://caselinker.up.railway.app").rstrip("/")
DEFAULT_TIMEOUT = 30.0
BULK_TIMEOUT = 180.0

_TRUSTED_KEY_HINT = (
    "Set CASELINKER_KEY to a value listed in CASELINKER_TRUSTED_KEYS on the server."
)


def caselinker_key_configured() -> bool:
    """True when CASELINKER_KEY is set in the MCP server environment."""
    return bool(os.getenv("CASELINKER_KEY", "").strip())


def require_caselinker_key() -> dict[str, str] | None:
    """Return an error payload when CASELINKER_KEY is missing for trusted-tier tools."""
    if caselinker_key_configured():
        return None
    return {
        "error": f"CASELINKER_KEY is not set. {_TRUSTED_KEY_HINT}",
    }


def _headers() -> dict[str, str]:
    headers = {"Accept": "application/json"}
    key = os.getenv("CASELINKER_KEY", "").strip()
    if key:
        headers["CaseLinker-Key"] = key
    return headers


def _http_error_payload(exc: httpx.HTTPStatusError) -> dict[str, Any]:
    detail = exc.response.text[:500] if exc.response is not None else str(exc)
    if exc.response is not None and exc.response.status_code in (401, 403):
        return {
            "error": f"HTTP {exc.response.status_code}: trusted access denied. {_TRUSTED_KEY_HINT}",
            "detail": detail,
        }
    return {"error": f"HTTP {exc.response.status_code if exc.response else 'error'}: {detail}"}


async def api_get(
    path: str,
    params: dict[str, Any] | None = None,
    *,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict | list:
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=timeout) as client:
        try:
            response = await client.get(path, params=params, headers=_headers())
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            payload = _http_error_payload(exc)
            raise RuntimeError(str(payload["error"])) from exc


async def api_post(
    path: str,
    body: dict | list,
    *,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict | list:
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=timeout) as client:
        try:
            response = await client.post(path, json=body, headers=_headers())
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            payload = _http_error_payload(exc)
            raise RuntimeError(str(payload["error"])) from exc
