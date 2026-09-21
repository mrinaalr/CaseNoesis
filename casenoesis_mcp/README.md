# CaseNoesis MCP (local, private)

CaseLinker is the **public ICAC collector** (hosted MCP + query APIs).  
CaseNoesis is the **private research engine**: heterogeneous press + court collection, analysis, and falsification of AfH outside CSEA.

This MCP server is **stdio-only**. It is not mounted on Railway. Strangers do not get a CaseLinker-style `/mcp-http/` against this repo.

Agents (Cursor, etc.) spawn:

```bash
CASENOESIS_API_URL=http://localhost:8000 MCP_COLLECTOR_WRITE=1 \
python -m casenoesis_mcp.server
```

Cursor config: copy [`mcp.json.example`](mcp.json.example) to `.cursor/mcp.json`, then **reload MCP**.

| Need | Where |
|------|--------|
| Collect 100–1000 press + free RECAP | CLI `collector/run_bulk.py`; MCP only for small batches |
| Analyze a local corpus | Corpus tools wrapping **local** `python3 run/main.py` (`http://localhost:8000`) |
| Public ICAC query API | CaseLinker (`https://caselinker.up.railway.app`) — not this process |

## Environment

| Variable | Default | Purpose |
|----------|---------|---------|
| `CASENOESIS_API_URL` | `http://localhost:8000` | Local FastAPI for corpus tools |
| `MCP_COLLECTOR_WRITE` | on (local) | Harvest/PDF/bulk write to `data/collected/` |
| `COURTLISTENER_API_TOKEN` | unset | Optional free token (rate limits). Never PACER |
| `CASELINKER_KEY` | unset | Optional trusted key on the **local** API |
| `CASENOESIS_MCP_HTTP` | unset | Emergency local loopback SSE (`127.0.0.1` only) |

`CASELINKER_API_URL` is still accepted as a fallback alias of `CASENOESIS_API_URL`. Do not point it at Railway for this server.

Start the website/API locally if you want corpus tools (stats, graphs, triage):

```bash
python3 run/main.py
```

Collector tools work **without** FastAPI — they call the DOJ News API and CourtListener directly.

## Tools (50 local)

Catalog: [`tool_registry.md`](tool_registry.md).

**Collection (the scraping suite agents should use)**

- READ: `search_doj_press_releases`, `probe_press_url`, `search_courtlistener`, `list_free_recap_documents`, `resolve_free_recap_download`
- WRITE: `harvest_doj_press_topic`, `fetch_press_listing_urls`, `resolve_press_urls`, `build_press_pdf`, `collect_case_dual_path`, `collect_record`, `collect_bulk`, `download_free_recap`

`collect_record()` pulls one new public record from domain profiles (not a URL you already know). `download_free_recap(document_id=…)` writes a known free filing. `collect_bulk` MCP default is 1 press / 0 court so the tool does not time out — use it for small agent batches. The 1000/50 fill is CLI: `python collector/run_bulk.py --press-count 1000 --court-count 50`.

**Analysis** — same corpus/graph/triage surface as before, against localhost, not caselinker.up.railway.app.

## Why not hosted MCP

Railway serves CaseNoesis as a **website and documentation**. It does not expose an agent-query MCP or OpenAPI. Collection writes JSON/PDFs on the researcher’s disk; a hosted MCP would write to an ephemeral filesystem the caller never sees.
