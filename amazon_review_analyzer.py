#!/usr/bin/env python3
"""Amazon Review Analyzer — fetch reviews, score sentiment, surface themes.

Uses the Pangolinfo MCP endpoint (https://mcp.pangolinfo.com/mcp) — the same
Model Context Protocol server AI assistants use — to call ``get_amazon_reviews``
for a set of ASINs, runs a dependency-free lexicon sentiment analyzer over the
review text, and stores the results in SQLite so you can watch sentiment and
rating distribution evolve over time.

Zero dependencies: Python 3.10+ standard library only.

Commands:
    init      Create reviews.json from the example file
    run       Fetch reviews for every configured ASIN and store stats
    history   Print tracked ASINs (optionally filtered by label)
    report    Generate a Markdown report with sentiment + top themes

Get a free API key (200 free calls) at https://tool.pangolinfo.com
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
import urllib.request
import urllib.error
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIG_FILE = ROOT / "reviews.json"
EXAMPLE_FILE = ROOT / "reviews.example.json"
DB_FILE = ROOT / "data" / "reviews.db"
REPORTS_DIR = ROOT / "reports"

MCP_URL = os.environ.get("PANGOLIN_MCP_URL", "https://mcp.pangolinfo.com/mcp")
MCP_PROTOCOL_VERSION = "2024-11-05"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS review_stats (
  stat_key TEXT PRIMARY KEY,
  asin TEXT NOT NULL,
  captured_at TEXT,
  review_count INTEGER,
  avg_rating REAL,
  rating_1 INTEGER, rating_2 INTEGER, rating_3 INTEGER, rating_4 INTEGER, rating_5 INTEGER,
  pos_count INTEGER, neu_count INTEGER, neg_count INTEGER,
  top_complaints TEXT,
  top_praise TEXT,
  first_seen_at TEXT,
  last_seen_at TEXT
);

CREATE TABLE IF NOT EXISTS review_history (
  asin TEXT NOT NULL,
  captured_date TEXT NOT NULL,
  avg_rating REAL,
  neg_ratio REAL,
  PRIMARY KEY (asin, captured_date)
);
"""

# --------------------------------------------------------------------------- #
# Minimal MCP (streamable-HTTP) client — stdlib only
# --------------------------------------------------------------------------- #

class McpError(RuntimeError):
    pass


