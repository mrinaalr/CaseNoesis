# Victim age overrides

Populate `victim_age_overrides.json` after hand-reviewing `scripts/stats/victim_age_review_queue.json`.

```json
[
  {"case_id": "ncmec_2024_928", "age": 10, "decision": "keep"},
  {"case_id": "some_case", "age": 7, "decision": "drop"}
]
```

- **`keep`**: promotes a slot (including REVIEW-queue slots excluded by default).
- **`drop`**: removes a slot even if the gate auto-KEEPs it.

Override path: `VICTIM_AGE_OVERRIDES_PATH` env var, else `config/victim_age_overrides.json`.
