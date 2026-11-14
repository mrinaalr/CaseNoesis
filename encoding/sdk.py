"""The pinned CASE/UCO SDK: where it is, which commit, and the SHACL gate.

Everything in CaseNoesis that reads SDK extension Turtle or validates a graph
resolves the SDK here, so a graph can record the exact SDK commit it passed.

The pin is the `vendor/CASE-UCO-SDK` git submodule. `SDK_COMMIT` below must
equal that submodule's HEAD. To move the pin, check out the new tag inside the
submodule, reinstall `vendor/CASE-UCO-SDK/python`, and update the two constants.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from functools import lru_cache
from importlib import metadata
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

SDK_REPO = "https://github.com/vulnmaster/CASE-UCO-SDK"
SDK_TAG = "v1.33.0"
SDK_COMMIT = "a2dc8bc96f5001c58af63e587593dbf6385b24cf"

VENDORED_SDK = REPO_ROOT / "vendor" / "CASE-UCO-SDK"
SDK_ROOT_ENV = "CASENOESIS_SDK_ROOT"

# Upper-ontology profiles every trajectories graph needs (OWL-Time intervals,
# PROV-O derivation links).
DEFAULT_PROFILES = ("time", "prov-o")

RECEIPT_SUFFIX = ".gate.json"
RECEIPT_SCHEMA = "noesis-gate-receipt/1"


class SdkUnavailable(RuntimeError):
    """The SDK checkout is missing, or is not at the pinned commit."""


def sdk_root() -> Path:
    """The SDK checkout to use.

    `CASENOESIS_SDK_ROOT` overrides the submodule, for trying an unreleased
    branch. A graph validated that way is never marked `pinned`.
    """
    override = os.environ.get(SDK_ROOT_ENV)
    root = Path(override).expanduser().resolve() if override else VENDORED_SDK
    if not (root / "extensions").is_dir():
        raise SdkUnavailable(
            f"No CASE/UCO SDK checkout at {root}. Run: "
            "git submodule update --init vendor/CASE-UCO-SDK"
        )
    return root


def _git(root: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=False
    )
    return done.stdout.strip() if done.returncode == 0 else ""


@lru_cache(maxsize=4)
def _checkout_state(root_text: str) -> tuple[str, bool]:
    root = Path(root_text)
    commit = _git(root, "rev-parse", "HEAD")
    # Untracked files do not change what the validator loads from a manifest,
    # but a modified tracked file does.
    dirty = bool(_git(root, "status", "--porcelain", "--untracked-files=no"))
    return commit, dirty


def _package_version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def extension_manifests(root: Path | None = None) -> dict[str, dict[str, Any]]:
    """`{extension name: manifest}` for every extension the checkout carries."""
    root = root or sdk_root()
    found: dict[str, dict[str, Any]] = {}
    for base in ("extensions", "ontology"):
        for path in sorted((root / base).glob("*/manifest.json")):
            try:
                manifest = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            found.setdefault(str(manifest.get("name") or path.parent.name), manifest)
    return found


def pin_status() -> dict[str, Any]:
    """What is installed, and whether it is the pin."""
    root = sdk_root()
    commit, dirty = _checkout_state(str(root))
    manifests = extension_manifests(root)
    return {
        "repo": SDK_REPO,
        "tag": SDK_TAG,
        "pinned_commit": SDK_COMMIT,
        "root": str(root),
        "commit": commit,
        "dirty": dirty,
        "pinned": commit == SDK_COMMIT and not dirty and root == VENDORED_SDK,
        "case_uco": _package_version("case-uco"),
        "case_utils": _package_version("case_utils"),
        "pyshacl": _package_version("pyshacl"),
        "rdflib": _package_version("rdflib"),
        "extensions": {name: m.get("version") for name, m in sorted(manifests.items())},
    }


def _extension_namespaces(root: Path) -> list[tuple[str, str]]:
    from case_uco.graph import DEFAULT_CONTEXT

    core = {iri for iri in DEFAULT_CONTEXT.values() if isinstance(iri, str)}
    pairs = [
        (iri, name)
        for name, manifest in extension_manifests(root).items()
        for iri in (manifest.get("namespaces") or {}).values()
        if isinstance(iri, str) and iri and iri not in core
    ]
    return sorted(pairs, key=lambda pair: len(pair[0]), reverse=True)


def extensions_used(graph_path: str | Path, root: Path | None = None) -> list[str]:
    """SDK extensions whose namespaces a Turtle or JSON-LD graph uses anywhere:
    as a type, a property, or a node it points at. A state from a pinned
    alphabet appears only as the object of `traj:assertsState`, and the gate
    still has to load the extension that declares it."""
    from rdflib import Graph, URIRef

    root = root or sdk_root()
    path = Path(graph_path)
    graph = Graph()
    graph.parse(path, format="turtle" if path.suffix.lower() in {".ttl", ".turtle"} else "json-ld")
    used = {str(term) for triple in graph for term in triple if isinstance(term, URIRef)}
    namespaces = _extension_namespaces(root)
    needed: set[str] = set()
    for iri in used:
        for namespace, name in namespaces:
            if iri.startswith(namespace):
                needed.add(name)
                break
    return sorted(needed)


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _use_venv_validator() -> None:
    """`case_validate` is looked up on PATH. Put this interpreter's bin first
    so the validator that runs is the one installed beside `case_uco`."""
    bin_dir = str(Path(sys.executable).parent)
    parts = os.environ.get("PATH", "").split(os.pathsep)
    if bin_dir not in parts:
        os.environ["PATH"] = os.pathsep.join([bin_dir, *parts])


def gate(
    graph_path: str | Path,
    *,
    extensions: list[str] | None = None,
    profiles: tuple[str, ...] | list[str] = DEFAULT_PROFILES,
    extra_ontology_graphs: list[str | Path] | None = None,
    timeout_seconds: int = 900,
) -> dict[str, Any]:
    """Validate one graph with the SDK: SHACL plus the closed-world concept
    check, with RDFS inference, against the extensions the graph uses.

    Returns a receipt. `conforms` is True only when every stage ran and passed.
    `publishable` also needs the SDK to be the pinned commit and no local
    ontology file: a term declared only on this machine is an upstream change
    proposal, not a release-line result.
    """
    from case_uco.validation import validate_graph_file

    _use_venv_validator()
    root = sdk_root()
    path = Path(graph_path).resolve()
    selected = sorted(extensions) if extensions is not None else extensions_used(path, root)
    status = pin_status()
    report = validate_graph_file(
        path,
        extensions=selected or None,
        profiles=list(profiles),
        strict_concepts=True,
        force_rdfs_inference=True,
        project_root=root,
        extra_ontology_graphs=extra_ontology_graphs,
        timeout_seconds=timeout_seconds,
    )
    conforms = report.conforms is True and report.verification_status == "complete"
    receipt: dict[str, Any] = {
        "schema": RECEIPT_SCHEMA,
        "graph": path.name,
        "graph_sha256": sha256_file(path),
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "conforms": conforms,
        "publishable": conforms and status["pinned"] and not extra_ontology_graphs,
        "violation_count": report.violation_count,
        "verification_status": report.verification_status,
        "stages": dict(report.stage_status),
        "sdk": {
            "repo": SDK_REPO,
            "tag": SDK_TAG if status["pinned"] else None,
            "commit": status["commit"],
            "pinned": status["pinned"],
            "case_uco": status["case_uco"],
            "case_utils": status["case_utils"],
            "pyshacl": status["pyshacl"],
            "rdflib": status["rdflib"],
        },
        "extensions": dict(report.extension_versions) or {name: None for name in selected},
        "profiles": list(report.selected_profiles) or list(profiles),
        "bundle_fingerprint": report.bundle_fingerprint,
        "local_ontology_graphs": [Path(p).name for p in extra_ontology_graphs or []],
    }
    if report.undeclared_concepts:
        receipt["undeclared_concepts"] = list(report.undeclared_concepts)
    if report.role_mismatches:
        receipt["role_mismatches"] = [list(item) for item in report.role_mismatches]
    if report.verification_errors:
        receipt["verification_errors"] = list(report.verification_errors)
    if not conforms:
        receipt["messages"] = violation_messages(report.validator_diagnostics)
    return receipt


def violation_messages(diagnostics: str, limit: int = 12) -> list[dict[str, Any]]:
    """Distinct SHACL violation and warning messages with counts, most
    frequent first. `sh:Info` results (UUID-suffix suggestions) are left out."""
    counts: dict[tuple[str, str], int] = {}
    severity = ""
    for line in diagnostics.splitlines():
        text = line.strip()
        if text.startswith("Severity:"):
            severity = text[len("Severity:"):].strip()
        elif text.startswith("Message:") and severity in {"sh:Violation", "sh:Warning"}:
            key = (severity, text[len("Message:"):].strip())
            counts[key] = counts.get(key, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [
        {"severity": severity, "message": message, "count": count}
        for (severity, message), count in ranked[:limit]
    ]


def receipt_path(graph_path: str | Path) -> Path:
    path = Path(graph_path)
    return path.with_name(path.name + RECEIPT_SUFFIX)


def write_receipt(graph_path: str | Path, receipt: dict[str, Any]) -> Path:
    target = receipt_path(graph_path)
    target.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return target
