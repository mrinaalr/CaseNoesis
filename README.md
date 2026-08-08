# CaseNoesis

**CaseNoesis** aggregates, structures, and decomposes case data across offense types, modeling exploitation as state machines and Markov decision processes to understand how platform affordances are misused, how crime types evolve alongside technology, and where intervention is possible.

## Origin & Framework

The theoretical foundation for this project is **["Affordances for Harm: How Offenders Misuse Platform Capabilities to Exploit Children, and Where to Intervene"](https://doi.org/10.5281/zenodo.21347781)**

AfH develops a formal affordance–misuse–harm framework (φ/η/ψ mapping) and validates it against a corpus of ICAC enforcement cases. CaseNoesis is the empirical test of whether that framework generalizes across offense types beyond the one it was originally derived from.

## Scope

- Multi-offense-category ingestion and processing pipeline (fraud, cyber-enabled crime, trafficking, and others to be defined as the project develops)
- Interfaced via MCP, command-line tools, and public dashboard
- Local database and external API integrations
- Runnable via localhost for collaborators and cloners

## Status

Early stage. Ingestion architecture and offense-category taxonomy are under active development. No public data release yet.

## Architecture

The pipeline turns public enforcement records into structured features, knowledge graphs, and state machines. Full design: [`Architecture design.md`](Architecture%20design.md).

```mermaid
flowchart TD
    P["PRESS / AGENCY <br/> scale · discovery"]
    C["PACER / RECAP <br/> lifecycle fidelity"]

    P --> ACQ["COLLECTION <br/> harvest → PDF → resolve"]
    C --> ENR["COURT ENRICHMENT <br/> docket correlate · evidence extraction"]

    ACQ --> PROC["PROCESSING <br/> case schema · <br/> deterministic extraction"]
    ENR --> PROC

    PROC --> ENC["SEMANTIC ENCODING <br/> CASE/UCO + Extensions · trajectories <br/> SHACL gate · observed ≠ inferred"]
    ENC --> STORE["STORAGE <br/> JSON-LD/TTL · PostgreSQL"]

    STORE --> ESM["FORMAL MODELING <br/> M = (S, A, T, R_G, s₀, F) <br/> φ / η / ψ · L* <br/> intervention points"]
    ESM --> AN["ANALYSIS <br/> Laws 1–4 · backbone · affordance structure"]
    AN --> VIZ["VIEWS <br/> machines · trajectories · case explorers"]

    STORE -.-> API["FastAPI · MCP"]
    VIZ -.-> API
```

**Two source jobs.** Press and agency releases give **scale**. PACER charging docs give **lifecycle fidelity** for grounding machines. Collection and enrichment are separate paths that meet at processing — see [Collection](#collection) and [Court records & enrichment](#court-records--enrichment).

**Cross domain analysis.** Processing extracts comparable features under a domain-agnostic offense record (domain profiles specialize; they do not redefine the core). Graphs are CASE/UCO + Extensions with the trajectories metamodel; SHACL is a publish gate, and inferred analytics are never typed as observed facts.

**What the system is for.** The primary purpose is to build formal models, specifically the *Exploitation State Machine*. Analysis tests Theorem 1 and Laws 1–4 across domains, annotates affordances, and *ranks intervention points*. Visualization and API/MCP expose machines, data, and analysis views.

## Collection

CaseNoesis is primarily built from public press releases — agency newsrooms, state attorney general offices, DOJ and its U.S. Attorney districts. Nothing behind a login, nothing paywalled. Every record traces back to a URL anyone can open.

### The pipeline, in one picture

```mermaid
flowchart TD
    SRC["sources/urls.txt <br/> ~56 sources · agency · state AG · DOJ"]

    SRC --> L["LISTING CRAWL <br/> paginate listing/search → article URLs"]
    SRC --> D["DOJ API <br/> press_releases.json → resolved records"]
    SRC --> M["MANUAL SEED <br/> one-off article URLs"]

    L --> F["FETCH <br/> delay · retry · Jina fallback"]
    D --> F
    M --> F

    F --> R["RENDER <br/> ReportLab page: title · date · source URL · body"]
    R --> B["BUNDLE <br/> one PDF per source <br/> e.g. SVICAC_All.pdf"]
    B --> E["EXTRACT <br/> text · entities · dates"]
    E --> V["RESOLVE <br/> link releases + merge features <br/> case_resolve.py"]
```

Scrape tools live under [`scripts/scraper/`](scripts/scraper/). Extract + resolve live under [`src/Processing Layer/`](src/Processing%20Layer/) (`batching.py`, [`case_resolve.py`](src/Processing%20Layer/case_resolve.py)). Analysis and CASE/UCO graphs are a separate layer downstream — not collection.

### How a press release becomes a case

1. **Discover.** Each source is a listing page the crawler paginates, a DOJ API lookup for `justice.gov` URLs, or a hand-supplied URL. Output is always the same: article URLs (or already-resolved DOJ records).
2. **Fetch.** Pages are pulled with spaced requests; failures retry and can fall back to Jina Reader when a host blocks direct HTML.
3. **Render.** Content is laid out into a structured PDF page (title, publication date, canonical source URL, body).
4. **Bundle.** Pages merge into one PDF per source, so a source is one reviewable artifact.
5. **Extract.** Ingestion splits the bundle on `Source:` lines and pulls text, entities, and dates. One URL → one document row.
6. **Resolve.** Related case releases (indictment / plea / sentencing) collapse to one canonical case. Features are **combined** across those releases (OR/union for platforms, agencies, statutes, topics; AND-check for docket / defendant / district; later lifecycle wins for plea/sentence). Every source URL is kept. Match order: docket → district + defendants → soft review. Whiteprint: [`case_resolve.py`](src/Processing%20Layer/case_resolve.py).

### Source types

| Type | What it covers | Notes |
|------|----------------|-------|
| DOJ API | Federal / USAO `justice.gov` releases | Structured JSON; used because live pages are bot-walled |
| Federal agency | USMS, USSS, HSI, and similar newsrooms | Templated sites; host extractors + Jina when needed |
| State AG | State-level prosecutions | Highest HTML variation |
| Task force / local | ICAC and specialized task forces, local PDs | Thin alone, wide in aggregate |

### What counts as a case

A case often generates several releases over its life — indictment, plea, sentencing — and a coordinated operation may be announced by DOJ, a U.S. Attorney’s office, and a state AG on the same day.

Collection keeps documents and cases distinct. Counts are not interchangeable:

| Level | Meaning |
|-------|---------|
| Documents | Press releases retrieved (one `Source:` URL each) |
| Cases | Canonical prosecutions after resolve (one or more documents) |
| Defendants | Individuals named across those cases |

### Current state

| | |
|--|--|
| Sources bundled | 56 |
| Bundled pages | 4,860 |
| Largest bundle | `SCAG_ICAC_All.pdf` — 633 pages |
| Coverage | ICAC corpus (CaseLinker lineage, same scraper). Elder fraud, trafficking, and extortion: pipeline-ready, not collected yet. |

The collection layer is crime-type agnostic. Extending to a new domain means a new source list and search terms — not a new pipeline.

## Court records & enrichment

Press releases are the discovery surface. Federal **PACER** filings (and free **CourtListener / RECAP** copies when available) are the supplementing sources including: indictments, superseding indictments, statements of offense, plea agreements, sentencing memoranda, docket sheets.

Court records **enrich** a press-release case already resolved in collection:

1. **Locate** — from a selected case, find the federal docket (district + case number when the release prints it; otherwise defendant + venue heuristics).
2. **Retrieve** — pull the filing PDFs (RECAP first; PACER purchase only when needed and authorized).
3. **Extract** — pull structured facts from each filing type (charges and counts from the indictment; factual narrative from the statement of offense; disposition and sentence from plea / judgment).
4. **Correlate** — attach filings to the same `prosecution_id` as the press releases (docket is the hard key; link press release and court records).
5. **Enrich** — merge court-extracted facts into the canonical case the same way *resolve* merges press releases (OR/union for charges, platforms, co-defendants; court filing wins on statute text and formal disposition when both exist). Court record provenance over press-release extracted features.

Early scaffolding for PACER eligibility and RECAP fetch lives under [`data/PACER/`](data/PACER/). Document-type extraction and the enrich path are being rebuilt with the rest of processing — not production-ready yet.

### State open records

Where a federal docket is thin or the matter is state-charged, **public records requests** can supply the same kind of enriching metadata — charging instruments, dispositions, affidavits — if the request is approved and the records are releasable:

| Mechanism | Scope |
|-----------|--------|
| Federal FOIA | Federal agency records (not a substitute for PACER court filings) |
| Georgia Open Records Act | State and local agency records in Georgia |
| Florida Public Records Law (Ch. 119) | State and local agency records in Florida |

These are **opt-in enrichment channels**, not scrapers. Nothing is collected under them until the request is lawful, approved where required, and logged with provenance like every other document.

## Data & Ethics

Case data is drawn exclusively from publicly available enforcement records (press releases, court filings) and from open-records releases obtained through lawful request. 


## Contributing

Contributors can help by:
- Proposing offense categories and taxonomy structure
- Ingestion pipeline design for new offense categories
- Code implementation

---

*CaseNoesis builds on ideas developed in [CaseLinker](https://github.com/mrinaalr/CaseLinker), a CSEA-focused case analysis platform. The relationship is one of shared DNA, not shared codebase. CaseNoesis's ingestion and processing layers are being built independently for cross-domain use.*