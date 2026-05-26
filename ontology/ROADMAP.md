# CaseLinker → CAC Ontology Pipeline: Roadmap

**Version:** 1.0  
**Started:** May 26, 2026  
**Cory Working Session:** June 8, 2026  
**Spec:** [MAPPING_PLAN.md](MAPPING_PLAN.md)

---

## What We Are Building

CaseLinker holds ~5,092 ICAC cases in local DB. Each case is a flat dictionary of
structured fields (victim age, platforms used, relationship to victim, prosecution
outcome) plus NLP-derived features from the semantic pipeline. This pipeline transforms
each case dict into a typed CAC Ontology knowledge graph — a set of named RDF nodes and
edges (using the ProjectVIC CAC Ontology v3.0.0 class vocabulary) serialized as JSON-LD
and Turtle. The resulting per-case graphs merge into a unified corpus graph that is
SPARQL-queryable, enabling three research questions: (1) which platform types appear in
which exploitation patterns; (2) how do exploitation lifecycles (grooming phases,
escalation, physical contact) distribute across the corpus; and (3) at which lifecycle
points are law enforcement interventions most effective — the kill chain analysis.

---

## Pipeline Architecture

```
PostgreSQL
  └─► CaseStorage.get_case(case_id)
         │  flat dict with merged extracted_features
         ▼
  features_to_cac.py
         │
         ├── [DETERMINISTIC] Mapping tables (PLATFORM_MAP, TOPIC_MAP, etc.)
         │        → typed RDF nodes + edges
         │        → written to named graph: .../graphs/deterministic
         │
         ├── [NLP] Semantic concept scores from ml_features.semantic_severity
         │        → typed RDF nodes with cac-core:hasConfidence annotations
         │        → written to named graph: .../graphs/nlp
         │        (threshold: grooming ≥ 0.45, sextortion ≥ 0.45, possession_csam ≥ 0.50)
         │
         ├── [SINGLETONS] Shared platform + agency IRIs
         │        → looked up in singleton registry; created once, reused across cases
         │
         ▼
  rdflib ConjunctiveGraph
         │
         ├── serialize → ontology/output/{case_id}.jsonld
         ├── serialize → ontology/output/{case_id}.ttl
         │
         ▼
  pyshacl validate()
         │
         ├── shapes: ../CAC-Ontology/ontology/cacontology-core-shapes.ttl
         ├── conforms? → True / False
         └── report → printed to console + logged in graph_output/

  [FUTURE - not in scope today]
         ▼
  Bulk merge → corpus.ttl
         ▼
  SPARQL endpoint (Oxigraph or Fuseki)
         ▼
  Patterns page live queries
```

---

## Mapping Decisions Made

All decisions below supersede any open questions in MAPPING_PLAN.md §7.

| Topic | Decision |
|---|---|
| `"online"` platform | **SKIP** — no node created |
| `"chat"` platform | `AnonymousChatPlatform` with `platformSpecificity=generic` |
| `"social media"` platform | `SocialMediaPlatform` with `platformSpecificity=generic` |
| Craigslist | `SocialMediaPlatform` with `platformType=classifieds` |
| TikTok | `SocialMediaPlatform` (primary type) |
| Webcam platform | `VideoStreamingPlatform` |
| `csam` + `possession` co-occur | Merge into ONE `CSAMIncident` node |
| `online_only` without grooming | `ChildSexualAbuseEvent` (not `GroomingSolicitation`) |
| `online_only` + grooming present | `GroomingSolicitation` |
| `international` + `multi_state` | Single `MultiJurisdictionalInvestigation` with `crossesBorders=true` |
| Person nodes | Create both `uco-identity:Person` and `VictimRole`/`OffenderRole` |
| Victim PII | Anonymized: age range and region only; no names |
| `victim_count > 1`, one demographics block | N generic `VictimRole` nodes sharing demographics |
| Null `perpetrator_age` | Still create `OffenderRole`; omit age property |
| IRI base | `https://caselinker.up.railway.app/resource/` |
| Re-processing | Stable IRIs; overwrite on re-process; no versioning |
| NLP graph separation | NLP-derived nodes in `…/graphs/nlp`; deterministic in `…/graphs/deterministic` |
| NLP grooming threshold | ≥ 0.45 |
| NLP sextortion threshold | ≥ 0.45 |
| NLP `possession_csam` threshold | ≥ 0.50 (unchanged from merge layer) |
| SHACL reporting | Report `mapped` count and `valid` count separately |
| `Location` class | Use `uco-location:Location` where available in rdflib UCO namespace |
| P2P clients (LimeWire, BitTorrent, etc.) | `FileHostingService` with `platformType=p2p` |
| `severityLevel` scope | Event-level property (not case-level) |
| Multi-defendant | One `CACInvestigation` + multiple `OffenderRole` nodes |

