import json
import unittest

from fieldsurvey import core, create_app
from fieldsurvey.core import EXAMPLE, FormError, Survey, evaluate


class TestExpressions(unittest.TestCase):
    def test_arithmetic_and_logic(self):
        self.assertEqual(evaluate("1 + 2 * 3", {}), 7)
        self.assertTrue(evaluate("age >= 18 and sex == 'F'", {"age": 20, "sex": "F"}))
        self.assertFalse(evaluate("not (a == 1 or b == 2)", {"a": 1}))
        self.assertEqual(evaluate("-a + 1", {"a": 2}), -1)

    def test_missing_answers_are_quiet(self):
        self.assertFalse(evaluate("age >= 18", {}))
        self.assertFalse(evaluate("age + 1 > 0", {}))
        self.assertIsNone(evaluate("1 / zero", {"zero": 0}))

    def test_functions(self):
        self.assertTrue(evaluate("selected(needs, 'food')", {"needs": ["food"]}))
        self.assertFalse(evaluate("selected(needs, 'food')", {}))
        self.assertEqual(evaluate("count(needs)", {"needs": ["a", "b"]}), 2)
        self.assertTrue(evaluate("answered(x)", {"x": 0}))
        self.assertEqual(evaluate("length(name)", {"name": "abc"}), 3)

    def test_mixed_types_do_not_crash(self):
        self.assertFalse(evaluate("a < 3", {"a": "text"}))

    def test_current_value(self):
        self.assertTrue(evaluate(". >= 1 and . <= 5", {}, 3))

    def test_nothing_can_reach_python(self):
        """Attacks that work on eval must simply fail here."""
        for bad in ("__import__('os').system('x')", "().__class__", "open('f')", "[x for x in y]", "a; b"):
            with self.assertRaises((FormError, IndexError)):
                evaluate(bad, {})

    def test_syntax_errors(self):
        for bad in ("(1", "1 +", "foo(1", "1 2"):
            with self.assertRaises((FormError, IndexError)):
                evaluate(bad, {})


class TestDefinition(unittest.TestCase):
    def test_example_loads(self):
        self.assertEqual(len(Survey(json.loads(EXAMPLE)).questions), 6)

    def test_mistakes_are_caught(self):
        for q in ([{"name": "a b", "type": "text"}], [{"name": "a", "type": "photo"}], [{"name": "a", "type": "select_one"}], [{"name": "a", "type": "text"}, {"name": "a", "type": "text"}], [{"name": "a", "type": "text", "relevant": "zzz == 1"}]):
            with self.assertRaises(FormError):
                Survey({"questions": q})


class TestAnswers(unittest.TestCase):
    def setUp(self):
        self.s = Survey(json.loads(EXAMPLE))
        self.ok = {"block": "A", "members": "5", "children": "2", "water": "tap", "needs": ["food"]}

    def test_good(self):
        clean, errors = self.s.check(self.ok)
        self.assertEqual(errors, {})
        self.assertEqual(clean["members"], 5)
        self.assertEqual(clean["needs"], ["food"])

    def test_required(self):
        self.assertIn("block", self.s.check({})[1])

    def test_constraint_uses_other_answers(self):
        _, e = self.s.check({**self.ok, "children": "9"})
        self.assertEqual(e, {"children": "cannot exceed household size"})

    def test_skip_logic(self):
        self.assertNotIn("water_other", [q["name"] for q in self.s.visible({"water": "tap"})])
        self.assertIn("water_other", [q["name"] for q in self.s.visible({"water": "other"})])

    def test_required_only_when_shown(self):
        self.assertEqual(self.s.check(self.ok)[1], {})
        self.assertIn("water_other", self.s.check({**self.ok, "water": "other"})[1])

    def test_answers_to_hidden_questions_are_dropped(self):
        clean, _ = self.s.check({**self.ok, "water_other": "river"})
        self.assertNotIn("water_other", clean)

    def test_a_chain_of_skips(self):
        s = Survey({"questions": [{"name": "a", "type": "text"}, {"name": "b", "type": "text", "relevant": "a == 'y'"}, {"name": "c", "type": "text", "relevant": "b == 'y'"}]})
        self.assertEqual(len(s.visible({"a": "n", "b": "y"})), 1)      # b is hidden, so its stale answer must not show c
        self.assertEqual(len(s.visible({"a": "y", "b": "y"})), 3)

    def test_types(self):
        for field, bad, msg in (("members", "lots", "whole number"), ("water", "river", "not a choice")):
            self.assertIn(msg, self.s.check({**self.ok, field: bad})[1][field])
        d = Survey({"questions": [{"name": "d", "type": "date"}, {"name": "x", "type": "decimal"}, {"name": "m", "type": "select_multiple", "choices": [["a", "A"]]}]})
        e = d.check({"d": "02/11/2026", "x": "abc", "m": ["z"]})[1]
        self.assertEqual(set(e), {"d", "x", "m"})


