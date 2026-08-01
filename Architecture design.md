# CaseNoesis Architecture

## Overview

CaseNoesis aggregates, structures, and decomposes case data across offense types, modeling exploitation as state machines and Markov decision processes to understand how platform affordances are misused, how crime types evolve alongside technology, and where intervention is possible.

The central scientific move is falsification. *Affordances for Harm* (AfH) developed the Exploitation State Machine (ESM) — backbone invariants and Laws 1–4 — against a corpus of 7,426 public ICAC enforcement records (2002–2026, 30+ platforms, 61 task forces). CaseNoesis exists to test whether those invariants are ICAC-specific artifacts or properties of technology-mediated exploitation generally. The architecture is an instrument built to break its own framework.

Domains under test:

- **ICAC** — home domain (framework origin)
- **Elder fraud** — far test
- **Trafficking** — near test
- **Organized crime / racketeering** — offender-structure axis, not a separate crime type

CaseNoesis identifies points for intervention under counterfactual transition removal. It does not produce deployed interventions.


## System Architecture

### High-Level Components

```
┌─────────────────────────────────────┐
│      Data Sources                   │
│  press/agency records (scale)       │
│  PACER / federal charging docs      │
│    (lifecycle sources)              │
└────────┬────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────┐
│      Corpus Acquisition             │
│  - retrieval & document-type routing│
│  - text extraction                  │
│  - case-boundary detection          │
│  - normalize → structured records   │
└────────┬────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────┐
│      Ingestion & Processing         │
│  - validation & cleaning            │
│  - feature extraction               │
│  - domain-agnostic schema           │
└────────┬────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────┐
│      Semantic Encoding              │
│  - CASE/UCO + CAC graph objects     │
│  - trajectories metamodel           │
│  - SHACL conformance gate           │
└────────┬────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────┐
│      Storage                        │
│  - case database (record model)     │
│  - graph artifacts (JSON-LD / TTL)  │
│  - cache for read paths             │
└────────┬────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────┐
│      Formal Modeling                │
│  - ESM / MDP: M=(S,A,T,R_G,s_0,F)   │
│  - φ / η / ψ affordance annotation  │
│  - L* and intervention counterfact. │
└────────┬────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────┐
│      Analysis                       │
│  - cross-domain invariant testing   │
│  - phase-transition structure       │
│  - affordance co-occurrence         │
│  - intervention-point identification│
└────────┬────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────┐
│      Visualization                  │
│  - per-case state machines          │
│  - phase-annotated trajectories     │
│  - cross-domain typology views      │
└─────────────────────────────────────┘
```

Press/agency records and PACER answer different questions. Press and agency outputs supply corpus scale. PACER charging documents (indictments, statements of offense, plea agreements, related federal filings) are the basis for state-machine grounding — higher lifecycle fidelity, not the primary volume source.


## Core Components

### 1. Corpus Acquisition

**Purpose**: Turn heterogeneous public enforcement sources into discrete offense records with provenance.

**Source classes**:

- Agency / press releases and public enforcement summaries
- Federal court records via PACER / CourtListener (RECAP): indictments, superseding indictments, statements of offense, plea agreements, sentencing memoranda, dockets

**Pipeline**:

- **Retrieval** — URL harvest, agency APIs where required (e.g. DOJ), CourtListener/RECAP for federal dockets
- **Document-type routing** — classify filings and press artifacts so downstream extraction applies the right boundary and field rules
- **Text extraction** — PDF and HTML → plain text; preserve source URL / document identity
- **Case-boundary detection** — split multi-case agency dumps into single-record units; bind PACER document bundles to one docketed matter
- **Normalization** — map into the domain-agnostic offense record model below, with provenance retained on every claim

### 2. Ingestion & Processing

**Purpose**: Validate, clean, and extract comparable features from normalized source text, then specialize fields under a domain profile without baking domain semantics into the core schema.

**Components**:

