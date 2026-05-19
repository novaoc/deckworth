#!/usr/bin/env python3
"""deckworth — Pokemon TCG deck value calculator

Fetches live card prices from pokemontcg.io and calculates
the total market value of a deck list.

Usage:
    deckworth decklist.txt
    cat decklist.txt | deckworth
    deckworth decklist.txt --format json
    deckworth decklist.txt --format csv
    deckworth decklist.txt --snapshot "my-deck"
    deckworth decklist.txt --stats
    deckworth --history "my-deck"
"""

import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

__version__ = "1.1.0"

# ── Paths ──────────────────────────────────────────────────────────────────────

_HISTORY_DIR = os.path.expanduser("~/.deckworth")


def _ensure_history_dir():
    os.makedirs(_HISTORY_DIR, exist_ok=True)


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class CardEntry:
    quantity: int
    name: str
    set_code: Optional[str] = None
    number: Optional[str] = None
    price: Optional[float] = None
    price_type: str = ""
    found: bool = False
    error: str = ""


# ── Parsing ────────────────────────────────────────────────────────────────────

_CARD_RE = re.compile(
    r"^(\d+)\s+"          # quantity
    r"(.+?)"              # card name (non-greedy)
    r"(?:\s+([A-Z0-9]{2,5})\s+(\d+)(?:/\d+)?)?$"  # optional set + number
)


def parse_line(line: str) -> Optional[CardEntry]:
    line = line.strip()
    if not line or line.startswith("#") or line.startswith("//"):
        return None
    if re.match(r"^(Pok[eé]mon|Trainer|Energy)\s*:", line, re.I):
        return None
    # Strip inline comments
    line = re.sub(r"\s*#.*$", "", line).strip()
    m = _CARD_RE.match(line)
    if not m:
        return None
    qty = int(m.group(1))
    name = m.group(2).strip()
    set_code = m.group(3)
    raw_num = m.group(4)
    number = raw_num.split("/")[0] if raw_num else None
    return CardEntry(qty, name, set_code, number)


def deduplicate(entries: list[CardEntry]) -> list[CardEntry]:
    """Combine quantities of cards with the same (name, set_code, number)."""
    groups: dict[tuple[str, Optional[str], Optional[str]], int] = defaultdict(int)
    for e in entries:
        key = (e.name.lower(), e.set_code, e.number)
        groups[key] += e.quantity

    # Preserve first occurrence's metadata when merging
    seen: dict[tuple[str, Optional[str], Optional[str]], CardEntry] = {}
    deduped: list[CardEntry] = []
    for e in entries:
        key = (e.name.lower(), e.set_code, e.number)
        if key not in seen:
            e.quantity = groups[key]
            seen[key] = e
            deduped.append(e)
        # skip duplicates — they're merged into the first occurrence

    return deduped


# ── Price fetching ────────────────────────────────────────────────────────────

API_BASE = "https://api.pokemontcg.io/v2/cards"
PRICE_ORDER = [
    "holofoil", "normal", "reverseHolofoil",
    "1stEditionHolofoil", "1stEditionNormal",
    "unlimitedHolofoil", "unlimitedNormal", "unlimited",
]


def _best_price(prices: dict) -> tuple[Optional[float], str]:
    for ptype in PRICE_ORDER:
        if ptype in prices:
            val = prices[ptype].get("market") or prices[ptype].get("mid")
            if val:
                return float(val), ptype
    for ptype, pdata in prices.items():
        val = pdata.get("market") or pdata.get("mid")
        if val:
            return float(val), ptype
    return None, ""


