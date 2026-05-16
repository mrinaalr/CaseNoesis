#!/usr/bin/env python3
"""
Train interpretable triage classifiers on CaseLinker structured features.

Labels come from the existing rule-based triage in analysis.triage_cases:
each case gets a normalized priority_score on [5, 10]. This script buckets
those scores into classes (default: 3 quantile bins → low / medium / high).

This is a **proof-of-concept**: the model learns to approximate the current
rules from extracted tags, not ground truth from investigators.

Usage:
  python3 scripts/run/train_triage_model.py --out models/triage_bundle.joblib
  python3 scripts/run/train_triage_model.py --no-agencies --out models/triage_no_agencies.joblib
  python3 scripts/run/train_triage_model.py --explain
  python3 scripts/run/train_triage_model.py --predict CASE_ID --bundle models/triage_bundle.joblib
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src" / "Storage Layer"))
sys.path.insert(0, str(REPO_ROOT / "src" / "Clustering & Analysis Layer"))

try:
    import joblib
    from scipy.sparse import csr_matrix, hstack
    from sklearn.base import BaseEstimator, TransformerMixin
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.impute import SimpleImputer
    from sklearn.metrics import accuracy_score, classification_report
    from sklearn.model_selection import train_test_split
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import MultiLabelBinarizer, OneHotEncoder
    from sklearn.tree import DecisionTreeClassifier
except ImportError as e:
    print("Missing dependency. Install with: pip install scikit-learn joblib", file=sys.stderr)
    raise SystemExit(1) from e

import pandas as pd  # noqa: E402

from analysis import triage_cases  # noqa: E402
from storage import CaseStorage  # noqa: E402


def get_case_storage(db_path: Optional[Path] = None) -> CaseStorage:
    """SQLite by default; PostgreSQL when DATABASE_URL is set (same as the FastAPI app)."""
    if os.getenv("DATABASE_URL"):
        try:
            from storage_postgres import CaseStorage as PgCaseStorage

            return PgCaseStorage()
        except ImportError as e:
            raise SystemExit(
                "DATABASE_URL is set but PostgreSQL storage is unavailable "
                "(install psycopg2-binary)."
            ) from e
    path = db_path or Path(os.environ.get("CASELINKER_DB", REPO_ROOT / "caselinker.db"))
    return CaseStorage(str(path.resolve()))

LIST_COLS_WITH_AGENCIES = (
    "case_topics",
    "severity_indicators",
    "platforms_used",
    "severity_phrases",
    "agencies_involved",
)
LIST_COLS_NO_AGENCIES = (
    "case_topics",
    "severity_indicators",
    "platforms_used",
    "severity_phrases",
)


def _as_list(val: Any) -> List[str]:
    if val is None:
        return []
    if isinstance(val, list):
        return [str(x) for x in val if x is not None and str(x).strip()]
    if isinstance(val, str):
        try:
            p = json.loads(val)
            if isinstance(p, list):
                return [str(x) for x in p if x is not None and str(x).strip()]
        except (json.JSONDecodeError, TypeError):
            pass
        s = val.strip()
        return [s] if s else []
    return []


def _evidence_images(case: Dict[str, Any]) -> float:
    ev = case.get("evidence_volume") or {}
    if isinstance(ev, str):
        try:
            ev = json.loads(ev)
        except (json.JSONDecodeError, TypeError):
            ev = {}
    if not isinstance(ev, dict):
        return 0.0
    n = ev.get("images")
    try:
        return float(n) if n is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def cases_to_dataframe(
    cases: List[Dict[str, Any]],
    top_agencies: int = 48,
    include_agencies: bool = True,
) -> pd.DataFrame:
    """Flatten cases to a DataFrame for sklearn."""
    keep_agencies: set = set()
    if include_agencies:
        agency_counts: Dict[str, int] = {}
        for c in cases:
            for a in _as_list(c.get("agencies_involved")):
                agency_counts[a] = agency_counts.get(a, 0) + 1
        keep_agencies = {a for a, _ in sorted(agency_counts.items(), key=lambda x: -x[1])[:top_agencies]}

    rows = []
    for c in cases:
        if include_agencies:
            agencies = [a for a in _as_list(c.get("agencies_involved")) if a in keep_agencies]
        else:
            agencies = []
        rows.append(
            {
                "id": c.get("id"),
                "case_topics": _as_list(c.get("case_topics")),
                "severity_indicators": _as_list(c.get("severity_indicators")),
                "platforms_used": _as_list(c.get("platforms_used")),
                "severity_phrases": _as_list(c.get("severity_phrases")),
                "agencies_involved": agencies,
                "investigation_type": (c.get("investigation_type") or "∅") or "∅",
                "relationship_to_victim": (c.get("relationship_to_victim") or "∅") or "∅",
                "victim_count": float(c.get("victim_count") or 0.0),
                "rso": 1.0 if c.get("perpetrator_registered_sex_offender") else 0.0,
                "log1p_images": np.log1p(_evidence_images(c)),
            }
        )
    return pd.DataFrame(rows)


def priority_scores_by_id(cases: List[Dict[str, Any]]) -> Dict[str, float]:
    """Normalized [5,10] scores from production triage_cases."""
    copies = [dict(c) for c in cases]
    triaged = triage_cases(copies)
    return {c["id"]: float(c["priority_score"]) for c in triaged}


def make_labels(
    scores: np.ndarray,
    n_bins: int = 3,
) -> Tuple[np.ndarray, List[str], List[float]]:
    """Quantile labels; returns y, class_names, priority bin_edges (length n_classes+1)."""
    s = pd.Series(scores)
    try:
        y_cat, bins = pd.qcut(s, q=n_bins, labels=False, retbins=True, duplicates="drop")
    except ValueError:
        y_cat, bins = pd.qcut(s.rank(method="first"), q=n_bins, labels=False, retbins=True, duplicates="drop")
    y = y_cat.astype(int).values
    n_classes = int(y.max()) + 1 if len(y) else 0
    class_names = ["tier_" + str(i) for i in range(n_classes)]
    if n_classes == 3:
        class_names = ["low", "medium", "high"]
    elif n_classes == 2:
        class_names = ["low", "high"]
    bin_edges = bins.tolist()
    return y, class_names, bin_edges


class TriageFeatures(BaseEstimator, TransformerMixin):
    """
    Multi-hot for list columns + one-hot for inv/relationship + numeric block.
    """

    _CAT_COLS = ("investigation_type", "relationship_to_victim")
    _NUM_COLS = ("victim_count", "rso", "log1p_images")

    def __init__(self, use_agencies: bool = True):
        self.use_agencies = use_agencies

    def fit(self, X: pd.DataFrame, y=None):
        self.list_cols_: Tuple[str, ...] = LIST_COLS_WITH_AGENCIES if self.use_agencies else LIST_COLS_NO_AGENCIES
        self.mlbs_: Dict[str, MultiLabelBinarizer] = {}
        for col in self.list_cols_:
            mlb = MultiLabelBinarizer()
            mlb.fit(X[col].tolist())
            self.mlbs_[col] = mlb
        self.ohe_ = OneHotEncoder(handle_unknown="ignore", sparse_output=True)
        self.ohe_.fit(X[list(self._CAT_COLS)])
        self.imputer_ = SimpleImputer(strategy="constant", fill_value=0.0)
        self.imputer_.fit(X[list(self._NUM_COLS)])
        return self

    def transform(self, X: pd.DataFrame):
        blocks = []
        for col in self.list_cols_:
            blocks.append(self.mlbs_[col].transform(X[col].tolist()))
        blocks.append(self.ohe_.transform(X[list(self._CAT_COLS)]))
        blocks.append(csr_matrix(self.imputer_.transform(X[list(self._NUM_COLS)])))
        return hstack(blocks, format="csr")


def build_feature_names(prep: TriageFeatures) -> List[str]:
    """Human-readable names aligned with hstack order."""
    names: List[str] = []
    for col in prep.list_cols_:
        mlb = prep.mlbs_[col]
        for c in mlb.classes_:
            names.append(f"{col}={c}")
    for raw in prep.ohe_.get_feature_names_out():
        names.append(str(raw))
    for col in prep._NUM_COLS:
        names.append(f"num__{col}")
    return names


def top_active_features_by_importance(
    pipe: Pipeline,
    X_row: pd.DataFrame,
    feature_names: List[str],
    top_k: int = 10,
) -> List[Tuple[str, float]]:
    """
    Rank features that are active on this row by (global_importance * |value|).
    Cheap local hint — not SHAP — good enough for mismatch triage.
    """
    prep = pipe.named_steps["prep"]
    clf = pipe.named_steps["clf"]
    imp = getattr(clf, "feature_importances_", None)
    if imp is None or len(imp) != len(feature_names):
        return []
    Xs = prep.transform(X_row)
    vec = np.asarray(Xs.todense()).ravel()
    scores = imp * np.abs(vec)
    active = np.where(np.abs(vec) > 1e-12)[0]
    if len(active) > 0:
        order = active[np.argsort(-scores[active])]
    else:
        order = np.argsort(-scores)
    out: List[Tuple[str, float]] = []
    for i in order[:top_k]:
        out.append((feature_names[i], float(scores[i])))
    return out


def _text_excerpt(case: Optional[Dict[str, Any]], max_len: int = 220) -> str:
    if not case:
        return ""
    t = case.get("case_text") or ""
    if not t and case.get("raw_data"):
        rd = case["raw_data"]
        if isinstance(rd, str):
            try:
                rd = json.loads(rd)
            except (json.JSONDecodeError, TypeError):
                rd = None
        if isinstance(rd, dict):
            t = rd.get("case_text") or ""
    if not isinstance(t, str):
        return ""
    t = " ".join(t.split())
    return t[:max_len] + ("…" if len(t) > max_len else "")


def run_mismatch_report(
    pipe: Pipeline,
    X_test: pd.DataFrame,
    y_test: np.ndarray,
    y_pred: np.ndarray,
    test_ids: np.ndarray,
    class_names: List[str],
    id_to_source: Dict[str, str],
    id_to_score: Dict[str, float],
    storage: CaseStorage,
    report_path: Path,
    proba: np.ndarray,
) -> None:
    prep = pipe.named_steps["prep"]
    assert isinstance(prep, TriageFeatures)
    feature_names = build_feature_names(prep)

    high_idx = class_names.index("high") if "high" in class_names else -1
    medium_idx = class_names.index("medium") if "medium" in class_names else -1

    rows_out: List[Dict[str, Any]] = []
    highlight: List[Dict[str, Any]] = []

    for i in range(len(y_test)):
        rid = str(test_ids[i])
        rt = class_names[int(y_test[i])]
        mt = class_names[int(y_pred[i])]
        if rt == mt:
            continue
        X_row = X_test.iloc[[i]]
        tops = top_active_features_by_importance(pipe, X_row, feature_names, top_k=10)
        top_str = "; ".join(f"{n} ({s:.4f})" for n, s in tops[:8])
        ph = float(proba[i, high_idx]) if high_idx >= 0 else ""
        case = storage.get_case(rid)
        excerpt = _text_excerpt(case)
        rec = {
            "case_id": rid,
            "source": id_to_source.get(rid, ""),
            "rule_tier": rt,
            "model_tier": mt,
            "rule_priority_score": id_to_score.get(rid, ""),
            "model_proba_high": ph,
            "top_features": top_str,
            "text_excerpt": excerpt,
        }
        rows_out.append(rec)
        if high_idx >= 0 and medium_idx >= 0 and int(y_pred[i]) == high_idx and int(y_test[i]) == medium_idx:
            highlight.append(rec)

    report_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows_out).to_csv(report_path, index=False)

    print("\n=== Mismatch summary (test set only) ===")
    print(f"Total test rows: {len(y_test)}")
    print(f"Rule ≠ model: {len(rows_out)}")
    print(f"Model HIGH, rule MEDIUM (human review): {len(highlight)}")
    print(f"Wrote: {report_path}")

    if highlight:
        print("\n--- Model HIGH / Rule MEDIUM (read narratives — severe or noise?) ---")
        for rec in highlight:
            print(
                f"\n  {rec['case_id']} | source={rec['source']} | "
                f"priority={rec['rule_priority_score']} | P(high)={rec['model_proba_high']:.3f}"
            )
            print(f"  features: {rec['top_features']}")
            print(f"  excerpt: {rec['text_excerpt']}")


def train_pipeline(
    X_train: pd.DataFrame,
    y_train: np.ndarray,
    model_kind: str,
    random_state: int,
    use_agencies: bool,
    criterion: str,
) -> Pipeline:
    pre = TriageFeatures(use_agencies=use_agencies)
    if model_kind == "tree":
        clf = DecisionTreeClassifier(
            criterion=criterion,
            max_depth=6,
            min_samples_leaf=4,
            random_state=random_state,
            class_weight="balanced",
        )
    else:
        clf = RandomForestClassifier(
            criterion=criterion,
            n_estimators=200,
            max_depth=12,
            min_samples_leaf=2,
            random_state=random_state,
            class_weight="balanced",
            n_jobs=-1,
        )
    pipe = Pipeline([("prep", pre), ("clf", clf)])
    pipe.fit(X_train, y_train)
    return pipe


def print_explain() -> None:
    text = """
