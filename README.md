# Amazon Review Analyzer — Free & Open Source

[![Track](https://github.com/pangolinfoapi/amazon-review-analyzer/actions/workflows/track.yml/badge.svg)](https://github.com/pangolinfoapi/amazon-review-analyzer/actions/workflows/track.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org)
[![Built with Pangolinfo](https://img.shields.io/badge/built%20with-Pangolinfo-blue)](https://www.pangolinfo.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> **Free & open-source Amazon review analyzer.** Fetch product reviews, score sentiment,
> and surface the themes customers complain about vs. praise — powered by the
> [Pangolinfo Amazon Scraper API](https://www.pangolinfo.com/amazon-scraper-api/).

Part of the [Pangolinfo open-source ecosystem](related-projects.md). A tiny Python tool
(zero dependencies) that pulls Amazon reviews for the ASINs you care about, runs a
**dependency-free lexicon sentiment analyzer** over the review text, and records rating
distribution + sentiment + top complaint/praise themes every day with GitHub Actions.
Great for **Amazon review analysis**, **review sentiment** monitoring, and
**competitor research** — no NLP libraries required.

---

## Table of contents

- [Why](#why)
- [Features](#features)
- [Architecture](#architecture)
- [Quick start](#quick-start)
- [Commands](#commands)
- [Configuration](#configuration-reviewsjson)
- [How it works](#how-it-works)
- [🌐 Pangolinfo ecosystem](#-pangolinfo-ecosystem)
- [FAQ](#faq)
- [Roadmap](#roadmap)

---

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

---

## Features

- 📝 **Review fetch** — pulls review text + star ratings via the Pangolinfo API
- 😊 **Sentiment scoring** — lexicon-based pos / neu / neg (no ML dependency)
- 🔥 **Theme mining** — top complaint words vs praise words per ASIN
- 📊 **Rating distribution** — 1★–5★ counts stored daily
- 🗄️ **SQLite history** — watch sentiment shift as you iterate your product
- 🤖 **Free daily automation** — GitHub Actions commits the report every day
- 🧩 **Zero dependencies** — Python standard library only

---

## Architecture

```
        ┌─────────────────────────────────────────────┐
        │  amazon-review-analyzer (this repo)          │
        │  amazon_review_analyzer.py · SQLite          │
        └───────────────────┬─────────────────────────┘
                            │  streamable-HTTP (MCP)
                            │  tools/call → get_amazon_reviews
                            ▼
        ┌─────────────────────────────────────────────┐
        │   Pangolinfo MCP server                       │
        │   mcp.pangolinfo.com/mcp  (Bearer JWT)        │
        └───────────────────┬─────────────────────────┘
                            │  proxy → Amazon reviews
                            ▼
              Amazon reviews (JSON)
```

---

## Quick start

```bash
git clone https://github.com/pangolinfoapi/amazon-review-analyzer.git
cd amazon-review-analyzer

export PANGOLIN_TOKEN="your-free-key-from-tool.pangolinfo.com"

# edit reviews.json — replace the placeholder ASINs with your own
python amazon_review_analyzer.py run
python amazon_review_analyzer.py report
```

The bundled `reviews.json` ships with **placeholder ASINs** — replace them with real
product ASINs (the 10-char code in the URL, e.g. `B0ABCD1234`) before running.

---

## Commands

| Command | What it does |
|---|---|
| `python amazon_review_analyzer.py init` | Create `reviews.json` from the example file |
| `python amazon_review_analyzer.py run` | Fetch reviews for every ASIN and store stats |
| `python amazon_review_analyzer.py history` | Print tracked ASINs and their stats |
| `python amazon_review_analyzer.py report` | Generate `reports/latest.md` with sentiment + themes |

---

## Configuration (`reviews.json`)

```json
[
  { "label": "my-product", "asin": "B0ABCD1234", "pages": 3 }
]
```

- `asin` *(str, required)* — the Amazon ASIN to analyze.
- `pages` *(int)* — how many review pages to fetch (default 3).
- `label` *(str)* — a friendly name shown in reports.

---

## How it works

The script talks to the **Pangolinfo MCP endpoint** (`mcp.pangolinfo.com/mcp`) over
streamable HTTP — the same Model Context Protocol server AI assistants use — and calls
the `get_amazon_reviews` tool. Review text is scored with a small positive/negative word
lexicon (no machine-learning dependencies), and results are stored in a local SQLite
database (`data/reviews.db`). **Python standard library only.**

> Prefer no code? Connect Claude / Cursor / Windsurf / ChatGPT to
> `https://mcp.pangolinfo.com/mcp` and call `get_amazon_reviews` directly.

Full setup + automation guide: [docs/SETUP.md](docs/SETUP.md).

---

## 🌐 Pangolinfo ecosystem

### 🛰️ More free tools by [@pangolinfoapi](https://github.com/pangolinfoapi)

- [amazon-keyword-rank-tracker](https://github.com/pangolinfoapi/amazon-keyword-rank-tracker) —
  track your Amazon keyword rankings daily
- [amazon-niche-finder](https://github.com/pangolinfoapi/amazon-niche-finder) —
  discover low-competition Amazon niches
- [google-trends-tracker](https://github.com/pangolinfoapi/google-trends-tracker) —
  monitor keyword interest with Google Trends

### 🏗️ Built on the official Pangolinfo projects ([by @Pangolin-spg](https://github.com/Pangolin-spg))

- [pangolinfo-amazon-scraper](https://github.com/Pangolin-spg/pangolinfo-amazon-scraper)
  — official Python SDK for the Pangolinfo Scrape API (this tool's data source: reviews)
- [amazon-walmart-shopify-scrape-api](https://github.com/Pangolin-spg/amazon-walmart-shopify-scrape-api)
  ⭐ 56 — the underlying Scrape API for Amazon, Walmart, Shopify, Shopee, eBay
- [pangolinfo-amazon-scraper-cli](https://github.com/Pangolin-spg/pangolinfo-amazon-scraper-cli)
  ⭐ 8 — Agent/AI-friendly CLI for Amazon data collection
- [clawdbot-competitor-monitor](https://github.com/Pangolin-spg/clawdbot-competitor-monitor)
  ⭐ 3 — automate Amazon competitor analysis

> Full map of official Pangolinfo projects, skills and the live MCP endpoint:
> [related-projects.md](related-projects.md).

---

## FAQ

**Is the sentiment model accurate enough?** The built-in lexicon scorer is lightweight
and transparent (no black box). For production-grade NLP, pipe the fetched reviews into
your own model — the `run` step already stores clean review text in SQLite.

**Is my API key safe?** Yes — env var locally, encrypted Actions secret on GitHub, never
committed.

**How many ASINs can I analyze for free?** 200 free calls; one `run` makes ~1 call per
ASIN in `reviews.json`.

**Is this affiliated with Amazon?** No. Independent open-source tool reading public
Amazon review data via the Pangolinfo API.

---

## Roadmap

- [ ] Aspect-based sentiment (price / quality / shipping)
- [ ] Time-series sentiment charts
- [ ] Competitor review comparison
- [ ] Export to CSV / Notion

---

## Contributing

Ideas and PRs welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). Ecosystem map:
[related-projects.md](related-projects.md).

## License

MIT © 2026 pangolinfo
