#!/usr/bin/env python3
"""Shared CaseLinker → JSON-LD/TTL graph generation (features_to_cac)."""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
ONTOLOGY = REPO_ROOT / "ontology"
DEFAULT_GRAPH_DIR = ONTOLOGY / "graph_output"

sys.path.insert(0, str(ONTOLOGY))


def generate_graphs(
    ids: List[str],
    out_dir: Path,
    *,
    validate_shacl: bool = True,
) -> Dict[str, Any]:
    from features_to_cac import CaseToCAC, _load_case_with_fallback  # noqa: E402
    from rdflib import Graph

    out_dir.mkdir(parents=True, exist_ok=True)
    mapper = CaseToCAC()

    generated: List[str] = []
    skipped: List[Dict[str, str]] = []
    failed: List[Dict[str, str]] = []
    shacl_ok: List[str] = []
    shacl_fail: List[Dict[str, Any]] = []

    for i, cid in enumerate(ids, 1):
        try:
            case, src = _load_case_with_fallback(cid)
            if case is None:
                skipped.append({"case_id": cid, "reason": "not in DB"})
                continue

            graph, _warnings = mapper.map_case(case)
            conforms, shacl_report = True, ""
            if validate_shacl:
                conforms, shacl_report = mapper.validate(graph)
                if shacl_report == "pyshacl not installed":
                    raise RuntimeError("pip install pyshacl")

            jsonld_path = out_dir / f"{cid}.jsonld"
            ttl_path = out_dir / f"{cid}.ttl"
            graph.serialize(destination=str(jsonld_path), format="json-ld", indent=2)
            flat_g = Graph()
            for ctx in graph.graphs():
                for triple in ctx:
                    flat_g.add(triple)
            for prefix, ns in graph.namespaces():
                flat_g.bind(prefix, ns, replace=True)
            flat_g.serialize(destination=str(ttl_path), format="turtle")

            if validate_shacl and not conforms:
                shacl_fail.append({"case_id": cid, "shacl_report": (shacl_report or "")[:4000]})
            else:
                shacl_ok.append(cid)
            generated.append(cid)

        except Exception as exc:
            failed.append(
                {
                    "case_id": cid,
                    "reason": str(exc),
                    "traceback": traceback.format_exc()[-1500:],
                }
            )
            print(f"  FAIL {cid}: {exc}", file=sys.stderr)

        if i % 50 == 0:
            print(
                f"  [{i}/{len(ids)}] generated={len(generated)} "
                f"shacl_ok={len(shacl_ok)} fail={len(failed)}",
                flush=True,
            )

    return {
        "generated": generated,
        "skipped": skipped,
        "failed": failed,
        "shacl_ok": shacl_ok,
        "shacl_fail": shacl_fail,
        "out_dir": str(out_dir),
    }


def load_all_case_ids(db_path: Optional[Path] = None) -> List[str]:
    import sqlite3

    db = db_path or (REPO_ROOT / "caselinker.db")
    if not db.is_file():
        raise FileNotFoundError(f"Database not found: {db}")
    conn = sqlite3.connect(str(db))
    try:
        return [r[0] for r in conn.execute("SELECT id FROM cases ORDER BY id").fetchall()]
    finally:
        conn.close()
