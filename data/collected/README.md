# `data/collected/`

Local harvest for **UMass HRPO NHSR #8252** (16 Sep 2026), *On the Mechanics of Exploitation*. Nothing in this folder is auto-ingested. The collector does not purchase PACER. `recap/` is only filings already free in RECAP. `PACER/` is an older paid folder that was already on disk; it is not this harvest.

Snapshot below: **23 Sep 2026, about 9:40 PM ET**, while the fraud-study harvest is still running. Press and court counts on this machine will keep growing. The committed lookup files match this snapshot.

## Public tree vs this machine

Commit only enough for someone else to **rebuild** the corpus. Do not commit narratives, PDFs, or local download paths.

| Ship in git | Stay on the machine |
|---|---|
| This README | Full press text (`body`) |
| `public/fraud_press_lookup.jsonl` — one row per fraud case record: title, date, agency, source URL, type tag. No article text | `press_releases/fraud/study_records.jsonl` and `state_records.jsonl` |
| `public/fraud_court_lookup.jsonl` — one row per free RECAP filing: court URL, docket, description, year. No PDF | `recap/fraud/*.pdf` and `recap/fraud/fraud_study.jsonl` |
| `press_releases/press_lookup.jsonl` — mixed-domain URL index from the earlier expansion (the live file on disk also has newer appends) | `press_releases/bulk/records/*.jsonl` |
| `recap/bulk/manifests/recap_links.jsonl` — URL index for the trafficking / forced-labor RECAP batch | Every `*.pdf` under `press_releases/` and `recap/` |
| Collector commands below | `press_releases/fraud/eji/` (Elder Justice PDFs and the case seed list) |
| | `manifests/` (first-batch JSON, includes full text) |
| | `PACER/` |

A public row is a pointer. The article text and the court PDF are fetched again from the URL.

## Reproduce

