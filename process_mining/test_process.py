"""Tests for process mining. Small invented logs; no collected data is read.

    .venv/bin/python -m unittest process_mining.test_process -v
"""

from __future__ import annotations

import unittest
from collections import Counter

from process_mining import conform, discover
from process_mining.log import Trace


def trace(*events: tuple[str, str | None]) -> Trace:
    return Trace("case-x", "p1", [
        {"type": kind, "date": stamp, "precision": "none" if not stamp else "month" if len(stamp) == 7 else "day",
         "order_basis": "date" if stamp else "kind"} for kind, stamp in events])


class DiscoveryTests(unittest.TestCase):
    def test_sequence_choice_and_parallel(self) -> None:
        # The running example of the Inductive Miner papers: a, then (b and c in either order) or e, then d.
        log = Counter({("a", "b", "c", "d"): 3, ("a", "c", "b", "d"): 2, ("a", "e", "d"): 1})
        tree = discover.mine(log)
        self.assertEqual(tree, ("seq", [("act", "a"), ("xor", [("par", [("act", "b"), ("act", "c")]), ("act", "e")]), ("act", "d")]))
        self.assertEqual(discover.language(tree), set(log))

    def test_a_loop(self) -> None:
        tree = discover.mine(Counter({("a", "b"): 5, ("a", "b", "c", "a", "b"): 2}))
        self.assertEqual(tree, ("loop", [("seq", [("act", "a"), ("act", "b")]), ("act", "c")]))

    def test_a_step_some_traces_skip(self) -> None:
        tree = discover.mine(Counter({("charge", "plea", "sentencing"): 6, ("charge", "sentencing"): 2}))
        self.assertEqual(tree, ("seq", [("act", "charge"), ("xor", [discover.TAU, ("act", "plea")]), ("act", "sentencing")]))

    def test_with_no_noise_filter_every_trace_replays(self) -> None:
        log = Counter({("i", "p", "s"): 9, ("i", "v", "s"): 2, ("p", "s"): 5, ("s", "p"): 1, ("a", "i"): 3, ("s", "s"): 1, ("i",): 4})
        result = conform.fitness(log, discover.mine(log, 0.0))
        self.assertEqual(result["fitness"], 1.0)
        self.assertEqual(result["traces_fitting_exactly"], 1.0)

    def test_noise_filtering_drops_a_rare_order_from_the_model(self) -> None:
        log = Counter({("plea", "sentencing"): 40, ("sentencing", "plea"): 1})
        self.assertEqual(discover.mine(log, 0.2), ("seq", [("act", "plea"), ("act", "sentencing")]))
        self.assertNotEqual(discover.mine(log, 0.0), ("seq", [("act", "plea"), ("act", "sentencing")]))

    def test_the_same_log_gives_the_same_tree(self) -> None:
        log = Counter({("a", "b", "c"): 2, ("a", "c", "b"): 2, ("d",): 1, ("a", "b"): 1})
        self.assertEqual(discover.mine(log, 0.1), discover.mine(Counter(dict(reversed(list(log.items())))), 0.1))

    def test_a_model_too_large_to_list_says_so(self) -> None:
        wide = ("par", [("act", str(i)) for i in range(12)])
        with self.assertRaises(discover.TooLarge):
            discover.language(wide)


class AlignmentTests(unittest.TestCase):
    ALLOWED = {("charge", "plea", "sentencing"), ("charge", "verdict", "sentencing")}

    def test_a_trace_the_model_allows_costs_nothing(self) -> None:
        self.assertEqual(conform.align(("charge", "plea", "sentencing"), self.ALLOWED)["cost"], 0)

    def test_an_extra_step_and_a_missing_step(self) -> None:
        result = conform.align(("plea", "verdict", "sentencing"), self.ALLOWED)
        self.assertEqual(result["cost"], 2)
        self.assertIn({"move": "model", "activity": "charge"}, result["moves"])
        self.assertEqual(sum(1 for move in result["moves"] if move["move"] == "log"), 1)
        self.assertAlmostEqual(result["fitness"], 1 - 2 / 6, places=4)


class ProcedureTests(unittest.TestCase):
    def kinds(self, *events) -> list[str]:
        return [found["kind"] for found in conform.check_order(trace(*events))]

    def test_a_sentencing_dated_before_the_plea(self) -> None:
        self.assertEqual(self.kinds(("sentencing", "2024-01-25"), ("plea", "2024-03-05")), ["order"])

    def test_a_month_that_may_hold_the_other_date_is_not_a_violation(self) -> None:
        self.assertEqual(self.kinds(("plea", "2024-03"), ("sentencing", "2024-03-20")), [])

    def test_a_resentencing_is_a_repeat(self) -> None:
        self.assertEqual(self.kinds(("plea", "2022-05-02"), ("sentencing", "2022-11-01"), ("sentencing", "2024-02-09")), ["repeat"])
        self.assertEqual(self.kinds(("sentencing", "2022-11"), ("sentencing", "2022-11-01")), [], "a month and a day in it are one date")

    def test_a_plea_and_a_verdict(self) -> None:
        self.assertEqual(self.kinds(("plea", "2022-05-02"), ("verdict", "2022-11-01"), ("sentencing", None)), ["plea_and_verdict"])

    def test_a_missing_step_is_not_a_departure(self) -> None:
        self.assertEqual(self.kinds(("sentencing", "2024-06-12")), [])
        self.assertEqual(self.kinds(("arrest", "2023-06-01"), ("indictment", "2023-05-20"), ("plea", "2024-01-09")), [], "an arrest may follow an indictment")


if __name__ == "__main__":
    unittest.main()
