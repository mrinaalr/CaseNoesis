# Triage: rule layer, supervised model, retrospective evaluation, live paste, and future work

This document describes the **Triage** tab and the triage stack end-to-end: **transparent rule-based priority scoring**, optional **Random Forest** or **decision tree** classifiers trained on labels derived from those rules, **retrospective** evaluation over the live database, **live** inference on pasted text with **no persistence**, and directions for extension. Implementation lives in `src/Clustering & Analysis Layer/analysis.py` (rules), `src/Clustering & Analysis Layer/triage.py` (bundle load, live path, optional corpus export), `scripts/train_triage_model.py` (training), `run/main.py` (HTTP API), and `visualization/triage.html` (UI).

---

## 1. Goals and constraints

### Primary goals

- **Auditable priority**: Analysts and researchers can see **why** a case ranks highly—via explicit **rule-based** weights on severity, victim count, case type, severity phrases, evidence volume, and registered-offender signals (`triage_cases` in `analysis.py`).
- **Comparable ML assist**: A **supervised** model (random forest or decision tree) learns to approximate **tier labels** derived from binned rule scores, so outputs remain **accountable to** the rule layer—not a parallel black-box policy.
- **Retrospective analysis**: Run **hold-out metrics**, **confusion-style summaries**, and **corpus-wide model tiers** on the **current** case store (PostgreSQL or SQLite), with optional **facet constraints** aligned with the rest of the app.
- **Live exploration**: Paste **unseen** narrative batches through the **same extraction pipeline** as retrospective cases, score tiers in memory, and **never write** narratives or features to the database.

### Non-goals (current design)

- **Triage is not** a real-time operational dispatch system for live investigations; it is an **analytic and research** surface on **public or ingested** summaries.
- **Model tiers** do not replace stored rule scores for policy; they **supplement** visualization and evaluation.

---

## 2. Conceptual model: rules → labels → classifier

### Rule-based priority (ground truth for training)

- Each case receives a **numeric priority score** from **weighted factors** (documented in code and technical reports): severity indicators, victim count, case type, severity phrases, evidence volume, registered sex offender status.
- Scores are **normalized** to a comparable scale for ranking and display.
- This layer is **deterministic** given extracted features: suitable for **audit**, **replication**, and **training labels**.

### Supervised tiers (Random Forest or decision tree)

- Rule scores are **binned** into a small number of **tier classes** (`make_labels` in `scripts/train_triage_model.py`).
- The classifier is trained on a **tabular feature matrix** built from the same **extraction pipeline** as the rest of CaseLinker (topics, counts, flags, agency features when enabled—not raw narrative text in the default sklearn path).
- **`--model rf`** (default) or **`--model tree`** selects **RandomForestClassifier** vs **DecisionTreeClassifier**; the trained object plus metadata are saved as a **`joblib` bundle** (`TriageModelBundle`).
- **Interpretability**: The tree model is explicitly small; the forest remains **inspectable relative to** neural baselines, and tier names stay tied to **rule bins**.

### Relationship between rule and model outputs

- **Rule tier** (from binned scores) and **model-predicted tier** can be **compared** in the UI and APIs, with Accuracy, Recall, F1 and a corresponding confusion matrix.
- All **model** inference is **downstream** of the same **feature extraction** assumptions as batch ingestion; live paste uses the **same** pattern/merge path as far as `triage.py` implements for single narratives.

---

## 3. Triage UX (copy and composition)

### Retrospective triage (accordion / sections)

- **Rule-based tiers**: Case IDs grouped by **rule-derived** priority bands for the loaded corpus view.
- **Model evaluation**: Stratified train/test **accuracy**, **classification report**, **confusion matrix**, and **per-tier case lists**—driven by **`GET /api/triage-eval`** (same statistical setup as `scripts/test_triage.py` on the **live** database).
- **Model tier tree / corpus view**: **`GET /api/triage-model-corpus`** runs the **saved bundle** on **every row** in the store (optionally **facet-filtered** via JSON query param). Inference is **on demand**; the server does **not** rely on a static `triage_corpus_predictions.json` snapshot for the web UI (that file may exist for offline backup or external validation only).

### Live triage