class TestTables(unittest.TestCase):
    def test_tabulate(self):
        s = Survey(json.loads(EXAMPLE))
        rows = [{"members": 2, "water": "tap", "needs": ["food", "health"]}, {"members": 4, "water": "tap", "needs": ["food"]}, {"members": 9, "water": "well"}]
        t = {x["name"]: x for x in s.tabulate(rows)}
        self.assertEqual((t["members"]["mean"], t["members"]["median"]), (5, 4))
        self.assertEqual(t["water"]["choices"][0], ("Tap stand", 2, 2 / 3))
        self.assertEqual(t["needs"]["answered"], 2)
        self.assertEqual(t["needs"]["choices"][0], ("Food", 2, 1.0))
        self.assertEqual(t["water_other"]["skipped"], 3)

    def test_crosstab(self):
        s = Survey({"questions": [{"name": "a", "type": "select_one", "choices": [["x", "X"], ["y", "Y"]]}, {"name": "b", "type": "select_one", "choices": [["p", "P"], ["q", "Q"]]}]})
        self.assertEqual(s.crosstab([{"a": "x", "b": "q"}, {"a": "x", "b": "q"}, {"a": "y"}], "a", "b"), {"x": {"p": 0, "q": 2}, "y": {"p": 0, "q": 0}})


class TestApp(unittest.TestCase):
    def setUp(self):
        self.a = create_app(":memory:")
        self.url = self.a.post("/new", definition=EXAMPLE).headers["Location"]

    def fill(self, **kw):
        return self.a.post(self.url + "/fill", **kw)

    def test_flow(self):
        self.assertIn("Household needs check", self.a.get(self.url).body.decode())
        r = self.fill(block="A", members=4, water="tap", needs__food=1, finish=1)
        self.assertEqual(r.status, 303)
        page = self.a.get(self.url).body.decode()
        self.assertIn("Mean 4.00", page)
        csv = self.a.get(self.url + "/data.csv").body.decode()
        self.assertIn("block,members", csv)
        self.assertIn("food", csv)

    def test_update_reveals_the_follow_up(self):
        self.assertNotIn("Which other source", self.a.get(self.url + "/fill").body.decode())
        self.assertIn("Which other source", self.fill(block="A", members=4, water="other", update=1).body.decode())

    def test_errors_show_and_nothing_saves(self):
        page = self.fill(block="A", members=99, water="tap", finish=1).body.decode()
        self.assertIn("must be 1 to 40", page)
        self.assertEqual(self.a.one("SELECT COUNT(*) FROM responses"), 0)

    def test_bad_definitions(self):
        self.assertEqual(self.a.post("/new", definition="{oops").status, 400)
        self.assertEqual(self.a.post("/new", definition='{"questions": [{"name": "a", "type": "photo"}]}').status, 400)

    def test_answers_are_escaped(self):
        self.fill(block='<script>x</script>', members=2, water="tap", finish=1)
        page = self.fill(block='"><script>y</script>', update=1).body.decode()
        self.assertNotIn("<script>y", page)


if __name__ == "__main__":
    unittest.main()