def fetch_price(card: CardEntry) -> CardEntry:
    """Query pokemontcg.io for this card's market price."""
    if card.number:
        query = f'name:"{card.name}" number:"{card.number}"'
    else:
        query = f'name:"{card.name}"'

    url = (
        f"{API_BASE}?q={urllib.parse.quote(query)}"
        f"&select=name,tcgplayer,set&pageSize=20&orderBy=-set.releaseDate"
    )

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "deckworth/1.1.0"})
        with urllib.request.urlopen(req, timeout=12) as r:
            data = json.loads(r.read())
    except urllib.error.HTTPError as e:
        card.error = f"HTTP {e.code}: {e.reason}"
        return card
    except urllib.error.URLError as e:
        card.error = f"Connection error: {e.reason}"
        return card
    except TimeoutError:
        card.error = "Request timed out"
        return card
    except json.JSONDecodeError as e:
        card.error = f"Invalid JSON response: {e}"
        return card

    results = data.get("data", [])
    if not results:
        card.error = "No results from API"
        return card

    exact = next(
        (c for c in results if c.get("name", "").lower() == card.name.lower()),
        results[0],
    )

    prices = exact.get("tcgplayer", {}).get("prices", {})
    if prices:
        val, ptype = _best_price(prices)
        if val is not None:
            card.price = val
            card.price_type = ptype
            card.found = True
            return card

    card.error = "No price data on API"
    return card


# ── Snapshot ───────────────────────────────────────────────────────────────────

SNAPSHOT_COLS = ["timestamp", "deck_name", "total_value", "card_count", "unique_cards", "format"]


def save_snapshot(deck_name: str, total: float, card_count: int, unique: int, fmt: str):
    """Append a value snapshot to the deck's history CSV."""
    _ensure_history_dir()
    safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", deck_name)
    path = os.path.join(_HISTORY_DIR, f"{safe_name}.csv")
    ts = time.strftime("%Y-%m-%d %H:%M:%S")

    is_new = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        writer = csv.writer(f)
        if is_new:
            writer.writerow(SNAPSHOT_COLS)
        writer.writerow([ts, deck_name, round(total, 2), card_count, unique, fmt])

    return path


def show_history(deck_name: str) -> Optional[str]:
    """Read and return snapshot history for a deck."""
    safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", deck_name)
    path = os.path.join(_HISTORY_DIR, f"{safe_name}.csv")

    if not os.path.exists(path):
        return None

    rows = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)

    if not rows:
        return None

    out = [f"📊 Value history for: {deck_name}", "─" * 65]
    out.append(f"{'Date':20s}  {'Value':>8s}  {'vs Start':>9s}  {'Cards':>5s}  {'Unique':>6s}  {'Format':>8s}")
    out.append("─" * 65)

    first_val = float(rows[0]["total_value"]) if rows else 0
    for row in rows:
        val = float(row["total_value"])
        diff = val - first_val
        diff_str = f"+${diff:.2f}" if diff > 0 else (f"-${abs(diff):.2f}" if diff < 0 else "   —   ")
        val_str = f"${val:.2f}"
        out.append(
            f"{row['timestamp']:20s}  {val_str:>8s}  {diff_str:>9s}  "
            f"{row['card_count']:>5s}  {row['unique_cards']:>6s}  {row.get('format', 'table'):>8s}"
        )
    out.append("─" * 65)
    out.append(f"Snapshots: {len(rows)}  |  First value: ${first_val:.2f}  |  "
               f"Current: ${float(rows[-1]['total_value']):.2f}")

    return "\n".join(out)


# ── Stats ──────────────────────────────────────────────────────────────────────

