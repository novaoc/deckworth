#!/usr/bin/env python3
"""
deckworth — Pokemon TCG deck value calculator

Fetches live card prices from pokemontcg.io and calculates
the total market value of a deck list.

Usage:
    deckworth decklist.txt
    cat decklist.txt | deckworth
    deckworth decklist.txt --format json
    deckworth decklist.txt --format csv
"""

import argparse
import json
import re
import sys
import time
import urllib.request
import urllib.parse
from dataclasses import dataclass, field
from typing import Optional


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


# ── Parsing ────────────────────────────────────────────────────────────────────

# Lines in a PTCGO/PTCGL export look like:
#   4 Charizard ex SVI 125
#   2 Pidgeot ex OBF 164
#   4 Rare Candy SVI 191
#   7 Basic {R} Energy SVE 2
# Section headers like "Pokémon:", "Trainer:", "Energy:" are ignored.
_CARD_RE = re.compile(
    r'^(\d+)\s+'         # quantity
    r'(.+?)'             # card name (non-greedy)
    r'(?:\s+([A-Z0-9]{2,5})\s+(\d+)(?:/\d+)?)?$'  # optional set + number
)


def parse_line(line: str) -> Optional[CardEntry]:
    line = line.strip()
    # Skip blanks, comments, section headers
    if not line or line.startswith('#') or line.startswith('//'):
        return None
    if re.match(r'^(Pokémon|Pokemon|Trainer|Energy)\s*:', line, re.I):
        return None
    # Strip inline comments
    line = re.sub(r'\s*#.*$', '', line).strip()
    m = _CARD_RE.match(line)
    if not m:
        return None
    qty = int(m.group(1))
    name = m.group(2).strip()
    set_code = m.group(3)
    raw_num = m.group(4)
    number = raw_num.split('/')[0] if raw_num else None
    return CardEntry(qty, name, set_code, number)


# ── Price fetching ────────────────────────────────────────────────────────────

API_BASE = "https://api.pokemontcg.io/v2/cards"
PRICE_ORDER = ["holofoil", "normal", "reverseHolofoil", "1stEditionHolofoil",
               "unlimitedHolofoil", "unlimited"]


def _best_price(prices: dict) -> tuple[Optional[float], str]:
    for ptype in PRICE_ORDER:
        if ptype in prices:
            val = prices[ptype].get("market") or prices[ptype].get("mid")
            if val:
                return float(val), ptype
    # Fall back to anything
    for ptype, pdata in prices.items():
        val = pdata.get("market") or pdata.get("mid")
        if val:
            return float(val), ptype
    return None, ""


def fetch_price(card: CardEntry) -> CardEntry:
    """Query pokemontcg.io for this card's market price."""
    if card.number:
        # Query by name + collector number (ptcgoCode doesn't match PTCGL exports)
        query = f'name:"{card.name}" number:"{card.number}"'
    else:
        query = f'name:"{card.name}"'

    url = (
        f"{API_BASE}?q={urllib.parse.quote(query)}"
        f"&select=name,tcgplayer,set&pageSize=20&orderBy=-set.releaseDate"
    )

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "deckworth/1.0"})
        with urllib.request.urlopen(req, timeout=12) as r:
            data = json.loads(r.read())
    except Exception:
        return card

    results = data.get("data", [])
    if not results:
        return card

    # Prefer exact name match; fallback to first result
    exact = next(
        (c for c in results if c.get("name", "").lower() == card.name.lower()),
        results[0]
    )

    prices = exact.get("tcgplayer", {}).get("prices", {})
    if prices:
        val, ptype = _best_price(prices)
        if val is not None:
            card.price = val
            card.price_type = ptype
            card.found = True

    return card


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
        src = e.price_type if e.found else "not found"
        rows.append(f"{e.quantity:>4}  {e.name:<{_COL_W}}  {each:>8}  {line:>8}  {src}")

    rows.append("─" * 72)
    rows.append(f"{'Deck total':>{4 + 2 + _COL_W + 2 + 8 + 2}}  ${total:>7.2f}")
    return "\n".join(rows)


def _json_out(entries: list[CardEntry], total: float) -> str:
    return json.dumps({
        "total": round(total, 2),
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
            }
            for e in entries
        ],
    }, indent=2)


def _csv_out(entries: list[CardEntry]) -> str:
    rows = ["quantity,name,set_code,number,price_each,price_total,price_type,found"]
    for e in entries:
        rows.append(
            f'{e.quantity},"{e.name}",{e.set_code or ""},{ e.number or ""},'
            f'{e.price or ""},{ round((e.price or 0) * e.quantity, 2)},'
            f'{e.price_type},{e.found}'
        )
    return "\n".join(rows)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="deckworth",
        description="Calculate the market value of a Pokemon TCG deck.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  deckworth deck.txt
  cat deck.txt | deckworth
  deckworth deck.txt --format json
  deckworth deck.txt --format csv > prices.csv
  deckworth deck.txt --delay 0.2
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
    args = parser.parse_args()

    # ── Read input ──────────────────────────────────────────────────────────
    if args.file:
        try:
            with open(args.file) as f:
                lines = f.readlines()
        except FileNotFoundError:
            print(f"Error: file not found: {args.file}", file=sys.stderr)
            sys.exit(1)
    else:
        lines = sys.stdin.readlines()

    # ── Parse deck ──────────────────────────────────────────────────────────
    entries: list[CardEntry] = []
    for line in lines:
        e = parse_line(line)
        if e:
            entries.append(e)

    if not entries:
        print("No cards parsed. Check your decklist format.", file=sys.stderr)
        print("Expected format: <qty> <name> [<set> <number>]", file=sys.stderr)
        sys.exit(1)

    # ── Fetch prices ────────────────────────────────────────────────────────
    if args.format == "table":
        print(
            f"Fetching prices for {len(entries)} card(s)…",
            file=sys.stderr
        )

    for i, entry in enumerate(entries):
        entries[i] = fetch_price(entry)
        if args.delay > 0 and i < len(entries) - 1:
            time.sleep(args.delay)

    # ── Totals ──────────────────────────────────────────────────────────────
    total = sum((e.price or 0) * e.quantity for e in entries)
    not_found = [e for e in entries if not e.found]

    # ── Output ──────────────────────────────────────────────────────────────
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
                file=sys.stderr
            )
        print(f"\nTotal deck value: ${total:.2f}", file=sys.stderr)


if __name__ == "__main__":
    main()
