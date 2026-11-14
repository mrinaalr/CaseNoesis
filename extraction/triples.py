"""The local triple store: every validated engine graph, queryable with SPARQL.

Everything is on this machine. There is no hosted database and no remote
endpoint. Two artifacts under `data/extracted/`, both rebuilt from the graph
files at any time:

    oxigraph/     an Oxigraph store, one named graph per record
    graphs.nq     the same quads as one N-Quads file, for any other RDF tool

A record's named graph is `urn:casenoesis:record:<record-id>`. Only graphs
that passed the SDK gate and the name check are loaded, unless asked.

    python -m extraction store                 load new graphs, write graphs.nq
    python -m extraction sparql "SELECT ..."    query
    python -m extraction serve                 SPARQL over HTTP on 127.0.0.1
"""

from __future__ import annotations

import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from extraction import graph as graph_layer
from extraction import store as sql

GRAPH_PREFIX = "urn:casenoesis:record:"
MAX_ROWS = 1000

PREFIXES = """PREFIX uco-core: <https://ontology.unifiedcyberontology.org/uco/core/>
PREFIX uco-identity: <https://ontology.unifiedcyberontology.org/uco/identity/>
PREFIX uco-observable: <https://ontology.unifiedcyberontology.org/uco/observable/>
PREFIX uco-role: <https://ontology.unifiedcyberontology.org/uco/role/>
PREFIX uco-action: <https://ontology.unifiedcyberontology.org/uco/action/>
PREFIX case-investigation: <https://ontology.caseontology.org/case/investigation/>
PREFIX legalproc: <https://ontology.caseontology.org/case/criminal/>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
"""

_WRITE = re.compile(r"^\s*(?:(?:PREFIX|BASE)\b[^\n]*\n\s*)*(?:INSERT|DELETE|LOAD|CLEAR|DROP|CREATE|ADD|MOVE|COPY|WITH)\b", re.IGNORECASE)


def store_dir() -> Path:
    return sql.EXTRACTED / "oxigraph"


def nquads_path() -> Path:
    return sql.EXTRACTED / "graphs.nq"


def _open(read_only: bool = False):
    import pyoxigraph as ox

    path = store_dir()
    if read_only and path.is_dir():
        return ox.Store.read_only(str(path))
    path.mkdir(parents=True, exist_ok=True)
    return ox.Store(str(path))


def load(*, rebuild: bool = False, include_unvalidated: bool = False, write_nquads: bool = True) -> dict[str, Any]:
    """Load engine graphs into the Oxigraph store and write `graphs.nq`.

    A record already in the store with the same graph hash is skipped.
    """
    import pyoxigraph as ox

    db = sql.connect()
    db.execute("CREATE TABLE IF NOT EXISTS triple_store (record_id TEXT PRIMARY KEY, graph_sha256 TEXT NOT NULL, loaded_at TEXT NOT NULL)")
    store = _open()
    if rebuild:
        store.clear()
        db.execute("DELETE FROM triple_store")
    loaded = {row[0]: row[1] for row in db.execute("SELECT record_id, graph_sha256 FROM triple_store")}
    condition = "name_check = 'pass'" + ("" if include_unvalidated else " AND conforms = 1")
    added = 0
    for row in db.execute(f"SELECT record_id, graph_sha256 FROM graphs WHERE {condition}").fetchall():
        record_id, digest = row[0], row[1]
        if loaded.get(record_id) == digest:
            continue
        path = graph_layer.graph_dir(record_id) / "graph.jsonld"
        if not path.is_file():
            continue
        name = ox.NamedNode(GRAPH_PREFIX + record_id)
        store.remove_graph(name)
        store.load(path=str(path), format=ox.RdfFormat.JSON_LD, to_graph=name)
        db.execute("INSERT OR REPLACE INTO triple_store (record_id, graph_sha256, loaded_at) VALUES (?,?,?)",
                   (record_id, digest, sql.now()))
        added += 1
        if added % 2000 == 0:
            db.commit()
    db.commit()
    store.flush()
    summary = {"loaded_now": added, "named_graphs": sum(1 for _ in store.named_graphs()), "quads": len(store),
               "store": str(store_dir().relative_to(sql.REPO_ROOT))}
    if write_nquads:
        store.dump(output=str(nquads_path()), format=ox.RdfFormat.N_QUADS)
        summary["nquads"] = str(nquads_path().relative_to(sql.REPO_ROOT))
        summary["nquads_bytes"] = nquads_path().stat().st_size
    return summary


