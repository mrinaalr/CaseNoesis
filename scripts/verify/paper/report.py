"""Render claims.md (catalog) and paper_tested.md (verification report)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from claims_registry import Claim
from verifiers import VerifyResult

STATUS_EMOJI = {
    "pass": "✅",
    "fail": "❌",
    "warn": "⚠️",
    "external": "🌐",
    "literature": "📚",
    "skip": "⏭️",
}


def _esc(s: str) -> str:
    return s.replace("|", "\\|")


def render_claims_md(claims: list[Claim], paper_url: str) -> str:
    lines = [
        "# Paper claims catalog",
        "",
        f"_Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}_",
        "",
        f"Source: [Affordance, Misuse, Harm, Kill Chain]({paper_url})",
        "",
        f"**{len(claims)}** claims registered for verification.",
        "",
        "Legend: **bold** = headline / table stat picked for high scrutiny.",
        "",
    ]

    by_section: dict[str, list[Claim]] = {}
    for c in claims:
        by_section.setdefault(c.section, []).append(c)

    bold_picks = [c for c in claims if c.bold]
    lines.extend(
        [
            "## Bold / headline picks (why included)",
            "",
        ]
    )
    for c in bold_picks:
        lines.append(f"- **{c.id}** ({c.section}): {c.text}")
        if c.why:
            lines.append(f"  - _Why:_ {c.why}")
    lines.append("")

    for section in sorted(by_section, key=lambda s: (s.startswith("§"), s)):
        lines.append(f"## {section}")
        lines.append("")
        lines.append("| ID | Bold | Kind | Verify | Claim |")
        lines.append("|---|---|---|---|---|")
        for c in by_section[section]:
            lines.append(
                f"| `{c.id}` | {'**yes**' if c.bold else ''} | {c.kind} | {c.verify} | {_esc(c.text)} |"
            )
        lines.append("")

    return "\n".join(lines)


def render_paper_tested_md(
    claims: list[Claim],
    results: list[VerifyResult],
    paper_url: str,
    *,
    db_path: Path,
) -> str:
    rmap = {r.claim_id: r for r in results}
    counts: dict[str, int] = {}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1

    lines = [
        "# Paper tested — claim verification report",
        "",
        f"_Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}_",
        "",
        f"Paper: [Affordance, Misuse, Harm, Kill Chain]({paper_url})",
        f"Database: `{db_path}`",
        "",
        "## Summary",
        "",
        f"| Status | Count |",
        f"|---|---:|",
    ]
    for st in ("pass", "warn", "fail", "external", "literature", "skip"):
        if counts.get(st):
            lines.append(f"| {STATUS_EMOJI.get(st, '')} {st} | {counts[st]} |")
    lines.append("")

    fails = [c for c in claims if rmap.get(c.id, VerifyResult(c.id, "skip", "")).status == "fail"]
    warns = [c for c in claims if rmap.get(c.id, VerifyResult(c.id, "skip", "")).status == "warn"]
    if fails:
        lines.extend(["## Failures", ""])
        for c in fails:
            r = rmap[c.id]
            lines.append(f"### `{c.id}` — {c.section}")
            lines.append(f"- **Claim:** {c.text}")
            lines.append(f"- **Observed:** {r.observed or '—'}")
            lines.append(f"- **Expected:** {r.expected or c.expected or '—'}")
            lines.append(f"- **Detail:** {r.detail}")
            lines.append("")

    if warns:
        lines.extend(["## Warnings", ""])
        for c in warns:
            r = rmap[c.id]
            lines.append(f"### `{c.id}`")
            lines.append(f"- {c.text}")
            lines.append(f"- {r.detail}")
            if r.notes:
                for n in r.notes:
                    lines.append(f"  - {n}")
            lines.append("")

    lines.extend(["## Full results", "", "| Status | ID | Section | Observed | Expected | Source | Detail |", "|---|---|---|---|---|---|---|"])
    for c in claims:
        r = rmap.get(c.id)
        if not r:
            continue
        emoji = STATUS_EMOJI.get(r.status, "")
        lines.append(
            f"| {emoji} {r.status} | `{c.id}` | {c.section} | {_esc(r.observed)} | {_esc(r.expected or c.expected)} | {_esc(r.source)} | {_esc(r.detail)} |"
        )
    lines.append("")

    lines.extend(
        [
            "## External citations (manual follow-up)",
            "",
            "Claims marked **external** cite ICAC, NCMEC, Tech Coalition, Thorn, statutes, or GitHub — verify against primary publications, not the CaseLinker DB.",
            "",
        ]
    )
    for c in claims:
        r = rmap.get(c.id)
        if r and r.status == "external":
            lines.append(f"- `{c.id}`: {c.text} _(source: {c.citation or 'see paper'})_")
    lines.append("")

    return "\n".join(lines)


def write_reports(
    out_dir: Path,
    claims: list[Claim],
    results: list[VerifyResult],
    paper_url: str,
    db_path: Path,
) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    claims_path = out_dir / "claims.md"
    tested_path = out_dir / "paper_tested.md"
    claims_path.write_text(render_claims_md(claims, paper_url), encoding="utf-8")
    tested_path.write_text(
        render_paper_tested_md(claims, results, paper_url, db_path=db_path),
        encoding="utf-8",
    )
    return claims_path, tested_path
