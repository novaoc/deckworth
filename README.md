# deckworth

**Calculate the market value of a Pokemon TCG deck from live prices.**

Paste in a deck list, get back a full price breakdown — each card, total cost, and data source. Pulls live market prices from [pokemontcg.io](https://pokemontcg.io).

```
 QTY  CARD                                      EACH      LINE  TYPE
────────────────────────────────────────────────────────────────────────
   4  Charizard ex                             $14.50    $58.00  holofoil
   3  Pidgeot ex                                $8.75    $26.25  holofoil
   4  Arven                                     $1.20     $4.80  normal
   4  Boss's Orders                             $2.10     $8.40  holofoil
  10  Basic Fire Energy                         $0.10     $1.00  normal
  ...
────────────────────────────────────────────────────────────────────────
                                               Total    $142.37
```

## Install

```bash
git clone https://github.com/novaoc/deckworth
cd deckworth
pip install .          # installs the 'deckworth' command
# or just run it directly:
python deckworth.py deck.txt
```

No API key required. No dependencies outside Python stdlib.

## Usage

```bash
# From a file
deckworth deck.txt

# Pipe from stdin
cat deck.txt | deckworth

# JSON output (for scripting)
deckworth deck.txt --format json

# CSV (for spreadsheets)
deckworth deck.txt --format csv > prices.csv

# Slow down API calls (default: 0.15s between requests)
deckworth deck.txt --delay 0.3
```

## Decklist Format

Standard PTCGL export format — copy straight from the game's deck builder:

```
Pokémon: 14
4 Charizard ex OBF 125
2 Charmander OBF 26
...

Trainer: 36
4 Arven SVI 166
...

Energy: 10
10 Basic Fire Energy SVE 2
```

Lines without a set code (e.g. `4 Charizard ex`) still work — deckworth fuzzy-matches by name and returns the most recent printing's price.

A sample deck is included: [`sample_deck.txt`](sample_deck.txt)

## How It Works

1. Parses the deck list into card entries (quantity, name, set code, collector number)
2. For each unique card, queries `api.pokemontcg.io/v2/cards` — free, no key needed
3. Picks the best price: market > mid, priority order: holofoil → normal → reverseHolofoil
4. Displays the breakdown and totals

## Output Formats

| Flag | Description |
|------|-------------|
| `--format table` | Human-readable table (default) |
| `--format json` | Machine-readable JSON with full details |
| `--format csv` | Spreadsheet-friendly CSV |

## Caveats

- Prices are **TCGPlayer market prices** via the pokemontcg.io API — USD only
- Promo cards and some alternate arts may not match perfectly; use set+number for precision
- Energy cards often have low or missing prices (expected)
- No rate limit on free tier, but `--delay` helps avoid hammering the API

## Why?

Because "should I buy singles or crack packs?" is a math problem, not a vibe. And because a $14 Charizard ex hidden in a $150 deck deserves to be found.

## License

MIT
