# `data/collected/`

Local harvest for **UMass HRPO NHSR #8252** (16 Sep 2026), *On the Mechanics of Exploitation*. Nothing in this folder is auto-ingested. The collector does not purchase PACER. `recap/` is only filings already free in RECAP. `PACER/` is an older paid folder that was already on disk; it is not this harvest.

**Snapshot below:** the 23 Sep 2026 freeze, 11:37 PM ET. Later harvests append to `public/`. The bytes stay on this machine.

## Share this number

**46,230 public rows** across six lookup files. One row per record. No article text. No PDF path. Fields: `kind`, `domain`, `agency`, `title`, `pub_date`, `source_url`, `nhsr`.

| File | Rows | What a row points at |
|---|---:|---|
| `public/press_lookup.jsonl` | 45,200 | A press URL |
| `public/recap_lookup.jsonl` | 962 | A free RECAP filing |
| `public/wayback_lookup.jsonl` | 38 | A dated platform-policy capture |
| `public/statute_lookup.jsonl` | 17 | A GovInfo statute |
| `public/calibration_lookup.jsonl` | 10 | A public report |
| `public/litigation_lookup.jsonl` | 3 | A free platform-civil filing |
| **Total** | **46,230** | |

Press rows by domain tag: fraud 41,073, trafficking 3,184, CSEA 665, forced labor 197, cyber 81. The CSEA press and court folders were removed from this machine. Those 665 URLs are still in `press_lookup.jsonl`.

## 23 Sep 2026 freeze

**45,159 distinct press URLs** was the count in the index that night.

| Domain tag | Press URLs |
|---|---:|
| Fraud | 41,087 |
| Trafficking | 3,140 |
| CSEA | 670 |
| Forced labor | 197 |
| Cyber | 65 |
| **Total** | **45,159** |

Fraud press inside that index is **40,958** full-text criminal-fraud records (`press_releases/fraud/study_records.jsonl`). 38,042 of those are a charge, plea, or sentence. The other fraud-tagged index rows are earlier bulk and state pages, not a second copy of that file.

CSEA in the index is 670 DOJ prosecutions. 400 of those were added in this freeze from the DOJ News API (`bulk/records/doj_csea.jsonl`: 223 sentenced, 93 guilty pleas or convictions, 84 charged or indicted). Another 15 are child-sexual-abuse prosecutions that had been tagged trafficking because the headline said "trafficking" images or files. The earlier ICAC press corpus was not copied into this index.

Trafficking in the index is 3,140 sex-trafficking, labor-trafficking, and human-trafficking prosecutions. A title search on the word "traffick" had also saved drug cases, firearms cases, stolen-human-remains cases, and a few program pages. Those 52 rows are removed. A case that is both sex trafficking and a drug charge stays. The court set in `recap/bulk/` is the charging-document counterpart (sex trafficking, forced labor, labor trafficking only).

Court PDFs, all free RECAP, `pacer_purchases` 0: **820 documents on 738 dockets**. One docket is one case. Some cases have more than one filing saved.

| Court folder | PDFs | What it is |
|---|---:|---|
| `recap/fraud/` | 277 | 100 year-sweep filings, 164 joined from a press docket, 13 from the 21 Sep first batch |
| `recap/bulk/` | 506 | Sex-trafficking indictments 341, forced-labor indictments 118, labor-trafficking indictments 22, plus a few named-defendant queries |
| `recap/trafficking/` | 13 | 21 Sep first batch |
| `recap/cyber/` | 12 | 21 Sep first batch |
| `recap/csea/` | 12 | 21 Sep first batch |

About **1.3 GB** on this machine. Press text is about **364 MB**. Court PDFs are about **914 MB**.

## Public tree vs this machine

Commit only enough for someone else to **rebuild** the corpus. Do not commit narratives, PDFs, or local download paths.

