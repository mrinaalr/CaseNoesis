"""Tests for people, attribution, events and the reader fixes the gold set found.
Invented text only; no collected data is read.

    .venv/bin/python -m unittest extraction.test_structure -v
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from extraction import cases, events, fields, names, people, pipeline, resolve, spans as sp, store
from extraction.readers import Doc
from extraction.source import MemorySource

# Invented for this test. No person, office, or docket here exists.
TWO = (
    "EXAMPLE CITY – Two people were sentenced today for wire fraud, U.S. Attorney Mary Major announced.\n\n"
    "Jane Roe Sample, 45, of Exampleton, was sentenced to 87 months in federal prison. In addition, Judge Bench "
    "ordered Sample to serve three years of supervised release and to pay $1,970,000 in restitution.\n\n"
    "Ravi Placeholder, 39, of Exampleton, was sentenced to 24 months in prison. Placeholder was also ordered "
    "to pay $400,000 in restitution.\n\n"
    "Sample and Placeholder pleaded guilty in March 2024. U.S. District Judge Richard Bench imposed the sentences."
)
JUDGMENT = (
    "Case 1:23-cr-00123-RB Document 88 Filed 06/14/24 Page 1 of 7\n"
    "UNITED STATES DISTRICT COURT\nDistrict of Example\n"
    "UNITED STATES OF AMERICA JUDGMENT IN A CRIMINAL CASE\nv.\n"
    "JANE ROE SAMPLE Case Number: 1:23-CR-00123(1)\nUSM Number: 12345-510\nPAT COUNSEL\nDefendant's Attorney\n"
    "THE DEFENDANT:\n☒ pleaded guilty to count(s) 1\n☐ was found guilty on count(s)\nafter a plea of not guilty.\n"
    "Title & Section / Nature of Offense Offense Ended Count\n18:1343 Wire Fraud 02/28/2022 1\n"
    "It is ordered that the defendant must notify the United States attorney for this district within 30 days of any change of name.\n"
    "June 12, 2024\nDate of Imposition of Judgment\ns/ Richard Bench\nSignature of Judge\n"
    "DEFENDANT: JANE ROE SAMPLE\nIMPRISONMENT\n"
    "The defendant is hereby committed to the custody of the Federal Bureau of Prisons to be imprisoned for a total term of:\n87 months.\n"
    "SUPERVISED RELEASE\nUpon release from imprisonment, you will be on supervised release for a term of: three years.\n"
    "CRIMINAL MONETARY PENALTIES\nAssessment Restitution Fine\nTOTALS $100.00 $1,970,000.00 $0.00\n"
)


def read(text: str, kind: str = "press", record_id: str = "pr-test000000000001", **entry) -> tuple[Doc, dict]:
    doc = Doc(record_id, kind, "fraud", text, {"record_id": record_id, "kind": kind, **entry})
    return doc, pipeline.read_doc(doc)


def finals(result, field):
    return {(f["role"], str(f["value"])): f for f in result["resolutions"].get(field, {"finals": []})["finals"]}


def build_store(records: list[tuple[Doc, dict]]):
    """A throwaway store holding these records, with every layer built."""
    folder = tempfile.TemporaryDirectory()
    db = store.connect(Path(folder.name) / "test.db")
    run_id = store.begin_run(db, engine_version="t", rule_set_version=resolve.RULE_SET_VERSION, readers={}, sdk_commit=None, code_revision=None, llm=False)
    for doc, result in records:
        stored = store.save_record(db, run_id, {
            "record_id": doc.record_id, "kind": doc.kind, "domain": doc.domain, "text_sha256": "x", "text_source": "test", "chars": len(doc.text),
        }, result["assertions"])
        store.save_resolutions(db, doc.record_id, resolve.resolve_record(stored))
    source = MemorySource((doc.entry, doc.text) for doc, _ in records)
    cases.build(db, source)
    people.build(db, source)
    events.build(db, source)
    db.commit()
    return db, folder


class TokenTests(unittest.TestCase):
    def test_a_month_and_year_is_a_date_with_month_precision(self) -> None:
        found = list(fields.iter_date("pleaded guilty in March 2024 and was sentenced on Sept. 8, 2024; it may 2024 happen"))
        self.assertEqual([(value, extras.get("precision")) for _, _, value, extras in found], [("2024-03", "month"), ("2024-09-08", None)])

    def test_a_hyphenated_number_is_one_number(self) -> None:
        months = [extras["months"] for _, _, _, extras in fields.iter_duration("up to twenty-five years; thirty-six months; 20 to 25 years")]
        self.assertEqual(months, [300, 36, 300])

    def test_the_judgment_form_citation_is_a_statute(self) -> None:
        values = [value for _, _, value, _ in fields.iter_statute("18:1343 Wire Fraud 02/28/2022 1, heard at 10:30 in 1:23-cr-00123")]
        self.assertEqual(values, ["18 U.S.C. § 1343"])

    def test_event_triggers(self) -> None:
        kinds = [kind for _, _, kind, _ in fields.iter_event("was indicted, pleaded guilty, was found guilty and was sentenced")]
        self.assertEqual(kinds, ["indict", "plead", "convict", "sentence"])


class FormTests(unittest.TestCase):
    def setUp(self) -> None:
        self.doc, self.result = read(JUDGMENT, "court", "ct-test000000000002")

    def test_terms_on_the_form(self) -> None:
        terms = finals(self.result, "sentence")
        self.assertIn(("imposed", "87 months"), terms)
        self.assertIn(("supervised_release", "three years"), terms)
        self.assertFalse(any("30 days" in value for _, value in terms), "a deadline is not a term")

    def test_the_penalties_table_is_read_by_column(self) -> None:
        money = finals(self.result, "money")
        self.assertIn(("special_assessment", "100.0"), money)
        self.assertIn(("restitution", "1970000.0"), money)
        self.assertFalse(any(role == "fine" for role, _ in money), "a zero in the fine column is not a fine")

    def test_a_table_with_a_blank_cell_is_not_guessed(self) -> None:
        text = JUDGMENT.replace("TOTALS $100.00 $1,970,000.00 $0.00", "TOTALS $ 100.00 $ $1,970,000.00")
        money = finals(read(text, "court", "ct-test000000000003")[1], "money")
        self.assertNotIn(("fine", "1970000.0"), money)
        self.assertNotIn(("restitution", "100.0"), money)

    def test_dates_on_the_form(self) -> None:
        dates = finals(self.result, "date")
        self.assertIn(("sentencing", "2024-06-12"), dates)
        self.assertIn(("offense", "2022-02-28"), dates)
        self.assertIn(("filed", "2024-06-14"), dates)

    def test_counsel_is_not_a_defendant(self) -> None:
        parties = self.result["resolutions"]["party"]["finals"]
        self.assertEqual(len(parties), 1, "the defendant, and not the defendant's attorney")
        self.assertEqual({a["role"] for a in self.result["assertions"] if a["field"] == "party" and "COUNSEL" in self.doc.text[a["span_start"] or 0: a["span_end"] or 0]}, {"official"})

    def test_an_unchecked_box_is_not_an_event(self) -> None:
        kinds = {final["role"] for final in self.result["resolutions"]["event"]["finals"]}
        self.assertIn("plea", kinds)
        self.assertNotIn("verdict", kinds)
        self.assertNotIn("conviction", kinds)

    def test_no_name_is_stored(self) -> None:
        stored = repr([(a["value"], a["span_text"], a["extras"]) for a in self.result["assertions"]])
        self.assertNotIn("SAMPLE", stored.replace("JANE ROE SAMPLE Case", ""))


class SpanTextTests(unittest.TestCase):
    def test_a_long_span_is_stored_without_the_names_in_it(self) -> None:
        text = "In an indictment, Jane Roe Sample and Ravi Placeholder are charged with two counts of bank fraud."
        doc = Doc("ct-test000000000009", "court", "fraud", text, {}, [
            {"start": 0, "end": len(text), "label": "", "class": "uco-action:Action", "event_types": ["criminal charge"]},
        ])
        result = pipeline.read_doc(doc)
        stored = [a for a in result["assertions"] if a["method"] == "sdk_processor" and a["field"] == "stage"]
        self.assertEqual(len(stored), 1)
        self.assertEqual((stored[0]["span_start"], stored[0]["span_end"]), (0, len(text)), "the offsets still point at the source")
        self.assertNotIn("Sample", stored[0]["span_text"])
        self.assertNotIn("Placeholder", stored[0]["span_text"])
        self.assertIn("[name]", stored[0]["span_text"])
        self.assertIn("are charged with two counts of bank fraud", stored[0]["span_text"])


class PenaltyListTests(unittest.TestCase):
    def test_every_item_of_a_statutory_list_is_exposure(self) -> None:
        text = ("Defendant understands that the statutory maximum sentence that the Court can impose for a violation of "
                "Title 18, United States Code, Section 1343 is: 20 years of imprisonment; a three-year period of supervised "
                "release; a fine of $250,000 or twice the gross gain; and a mandatory special assessment of $100.")
        result = read(text, "court", "ct-test000000000004")[1]
        self.assertEqual({role for role, _ in finals(result, "sentence")}, {"exposure"})
        self.assertIn(("exposure_fine", "250000.0"), finals(result, "money"))

    def test_an_imposed_sentence_is_not_a_penalty_list(self) -> None:
        self.assertFalse(sp.in_penalty_list("Sample was sentenced to 87 months; the maximum penalty is: 20 years", 30))


class EventReadingTests(unittest.TestCase):
    def roles(self, text: str) -> set[str]:
        return {a["role"] for a in read(text)[1]["assertions"] if a["field"] == "event" and a["span_ok"]}

    def test_a_scheduled_sentencing_is_not_a_sentencing(self) -> None:
        result = read("Jane Roe Sample, 45, pleaded guilty today. Sample is scheduled to be sentenced on Sept. 8, 2024.")[1]
        self.assertEqual({final["role"] for final in result["resolutions"]["event"]["finals"]}, {"plea"})
        self.assertIn(("scheduled", "2024-09-08"), finals(result, "date"))

    def test_an_agreement_to_plead_is_not_a_plea(self) -> None:
        self.assertEqual(self.roles("Defendant agrees to plead guilty to Count One."), {"scheduled"})

    def test_if_convicted_is_not_a_conviction(self) -> None:
        self.assertEqual(self.roles("If convicted, the defendant faces up to 20 years in prison."), {"not_event"})

    def test_how_a_charge_was_brought(self) -> None:
        self.assertEqual(self.roles("Jane Roe Sample was charged today in a criminal information with wire fraud."), {"information"})
        self.assertEqual(self.roles("A federal jury convicted Jane Roe Sample today after a five-day trial."), {"verdict"})


class AttributionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.doc, self.result = read(TWO, pub_date="2024-09-10", agency="USAO - Example")
        self.db, self.folder = build_store([(self.doc, self.result)])

    def tearDown(self) -> None:
        self.db.close()
        self.folder.cleanup()

    def owners(self) -> dict[tuple[str, str], list[str]]:
        return {(row["role"], row["value"]): __import__("json").loads(row["people"])
                for row in self.db.execute("SELECT role, value, people FROM attributions WHERE field IN ('sentence', 'money')")}

    def test_each_term_and_amount_goes_to_its_defendant(self) -> None:
        owners = self.owners()
        first, second = owners[("imposed", "87 months")], owners[("imposed", "24 months")]
        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 1)
        self.assertNotEqual(first, second)
        self.assertEqual(owners[("restitution", "1970000.0")], first)
        self.assertEqual(owners[("supervised_release", "three years")], first)
        self.assertEqual(owners[("restitution", "400000.0")], second)

    def test_a_judge_never_owns_a_sentence(self) -> None:
        parties = {final["value"]: final["role"] for final in self.result["resolutions"]["party"]["finals"]}
        for people_ in self.owners().values():
            self.assertTrue(all(parties.get(person) == "defendant" for person in people_))

    def test_names_joined_by_and_share_an_event(self) -> None:
        plea = next(e for e in events.timeline(self.db, cases.case_id_of(self.db, self.doc.record_id)) if e["type"] == "plea")
        self.assertEqual(plea["people"], ["p1", "p2"])
        self.assertEqual((plea["date"], plea["precision"]), ("2024-03", "month"))

    def test_today_is_read_against_the_publication_date(self) -> None:
        timeline = events.timeline(self.db, cases.case_id_of(self.db, self.doc.record_id))
        sentencings = [e for e in timeline if e["type"] == "sentencing"]
        self.assertEqual(len(sentencings), 1, "one sentencing, reported in the lead and again for each defendant")
        self.assertEqual(sentencings[0]["date"], "2024-09-10")
        self.assertEqual(sentencings[0]["people"], ["p1", "p2"])
        self.assertEqual([e["type"] for e in timeline], ["plea", "sentencing"])

    def test_one_defendant_owns_what_no_vote_placed(self) -> None:
        text = "EXAMPLE CITY – A resident was sentenced today to 60 months in prison. Jane Roe Sample, 45, of Exampleton, pleaded guilty in March 2024."
        doc, result = read(text, record_id="pr-test000000000005", pub_date="2024-09-10")
        db, folder = build_store([(doc, result)])
        try:
            row = db.execute("SELECT people, basis FROM attributions WHERE field = 'sentence'").fetchone()
            self.assertEqual((row["people"], row["basis"]), ('["person-1"]', "sole_defendant"))
        finally:
            db.close()
            folder.cleanup()


class LinkingTests(unittest.TestCase):
    def test_one_defendant_across_a_release_and_a_judgment(self) -> None:
        press = read(TWO, record_id="pr-test000000000001", pub_date="2024-06-12", source_url="https://gold.example/pr/x")
        court = read(JUDGMENT, "court", "ct-test000000000002", agency="District Court, Example", docket_number="1:23-cr-00123",
                     press_url="https://gold.example/pr/x")
        from encoding import corpus

        press[0].record_id = press[0].entry["record_id"] = corpus.press_record_id("https://gold.example/pr/x")
        db, folder = build_store([press, court])
        try:
            self.assertEqual(db.execute("SELECT COUNT(DISTINCT case_id) FROM cases").fetchone()[0], 1)
            rows = {(row["record_id"][:2], row["person"]) for row in db.execute("SELECT record_id, person FROM people")}
            self.assertEqual(rows, {("pr", "p1"), ("pr", "p2"), ("ct", "p1")}, "the judgment's defendant is the release's first defendant")
            sentencing = [e for e in events.timeline(db, cases.case_id_of(db, court[0].record_id)) if e["type"] == "sentencing"]
            self.assertEqual(len(sentencing), 1, "the release's 'today' and the judgment's date are one sentencing")
            self.assertEqual(len({r["record_id"] for r in sentencing[0]["reports"]}), 2)
        finally:
            db.close()
            folder.cleanup()

    def test_given_names_that_conflict_are_two_people(self) -> None:
        self.assertTrue(people._compatible(("sample", "jane"), ("sample", "j")))
        self.assertTrue(people._compatible(("sample", "jane"), ("sample", "")))
        self.assertFalse(people._compatible(("sample", "jane"), ("sample", "john")))


class EventOrderTests(unittest.TestCase):
    def report(self, kind, stamp, people_=(), record="r1"):
        return {"type": kind, "date": stamp, "people": list(people_), "basis": "stated", "record_id": record, "span": None, "status": "agreed", "bound": None}

    def test_a_month_and_a_day_in_it_are_one_event(self) -> None:
        merged = events.merge([self.report("plea", "2024-03", ["p1"]), self.report("plea", "2024-03-14", ["p1"], "r2")])
        self.assertEqual([(e["type"], e["date"]) for e in merged], [("plea", "2024-03-14")])

    def test_two_sentencings_on_different_dates_stay_two(self) -> None:
        merged = events.merge([self.report("sentencing", "2023-01-10", ["p1"]), self.report("sentencing", "2024-06-12", ["p1"], "r2")])
        self.assertEqual(len(merged), 2)

    def test_an_undated_event_is_placed_by_its_kind(self) -> None:
        ordered = events.order(events.merge([
            self.report("sentencing", "2024-06-12"), self.report("indictment", "2023-02-01"), self.report("plea", None, record="r2"),
        ]))
        self.assertEqual([(e["type"], e["order_basis"]) for e in ordered], [("indictment", "date"), ("plea", "kind"), ("sentencing", "date")])

    def test_the_offense_is_one_event_at_its_earliest_date(self) -> None:
        merged = events.merge([self.report("offense", "2021-06-30"), self.report("offense", "2019-03", record="r2")])
        self.assertEqual([(e["type"], e["date"]) for e in merged], [("offense", "2019-03")])


class NameListTests(unittest.TestCase):
    def test_a_list_of_names_shares_what_is_said_of_the_last(self) -> None:
        text = "Jane Roe Sample, 45, of Exampleton, Ravi Placeholder, 39, of Exampleton, and Lee Standin, 51, of Exampleton, are charged in an indictment."
        self.assertEqual([hint for _, _, hint in names.iter_people(text)], ["defendant", "defendant", "defendant"])

    def test_a_caption_names_every_defendant(self) -> None:
        text = "UNITED STATES OF AMERICA,\nPlaintiff,\nv. Case No. 1:23-cr-00123\nJANE ROE SAMPLE, and\nRAVI K PLACEHOLDER,\nDefendants.\nINDICTMENT\n"
        self.assertEqual([text[s:e] for s, e, hint in names.iter_people(text) if hint == "defendant"], ["JANE ROE SAMPLE", "RAVI K PLACEHOLDER"])


if __name__ == "__main__":
    unittest.main()
