# `data/PACER/`

Paid-PACER **data** only (facts files, jsonld, BULK_FOLDER filings, cost CSV, `pacer_cases.json`).

Scripts live in [`collector/pacer/`](../../collector/pacer/):

| Tool | Role |
|---|---|
| `corpus2pacer.py` | Corpus → likely federal dockets (`pacer_cases.json` here) |
| `cases2records.py` | CourtListener/RECAP fetch; PACER purchase only with `--charge-pacer` |
| `pacer_cost.py` | Append rows to `BULK_FOLDER/pacer_cost.csv` |
| `build_facts_graphs.py` | Facts files → CASE/UCO graphs |

Free RECAP harvests from the bulk collector go to `data/collected/recap/`, not here.
