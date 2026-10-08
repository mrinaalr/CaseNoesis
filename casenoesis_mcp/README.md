# CaseNoesis MCP

Local stdio server for agents. It exposes corpus tools against a FastAPI process on this machine, and the collector: press, court (CourtListener and free RECAP), and reference records.

There is no hosted MCP. Railway may serve the website. It does not serve this process.

Corpus tools are read-only against the local database. Collector WRITE tools write files under `data/collected/`. They do not ingest.

Catalog: [`tool_registry.md`](tool_registry.md). Parameter detail is the docstring on each `@mcp.tool()` in `server.py`.

**54 tools** when collector writes are enabled (local default). **42** when writes are off: the 12 collector WRITE tools are not registered.

## Prerequisites

```bash
pip install mcp httpx
```

From the repo root, with the project environment:

```bash
pip install -r requirements.txt
```

## Run

```bash
CASENOESIS_API_URL=http://localhost:8000 MCP_COLLECTOR_WRITE=1 \
python -m casenoesis_mcp.server
```

The process speaks MCP on stdin/stdout. Logs go to stderr.

Corpus tools need the API:

```bash
python3 run/main.py
```

Collector tools do not. They call the DOJ News API and CourtListener directly.

## Environment

| Variable | Default | Purpose |
|---|---|---|
| `CASENOESIS_API_URL` | `http://localhost:8000` | Local FastAPI for corpus tools |
| `MCP_COLLECTOR_WRITE` | on locally | `1` force on, `0` force off. Off when `RAILWAY_*` is set |
| `COURTLISTENER_API_TOKEN` | unset | Free CourtListener token. Never PACER |
| `CASELINKER_KEY` | unset | Trusted key forwarded to the local API for five export tools |
| `CASENOESIS_MCP_HTTP` | unset | `1` plus `MCP_TRANSPORT=sse` binds loopback only (`127.0.0.1`) |

## Cursor

Copy [`mcp.json.example`](mcp.json.example) to `.cursor/mcp.json` and reload MCP. Do not commit a file that holds a token.

```json
{
  "mcpServers": {
    "casenoesis": {
      "command": "python",
      "args": ["-m", "casenoesis_mcp.server"],
      "cwd": "${workspaceFolder}",
      "env": {
        "CASENOESIS_API_URL": "http://localhost:8000",
        "MCP_COLLECTOR_WRITE": "1"
      }
    }
  }
}
```

## Tools

### Collector READ (always)

`search_doj_press_releases`, `probe_press_url`, `search_courtlistener`, `list_free_recap_documents`, `resolve_free_recap_download`.

### Collector WRITE (local only)

Press: `harvest_doj_press_topic`, `fetch_press_listing_urls`, `resolve_press_urls`, `build_press_pdf`, `collect_case_dual_path`.

Court: `download_free_recap`. Search first with `search_courtlistener`, `list_free_recap_documents`, and `resolve_free_recap_download`.

Reference records: `fetch_seed_docs`, `harvest_wayback_policy`, `harvest_platform_litigation`, `harvest_statutes`, `harvest_calibration`.

`reproduce_from_lookup` reads `data/collected/public/*.jsonl` and fetches `source_url`. `run=false` returns the plan. `run=true` fetches `limit` rows (default 1). A docket page is skipped. PACER is never purchased. Same command: `python3 -m collector.reproduce`.

WRITE responses include `"write": true`. Files go to `data/collected/`. Nothing is ingested. PACER is never purchased.

### Corpus

Search, stats, triage, graphs, and case studies. These proxy the local API or build a session graph in memory. Five tools change behavior when `CASELINKER_KEY` is set and listed in the server trusted keys: `get_all_cases`, `get_lifecycle_cases`, `get_lifecycle_lstar`, `get_case`, `llm_chat`. Without that key, bulk and lifecycle export are blocked, `get_case` is sanitized, and `llm_chat` keeps a daily cap.

No MCP tool mutates the sqlite corpus.

## On-demand graphs

1. `filter_cases_by_tags` or `get_cohort_members` for case ids.
2. `case2cac(case_ids)` returns `graph_id`.
3. `graph_get_neighbors`, `graph_find_cases_by_concept`, or `graph_summarize`.
4. `export_case_graph_ttl` for JSON-LD and Turtle.
5. `graph_compare_cohorts` on two session graphs.

Session graphs live in memory on this machine, or in Redis when `REDIS_URL` is set (2-hour TTL).
