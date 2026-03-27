# Search: conceptual direction, tree, mechanism, and future work

This document describes the **Search** tab: an interactive way to explore the CaseLinker corpus without exposing individual records in ways that conflict with mosaic-style privacy / adversial misuse. Implementation will live on the `search` branch and evolve in phases.

---

## 1. Goals and constraints

### Primary goals

- **Interactive exploration**: A prominent search experience (e.g. a dedicated tab) where the user can type or select criteria and **drill into** the dataset along a structured path—not a single flat keyword dump.
- **Queryable backend**: Requests resolve against the existing case store (SQLite locally, PostgreSQL in production) and any auxiliary indices we add for search facets.
- **Phased intelligence**: Start with a **deterministic decision tree / guided graph** over known dimensions (topics, platforms, severity buckets, jurisdiction, time windows, etc.). Reserve a path to richer **natural-language or agent-style** interaction later.

### Mosaic-oriented disclosure

- **Do not optimize for “open this exact case”** as the default success mode.
- The **search result schema** should emphasize **groups**: sets of anonymized or opaque identifiers (e.g. internal cluster keys, cohort labels, or bucketing keys), **counts**, and **aggregate descriptors**—not a direct “here is case `azicac_2013_january_001`” unless a separate policy explicitly allows it.
- The UI can still **drive** the rest of the app (e.g. “highlight this region of the similarity graph”) using those **group ids** or **filters**, keeping per-case detail behind thresholds or separate flows.

This aligns with using CaseLinker for **pattern discovery** and **research navigation** rather than case lookup as a directory service.

---

## 2. Conceptual model: tree vs graph

### Decision tree (phase 1)

- **Nodes** = questions or facets drawn from the data model: e.g. source/jurisdiction, broad `case_topics`, `platforms_used`, coarse time range, high-level `severity_indicators` buckets, investigation posture, etc.
- **Edges** = user choices or parsed intent that narrow the population.
- **Leaves** (or stopping points) = **cohorts**: `{ group_id, member_ids_or_hashes, count, summary_stats }` where `member_*` may be opaque or omitted in the API depending on policy.

The tree is **authoritative** (curated from the schema and safe enumerations) so behavior is reproducible and explainable.

### Graph (phase 1.5+)

- The same facets can be modeled as a **directed graph** with multiple paths to similar cohorts (e.g. “platform → topic → era” vs “topic → platform → era”).
- **Combined phrases** in the search bar map to **paths** or **subgraphs**: conjunctions narrow; disjunctions branch; negation excludes subtrees where supported.
- Precomputed structures already in the stack (e.g. cluster-related tables) can feed **group ids** that are stable enough to reference in search results without exposing raw case narratives in the search response itself.

---

## 3. Search bar UX (copy and composition)

### Prompt pattern

A guiding template such as:

> I am interested in cases involving **___** **___** **___** **___**.

- Blanks map to **slots**: e.g. domain phrases (topics), modality (online / hands-on), geography bucket, time period, platform family, or outcome class—exact slot design follows the tree.
- Users can **combine** fragments: multiple topics, “and/or” style composition (initially simplified to AND-only or fixed templates to avoid ambiguous boolean parsing).

### Interaction modes

1. **Structured**: chips / dropdowns synced to the tree (fast, accessible).
2. **Semi-natural**: typed text parsed into **known facet tokens** + confidence; unknown tokens become “soft” filters or are ignored with UI feedback.
3. **Future**: full NL or agent loop—see §5.

---

## 4. Search mechanism and API shape (intended)

### Request (conceptual)

- `query`: string (optional) — free text aligned with the template.
- `facets`: explicit key/value or path segments (optional) — mirrors tree choices for reproducibility.
- `cursor` / `step`: optional state for multi-step drill-down in the tree.

### Response (conceptual) — **group-centric schema**

- **`groups`**: array of objects such as:
  - `group_id` — stable reference for UI and downstream visualization (not necessarily a case id).
  - `case_count` — aggregate size.
  - `labels` — human-readable summary of the cohort (no verbatim PII).
  - `facet_signature` — what dimensions define this group (for transparency).
  - Optional: `representative_features` — aggregated stats only.

- **`next_options`**: suggested branches (child nodes) to continue the tree/graph from the current state.

- **`provenance`**: which tree version / dataset snapshot was used (for audits).

Individual case ids may appear only in **non-search** endpoints or under **stricter** policies—not as the default payload of search.

### Backend implementation sketch

- **Phase A**: Map facets to SQL/JSON filters over `cases` and related tables (`case_topics`, `platforms_used`, demographics, etc.—see `Architecture design.md` and storage layer).
- **Phase B**: Materialized facet counts or small rollup tables if interactive performance requires it.
- **Phase C**: Optional embedding or LLM layer **only** where policy allows, still returning **groups** by default.

---

## 5. Future expansion

| Direction | Role |
|-----------|------|
| **Richer NL** | Parse “interested in …” into facet paths; clarify via disambiguation prompts instead of one-shot black-box retrieval. |
| **Interactive agent** | Multi-turn refinement (“narrow to X”, “compare A vs B cohorts”), tool calls that only expose aggregates unless elevated. |
| **LLM-assisted labeling** | Offline or gated use to suggest new facet nodes or synonyms; human-approved before affecting the public tree. |
| **Visualization tie-in** | Search `group_id` selects regions of cluster views or filters the mosaic without listing cases. |

---

## 6. Relation to existing codebase

- **Storage**: `cases` and related tables in the storage layer already expose filterable dimensions (JSON arrays for topics, platforms, severity, etc.).
- **Raw vs features vs narrative** (see `case_storage_utils.py`):
  - **`cases.raw_data`**: Canonical **ingestion blob** (includes `case_text`, `source_file`, batch metadata). This is the **raw material** from the pipeline.
  - **`cases.extracted_features`**: JSON of **structured fields only** — `comparison_values`, demographics objects, `evidence_volume`, `date_range`, etc. It **excludes** `case_text`, `raw_data`, and fields duplicated in other `cases` columns (`source`, `case_topics`, …) so narrative is not stored twice in the blob.
  - **Reads**: `get_case()` loads `raw_data` and **hydrates** `case_text` from `raw_data.case_text` when needed. `get_all_cases(include_raw_data=False)` **omits** `raw_data` and **`case_text`** from each case dict (slim API); use `include_raw_data=True` when server-side code needs the narrative (e.g. full automated analysis).
- **Clusters**: `precomputed_clusters` / `cluster_groups_slim` suggest existing **group-level** artifacts search can align with.
- **UI**: A new **Search** tab in the visualization shell will call new endpoints and render cohort summaries + next steps along the tree/graph.

---

## 7. Open decisions (to resolve during implementation)

1. Exact **group_id** strategy: cluster-based vs facet-hash vs explicit cohort tables.
2. **Minimum cell size** for reporting counts (k-anonymity-style thresholds).
3. **Boolean and negation** grammar for combined phrases in the search bar.
4. Whether **case-level** detail remains entirely outside search or is gated behind a separate affordance.

This document is the working contract for direction on the `search` branch; update it as the tree and API solidify.
