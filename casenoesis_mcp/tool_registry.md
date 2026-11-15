# CaseNoesis MCP tool registry (local stdio)

**85 tools** when local writes are on, **71** when they are off. All of them run on this machine. There is no hosted MCP. WRITE tools register when `collector_disk_write_enabled()` is true (local default).

Authoritative implementation: `casenoesis_mcp/server.py`.

## Backend split

| Backend | Count | Notes |
|---------|------:|-------|
| REST API wrappers | **29** | Proxy to `GET`/`POST /api/*` |
| MCP-only (corpus graphs) | **8** | `tree_traversal`, `list_sources`, `case2cac`, four graph tools, `export_case_graph_ttl` |
| MCP-only (free public records) | **4** | DOJ press search + CourtListener/RECAP (`public_records.py`) |
| MCP-only (press collector READ) | **1** | `probe_press_url` — all hosts |
| MCP-only (collector WRITE) | **13** | Press, free RECAP, conduct filings (`collect_conduct_documents`), reference records, and reproduce-from-lookup. Disk only. No sqlite ingest |
| MCP-only (SDK encoding) | **3** | `encoding_status`, `gate_graph` (READ); `encoding_process_records` (WRITE local, under `data/encoded/`). See `docs/sdk-encoding.md` |
| MCP-only (extraction engine) | **27** | Nine READ tools over the assertion store and its timelines, five over the event log (`process_*`), six over offense conduct and trajectories (`conduct_*`), four over the fitted state machine (`esm_*`), two over the local triple store (`graph_sparql`, `graph_store_status`), and `extraction_run` (WRITE local, under `data/extracted/`). See `Architecture design.md`, sections 5, 7, 8, 10 and 11 |
| **Total (local stdio, writes on)** | **85** | **71** when `MCP_COLLECTOR_WRITE=0` |

There are **32** REST `/api/*` routes in `run/main.py`. **29** have MCP tools; four are intentionally excluded from MCP (admin/write/index): `POST /api/cache/clear`, `POST /api/case-studies/notes/{id}`, `POST /api/ontology/cache/warm`, `GET /api`.

`POST /api/llm/chat` exposes an internal `query_cases_database` function-calling tool to the LLM; that helper is **not** a separate MCP tool. MCP clients use `llm_chat` instead.

No MCP resources (`@mcp.resource`) or prompts (`@mcp.prompt`) are registered.

## Collector (press + court)

On disk: repo-root `collector/`. WRITE tools create files under `data/collected/` and do **not** auto-ingest. Never purchase PACER.

| Tool | Kind | Notes |
|------|------|-------|
| `search_doj_press_releases` | READ | DOJ News API title search |
| `probe_press_url` | READ | One URL extract/resolve, no PDF |
| `search_courtlistener` | READ | Free RECAP / opinion search |
| `list_free_recap_documents` | READ | Free filings for a `docket_id` |
| `resolve_free_recap_download` | READ | Free storage URL when `is_available` |
| `download_free_recap` | WRITE local | Known `document_id` or `docket_id` → `data/collected/recap/<domain>/` PDF + manifest |
| `harvest_doj_press_topic` | WRITE local | DOJ API harvest JSON |
| `fetch_press_listing_urls` | WRITE local | Listing → url-file |
| `resolve_press_urls` | WRITE local | URL-path resolve JSON |
| `build_press_pdf` | WRITE local | Merged PDF |
| `collect_case_dual_path` | WRITE local | A+B dual collect for one press topic |
| `fetch_seed_docs` | WRITE local | URL seed → `data/collected/hyletic_data/<collection>/` |
| `harvest_wayback_policy` | WRITE local | One dated Wayback snapshot of a policy URL |
| `harvest_platform_litigation` | WRITE local | One free RECAP filing for a platform-litigation query |
| `harvest_statutes` | WRITE local | GovInfo copy of a profile citation |
| `harvest_calibration` | WRITE local | One public calibration report from the seed list |
| `reproduce_from_lookup` | WRITE local | Read `data/collected/public/*.jsonl` and refetch `source_url`. `run=false` is the plan |

`POST /api/llm/chat` exposes an internal `query_cases_database` function-calling tool to the LLM; that helper is **not** a separate MCP tool. MCP clients use `llm_chat` instead.

