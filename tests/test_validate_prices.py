import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import validate_prices as vp

GOOD = {"input": 4, "output": 20, "cacheW5m": 5, "cacheW1h": 8, "cacheRead": 0.2}


def doc(**over):
    d = {"schema": 1, "currency": "USD", "updated": "2026-11-05", "models": {"claude-opus-5-5": dict(GOOD)}}
    d.update(over)
    return d


def quiet(f, *args):
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        return f(*args)


class ValidateTests(unittest.TestCase):
    def test_good_file(self):
        self.assertEqual(vp.problems(doc()), [])

    def test_the_repo_file_is_valid(self):
        self.assertEqual(quiet(vp.main, []), 0)

    def test_top_level_rules(self):
        self.assertEqual(vp.problems([]), ["not a JSON object"])
        self.assertIn("schema must be 1", vp.problems(doc(schema=2)))
        self.assertIn("currency must be USD", vp.problems(doc(currency="EUR")))
        self.assertIn("updated must be a YYYY-MM-DD date", vp.problems(doc(updated="soon")))
        self.assertTrue(vp.problems(doc(models={})))
        self.assertTrue(vp.problems(doc(models=[1])))

    def test_matches_the_apps_stricter_parsing(self):
        # Each of these passes a loose Python check but the app rejects it.
        self.assertIn("schema must be 1", vp.problems(doc(schema=True)))
        self.assertIn("schema must be 1", vp.problems(doc(schema=1.0)))
        for date in ["20261105", "2026-W45-4", "2026-11-5", "2026-13-01", 20261105]:
            with self.subTest(date=date):
                self.assertIn("updated must be a YYYY-MM-DD date", vp.problems(doc(updated=date)))
        self.assertEqual(len(vp.problems(doc(models={"claude-x-1\n": GOOD}))), 1)

    def test_model_rules(self):
        cases = {
            "gpt-5-turbo": GOOD,
            "claude-<x>": GOOD,
            "claude-": GOOD,
            "claude-opus-5-5": {**GOOD, "input": -1},
            "claude-opus-5-6": {**GOOD, "output": 1e9},
            "claude-opus-5-7": {**GOOD, "cacheRead": "0.2"},
            "claude-opus-5-8": {**GOOD, "cacheRead": True},
            "claude-opus-5-9": {k: v for k, v in GOOD.items() if k != "cacheW1h"},
            "claude-opus-6-0": {**GOOD, "input": 0},
            "claude-opus-6-1": {**GOOD, "output": 0},
        }
        for model, p in cases.items():
            with self.subTest(model=model):
                self.assertEqual(len(vp.problems(doc(models={model: p}))), 1)

    def test_free_cache_prices_are_allowed(self):
        self.assertEqual(vp.problems(doc(models={"claude-opus-5-5": {**GOOD, "cacheRead": 0}})), [])

    def test_main_on_files(self):
        with tempfile.TemporaryDirectory() as t:
            f = Path(t) / "p.json"
            f.write_text(json.dumps(doc()), encoding="utf-8")
            self.assertEqual(quiet(vp.main, [str(f)]), 0)
            f.write_text(json.dumps(doc(currency="EUR")), encoding="utf-8")
            self.assertEqual(quiet(vp.main, [str(f)]), 1)
            f.write_text("{not json", encoding="utf-8")
            self.assertEqual(quiet(vp.main, [str(f)]), 1)
            self.assertEqual(quiet(vp.main, [str(Path(t) / "missing.json")]), 1)


if __name__ == "__main__":
    unittest.main()
