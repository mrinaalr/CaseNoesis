# `data/collected/`

Local harvest for NHSR #8252 (16 Sep 2026). Public press and free RECAP, plus the already-purchased PACER folder. Nothing here is auto-ingested.

How a press record is made: `collector/PRESS_RELEASE_COLLECTION.md` (listing or API → article URL → criminal-case gate → text + source URL). Grants, awards, prevention pages, consumer alerts, and non-case noise are dropped. A kept press record is a charged, indicted, plea, or sentenced case.

```
data/collected/
  press_releases/press_lookup.jsonl public lookup only: title, date, agency, domain, source URL
  press_releases/<domain>/          local: first-batch PDFs (gitignored)
  press_releases/bulk/records/      local: full press text JSONL (gitignored)
  recap/<domain>/                   local: first-batch free RECAP PDFs (gitignored)
  recap/bulk/                       local PDFs + public manifests/recap_links.jsonl
  PACER/                            already-purchased PACER (facts, jsonld, cost CSV). Not this harvest.
  manifests/<domain>/               local: first-batch per-record JSON, including full text (gitignored)
```

`recap/` is only documents already free in RECAP. `PACER/` is paid filings that were already on disk. This collector does not purchase PACER.

**First batch** (21 Sep 2026): **1,000** press PDFs (250 each in `fraud`, `trafficking`, `cyber`, `csea`, plus one merged PDF per domain) and **50** free RECAP PDFs (`fraud` 13, `trafficking` 13, `cyber` 12, `csea` 12).

**Press expansion** (snapshot 2:21 PM ET, 22 Sep 2026): **13,047** full-text rows in `press_releases/bulk/records/`. Those files stay on disk and are gitignored. `press_releases/press_lookup.jsonl` is the public index (no article text). State feeds were still running after this count.

Local files only (not on the public tree):

| File | Rows | What is in it |
|---|---:|---|
| `doj_trafficking.jsonl` | 2,521 | trafficking 2,432; forced labor 88; fraud 1 |
| `doj_forced_labor.jsonl` | 2 | forced labor |
| `doj_fraud.jsonl` | 8,706 | earlier criminal-fraud pass (fraud 8,605; also 95 cyber, 5 trafficking, 1 forced labor) |
| `doj_cyber.jsonl` | 170 | cyber 81; fraud 89 |
| `ice.jsonl` | 1,518 | fraud 1,035; trafficking 401; forced labor 63; cyber 19 |
| `usss.jsonl` | 117 | fraud 111; cyber 3; trafficking 2; forced labor 1 |

These rows are new URLs, not copies of the first 1,000. Non-DOJ files in this snapshot also include Washington AG (6), New Jersey AG (4), Texas AG (1), Georgia Bureau of Investigation (1), and Pennsylvania AG (1), all trafficking or forced labor. CBP, Marshals, NCIS, Air Force OSI, and Army CID returned no usable text.

**Court expansion** (same snapshot): **556** free RECAP PDFs. That is the first batch of 50 plus **506** in `recap/bulk/` (**499** distinct dockets). The bulk 506 are indictments already free in RECAP: sex trafficking 341, forced labor 137, labor trafficking 27, human trafficking 1. Nothing was purchased.

`case_studies.json` sits next to this folder, at `data/case_studies.json`. It is not part of this harvest.
