# `data/collected/`

Local harvest landing zone (NHSR #8252). JSON manifests are tracked so collabs can see what was collected. PDFs stay gitignored.

```
data/collected/
  press_releases/<domain>/     individual {slug}.pdf + {DOMAIN}_All.pdf
  pacer/<domain>/              free CourtListener/RECAP PDFs (never PACER purchase)
  manifests/<domain>/          per-record JSON + domain MANIFEST.json + harvest JSON
  manifests/COLLECTION.json    whole-batch summary
```

Domains: `fraud`, `trafficking`, `cyber`, `csea`. Fill via local MCP `collect_bulk` or `python3 collector/run_bulk.py`. CSEA/ICAC is one exploitation type among those; grant/award/prevention noise is dropped, not CSEA cases.
