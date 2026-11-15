# Gold set

**Every record here is invented.** The people, the dockets, the amounts, the dates and the events do not exist. No record is a public record, and none is taken from one. Surnames are coined for this corpus so that a record does not name a real family; a match with a real person would be a coincidence. Districts, agencies and statutes are real, because a record that named a fictional court would not have the shape of a real one. Every record carries a `notice` saying it is invented, and every source address is under `gold.example`.

The corpus exists to measure the extraction engine. A record is written from a case whose attributes are known, so what the engine stores can be compared with what the text states, exactly and without a person or a model labelling anything.

| File | Holds |
|---|---|
| `world.py` | The generator of cases: defendants, charges, dates, terms, amounts, and the path each case took |
| `render.py` | Six document shapes written from a case, and beside each text what it states |
| `build.py` | Builds the corpus. Deterministic: the same seed writes the same bytes |
| `score.py` | Runs the engine on the corpus and scores every layer |
| `corpus/records.jsonl` | 200 records: id, metadata, text |
| `corpus/truth.jsonl` | What each record states: values with roles and owners, labels, events, distractors |
| `corpus/cases.jsonl` | The 133 cases: their records, their defendants, what was planted |
| `results/` | Scores on each split, with and without the parser readers, and for the previous engine version |

```bash
python -m gold build                    # write corpus/ from the generator
python -m gold score --split dev        # the split used while working on the readers
python -m gold score --split test       # the held-out split
python -m gold score --split dev --misses 10 --field money
CASENOESIS_SYNTAX=1 python -m gold score --split test
```

Cases alternate between `dev` and `test`. Change readers against `dev`. Score `test` after the last change, and do not correct readers against it.

What the scores mean, and what they do not, is in `Architecture design.md`, section 13.1.
