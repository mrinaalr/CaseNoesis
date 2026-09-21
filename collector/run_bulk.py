#!/usr/bin/env python3
"""Bulk public-record harvest for CaseNoesis (NHSR #8252).

Press: DOJ News API via harvest_doj_press.py (free, no key).
Court: CourtListener / RECAP only — never PACER purchase.

Writes ``data/collected/{press_releases,pacer,manifests}/<domain>/``.
Does not auto-ingest.

usage:
    python3 collector/run_bulk.py --press-count 100 --court-count 5
    python3 collector/run_bulk.py --press-count 1000 --court-count 50
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
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
        "pacer": root / "pacer" / domain,
        "manifests": root / "manifests" / domain,
    }
    for p in paths.values():
        p.mkdir(parents=True, exist_ok=True)
    return paths


def _promote_individuals(tmp_dir: Path, records: list[dict], dest_dir: Path) -> list[Path]:
    """Copy build_press_pdf tmp/{index}_{sha16}.pdf → press_releases/{domain}/{slug}.pdf."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    out: list[Path] = []
    for i, rec in enumerate(records, start=1):
        url = rec.get("source_url") or ""
        if not url:
            continue
        h = hashlib.sha256(url.strip().encode("utf-8")).hexdigest()[:16]
        src = tmp_dir / f"{i:04d}_{h}.pdf"
        if not src.is_file():
            matches = list(tmp_dir.glob(f"*_{h}.pdf"))
            src = matches[0] if matches else None
        if src is None or not src.is_file():
            continue
        dest = dest_dir / f"{_slug_for(url, rec.get('title') or '')}.pdf"
        shutil.copy2(src, dest)
        rec["pdf"] = str(dest)
        out.append(dest)
    return out


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
    base, rem = divmod(max(0, total), n)
    return [base + (1 if i < rem else 0) for i in range(n)]


