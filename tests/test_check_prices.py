import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import check_prices as cp  # noqa: E402

PAGE = """# Pricing

## Model pricing

| Model | Base input tokens | 5m cache writes | 1h cache writes | Cache hits and refreshes | Output tokens |
| :---- | :---------------- | :-------------- | :-------------- | :----------------------- | :------------ |
| Claude Fable 5.1 | $10 / MTok | $12.50 / MTok | $20 / MTok | $0.25 / MTok<sup>1</sup> | $50 / MTok |
| Claude Opus 5.5 | $4 / MTok | $5 / MTok | $8 / MTok | $0.20 / MTok<sup>2</sup> | $20 / MTok |
| Claude Opus 4 ([retired](https://example.com)) | $15 / MTok | $18.75 / MTok | $30 / MTok | $1.50 / MTok | $75 / MTok |
| Claude Sonnet 5 | $2 / MTok<sup>3</sup> | $2.50 / MTok | $4 / MTok | $0.20 / MTok | $10 / MTok<sup>3</sup> |
| Claude Haiku 5.5 (for prompts up to 100,000 tokens) | $0.10 / MTok | $0.125 / MTok | $0.20 / MTok | $0.01 / MTok | $0.50 / MTok |
| Claude Haiku 5.5 (for prompts over 100,000 tokens) | $0.50 / MTok | $0.625 / MTok | $1 / MTok | $0.05 / MTok | $2.50 / MTok |

## Batch processing

| Model | Batch input | Batch output |
| :---- | :---------- | :----------- |
| Claude Opus 5.5 | $2 / MTok | $10 / MTok |
"""


class ParseTests(unittest.TestCase):
    def test_parses_the_model_table_only(self):
        page = cp.parse_page(PAGE)
        self.assertEqual(sorted(page), ["claude-fable-5-1", "claude-haiku-5-5", "claude-opus-4", "claude-opus-5-5", "claude-sonnet-5"])
        self.assertEqual(page["claude-opus-5-5"], {"input": 4, "cacheW5m": 5, "cacheW1h": 8, "cacheRead": 0.2, "output": 20})

    def test_haiku_uses_the_short_prompt_rate(self):
        self.assertEqual(cp.parse_page(PAGE)["claude-haiku-5-5"]["input"], 0.10)

    def test_footnotes_and_links_are_ignored(self):
        page = cp.parse_page(PAGE)
        self.assertEqual(page["claude-sonnet-5"]["output"], 10)
        self.assertEqual(page["claude-opus-4"]["input"], 15)

    def test_changed_columns_fail(self):
        with self.assertRaises(cp.ParseError):
            cp.parse_page(PAGE.replace("Output tokens |", "Output |", 1))

    def test_missing_section_fails(self):
        with self.assertRaises(cp.ParseError):
            cp.parse_page("# Nothing here")

    def test_bad_price_fails(self):
        with self.assertRaises(cp.ParseError):
            cp.parse_page(PAGE.replace("$4 / MTok", "contact sales", 1))

    def test_too_few_models_fails(self):
        short = "\n".join(l for l in PAGE.splitlines() if "Opus" not in l and "Fable" not in l)
        with self.assertRaises(cp.ParseError):
            cp.parse_page(short)


class DiffTests(unittest.TestCase):
    def test_reports_added_and_changed(self):
        cur = {"claude-opus-5-5": {"input": 4, "output": 20, "cacheW5m": 5, "cacheW1h": 8, "cacheRead": 0.4}}
        new = {
            "claude-opus-5-5": {"input": 4, "output": 20, "cacheW5m": 5, "cacheW1h": 8, "cacheRead": 0.2},
            "claude-x-1": {"input": 1, "output": 2, "cacheW5m": 1.25, "cacheW1h": 2, "cacheRead": 0.1},
        }
        out = cp.diff(cur, new)
        self.assertEqual(len(out), 2)
        self.assertIn("Changed `claude-opus-5-5`: cacheRead $0.4 → $0.2", out[0])
        self.assertIn("Added `claude-x-1`", out[1])

    def test_no_changes(self):
        same = {"m": {"input": 1, "output": 2, "cacheW5m": 1.25, "cacheW1h": 2, "cacheRead": 0.1}}
        self.assertEqual(cp.diff(same, same), [])


if __name__ == "__main__":
    unittest.main()
