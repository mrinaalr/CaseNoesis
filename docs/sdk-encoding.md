# SDK encoding

A collected record goes in. A validated CASE/UCO graph comes out, with no person's name in it. The [CASE/UCO SDK](https://github.com/vulnmaster/CASE-UCO-SDK) does the reading and the validating; CaseNoesis feeds it, removes names, and keeps the result.

Code: [`encoding/`](../encoding/).

This graph is the input to the extraction engine, not its output. The engine reads the text and character anchors the SDK leaves behind, settles what each value is, and writes its own graph. See [`Architecture design.md`](../Architecture%20design.md), sections 5 and 6.

State machines are not part of this. Nothing here produces a phase or a transition.

## The pin

The SDK is the `vendor/CASE-UCO-SDK` submodule.

| | |
|---|---|
| Tag | `v1.33.0` |
| Commit | `a2dc8bc96f5001c58af63e587593dbf6385b24cf` |
| Ontologies | CASE 1.5.0, UCO 1.5.0 |
| Validator | `case-utils` 0.18.0, `pyshacl` 0.31.0, `rdflib` 7.6.0 |

The commit is also written in [`encoding/sdk.py`](../encoding/sdk.py). `python -m encoding pin` fails when the checkout is not that commit.

To move the pin: check out the new tag in the submodule, reinstall `vendor/CASE-UCO-SDK/python`, update `SDK_TAG` and `SDK_COMMIT`, run the tests.

## Setup

```bash
git submodule update --init vendor/CASE-UCO-SDK
pip install -r requirements-encoding.txt
```

`case-uco` is not on PyPI. It installs from the submodule.

## Use

```bash
python -m encoding pin                               # which SDK, and is it the pin
python -m encoding index                             # what the collector has
python -m encoding records --kind court --workers 6  # encode (court, press, or reference)
python -m encoding redact --workers 6                # remove names from graphs encoded before redaction existed
python -m encoding gate --kind court --workers 6     # validate what was encoded
python -m encoding gate path/to/graph.jsonld         # validate any graph
python -m encoding status
```

## What happens to a record

1. **Index.** One pointer per record. A press record is keyed by a hash of its URL, a court filing or reference record by a hash of its bytes, so identical files are one record. A filing collected under two domain folders is one record in both domains (`domains`), and `--domain` matches either. Reference records are the statutes, calibration reports, platform litigation, and archived policy pages under `data/collected/hyletic_data/`. The index rebuilds itself when the collected files have changed under it.
2. **Process.** The SDK's `process_document_file`, as shipped. It is rule-based and uses no model. A press body goes in as plain text, a court filing or reference record as the file the collector saved. A scanned PDF is read by the SDK's OCR path, which needs `tesseract` and `pdftoppm` on the machine.
3. **Add the source.** The public URL the bytes came from, added with the SDK's builder following its public-record-capture recipe. A retrieval time is written only for reference records, where the collector recorded one. 202 of the 864 court filings have no address in the collector's logs; their graphs carry the content hash and no source address.
4. **Remove names.** [`redact.py`](../encoding/redact.py), before validation. See below.
5. **Gate.** SHACL plus the SDK's closed-world concept check. A receipt beside the graph records the result and the SDK commit.

Every collected record is encoded. All of it is public record under NHSR #8252, CSEA included. A filing labelled "sealed indictment" on its docket was unsealed before it reached free RECAP; the label stays.

## No names in graphs

The processor writes what it reads. The source text is public record and stays on this machine. The graph is derived data and carries no person's name. People stay in it; their names do not.

| What the processor wrote | What the graph keeps |
|---|---|
| A `Person` node per name | The node and its relationships, renamed `Person 1`, `Person 2`, … |
| A passage of the record on each event, and the opening of the document on the source node | "Text window withheld." The character span stays in `annotations.jsonld` |
| E-mail addresses | The domain. The local part is replaced |
| A CourtListener address ending in the case caption | The address without the caption slug |
| Any other address whose path spells a name | The host, tagged with the SHA-256 of the full address. The full address is in the local index |
| Names anywhere else in a string | `[name]` |

Names are collected from the `Person` nodes and from the text by rule: case captions, "Name, 45, of City", honorifics, role words ([`extraction/names.py`](../extraction/names.py)). An annotation on a person keeps its character position and loses its quote. Then every collected name is searched for in the graph and the anchors, and the result is written to `record.json` as `redaction.name_check`.

Name-finding is rule-based and tuned to over-mask. A name written in a form no rule covers can survive. `extracted-content.json` is the source text and is not redacted; it never leaves the machine.

Output, under `data/encoded/records/<record-id>/`. None of it is committed.

| File | Holds |
|---|---|
| `graph.jsonld` | The CASE/UCO graph |
| `extracted-content.json` | The text the processor read |
| `annotations.jsonld` | Character anchors for every extracted entity |
| `record.json` | Status, source SHA-256, entity counts, SDK commit, redaction report, gate result |
| `graph.jsonld.gate.json` | The validation receipt |

A record already encoded is skipped on the next run. One that failed is retried.

## What was run

Checked 2026-11-13 on the 23 Sep 2026 collection.

| Step | Result |
|---|---|
| Index | 44,602 press records, 864 court filings (1,083 PDFs, 219 of them byte-identical copies), 68 reference records |
| Court | All 864 encoded. 31,013 extracted entities. 608 of 864 graphs validate after redaction |
| Press | 300-record sample. 300 encoded, 300 of 300 validate |
| Reference | All 68 encoded. 0 of 68 validate. The 39 HTML pages carry no extracted entities |
| Names | 697 people renamed, 110 addresses cut, 0 records failing the name check |
| Tests | `python -m unittest encoding.test_encoding`: 6 pass, on invented text. Redaction is tested in `extraction.test_extraction` |

The press corpus has not been run in full. It needs about 1.8 GB of disk.

## Limits

- The processor is built for court filings. On a press release it finds dates, amounts, organizations, and places, and usually not who did what.
- It reads "$1.97 million" as "$1.97". Do not compute on amounts from this graph. The extraction engine re-reads every amount from the text at the SDK's anchor and gets 1,970,000.
- An HTML page is hashed and recorded, and nothing is extracted from it. The SDK's HTML reader keeps script and style text and does not run entity extraction. The archived policy pages are in this state.
- The processor is imported from the SDK's `mcp_server/` folder, which is not a published API. A new SDK tag can move it.
- Validation takes about 3 seconds a graph.

## MCP

Three tools in the local CaseNoesis server: `encoding_status`, `gate_graph`, `encoding_process_records`. The last one redacts and validates what it encodes, and tries again a record that failed before.
