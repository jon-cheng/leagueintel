# leagueintel

An ESPN fantasy football analytics and competitive intelligence platform.
leagueintel ingests your league's full history and puts it behind an
LLM-powered chatbot that answers questions no other tool can. This is especially useful for private leagues and leagues with auction draft and/or free agent budget (FAAB) rules.

> "Who had the most regrettable drop of 2025?"
> 
> "What was the most competitive waiver auction bid of all time?"
> 
> "Who has had the best waiver instincts over all seasons?"

These questions are answerable in seconds because leagueintel persists
data ESPN deletes — including FAAB bid history, losing bids, and
weekly box scores going back to your league's founding.

---

## What it does

leagueintel is built for a single league. It knows your managers by
name, your league's scoring rules, your auction budget, and every
transaction since the first season with available data.

**Dashboard:**
- Draft ROI — bid amount vs points per game started, with position breakdown
- Best Waiver Pickup — position-normalized percentile score across all eligible adds
- Season Overview — standings, playoff bracket, last place (toilet bowl) history
- All-Time Head to Head — full win/loss matrix across every regular season game
- Podium — all-time top 3 finishers, consolation and last place finishers per season

**Chatbot:**
Ask anything in plain English. The chatbot routes simple questions to
_ad-hoc_ SQL and complex validated analytics (waiver scores, draft ROI)
to pre-built pandas pipelines, preventing the confident hallucinations
that plague naive text-to-SQL implementations. Under the hood, the semantic layer (views, well-documented schema descriptions) guides the LLM queries.

---

## How it works

### Self-hosted

leagueintel is self-hosted: you run your own instance
for your own league. Your data stays with you.

### Data ingestion

leagueintel ingests from ESPN's fantasy football API via
[`espn_api`](https://github.com/cwendt94/espn-api), a community-built
Python wrapper around ESPN's undocumented endpoints.

One piece of data ESPN deletes after each season: FAAB bid history,
including losing bids. leagueintel recovers this via an undocumented
`scoringPeriodId` parameter on ESPN's `mTransactions2` endpoint —
capturing the full bid history, including what every manager bid and
lost, before ESPN removes it.

### Architecture
- **Ingestion** — fetches from the ESPN API, validates with Pydantic, and normalizes into a SQLite database
- **Analytics** — pre-validated pandas functions for complex queries (waiver scores, draft ROI, standings)
- **LLM agent** — Anthropic API tool-use agent routes natural language questions to ad-hoc SQL or validated analytics
- **Frontend** — Streamlit dashboard and chatbot, password-gated and mobile-friendly

The database is stored in S3 — downloaded by Streamlit on cold start and refreshed weekly by GitHub Actions.
![leagueintel architecture](leagueintel.png)

#### Design choices for persistent storage
The fantasy football database (leagueintel.db) is stored in S3 and 
downloaded to the Streamlit instance on cold start. SQLite was chosen 
as a lightweight embedded database appropriate for the scale — ~10MB, 
weekly updates, single writer — as opposed to heavier analytical engines 
like DuckDB or a managed Postgres instance. The Streamlit app's IAM policy is 
read-only, eliminating any risk of the app corrupting 
or overwriting the database — concurrency safety enforced at the 
infrastructure level rather than in code. S3 also has no read caps, 
making it the right choice for a database queried heavily by every user 
on every page load.

Token usage tracking requires persistent writes from the app after every 
question, which conflicts with the read-only S3 pattern. Turso (hosted 
SQLite) serves as a lightweight operational layer for this — persistent 
across cold starts, writable by the app, and completely independent of 
the weekly data refresh pipeline. Turso's free tier read caps are not a 
concern here since the usage table is queried only once per chatbot 
question, not on every page load.

### Tech stack 
- **Data & Storage** — Python 3.12, SQLite, S3, boto3
- **Ingestion** — `espn_api`, Pydantic, Click, Poetry
- **Analytics & Viz** — Plotly, Loguru
- **AI** — Anthropic API (Claude)
- **Frontend** — Streamlit
- **CI/CD** — GitHub Actions
- **LLM token usage tracking** - SQLite on Turso 

---

## Taking anonymized screenshots

leagueintel supports taking anonymized screenshots/demos via a
disposable, one-time-anonymized copy of the database — not a schema
migration, not a runtime flag, not anything the real app or real
`leagueintel.db` ever knows about.

1. The real `leagueintel.db` (used by the deployed app and
   `leagueintel sync`) is never touched — no schema change, no new
   table, no new view, no code changes anywhere.
2. Copy the real database to a new, separate file:
   ```
   cp leagueintel.db leagueintel_demo.db
   ```
   From this point on it's a completely independent file — no link, no
   shared storage, no relationship to the original.
3. Run the anonymize script ONCE against that copy:
   ```
   poetry run python scripts/anonymize_demo_db.py --db ./leagueintel_demo.db
   ```
   It prints the resolved path, a sample of current names, and requires
   typed `yes` confirmation before permanently overwriting
   `teams.owner_name`/`teams.team_name` in place with generated aliases
   (Manager A/Team A, Manager B/Team B, ...) — the same `team_id` always
   gets the same alias across every season.
4. Because the overwrite happens directly in the `teams` table (not a
   view layered on top), every existing query — dashboard pages,
   `run_analysis` functions, and the chatbot's ad-hoc LLM-generated SQL
   — automatically returns aliases when run against the demo copy, with
   zero code changes anywhere. There's no real name left in that file
   for any query to return.
5. Point the app at the demo copy and take your screenshots:
   ```
   DB_PATH=./leagueintel_demo.db poetry run streamlit run src/leagueintel/reporting/home.py
   ```
   Verify every page and a few chatbot questions show aliases before
   recording/screenshotting.
6. `leagueintel_demo.db` is local-only — never committed to git, never
   uploaded to S3. Discard it when done, or keep it; regenerate a fresh
   anonymized copy anytime by repeating steps 2–3 from the current real
   data.


