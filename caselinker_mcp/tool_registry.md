# CaseLinker MCP tool registry

**Total: 36 tools** (as of `get_lifecycle_lstar`).

Authoritative implementation: `@mcp.tool()` definitions in `server.py`. This file is the human-readable catalog for docs and agent hosts.

## Tier model

Almost every tool is **public** — callable without a trusted `CASELINKER_KEY`. **Five** tools require trusted access for full export behavior (see below). The other eleven REST helpers (`get_case_count`, `get_facet_distinct`, `get_unique_tags`, etc.) are **fully public**; API key is needed for full case access, lifecycle export, and removal of rate limits. 

| Category | Count | Meaning |
|----------|------:|---------|
| Public (trusted key irrelevant) | **31** | Same behavior with or without trusted key |
| Trusted-key sensitive | **5** | Blocked or reduced without trusted key |
| **Total** | **36** | |

## Public tier (31 tools)

Trusted key does **not** change behavior (still subject to normal slowapi / public rate limits).

| Tool | Backend | Notes |
|------|---------|-------|
| `get_corpus_stats` | `GET /api/stats` | Corpus-wide counts |
| `get_cases_page` | `GET /api/cases-summaries-chunk` | Paginated summaries |
| `get_cases_by_ids` | `POST /api/cases-summaries-by-ids` | Batch summaries |
| `filter_cases_by_tags` | `POST /api/return-tagged-cases` | Tag intersection |
| `get_facet_tree` | `GET /api/facet-tree` | Facet decision tree |
| `get_cohort_members` | `POST /api/facet-cohort-members` | Cohort case IDs |
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