From the repo root. Python packages: `requests`, `beautifulsoup4`, `reportlab`. Court downloads need a free CourtListener token in `.env` as `COURTLISTENER_API_TOKEN` ([API help](https://www.courtlistener.com/help/api/rest/)). Do not commit the token. DOJ press uses the public News API (no key, about 3 requests/second). CourtListener on this token is about 10/minute, 100/hour, 250/day. Storage PDF downloads do not spend that quota. Never point the collector at PACER or ECF.

Details of extractors and the DOJ API: `collector/PRESS_RELEASE_COLLECTION.md`. Suite map: `collector/README.md`.

### Fraud study (this pass)

Press case records land in `press_releases/fraud/study_records.jsonl`. Court PDFs land in `recap/fraud/`. State prosecution pages land in `press_releases/fraud/state_records.jsonl`. Re-runs skip URLs and document ids already saved.

```bash
# DOJ criminal-fraud press, 2009–2026 (the News API's fraud titles start 2009-01-06).
# Elder, romance, grandparent, wire/mail/bank, securities, health-care, crypto, tech-support.
python3 -u collector/harvest_fraud_study.py --phase press

# Free RECAP indictments, pleas, sentencing memos, complaints. Year-filtered.
# --court-calls 220 walks years, then sleeps when the hourly quota is empty.
python3 -u collector/harvest_fraud_study.py --phase court --court-calls 220

# State AG / federal feed pages. Prosecution gate only (charged, plea, or sentence).
python3 -u collector/harvest_fraud_study.py --phase state --state-cap 80
```

Prompt you can hand an agent:

> Reproduce the CaseNoesis fraud study under NHSR #8252. Use `collector/harvest_fraud_study.py`. Press full text goes to `data/collected/press_releases/fraud/study_records.jsonl`. Free RECAP PDFs go to `data/collected/recap/fraud/`. Keep criminal prosecutions only (indictment, plea, sentence, or charge). Do not purchase PACER. Do not commit article text or PDFs. Refresh `data/collected/public/fraud_press_lookup.jsonl` and `fraud_court_lookup.jsonl` from those files with the body and local PDF path removed.

The public press lookup is the input list of URLs. To rebuild text for one known `justice.gov` URL, `collector/resolve_press_urls.py` reads the DOJ API. Do not scrape `justice.gov` HTML; it sits behind a bot wall. State and other hosts use `collector/build_press_pdf.py` / `fetch_source_urls.py`.

### Earlier mixed corpus (already on disk)

```bash
python3 collector/run_source_bulk.py --phase doj
python3 collector/run_source_bulk.py --phase agencies
python3 collector/run_source_bulk.py --phase recap --max-recap 500
python3 collector/run_bulk.py --press-count 1000 --court-count 50 \
  --domains fraud,trafficking,cyber,csea --out-dir data/collected
```

`run_source_bulk.py --phase recap` searches trafficking and forced labor, not generic fraud. Fraud court filings are the `--phase court` command above.

## Folder tour

```
data/collected/                         about 1.1 GB on this machine
  README.md                             this map
  public/
    fraud_press_lookup.jsonl            12,104 fraud case records (URLs only)
    fraud_court_lookup.jsonl            100 fraud court documents (URLs only)
  press_releases/
    press_lookup.jsonl                  mixed-domain URL index, no article text
    fraud/                              fraud study + first-batch press PDFs
    trafficking/  cyber/  csea/         first-batch press PDFs (250 each) and tmp/
    bulk/records/                       13,131 full-text rows from the 22 Sep expansion
    bulk/doj_raw/                       DOJ API JSON before the domain gate
    bulk/urls/                          listing URLs tried for state and federal feeds
  recap/
    fraud/                              fraud-study PDFs (free RECAP) + working log
    bulk/                               506 trafficking / forced-labor RECAP PDFs
    bulk/manifests/recap_links.jsonl    public URL index for that court batch
    trafficking/  cyber/  csea/         first-batch court PDFs (about 12–13 each)
  manifests/                            first-batch per-record JSON, full text, local only
  PACER/                                already-purchased filings. Not produced here
```

`case_studies.json` is next to this folder, at `data/case_studies.json`. It is not part of the harvest.

### Press expansion already on disk (22 Sep 2026)

**13,131** full-text rows in `press_releases/bulk/records/`. **556** free RECAP PDFs in total for that pass: 50 in the first batch plus **506** in `recap/bulk/` (499 dockets). Those 506 are trafficking and forced-labor indictments (sex trafficking 341, forced labor 137, labor trafficking 27, human trafficking 1). The fraud study is separate and lives under `press_releases/fraud/` and `recap/fraud/`.

| Bulk file | Rows | What it is |
|---|---:|---|
| `doj_fraud.jsonl` | 8,706 | earlier criminal-fraud pass |
| `doj_trafficking.jsonl` | 2,521 | trafficking and a little forced labor |
| `doj_cyber.jsonl` | 170 | cyber and fraud |
| `doj_forced_labor.jsonl` | 2 | forced labor |
| `ice.jsonl` | 1,518 | mostly fraud, then trafficking |
| `usss.jsonl` | 117 | mostly fraud |

## Fraud study tour

Use this when the goal is mechanics of fraud: how a fraud type changes when a technology shows up (wire, elder, romance, business-email compromise, crypto, tech support), with press for scale and court filings for the close read.

### Press case records — `press_releases/fraud/study_records.jsonl`

**12,104** unique prosecutions, about **49 MB** of full text. Local only. Each line is one case: `title`, `pub_date`, `agency`, `source_url`, `body`, `stage`, `bucket`, `source_id`. `observed` is true. Nothing in here is an inferred trajectory.

`stage` is taken from the headline: `sentenced` 4,456, `plea_or_convicted` 3,789, `early` (arrest, charge, or indictment) 3,256, `other` 603.

`bucket` is a type tag for sampling, not a legal charge:

| Bucket | Rows | What it catches |
|---|---:|---|
| `classic` | 6,121 | wire, mail, bank fraud |
| `cyber` | 2,121 | business email, crypto, phishing, identity theft, tech-support |
| `investment` | 2,091 | investment fraud, Ponzi, securities |
| `elder` | 1,283 | elder fraud, grandparent, seniors |
| `online` | 405 | romance, lottery, sweepstakes, gift card |
| `other` | 83 | health-care, tax, mortgage, insurance |

Years. The DOJ News API's fraud titles start **2009-01-06**. 2006–2008 in this file are a handful of non-DOJ rows. 2000–2005 are empty here.

| Year | Rows | Year | Rows | Year | Rows |
|---:|---:|---:|---:|---:|---:|
| 2006 | 1 | 2013 | 910 | 2020 | 782 |
| 2007 | 2 | 2014 | 993 | 2021 | 852 |
| 2009 | 27 | 2015 | 921 | 2022 | 836 |
| 2010 | 27 | 2016 | 873 | 2023 | 806 |
| 2011 | 142 | 2017 | 862 | 2024 | 899 |
| 2012 | 147 | 2018 | 832 | 2025 | 748 |
| | | 2019 | 860 | 2026 | 584 |

Where those 12,104 rows came from: `doj_fraud` 8,699 (copied forward from the earlier bulk file), `doj_fraud_study` 2,137 added by this sweep, `ice` 983, `doj_cyber` 170, `usss` 114, Elder Justice Initiative 1. The sweep is still paging DOJ title terms, so `doj_fraud_study` will rise. `study_status.json` is the live counter.

`state_records.jsonl` is the state-AG prosecution pass (15 kept when this snapshot was written). Per-source text is under `state_feeds/`. The same prosecution gate drops alerts, award pages, and program pages.

`eji/` holds the Elder Justice Initiative appendix PDFs, their text, and `seeds.json` (case name, docket, criminal flag). Those seeds are how court search finds elder-fraud prosecutions. The PDFs stay local.

The 250 PDFs directly in `press_releases/fraud/` are the **21 Sep** first batch, not the study JSONL.

### Court documents — `recap/fraud/`

**100** free RECAP filings in `fraud_study.jsonl`, about **113** PDFs in the folder (the extra files are the 21 Sep first batch, including a few surname hits such as *United States v. Elder* that are not elder fraud). Study PDFs are named `{courtlistener document id}.pdf`. About **181 MB**.

Document kinds in the 100: indictment 58, plea 19, sentencing memorandum 17, complaint 3, factual basis 2, affidavit 1.

Years are uneven because CourtListener's free archive is thicker in recent years, and this pass paused when the 100/hour quota emptied (it resumes on its own):

| Year | Docs | Year | Docs | Year | Docs |
|---:|---:|---:|---:|---:|---:|
| 2000 | 6 | 2009 | 1 | 2021 | 13 |
| 2001 | 3 | 2010 | 1 | 2022 | 10 |
| 2006 | 1 | 2017 | 2 | 2023 | 5 |
| 2007 | 1 | 2018 | 2 | 2024 | 18 |
| 2008 | 1 | 2020 | 3 | 2025 | 29 |
| | | | | 2026 | 4 |

`fraud_study_status.json` shows calls used, the year histogram, and `pacer_purchases: 0`.

The trafficking court set is a different question. It is `recap/bulk/` plus `recap/bulk/manifests/recap_links.jsonl`, not the fraud study.
