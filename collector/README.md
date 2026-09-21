# CaseNoesis collector — personal collecting suite

**CaseLinker** (public): ICAC / CSEA press corpus, hosted demo, public MCP.  
**CaseNoesis** (this tree): personal super-engine for thousands of **heterogeneous** press releases and court records (fraud, trafficking, cyber, CSEA). NHSR **#8252**. CSEA/ICAC is one exploitation type among those — it is not filtered out.

Railway may host the CaseNoesis **website**. Collection and MCP stay **on your machine**. Outputs: `data/collected/{press_releases,recap,manifests}/<domain>/`. Nothing auto-ingests.

Ported from [CaseLinker `collector/`](https://github.com/mrinaalr/CaseLinker/tree/main/collector) and extended with domain profiles, grant/noise filters, bulk runner, and free RECAP.

`scripts/scraper/` is gone. This directory is the engine.

## What you get

```
listing page ──► fetch_source_urls.py ──► urls.txt ─┐
DOJ topic    ──► harvest_doj_press.py ──────────────┼─► resolve JSON ──► build_press_pdf.py ──► merged PDF
known URLs   ──► resolve_press_urls.py ─────────────┘
CourtListener ─► court_records.py ──► data/collected/recap/  (free, never PACER)
                 pacer/*.py ────────► data/PACER/           (paid opt-in)
                 run_bulk.py ──► N press + M court + MANIFEST.json
```

| Piece | Role |
|---|---|
| `profiles/{fraud,trafficking,cyber,csea,noesis}.json` | Title terms, require, court queries |
| `harvest_doj_press.py` | DOJ News API **discovery** (no justice.gov HTML; Akamai) |
| `resolve_press_urls.py` | Known URLs → API resolve or `mode: scrape` |
| `build_press_pdf.py` | Core engine: one ReportLab page per URL + provenance sidecars |
| `fetch_source_urls.py` | HTML / Squarespace / CSE / usa.gov / WordPress REST listings |
| `court_records.py` | Free RECAP search + download. Refuses PACER/ECF |
| `pacer/` | Paid-PACER opt-in: corpus eligibility, CourtListener fetch, cost log, facts→graphs. Writes `data/PACER/` |
| `run_bulk.py` | Sequential harvest to a press/court quota. Never purchases PACER. |
| `filter_merged_pdf.py` / `remove_pdf_pages_by_text.py` / `check_expand_novelty.py` | Quality gates |
| `PRESS_RELEASE_COLLECTION.md` | Extractors, DOJ API quirks, when to stop |

## Collect

```
python3 collector/run_bulk.py --press-count 100 --court-count 5 \
  --domains fraud,trafficking,cyber,csea \
  --out-dir data/collected
```

MCP `collect_record` pulls one public record from domain profiles. `download_free_recap` writes a known free RECAP filing. `collect_bulk` MCP default is 1 press so it does not time out (fine for small agent batches). Scale with CLI `--press-count 1000 --court-count 50`.

## Scale

```bash
python3 collector/run_bulk.py --press-count 1000 --court-count 50 \
  --domains fraud,trafficking,cyber,csea \
  --out-dir data/collected
```

Reload `.cursor/mcp.json` so `collect_record` / `collect_bulk` include CSEA. Do not send 1000 through MCP — the client times out.

## Agents

Local stdio only (`casenoesis_mcp`). Collector WRITE tools do not need FastAPI. Corpus analysis tools need `python3 run/main.py` on localhost.

- READ: `search_doj_press_releases`, `probe_press_url`, `search_courtlistener`, `list_free_recap_documents`, `resolve_free_recap_download`
- WRITE: `harvest_doj_press_topic`, `fetch_press_listing_urls`, `resolve_press_urls`, `build_press_pdf`, `collect_case_dual_path`, `collect_record`, `collect_bulk`, `download_free_recap`

## Ingest (separate on purpose)

```bash
python3 src/main.py data/collected/press_releases/fraud/FRAUD_All.pdf
```

## Install

```bash
pip install requests beautifulsoup4 reportlab pypdf pdfplumber httpx
```

Python 3.14 in `.venv` currently breaks `pyexpat` (`pypdf`). Harvest JSON and RECAP downloads still work. PDF merge uses `runtime.py` to pick a working interpreter.

## When to stop and ask a human

- Login, CAPTCHA, or a **paid** API (including PACER).
- robots.txt / terms block the scale you need.
- A JS bot-wall (same call already made for `justice.gov`).