- Text cleanup (URL fragments, formatting artifacts)
- Case batching where source files contain multiple matters
- Hybrid feature extraction (deterministic patterns + semantic concept scoring)
- NER for entity spans when present in the public text
- Domain-profile gates and taxonomies (e.g. age routing for ICAC; offense-role vocab for fraud or racketeering)
- Stable case IDs with source + temporal disambiguation
- Comparison vectors for corpus-level feature comparison (retained from the CaseLinker path; secondary to formal analysis)

**Offense Record Schema** (domain-agnostic core):

```yaml
OffenseRecord:
  - id: unique identifier
  - domain: offense domain label (e.g. icac, elder_fraud, trafficking, racketeering)
  - source: issuing organization / court / jurisdiction
  - provenance:
      url: public source URL or document locator
      document_type: press_release | indictment | statement_of_offense | plea | docket | other
      retrieved_at: timestamp
  - date_range: {start, end} or single date

  # Parties (anonymized / as publicly stated)
  - victim_context: {count, demographics, role_labels}
  - offender_context: {age, roles, relationship_to_victim, prior_record_flags}

  # Technology surface
  - platforms_used: [str]
  - affordance_mentions: [str]   # capability classes when attributable

  # Enforcement surface
  - investigation_types: [str]
  - agencies_involved: [str]
  - prosecution_outcome: {charges: [{count, charge, statute}], disposition: str}

  # Offense structure (pre-ontology)
  - offense_topics: [str]        # domain-profile vocabulary
  - evidence_volume: {images, videos, storage_size, messages}  # when stated

  # Raw retention
  - raw_data: original structured payload
  - case_text: full extracted text

  - tags: [str]
  - notes: summary
  - created_at, updated_at
```

**Domain profile example (ICAC)** — specializes the core; does not redefine it:

```yaml
DomainProfile:
  domain: icac
  offense_topics:
    - production, possession, distribution, enticement, sextortion,
      trafficking, enterprise, hands_on, online_only, family, stranger, csam
  severity_indicators:   # profile-local; not core schema
    - infant, very_young, under_10, rape, production
  party_rules:
    victim_age_gate: {min: 1, max: 17, actions: [KEEP, REJECT, REVIEW]}
  phase_vocab:           # maps into CAC / traj:State
    - InitialContactPhase
    - ConditioningPhase
    - ExploitationPhase
    - MaintenancePhase
  goal_set: [enticement, sextortion, production, enterprise, trafficking]
```

ICAC-specific severity scoring and operational triage weights live in the profile, not in the core record model. See Analysis for how triage is treated.

### 3. Semantic Encoding (CASE/UCO)

**Purpose**: Express extracted case content as CASE/UCO-conformant graph objects so the state machine is interoperable with practitioner tooling rather than a bespoke research artifact.