class McpClient:
    """Talks JSON-RPC to the Pangolinfo MCP server over streamable-HTTP."""

    def __init__(self, token: str, url: str = MCP_URL, timeout: int = 90) -> None:
        self.token = token
        self.url = url
        self.timeout = timeout
        self.session_id: str | None = None
        self._next_id = 0
        self._initialized = False

    def _post(self, payload: dict) -> dict:
        req = urllib.request.Request(self.url, data=json.dumps(payload).encode(), method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json, text/event-stream")
        req.add_header("User-Agent", USER_AGENT)
        req.add_header("Authorization", f"Bearer {self.token}")
        if self.session_id:
            req.add_header("mcp-session-id", self.session_id)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                sid = resp.headers.get("mcp-session-id")
                if sid:
                    self.session_id = sid
                raw = resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            raise McpError(f"HTTP {exc.code} from MCP server: {exc.read()[:200]!r}") from exc
        except urllib.error.URLError as exc:
            raise McpError(f"MCP server unreachable: {exc}") from exc
        if not raw.strip():
            return {}
        for line in raw.splitlines():
            line = line.strip()
            if line.startswith("data:"):
                return json.loads(line[5:].strip())
        return json.loads(raw)

    def initialize(self) -> None:
        self._next_id += 1
        self._post({
            "jsonrpc": "2.0", "id": self._next_id, "method": "initialize",
            "params": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "amazon-review-analyzer", "version": "1.0.0"},
            },
        })
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        self._initialized = True

    def call_tool(self, name: str, arguments: dict) -> dict:
        if not self._initialized:
            self.initialize()
        self._next_id += 1
        resp = self._post({
            "jsonrpc": "2.0", "id": self._next_id, "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        })
        if "error" in resp:
            raise McpError(f"JSON-RPC error: {resp['error']}")
        result = resp.get("result", {})
        texts = [c.get("text", "") for c in result.get("content", []) if c.get("type") == "text"]
        if result.get("isError"):
            raise McpError("tool error: " + (" ".join(texts)[:300] or "unknown"))
        for text in texts:
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                continue
        return {}


# --------------------------------------------------------------------------- #
# Review response parsing
# --------------------------------------------------------------------------- #

def _looks_like_review(d: dict) -> bool:
    keys = {k.lower() for k in d.keys()}
    has_text = bool(keys & {"title", "body", "content", "text", "reviewbody", "reviewtext"})
    has_rating = bool(keys & {"rating", "stars", "reviewrating", "starRating".lower()})
    has_id = bool(keys & {"id", "reviewid", "review_id"})
    return (has_text or has_rating) and (has_id or has_text)


def _find_review_list(node, depth: int = 0) -> list:
    if depth > 6 or node is None:
        return []
    if isinstance(node, dict):
        for value in node.values():
            if isinstance(value, list) and value and isinstance(value[0], dict) and _looks_like_review(value[0]):
                return value
        for value in node.values():
            found = _find_review_list(value, depth + 1)
            if found:
                return found
    if isinstance(node, list):
        for value in node:
            found = _find_review_list(value, depth + 1)
            if found:
                return found
    return []


def extract_review_list(payload: dict) -> list:
    """Pull the list of review dicts out of a get_amazon_reviews response."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("reviews", "data", "results", "items", "reviewList"):
            v = payload.get(key)
            if isinstance(v, list) and v and isinstance(v[0], dict) and _looks_like_review(v[0]):
                return v
        return _find_review_list(payload)
    return []


def _get(d: dict, *names):
    low = {k.lower(): v for k, v in d.items()}
    for n in names:
        if n.lower() in low and low[n.lower()] not in (None, ""):
            return low[n.lower()]
    return None


def parse_review(item: dict) -> dict:
    text = " ".join(str(x or "") for x in (
        _get(item, "title", "name"),
        _get(item, "body", "content", "text", "reviewBody", "reviewText"),
    ))
    raw_rating = _get(item, "rating", "stars", "reviewRating", "starRating", "score")
    try:
        rating = float(raw_rating)
    except (TypeError, ValueError):
        rating = None
    return {
        "review_id": _get(item, "reviewId", "review_id", "id"),
        "author": _get(item, "authorName", "reviewerName", "name", "author"),
        "rating": rating,
        "date": _get(item, "date", "reviewDate", "postedDate"),
        "text": text,
    }


# --------------------------------------------------------------------------- #
# Lexicon sentiment analyzer (stdlib only)
# --------------------------------------------------------------------------- #

POSITIVE = {
    "good", "great", "excellent", "amazing", "love", "loved", "perfect", "best",
    "awesome", "happy", "satisfied", "quality", "recommend", "worth", "nice",
    "comfortable", "easy", "fast", "durable", "sturdy", "reliable", "favorite",
    "impressed", "works", "working", "beautiful", "soft", "clean", "quiet",
    "value", "useful", "convenient", "smooth", "solid", "pleasant", "wonderful",
}
NEGATIVE = {
    "bad", "terrible", "awful", "hate", "hated", "worst", "poor", "cheap",
    "broken", "broke", "defective", "stopped", "stop", "fail", "failed", "faulty",
    "disappointed", "disappointing", "waste", "useless", "junk", "return",
    "returned", "refund", "damaged", "difficult", "hard", "slow", "noisy",
    "uncomfortable", "flimsy", "fell", "cracked", "leak", "leaked", "smell",
    "smelly", "fake", "counterfeit", "rip", "ripped", "loose", "wrong", "issue",
    "problem", "annoying", "regret",
}

STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "to", "of", "in", "on", "for", "with",
    "is", "are", "was", "were", "it", "this", "that", "i", "we", "you", "they",
    "he", "she", "my", "our", "your", "their", "at", "by", "from", "as", "be",
    "been", "has", "have", "had", "not", "no", "so", "if", "than", "then", "out",
    "up", "down", "very", "just", "about", "into", "over", "after", "before",
    "me", "them", "his", "her", "its", "do", "did", "does", "will", "would",
    "can", "could", "should", "there", "here", "all", "any", "some", "one",
    "two", "get", "got", "use", "used", "using", "product", "item", "buy",
    "bought", "purchase", "purchased", "amazon", "review", "reviews", "star",
    "stars", "rating", "month", "year", "day", "time", "times", "also", "when",
    "which", "what", "who", "how", "because", "too", "more", "most", "much",
}


def sentiment_score(text: str) -> int:
    words = re.findall(r"[a-z']+", text.lower())
    score = 0
    for w in words:
        if w in POSITIVE:
            score += 1
        elif w in NEGATIVE:
            score -= 1
    return score


def theme_words(texts: list, top: int = 8) -> list:
    counter = Counter()
    for text in texts:
        for w in re.findall(r"[a-z][a-z\-]{2,}", text.lower()):
            if w in STOPWORDS or len(w) < 3:
                continue
            counter[w] += 1
    return [w for w, _ in counter.most_common(top)]


# --------------------------------------------------------------------------- #
# Storage
# --------------------------------------------------------------------------- #

def db_connect() -> sqlite3.Connection:
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    return conn


def upsert_stats(conn: sqlite3.Connection, row: dict, now: str) -> None:
    conn.execute(
        """INSERT INTO review_stats
           (stat_key, asin, captured_at, review_count, avg_rating,
            rating_1, rating_2, rating_3, rating_4, rating_5,
            pos_count, neu_count, neg_count, top_complaints, top_praise,
            first_seen_at, last_seen_at)
           VALUES (:stat_key, :asin, :captured_at, :review_count, :avg_rating,
                   :rating_1, :rating_2, :rating_3, :rating_4, :rating_5,
                   :pos_count, :neu_count, :neg_count, :top_complaints, :top_praise,
                   :first_seen_at, :last_seen_at)
           ON CONFLICT(stat_key) DO UPDATE SET
             captured_at=excluded.captured_at, review_count=excluded.review_count,
             avg_rating=excluded.avg_rating, rating_1=excluded.rating_1,
             rating_2=excluded.rating_2, rating_3=excluded.rating_3,
             rating_4=excluded.rating_4, rating_5=excluded.rating_5,
             pos_count=excluded.pos_count, neu_count=excluded.neu_count,
             neg_count=excluded.neg_count, top_complaints=excluded.top_complaints,
             top_praise=excluded.top_praise, last_seen_at=excluded.last_seen_at""",
        row,
    )
    conn.commit()


def append_history(conn: sqlite3.Connection, asin: str, date: str, avg_rating, neg_ratio) -> None:
    conn.execute(
        """INSERT OR REPLACE INTO review_history (asin, captured_date, avg_rating, neg_ratio)
           VALUES (?, ?, ?, ?)""",
        (asin, date, avg_rating, neg_ratio),
    )
    conn.commit()


# --------------------------------------------------------------------------- #
# Sparkline helper
# --------------------------------------------------------------------------- #

def sparkline(values: list, width: int = 14) -> str:
    if not values:
        return "·"
    nums = [v for v in values if v is not None]
    if not nums:
        return "·"
    lo, hi = min(nums), max(nums)
    ramp = "▁▂▃▄▅▆▇█"
    span = hi - lo
    out = []
    for v in values[-width:]:
        if v is None:
            out.append(" ")
        else:
            idx = 0 if span == 0 else int((v - lo) / span * (len(ramp) - 1))
            out.append(ramp[idx])
    return "".join(out)


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #

def cmd_init() -> None:
    if CONFIG_FILE.exists():
        sys.exit("reviews.json already exists — edit it directly.")
    CONFIG_FILE.write_text(EXAMPLE_FILE.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"Created {CONFIG_FILE.name} — set the ASINs you want to analyze.")


def cmd_run(args) -> None:
    if not CONFIG_FILE.exists():
        sys.exit("reviews.json not found. Run: python amazon_review_analyzer.py init")
    items = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    token = os.environ.get("PANGOLIN_TOKEN") or os.environ.get("PANGOLINFO_API_KEY")
    if not token:
        sys.exit("Set PANGOLIN_TOKEN env var (free key: https://tool.pangolinfo.com)")

    conn = db_connect()
    client = McpClient(token=token)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    today = datetime.now(timezone.utc).date().isoformat()
    processed, stored = 0, 0

    for entry in items:
        label = entry.get("label", entry.get("asin", "asin"))
        asin = entry["asin"]
        pages = max(1, int(entry.get("pages", 3)))
        processed += 1
        arguments = {"asin": asin}
        try:
            payload = client.call_tool("get_amazon_reviews", arguments)
        except McpError as exc:
            print(f"  ! {label} ({asin}): {exc}")
            time.sleep(args.delay)
            continue

        reviews = extract_review_list(payload)
        if not reviews:
            print(f"  · {label} ({asin}): no reviews returned")
            time.sleep(args.delay)
            continue

        parsed = [parse_review(r) for r in reviews]
        ratings = [p["rating"] for p in parsed if p["rating"] is not None]
        dist = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
        for rt in ratings:
            bucket = int(round(rt))
            if bucket in dist:
                dist[bucket] += 1
        avg = round(sum(ratings) / len(ratings), 2) if ratings else None

        pos = neu = neg = 0
        pos_texts, neg_texts = [], []
        for p in parsed:
            s = sentiment_score(p["text"])
            if s > 0:
                pos += 1
                pos_texts.append(p["text"])
            elif s < 0:
                neg += 1
                neg_texts.append(p["text"])
            else:
                neu += 1

        complaints = theme_words(neg_texts)
        praise = theme_words(pos_texts)
        neg_ratio = round(neg / len(parsed), 3) if parsed else 0.0

        row = {
            "stat_key": asin,
            "asin": asin,
            "captured_at": now,
            "review_count": len(parsed),
            "avg_rating": avg,
            "rating_1": dist[1], "rating_2": dist[2], "rating_3": dist[3],
            "rating_4": dist[4], "rating_5": dist[5],
            "pos_count": pos, "neu_count": neu, "neg_count": neg,
            "top_complaints": json.dumps(complaints),
            "top_praise": json.dumps(praise),
            "first_seen_at": now,
            "last_seen_at": now,
        }
        upsert_stats(conn, row, now)
        append_history(conn, asin, today, avg, neg_ratio)
        stored += 1
        print(f"  ✓ {label} ({asin}): {len(parsed)} reviews, "
              f"avg={avg}, pos={pos}/neu={neu}/neg={neg}")
        time.sleep(args.delay)

    print(f"\nDone: analyzed {stored} ASINs across {processed} entries. DB: {DB_FILE.relative_to(ROOT)}")


def cmd_history(args) -> None:
    conn = db_connect()
    query = "SELECT asin, review_count, avg_rating, pos_count, neu_count, neg_count, last_seen_at FROM review_stats"
    params = []
    if args.label:
        query += " WHERE asin LIKE ?"
        params.append(f"%{args.label}%")
    query += " ORDER BY avg_rating DESC NULLS LAST LIMIT ?"
    params.append(args.limit)
    rows = conn.execute(query, params).fetchall()
    if not rows:
        print("No data yet. Run: python amazon_review_analyzer.py run")
        return
    print(f"{'asin':<14}{'reviews':>8}{'avg':>6}{'pos':>5}{'neu':>5}{'neg':>5}")
    print("-" * 48)
    for asin, rc, avg, pos, neu, neg, seen in rows:
        print(f"{asin[:13]:<14}{rc:>8}{str(avg):>6}{pos:>5}{neu:>5}{neg:>5}")


def cmd_report(_args) -> None:
    conn = db_connect()
    REPORTS_DIR.mkdir(exist_ok=True)
    today = datetime.now(timezone.utc).date().isoformat()

    rows = conn.execute(
        """SELECT asin, review_count, avg_rating, rating_1, rating_2, rating_3,
                  rating_4, rating_5, pos_count, neu_count, neg_count,
                  top_complaints, top_praise
           FROM review_stats ORDER BY avg_rating DESC NULLS LAST LIMIT 200"""
    ).fetchall()
    if not rows:
        print("No reviews analyzed yet. Run: python amazon_review_analyzer.py run")
        return

    lines = [
        f"# Amazon Review Analysis — {today}",
        "",
        "Generated with [amazon-review-analyzer](https://github.com/pangolinfoapi/amazon-review-analyzer) "
        "using the [Pangolinfo Amazon Scraper API](https://www.pangolinfo.com/amazon-scraper-api/).",
        "",
        "> Sentiment is a dependency-free lexicon scorer over review text. "
        "▲/▼ show avg-rating trend over captured snapshots.",
        "",
        "## ASIN summary",
        "",
        "| ASIN | Reviews | Avg | 1★ | 2★ | 3★ | 4★ | 5★ | Pos/Neu/Neg | Avg trend |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for (asin, rc, avg, r1, r2, r3, r4, r5, pos, neu, neg, complaints, praise) in rows:
        hist = conn.execute(
            "SELECT avg_rating FROM review_history WHERE asin = ? ORDER BY captured_date",
            (asin,),
        ).fetchall()
        vals = [r[0] for r in hist]
        lines.append(
            f"| {asin} | {rc} | {avg if avg is not None else '—'} | {r1} | {r2} | {r3} | {r4} | {r5} | "
            f"{pos}/{neu}/{neg} | `{sparkline(vals)}` |"
        )

    lines += ["", "## Top complaint themes", ""]
    for (asin, _rc, _avg, _r1, _r2, _r3, _r4, _r5, _pos, _neu, _neg, complaints, _praise) in rows:
        words = json.loads(complaints or "[]")
        if words:
            lines.append(f"- **{asin}**: {', '.join(words)}")

    lines += ["", "## Top praise themes", ""]
    for (asin, _rc, _avg, _r1, _r2, _r3, _r4, _r5, _pos, _neu, _neg, _complaints, praise) in rows:
        words = json.loads(praise or "[]")
        if words:
            lines.append(f"- **{asin}**: {', '.join(words)}")

    report = "\n".join(lines) + "\n"
    (REPORTS_DIR / f"{today}.md").write_text(report, encoding="utf-8")
    (REPORTS_DIR / "latest.md").write_text(report, encoding="utf-8")
    print(f"Report written: reports/{today}.md, reports/latest.md")


def main() -> None:
    parser = argparse.ArgumentParser(description="Amazon Review Analyzer (powered by Pangolinfo)")
    parser.add_argument("--delay", type=float, default=2.0, help="Seconds between API calls (default: 2)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="Create reviews.json from the example")
    sub.add_parser("run", help="Fetch reviews for all configured ASINs")
    hist = sub.add_parser("history", help="Show tracked ASINs")
    hist.add_argument("--label")
    hist.add_argument("--limit", type=int, default=50)
    sub.add_parser("report", help="Generate Markdown report")

    args = parser.parse_args()
    {"init": cmd_init, "run": cmd_run, "history": cmd_history, "report": cmd_report}[args.command](args)


if __name__ == "__main__":
    main()
