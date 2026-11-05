"""Compares prices.json with Anthropic's public pricing page.

Usage: python scripts/check_prices.py [--write] [--page FILE]

Reads the "Model pricing" table from the pricing page (markdown), maps each row to a
model id (Claude Opus 5.5 -> claude-opus-5-5), and prints what differs from prices.json.
With --write it also rewrites prices.json and writes the change summary to changes.md,
which the scheduled workflow uses as the pull request body.

Exit codes: 0 no differences, 1 differences found, 2 the page couldn't be read or parsed.
Models in prices.json that the page no longer lists are kept: Claude Monitor still needs
prices for old transcripts.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import urllib.request
from pathlib import Path

PAGE_URL = "https://platform.claude.com/docs/en/about-claude/pricing.md"
SOURCE_URL = "https://platform.claude.com/docs/en/about-claude/pricing"
ROOT = Path(__file__).resolve().parent.parent
PRICES = ROOT / "prices.json"
FIELDS = ("input", "output", "cacheW5m", "cacheW1h", "cacheRead")
# The page table's column order after the model name.
PAGE_COLUMNS = ("input", "cacheW5m", "cacheW1h", "cacheRead", "output")
# A real table lists far more; fewer means the page layout changed and parsing went wrong.
MIN_MODELS = 5
MAX_PRICE = 1000.0

MONEY = re.compile(r"^\$(\d+(?:\.\d+)?)\s*/\s*MTok$")
NAME = re.compile(r"^Claude ([A-Za-z]+) (\d+)(?:\.(\d+))?$")


class ParseError(Exception):
    pass


def model_id(name: str) -> str | None:
    """'Claude Opus 5.5 ([retired ...](...))' -> 'claude-opus-5-5'. None for rows to skip."""
    # Haiku 5.5 has two rows; Claude Monitor uses the <=100K-token prompt rate.
    if "over 100,000 tokens" in name:
        return None
    base = re.sub(r"\s*\(.*$", "", name).strip()
    m = NAME.match(base)
    if not m:
        return None
    family, major, minor = m.group(1).lower(), m.group(2), m.group(3)
    return f"claude-{family}-{major}" + (f"-{minor}" if minor else "")


def money(cell: str) -> float:
    text = re.sub(r"<sup>.*?</sup>", "", cell).strip()
    m = MONEY.match(text)
    if not m:
        raise ParseError(f"not a price: {cell!r}")
    value = float(m.group(1))
    if not 0 <= value <= MAX_PRICE:
        raise ParseError(f"price out of range: {cell!r}")
    return value


def parse_page(markdown: str) -> dict[str, dict[str, float]]:
    """The first table under '## Model pricing', as {model id: prices}."""
    start = markdown.find("## Model pricing")
    if start < 0:
        raise ParseError("no '## Model pricing' section")
    lines = markdown[start:].splitlines()[1:]
    rows: list[list[str]] = []
    in_table = False
    for line in lines:
        if line.startswith("|"):
            in_table = True
            rows.append([c.strip() for c in line.strip().strip("|").split("|")])
        elif in_table:
            break
        elif line.startswith("## "):
            break
    if len(rows) < 3:
        raise ParseError("no pricing table")
    header = [h.lower() for h in rows[0]]
    expected = ["model", "base input tokens", "5m cache writes", "1h cache writes", "cache hits and refreshes", "output tokens"]
    if header != expected:
        raise ParseError(f"unexpected columns: {rows[0]}")
    out: dict[str, dict[str, float]] = {}
    for row in rows[2:]:
        if len(row) != len(expected):
            raise ParseError(f"bad row: {row}")
        mid = model_id(row[0])
        if mid is None:
            continue
        out[mid] = {col: money(cell) for col, cell in zip(PAGE_COLUMNS, row[1:])}
    if len(out) < MIN_MODELS:
        raise ParseError(f"only {len(out)} models parsed")
    return out


def diff(current: dict[str, dict[str, float]], page: dict[str, dict[str, float]]) -> list[str]:
    changes = []
    for mid in sorted(page):
        new = page[mid]
        old = current.get(mid)
        if old is None:
            changes.append(f"- Added `{mid}`: " + ", ".join(f"{f} ${new[f]:g}" for f in FIELDS))
            continue
        moved = [f"{f} ${old.get(f, 0):g} → ${new[f]:g}" for f in FIELDS if old.get(f) != new[f]]
        if moved:
            changes.append(f"- Changed `{mid}`: " + ", ".join(moved))
    return changes


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "claude-monitor-prices-check"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read(2_000_000).decode("utf-8")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="rewrite prices.json and changes.md when they differ")
    ap.add_argument("--page", help="read the page from a file instead of the web")
    args = ap.parse_args(argv)
    try:
        page_md = Path(args.page).read_text(encoding="utf-8") if args.page else fetch(PAGE_URL)
        page = parse_page(page_md)
    except (ParseError, OSError) as e:
        print(f"Couldn't read the pricing page: {e}", file=sys.stderr)
        return 2

    data = json.loads(PRICES.read_text(encoding="utf-8"))
    changes = diff(data["models"], page)
    if not changes:
        print("prices.json matches the pricing page.")
        return 0
    print("\n".join(changes))
    if args.write:
        models = {**data["models"], **page}
        data["models"] = {k: models[k] for k in sorted(models)}
        data["updated"] = dt.date.today().isoformat()
        data["source"] = SOURCE_URL
        PRICES.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        (ROOT / "changes.md").write_text(
            f"Anthropic's [pricing page]({SOURCE_URL}) differs from `prices.json`:\n\n" + "\n".join(changes) + "\n\n"
            "Check the values against the page before merging. Once merged, Claude Monitor picks them up within a day.\n",
            encoding="utf-8",
        )
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