No MCP resources (`@mcp.resource`) or prompts (`@mcp.prompt`) are registered.

## Extraction engine

On disk: repo-root `extraction/`. Every READ tool answers from stored assertions and decisions in `data/extracted/noesis.db`. None calls a model and none writes a value. Record text in a result has names masked; people appear as `person-1`, `person-2`.

| Tool | Kind | Notes |
|------|------|-------|
| `extraction_status` | READ | Records read, assertions by family, decisions by field, review queue, cases, graphs |
| `extraction_fields` | READ | Every field, its roles and labels; readers and families. Call first |
| `extraction_record` | READ | One record: settled values, the families behind each, open mentions with masked windows |
| `extraction_review_queue` | READ | Open mentions by field and state (`contested`, `weak`, `self_contradiction`) |
| `extraction_search` | READ | A cohort by field, role, label, domain, or numeric range. `status="agreed"` keeps two-family values |
| `extraction_count` | READ | How many records settled each label or role of a field |
| `extraction_case` | READ | A case: its records, the basis for each link, candidate links |
| `extraction_agreement` | READ | Reader agreement per field. Not accuracy |
| `case_timeline` | READ | One case: defendants (`p1`, `p2`), events in order with how each date was read, and whose each term and amount is |
| `process_log` | READ | The event log: one trace per defendant per case, events by kind, how many are dated |
| `process_variants` | READ | The paths cases take, most common first. `level="coarse"` folds charge kinds and dispositions; `dated_only` assumes no order |
| `process_model` | READ | The process tree found by the Inductive Miner, replay fitness, and the directly-follows graph with median days between steps |
| `process_conformance` | READ | Traces that depart from procedural order: `order`, `repeat`, `plea_and_verdict`. A missing step is never counted |
| `process_case` | READ | One case against the discovered model and against procedure |
| `conduct_summary` | READ | The acts read from records, by kind; how many carry a date or name a technology |
| `conduct_record` | READ | One record's acts in order, with the path at the means, act and phase levels |
| `conduct_paths` | READ | The paths offenses take at one level, and the process tree mined from them |
| `conduct_transitions` | READ | From each step, how often each step follows, with entropy |
| `conduct_compare` | READ | Divergence between offense domains at each level, beside a shuffled baseline |
| `conduct_means` | READ | Which technology is named at which act, per domain |
| `esm_machine` | READ | The fitted machine: action space per state, observed policy, T(s'\|s,a) with counts |
| `esm_states` | READ | States learned per domain, and whether they hold across domains against a resampling floor |
| `esm_decide` | READ | The goal-conditioned decision model under declared costs: L\*, agreement, fitted rationality against random costs |
| `esm_coverage` | READ | Backbone by coverage threshold, and what removing each state would leave untouched |
| `graph_sparql` | READ | SPARQL over the local Oxigraph store of validated engine graphs. One named graph per record. Updates refused |
| `graph_store_status` | READ | Named graphs, quads, store location, example queries |
| `extraction_run` | WRITE local | Read records, link cases, optionally build and validate graphs and load them into the triple store. At most 2,000 per call |

## Tier model

Almost every tool is **public** — callable without a trusted `CASELINKER_KEY`. **Five** tools require trusted access for full export behavior (see below).

| Category | Count | Meaning |
|----------|------:|---------|
| Public (trusted key irrelevant) | **32** | Same behavior with or without trusted key |
| Trusted-key sensitive | **5** | Blocked or reduced without trusted key |
| **Total in this split** | **37** | Corpus API surface only. Add 5 collector READ, 13 collector WRITE, 3 SDK encoding tools, and 27 extraction tools for the local total of **85**. |

## Public tier (32 tools)

Trusted key does **not** change behavior (still subject to normal slowapi / public rate limits).

| Tool | Backend | Notes |
|------|---------|-------|
| `get_corpus_stats` | `GET /api/stats` | Corpus-wide counts |
| `get_cases_page` | `GET /api/cases-summaries-chunk` | Paginated summaries |
| `get_cases_by_ids` | `POST /api/cases-summaries-by-ids` | Batch summaries |
| `filter_cases_by_tags` | `POST /api/return-tagged-cases` | Tag intersection |
| `get_facet_tree` | `GET /api/facet-tree` or MCP-local | Facet tree; optional `case_ids` for subset |
| `get_cohort_members` | `POST /api/facet-cohort-members` or MCP-local | Cohort case IDs; optional `case_ids` |
| `tree_traversal` | MCP-only | Random + targeted facet samples over a case subset |
| `run_automated_analysis` | `GET /api/automated-analysis` | Similarity + triage insights |
| `triage_text` | `POST /api/triage-live` | In-memory narrative triage |
| `get_triage_eval_metrics` | `GET /api/triage-eval` | Classifier eval metrics |
| `get_knowledge_graph` | `GET /api/ontology/merged` | Pre-merged ontology pool |
| `get_case_graph_manifest` | `GET /api/ontology/cases` | Graph coverage metadata |
| `get_case_studies` | `GET /api/case-studies` | Era-based narratives |
| `q1_platform_evidence` | `GET /api/q1/platform-evidence` | Q1 platform harm cohort index or per-platform evidence |
| `list_sources` | (static) | Source catalog |
| `case2cac` | MCP-only | On-demand cohort graph → `graph_id` |
| `graph_get_neighbors` | MCP-only | Traverse session graph |
| `graph_find_cases_by_concept` | MCP-only | Concept → case IDs |
| `graph_summarize` | MCP-only | Structural graph summary |
| `graph_compare_cohorts` | MCP-only | Diff two session graphs |
| `export_case_graph_ttl` | MCP-only | Session graph → JSON-LD + Turtle; optional save to graph_output pool |
| `get_case_count` | `GET /api/case-count` | Fast COUNT |
| `get_facet_distinct` | `GET /api/facet-distinct` | Facet prune values |
| `get_unique_tags` | `GET /api/tags` | All tag dimensions |
| `tag_threader` | `POST /api/tag-threader` | Tag intersection + threads |
| `get_case_ids_by_filter` | `GET /api/case-ids-by-filter` | Structured ID filters |
| `get_stats_detailed` | `GET /api/stats-detailed` | Chart-ready stats |
| `get_technology_revolver` | `GET /api/technology-revolver` | Tech by era |
| `get_cluster_groups` | `GET /api/cluster-groups` | Similarity clusters |
| `get_location_stats` | `GET /api/location-stats` | Map aggregation |
| `get_triage_model_corpus` | `GET /api/triage-model-corpus` | Bundle predictions |
| `get_case_study_notes` | `GET /api/case-studies/notes/{id}` | Community notes |

### On-demand graph workflow

1. `case2cac(case_ids)` → `graph_id`
2. `graph_get_neighbors` / `graph_find_cases_by_concept` / `graph_summarize`
3. `export_case_graph_ttl(graph_id, case_id?, pool?)` → `{ jsonld, turtle, triple_count, node_count, saved? }`

Session graphs are stored in Redis when available (`caselinker:mcp:graph:{id}`, 2-hour TTL); otherwise in-process memory for local dev.

## Trusted-key sensitive (5 tools)

Requires `CASELINKER_KEY` / `CaseLinker-Key` listed in server `CASELINKER_TRUSTED_KEYS` for full behavior.

| Tool | Without trusted key | With trusted key |
|------|---------------------|------------------|
| `get_all_cases` | **403** from API (or MCP local error if no key configured) | Full bulk export; optional `include_raw_data` |
| `get_lifecycle_cases` | **403** from API (or MCP local error if no key configured) | Lifecycle swimlane / visualization payload |
| `get_lifecycle_lstar` | **403** from API (or MCP local error if no key configured) | Full `lstar_all_cases.json` (transition matrix, global L*, per-case details) |
| `get_case` | Works; **sanitized** (no `raw_data` / narrative blobs) | Works; **full** case payload including `raw_data` |
| `llm_chat` | Works; **50 requests/IP/day** (+ slowapi 15/min) | Works; **daily cap exempt** (+ slowapi 15/min still applies) |

`get_all_cases` and both lifecycle tools are blocked without trusted access. `get_case` and `llm_chat` are public tools with richer responses or limits when a trusted key is forwarded on REST calls. The public `/lifecycle` page embeds visualization data server-side and does not require a browser API key.