- User pastes text using the same **`Case N :`** delimiter convention as external PDF batching: each block is processed as a synthetic case, scored, and returned—**nothing** is persisted.
- **`POST /api/triage-live`** accepts JSON `{ "raw": "..." }` and returns tier assignments and metadata; errors if the bundle is missing or invalid.

---

## 4. Mechanism and API shape

### Finding model (three conventions)

1. **Default**: `models/triage_bundle.joblib` at the repository root (see `.gitignore` whitelist).
2. **`CASELINKER_MODELS_DIR`**: directory containing **`triage_bundle.joblib`** (e.g. mounted volume on Railway).
3. **`CASELINKER_TRIAGE_BUNDLE`**: explicit **file path** to any `*.joblib` bundle.

Precedence is implemented in `triage.py` (`default_bundle_path`); set **one** override unless you know the interaction. In addition, different / improved models can utilized.

### Training (offline)

```bash
python3 scripts/train_triage_model.py --model rf --out models/triage_bundle.joblib
python3 scripts/train_triage_model.py --model tree --out models/triage_bundle.joblib
```

Common flags include **`--no-agencies`**, **`--seed`**, and **`--explain`**; see `scripts/train_triage_model.py --help`. Training reads cases from the configured database (same `DATABASE_URL` / SQLite config as the main app).

### HTTP endpoints (FastAPI)

| Endpoint | Role |
|----------|------|
| **`GET /triage`** | Serves `visualization/triage.html`. |
| **`GET /api/triage-eval`** | Stratified eval vs rule labels; merges optional corpus summary when bundle loads. |
| **`GET /api/triage-model-corpus`** | Bundle inference over **all** stored cases; optional **`facet_constraints`** query JSON; rate limited. |
| **`POST /api/triage-live`** | Paste batch → in-memory pipeline → tier predictions; **no DB write**. |

### Offline corpus export (optional)

- `triage.py` CLI supports **`--write-corpus`** to emit JSON predictions for every DB case (useful for backups or external notebooks). The **interactive** triage page uses **live** inference instead.

---

## 5. Future expansion

| Direction | Role |
|-----------|------|
| **Richer features for ML** | Carefully vetted additional columns (e.g. embedding summaries) with explicit ablation and documentation, no silent replacement of rule tiers. |
| **Calibration and fairness reporting** | Per-source or per-era confusion tables; tie to stratified sampling in research papers. |
| **Explainability** | Feature importance for RF; printed rules for shallow trees; mismatch case review workflows. |
| **Policy considerations** | If a deployment ever needs **human approval** before acting on tiers, keep model output **advisory** and rule tier **primary** unless governance changes. |
| **Integration with Search** | Facet constraints on **`/api/triage-model-corpus`** already align with cohort exploration; deeper links (e.g. “open cohort in Search”) are UI work. |

---

## 6. Relation to existing codebase

- **Rules**: `triage_cases()` and related helpers in `src/Clustering & Analysis Layer/analysis.py`.
- **Training / bundle**: `scripts/train_triage_model.py` (`train_pipeline`, `cases_to_dataframe`, `make_labels`, `normalize_triage_bundle_after_load` for sklearn version drift).
- **Live path**: `run_live_triage`, `parse_live_case_input` in `src/Clustering & Analysis Layer/triage.py` (aligns delimiter semantics with `visualization/triage.html` and external PDF batching in `batching.py`).
- **API**: `run/main.py` (`_triage_saved_bundle_corpus_live` for live-DB corpus predictions).
- **Docs**: `visualization/ml-experimental.html` summarizes ML and triage scope; **`triage.md`** is the **technical working contract** for behavior and APIs.

### Raw data and features (same as Search doc)

- **`cases.raw_data`**: ingestion blob including `case_text`.
- **`cases.extracted_features`**: slim structured JSON; triage features are derived from **stored case rows** + merged `extracted_features` when building the training matrix.
- **Live triage** never calls `store_case`; it only builds in-memory dicts for the pipeline.

---

## 7. Open decisions (to resolve as usage grows)

1. **Minimum corpus size** for stable eval (`/api/triage-eval` enforces a floor; document for papers).
2. **Whether** to standardize on **one** bundle per deployment or support **A/B** bundles via env (currently single path).
3. **Agency features on/off** parity between training and production (`--no-agencies` vs default).

Full code implementation in `scripts/train_triage_model.py` and `run/main.py`; update it / documentation when bundle formats, env vars, or endpoint contracts change.
