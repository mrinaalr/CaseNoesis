#!/usr/bin/env python3
"""
Build + cache merged JSON-LD flat node lists for Patterns compare / Big Bang.

Caches to:
  ontology/cache/merged_compare.json
  ontology/cache/merged_all.json.gz

Redis keys (when available):
  caselinker:ontology:merged:compare:{manifest}
  caselinker:ontology:merged:all:{manifest}
"""

from __future__ import annotations

import gzip
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

REPO_ROOT = Path(__file__).resolve().parent.parent
ONTOLOGY = REPO_ROOT / "ontology"
GRAPH_DIR = ONTOLOGY / "graph_output"
CACHE_DIR = ONTOLOGY / "cache"
COMPARE_IDS_FILE = ONTOLOGY / "selected_200_ids.txt"
NLP_GRAPH_RE = re.compile(r"/graphs/nlp$")


def _compare_pool_ids() -> List[str]:
    if not COMPARE_IDS_FILE.is_file():
        return []
    return [ln.strip() for ln in COMPARE_IDS_FILE.read_text().splitlines() if ln.strip()]


def graph_manifest() -> str:
    """Fingerprint graph_output contents for cache invalidation."""
    if not GRAPH_DIR.is_dir():
        return "empty"
    parts: List[str] = []
    for p in sorted(GRAPH_DIR.glob("*.jsonld")):
        st = p.stat()
        parts.append(f"{p.stem}:{st.st_size}:{int(st.st_mtime)}")
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:16]


def flatten_named_graphs(json_ld: Any) -> List[Dict[str, Any]]:
    nodes: List[Dict[str, Any]] = []
    if isinstance(json_ld, dict):
        graphs = [json_ld]
    elif isinstance(json_ld, list):
        graphs = json_ld
    else:
        return nodes

    for named in graphs:
        is_nlp = bool(
            isinstance(named, dict)
            and NLP_GRAPH_RE.search(str(named.get("@id") or ""))
        )
        for node in named.get("@graph") or []:
            if not isinstance(node, dict) or not node.get("@id"):
                continue
            copy = dict(node)
            if is_nlp:
                copy["_isNlp"] = True
            nodes.append(copy)
    return nodes


def _serialize_term(v: Any) -> str:
    if isinstance(v, dict):
        if "@id" in v:
            return "id:" + str(v["@id"])
        if "@value" in v:
            return "v:" + str(v.get("@type") or "") + ":" + str(v["@value"])
    return "lit:" + str(v)


def merge_case_into_store(store: Dict[str, Dict[str, Any]], case_id: str, json_ld: Any) -> None:
    for node in flatten_named_graphs(json_ld):
        nid = node["@id"]
        if nid not in store:
            copy = dict(node)
            t = copy.get("@type")
            if isinstance(t, list):
                copy["@type"] = list(t)
            copy["_cases"] = [case_id]
            copy["_isNlp"] = bool(node.get("_isNlp"))
            store[nid] = copy
            continue
        ex = store[nid]
        if case_id not in ex["_cases"]:
            ex["_cases"].append(case_id)
        if node.get("_isNlp"):
            ex["_isNlp"] = True
        for k, v in node.items():
            if k in ("@id", "_cases", "_isNlp"):
                continue
            if k == "@type":
                ea = ex.get(k) or []
                ea = ea if isinstance(ea, list) else [ea]
                na = v if isinstance(v, list) else [v]
                ex[k] = list(dict.fromkeys([*ea, *na]))
                continue
            if k not in ex:
                ex[k] = v
                continue
            if isinstance(ex[k], list) and isinstance(v, list):
                seen = {_serialize_term(x) for x in ex[k]}
                for item in v:
                    key = _serialize_term(item)
                    if key not in seen:
                        ex[k].append(item)
                        seen.add(key)


def build_merged_flat(case_ids: List[str]) -> List[Dict[str, Any]]:
    store: Dict[str, Dict[str, Any]] = {}
    for cid in case_ids:
        path = GRAPH_DIR / f"{cid}.jsonld"
        if not path.is_file():
            continue
        try:
            doc = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        merge_case_into_store(store, cid, doc)
    flat = list(store.values())
    for n in flat:
        n["_isShared"] = len(n.get("_cases") or []) > 1
    return flat


def case_ids_for_pool(pool: str) -> List[str]:
    graphs = sorted(p.stem for p in GRAPH_DIR.glob("*.jsonld"))
    if pool == "compare":
        order = _compare_pool_ids()
        return [cid for cid in order if cid in set(graphs)]
    return graphs


def load_merged_payload(pool: str) -> Optional[Dict[str, Any]]:
    manifest = graph_manifest()
    path = CACHE_DIR / ("merged_compare.json" if pool == "compare" else "merged_all.json.gz")
    if not path.is_file():
        return None
    try:
        if path.suffix == ".gz":
            raw = gzip.decompress(path.read_bytes()).decode()
        else:
            raw = path.read_text()
        payload = json.loads(raw)
        if payload.get("manifest") == manifest and payload.get("pool") == pool:
            return payload
    except (json.JSONDecodeError, OSError):
        pass
    return None


def save_merged_payload(pool: str, flat: List[Dict[str, Any]], case_ids: List[str]) -> Dict[str, Any]:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    manifest = graph_manifest()
    payload = {
        "pool": pool,
        "manifest": manifest,
        "n_cases": len(case_ids),
        "n_nodes": len(flat),
        "case_ids": case_ids,
        "flat_nodes": flat,
    }
    if pool == "compare":
        (CACHE_DIR / "merged_compare.json").write_text(json.dumps(payload))
    else:
        data = json.dumps(payload).encode()
        (CACHE_DIR / "merged_all.json.gz").write_bytes(gzip.compress(data, compresslevel=6))
    return payload


def get_or_build_merged(pool: str, redis_get=None, redis_set=None) -> Dict[str, Any]:
    """Return merged payload; use Redis hooks from run/redis_cache when provided."""
    pool = pool.strip().lower()
    if pool not in ("compare", "all"):
        raise ValueError("pool must be compare or all")

    manifest = graph_manifest()
    redis_key = f"caselinker:ontology:merged:{pool}:{manifest}"

    if redis_get:
        hit = redis_get(redis_key)
        if hit and isinstance(hit, dict) and hit.get("manifest") == manifest:
            hit["cache"] = "redis"
            return hit

    disk = load_merged_payload(pool)
    if disk:
        disk["cache"] = "disk"
        if redis_set:
            redis_set(redis_key, disk, ttl=86400 * 7)
        return disk

    case_ids = case_ids_for_pool(pool)
    flat = build_merged_flat(case_ids)
    payload = save_merged_payload(pool, flat, case_ids)
    payload["cache"] = "built"
    if redis_set:
        redis_set(redis_key, payload, ttl=86400 * 7)
    return payload


def warm_all_caches(redis_get=None, redis_set=None) -> None:
    for pool in ("compare", "all"):
        p = get_or_build_merged(pool, redis_get=redis_get, redis_set=redis_set)
        print(f"  merged {pool}: {p['n_cases']} cases, {p['n_nodes']} nodes ({p.get('cache')})")


if __name__ == "__main__":
    try:
        import sys

        sys.path.insert(0, str(REPO_ROOT / "run"))
        from redis_cache import get_cached, set_cached  # noqa: E402

        warm_all_caches(redis_get=get_cached, redis_set=lambda k, v, ttl=604800: set_cached(k, v, ttl=ttl))
    except ImportError:
        warm_all_caches()
