# Amazon Review Analyzer

> **Free & open-source Amazon review analyzer.** Fetch product reviews, score
> sentiment, and surface the themes customers complain about vs. praise — powered
> by the [Pangolinfo Amazon Scraper API](https://www.pangolinfo.com/amazon-scraper-api/).

A tiny Python tool (zero dependencies) that pulls Amazon reviews for the ASINs you
care about, runs a **dependency-free lexicon sentiment analyzer** over the review
text, and records rating distribution + sentiment + top complaint/praise themes
every day with GitHub Actions. Great for **Amazon review analysis**, **review
sentiment** monitoring, and **competitor research** — no NLP libraries required.

## Why

- 🗂️ **Amazon review analysis tool** — one command pulls reviews and summarizes them.
- 😊 **Review sentiment in Python** — a built-in lexicon scorer labels each review
  positive / neutral / negative without any external model.
- 🔥 **Theme mining** — extracts the most frequent words in negative vs positive
  reviews, so you see *what* people complain about at a glance.
- 📊 **Daily snapshots** — GitHub Actions commits rating/sentiment history, so the
  repo becomes a tracked dataset over time.
- 🆓 **Free tier** — 200 free API calls at
  [tool.pangolinfo.com](https://tool.pangolinfo.com).

## Quick start

```bash
git clone https://github.com/pangolinfoapi/amazon-review-analyzer.git
cd amazon-review-analyzer

export PANGOLIN_TOKEN="your-free-key-from-tool.pangolinfo.com"

# edit reviews.json — replace the placeholder ASINs with your own
python amazon_review_analyzer.py run
python amazon_review_analyzer.py report
```

The bundled `reviews.json` ships with **placeholder ASINs** — replace them with
real product ASINs (the 10-char code in the URL, e.g. `B0ABCD1234`) before running.

## Commands

| Command | What it does |
|---|---|
| `python amazon_review_analyzer.py init` | Create `reviews.json` from the example file |
| `python amazon_review_analyzer.py run` | Fetch reviews for every ASIN and store stats |
| `python amazon_review_analyzer.py history` | Print tracked ASINs and their stats |
| `python amazon_review_analyzer.py report` | Generate `reports/latest.md` with sentiment + themes |

## Configuration (`reviews.json`)

```json
[
  { "label": "my-product", "asin": "B0ABCD1234", "pages": 3 }
]
```

- `asin` *(str, required)* — the Amazon ASIN to analyze.
- `pages` *(int)* — how many review pages to fetch (default 3).
- `label` *(str)* — a friendly name shown in reports.

## How it works

The script talks to the **Pangolinfo MCP endpoint** (`mcp.pangolinfo.com/mcp`) over
streamable HTTP — the same Model Context Protocol server AI assistants use — and
calls the `get_amazon_reviews` tool. Review text is scored with a small positive/
negative word lexicon (no machine-learning dependencies), and results are stored in
a local SQLite database (`data/reviews.db`). **Python standard library only.**

## Related open-source tools by pangolinfo

- [amazon-keyword-rank-tracker](https://github.com/pangolinfoapi/amazon-keyword-rank-tracker) — track your Amazon keyword rankings daily
- [amazon-niche-finder](https://github.com/pangolinfoapi/amazon-niche-finder) — discover low-competition Amazon niches
- [google-trends-tracker](https://github.com/pangolinfoapi/google-trends-tracker) — monitor keyword interest with Google Trends

All powered by [Pangolinfo](https://www.pangolinfo.com) — get a free API key at
[tool.pangolinfo.com](https://tool.pangolinfo.com).

## License

MIT © 2026 pangolinfo
