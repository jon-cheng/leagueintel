# leagueintel working agreement

## My learning goals
This is a deliberate learning project. I want to improve at:
- Python OOP and single responsibility principle
- pytest and test-driven thinking
- Python packaging
- CI/CD with GitHub Actions
- LLM tool use and agentic patterns

Prioritize my understanding over speed. I want to rebuild strong habits.

## How to work with me
- Before writing any code, explain the approach and tradeoffs in
  plain language. Wait for my go-ahead before implementing.
- Propose changes as small, focused diffs — one concern at a time.
- When introducing a pattern for the first time (dataclass, fixture,
  context manager, etc.), explain WHY this pattern over alternatives.
- Never refactor unrelated code in the same change.
- Write tests alongside new logic. Explain what each test is protecting
  against, not just what it does.
- Flag when I'm about to do something that violates single responsibility
  or will be hard to test later.
- When I ask "why", give reasoning first, code second.

## What I don't want
- Large sweeping changes I can't review in one sitting
- Boilerplate I don't understand
- Skipping tests to move faster

## Stack
- Python 3.12, Poetry
- SQLite (local dev), S3 (production)
- Streamlit Community Cloud
- Claude API (tool use, claude-sonnet-4-6)
- ESPN API (espn_api + direct requests)
- boto3, Plotly, Pydantic, Click, Loguru

## Repo structure
src/leagueintel/
  analytics/     → draft.py, waiver.py (pre-validated pandas)
  ingestion/     → espn.py (API fetchers), parse.py
  reporting/     → dashboard.py, chatbot.py, playoff_bracket.py
                    pages/Chat.py
  storage/       → database.py, writer.py, views.py
  config.py      → single source of truth for constants

## Key architecture decisions
- DEFAULT_DB_PATH from env var (local) or /tmp (Streamlit Cloud)
- S3 bucket: leagueintel-data/leagueintel.db (us-west-2)
- Chatbot client must be lazy (_get_client()) — not module-level
- run_analysis for complex validated queries (not query_db)
- NON_STARTING_SLOTS = ['BE', 'IR'] — critical for points calculation
- ALL_SEASONS = range(2019, CURRENT_YEAR) — rich data starts 2019
- teams table has data from 2014 (league founding)

## Known bugs / deferred
- COALESCE(drop_week, 18) sentinel slightly wrong pre-2021

## Testing
poetry run pytest -v
poetry run pytest tests/reporting/test_chatbot_throttling.py -v

## Deployment
Streamlit Community Cloud → src/leagueintel/reporting/dashboard.py
S3 → leagueintel-data/leagueintel.db (us-west-2)