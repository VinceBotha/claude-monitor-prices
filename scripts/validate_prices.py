"""Checks prices.json against the same rules Claude Monitor applies before using it.

Usage: python scripts/validate_prices.py [FILE]   (default: prices.json)

If this passes, the app accepts the file. A file the app rejects would leave every
install on its old prices, so the workflow runs this on every change and before it
opens a price update pull request. Keep it in line with `parse_price_list` in the
app (src-tauri/src/updates.rs).
"""

from __future__ import annotations

import datetime as dt
import json
import math
import re
import sys
from pathlib import Path

FIELDS = {"input", "output", "cacheW5m", "cacheW1h", "cacheRead"}
MODEL_ID = re.compile(r"claude-[a-z0-9.-]+")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
MAX_PRICE = 1000.0
MAX_MODELS = 500


def problems(data: object) -> list[str]:
    """Every rule the file breaks; empty when the app would accept it."""
    if not isinstance(data, dict):
        return ["not a JSON object"]
    out = []
    # `is int`: True and 1.0 equal 1 in Python, but the app (serde u32) rejects them.
    schema = data.get("schema")
    if type(schema) is not int or schema != 1:
        out.append("schema must be 1")
    if data.get("currency") != "USD":
        out.append("currency must be USD")
    # fromisoformat also takes 20261105 and 2026-W45-4; the app only takes YYYY-MM-DD.
    updated = data.get("updated")
    try:
        if not (isinstance(updated, str) and DATE.fullmatch(updated)):
            raise ValueError(updated)
        dt.date.fromisoformat(updated)
    except ValueError:
        out.append("updated must be a YYYY-MM-DD date")
    models = data.get("models")
    if not isinstance(models, dict) or not 1 <= len(models) <= MAX_MODELS:
        return out + [f"models must be an object with 1 to {MAX_MODELS} entries"]
    for model, p in models.items():
        out += model_problems(model, p)
    return out


def model_problems(model: str, p: object) -> list[str]:
    # fullmatch: `$` in match() would also accept a trailing newline.
    if not (8 <= len(model) <= 100 and MODEL_ID.fullmatch(model)):
        return [f"{model}: invalid model id"]
    if not isinstance(p, dict) or set(p) != FIELDS:
        return [f"{model}: needs exactly {sorted(FIELDS)}"]
    bad = [k for k, v in p.items() if not (isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and 0 <= v <= MAX_PRICE)]
    if bad:
        return [f"{model}: invalid {', '.join(sorted(bad))}"]
    if p["input"] == 0 or p["output"] == 0:
        return [f"{model}: input and output prices can't be 0"]
    return []


def main(argv: list[str]) -> int:
    path = Path(argv[0]) if argv else Path(__file__).resolve().parent.parent / "prices.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"{path}: {e}", file=sys.stderr)
        return 1
    found = problems(data)
    for p in found:
        print(p, file=sys.stderr)
    if not found:
        print(f"{path.name}: {len(data['models'])} models OK")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