def compute_stats(entries: list[CardEntry], total: float) -> dict:
    """Compute summary statistics from priced entries."""
    priced = [e for e in entries if e.price is not None]
    n = len(priced)

    stats = {
        "total_cards": sum(e.quantity for e in entries),
        "unique_cards": len(entries),
        "total_value": round(total, 2),
        "priced_count": n,
        "unpriced_count": len(entries) - n,
    }

    if n == 0:
        return stats

    prices = [(e.price or 0) * e.quantity for e in priced if e.price]

    stats["mean_card_price"] = round(sum(prices) / n, 2)
    prices_sorted = sorted(prices)
    if n % 2 == 1:
        stats["median_card_price"] = round(prices_sorted[n // 2], 2)
    else:
        mid = n // 2
        stats["median_card_price"] = round(
            (prices_sorted[mid - 1] + prices_sorted[mid]) / 2, 2
        )

    prices_by_line = [(e, (e.price or 0) * e.quantity) for e in priced if e.price]
    prices_by_line.sort(key=lambda x: -x[1])

    most_expensive = prices_by_line[0] if prices_by_line else None
    least_expensive = prices_by_line[-1] if prices_by_line else None

    if most_expensive:
        stats["most_expensive"] = {
            "name": most_expensive[0].name,
            "total": round(most_expensive[1], 2),
            "each": round(most_expensive[0].price or 0, 2),
            "qty": most_expensive[0].quantity,
        }
    if least_expensive and least_expensive[0] != most_expensive[0]:
        stats["least_expensive"] = {
            "name": least_expensive[0].name,
            "total": round(least_expensive[1], 2),
            "each": round(least_expensive[0].price or 0, 2),
            "qty": least_expensive[0].quantity,
        }

    return stats


# ── Output formatters ─────────────────────────────────────────────────────────

_COL_W = 36


def _table(entries: list[CardEntry], total: float) -> str:
    rows = []
    rows.append(
        f"{'QTY':>4}  {'CARD':<{_COL_W}}  {'EACH':>8}  {'LINE':>8}  TYPE"
    )
    rows.append("─" * 72)

    for e in sorted(entries, key=lambda x: -(x.price or 0) * x.quantity):
        each = f"${e.price:.2f}" if e.price else "—"
        line = f"${e.price * e.quantity:.2f}" if e.price else "—"
        src = e.price_type if e.found else (e.error if e.error else "not found")
        rows.append(f"{e.quantity:>4}  {e.name:<{_COL_W}}  {each:>8}  {line:>8}  {src}")

    rows.append("─" * 72)
    rows.append(f"{'Deck total':>{4 + 2 + _COL_W + 2 + 8 + 2}}  ${total:>7.2f}")
    return "\n".join(rows)


def _json_out(entries: list[CardEntry], total: float) -> str:
    return json.dumps({
        "total": round(total, 2),
        "version": __version__,
        "cards": [
            {
                "quantity": e.quantity,
                "name": e.name,
                "set_code": e.set_code,
                "number": e.number,
                "price_each": e.price,
                "price_total": round((e.price or 0) * e.quantity, 2),
                "price_type": e.price_type,
                "found": e.found,
                "error": e.error or None,
            }
            for e in entries
        ],
    }, indent=2)


def _csv_out(entries: list[CardEntry]) -> str:
    rows = [
        "quantity,name,set_code,number,price_each,price_total,price_type,found,error"
    ]
    for e in entries:
        rows.append(
            f'{e.quantity},"{e.name}",{e.set_code or ""},{e.number or ""},'
            f'{e.price or ""},{round((e.price or 0) * e.quantity, 2)},'
            f'{e.price_type},{e.found},{e.error or ""}'
        )
    return "\n".join(rows)


def _stats_text(stats: dict) -> str:
    lines = ["📊 Deck Summary", "─" * 50]
    lines.append(f"Total cards:      {stats['total_cards']} ({stats['unique_cards']} unique)")
    lines.append(f"Total value:      ${stats['total_value']:.2f}")
    lines.append(f"Priced:           {stats['priced_count']} / {stats['priced_count'] + stats['unpriced_count']}")

    if "mean_card_price" in stats:
        lines.append(f"Mean card value:  ${stats['mean_card_price']:.2f}")
    if "median_card_price" in stats:
        lines.append(f"Median value:     ${stats['median_card_price']:.2f}")

    if "most_expensive" in stats:
        m = stats["most_expensive"]
        lines.append(f"Most expensive:   {m['name']} ×{m['qty']} = ${m['total']:.2f} (${m['each']:.2f} ea.)")
    if "least_expensive" in stats and stats["least_expensive"] is not None:
        le = stats["least_expensive"]
        lines.append(f"Least expensive:  {le['name']} ×{le['qty']} = ${le['total']:.2f} (${le['each']:.2f} ea.)")

    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

def _parse_deck(lines: list[str]) -> list[CardEntry]:
    """Parse lines into deduplicated card entries."""
    raw: list[CardEntry] = []
    for line in lines:
        e = parse_line(line)
        if e:
            raw.append(e)
    return deduplicate(raw)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="deckworth",
        description="Calculate the market value of a Pokemon TCG deck.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  deckworth deck.txt
  cat deck.txt | deckworth
  deckworth deck.txt --format json
  deckworth deck.txt --format csv > prices.csv
  deckworth deck.txt --snapshot "My Charizard Deck"
  deckworth deck.txt --stats
  deckworth --history "My Charizard Deck"
        """,
    )
    parser.add_argument(
        "file", nargs="?",
        help="Decklist file (default: stdin)"
    )
    parser.add_argument(
        "--format", choices=["table", "json", "csv"], default="table",
        help="Output format (default: table)"
    )
    parser.add_argument(
        "--delay", type=float, default=0.15, metavar="SECS",
        help="Delay between API calls in seconds (default: 0.15)"
    )
    parser.add_argument(
        "--snapshot", type=str, metavar="NAME",
        help="Save deck value snapshot to ~/.deckworth/NAME.csv"
    )
    parser.add_argument(
        "--history", type=str, metavar="NAME",
        help="Show value history for a previously snapshot deck"
    )
    parser.add_argument(
        "--stats", action="store_true",
        help="Show summary statistics for the deck"
    )
    parser.add_argument(
        "--version", action="version",
        version=f"deckworth {__version__}",
    )
    args = parser.parse_args()

    # ── History mode (no deck file needed) ────────────────────────────────
    if args.history:
        result = show_history(args.history)
        if result is None:
            print(
                f"No history found for deck: {args.history}",
                file=sys.stderr,
            )
            print(
                f"  (looked in {os.path.join(_HISTORY_DIR, re.sub(r'[^a-zA-Z0-9_-]', '_', args.history))}.csv)",
                file=sys.stderr,
            )
            sys.exit(1)
        print(result)
        return

    # ── Read input ────────────────────────────────────────────────────────
    if args.file:
        try:
            with open(args.file) as f:
                lines = f.readlines()
        except FileNotFoundError:
            print(f"Error: file not found: {args.file}", file=sys.stderr)
            sys.exit(1)
    else:
        lines = sys.stdin.readlines()

    # ── Parse deck ────────────────────────────────────────────────────────
    entries = _parse_deck(lines)

    if not entries:
        print("No cards parsed. Check your decklist format.", file=sys.stderr)
        print("Expected format: <qty> <name> [<set> <number>]", file=sys.stderr)
        sys.exit(1)

    # ── Fetch prices ──────────────────────────────────────────────────────
    if args.format == "table":
        print(
            f"Fetching prices for {len(entries)} card(s) (deduplicated)…",
            file=sys.stderr,
        )

    for i, entry in enumerate(entries):
        entries[i] = fetch_price(entry)
        if entry.error and args.format == "table":
            print(
                f"  ⚠ {entry.name}: {entry.error}",
                file=sys.stderr,
            )
        if args.delay > 0 and i < len(entries) - 1:
            time.sleep(args.delay)

    # ── Totals ────────────────────────────────────────────────────────────
    total = round(sum((e.price or 0) * e.quantity for e in entries), 2)
    not_found = [e for e in entries if not e.found]
    api_errors = [e for e in entries if e.error and not e.error.startswith("No price")]
    total_cards = sum(e.quantity for e in entries)

    # ── Snapshot ──────────────────────────────────────────────────────────
    if args.snapshot:
        path = save_snapshot(
            args.snapshot, total, total_cards, len(entries), args.format
        )
        if args.format == "table":
            print(
                f"\n💾 Snapshot saved: {path}",
                file=sys.stderr,
            )

    # ── Output ────────────────────────────────────────────────────────────
    if args.format == "json":
        print(_json_out(entries, total))
    elif args.format == "csv":
        print(_csv_out(entries))
    else:
        print(_table(entries, total))
        if not_found:
            names = ", ".join(e.name for e in not_found)
            print(
                f"\n⚠  {len(not_found)} card(s) not priced: {names}",
                file=sys.stderr,
            )
        if api_errors:
            print(
                f"\n⚠  {len(api_errors)} API error(s) during fetching",
                file=sys.stderr,
            )
        print(f"\nTotal deck value: ${total:.2f}", file=sys.stderr)

    # ── Stats ─────────────────────────────────────────────────────────────
    if args.stats:
        stats = compute_stats(entries, total)
        print(file=sys.stderr)
        print(_stats_text(stats), file=sys.stderr)


if __name__ == "__main__":
    main()
