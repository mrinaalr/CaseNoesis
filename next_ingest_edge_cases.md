# Next ingest edge cases (Tier D — not auto-fixed)

Logged from possessive-agency sweep (2026-06-02). Do not apply generic possessive strip.

| Label (examples) | Cases | Issue |
|------------------|------:|-------|
| `United State's Attorney` | 1 | OCR typo (`State` not `States`) + possessive |
| `Camden Sheriff's Office 6. Cobb County Police Department` | 1 | Two agencies merged into one NER span |
| `Contra Costa's District Attorney''s Office` | 1 | Nested possessive / quote artifact |
| `Prosecutor's Office {Town} Police Department` | ~6 | NJ press merge: prosecutor office glued to local PD |
| `General's Office Texas Department of Criminal Justice` | 2 | Truncated AG + unrelated Texas DCR string |

Tier C (legit — do not strip): `Prince George's County Police Department`, `Lee's Summit Police Department`, `Justice Department's Criminal Division`, `Secret Service's … Field Office`, `Governor's Task Force Against Human Trafficking`.