Built on: [CASE/UCO SDK](https://github.com/vulnmaster/CASE-UCO-SDK) and the Crimes Against Children Ontology (CAC) for offense-phase vocabulary. **All version pins and resolving refs live only in the SHACL validation block below** — that block is authoritative; do not duplicate version numbers elsewhere in this document.

**Feature → ontology mapping** (conceptual):

| Extracted facet | Ontology target |
|---|---|
| Offense matter / investigation | CAC investigation / CASE investigative framing |
| Platforms & channel changes | platform nodes; `ChannelMigrationEvent` on transitions |
| Trust / conditioning / coercion mechanics | phase classes + mechanism properties |
| Affordance misuse on a transition | `AffordanceMisuse` (or trajectories-aligned annotation) attached to edges, not platform nodes alone |
| Account reset after ban | `AccountReplacementEvent` with resume-phase pointer |
| Self-sustaining leverage loop | `CoercionCycle` (distinct from linear progression) |
| Ordered phase path | `cac-core:precedes` and/or `traj:sequenceIndex` |

**Offense phases**:

- Spine macro-phases include `InitialContactPhase`, `ConditioningPhase`, `ExploitationPhase`, `MaintenancePhase`
- `ConditioningPhase` is the canonical preparatory macro-phase between contact and exploitation (introduced in CAC-Ontology PR #39; see pin block for merge status). `TrustBuildingPhase` is a deprecated alias re-parented under Conditioning; existing graphs remain readable via alias
- Terminal states are modeled as terminal phase instances (typically Exploitation or domain-specific terminal marks) with terminal polarity (`completed` | `disrupted`) — not a separate ad-hoc “done” flag outside the graph

**Trajectories extension**: domain-agnostic metamodel — `traj:State`, `traj:Transition`, `traj:Trajectory`, `traj:PhaseAssertion`, `traj:StateMachineModel`, `traj:TransitionEstimate`. Domain SKOS schemes plug state labels into the shared metamodel. Observed phase occupancy (`PhaseAssertion`) is shape-separated from inferred analytics (`StateMachineModel` / `TransitionEstimate`): observed ≠ inferred is enforced in SHACL, not left to convention. Extension version and resolving ref: SHACL validation block only.

**SHACL validation**: conformance is a pipeline gate. Graphs that do not pass the pinned shapes suite are not treated as publishable analytical inputs. An unversioned “conforms to CAC/CASE” claim is not part of this design.

**This block is the single source of truth for all pinned dependency refs in this document** (checked 2026-07-25 UTC).

| Surface | Status | Resolving ref | Notes |
|---|---|---|---|
| CAC Ontology release baseline | **Merged release tag** | [Project-VIC-International/CAC-Ontology](https://github.com/Project-VIC-International/CAC-Ontology) tag `v3.0.0` → `a923bebb28571b91e19c4c4acc788c7870b28e45` (`owl:versionInfo` / `owl:versionIRI` `…/3.0.0`) | Release-line pin. Does **not** include ConditioningPhase or post-tag state-machine shape deltas. |
| CAC ConditioningPhase + state-machine shapes | **Open PR** (as of 2026-07-25) | Upstream `refs/pull/39/head` → `b73b51bc3583b95cf6ef9a55dc798bb7b15dc2d5`; also `https://github.com/mrinaalr/CAC-Ontology` (PR head fork). **Not** on tag `v3.0.0`. `git merge-base --is-ancestor b73b51b… v3.0.0` is false; v3.0.0 **is** an ancestor of the PR tip. | CAC-Ontology **PR #39** @ `b73b51bc3583b95cf6ef9a55dc798bb7b15dc2d5` (open as of 2026-07-25; resolves via `refs/pull/39/head`; shape definitions may change on merge). Phase-graph conformance against these shapes is **locally verified pending upstream merge**. |
| CAC state-machine shape precursors | **Open PR** (as of 2026-07-25) | Upstream `refs/pull/33/head` → `4e397f0d9a5e48cef3c2ddab28d52e9adb7a025b`; fork `https://github.com/mrinaalr/CAC-Ontology`. PR #39 depends on #33. | CAC-Ontology **PR #33** @ `4e397f0d9a5e48cef3c2ddab28d52e9adb7a025b` (open as of 2026-07-25; resolves via `refs/pull/33/head`; shape definitions may change on merge). Platforms / sextortion / core shape bytes differ from `v3.0.0`. |
| CASE/UCO SDK release baseline | **Merged release tag** | [vulnmaster/CASE-UCO-SDK](https://github.com/vulnmaster/CASE-UCO-SDK) tag `v1.22.4` → `732733e434dc67e790f5a8f371b315d79237641d` (`python/pyproject.toml` `version = "1.22.4"`) | Real tagged release. **Does not contain** `extensions/trajectories/`. |
| trajectories extension (candidate metamodel) | **Open PR** (as of 2026-07-25) | Upstream `refs/pull/86/head` → `15d25c7dbeeef0abe48c4f93fb2656473dbcfdba`; fork `https://github.com/built-by-mars/CaseNoesis-Ontology`. Manifest version **0.1.0** at `extensions/trajectories/manifest.json`. | SDK **PR #86** @ `15d25c7dbeeef0abe48c4f93fb2656473dbcfdba` (open as of 2026-07-25; resolves via `refs/pull/86/head`; shape definitions may change on merge). **Not** in tag `v1.22.4`. |
| trajectories extension (ESM-expanded shapes) | **Open PR** (as of 2026-07-25) | Upstream `refs/pull/87/head` → `6754face0e1e5dc9d093de32384215768b4eb1ac`; fork `https://github.com/built-by-mars/CaseNoesis-Ontology` branch `feat/exploitation-state-machine`. Manifest version **0.3.1**. | SDK **PR #87** @ `6754face0e1e5dc9d093de32384215768b4eb1ac` (open as of 2026-07-25; resolves via `refs/pull/87/head`; shape definitions may change on merge). This is the source of the former “trajectories 0.3.1” string — **not** a release artifact and **not** PR #86. |
| CASE built ontology (`case_validate`) | **Tool enum / env** | `case_validate --built-version case-1.4.0` via `case-utils==0.17.0` (SDK `.venv` `pip freeze`, 2026-07-25) | CASE **1.4.0** here means the built-in CASE ontology bundle selected by `case_validate`, not an SDK tag. |
| pyshacl / rdflib (CAC pyshacl path) | **Pinned in requirements + resolved env** | CaseNoesis `requirements.txt`: `pyshacl==0.31.0`, `rdflib==7.6.0`; CaseNoesis `.venv` `pip freeze` matches those exact versions (2026-07-25). **No lockfile** in-repo. | Primary CAC gate in `features_to_cac.py` loads sibling `../CAC-Ontology/ontology/cacontology-core-shapes.ttl` through pyshacl. |

**Shapes files the gates load** (SHA-256 of file bytes; survives PR force-push). Hashes below are for the open-PR tips named above unless marked `v3.0.0`.

| File | SHA-256 | Bytes | Source tip |
|---|---|---:|---|
| `cacontology-core-shapes.ttl` | `5dc73fda06f8fccaa67af571cc2d6c41fb28ef22ed11621150cb7e552e6d638f` | 21187 | PR #39 `b73b51bc3583b95cf6ef9a55dc798bb7b15dc2d5` (also matches CaseNoesis vendored copy; **differs** from `v3.0.0`) |
| `cacontology-core-spine-shapes.ttl` | `231b6f4d3cb1bf8c2fc987d6652a2dfd9f45a63c944014e1b0fd78e4e98f19ff` | 9221 | PR #39 `b73b51bc3583b95cf6ef9a55dc798bb7b15dc2d5` |
| `cacontology-grooming-shapes.ttl` | `1a2b66632764b94334e9e0c855f44b1a7a8b749b33f0701756976a65672cec55` | 41663 | PR #39 `b73b51bc3583b95cf6ef9a55dc798bb7b15dc2d5` |
| `cacontology-platforms-shapes.ttl` | `401fbd924c094132b6effc675b5af49bc23a15cb87fa6d9d781266888fab9ed4` | 35458 | PR #33/`#39` tips (same bytes; **differs** from `v3.0.0`) |
| `cacontology-sextortion-shapes.ttl` | `573d190935c9a569ba8e0559736e1acdc45cd238910bdeb40228bcc822825330` | 30971 | PR #33/`#39` tips (same bytes; **differs** from `v3.0.0`) |
| `extensions/trajectories/trajectories-shapes.ttl` | `7eb09c1185e7181ccbf81bd0d3a34db7751a5d2f7f8c029d9cf5b1025eb47eeb` | 4705 | PR #86 `15d25c7dbeeef0abe48c4f93fb2656473dbcfdba` (manifest **0.1.0**) |
| `extensions/trajectories/trajectories-shapes.ttl` | `c454ae4480813ec0b8f4c1e184a756c04b97b8ebf10a9eb7b5d8f999ab4424c7` | 6156 | PR #87 `6754face0e1e5dc9d093de32384215768b4eb1ac` (manifest **0.3.1**; local CaseNoesis SDK worktree matches this tip) |

`features_to_cac.py`’s pyshacl gate currently loads **only** `cacontology-core-shapes.ttl` from the sibling CAC checkout. Broader phase-graph / trajectories checks use the additional rows above; until PRs #33 / #39 / #86 / #87 merge, treat those conformance results as **locally verified pending upstream merge**, not as release-line certification.

### 4. Storage

**Purpose**: Persist offense records and graph artifacts for fast retrieval and reproducible analysis.

**Components**:

- **Case database** (PostgreSQL / SQLite): database-agnostic selection by environment; normalized tables plus JSON for variable fields; indexes on source, date, domain/topics; raw text and extracted features retained
- **Graph artifacts**: JSON-LD / Turtle case and state-machine graphs under ontology and state-machine outputs
- **Cache** (Redis when configured): short-TTL / shared cache for expensive read paths

**Future**: Graph database for relationship traversal — not part of the current design surface (see Future Work).

### 5. Formal Modeling

**Purpose**: Instantiate each case (or typology) as an exploitation state machine and compute Bellman-optimal trajectories and intervention deltas under the AfH apparatus.

Machine:

$$
M = (S, A, T, R_G, s_0, F)
$$

**State space $S$**: finite offense-phase classes from the ontology spine and domain vocabularies. Backbone invariant $B$:

$$
B = \{\mathrm{InitialContactPhase},\ \mathrm{ConditioningPhase},\ \mathrm{ExploitationPhase},\ \mathrm{MaintenancePhase}\}
$$

Phase ordering constraints are expressed by `precedes` / sequence indices. Terminal set $F \subseteq S$ holds completed or disrupted terminal phase instances. $s_0 = \mathrm{InitialContactPhase}$ for enforcement-record trajectories that document contact-onset exploitation.

**Actions / transitions**: offender actions appear as transitions between phases. Affordance-enabled transitions carry misuse annotations. Channel migration events are first-class transition-adjacent objects when the record supports them.

**Transition function $T$**: corpus-estimated from observed consecutive phase pairs across grounded graphs. “Corpus-estimated” means empirical edge frequencies (and row-normalized conditionals) over the available lifecycle-resolved sample — typically PACER-anchored machines plus any other graphs with ordered phases. It does **not** mean a population transition law, a platform telemetry estimate, or a claim robust to selection effects. Small per-domain $n$ yields weak $T$; estimates are analytical instruments, never typed as observed facts (trajectories SHACL firewall).

**Reward / objective $R_G$**: goal-conditioned rewards $R_g(s)$ measure how much reaching state $s$ advances goal $g \in G$. $L^*_{g,A}$ is the Bellman-optimal path from $s_0$ toward $F$ through $M$ under affordance environment $A$:

$$
L^{*}_{g,A} = \arg\max_{L \in \mathrm{Seq}(A)} \mathbb{E}\big[U_g(L)\big]
$$

**Affordance annotation (φ / η / ψ)**:

- **φ** — trajectory → exploitation type
- **η** — exploitation type → victim-facing harms $H$
- **ψ** — affordance class → harms across trajectories in which it appears

Annotations attach to states and transitions (misuse on edges; type resolution on complete trajectories).

**Intervention counterfactuals**: remove or friction a transition or phase (e.g. delete a state from the reachable graph) and recompute $L^*$ / $V^*(s_0)$. The yield is a ranked set of high-delta intervention *points* — where friction would most reduce goal-conditioned value — not a deployed control, policy recommendation, or product change.

Falsifiable targets carried from AfH (restated for cross-domain test):

- **Theorem 1 (Closure of $H$)** — victim-facing harm set is finite and closed
- **Law 1 (Contact Primacy)** — no exploitation trajectory without an initial contact event
- **Law 2 (Backbone Invariance)** — $B$ present in every complete trajectory
- **Law 3 (Type Invariance)** — new affordance changes trajectory cost via φ, not exploitation type
- **Law 4 (Affordance Displacement)** — affordance removal shifts $L^*$ to the nearest bundle; $g$ unchanged

### 6. Analysis

**Purpose**: Primary outputs are scientific tests of the apparatus, not operational case triage.

**Primary outputs**:

- Cross-domain invariant testing (Theorem 1 / Laws 1–4)
- Phase-transition frequency and timing
- Affordance co-occurrence across trajectories and domains
- Intervention-point identification under counterfactual transition/phase removal

**Retained from CaseLinker** (secondary):

- Feature comparison / similarity over the offense record model
- Corpus-level trend detection (platforms, topics, investigation mix over time)
- Tag intersection filtering for exploratory UI

**Superseded as primary framing**:

- Clustering-for-display as the main analytical product
- CSEA severity dashboards as the default view of “importance”

**Deprecated for CaseNoesis primary outputs** (retained as optional domain-profile capability):

- Multi-factor severity / priority triage with ICAC-tuned weights (infant, very_young, production, etc.)

Reason: those weights are domain-semantic and do not transfer to elder fraud or racketeering; triage is operational prioritization, not falsification. The machinery may later serve as a per-domain or cross-domain extension. It is not deleted and not featured.

### 7. Visualization

**Purpose**: Render state machines and trajectories so phase structure, affordances, and cross-domain comparison are inspectable.

**Reference views**:

- Per-case instantiated machines (ordered phases, terminal polarity, disruption marks)
- Phase-annotated trajectories with affordance-on-arrival / misuse labels
- Cross-domain typology views — elder fraud, trafficking, racketeering, and ICAC offense types — as parallel renderings of the same metamodel, not separate dashboard products

Supporting corpus views (timeline, platform environment, agency mix) remain available for scale context; they are not the primary analytical surface.


## Data Handling

**What is stored**: public offense records (structured fields + raw extracted text), provenance URLs / document locators, derived features, and CASE/UCO graph artifacts. Optional cache entries for expensive read paths.

**What is retained**: original source text and raw payloads alongside normalized fields so extractions remain auditable against the public record. Graph exports retain evidence provenance links required by the observed≠inferred firewall.

**Sensitive content in public records**: sources are already public enforcement or court documents. The system does not enrich records with non-public investigative material. Party fields are stored as stated in the source (often already anonymized or initialed by the issuer). Downstream displays prefer structured summaries; full text is available for audit and grounding, not as a default broadcast surface.

**What leaves via API / MCP**: corpus statistics, case summaries, tag-filtered sets, typology/state-machine views, and graph exports subject to access controls on sensitive export tools. The API does not invent private facts; it serves transformations of the public corpus and derived (explicitly inferred) model artifacts.


## Interfaces & Runtime

- **FastAPI** — HTTP API over corpus, filters, typology/state-machine views, and graph-related routes
- **MCP** — agent-queryable tool surface over the same corpus (structured tools for stats, cases, graphs, traversal); differentiator for programmatic research and T&S evaluation workflows
- **Redis** — optional shared cache for expensive read paths


## Relationship to CaseLinker

CaseLinker is the case-aggregation and corpus-visualization system. CaseNoesis is the formal-modeling system that consumes structured offense records and encodes them as computational objects (CASE/UCO graphs, ESM/MDP instances, $L^*$ and intervention analysis).

What flows between them: public records → shared ingestion/processing DNA → offense records and (where produced) CAC/trajectory graphs → CaseNoesis formal layer and typology views. Shared DNA, not a claim of a single codebase or identical product question.


## Limitations

- **Prosecutorial artifacts**: charging documents reflect what was charged and stipulated, not a complete account of what occurred
- **Selection bias**: the corpus is biased toward detected, prosecuted, and publicly disclosed conduct; sealed and non-public matters are absent by design
- **Weak transition estimates**: per-domain lifecycle samples are small; corpus-estimated $T$ is fragile and must not be read as population dynamics
- **Shared vocabulary risk**: cross-domain comparison can force a common phase language onto genuinely different phenomena; negative results and failed mappings are analytically informative, not defects to hide
- **Platform attribution**: many press records omit named platforms; affordance analysis is constrained to cases with sufficient resolution
- **Intervention scope**: outputs are intervention *points* under model counterfactuals, not evaluated product or enforcement interventions


## Future Work

- Graph database for relationship mapping and traversal (called out in the prior CaseLinker architecture; still not part of the design surface above)
- Broader lifecycle-resolved samples per non-ICAC domain to strengthen $T$ without collapsing domains into ICAC defaults
- Deeper counterfactual friction models (partial edge cost, not only state deletion)
- Continued upstream ontology/SDK work where the metamodel lacks coverage — no local ontology forks
