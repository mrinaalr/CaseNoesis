#!/usr/bin/env python3
"""
Quick triage model evaluation with an 80/20 train-test split.

Uses existing CaseLinker triage labels (from `analysis.triage_cases`) and the same
feature pipeline as `scripts/train_triage_model.py`.

Examples:
  python3 scripts/test_triage.py
  python3 scripts/test_triage.py --no-agencies
  python3 scripts/test_triage.py --model tree --seed 7
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
from sklearn.model_selection import train_test_split

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src" / "Storage Layer"))

from train_triage_model import (  # noqa: E402
    CaseStorage,
    cases_to_dataframe,
    make_labels,
    priority_scores_by_id,
    train_pipeline,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate triage classifier with 80/20 split")
    parser.add_argument("--db", type=Path, default=ROOT / "caselinker.db", help="Path to SQLite DB")
    parser.add_argument("--model", choices=("rf", "tree"), default="rf", help="Model type")
    parser.add_argument(
        "--criterion",
        choices=("gini", "entropy", "log_loss"),
        default="entropy",
        help="Tree split criterion. 'entropy' means information gain.",
    )
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--no-agencies", action="store_true", help="Drop agencies feature")
    args = parser.parse_args()

    storage = CaseStorage(str(args.db))
    cases = storage.get_all_cases(include_raw_data=False)
    if len(cases) < 20:
        raise SystemExit(f"Need at least 20 cases; found {len(cases)}")

    use_agencies = not args.no_agencies
    id_to_score = priority_scores_by_id(cases)
    scores = np.array([id_to_score[c["id"]] for c in cases])
    y, class_names, _ = make_labels(scores, n_bins=3)

    df = cases_to_dataframe(cases, include_agencies=use_agencies)
    X = df.drop(columns=["id"])

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.20, random_state=args.seed, stratify=y
    )

    pipe = train_pipeline(
        X_train,
        y_train,
        args.model,
        args.seed,
        use_agencies=use_agencies,
        criterion=args.criterion,
    )
    y_pred = pipe.predict(X_test)

    acc = accuracy_score(y_test, y_pred)
    cm = confusion_matrix(y_test, y_pred, labels=list(range(len(class_names))))

    print("=== Triage 80/20 Evaluation ===")
    print(f"cases={len(cases)} | train={len(X_train)} | test={len(X_test)}")
    print(f"model={args.model} | criterion={args.criterion} | use_agencies={use_agencies} | seed={args.seed}")
    print(f"accuracy={acc:.4f}")
    print("\nClassification report:")
    print(classification_report(y_test, y_pred, target_names=class_names, zero_division=0))
    print("Confusion matrix (rows=true, cols=pred):")
    print(class_names)
    print(cm)


if __name__ == "__main__":
    main()
