# ICAC / CAC source expansion queue

**Pipeline** (you provide the search/listing URL; agent runs the rest):

1. **Harvest** — `fetch_source_urls.py`, site API, or Jina (SPA sites). Query must be **`child sexual`** (not bare `child`).
2. **Dedupe** — drop URLs already in the merged `*_ICAC_All.pdf` (and obvious noise: grants, bills, DEI, index pages).
3. **Novelty gate** — `python3 scripts/scraper/check_expand_novelty.py --batch-pdf … --baseline *.pre_expand.bak --new-urls-file …` (must PASS before append). Uses **raw PDF URLs** (authoritative) plus body fingerprint vs baseline.
4. **Scrape** — `scrape_pdf.py --url-file …` → `batch.pdf`
5. **Append** — merge into repo-root `*_ICAC_All.pdf` (backup `*.pre_expand.bak` first).
6. **Re-check** — `check_expand_novelty.py --pdf … --baseline *.pre_expand.bak` (no double-dip in merged file).
7. **CAC verify (required)** — every batched case in the final merged PDF must pass `verify_cac.py`. **Print and save ALL failures** (not just a sample). Do not ingest until failures are removed or justified.
8. **Recommend** — next source from the table below.

### Step 7 — CAC verify on final PDF (all failures)

After append, run (repo root):

```bash
python3 scripts/verify/verify_cac.py \
  --pdf SCAG_ICAC_All.pdf \
  --source "SCAG ICAC" \
  --all-failures \
  --default-fail-csv
```

- **`--all-failures`** — prints **every** non-CAC case to the terminal in a numbered block (`case_id`, URL, preview).
- **`--default-fail-csv`** — writes a full machine-readable list to  
  `scripts/scraper/state/<pdf_stem>_cac_failures.csv` (one row per failure).
- Exit code **1** if any case fails → treat as blocking until you review the CSV.
- Optional: `--json scripts/scraper/state/<stem>_cac_verify.json` for automation.

Same pattern for each expanded source, e.g. Kentucky:

```bash
python3 scripts/verify/verify_cac.py \
  --pdf KYSP_ICAC_All.pdf \
  --source "KY SP" \
  --all-failures \
  --default-fail-csv
```

**What to do with failures:** grants, bills, fugitive manhunts, election/DEI press, etc. → delete those pages from the merged PDF (or exclude URL and re-merge). Borderline CAC wording may pass on manual read even if regex misses — note in CSV, don’t auto-delete.

**Already expanded (re-verify anytime):**

| PDF | Source key | Failures CSV (after `--default-fail-csv`) |
|-----|------------|-------------------------------------------|
| `SCAG_ICAC_All.pdf` | `SCAG ICAC` | `scripts/scraper/state/scag_icac_all_cac_failures.csv` |
| `KYSP_ICAC_All.pdf` | `KY SP` | `scripts/scraper/state/kysp_icac_all_cac_failures.csv` |

---

## Top priority (ICAC-only harvest → broaden with child sexual)

| Priority | Source key | Merged PDF | Child-sexual search URL | Notes |
|---------:|------------|------------|-------------------------|--------|
| ✅ done | SCAG ICAC | `SCAG_ICAC_All.pdf` | `https://www.scag.gov/search?s=child%20sexual&p={1-50}` | Paginated site search |
| ✅ done | **KY SP** | `KYSP_ICAC_All.pdf` | `https://www.kentuckystatepolice.ky.gov/news?searchTerm=child+sexual` | WP REST harvest — `harvest_ky_child_sexual.py` (+164 new) |
| 1 | ILLINOIS AG | `ILLNOISAG_ICAC_All.pdf` | `https://illinoisattorneygeneral.gov/site-search-page/press-releases/index?q=child+sexual` | |
| 2 | Idaho ICAC | `IDAHO_ICAC_All.pdf` | (newsroom ICAC category + child sexual site search) | |
| ✅ done | NJ AG | `NJOAG_ICAC_All.pdf` | `https://www.njoag.gov/?s=child+sexual` (+ `page/N`) | Jina search harvest; HTML extract + `_trim_njoag_body` (+116 novel) |
| 4 | SVICAC | `SVICAC_ICAC_All.pdf` | Silicon Valley ICAC news index | |
| 5 | SOUTH FLORIDA ICAC | `SOUTHFLORIDA_ICAC_All.pdf` | | |
| 6 | TBI ICAC | `TBI_ICAC_All.pdf` | `https://tbinewsroom.com/?s=child+sexual` | |
| ✅ done | NEWYORK SP | `NYSP_ICAC_All.pdf` | [NY State CSE](https://search.its.ny.gov/search/search.html?q=child+sexual+inurl:troopers.ny.gov&site=default_collection) + [newsroom keyword](https://troopers.ny.gov/nysp-newsroom?keyword=child+sexual) | `harvest_nysp_child_sexual.py` (+138 new) |
| 8 | FRESNO SO | `FRESNOSO_ICAC_All.pdf` | `https://www.fresnosheriff.org/search.html?q=child+sexual` | `--insecure` |
| 9 | LAPD | `LAPD_ICAC_All.pdf` | `https://www.lapdonline.org/?s=child+sexual` | |
| 10 | SJPD | `SJPD_ICAC_All.pdf` | `https://www.sjpd.org/services/automated-services/search?q=child+sexual` | |
| 11 | ANCHORAGE PD | `ANCHORAGEPD_ICAC_All.pdf` | `https://www.anchoragepolice.com/search?q=child+sexual` | Squarespace API in `fetch_source_urls.py` |
| 12 | WCSO | `WCSO_ICAC_All.pdf` | `https://washoesheriff.com/search_results.php?q=child+sexual` | |
| 13 | OSCEOLA SO | `OSCEOLA_ICAC_All.pdf` | `https://www.osceolasheriff.org/?s=child+sexual` | |
| 14 | LVMPD | `LVMPD_ICAC_All.pdf` | `https://www.lvmpd.com/.../search?q=child+sexual` | |
| 15 | SPD | `SPD_ICAC_All.pdf` | `https://spdblotter.seattle.gov/?s=child+sexual` | |
| 16 | SDPD | `SDPD_ICAC_All.pdf` | `https://www.sandiego.gov/search/site?search_api_fulltext=child+sexual` | |
| 17 | CSPD | `CSPD_ICAC_All.pdf` | `https://coloradosprings.gov/search?s=child+sexual` | |
| 18 | PA AG | `PAAG_ICAC_All.pdf` | `https://www.attorneygeneral.gov/taking-action-search-results/?swpquery=child+sexual` | |
| 19 | VT AG | `VTAG_ICAC_All.pdf` | Vermont AG child search | |
| 20 | OHIO AG | `OHIOAG_ICAC_All.pdf` | | |
| 21 | DE AG | `DEAG_ICAC_All.pdf` | | |
| 22 | UT AG | `UTAG_ICAC_All.pdf` | | |
| 23 | WA AG | `WAAG_ICAC_All.pdf` | | |
| 24 | OREGON DOJ | `OREGON_ICAC_All.pdf` | | |
| 25 | FL AG | `FLAG_ICAC_All.pdf` | | |
| 26 | RI AG | `RIAG_ICAC_All.pdf` | | |

DB counts (approx., pre-expansion): see `visualization/query.html` ICAC-search table.

**Next recommended after KY SP:** Illinois AG (265 cases, largest remaining gap).
