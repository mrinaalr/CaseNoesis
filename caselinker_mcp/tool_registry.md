# CaseLinker MCP tool registry

**Total: 33 tools** (as of `export_case_graph_ttl`).

Authoritative implementation: `@mcp.tool()` definitions in `server.py`. This file is the human-readable catalog for docs and agent hosts.

## Tier model

Almost every tool is **public** — callable without a trusted `CASELINKER_KEY`. Only **three** tools behave differently when a trusted key is present (see below). The other eleven REST helpers (`get_case_count`, `get_facet_distinct`, `get_unique_tags`, etc.) are **fully public**; they were previously mislabeled as trusted-tier in older docs.

| Category | Count | Meaning |
|----------|------:|---------|
| Public (trusted key irrelevant) | **30** | Same behavior with or without trusted key |
| Trusted-key sensitive | **3** | Blocked or reduced without trusted key |
| **Total** | **33** | |

## Public tier (30 tools)

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
| `list_sources` | (static) | Source catalog |
| `case2cac` | MCP-only | On-demand cohort graph → `graph_id` |
| `graph_get_neighbors` | MCP-only | Traverse session graph |
| `graph_find_cases_by_concept` | MCP-only | Concept → case IDs |
| `graph_summarize` | MCP-only | Structural graph summary |
| `graph_compare_cohorts` | MCP-only | Diff two session graphs |
| `export_case_graph_ttl` | MCP-only | Session graph → Turtle RDF |
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
3. `export_case_graph_ttl(graph_id)` → `{ turtle, triple_count, node_count }`

Session graphs live in process memory (`_graph_store`); lost on restart.

## Trusted-key sensitive (3 tools)

Requires `CASELINKER_KEY` / `CaseLinker-Key` listed in server `CASELINKER_TRUSTED_KEYS` for full behavior.

| Tool | Without trusted key | With trusted key |
|------|---------------------|------------------|
| `get_all_cases` | **403** from API (or MCP local error if no key configured) | Full bulk export; optional `include_raw_data` |
| `get_case` | Works; **sanitized** (no `raw_data` / narrative blobs) | Works; **full** case payload including `raw_data` |
| `llm_chat` | Works; **50 requests/IP/day** (+ slowapi 15/min) | Works; **daily cap exempt** (+ slowapi 15/min still applies) |

Only `get_all_cases` is blocked without trusted access. The other two are public tools with richer responses or limits when a trusted key is forwarded on REST calls.