---

## IRI Strategy

**Base IRI:** `https://caselinker.up.railway.app/resource/`

| Node Type | Pattern | Example |
|---|---|---|
| Investigation | `/resource/case/{case_id}` | `.../case/azicac_2011_006` |
| Event (case-specific) | `/resource/case/{case_id}/event/{type}` | `.../case/azicac_2011_006/event/production` |
| Person (victim) | `/resource/case/{case_id}/person/victim/{n}` | `.../case/azicac_2011_006/person/victim/1` |
| Person (offender) | `/resource/case/{case_id}/person/offender/{n}` | `.../case/azicac_2011_006/person/offender/1` |
| Role (victim) | `/resource/case/{case_id}/role/victim/{n}` | `.../case/azicac_2011_006/role/victim/1` |
| Role (offender) | `/resource/case/{case_id}/role/offender/{n}` | `.../case/azicac_2011_006/role/offender/1` |
| Relationship | `/resource/case/{case_id}/relationship/{type}` | `.../case/azicac_2011_006/relationship/familial` |
| Trust violation | `/resource/case/{case_id}/event/trust_violation` | — |
| Charge | `/resource/case/{case_id}/charge/{n}` | `.../case/azicac_2011_006/charge/1` |
| Sentence | `/resource/case/{case_id}/sentence/{n}` | `.../case/azicac_2011_006/sentence/1` |
| Legal phase | `/resource/case/{case_id}/phase/{name}` | `.../case/azicac_2011_006/phase/sentencing` |
| Operation | `/resource/case/{case_id}/operation` | — |
| **Platform (shared)** | `/resource/platform/{slug}` | `.../platform/snapchat` |
| **Agency (shared)** | `/resource/agency/{slug}` | `.../agency/fbi` |
| Deterministic named graph | `/resource/graphs/deterministic` | — |
| NLP named graph | `/resource/graphs/nlp` | — |

Slug generation: lowercase, spaces and special chars → hyphens, strip leading/trailing
hyphens. Example: `"U.S. Marshals Service"` → `us-marshals-service`.

Shared singletons (platforms, agencies) are created once and reused across cases in the
same graph build session. In a bulk export, a separate `singletons.ttl` file holds all
shared nodes and is merged into the corpus graph.

---

## What Gets Mapped (Deterministic)

| Mapping Table | Values | Status |
|---|---|---|
| `PLATFORM_MAP` | 32 specific + 2 generic (`chat`, `social media`) + 1 skip (`online`) = 35 total | ✓ Fully mapped |
| `TOPIC_MAP` | 9 deterministic + 1 merge-layer (`grooming`) = 10 | ✓ Fully mapped |
| `INVESTIGATION_TYPE_MAP` | 5 values (`undercover`, `proactive`, `reactive`, `online`, `unknown`) | ✓ Fully mapped |
| `PROSECUTION_MAP` | 5 status values + ~8 charge type patterns + 6 sentence types | ✓ Fully mapped |
| `SEVERITY_MAP` | 6 indicators → severityLevel integer + decomposed nodes | ✓ Fully mapped |
| `ROLE_MAP` | 15 relationship values → custodial/grooming role classes | ✓ Fully mapped |
| `AGENCY_MAP` | Tiered: federal (9) → ICAC pattern → state pattern → local fallback | ✓ Strategy implemented |
| `TECHNOLOGY_SIGNAL_MAP` | investigation_technology (4) + anonymization (4) + p2p (4) = 12 | ✓ Fully mapped |

---

## What Gets Mapped (NLP with Confidence)

Nodes produced by NLP features go into the `…/graphs/nlp` named graph with
`cac-core:hasConfidence` (xsd:decimal) annotations.

| Concept Key | Threshold | CAC Node Type | Included in v1 |
|---|---|---|---|
| `grooming` | ≥ 0.45 | `cacontology-grooming:OnlineGrooming` | Yes |
| `sextortion` | ≥ 0.45 | `cacontology-sextortion:SextortionIncident` | Yes |
| `production_csam` | ≥ 0.50 | `cacontology-production:ProductionOffense` (confidence-annotated variant) | Yes |
| `possession_csam` | ≥ 0.50 | `cacontology:CSAMIncident` (reinforces deterministic node) | Yes |
| `dissemination` | ≥ 0.45 | `cacontology-legal-outcomes:CSAM_Distribution` charge node | Yes |
| `exploitive_positions` | ≥ 0.45 | `cacontology-custodial:PositionOfTrust` supplement | Yes |
| `registered_sex_offender` | ≥ 0.45 | RSO flag on `OffenderRole` | Yes |
| `evidence_seizure` | ≥ 0.45 | `cacontology-production:ProducedContent` node | Yes |
| `criminal_networks_trafficking` | deferred (needs ≥ 0.60) | — | **No** |
| `ai_and_internet_tools` | deferred | — | **No** |
| `paraphilia_fetish` | deferred (no CAC subclass) | — | **No** |

