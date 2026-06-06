# CaseLinker MCP Server

The CaseLinker MCP (Model Context Protocol) server exposes the corpus, knowledge graphs, triage scoring, and automated analysis as structured tools for agent and LLM workflows. It wraps the existing CaseLinker REST API over HTTP — read-only, no direct database access — so it works the same against local `run/main.py` and the Railway production deployment.

## Prerequisites

```bash
pip install mcp httpx
```

Outside a virtual environment you may need:

```bash
pip install mcp httpx --break-system-packages
```

Or install from the repo root after activating `.venv`:

```bash
pip install -r requirements.txt
```

## Run standalone (verify)

```bash
CASELINKER_API_URL=https://caselinker.up.railway.app \
python -m caselinker_mcp.server
```

The process starts silently on stdin/stdout (MCP wire protocol). Diagnostic logs go to stderr only. Press Ctrl+C to stop.

Point at a local server instead:

```bash
CASELINKER_API_URL=http://localhost:8000 python -m caselinker_mcp.server
```

## Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `CASELINKER_API_URL` | `https://caselinker.up.railway.app` | Base URL for the CaseLinker REST API |
| `CASELINKER_KEY` | (unset) | Sent as `CaseLinker-Key` header when set (trusted bulk access) |

Set `CASELINKER_KEY` to a value listed in `CASELINKER_TRUSTED_KEYS` on Railway for full-access tools (bulk export, unsanitized single-case payloads, LLM rate-limit exemption).

## Tool tiers

### Public tier (no trusted key required)

Works against the public CaseLinker REST API without bulk-export privileges:

- Corpus: `get_corpus_stats`, `get_cases_page`, `get_cases_by_ids`, `get_case` (sanitized without trusted key)
- Search / cohorts: `filter_cases_by_tags`, `get_facet_tree`, `get_cohort_members`
- Analysis: `run_automated_analysis`, `triage_text`, `get_triage_eval_metrics`
- Ontology (pre-merged): `get_knowledge_graph`, `get_case_graph_manifest`
- Reference: `get_case_studies`, `list_sources`
- On-demand graphs (MCP-only, local Python): `case2cac`, `graph_get_neighbors`, `graph_find_cases_by_concept`, `graph_summarize`, `graph_compare_cohorts`

### Trusted-key tier (set `CASELINKER_KEY`)

Requires `CASELINKER_KEY` to match an entry in `CASELINKER_TRUSTED_KEYS` on the server. Non-trusted keys receive **403** from the API.

| Tool | API | Notes |
|------|-----|-------|
| `get_all_cases` | `GET /api/cases` | Full corpus bulk export; optional `include_raw_data` |
| `get_case` | `GET /api/cases/{id}` | Unsanitized narratives when key is trusted |
| `get_case_count` | `GET /api/case-count` | Fast total count |
| `get_facet_distinct` | `GET /api/facet-distinct` | Facet prune values |
| `get_unique_tags` | `GET /api/tags` | All tag dimensions |
| `tag_threader` | `POST /api/tag-threader` | Tag intersection + thread links |
| `get_case_ids_by_filter` | `GET /api/case-ids-by-filter` | Structured ID filters |
| `get_stats_detailed` | `GET /api/stats-detailed` | Chart-ready detailed stats |
| `get_technology_revolver` | `GET /api/technology-revolver` | Tech landscape by era |
| `get_cluster_groups` | `GET /api/cluster-groups` | Pre-computed similarity groups |
| `get_location_stats` | `GET /api/location-stats` | Map aggregation |
| `get_triage_model_corpus` | `GET /api/triage-model-corpus` | Bundle predictions over live DB |
| `get_case_study_notes` | `GET /api/case-studies/notes/{id}` | Community notes (read-only) |
| `llm_chat` | `POST /api/llm/chat` | NL → read-only SQL; trusted key skips daily cap |

No write tools, PDF ingestion, or database mutation endpoints are exposed via MCP.

## Cursor configuration

Add to `.cursor/mcp.json` at the repo root (do **not** commit this file if it contains your API key):

```json
{
  "mcpServers": {
    "caselinker": {
      "command": "python",
      "args": ["-m", "caselinker_mcp.server"],
      "cwd": "${workspaceFolder}",
      "env": {
        "CASELINKER_API_URL": "https://caselinker.up.railway.app",
        "CASELINKER_KEY": ""
      }
    }
  }
}
```

Fill in `CASELINKER_KEY` locally if you need trusted-key endpoints.

## Hosted (Railway)

When CaseLinker runs on Railway, the MCP server is mounted on the main FastAPI app at **`/mcp/sse`** (no separate service or Procfile entry). Client messages POST to **`/mcp/messages?session_id=...`** (no trailing slash; trailing-slash redirects break some MCP clients).

**SSE URL:** `https://caselinker.up.railway.app/mcp/sse`

**Cursor config (URL transport):**

```json
{
  "mcpServers": {
    "caselinker-hosted": {
      "url": "https://caselinker.up.railway.app/mcp/sse",
      "headers": {
        "Authorization": "Bearer <your MCP_ACCESS_KEY>",
        "CaseLinker-Key": "<your trusted key>"
      }
    }
  }
}
```

Public tier only (no trusted key): omit `CaseLinker-Key` from `headers`.

**Railway environment variables:**

| Variable | Purpose |
|----------|---------|
| `MCP_ACCESS_KEY` | Gates inbound MCP HTTP requests (`Authorization: Bearer …`) |

`MCP_ACCESS_KEY` is separate from `CASELINKER_KEY` / `CaseLinker-Key`:

- **`MCP_ACCESS_KEY`** — who may connect to the MCP server (`Authorization: Bearer …`)
- **`CASELINKER_KEY` env** (stdio) or **`CaseLinker-Key` header** (SSE) — what the MCP server sends to the CaseLinker REST API for trusted-tier tools

Per-user trusted access over SSE: pass `CaseLinker-Key` in `mcp.json` `headers`. The server forwards it on outbound REST calls. If the header is absent, it falls back to server-side `CASELINKER_KEY` env (if set), then public tier only.

Add `.cursor/mcp.json` to `.gitignore` if it contains secrets.

## On-Demand Graph Generation

Workflow for cohort-specific CAC ontology graphs (MCP-only; not REST):

1. Use `filter_cases_by_tags` or `get_cohort_members` to find case IDs
2. Call `case2cac(case_ids)` — returns `graph_id` and a structural summary
3. Use `graph_id` with `graph_get_neighbors`, `graph_find_cases_by_concept`, or `graph_summarize`
4. Optionally run `case2cac` on a second cohort and call `graph_compare_cohorts` to diff them (e.g. Discord vs Roblox for Q1/Q2/Q3 research)

Graphs live in an in-memory session store only (not persisted across restarts).

## Local stdio transport

The default entry point uses stdio (local agent hosts):

```bash
python -m caselinker_mcp.server
```

For a standalone SSE process (not via Railway mount), set `MCP_TRANSPORT=sse` and optionally `PORT` (default 8001).

## Tools

See **Tool tiers** above and tool docstrings in `server.py` for the full public vs trusted-key catalog.
