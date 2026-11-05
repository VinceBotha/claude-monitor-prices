import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import check_prices as cp  # noqa: E402
import validate_prices  # noqa: E402

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
        # Both Haiku 5.5 rows would map to one id; only the <=100K row is used.
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

    def test_table_must_have_rows(self):
        with self.assertRaises(cp.ParseError):
            cp.parse_page("## Model pricing\n\nNo table here.\n\n## Other\n\n| a | b |\n")

    def test_bad_price_fails(self):
        with self.assertRaises(cp.ParseError):
            cp.parse_page(PAGE.replace("$4 / MTok", "contact sales", 1))

    def test_price_over_the_limit_fails(self):
        with self.assertRaises(cp.ParseError):
            cp.parse_page(PAGE.replace("$75 / MTok", "$7500 / MTok", 1))

    def test_row_with_wrong_cell_count_fails(self):
        with self.assertRaises(cp.ParseError):
            cp.parse_page(PAGE.replace(" $12.50 / MTok |", "", 1))

    def test_too_few_models_fails(self):
        short = "\n".join(line for line in PAGE.splitlines() if "Opus" not in line and "Fable" not in line)
        with self.assertRaises(cp.ParseError):
            cp.parse_page(short)

    def test_model_ids(self):
        self.assertEqual(cp.model_id("Claude Opus 4 ([retired](x))"), "claude-opus-4")
        self.assertEqual(cp.model_id("Claude Opus 5.5"), "claude-opus-5-5")
        self.assertIsNone(cp.model_id("Claude Haiku 5.5 (for prompts over 100,000 tokens)"))
        self.assertIsNone(cp.model_id("Some other row"))


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


class MainTests(unittest.TestCase):
    """main() against a temporary repo folder and a saved page."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        patcher = mock.patch.object(cp, "ROOT", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.page = self.root / "page.md"
        self.page.write_text(PAGE, encoding="utf-8")

    def write_prices(self, models):
        data = {"schema": 1, "currency": "USD", "unit": "per million tokens", "updated": "2026-01-01", "source": "", "models": models}
        (self.root / "prices.json").write_text(json.dumps(data), encoding="utf-8")

    def run_main(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cp.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def prices(self):
        return json.loads((self.root / "prices.json").read_text(encoding="utf-8"))

    def test_matching_file_exits_0_and_writes_nothing(self):
        self.write_prices(cp.parse_page(PAGE))
        code, out, _ = self.run_main("--page", str(self.page), "--write")
        self.assertEqual(code, 0)
        self.assertIn("matches", out)
        self.assertFalse((self.root / "changes.md").exists())
        self.assertEqual(self.prices()["updated"], "2026-01-01")

    def test_differences_without_write_only_report(self):
        self.write_prices({})
        code, out, _ = self.run_main("--page", str(self.page))
        self.assertEqual(code, 1)
        self.assertIn("Added `claude-opus-5-5`", out)
        self.assertEqual(self.prices()["models"], {})
        self.assertFalse((self.root / "changes.md").exists())

    def test_write_merges_keeps_old_models_and_writes_changes(self):
        old = {"input": 3, "output": 15, "cacheW5m": 3.75, "cacheW1h": 6, "cacheRead": 0.3}
        stale = dict(cp.parse_page(PAGE)["claude-opus-5-5"], cacheRead=0.4)
        self.write_prices({"claude-retired-1": old, "claude-opus-5-5": stale})
        code, _, _ = self.run_main("--page", str(self.page), "--write")
        self.assertEqual(code, 1)
        data = self.prices()
        self.assertEqual(list(data["models"]), sorted(data["models"]), "sorted by model id")
        self.assertEqual(data["models"]["claude-retired-1"], old, "models the page no longer lists are kept")
        self.assertEqual(data["models"]["claude-opus-5-5"]["cacheRead"], 0.2)
        self.assertEqual(list(data["models"]["claude-opus-5-5"]), list(cp.FIELDS), "fields in a fixed order")
        self.assertEqual(data["source"], cp.SOURCE_URL)
        self.assertNotEqual(data["updated"], "2026-01-01")
        changes = (self.root / "changes.md").read_text(encoding="utf-8")
        self.assertIn("Changed `claude-opus-5-5`: cacheRead $0.4 → $0.2", changes)
        self.assertIn("Added `claude-fable-5-1`", changes)
        self.assertEqual(validate_prices.problems(data), [], "the rewritten file passes the app's rules")

    def test_unreadable_page_exits_2(self):
        self.write_prices({})
        code, _, err = self.run_main("--page", str(self.root / "missing.md"))
        self.assertEqual(code, 2)
        self.assertIn("Couldn't read the pricing page", err)
        self.page.write_text("# moved", encoding="utf-8")
        self.assertEqual(self.run_main("--page", str(self.page))[0], 2)

    def test_fetch_only_takes_https(self):
        with self.assertRaises(ValueError):
            cp.fetch("file:///etc/passwd")

    def test_fetch_reads_the_page(self):
        class Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        with mock.patch.object(cp.urllib.request, "urlopen", return_value=Resp(PAGE.encode())) as op:
            self.assertEqual(cp.fetch(cp.PAGE_URL), PAGE)
        self.assertEqual(op.call_args.args[0].full_url, cp.PAGE_URL)
        self.assertEqual(op.call_args.kwargs["timeout"], 30)

    def test_main_fetches_when_no_page_is_given(self):
        self.write_prices(cp.parse_page(PAGE))
        with mock.patch.object(cp, "fetch", return_value=PAGE) as f:
            self.assertEqual(self.run_main()[0], 0)
        f.assert_called_once_with(cp.PAGE_URL)


if __name__ == "__main__":
    unittest.main()
