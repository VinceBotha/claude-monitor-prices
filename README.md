# Claude Monitor prices

The model price list that [Claude Monitor](https://vincebotha.atlassian.net/wiki/spaces/AMA/pages/3178497) installs check once a day (AMA-5).

- `prices.json`: Anthropic API list prices in **USD per million tokens**, per model id. Fields: `input`, `output`, `cacheW5m` (5-minute cache writes), `cacheW1h` (1-hour cache writes), `cacheRead` (cache hits).
- The app downloads `https://raw.githubusercontent.com/VinceBotha/claude-monitor-prices/main/prices.json`. It adds new models and updates the prices the user hasn't edited. Prices a user edited or removed are never overwritten.
- `.github/workflows/check-prices.yml` runs daily. It compares `prices.json` with [Anthropic's pricing page](https://platform.claude.com/docs/en/about-claude/pricing) and opens a pull request when they differ. **Review the values against the page before merging**: whatever is on `main` reaches every install.
- Haiku 5.5 uses its rate for prompts up to 100,000 tokens. Models the page no longer lists stay in the file, so old transcripts keep a price.

Only public list prices live here; the app's code is in a private repository.

Run the checks locally:

```
python -m unittest discover -s tests
python scripts/check_prices.py          # report differences
python scripts/check_prices.py --write  # also rewrite prices.json and changes.md
```