def harvest_domain(
    *,
    python: str,
    profile_name: str,
    max_keep: int,
    out_dir: Path,
    keep_early: bool,
) -> dict:
    if max_keep <= 0:
        return {"ok": True, "kept": 0, "records": [], "profile": profile_name}
    profile = _load_profile(profile_name)
    cmd = [
        python,
        str(HERE / "harvest_doj_press.py"),
        "--profile",
        profile_name,
        "--max-keep",
        str(max_keep),
        "--out-dir",
        str(out_dir),
    ]
    if profile.get("skip_cac", True):
        cmd.append("--skip-cac")
    if keep_early:
        cmd.append("--keep-early")
    # 100 records can page several title terms; stay under API 4 req/s.
    timeout = max(300, max_keep * 12)
    proc = _run(cmd, cwd=HERE, timeout=timeout)
    slug = profile.get("slug") or f"doj_{profile_name}"
    resolved = out_dir / f"{slug}_resolved.json"
    records: list[dict] = []
    if resolved.is_file():
        try:
            records = json.loads(resolved.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            records = []
    ok = proc.returncode == 0 and bool(records)
    if not ok:
        print(proc.stderr[-2000:] if proc.stderr else proc.stdout[-1000:], file=sys.stderr)
    return {
        "ok": ok,
        "exit_code": proc.returncode,
        "profile": profile_name,
        "slug": slug,
        "resolved_json": str(resolved) if resolved.is_file() else None,
        "kept": len(records),
        "records": records,
        "stderr_tail": (proc.stderr or "")[-1500:],
    }


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
    proc = _run(cmd, cwd=HERE, timeout=max(300, limit * 5))
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
        "title": rec.get("title"),
        "source_url": rec.get("source_url") or rec.get("absolute_url"),
        "pub_date": rec.get("pub_date") or rec.get("date_filed"),
        "agency": rec.get("agency") or rec.get("court"),
        "pdf": rec.get("pdf"),
        "record": rec,
    }
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="CaseNoesis bulk public-record harvest (free sources only).")
    ap.add_argument("--press-count", type=int, default=100, help="Target exploitation press records.")
    ap.add_argument("--court-count", type=int, default=5, help="Target free RECAP court PDFs.")
    ap.add_argument(
        "--domains",
        default=",".join(DEFAULT_DOMAINS),
        help="Comma-separated domain profiles (fraud,trafficking,cyber,csea).",
    )
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=COLLECTED_ROOT,
        help="Root of data/collected (press_releases/, pacer/, manifests/).",
    )
    ap.add_argument("--no-pdf", action="store_true", help="Skip press PDFs (JSON only).")
    ap.add_argument("--skip-court", action="store_true")
    args = ap.parse_args()

    domains = [d.strip() for d in args.domains.split(",") if d.strip()]
    if not domains:
        sys.exit("need at least one domain")
    root = args.out_dir if args.out_dir.is_absolute() else (REPO / args.out_dir)
    (root / "press_releases").mkdir(parents=True, exist_ok=True)
    (root / "pacer").mkdir(parents=True, exist_ok=True)
    (root / "manifests").mkdir(parents=True, exist_ok=True)

    python = sys.executable
    sys.path.insert(0, str(HERE))
    shares = _split_counts(args.press_count, len(domains))
    court_shares = _split_counts(args.court_count, len(domains))
    harvests: list[dict] = []
    domain_bundles: dict[str, list[dict]] = {d: [] for d in domains}
    seen_urls: set[str] = set()
    pdf_by_domain: dict[str, dict] = {}
    court_by_domain: dict[str, list[dict]] = {d: [] for d in domains}

    for domain, n in zip(domains, shares):
        dirs = _dirs(root, domain)
        print(f"\n=== harvest {domain} target={n} → {dirs['manifests']} ===", file=sys.stderr)
        result = harvest_domain(
            python=python,
            profile_name=domain,
            max_keep=n,
            out_dir=dirs["manifests"],
            keep_early=True,
        )
        harvests.append({k: v for k, v in result.items() if k != "records"})
        for rec in result.get("records") or []:
            rec["domain"] = domain
            url = rec.get("source_url") or ""
            if url and url not in seen_urls:
                seen_urls.add(url)
                domain_bundles[domain].append(rec)

    all_records = [r for d in domains for r in domain_bundles[d]]
    shortfall = args.press_count - len(all_records)
    if shortfall > 0:
        fill_domain = domains[0]
        dirs = _dirs(root, fill_domain)
        print(f"\n=== backfill {shortfall} via noesis → {fill_domain} ===", file=sys.stderr)
        extra = harvest_domain(
            python=python,
            profile_name="noesis",
            max_keep=shortfall + 10,
            out_dir=dirs["manifests"],
            keep_early=True,
        )
        harvests.append({k: v for k, v in extra.items() if k != "records"})
        for rec in extra.get("records") or []:
            rec["domain"] = rec.get("domain") or fill_domain
            url = rec.get("source_url") or ""
            if url and url not in seen_urls:
                seen_urls.add(url)
                domain_bundles[fill_domain].append(rec)
            if sum(len(v) for v in domain_bundles.values()) >= args.press_count:
                break

    # Cap per domain to share, then leftover into first domain.
    kept: dict[str, list[dict]] = {d: domain_bundles[d][: shares[i]] for i, d in enumerate(domains)}
    leftover = args.press_count - sum(len(v) for v in kept.values())
    if leftover > 0:
        extra_pool = domain_bundles[domains[0]][len(kept[domains[0]]) :]
        kept[domains[0]].extend(extra_pool[:leftover])

    if not args.no_pdf:
        for domain, recs in kept.items():
            if not recs:
                continue
            dirs = _dirs(root, domain)
            resolved = dirs["manifests"] / f"{domain}_resolved.json"
            resolved.write_text(json.dumps(recs, indent=2), encoding="utf-8")
            merged_name = f"{domain.upper()}_All.pdf"
            try:
                info = build_pdf(
                    python=python,
                    doj_file=resolved,
                    out_dir=dirs["press"],
                    out_name=merged_name,
                    limit=len(recs),
                )
            except Exception as exc:  # noqa: BLE001
                info = {"ok": False, "error": str(exc)}
            individuals = []
            if info.get("ok"):
                individuals = _promote_individuals(
                    dirs["press"] / "tmp", recs, dirs["press"]
                )
            for rec in recs:
                slug = _slug_for(rec.get("source_url") or "", rec.get("title") or "")
                _write_record_manifest(
                    dirs["manifests"] / f"{slug}.json", rec, domain=domain, kind="press"
                )
            domain_summary = {
                "domain": domain,
                "press_kept": len(recs),
                "individuals": [str(p) for p in individuals],
                "merged_pdf": info.get("pdf_path"),
                "resolved_json": str(resolved),
            }
            (dirs["manifests"] / "MANIFEST.json").write_text(
                json.dumps(domain_summary, indent=2, default=str), encoding="utf-8"
            )
            pdf_by_domain[domain] = {**info, "individuals": len(individuals)}

    if not args.skip_court and args.court_count > 0:
        from court_records import collect_free_court_records, load_token_from_env_files

        load_token_from_env_files(
            [
                REPO / ".env",
                REPO.parent / "CaseLinker" / ".env",
            ]
        )
        for i, (domain, n_court) in enumerate(zip(domains, court_shares)):
            if n_court <= 0:
                continue
            if i:
                time.sleep(3)
            dirs = _dirs(root, domain)
            queries = list(_load_profile(domain).get("court_queries") or [])[:4]
            for r in (kept.get(domain) or [])[:2]:
                title = (r.get("title") or "").strip()
                if title:
                    queries.append(title[:80])
            recs = collect_free_court_records(
                queries, dest_dir=dirs["pacer"], max_records=n_court, per_query=3
            )
            for rec in recs:
                rec["domain"] = domain
                pdf = (rec.get("download") or {}).get("path")
                rec["pdf"] = pdf
                slug = _slug_for(
                    rec.get("absolute_url") or rec.get("docket_number") or "docket",
                    rec.get("case_name") or "",
                )
                _write_record_manifest(
                    dirs["manifests"] / f"court_{slug}.json",
                    rec,
                    domain=domain,
                    kind="court",
                )
            court_by_domain[domain] = recs

    all_press = [r for d in domains for r in kept.get(d) or []]
    all_court = [c for d in domains for c in court_by_domain.get(d) or []]
    collection = {
        "nhsr": NHSR,
        "nhsr_title": NHSR_TITLE,
        "cost": "free",
        "pacer_purchases": 0,
        "observed": True,
        "inferred": False,
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "layout": {
            "press_releases": str(root / "press_releases" / "<domain>" / "{slug}.pdf + DOMAIN_All.pdf"),
            "pacer": str(root / "pacer" / "<domain>"),
            "manifests": str(root / "manifests" / "<domain>"),
        },
        "press_target": args.press_count,
        "press_kept": len(all_press),
        "court_target": args.court_count,
        "court_kept": len(all_court),
        "domains": {
            d: {
                "press": len(kept.get(d) or []),
                "court": len(court_by_domain.get(d) or []),
                "merged_pdf": (pdf_by_domain.get(d) or {}).get("pdf_path"),
                "individuals": (pdf_by_domain.get(d) or {}).get("individuals"),
            }
            for d in domains
        },
        "harvests": harvests,
        "pdf_by_domain": pdf_by_domain,
        "ingest_hint": (
            "Outputs do not auto-ingest. Example: "
            f"python3 src/main.py {root / 'press_releases' / 'fraud' / 'FRAUD_All.pdf'}"
        ),
    }
    collection_path = root / "manifests" / "COLLECTION.json"
    collection_path.write_text(json.dumps(collection, indent=2, default=str), encoding="utf-8")
    print(json.dumps(
        {
            "nhsr": collection["nhsr"],
            "cost": collection["cost"],
            "press_kept": collection["press_kept"],
            "court_kept": collection["court_kept"],
            "domains": collection["domains"],
            "collection": str(collection_path),
        },
        indent=2,
        default=str,
    ))
    print(f"Wrote {collection_path}")
    if len(all_press) < args.press_count:
        sys.exit(f"press shortfall: {len(all_press)}/{args.press_count}")
    if not args.skip_court and len(all_court) < args.court_count:
        print(
            f"warning: court shortfall {len(all_court)}/{args.court_count} "
            "(RECAP rate limit or no free filings). Press harvest is complete.",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
