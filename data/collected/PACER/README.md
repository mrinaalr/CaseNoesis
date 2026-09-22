# `data/collected/PACER/`

Paid-PACER **data** only (facts files, jsonld, BULK_FOLDER filings, cost CSV, `pacer_cases.json`).

This folder is already-purchased PACER. The bulk harvest does not buy more. Free RECAP downloads stay in `data/collected/recap/`.

Scripts live in [`collector/pacer/`](../../../collector/pacer/):

| Tool | Role |
|---|---|
| `corpus2pacer.py` | Corpus → likely federal dockets (`pacer_cases.json` here) |
| `cases2records.py` | CourtListener/RECAP fetch; PACER purchase only with `--charge-pacer` |
| `pacer_cost.py` | Append rows to `BULK_FOLDER/pacer_cost.csv` |
| `build_facts_graphs.py` | Facts files → CASE/UCO graphs |
