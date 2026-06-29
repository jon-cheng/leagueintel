# leagueintel

![tests](https://github.com/jon-cheng/leagueintel/actions/workflows/test.yml/badge.svg)

Fantasy football league-specific analytics and competitive intelligence platform.

## What it does

Fetches ESPN fantasy football transaction data including full waiver bid 
history — winning and losing bids with FAAB dollar amounts — going back 
to 2019 via an undocumented ESPN API endpoint (`mTransactions2` with 
`scoringPeriodId`). Foundation for a waiver bid estimator and natural 
language league chatbot.

## Background

ESPN's `recent_activity` endpoint deletes historical transaction data 
after each season ends. This project discovered that passing 
`scoringPeriodId` to the `mTransactions2` view preserves full transaction 
history including FAAB bid amounts and losing bids — data not available 
through any other known method.

## Quick start

```bash
git clone https://github.com/jon-cheng/leagueintel
cd leagueintel
poetry install
cp .env.example .env  # add your ESPN credentials
leagueintel fetch-transactions --year 2024 --week 1
```

## Credentials

ESPN uses cookie-based auth for private leagues. You need:
- `LEAGUE_ID` — your ESPN league ID
- `ESPN_S2` — from ESPN cookies in browser DevTools
- `SWID` — from ESPN cookies in browser DevTools

See `.env.example` for the format.

## CLI

```bash
# fetch specific week
leagueintel fetch-transactions --year 2024 --week 1

# fetch full season
leagueintel fetch-transactions --year 2024

# fetch all available seasons (2019+)
leagueintel fetch-transactions

# custom max week
leagueintel fetch-transactions --year 2024 --max-week 13
```

## Project status

- ✅ fetch-transactions — ESPN API ingestion with raw JSON storage
- ✅  parse-transactions — coming next
- 🔄 analytics layer — waiver ROI, manager skill metrics
- 🔄 chatbot — natural language league Q&A

## Tech stack

- Python 3.12, Poetry
- click (CLI), loguru (logging), requests (HTTP)
- SQLite (storage)
- GitHub Actions (CI/CD)