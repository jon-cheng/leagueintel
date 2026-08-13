# Setup guide

Run leagueintel against your own ESPN league (or a public demo league)
in a few minutes. No Docker required — everything runs locally via Poetry.

## Prerequisites

- Python 3.12+
- [Poetry](https://python-poetry.org/docs/#installation)

## 1. Install dependencies

```bash
git clone <this repo>
cd leagueintel
poetry install
```

This installs the core package. If you want the Streamlit app and
chatbot too (most people do), also run:

```bash
poetry install --with reporting
```

## 2. Run the setup script

```bash
poetry run python scripts/setup.py
```

It will walk you through a decision tree:

- **Try the demo league** — a real, public ESPN league (no account or
  cookies needed) so you can see leagueintel working immediately.
- **Connect your own league** — you'll be asked whether it's public or
  private:
  - **Public**: only your league ID is needed.
  - **Private**: you'll also need two browser cookies (`espn_s2`,
    `SWID`). The script prints exact steps for grabbing them from
    DevTools when you get to this branch.

The script then validates the credentials against the live ESPN API,
writes a `.env` file, and pulls one season of data into a local
SQLite database so there's something to look at right away.

If you'd rather do this by hand, copy `.env.example` to `.env` and
fill in the values yourself.

## 3. Run the app

```bash
poetry run streamlit run src/leagueintel/reporting/home.py
```

## Optional: chatbot

Set `ANTHROPIC_API_KEY` in `.env` (the setup script prompts for this,
or add it manually) to enable the chatbot. Leave it blank and the rest
of the app works fine without it.

## Optional: cloud deployment features

These are **not needed for local use** — leagueintel runs entirely off
a local SQLite file without them. They only matter if you're deploying
to Streamlit Community Cloud with a shared, persisted database:

- `S3_BUCKET` / `S3_KEY` / `AWS_*` — sync the SQLite DB to S3 so it
  survives redeploys.
- `TURSO_OPS_URL` / `TURSO_OPS_TOKEN` — track chatbot usage/spend
  across sessions. If unset, usage tracking is silently disabled;
  nothing else breaks.

## Getting more data

The setup script only pulls one season. To backfill your league's
full history:

```bash
poetry run leagueintel sync
```

Run `poetry run leagueintel --help` for the full list of ingestion
commands (fetch teams, players, matchups, transactions, etc. individually).
