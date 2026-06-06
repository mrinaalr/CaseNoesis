"""Tests for per-request CaseLinker-Key forwarding (SSE) and env fallback (stdio)."""

from __future__ import annotations

import os

from caselinker_mcp.client import (
    bind_request_caselinker_key,
    caselinker_key_configured,
    effective_caselinker_key,
    require_caselinker_key,
    reset_request_caselinker_key,
    _headers,
)


def test_request_header_takes_precedence_over_env(monkeypatch):
    monkeypatch.setenv("CASELINKER_KEY", "env_key")
    token = bind_request_caselinker_key("header_key")
    try:
        assert effective_caselinker_key() == "header_key"
        assert _headers()["CaseLinker-Key"] == "header_key"
        assert caselinker_key_configured()
        assert require_caselinker_key() is None
    finally:
        reset_request_caselinker_key(token)


def test_empty_header_falls_back_to_env(monkeypatch):
    monkeypatch.setenv("CASELINKER_KEY", "env_key")
    token = bind_request_caselinker_key("")
    try:
        assert effective_caselinker_key() == "env_key"
        assert _headers()["CaseLinker-Key"] == "env_key"
    finally:
        reset_request_caselinker_key(token)


def test_no_header_no_env_is_public_tier(monkeypatch):
    monkeypatch.delenv("CASELINKER_KEY", raising=False)
    token = bind_request_caselinker_key(None)
    try:
        assert effective_caselinker_key() == ""
        assert "CaseLinker-Key" not in _headers()
        assert not caselinker_key_configured()
        err = require_caselinker_key()
        assert err is not None and "No trusted key" in err["error"]
    finally:
        reset_request_caselinker_key(token)


def test_stdio_env_only(monkeypatch):
    """Unbound request context behaves like legacy stdio (env var only)."""
    monkeypatch.setenv("CASELINKER_KEY", "mars_is_the_best_dog")
    assert effective_caselinker_key() == "mars_is_the_best_dog"
    assert _headers()["CaseLinker-Key"] == "mars_is_the_best_dog"


def test_middleware_binds_header(monkeypatch):
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.routing import Route
    from starlette.testclient import TestClient

    from caselinker_mcp.server import _wrap_mcp_request_context

    captured: dict[str, str] = {}

    async def handler(request: Request):
        captured["key"] = effective_caselinker_key()
        captured["headers"] = _headers().get("CaseLinker-Key", "")
        return JSONResponse({"ok": True})

    app = Starlette(routes=[Route("/", handler)])
    app = _wrap_mcp_request_context(app)

    with TestClient(app) as client:
        resp = client.get("/", headers={"CaseLinker-Key": "cory_trusted_key"})
        assert resp.status_code == 200
        assert captured["key"] == "cory_trusted_key"
        assert captured["headers"] == "cory_trusted_key"

    monkeypatch.setenv("CASELINKER_KEY", "env_key")
    with TestClient(app) as client:
        resp = client.get("/")
        assert resp.status_code == 200
        assert captured["key"] == "env_key"
