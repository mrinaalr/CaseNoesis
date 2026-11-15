"""Build the gold corpus: 200 invented records with known attributes.

The corpus is deterministic. The same seed writes the same bytes, and a test
checks that the committed files match what the generator produces.

    gold/corpus/records.jsonl   one record per line: id, metadata, text
    gold/corpus/truth.jsonl     what each record states
    gold/corpus/cases.jsonl     each case: its people, its records, what was planted

Cases alternate between a `dev` split, which may be used while working on the
readers, and a `test` split, which is only scored.
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

from encoding import corpus
from extraction import fields
from gold import render
from gold.world import Case, sample_case

SEED = 20261114
RECORDS = 200
CORPUS = Path(__file__).resolve().parent / "corpus"
# How many court filings accompany the press release, cycled over cases.
_PLAN = (0, 0, 1, 0, 2, 0, 1, 0, 0, 2, 1, 0, 0)


def _documents(case: Case, rng: random.Random, court: int) -> list[render.Rec]:
    press = {"charged": render.press_charged, "disposed": render.press_disposed, "sentenced": render.press_sentenced}[case.stage](case, rng)
    lead = case.defendants[0]
    first = case.outcomes[lead.key]
    available: list[Any] = [lambda: render.indictment(case, rng, press)]
    if first.disposition == "plea" and case.planted != "plea_withdrawn":
        available.append(lambda: render.plea_agreement(case, rng, press, lead))
    if case.stage == "sentenced":
        person = rng.choice(case.defendants)
        available.append(lambda: render.judgment(case, rng, press, person))
    chosen = sorted(rng.sample(range(len(available)), k=min(court, len(available))))
    return [press, *(available[index]() for index in chosen)]


def _unclaimed(rec: render.Rec) -> list[dict[str, Any]]:
    """Typed tokens in the text that the truth does not claim: the distractors."""
    claimed = {(item["field"], _norm(item["field"], item["value"])) for item in (*rec.values, *rec.optional)}
    found = []
    for name, iterate in fields.ITERATORS.items():
        if name == "conduct":
            continue  # acts are measured on the statements of offense in gold/conduct.py, not here
        for start, end, value, extras in iterate(rec.text):
            shown = ("life" if extras.get("life") else extras.get("months")) if name == "sentence" else value
            key = (name, _norm(name, shown))
            if key not in claimed:
                found.append({"field": name, "value": key[1], "text": rec.text[max(0, start - 30): end + 20].replace("\n", " ")})
    return found


def _norm(name: str, value: Any) -> Any:
    if name in ("money", "sentence") and isinstance(value, (int, float)):
        return round(float(value), 2)
    return value


def generate() -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    records: list[dict[str, Any]] = []
    truth: list[dict[str, Any]] = []
    cases: list[dict[str, Any]] = []
    distractors: list[dict[str, Any]] = []
    number = 0
    while len(records) < RECORDS:
        number += 1
        case = sample_case(SEED, number)
        rng = random.Random(SEED * 7 + number)
        documents = _documents(case, rng, _PLAN[number % len(_PLAN)])[: RECORDS - len(records)]
        ids = []
        for rec in documents:
            entry = dict(rec.entry)
            record_id = corpus.press_record_id(entry["source_url"]) if rec.kind == "press" else "ct-" + entry["sha256"][:16]
            entry["record_id"] = record_id
            ids.append(record_id)
            records.append({"record_id": record_id, "case_id": case.case_id, "split": case.split, "shape": rec.shape, "entry": entry, "text": rec.text})
            none = _unclaimed(rec)
            distractors += [{"record_id": record_id, **item} for item in none]
            truth.append({
                "record_id": record_id, "case_id": case.case_id, "split": case.split, "kind": rec.kind, "shape": rec.shape,
                "values": rec.values, "optional": rec.optional, "distractors": [{"field": d["field"], "value": d["value"]} for d in none],
                "tags": {name: sorted(labels) for name, labels in rec.tags.items()},
                "unscored": sorted(rec.unscored),
                "defendants": sorted(rec.names),
                "names": {key: sorted(forms) for key, forms in sorted(rec.names.items())},
                "events": rec.events,
            })
        cases.append({
            "case_id": case.case_id, "split": case.split, "domain": case.domain, "narrative": case.narrative.key,
            "stage": case.stage, "planted": case.planted, "records": ids,
            "defendants": [{"key": p.key, "name": p.full} for p in case.defendants],
        })
    return records, truth, cases, distractors


def write() -> dict[str, Any]:
    records, truth, cases, distractors = generate()
    CORPUS.mkdir(parents=True, exist_ok=True)
    for name, rows in (("records", records), ("truth", truth), ("cases", cases)):
        with (CORPUS / f"{name}.jsonl").open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    shapes: dict[str, int] = {}
    for row in records:
        shapes[row["shape"]] = shapes.get(row["shape"], 0) + 1
    return {
        "records": len(records), "cases": len(cases), "shapes": shapes,
        "cases_with_more_than_one_record": sum(1 for c in cases if len(c["records"]) > 1),
        "planted": {key: sum(1 for c in cases if c["planted"] == key) for key in ("resentencing", "plea_withdrawn", "date_inconsistency")},
        "truth_values": sum(len(t["values"]) for t in truth), "distractors": len(distractors),
        "split": {key: sum(1 for r in records if r["split"] == key) for key in ("dev", "test")},
    }


def load(split: str | None = None) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Records, truth by record id, and cases, from the committed corpus."""
    def rows(name: str) -> list[dict[str, Any]]:
        with (CORPUS / f"{name}.jsonl").open(encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]

    records = [r for r in rows("records") if split in (None, r["split"])]
    truth = {t["record_id"]: t for t in rows("truth") if split in (None, t["split"])}
    cases = [c for c in rows("cases") if split in (None, c["split"])]
    return records, truth, cases