---

## What Does NOT Get Mapped

| Feature | Reason |
|---|---|
| `comparison_values.*` (all vectors) | Clustering artifacts; duplicates of already-mapped fields |
| `ml_features.semantic_severity.scores` (raw) | Model outputs; used only as `cac-core:hasConfidence` annotations |
| `ml_features.semantic_severity.concept_metadata` | Internal model metadata |
| `ml_features.ner_entities` | Intermediate NER output; not resolved |
| `severity_phrases` | Debug evidence for severity indicators; no distinct CAC node |
| `tags` | Editorial labels; no CAC target (written as `rdfs:comment`) |
| `notes` | Free-text; written as `rdfs:comment` |
| `era` (case_studies.json) | CaseLinker periodization; no CAC equivalent |
| `case_demographics.gender` | No CAC victim gender property (gap for Cory) |
| `locations` (raw NER) | No `Location` class in CAC core; use `uco-location:Location` if available |
| `raw_data` | Full source blob; not mapped |
| `created_at` / `updated_at` | DB timestamps; written as `dcterms:created`/`dcterms:modified` |

---

## Known Gaps for Cory (June 8)

1. **No `Location` class in CAC core** — `locations` NER field has no target. Currently
   using `uco-location:Location` from UCO. Confirm if this import is intended.
2. **No victim gender property** — `case_demographics.gender` has no CAC mapping target.
   Propose `cacontology:victimGender` as a datatype property on `VictimRole`.
3. **P2P network subclass missing** — P2P clients (LimeWire, BitTorrent, Kazaa,
   Gigatribe) use `FileHostingService` with `platformType=p2p`. A dedicated
   `PeerToPeerNetwork` subclass would be more accurate.
4. **`severityLevel` scoping** — The property lives on `ChildSexualAbuseEvent` (event
   level). CaseLinker severity indicators are aggregated case-level. The mapper applies
   the highest severity to the most severe event node. Confirm this is the intended use.
5. **No `era` / periodization concept** — CaseLinker's Era I/II/III taxonomy has no CAC
   equivalent. Would Cory like a `CACInvestigationEra` annotation property?
6. **`paraphilia_fetish` concept** — Detected by the semantic pipeline; no CAC subclass.
   A `ParaphiliaContext` situation class would enable mapping this signal.
7. **Adult webcam / classifieds platform types** — `Webcam platform` maps to
   `VideoStreamingPlatform` and `Craigslist` maps to `SocialMediaPlatform`. Neither is
   precise. Propose `AdultContentPlatform` and `ClassifiedsService` subclasses.
8. **`Relative` class granularity** — `cacontology-custodial:Relative` covers uncle,
   aunt, cousin. More specific subclasses (Uncle, Aunt, Cousin) would improve query
   precision.

---

## Timeline

| Day | Work |
|---|---|
| **Day 1 (May 26)** | ROADMAP.md + `features_to_cac.py` v1 + test on `azicac_2011_006` ✓ |
| **Day 2** | Iterate on SHACL validation failures; scale to 10 cases; fix edge cases |
| **Days 3–4** | Scale to 50–100 cases; build `bulk_export.py`; build `/api/ontology/{case_id}` endpoint |
| **Days 5–7** | Full corpus export (~5,092 cases); SHACL report (mapped vs. valid counts); Patterns page live numbers from SPARQL |
| **Week 2** | Polish for Rita/GEN review; performance profiling; singleton deduplication across bulk export |
| **Week 3 (June 8)** | Cory working session — gaps review, CAC class proposals, ontology version bump |

---

## Technical Notes

- **SDK status:** `case-uco` and `case-uco-cac` are not published on PyPI as of May 2026.
  The mapper uses `rdflib` 7.6.0 with manual CAC namespace bindings as the fallback.
  When the SDK becomes available, swap in `CASEGraph` and `graph.create()` calls with
  minimal changes to the mapping logic.
- **SHACL validation:** Uses `pyshacl` 0.31.0 against
  `cacontology-core-shapes.ttl`. The shapes file declares `owl:imports` for remote UCO
  ontologies; the validator runs with `inference="none"` to avoid import-resolution
  failures in offline environments.
- **Requirements additions:** `rdflib>=7.0.0` and `pyshacl>=0.28.0` added to
  `requirements.txt`.
