# Test Output

This directory contains the output of `ontology/features_to_cac.py` run against
the `azicac_2011_006` test fixture (documented in `MAPPING_PLAN.md §6.1`).

## Files

| File | Description |
|---|---|
| `azicac_2011_006.jsonld` | JSON-LD serialization of the full CAC Ontology graph for this case (two named graphs: deterministic + NLP) |
| `azicac_2011_006.ttl` | Turtle serialization of the same graph, easier to read for ontology debugging |

## What the files contain

The graph for `azicac_2011_006` encodes:

- **30 nodes** (unique subjects) across the deterministic and NLP named graphs
- **130 triples** total
- Root node: `CACInvestigation` at `https://caselinker.up.railway.app/resource/case/azicac_2011_006`
- Two named graphs:
  - `…/graphs/deterministic` — typed nodes from rule-based mapping tables
  - `…/graphs/nlp` — nodes derived from semantic concept scores, annotated with `cac-core:hasConfidence`

Key node types created:

| Type | Count | Source |
|---|---|---|
| `Event` | 8 | production, hands_on, conspiracy, trust violation, proactive operation, NLP nodes |
| `OffenderRole` | 2 subjects (4 type triples: CAC + UCO) | `perpetrator_age: [32, 41]` |
| `ProductionOffense` | 2 | deterministic (topic: production) + NLP (production_csam score: 0.72) |
| `Person` | 3 | 1 victim + 2 offenders |
| `AssessmentResult` | 3 | NLP confidence annotations |
| `FamilialRelationship` + `CustodialAbuse` | 1 each | `relationship_to_victim: family` |
| `ConspiracyToCommitCSA` | 1 | `severity_indicators: multiple_perpetrators` |
| `FederalAgency` / `StateICACtaskForce` / `StateAgency` | 1 each | FBI, AZICAC, Maricopa County Attorney |
| `ProactiveOperation` | 1 | `investigation_type: proactive` |
| `PrisonSentence` / `CSAM_Production` charges | 1 / 2 | `prosecution_outcome` |

## SHACL Validation

**Conforms: ✓**  
Validated against `../CAC-Ontology/ontology/cacontology-core-shapes.ttl` using pyshacl.

## How to regenerate

```bash
cd /path/to/CaseLinker/ontology
python features_to_cac.py
```

Output is written to this directory (`graph_output/`).

To run against a live database case:
```bash
DATABASE_URL=postgresql://... python features_to_cac.py <case_id>
```
Output goes to `ontology/output/` in that case.