def status() -> dict[str, Any]:
    if not store_dir().is_dir():
        return {"loaded": False, "hint": "python -m extraction store"}
    store = _open(read_only=True)
    return {
        "loaded": True, "named_graphs": sum(1 for _ in store.named_graphs()), "quads": len(store),
        "store": str(store_dir().relative_to(sql.REPO_ROOT)),
        "nquads": str(nquads_path().relative_to(sql.REPO_ROOT)) if nquads_path().is_file() else None,
        "graph_name": GRAPH_PREFIX + "<record-id>",
    }


def _term(term: Any) -> Any:
    return None if term is None else getattr(term, "value", str(term))


def query(sparql: str, limit: int = 200, add_prefixes: bool = True) -> dict[str, Any]:
    """Run a read-only SPARQL query. SELECT returns rows, ASK a boolean,
    CONSTRUCT and DESCRIBE triples. Updates are refused."""
    if _WRITE.match(sparql):
        return {"error": "The store is read-only here. Rebuild it with: python -m extraction store"}
    if not store_dir().is_dir():
        return {"error": "No triple store yet. Run: python -m extraction store"}
    text = (PREFIXES + sparql) if add_prefixes and not re.search(r"^\s*PREFIX\s+uco-core:", sparql, re.I | re.M) else sparql
    limit = max(1, min(limit, MAX_ROWS))
    try:
        result = _open(read_only=True).query(text, use_default_graph_as_union=True)
    except (SyntaxError, ValueError, OSError) as error:
        return {"error": f"{type(error).__name__}: {error}"}
    if isinstance(result, bool) or type(result).__name__ == "QueryBoolean":
        return {"boolean": bool(result)}
    if hasattr(result, "variables"):
        names = [variable.value for variable in result.variables]
        rows = []
        for solution in result:
            rows.append({name: _term(solution[name]) for name in names})
            if len(rows) >= limit:
                break
        return {"variables": names, "rows": rows, "truncated": len(rows) >= limit}
    triples = []
    for triple in result:
        triples.append([_term(triple.subject), _term(triple.predicate), _term(triple.object)])
        if len(triples) >= limit:
            break
    return {"triples": triples, "truncated": len(triples) >= limit}


EXAMPLES = {
    "records_per_scheme": 'SELECT ?scheme (COUNT(DISTINCT ?g) AS ?records) WHERE { GRAPH ?g { ?r uco-core:tag ?scheme . FILTER(STRSTARTS(?scheme, "scheme:")) } } GROUP BY ?scheme ORDER BY DESC(?records)',
    "restitution_over_1m": "SELECT ?g ?amount WHERE { GRAPH ?g { ?o a legalproc:RestitutionOrder ; legalproc:monetaryAmount ?amount . FILTER(?amount >= 1000000) } } ORDER BY DESC(?amount)",
    "defendants_and_charges": "SELECT ?g ?person ?citation WHERE { GRAPH ?g { ?p a uco-identity:Person ; uco-core:name ?person ; legalproc:chargedWith ?c . ?c legalproc:statuteCitation ?citation } }",
    "crypto_romance": 'SELECT ?g WHERE { GRAPH ?g { ?r uco-core:tag "scheme:romance", "channel:cryptocurrency" } }',
}


class _Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, payload: Any) -> None:
        body = json.dumps(payload, indent=2, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _sparql(self, text: str | None, limit: str | None) -> None:
        if not text:
            self._send(400, {"error": "missing query", "examples": EXAMPLES})
            return
        result = query(text, int(limit) if (limit or "").isdigit() else 200)
        self._send(400 if "error" in result else 200, result)

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        parts = urlsplit(self.path)
        params = parse_qs(parts.query)
        if parts.path == "/sparql":
            self._sparql((params.get("query") or [None])[0], (params.get("limit") or [None])[0])
        elif parts.path in ("/", "/status"):
            from extraction import explore

            self._send(200, {"triple_store": status(), "engine": explore.status(), "sparql": "/sparql?query=", "examples": EXAMPLES})
        else:
            self._send(404, {"error": "not found", "routes": ["/", "/status", "/sparql?query="]})

    def do_POST(self) -> None:  # noqa: N802 - http.server API
        if urlsplit(self.path).path != "/sparql":
            self._send(404, {"error": "not found"})
            return
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode("utf-8")
        if "application/x-www-form-urlencoded" in (self.headers.get("Content-Type") or ""):
            params = parse_qs(body)
            self._sparql((params.get("query") or [None])[0], (params.get("limit") or [None])[0])
        else:
            self._sparql(body, None)

    def log_message(self, *args: Any) -> None:  # quiet
        return


def serve(port: int = 7878) -> None:
    """SPARQL over HTTP for this machine only. Binds 127.0.0.1 and nothing else."""
    server = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    print(f"CaseNoesis triple store on http://127.0.0.1:{port}/  (SPARQL at /sparql, read-only, local only)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
