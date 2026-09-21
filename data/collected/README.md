# `data/collected/`

Local harvest landing zone (NHSR #8252). JSON manifests are tracked so collabs can see what was collected. PDFs stay gitignored.

```
data/collected/
  press_releases/<domain>/     individual {slug}.pdf + {DOMAIN}_All.pdf
  recap/<domain>/              free CourtListener/RECAP PDFs (unpaid; never PACER)
  manifests/<domain>/          per-record JSON + domain MANIFEST.json + harvest JSON
  manifests/COLLECTION.json    whole-batch summary
```

Paid PACER work stays under `data/PACER/` (uppercase). `recap/` is only documents already in RECAP.

Domains: `fraud`, `trafficking`, `cyber`, `csea`. Present harvest: **1,000** press PDFs and **50** free RECAP PDFs (`manifests/COLLECTION.json`). Fill via CLI `python3 collector/run_bulk.py` or local MCP `collect_record` / `collect_bulk` (small batches). Targeted court: MCP `download_free_recap` or `python3 collector/court_records.py --document-id …`. CSEA/ICAC is one exploitation type among those; grant/award/prevention noise is dropped, not CSEA cases.
