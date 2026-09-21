#!/usr/bin/env python3
"""Sequential public-record harvest for CaseNoesis (NHSR #8252).

Press: DOJ News API via harvest_doj_press.py (free, no key). One HTTP page at a
time; each kept record is written (JSON + PDF) before the next.
Court: CourtListener / RECAP only — never PACER purchase. One PDF at a time.

Writes ``data/collected/{press_releases,recap,manifests}/<domain>/``.
Does not auto-ingest.

usage:
    python3 collector/run_bulk.py --one
    python3 collector/run_bulk.py --press-count 1000 --court-count 50
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent

NHSR = "UMass HRPO NHSR #8252 (16 Sep 2026)"
NHSR_TITLE = "On the Mechanics of Exploitation: State-Machine Modeling of Public Exploitation-Related Case Records"

DEFAULT_DOMAINS = ("fraud", "trafficking", "cyber", "csea")
COLLECTED_ROOT = REPO / "data" / "collected"


def _slug_for(url: str, title: str = "") -> str:
    tail = url.rstrip("/").split("/")[-1].lower()
    slug = re.sub(r"[^a-z0-9\-]+", "-", tail).strip("-")
    if not slug:
        slug = re.sub(r"[^a-z0-9\-]+", "-", (title or "case").lower())[:70].strip("-")
    return slug[:70] or "case"


def _dirs(root: Path, domain: str) -> dict[str, Path]:
    paths = {
        "press": root / "press_releases" / domain,
        "recap": root / "recap" / domain,
        "manifests": root / "manifests" / domain,
    }
    for p in paths.values():
        p.mkdir(parents=True, exist_ok=True)
    return paths


def _load_profile(name: str) -> dict:
    path = HERE / "profiles" / f"{name}.json"
    if not path.is_file():
        sys.exit(f"unknown domain profile: {name} ({path})")
    return json.loads(path.read_text(encoding="utf-8"))


def _run(cmd: list[str], *, cwd: Path, timeout: int) -> subprocess.CompletedProcess:
    print("+", " ".join(cmd), file=sys.stderr)
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _split_counts(total: int, n: int) -> list[int]:
    if n <= 0:
        return []
    base, remnant = divmod(max(0, total), n)
    return [base + (1 if i < remnant else 0) for i in range(n)]


def harvest_one(
    *,
    python: str,
    profile_name: str,
    out_dir: Path,
    skip_url_file: Path,
    keep_early: bool,
) -> dict:
    """Harvest a single new press record for one domain (max-keep 1)."""
    profile = _load_profile(profile_name)
    one_dir = out_dir / "_one"
    one_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        python,
        str(HERE / "harvest_doj_press.py"),
        "--profile",
        profile_name,
        "--max-keep",
        "1",
        "--out-dir",
        str(one_dir),
        "--slug",
        "one",
        "--skip-url-file",
        str(skip_url_file),
    ]
    if profile.get("skip_cac", True):
        cmd.append("--skip-cac")
    if keep_early:
        cmd.append("--keep-early")
    try:
        proc = _run(cmd, cwd=HERE, timeout=240)
        code = proc.returncode
        stderr = proc.stderr or ""
    except subprocess.TimeoutExpired as exc:
        code = 124
        stderr = (exc.stderr or "") if isinstance(exc.stderr, str) else ""
    resolved = one_dir / "one_resolved.json"
    records: list[dict] = []
    if resolved.is_file():
        try:
            records = json.loads(resolved.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            records = []
    rec = records[0] if records else None
    return {
        "ok": rec is not None,
        "exit_code": code,
        "profile": profile_name,
        "record": rec,
        "stderr_tail": stderr[-1500:],
    }


def harvest_many(
    *,
    python: str,
    profile_name: str,
    max_keep: int,
    out_dir: Path,
    skip_url_file: Path,
    keep_early: bool,
) -> dict:
    """Page the DOJ API sequentially until max_keep new records. One HTTP request at a time."""
    if max_keep <= 0:
        return {"ok": True, "records": [], "profile": profile_name}
    profile = _load_profile(profile_name)
    batch_dir = out_dir / "_batch"
    batch_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        python,
        str(HERE / "harvest_doj_press.py"),
        "--profile",
        profile_name,
        "--max-keep",
        str(max_keep),
        "--out-dir",
        str(batch_dir),
        "--slug",
        "batch",
        "--skip-url-file",
        str(skip_url_file),
    ]
    if profile.get("skip_cac", True):
        cmd.append("--skip-cac")
    if keep_early:
        cmd.append("--keep-early")
    try:
        proc = _run(cmd, cwd=HERE, timeout=max(600, max_keep * 25))
        code = proc.returncode
        stderr = proc.stderr or ""
        stdout = proc.stdout or ""
    except subprocess.TimeoutExpired as exc:
        code = 124
        stderr = (exc.stderr or "") if isinstance(exc.stderr, str) else ""
        stdout = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        print("harvest_many timed out; using whatever resolved JSON exists", file=sys.stderr)
    resolved = batch_dir / "batch_resolved.json"
    records: list[dict] = []
    if resolved.is_file():
        try:
            loaded = json.loads(resolved.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                records = loaded
        except json.JSONDecodeError:
            records = []
    if code != 0:
        print((stderr or stdout)[-2000:], file=sys.stderr)
    return {
        "ok": bool(records),
        "exit_code": code,
        "profile": profile_name,
        "records": records,
        "stderr_tail": stderr[-1500:],
    }


def _iter_kind(root: Path, domain: str, kind: str) -> list[dict]:
    folder = root / "manifests" / domain
    out: list[dict] = []
    if not folder.is_dir():
        return out
    for path in sorted(folder.glob("*.json")):
        if path.name in {"MANIFEST.json", "COLLECTION.json"}:
            continue
        if "resolved" in path.name or "harvest" in path.name:
            continue
        if kind == "court" and not path.name.startswith("court_"):
            continue
        if kind == "press" and path.name.startswith("court_"):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        if data.get("kind") == kind:
            out.append(data)
    return out


def _press_pdf_count(root: Path, domain: str) -> int:
    folder = root / "press_releases" / domain
    if not folder.is_dir():
        return 0
    return sum(
        1
        for p in folder.glob("*.pdf")
        if p.is_file() and not p.name.endswith("_All.pdf")
    )


def _court_pdf_count(root: Path, domain: str) -> int:
    folder = root / "recap" / domain
    if not folder.is_dir():
        return 0
    return sum(1 for p in folder.glob("*.pdf") if p.is_file())


def collected_press_urls(root: Path) -> set[str]:
    urls: set[str] = set()
    man_root = root / "manifests"
    if not man_root.is_dir():
        return urls

    def _add(obj: object) -> None:
        if isinstance(obj, dict):
            if obj.get("kind") == "court":
                return
            url = obj.get("source_url") or (obj.get("record") or {}).get("source_url")
            if url:
                urls.add(str(url).strip())
            return
        if isinstance(obj, list):
            for item in obj:
                _add(item)

    for path in man_root.rglob("*.json"):
        if path.name in {"COLLECTION.json", "MANIFEST.json"}:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        _add(data)
    return urls


def _write_skip_url_file(root: Path) -> Path:
    path = root / "manifests" / "_skip_urls.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    urls = sorted(collected_press_urls(root))
    path.write_text("\n".join(urls) + ("\n" if urls else ""), encoding="utf-8")
    return path


def _append_resolved(path: Path, rec: dict) -> None:
    records: list[dict] = []
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                records = loaded
        except json.JSONDecodeError:
            records = []
    url = rec.get("source_url")
    if url and any(r.get("source_url") == url for r in records):
        return
    records.append(rec)
    path.write_text(json.dumps(records, indent=2, default=str), encoding="utf-8")


def write_collection_json(root: Path, domains: list[str], *, press_target: int, court_target: int) -> Path:
    stats: dict[str, dict] = {}
    press_kept = 0
    court_kept = 0
    for domain in domains:
        press = _iter_kind(root, domain, "press")
        court = _iter_kind(root, domain, "court")
        n_press = max(len(press), _press_pdf_count(root, domain))
        n_court = max(len(court), _court_pdf_count(root, domain))
        merged = root / "press_releases" / domain / f"{domain.upper()}_All.pdf"
        stats[domain] = {
            "press": n_press,
            "court": n_court,
            "merged_pdf": str(merged) if merged.is_file() else None,
            "individuals": n_press,
        }
        press_kept += n_press
        court_kept += n_court
    payload = {
        "nhsr": NHSR,
        "nhsr_title": NHSR_TITLE,
        "cost": "free",
        "pacer_purchases": 0,
        "observed": True,
        "inferred": False,
        "mode": "sequential",
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "layout": {
            "press_releases": str(root / "press_releases" / "<domain>" / "{slug}.pdf"),
            "recap": str(root / "recap" / "<domain>"),
            "manifests": str(root / "manifests" / "<domain>"),
        },
        "press_target": press_target,
        "press_kept": press_kept,
        "court_target": court_target,
        "court_kept": court_kept,
        "domains": stats,
    }
    path = root / "manifests" / "COLLECTION.json"
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path


def build_pdf(*, python: str, doj_file: Path, out_dir: Path, out_name: str, limit: int) -> dict:
    from runtime import python_with_pypdf

    pdf_py = python_with_pypdf() or python
    cmd = [
        pdf_py,
        str(HERE / "build_press_pdf.py"),
        "--doj-file",
        str(doj_file),
        "--out-dir",
        str(out_dir),
        "--out-name",
        out_name,
        "--limit",
        str(limit),
    ]
    proc = _run(cmd, cwd=HERE, timeout=max(300, limit * 8))
    pdf_path = out_dir / out_name
    return {
        "ok": proc.returncode == 0 and pdf_path.is_file(),
        "exit_code": proc.returncode,
        "python": pdf_py,
        "pdf_path": str(pdf_path) if pdf_path.is_file() else None,
        "pdf_bytes": pdf_path.stat().st_size if pdf_path.is_file() else 0,
        "tmp_dir": str(out_dir / "tmp"),
        "stderr_tail": (proc.stderr or "")[-800:],
        "stdout_tail": (proc.stdout or "")[-800:],
    }


def _write_record_manifest(path: Path, rec: dict, *, domain: str, kind: str) -> None:
    payload = {
        "nhsr": NHSR,
        "cost": "free",
        "pacer_purchases": 0,
        "observed": True,
        "inferred": False,
        "domain": domain,
        "kind": kind,
        "title": rec.get("title") or rec.get("case_name"),
        "source_url": rec.get("source_url") or rec.get("absolute_url"),
        "pub_date": rec.get("pub_date") or rec.get("date_filed"),
        "agency": rec.get("agency") or rec.get("court"),
        "pdf": rec.get("pdf"),
        "record": rec,
    }
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def collect_one_press(*, python: str, domain: str, root: Path, no_pdf: bool = False) -> dict:
    dirs = _dirs(root, domain)
    skip_file = _write_skip_url_file(root)
    harvested = harvest_one(
        python=python,
        profile_name=domain,
        out_dir=dirs["manifests"],
        skip_url_file=skip_file,
        keep_early=True,
    )
    rec = harvested.get("record")
    if not harvested.get("ok") or not rec:
        return {
            "ok": False,
            "kind": "press",
            "domain": domain,
            "error": "harvest returned no new record",
            "stderr_tail": harvested.get("stderr_tail"),
            "pacer_purchases": 0,
            "cost": "free",
        }
    return _persist_press_record(python=python, domain=domain, root=root, rec=rec, no_pdf=no_pdf)


def collect_one_court(*, domain: str, root: Path) -> dict:
    from court_records import collect_free_court_records, load_token_from_env_files

    load_token_from_env_files([REPO / ".env", REPO.parent / "CaseLinker" / ".env"])
    dirs = _dirs(root, domain)
    queries = list(_load_profile(domain).get("court_queries") or [])
    for rec in _iter_kind(root, domain, "press")[:40]:
        title = (rec.get("title") or "").strip()
        if title:
            queries.append(title[:80])
    before = {p.name for p in dirs["recap"].glob("*.pdf")}
    recs = collect_free_court_records(
        queries, dest_dir=dirs["recap"], max_records=1, per_query=8
    )
    new = [
        r
        for r in recs
        if Path((r.get("download") or {}).get("path") or "").name not in before
        and (r.get("download") or {}).get("ok")
    ]
    if not new:
        return {
            "ok": False,
            "kind": "court",
            "domain": domain,
            "error": "no new free RECAP PDF",
            "pacer_purchases": 0,
            "cost": "free",
        }
    rec = new[0]
    rec["domain"] = domain
    rec["pdf"] = (rec.get("download") or {}).get("path")
    slug = _slug_for(
        rec.get("absolute_url") or rec.get("docket_number") or "docket",
        rec.get("case_name") or "",
    )
    _write_record_manifest(
        dirs["manifests"] / f"court_{slug}.json", rec, domain=domain, kind="court"
    )
    return {
        "ok": True,
        "kind": "court",
        "domain": domain,
        "title": rec.get("case_name"),
        "source_url": rec.get("absolute_url"),
        "pdf": rec.get("pdf"),
        "pacer_purchases": 0,
        "cost": "free",
    }


def _persist_press_record(*, python: str, domain: str, root: Path, rec: dict, no_pdf: bool) -> dict:
    dirs = _dirs(root, domain)
    rec = dict(rec)
    rec["domain"] = domain
    slug = _slug_for(rec.get("source_url") or "", rec.get("title") or "")
    man_path = dirs["manifests"] / f"{slug}.json"
    pdf_path = dirs["press"] / f"{slug}.pdf"
    if man_path.is_file() and (no_pdf or pdf_path.is_file()):
        return {
            "ok": True,
            "skipped": True,
            "kind": "press",
            "domain": domain,
            "source_url": rec.get("source_url"),
            "pacer_purchases": 0,
            "cost": "free",
        }
    if not no_pdf and not pdf_path.is_file():
        one_json = dirs["manifests"] / "_one_rec.json"
        one_json.write_text(json.dumps([rec], indent=2), encoding="utf-8")
        info = build_pdf(
            python=python,
            doj_file=one_json,
            out_dir=dirs["press"],
            out_name=f"{slug}.pdf",
            limit=1,
        )
        rec["pdf"] = str(pdf_path) if info.get("ok") else None
    elif pdf_path.is_file():
        rec["pdf"] = str(pdf_path)
    _append_resolved(dirs["manifests"] / f"{domain}_resolved.json", rec)
    _write_record_manifest(man_path, rec, domain=domain, kind="press")
    return {
        "ok": True,
        "kind": "press",
        "domain": domain,
        "title": rec.get("title"),
        "source_url": rec.get("source_url"),
        "pdf": rec.get("pdf"),
        "pacer_purchases": 0,
        "cost": "free",
    }


def main() -> None:
    ap = argparse.ArgumentParser(
        description="CaseNoesis harvest. DOJ API is sequential (one page at a time). "
        "Each kept press record is written before the next PDF. Never purchases PACER."
    )
    ap.add_argument("--press-count", type=int, default=1, help="Target total press records on disk.")
    ap.add_argument("--court-count", type=int, default=0, help="Target total free RECAP PDFs on disk.")
    ap.add_argument(
        "--domains",
        default=",".join(DEFAULT_DOMAINS),
        help="Comma-separated domain profiles (fraud,trafficking,cyber,csea).",
    )
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=COLLECTED_ROOT,
        help="Root of data/collected (press_releases/, recap/, manifests/).",
    )
    ap.add_argument("--no-pdf", action="store_true", help="Skip press PDFs (JSON only).")
    ap.add_argument("--skip-court", action="store_true")
    ap.add_argument("--one", action="store_true", help="Pull a single new press record and exit.")
    ap.add_argument("--one-court", action="store_true", help="Pull a single new free RECAP PDF and exit.")
    args = ap.parse_args()

    domains = [d.strip() for d in args.domains.split(",") if d.strip()]
    if not domains:
        sys.exit("need at least one domain")
    root = args.out_dir if args.out_dir.is_absolute() else (REPO / args.out_dir)
    (root / "press_releases").mkdir(parents=True, exist_ok=True)
    (root / "recap").mkdir(parents=True, exist_ok=True)
    (root / "manifests").mkdir(parents=True, exist_ok=True)

    python = sys.executable
    sys.path.insert(0, str(HERE))
    prior_press, prior_court = 1000, 50
    prior_path = root / "manifests" / "COLLECTION.json"
    if prior_path.is_file():
        try:
            prior = json.loads(prior_path.read_text(encoding="utf-8"))
            prior_press = int(prior.get("press_target") or prior_press)
            prior_court = int(prior.get("court_target") or prior_court)
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    if args.one:
        press_target = max(args.press_count, prior_press)
        court_target = max(args.court_count, prior_court)
    elif args.one_court:
        press_target = max(args.press_count, prior_press)
        court_target = max(args.court_count, prior_court, 1)
    else:
        press_target = args.press_count
        court_target = 0 if args.skip_court else args.court_count
    shares = _split_counts(press_target, len(domains))
    court_shares = _split_counts(court_target, len(domains))

    if args.one:
        counts = {d: max(len(_iter_kind(root, d, "press")), _press_pdf_count(root, d)) for d in domains}
        domain = min(domains, key=lambda d: counts[d] / max(shares[domains.index(d)], 1))
        result = collect_one_press(python=python, domain=domain, root=root, no_pdf=args.no_pdf)
        write_collection_json(root, domains, press_target=press_target, court_target=court_target)
        print(json.dumps(result, indent=2, default=str))
        if not result.get("ok"):
            sys.exit(1)
        return

    if args.one_court:
        counts = {d: max(len(_iter_kind(root, d, "court")), _court_pdf_count(root, d)) for d in domains}
        domain = min(domains, key=lambda d: counts[d] / max(court_shares[domains.index(d)], 1))
        result = collect_one_court(domain=domain, root=root)
        write_collection_json(root, domains, press_target=press_target, court_target=court_target)
        print(json.dumps(result, indent=2, default=str))
        if not result.get("ok"):
            sys.exit(1)
        return

    write_collection_json(root, domains, press_target=press_target, court_target=court_target)

    for domain, n in zip(domains, shares):
        have = max(len(_iter_kind(root, domain, "press")), _press_pdf_count(root, domain))
        need = max(0, n - have)
        print(f"\n=== {domain} press have={have} need={need} target={n} ===", file=sys.stderr)
        if need <= 0:
            continue
        skip_file = _write_skip_url_file(root)
        dirs = _dirs(root, domain)
        harvested = harvest_many(
            python=python,
            profile_name=domain,
            max_keep=need,
            out_dir=dirs["manifests"],
            skip_url_file=skip_file,
            keep_early=True,
        )
        for rec in harvested.get("records") or []:
            _persist_press_record(
                python=python, domain=domain, root=root, rec=rec, no_pdf=args.no_pdf
            )
            write_collection_json(root, domains, press_target=press_target, court_target=court_target)

    if court_target > 0:
        for domain, n_court in zip(domains, court_shares):
            have = max(len(_iter_kind(root, domain, "court")), _court_pdf_count(root, domain))
            need = max(0, n_court - have)
            print(f"\n=== {domain} recap have={have} need={need} target={n_court} ===", file=sys.stderr)
            for _ in range(need):
                result = collect_one_court(domain=domain, root=root)
                write_collection_json(root, domains, press_target=press_target, court_target=court_target)
                if not result.get("ok"):
                    print(result.get("error"), file=sys.stderr)
                    break
                print(
                    f"  recap +1 {domain}: {result.get('title')}",
                    file=sys.stderr,
                )
                time.sleep(2)

    collection_path = write_collection_json(
        root, domains, press_target=press_target, court_target=court_target
    )
    collection = json.loads(collection_path.read_text(encoding="utf-8"))
    print(json.dumps(
        {
            "nhsr": collection["nhsr"],
            "cost": collection["cost"],
            "mode": "sequential",
            "pacer_purchases": 0,
            "press_kept": collection["press_kept"],
            "court_kept": collection["court_kept"],
            "domains": collection["domains"],
            "collection": str(collection_path),
        },
        indent=2,
        default=str,
    ))
    print(f"Wrote {collection_path}")
    if collection["press_kept"] < press_target:
        sys.exit(f"press shortfall: {collection['press_kept']}/{press_target}")
    if court_target and collection["court_kept"] < court_target:
        print(
            f"warning: court shortfall {collection['court_kept']}/{court_target} "
            "(RECAP rate limit or no free filings).",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