| Ship in git | Stay on the machine |
|---|---|
| This README | Full press text (`body`) |
| `public/*_lookup.jsonl` — one row per record, no article text, no PDF path | `press_releases/fraud/study_records.jsonl` and `state_records.jsonl` |
| | `recap/**/*.pdf`, `fraud_study.jsonl`, `from_press.jsonl` |
| | `recap/bulk/manifests/recap_links.jsonl` — local log for the 506-PDF batch. The public court list is `public/recap_lookup.jsonl` |
| Collector commands below | `press_releases/fraud/eji/` and `manifests/` |
| | `PACER/` |
| | `hyletic_data/` — reference records: wayback, statutes, calibration, platform civil filings |

A public row is a pointer. Rebuild from it with `python3 -m collector.reproduce` (plan only) or `--run --limit N` (fetch). Map: [`collector/README.md`](../../collector/README.md).

## Reproduce

From the repo root. Python packages: `requests`, `beautifulsoup4`, `reportlab`. Court downloads need a free CourtListener token in `.env` as `COURTLISTENER_API_TOKEN` ([API help](https://www.courtlistener.com/help/api/rest/)). Do not commit the token. DOJ press uses the public News API (no key, about 3 requests/second). This token is about 10 CourtListener calls/minute, 100/hour, 250/day. Storage PDF downloads do not spend that quota. Never point the collector at PACER or ECF.

These commands are how the 23 Sep snapshot was built. Running them again resumes harvest and appends new URLs to `public/`.

Details of extractors and the DOJ API: `collector/press_releases/PRESS_RELEASE_COLLECTION.md`. Suite map: `collector/README.md`.

### Fraud press

Fraud is one press profile, the same path as trafficking, cyber, and CSEA: `collector/press_releases/harvest_doj_press.py --profile fraud`. Full text already on disk is `press_releases/fraud/study_records.jsonl`. Free RECAP joined from those releases is `recap/fraud/`.

```bash
python3 collector/press_releases/harvest_doj_press.py --profile fraud
python3 collector/press_to_recap.py extract
python3 collector/press_to_recap.py pull --max-calls 180
```

The public press lookup is the input list of URLs. To rebuild text for one known `justice.gov` URL, `collector/press_releases/resolve_press_urls.py` reads the DOJ API. Do not scrape `justice.gov` HTML. State and other hosts use `collector/press_releases/build_press_pdf.py` and `fetch_source_urls.py`.

### Earlier mixed corpus (already on disk)

Those rows were gathered with the press and court scripts: `harvest_doj_press.py` for DOJ titles, `fetch_source_urls.py` for agency and state listings, `build_press_pdf.py` for the merged PDFs, and `press_to_recap.py` plus `court_records.py` for free RECAP. The CSEA and trafficking additions used `harvest_doj_press.py` with `--skip-url-file` pointing at URLs already in `public/press_lookup.jsonl`.

## Folder tour

```
data/collected/                         about 1.3 GB, frozen 23 Sep 2026 11:37 PM ET
  README.md                             this map
  public/
    press_lookup.jsonl                  press URLs, no article text
    recap_lookup.jsonl                  free RECAP URLs, no PDF
    wayback_lookup.jsonl                dated platform-policy URLs
    statute_lookup.jsonl                statute URLs
    calibration_lookup.jsonl            public report URLs
    litigation_lookup.jsonl             platform-filing URLs
  press_releases/
    fraud/                              study JSONL, state feeds, EJI seeds, first-batch PDFs
    trafficking/  cyber/              first-batch press PDFs
    bulk/records/                       full-text rows from the bulk expansion plus this freeze
    bulk/doj_raw/                       DOJ API JSON before the domain gate
    bulk/urls/                          listing URLs tried for state and federal feeds
  recap/
    fraud/                              277 fraud PDFs (year sweep + docket join + first batch)
    fraud/from_press/                   164 PDFs joined from a press-release docket
    bulk/                               506 trafficking / forced-labor RECAP PDFs
    bulk/manifests/recap_links.jsonl    public URL index for that court batch
    trafficking/  cyber/              first-batch court PDFs
  manifests/                            first-batch per-record JSON, full text, local only
  PACER/                                already-purchased filings. Not produced here
  hyletic_data/                         reference records. Not part of the 23 Sep freeze. Local only
    wayback/  litigation/  statutes/  calibration/
```

`case_studies.json` is next to this folder, at `data/case_studies.json`. It is not part of the harvest.

## Reference records

Not part of the 23 Sep freeze. Nothing here is ingested. Files stay on this machine. Seeds that rebuild them live in `collector/profiles/`. Commands: `python3 -m collector.hyletic`. Map: `collector/README.md`.

```
data/collected/hyletic_data/
  wayback/          dated platform-policy snapshots
  litigation/       free RECAP filings. pacer_purchases 0
  statutes/         GovInfo copies of cited U.S. Code sections
  calibration/      public reports (WeProtect, NCMEC, CCRC). Not raw CyberTipline cases
```

Each saved object is the bytes plus `<filename>.provenance.json`: source URL, retrieval time, sha256. A `manifest.jsonl` in each folder is the log. Re-runs skip a file when the URL and the hash already match. `catalog_role` on a sidecar is a filing label for a later CASE-UCO load. It is not an observed fact.

First-batch press PDFs (21 Sep), separate from the study JSONL: fraud 515, trafficking 530, cyber 538, CSEA 501. Many of those are short merged pages, which is why the PDF count is high and the megabytes are small.

### Press expansion already on disk (22 Sep 2026, plus this freeze)

Full-text rows in `press_releases/bulk/records/`. The fraud press file already includes the earlier DOJ fraud bulk file, so do not add `doj_fraud.jsonl` on top of those 40,958 records.

| Bulk file | Rows | Domain mix |
|---|---:|---|
| `doj_fraud.jsonl` | 8,706 | fraud 8,605, cyber 95, trafficking 5, forced labor 1 |
| `doj_trafficking.jsonl` | 2,575 | sex trafficking, labor trafficking, and human trafficking. Drug-only rows from the last pass are removed |
| `doj_csea.jsonl` | 400 | CSEA prosecutions added at this freeze |
| `ice.jsonl` | 1,518 | fraud 1,035, trafficking 401, forced labor 63, cyber 19 |
| `doj_cyber.jsonl` | 170 | fraud 89, cyber 81 |
| `usss.jsonl` | 117 | fraud 111, cyber 3, trafficking 2, forced labor 1 |
| `doj_forced_labor.jsonl` | 30 | forced labor (2 older rows plus 28 new at this freeze) |
| State and local feeds | the rest | mostly trafficking or forced labor, a few rows each |

## Fraud press on disk

Press for scale. Court filings for the close read of how a fraud runs (wire, elder, romance, business-email compromise, crypto, tech support).

### Press case records — `press_releases/fraud/study_records.jsonl`

**40,958** unique records, one URL each, about **161 MB** of full text on disk. The press index had been appending the same URL twice; those extra index rows are gone. Local only. Each line is one case: `title`, `pub_date`, `agency`, `source_url`, `body`, `stage`, `bucket`, `source_id`. `observed` is true. Nothing in here is an inferred trajectory.

A row is kept when the title or the opening says fraud, scam, embezzlement, Ponzi, phishing, identity theft, or a scheme to defraud, and it also reads like a case (sentenced, guilty, convicted, indicted, charged, or arrested). Grants, awareness months, scam-alert tips, and civil-settlement headlines are dropped.

`stage` comes from the headline:

| Stage | Rows | Meaning |
|---|---:|---|
| `sentenced` | 15,428 | A sentence |
| `plea_or_convicted` | 12,372 | A guilty plea or conviction |
| `early` | 10,242 | Arrest, charge, or indictment |
| `other` | 2,916 | Fraud is in the text; the prosecution word is in the body, not the headline |

The first three are **38,042** criminal-fraud prosecutions. The `other` slice includes real cases with a vague headline and some ICE operational notes that are not one prosecution. Treat that slice lightly when coding a trajectory.

`bucket` is a type tag for sampling, not a legal charge:

| Bucket | Rows | What it catches |
|---|---:|---|
| `classic` | 22,176 | wire, mail, bank fraud |
| `cyber` | 7,472 | business email, crypto, phishing, identity theft, tech-support |
| `other` | 5,461 | health-care, tax, mortgage, insurance |
| `investment` | 2,594 | investment fraud, Ponzi, securities |
| `elder` | 2,177 | elder fraud, grandparent, seniors |
| `online` | 1,078 | romance, lottery, sweepstakes, gift card |

Years. The DOJ News API's fraud titles start **2009-01-06**. 2006–2007 here are two non-DOJ rows.

| Year | Rows | Year | Rows | Year | Rows |
|---:|---:|---:|---:|---:|---:|
| 2006 | 1 | 2013 | 3,313 | 2020 | 2,352 |
| 2007 | 2 | 2014 | 3,550 | 2021 | 2,808 |
| 2009 | 126 | 2015 | 3,347 | 2022 | 2,809 |
| 2010 | 212 | 2016 | 3,058 | 2023 | 2,698 |
| 2011 | 379 | 2017 | 3,105 | 2024 | 2,791 |
| 2012 | 396 | 2018 | 2,865 | 2025 | 2,512 |
| | | 2019 | 2,656 | 2026 | 1,978 |

Sources: `doj_fraud_study` 30,991 from this sweep, `doj_fraud` 8,699 copied from the earlier bulk file, `ice` 983, `doj_cyber` 170, `usss` 114, Elder Justice Initiative 1. The DOJ title sweep has finished. `study_status.json` is the counter from that run.

`state_records.jsonl` had **50** state-AG prosecution rows when collection stopped. Per-source text is under `state_feeds/`. The same prosecution gate drops alerts and program pages. Yield there is thin.

`eji/` holds the Elder Justice Initiative appendix PDFs, their text, and `seeds.json`. The PDFs stay local.

### Court documents — `recap/fraud/`

**277** PDFs. Three layers, then stopped:

| Layer | Documents | What it is |
|---|---:|---|
| Year sweep | 100 | `fraud_study.jsonl`. Indictments, pleas, sentencing memos from a keyword search. |
| Press-docket join | 164 | `from_press.jsonl`. One CourtListener lookup per press-release docket, then the free PDF. 163 docket filings plus 1 linked appellate opinion. The queue was 804 dockets; the rest were not looked up. |
| 21 Sep first batch | 13 | Loose surname hits included, such as *United States v. Elder*. Prefer the two logs above. |

The public court lookup has **264** of those filings (100 year-sweep + 164 docket-join). No PDF path. Kinds: indictment 70, sentencing 71, sealed indictment 34, plea 33, superseding indictment 28, factual basis 11, affidavit 8, complaint 8, other 1.

Years in those 264. The docket join walked recent years first, so 2024–2025 are the thick part of the free archive we reached:

| Year | Docs | Year | Docs | Year | Docs |
|---:|---:|---:|---:|---:|---:|
| 2000 | 6 | 2009 | 1 | 2021 | 13 |
| 2001 | 3 | 2010 | 1 | 2022 | 10 |
| 2006 | 1 | 2017 | 2 | 2023 | 19 |
| 2007 | 1 | 2018 | 2 | 2024 | 65 |
| 2008 | 1 | 2020 | 3 | 2025 | 114 |
| | | | | 2026 | 21 |

One linked opinion has no filing year. Many lookups find the indictment on the docket and save nothing, because the PDF is not in free RECAP. Those are skipped. Nothing is bought.

`fraud_study_status.json` and `from_press_status.json` show calls used and `pacer_purchases: 0`. The status file can lag the last PDFs written; the JSONL and the PDF folder are the freeze count.

The trafficking court set is `recap/bulk/` plus `recap/bulk/manifests/recap_links.jsonl`.
