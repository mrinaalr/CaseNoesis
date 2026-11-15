"""Tests for the extraction engine. Invented text only; no collected data is read.

    .venv/bin/python -m unittest extraction.test_extraction -v
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from encoding import redact
from extraction import cases, explore, fields, graph, names, pipeline, resolve, store
from extraction.readers import Doc, llm

# Invented for this test. No person, office, or docket here exists.
RELEASE = (
    "UNITED STATES OF AMERICA v. JOHN Q. SAMPLE, Defendant. Case 1:23-cr-00123.\n\n"
    "EXAMPLE CITY – Jane Roe Sample, 45, of Exampleton, was sentenced today to 10 years in prison "
    "for wire fraud, in violation of 18 U.S.C. § 1343, announced U.S. Attorney Mary Major. "
    "U.S. District Judge Richard Bench also ordered Sample to pay $1.97 million in restitution. "
    "Sample defrauded more than 30 investors of $2.5 million through a Ponzi scheme, "
    "using WhatsApp and wire transfers. Wire fraud carries a maximum penalty of 20 years in prison.\n\n"
    "To report fraud, call the hotline or send an e-mail to the office."
)


def doc(text: str = RELEASE, kind: str = "press", **entry) -> Doc:
    return Doc("pr-test000000000000", kind, "fraud", text, entry)


def finals(result, field):
    return {(f["role"], f["value"]): f for f in result["resolutions"][field]["finals"]}


def claim(field="money", role="loss", family="surface_pattern", confidence=0.8, span=(0, 5), value=100.0, **more):
    return {
        "field": field, "role": role, "family": family, "method": family, "confidence": confidence,
        "span_start": span[0] if span else None, "span_end": span[1] if span else None,
        "span_ok": 1 if span else 0, "value": value, "extras": {}, **more,
    }


class TypedTokenTests(unittest.TestCase):
    def test_money_reads_the_scale_word(self) -> None:
        text = "lost $1.97 million, then $2.5M, then $40,000 and $3 billion"
        self.assertEqual([v for _, _, v, _ in fields.iter_money(text)], [1970000.0, 2500000.0, 40000.0, 3e9])

    def test_statute_forms_and_lists(self) -> None:
        text = "18 U.S.C. §§ 1343 and 1349; Title 18, United States Code, Section 1956(a)(1); 18 u.s.c. § 1028a"
        self.assertEqual(
            [v for _, _, v, _ in fields.iter_statute(text)],
            ["18 U.S.C. § 1343", "18 U.S.C. § 1349", "18 U.S.C. § 1956(a)(1)", "18 U.S.C. § 1028A"],
        )

    def test_two_terms_side_by_side_are_two_terms(self) -> None:
        found = [(v, x["months"]) for _, _, v, x in fields.iter_duration("48 months, 44 months; five years and three months; life in prison")]
        self.assertEqual(found, [("48 months", 48), ("44 months", 44), ("five years and three months", 63), ("life in prison", None)])

    def test_docket_number_and_dates_normalize(self) -> None:
        self.assertEqual([v for _, _, v, _ in fields.iter_case_number("No. 1:23-CR-123-ABC")], ["1:23-cr-00123"])
        self.assertEqual([v for _, _, v, _ in fields.iter_date("Filed 01/05/99; March 3, 2024; 2024-02-30")], ["1999-01-05", "2024-03-03"])


class GateTests(unittest.TestCase):
    def test_value_comes_from_the_text_not_the_reader(self) -> None:
        text = "ordered to pay $1.97 million in restitution"
        start = text.index("$")
        out = fields.gate_assertion(text, claim(role="restitution", span=(start, start + 5), value=1.97))
        self.assertEqual((out["span_ok"], out["value"], out["span_text"]), (1, 1970000.0, "$1.97 million"))

    def test_no_span_no_value(self) -> None:
        out = fields.gate_assertion("no amount here at all", claim(span=(3, 9)))
        self.assertEqual((out["span_ok"], out["span_text"]), (0, None))
        self.assertEqual(out["extras"]["gate_reason"], "no_money_token_in_span")

    def test_a_role_the_field_does_not_have_is_rejected(self) -> None:
        out = fields.gate_assertion("pay $5,000", claim(role="victim", span=(4, 10)))
        self.assertEqual(out["extras"]["gate_reason"], "role_not_in_field")


class VoteTests(unittest.TestCase):
    def resolve(self, *claims):
        return resolve.resolve_field(fields.get(claims[0]["field"]), list(claims))

    def test_two_families_agree(self) -> None:
        out = self.resolve(claim(), claim(family="clause", confidence=0.6))
        self.assertEqual((out["status"], out["finals"][0]["status"]), ("agreed", "agreed"))

    def test_two_methods_in_one_family_are_one_vote(self) -> None:
        out = self.resolve(claim(), claim(method="another_regex"))
        self.assertEqual(out["finals"][0]["status"], "resolved")

    def test_one_weak_family_goes_to_review(self) -> None:
        out = self.resolve(claim(confidence=0.6))
        self.assertEqual((out["status"], out["finals"], out["review"][0]["state"]), ("needs_review", [], "weak"))

    def test_disagreement_vetoes(self) -> None:
        out = self.resolve(claim(role="loss"), claim(role="restitution", family="clause"))
        self.assertEqual((out["status"], out["finals"]), ("disagreement", []))
        self.assertEqual(out["review"][0]["roles"], {"loss": ["surface_pattern"], "restitution": ["clause"]})

    def test_unknown_abstains(self) -> None:
        out = self.resolve(claim(), claim(role="unknown", family="sdk_rule"))
        self.assertEqual(out["finals"][0]["families"], ["surface_pattern"])

    def test_a_family_that_says_two_things_abstains(self) -> None:
        out = self.resolve(claim(role="loss"), claim(role="fine"), claim(role="loss", family="clause", confidence=0.75))
        self.assertEqual((out["finals"][0]["role"], out["finals"][0]["families"]), ("loss", ["clause"]))

    def test_a_witness_with_no_span_cannot_create_a_value(self) -> None:
        alone = self.resolve(claim(field="stage", role="present", family="metadata", span=None, value="sentenced"))
        self.assertEqual((alone["status"], alone["finals"]), ("empty", []))
        both = self.resolve(
            claim(field="stage", role="present", value="sentenced"),
            claim(field="stage", role="present", family="metadata", span=None, value="sentenced"),
        )
        self.assertEqual(both["finals"][0]["status"], "agreed")

    def test_an_excluded_role_is_a_vote_and_never_a_value(self) -> None:
        out = self.resolve(claim(field="sentence", role="not_sentence", value="two years"))
        self.assertEqual(out["finals"], [])
        contested = self.resolve(
            claim(field="sentence", role="imposed", value="two years"),
            claim(field="sentence", role="not_sentence", family="clause", value="two years"),
        )
        self.assertEqual(contested["status"], "disagreement")

    def test_human_wins(self) -> None:
        out = self.resolve(claim(role="loss"), claim(role="restitution", family="clause"), claim(role="proceeds", family="human", confidence=1.0))
        self.assertEqual((out["finals"][0]["role"], out["finals"][0]["status"]), ("proceeds", "human"))


class ReaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.result = pipeline.read_doc(doc(stage="sentenced"))

    def test_terms_are_told_apart(self) -> None:
        found = finals(self.result, "sentence")
        self.assertEqual(found[("imposed", "10 years")]["status"], "agreed")
        self.assertIn(("exposure", "20 years"), found)

    def test_amounts_get_roles_from_two_families(self) -> None:
        found = finals(self.result, "money")
        self.assertEqual(found[("restitution", 1970000.0)]["families"], ["clause", "surface_pattern"])
        self.assertEqual(found[("loss", 2500000.0)]["status"], "agreed")

    def test_statute_and_words_agree_on_the_offense(self) -> None:
        self.assertEqual(finals(self.result, "offense")[("present", "wire_fraud")]["families"], ["lookup", "surface_pattern"])

    def test_collector_stage_corroborates_the_text(self) -> None:
        self.assertEqual(finals(self.result, "stage")[("present", "sentenced")]["families"], ["metadata", "surface_pattern"])

    def test_profile_labels(self) -> None:
        self.assertIn(("present", "ponzi"), finals(self.result, "scheme"))
        self.assertIn(("present", "wire_transfer"), finals(self.result, "channel"))
        self.assertIn(("present", "whatsapp"), finals(self.result, "platform"))

    def test_a_cue_in_reporting_boilerplate_is_not_a_channel(self) -> None:
        self.assertNotIn(("present", "email"), finals(self.result, "channel"))

    def test_sdk_anchor_confirms_and_the_gate_fixes_its_value(self) -> None:
        start = RELEASE.index("$1.97")
        cite = RELEASE.index("18 U.S.C.")
        anchored = doc()
        anchored.sdk_anchors = [
            {"start": start, "end": start + 5, "label": "Amount $1.97", "class": "uco-observable:ObservableObject", "event_types": []},
            {"start": cite, "end": cite + 16, "label": "Statute 18 U.S.C. § 1343", "class": "uco-observable:ObservableObject", "event_types": []},
        ]
        result = pipeline.read_doc(anchored)
        sdk_money = next(a for a in result["assertions"] if a["family"] == "sdk_rule" and a["field"] == "money")
        self.assertEqual(sdk_money["value"], 1970000.0)
        self.assertEqual(finals(result, "statute")[("cited", "18 U.S.C. § 1343")]["families"], ["sdk_rule", "surface_pattern"])


class NameTests(unittest.TestCase):
    def test_defendants_are_numbered_and_officials_are_not_stored(self) -> None:
        result = pipeline.read_doc(doc())
        found = finals(result, "party")
        self.assertEqual(sorted(found), [("defendant", "person-1"), ("defendant", "person-2")])
        self.assertEqual({a["span_text"] for a in result["assertions"] if a["field"] == "party" and a["span_ok"]}, {names.MASK})

    def test_no_assertion_or_decision_holds_a_name(self) -> None:
        stored = json.dumps(pipeline.read_doc(doc()), default=str)
        for name in ("Sample", "Major", "Bench", "Jane", "Richard"):
            self.assertNotIn(name, stored)

    def test_scrub_masks_full_names_and_later_surnames(self) -> None:
        masked = names.scrub_text(RELEASE)
        for name in ("Jane Roe Sample", "JOHN Q. SAMPLE", "Mary Major", "Richard Bench", "ordered Sample"):
            self.assertNotIn(name, masked)
        self.assertIn("Ponzi scheme", masked)
        self.assertIn("U.S. Attorney", masked)

    def test_scrub_masks_a_name_with_no_label_before_it(self) -> None:
        for sentence, name in (("Sample told Maria Lopez that her grandson was in jail.", "Maria Lopez"),
                               ("The funds went to an account held by Robert Chen.", "Robert Chen"),
                               ("He met with Ana-Maria O'Neil, who wired the funds.", "O'Neil")):
            self.assertNotIn(name, names.scrub_text(sentence))

    def test_a_name_with_no_label_masks_but_is_not_a_person_of_the_record(self) -> None:
        text = "Sample told Maria Lopez that her grandson was in jail."
        self.assertIn("Maria Lopez", names.find_unlabeled(text))
        self.assertNotIn("Maria Lopez", names.find_names(text))

    def test_an_unlabeled_phrase_is_masked_whole_and_as_written(self) -> None:
        masked = names.scrub_text("He worked with the Child Exploitation Unit. He possessed child pornography.")
        self.assertIn("child pornography", masked)

    def test_institutions_in_running_text_are_not_names(self) -> None:
        masked = names.scrub_text("The victim sent money through Western Union to the United States District Court.")
        self.assertIn("Western Union", masked)
        self.assertIn("United States District Court", masked)

    def test_the_independent_check_finds_a_name_the_rules_missed(self) -> None:
        if not names.ner_available():
            self.skipTest("Stanza's English model is not installed")
        self.assertIn("Maria Lopez", " ".join(names.independent_leaks(json.dumps({"text": "Then Maria Lopez called the bank."}))))
        self.assertEqual(names.independent_leaks(json.dumps({"text": "Then [name] called the bank."})), [])

    def test_redaction_keeps_the_person_and_drops_the_name(self) -> None:
        source = {
            "@graph": [
                {"@id": "p", "@type": "uco-identity:Person", "uco-core:name": "Jane Roe Sample", "uco-core:description": "Jane Roe Sample"},
                {"@id": "e", "@type": "uco-core:Event", "uco-core:description": "Jane Roe Sample was sentenced " * 5},
                {"@id": "r", "@type": "uco-core:Relationship", "uco-core:source": {"@id": "p"}, "uco-core:target": {"@id": "e"}},
                {"@id": "m", "@type": "uco-observable:EmailAddress", "uco-core:name": "Email jane.sample@example.org"},
                {"@id": "u", "@type": "uco-observable:URL", "uco-core:hasFacet": [
                    {"@id": "f", "@type": "uco-observable:URLFacet", "uco-observable:fullValue": "https://example.org/pr/jane-sample-sentenced"}]},
            ]
        }
        annotations = [{"type": "Annotation", "body": "p", "target": {"selector": [
            {"type": "TextPositionSelector", "start": 0, "end": 15}, {"type": "TextQuoteSelector", "exact": "Jane Roe Sample"}]}}]
        cleaned, notes, report = redact.redact_graph(source, annotations, RELEASE)
        by_id = {node["@id"]: node for node in cleaned["@graph"]}
        self.assertEqual(by_id["p"]["uco-core:name"], "Person 1")
        self.assertIn("r", by_id)
        self.assertEqual(by_id["e"]["uco-core:description"], redact.WITHHELD)
        self.assertEqual(by_id["m"]["uco-core:name"], "Email [redacted]@example.org")
        self.assertEqual(by_id["u"]["uco-core:hasFacet"][0]["uco-observable:fullValue"], "https://example.org/")
        self.assertEqual([s["type"] for s in notes[0]["target"]["selector"]], ["TextPositionSelector"])
        self.assertEqual((report["people_renamed"], report["name_check"]), (1, "pass"))
        self.assertNotIn("Sample", json.dumps(cleaned) + json.dumps(notes))
        again, _, second = redact.redact_graph(cleaned, notes, RELEASE)
        self.assertEqual((again, second["strings_changed"]), (cleaned, 0))


class LlmTests(unittest.TestCase):
    TEXT = "The court noted the $40,000 figure in the record. Nothing else was said."

    def open_mention(self):
        start = self.TEXT.index("$")
        return [{"field": "money", "span": [start, start + 7]}]

    def test_a_quoted_answer_is_kept_below_the_line(self) -> None:
        reply = json.dumps({"role": "loss", "quote": "the $40,000 figure"})
        out = llm.ask(doc(self.TEXT), self.open_mention(), transport=lambda prompt: reply)
        self.assertEqual((out[0]["role"], out[0]["confidence"]), ("loss", 0.6))
        self.assertLess(out[0]["confidence"], resolve.SINGLE_FAMILY_MIN_CONFIDENCE)

    def test_an_answer_without_a_real_quote_is_dropped(self) -> None:
        for reply in ({"role": "loss", "quote": "a figure the text never states"}, {"role": "made_up", "quote": "the $40,000 figure"},
                      {"role": "loss", "quote": "Nothing else was said."}):
            self.assertEqual(llm.ask(doc(self.TEXT), self.open_mention(), transport=lambda prompt, r=reply: json.dumps(r)), [])

    def test_the_model_cannot_finalize_alone(self) -> None:
        reply = json.dumps({"role": "loss", "quote": "the $40,000 figure"})
        result = pipeline.read_doc(doc(self.TEXT), use_llm=True, llm_transport=lambda prompt: reply)
        self.assertEqual(result["resolutions"]["money"]["finals"], [])


class StoreAndGraphTests(unittest.TestCase):
    """Synthetic record -> store -> cases -> graph -> SDK gate."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name).resolve()
        self.entries = [
            {"record_id": "pr-test000000000000", "kind": "press", "domain": "fraud", "stage": "sentenced",
             "agency": "USAO - Example, Northern", "source_url": "https://example.org/pr/jane-sample-sentenced"},
            {"record_id": "ct-test000000000000", "kind": "court", "domain": "fraud", "agency": "exd",
             "docket_number": "1:23-cr-00123", "press_url": "https://example.org/pr/jane-sample-sentenced",
             "source_url": "https://www.courtlistener.com/docket/123456/1/united-states-v-sample/", "sha256": "ab" * 32},
        ]
        texts = {"pr-test000000000000": RELEASE, "ct-test000000000000": "JUDGMENT IN A CRIMINAL CASE\nCase 1:23-cr-00123\n" + RELEASE}
        self.patches = [
            mock.patch.object(store, "DB_PATH", root / "noesis.db"),
            mock.patch.object(graph, "GRAPHS", root / "graphs"),
            mock.patch.object(store, "EXTRACTED", root),
            mock.patch.object(store, "REPO_ROOT", root),
            mock.patch.dict(graph._INDEX, {entry["record_id"]: entry for entry in self.entries}, clear=True),
            mock.patch.dict(explore._INDEX, {entry["record_id"]: entry for entry in self.entries}, clear=True),
            mock.patch.object(pipeline, "load_doc", lambda entry: (Doc(entry["record_id"], entry["kind"], entry["domain"], texts[entry["record_id"]], entry), "test")),
            mock.patch("encoding.corpus.load_index", lambda: self.entries),
            mock.patch("encoding.corpus.press_record_id", lambda url: "pr-test000000000000"),
        ]
        for patch in self.patches:
            patch.start()
        pipeline.run(self.entries)

    def tearDown(self) -> None:
        for patch in self.patches:
            patch.stop()
        self.tmp.cleanup()

    def test_a_record_already_read_is_skipped_and_can_be_revoted(self) -> None:
        self.assertEqual(pipeline.run(self.entries)["already_read"], 2)
        db = store.connect()
        before = db.execute("SELECT COUNT(*) FROM assertions").fetchone()[0]
        self.assertEqual(pipeline.reresolve()["records"], 2)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM assertions").fetchone()[0], before)
        self.assertEqual(explore.search("money", role="loss", minimum=1_000_000)["records"], 2)

    def test_the_press_link_joins_release_and_filing(self) -> None:
        summary = cases.build()
        self.assertEqual((summary["cases"], summary["largest_case"]), (1, 2))
        linked = explore.case("ct-test000000000000")
        self.assertEqual({r["basis"] for r in linked["records"]}, {"press_link"})

    def test_review_windows_mask_names(self) -> None:
        shown = json.dumps(explore.record("pr-test000000000000"))
        self.assertNotIn("Sample", shown)

    def test_the_graph_validates_has_defendants_and_no_names(self) -> None:
        cases.build()
        summary = graph.build(["ct-test000000000000"], gate=True)
        self.assertEqual((summary["built"], summary["conforming"], summary["errors"]), (1, 1, {}))
        text = (graph.graph_dir("ct-test000000000000") / "graph.jsonld").read_text(encoding="utf-8")
        nodes = json.loads(text)["@graph"]
        kinds = {node["@type"] if isinstance(node["@type"], str) else node["@type"][0] for node in nodes}
        for expected in ("uco-identity:Person", "uco-role:Role", "legalproc:Sentence", "legalproc:RestitutionOrder",
                         "legalproc:FederalCharge", "legalproc:PotentialPenalty", "case-investigation:Investigation"):
            self.assertIn(expected, kinds)
        self.assertEqual(sorted(n["uco-core:name"] for n in nodes if n["@type"] == "uco-identity:Person"), ["Defendant 1", "Defendant 2"])
        for name in ("Sample", "SAMPLE", "Major", "Bench", "united-states-v"):
            self.assertNotIn(name, text)
        self.assertIn("1970000.00", text)

    def test_the_local_triple_store_answers_sparql_and_refuses_updates(self) -> None:
        from extraction import triples

        cases.build()
        graph.build(["ct-test000000000000"], gate=True)
        summary = triples.load()
        self.assertEqual((summary["loaded_now"], summary["named_graphs"]), (1, 1))
        self.assertTrue(triples.nquads_path().is_file())
        self.assertEqual(triples.load()["loaded_now"], 0)
        found = triples.query("SELECT ?g ?amount WHERE { GRAPH ?g { ?o a legalproc:RestitutionOrder ; legalproc:monetaryAmount ?amount } }")
        self.assertEqual(found["rows"], [{"g": "urn:casenoesis:record:ct-test000000000000", "amount": "1970000"}])
        people = triples.query("SELECT ?name WHERE { ?p a uco-identity:Person ; uco-core:name ?name } ORDER BY ?name")
        self.assertEqual([row["name"] for row in people["rows"]], ["Defendant 1", "Defendant 2"])
        self.assertIn("error", triples.query("DELETE WHERE { ?s ?p ?o }"))
        self.assertNotIn("Sample", triples.nquads_path().read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