What does it mean to "classify a new case"?
------------------------------------------

1. **Ingest & extract (same as always)**  
   A new narrative (PDF or text) runs through the CaseLinker processing layer:
   regex/pattern features, optional NER/merge → you get the same structured fields
   as rows in `cases` (topics, severity tags, platforms, investigation_type, etc.).

2. **Feature vector (this script's view)**  
   Those fields are flattened to a numeric design matrix: multi-label bins for list
   fields, one-hot for investigation/relationship, plus victim_count, RSO flag,
   log1p(image count). **No raw text** enters the sklearn model unless you extend it.

3. **What the model predicts**  
   The trainer uses labels derived from **your existing rule-based** `triage_cases`
   priority (normalized 5–10), binned into tiers (default: 3 quantile classes).
   So the classifier learns: "given extracted tags, which priority band would the
   current CaseLinker rules put this case in?"

4. **Not the same as operational CyberTip triage**  
   Labels are **proxies** from retrospective narratives + your rules, not
   investigator disposition or outcome. Use as **decision support / exploration**,
   compare to the explicit score, and expect **domain shift** on real tips.

5. **How to run inference**  
   After training, `--predict CASE_ID` loads the case from the DB, builds the row,
   and prints predicted tier + probabilities. For cases not in DB, export JSON
   from your pipeline and add a small loader (same columns as `cases_to_dataframe`).
"""
    print(text.strip())


def normalize_triage_bundle_after_load(bundle: TriageModelBundle) -> None:
    """
    Make pickled bundles usable across minor sklearn versions (train vs API venv).

    - Older bundles: statistics_ may be object dtype → coerce to float64.
    - Newer runtime (e.g. 1.8+): older pickles may lack SimpleImputer._fill_dtype.
    """
    prep = bundle.pipeline.named_steps.get("prep")
    if prep is None:
        return
    imp = getattr(prep, "imputer_", None)
    if imp is None:
        return
    stats = getattr(imp, "statistics_", None)
    if stats is not None and hasattr(stats, "dtype") and stats.dtype == np.dtype("O"):
        imp.statistics_ = np.asarray(stats, dtype=np.float64)
        stats = imp.statistics_
    if stats is not None and not hasattr(imp, "_fill_dtype"):
        fill_dtype = getattr(stats, "dtype", np.float64)
        imp._fill_dtype = np.dtype(fill_dtype) if not isinstance(fill_dtype, np.dtype) else fill_dtype


@dataclass
class TriageModelBundle:
    pipeline: Pipeline
    class_names: List[str]
    label_strategy: str
    priority_bin_edges: List[float]
    score_stats: Dict[str, float] = field(default_factory=dict)
    model_kind: str = "rf"
    use_agencies: bool = True
    criterion: str = "entropy"


def main() -> None:
    parser = argparse.ArgumentParser(description="Train triage tier model on CaseLinker DB")
    parser.add_argument("--db", type=Path, default=None, help="SQLite path (default: repo caselinker.db)")
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "models" / "triage_bundle.joblib")
    parser.add_argument("--model", type=str, choices=("rf", "tree"), default="rf", help="Classifier type")
    parser.add_argument(
        "--criterion",
        type=str,
        choices=("gini", "entropy", "log_loss"),
        default="entropy",
        help="Tree split criterion. 'entropy' uses information gain.",
    )
    parser.add_argument("--test-size", type=float, default=0.20)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--no-agencies", action="store_true", help="Ablation: drop agencies_involved multi-hot")
    parser.add_argument(
        "--mismatch-report",
        type=Path,
        default=None,
        help="CSV path for rule vs model mismatches on test set (default: alongside --out)",
    )
    parser.add_argument("--no-mismatch-report", action="store_true", help="Skip mismatch CSV and print block")
    parser.add_argument("--explain", action="store_true", help="Print what 'classify a new case' means and exit")
    parser.add_argument("--predict", type=str, default=None, metavar="CASE_ID", help="Predict tier for this case id")
    parser.add_argument("--bundle", type=Path, default=None, help="Bundle path for --predict (default: --out)")
    args = parser.parse_args()

    if args.explain:
        print_explain()
        return

    db = args.db or Path(os.environ.get("CASELINKER_DB", REPO_ROOT / "caselinker.db"))
    bundle_path = args.bundle or args.out
    use_agencies = not args.no_agencies

    if args.predict:
        if not bundle_path.exists():
            print(f"Bundle not found: {bundle_path}", file=sys.stderr)
            raise SystemExit(1)
        bundle: TriageModelBundle = joblib.load(bundle_path)
        normalize_triage_bundle_after_load(bundle)
        storage = get_case_storage(db)
        case = storage.get_case(args.predict)
        if not case:
            print(f"Case not found: {args.predict}", file=sys.stderr)
            raise SystemExit(1)
        df = cases_to_dataframe([case], include_agencies=bundle.use_agencies)
        X = df.drop(columns=["id"])
        proba = bundle.pipeline.predict_proba(X)[0]
        pred = int(bundle.pipeline.predict(X)[0])
        name = bundle.class_names[pred] if pred < len(bundle.class_names) else str(pred)
        print(f"case_id={args.predict}")
        print(f"predicted_tier={name} (class_index={pred})")
        print("class_probabilities:")
        for i, p in enumerate(proba):
            label = bundle.class_names[i] if i < len(bundle.class_names) else str(i)
            print(f"  {label}: {p:.4f}")
        return

    storage = get_case_storage(db)
    cases = storage.get_all_cases(include_raw_data=False)
    if len(cases) < 12:
        print(f"Need at least ~12 cases for a stable split; got {len(cases)}.", file=sys.stderr)
        raise SystemExit(1)

    id_to_source = {str(c["id"]): (c.get("source") or "") for c in cases}
    id_to_score = priority_scores_by_id(cases)
    scores = np.array([id_to_score[c["id"]] for c in cases])
    y, class_names, bin_edges = make_labels(scores, n_bins=3)

    df = cases_to_dataframe(cases, include_agencies=use_agencies)
    X = df.drop(columns=["id"])
    ids = df["id"].values

    idx = np.arange(len(df))
    idx_train, idx_test, y_train, y_test = train_test_split(
        idx, y, test_size=args.test_size, random_state=args.seed, stratify=y
    )
    X_train = X.iloc[idx_train]
    X_test = X.iloc[idx_test]
    test_ids = ids[idx_test]

    pipe = train_pipeline(X_train, y_train, args.model, args.seed, use_agencies, args.criterion)
    y_pred = pipe.predict(X_test)
    proba = pipe.predict_proba(X_test)
    acc = accuracy_score(y_test, y_pred)

    print("=== Hold-out classification report ===")
    print(f"use_agencies={use_agencies}")
    print(f"criterion={args.criterion}")
    print(f"test accuracy: {acc:.4f}")
    print(classification_report(y_test, y_pred, target_names=class_names, zero_division=0))

    report_path = args.mismatch_report
    if report_path is None:
        report_path = args.out.with_suffix(".mismatches.csv")
    if not args.no_mismatch_report:
        run_mismatch_report(
            pipe,
            X_test,
            y_test,
            y_pred,
            test_ids,
            class_names,
            id_to_source,
            id_to_score,
            storage,
            report_path,
            proba,
        )

    bundle = TriageModelBundle(
        pipeline=pipe,
        class_names=class_names,
        label_strategy="quantile_3_on_normalized_priority_score",
        priority_bin_edges=[float(x) for x in bin_edges],
        score_stats={"min": float(scores.min()), "max": float(scores.max()), "mean": float(scores.mean())},
        model_kind=args.model,
        use_agencies=use_agencies,
        criterion=args.criterion,
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, args.out)
    meta_path = args.out.with_suffix(".meta.json")
    meta = {
        "class_names": class_names,
        "label_strategy": bundle.label_strategy,
        "priority_bin_edges": bundle.priority_bin_edges,
        "score_stats": bundle.score_stats,
        "model_kind": args.model,
        "criterion": args.criterion,
        "use_agencies": use_agencies,
        "test_accuracy": acc,
        "n_cases": len(cases),
        "mismatch_report": str(report_path) if not args.no_mismatch_report else None,
        "explain": "Labels = quantile bins of analysis.triage_cases priority_score (5-10 scale).",
    }
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"\nSaved bundle: {args.out}")
    print(f"Saved meta:   {meta_path}")


if __name__ == "__main__":
    main()
